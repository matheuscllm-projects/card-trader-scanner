"""B1n — revisão independente do B1m (exit code, retomada, ordem do postprocess, defaults silenciosos)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402

FINAL4 = json.loads((REPO_ROOT / "tests" / "fixtures" / "ct" / "final4_live0_rows.json").read_text(encoding="utf-8"))["rows"]


def _o(status, live=None):
    return SimpleNamespace(validation_status=status, live_price_brl=live)


# ───────── 1) exit code por combinação ─────────
@pytest.mark.parametrize("opps,code", [
    ([], 0),
    ([_o("NOT_VALIDATED")], 0),
    ([_o("VALIDATED_REAL", 10.0), _o("PRECO_INVALIDO")], 0),                 # há live válido
    ([_o("STALE"), _o("STALE")], 0),                                         # tudo STALE = resultado legítimo
    ([_o("NAO_CONFIRMAVEL"), _o("STALE")], 0),
    ([_o("PRECO_INVALIDO"), _o("PRECO_INVALIDO")], 3),
    ([_o("PRECO_INVALIDO"), _o("STALE")], 3),
    ([_o("VALIDATED_REAL", 0.0)], 3),                                        # VALIDATED_* com live inválido
    ([_o("VALIDATED_MARKUP", None), _o("STALE")], 3),
    ([_o("API_ERROR"), _o("API_ERROR")], 2),                                 # falha operacional, não "preço inválido"
    ([_o("API_ERROR"), _o("STALE")], 0),
])
def test_validation_exit_code_matrix(opps, code):
    assert sc.validation_exit_code(opps) == code


def test_exit_messages_are_distinct():
    assert "preço live" in sc.validation_exit_message(3) and "API" in sc.validation_exit_message(2)
    assert "preço live" not in sc.validation_exit_message(2)


@pytest.mark.parametrize("ps1", ["run_weekly_local.ps1", "run_priority_scan.ps1"])
def test_launchers_still_run_postprocess_when_exit_2_or_3_and_xlsx_exists(ps1):
    t = (REPO_ROOT / "scripts" / ps1).read_text(encoding="utf-8")
    i = t.index("$scannerExit -in 2, 3")
    block = t[i:i + 900]
    assert "Test-Path -LiteralPath $rawOut" in block[:120] and "elseif ($scannerExit -ne 0)" in block


# ───────── 2) retomada: VALIDATED_* com live inválido no checkpoint é descartado ─────────
def _rec(**k):
    r = {"validation_status": "VALIDATED_REAL", "live_price_brl": 345.36, "offer_price_brl": 293.78,
         "ref_brl": 1000.0, "validated_at": "2026-11-24T15:00:00-03:00"}
    r.update(k)
    return r


def _opp(price=293.78, ref=1000.0):
    from test_b1_wiring import _opp as mk
    o = mk()
    o.ct_price_brl, o.tcg_market_brl = price, ref
    return o


@pytest.mark.parametrize("live", [0.0, None, -1.0, float("nan"), float("inf"), "x"])
def test_checkpoint_record_validated_with_invalid_live_does_not_match(live):
    assert sc.validation_record_matches(_opp(), _rec(live_price_brl=live)) is False


def test_checkpoint_record_with_valid_live_still_matches_and_non_validated_records_are_unaffected():
    assert sc.validation_record_matches(_opp(), _rec()) is True
    assert sc.validation_record_matches(_opp(), _rec(validation_status="STALE", live_price_brl=None)) is True


# ───────── 3) postprocess: preço não validado vem ANTES dos cortes de margem e do ramo SEM REF ─────────
def _final4_df():
    return pp.enrich_df(pd.DataFrame(FINAL4))


def test_final4_rows_with_live_zero_are_revisar_preco_nao_validado_not_sem_ref():
    df = _final4_df()
    assert len(df) == 3
    for _, row in df.iterrows():
        d, why = pp.classify_decision(row, pp.DecisionConfig())
        assert d == "REVISAR" and "preço não validado" in why, (d, why)
        assert not str(row.get("sem_margem_motivo") or "").strip()      # margem do preço do scan, com compra_inclui_hub=False


@pytest.mark.parametrize("status,live", [("PRECO_INVALIDO", None), ("VALIDATED_REAL", 0.0), ("VALIDATED_MARKUP", -3.0)])
def test_preco_nao_validado_wins_over_margin_cuts_and_sem_ref(status, live):
    for nm in (0.95, 0.10, -0.50, float("nan")):
        row = pd.Series({"net_margin": nm, "lucro_liq": 100.0, "validation_status": status, "live_brl": live,
                         "compra_inclui_hub": False, "ref_compativel": "Sim",
                         "sem_margem_motivo": "compra invalida (live_brl <= 0)"})
        d, why = pp.classify_decision(row, pp.DecisionConfig())
        assert d == "REVISAR" and "preço não validado" in why, (status, nm, d, why)


def test_validated_with_no_price_at_all_is_still_sem_ref():
    """Sem preço live E sem preço cru do scan (nada a comparar): continua SEM REF (não é falha de LIVE medida)."""
    row = pd.Series({"net_margin": float("nan"), "lucro_liq": float("nan"), "validation_status": "VALIDATED_REAL",
                     "live_brl": float("nan"), "compra_inclui_hub": False, "ref_compativel": "Sim",
                     "sem_margem_motivo": "compra invalida (live_brl <= 0)"})
    assert pp.classify_decision(row, pp.DecisionConfig())[0] == "SEM REF"
