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


# ═════════ 4) defaults silenciosos: preço, graded, campos obrigatórios, moeda, canário ═════════
import logging  # noqa: E402

REAL_L = json.loads((REPO_ROOT / "tests" / "fixtures" / "ct" / "blueprint_117903_listings.json").read_text(encoding="utf-8"))["listings"]
BP = {117903: {"name": "Typhlosion", "fixed_properties": {"pokemon_rarity": "Holo Rare"}}}


def _ps():
    from test_b1_wiring import _plain_scanner
    s = _plain_scanner()
    s.language, s.exclude_graded, s.min_price_usd = "en", True, 0.0
    s.stats = {"skipped_exotic_currency": 0}
    return s


def _raw(**ch):
    r = json.loads(json.dumps(REAL_L[0]))
    for k, v in ch.items():
        if v is KeyError:
            r.pop(k, None)
        else:
            r[k] = v
    return r


@pytest.mark.parametrize("price", [{"cents": 0, "currency": "BRL"}, {"currency": "BRL"}, {"cents": None, "currency": "BRL"},
                                   {"cents": float("nan"), "currency": "BRL"}, {"cents": -5, "currency": "BRL"}, {}, KeyError])
def test_scan_offer_without_valid_price_is_dropped_and_counted(price):
    s = _ps()
    assert s._parse_listing(_raw(price=price), BP) is None
    assert s.stats["skipped_invalid_price"] == 1


def test_missing_mandatory_keys_drop_the_offer_into_the_unexpected_payload_counter():
    s = _ps()
    s._pl_missing = {}
    assert s._parse_listing(_raw(graded=KeyError), BP) is None          # graded ausente NÃO vira False em silêncio
    raw = _raw()
    raw["properties_hash"].pop("condition")
    assert s._parse_listing(raw, BP) is None
    raw = _raw()
    raw["properties_hash"].pop("pokemon_language")
    assert s._parse_listing(raw, BP) is None
    raw = _raw()
    raw["user"].pop("username")
    assert s._parse_listing(raw, BP) is None
    assert s._pl_missing == {"graded": 1, "condition": 1, "pokemon_language": 1, "user.username": 1}
    assert s.stats["skipped_unexpected_payload"] == 4


def test_optional_keys_use_documented_safe_defaults_and_are_counted():
    s = _ps()
    s._pl_missing = {}
    raw = _raw()
    raw["properties_hash"].pop("pokemon_reverse", None)
    raw["user"].pop("can_sell_via_hub", None)
    raw["user"].pop("user_type", None)
    l = s._parse_listing(raw, BP)
    assert l is not None and l.foil is False and l.seller_can_sell_via_hub is False and l.seller_user_type == "private"
    assert s._pl_defaults == {"pokemon_reverse": 1, "user.can_sell_via_hub": 1, "user.user_type": 1}


def test_unsupported_currency_has_its_own_counter_and_warning(caplog):
    s = _ps()
    with caplog.at_level(logging.WARNING, logger=sc.log.name):
        assert s._parse_listing(_raw(price={"cents": 1000, "currency": "GBP"}), BP) is None
    assert s.stats["skipped_exotic_currency"] == 1
    assert any("moeda não suportada" in r.getMessage() and "GBP" in r.getMessage() for r in caplog.records)


def test_ingest_closes_the_funnel_sum():
    s = _ps()
    raws = [_raw(), _raw(id=2, price={"cents": 0, "currency": "BRL"}), _raw(id=3, graded=KeyError),
            _raw(id=4, blueprint_id=999), _raw(id=5, price={"cents": 900, "currency": "GBP"}),
            _raw(id=6, graded=True), _raw(id=7)]                       # 7 = mesmo vendedor/uid de 1 (dedup)
    best, _ = s._ingest_raw_listings(raws, BP)
    st = s.stats
    assert len(best) == 1
    closed = (len(best) + st["listings_deduped"] + st["listings_rejected_by_filters"] + st["listings_no_blueprint"]
              + st["skipped_invalid_price"] + st["skipped_unexpected_payload"] + st["skipped_exotic_currency"])
    assert closed == len(raws), (closed, st)
    lines = "\n".join(s.funnel_summary_lines())
    assert "sem preço CT válido: 1" in lines and "payload inesperado: 1" in lines and "moeda não suportada: 1" in lines


def test_canary_set_with_many_missing_keys_is_operational_failure_not_no_coverage(caplog):
    s = _ps()
    s._pl_missing = {"graded": 30}
    with caplog.at_level(logging.ERROR, logger=sc.log.name):
        assert s._check_payload_canary("uf", total=100) is True
    assert any("formato da API mudou: chave graded ausente em 30/100" in r.getMessage() for r in caplog.records)
    assert s._set_status == "operational_failure" and s._set_reason == "api_format_changed_graded"
    s2 = _ps()
    s2._pl_missing = {"graded": 1}
    assert s2._check_payload_canary("uf", total=100) is False


# ───────── validação per-blueprint: graduado recusado, variante exata, moeda não suportada ─────────
def _sc_val():
    from test_b1m import _scanner, _opp_for
    return _scanner(), _opp_for("PokePosta-Store")


def test_validation_refuses_a_graded_listing():
    s, o = _sc_val()
    l = dict(REAL_L[0], graded=True)
    s._enrich_validation(o, [l])
    assert o.validation_status == "STALE" and o.live_price_brl is None


def test_validation_requires_graded_key_to_be_present_false():
    s, o = _sc_val()
    l = {k: v for k, v in REAL_L[0].items() if k != "graded"}
    s._enrich_validation(o, [l])
    assert o.validation_status == "STALE" and o.live_price_brl is None


def test_validation_unsupported_currency_has_its_own_status():
    s, o = _sc_val()
    s._enrich_validation(o, [dict(REAL_L[0], price={"cents": 1000, "currency": "GBP"})])
    assert o.validation_status == "MOEDA_NAO_SUPORTADA" and "GBP" in o.validation_reason
    assert o.live_price_brl is None


# ═════════ 5) TOP 5 com log.exception; rótulos de tier neutros ═════════
def test_top5_failure_is_logged_with_traceback_not_a_mute_warning(caplog, monkeypatch):
    src = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")
    assert "log.exception(" in src[src.index("print_top_opportunities(opps_by_net, validated="):][:800]


@pytest.mark.parametrize("markup,status", [(0.0, "VALIDATED_REAL"), (0.01, "VALIDATED_REAL"), (0.06, "VALIDATED_MARKUP"),
                                           (0.1756, "VALIDATED_MARKUP"), (0.40, "VALIDATED_MARKUP"), (0.60, "PRICE_CHANGED")])
def test_markup_labels_are_neutral_interval_descriptions(markup, status):
    label, st = sc.classify_markup(markup)
    assert st == status
    for bad in ("VAT", "Hub", "Real (sem markup)", "Anômalo"):
        assert bad not in label, (markup, label)
    assert "LIVE" in label and "scan" in label
