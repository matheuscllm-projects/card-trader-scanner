"""B1o — 2ª devolução da revisão independente: funil em todo caminho, launchers com XLSX deste run, reverse ausente,
canário em set pequeno, matriz de exit code com parciais, coluna LIVE só com preço validado. Testes PELO FLUXO."""
from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
from test_language_flag import _stub  # noqa: E402

REAL = json.loads((REPO_ROOT / "tests" / "fixtures" / "ct" / "blueprint_117903_listings.json").read_text(encoding="utf-8"))["listings"]
BP = [{"id": 117903, "name": "Typhlosion", "fixed_properties": {"pokemon_rarity": "Holo Rare"}}]
EXP = {"id": 1507, "code": "uf", "name": "EX Unseen Forces"}


def _raw(i, **drop):
    r = copy.deepcopy(REAL[0])
    r["id"] = 1000 + i
    r["user"]["username"] = f"seller{i}"
    r["price"] = {"cents": 10000 + i, "currency": "USD"}
    for k in drop.get("top", ()):
        r.pop(k, None)
    for k in drop.get("props", ()):
        r["properties_hash"].pop(k, None)
    r["properties_hash"]["condition"] = r["properties_hash"].get("condition", "Near Mint") if "condition" not in drop.get("props", ()) else None
    if "condition" not in drop.get("props", ()):
        r["properties_hash"]["condition"] = "Near Mint"
    else:
        r["properties_hash"].pop("condition", None)
    return r


def _flow(raws):
    s = _stub("en")
    s.ct = MagicMock()
    s.ct.list_blueprints.return_value = BP
    s.ct.list_listings_by_expansion.return_value = raws
    s.pricing = MagicMock()
    s.pricing.market_price_usd.return_value = None
    s.min_price_usd = 0.0
    s.mass_pricing_failure_min_sample, s.mass_pricing_failure_threshold = 20, 0.5
    s.breaker, s.ptcg_alt, s.max_ref_age_days = None, None, 7.0
    list(s.scan_expansion(EXP))
    return s


def _closed(st):
    parts = ("listings_after_filters", "listings_canary_discarded", "listings_deduped", "listings_rejected_by_filters",
             "listings_no_blueprint", "skipped_invalid_price", "skipped_unexpected_payload", "skipped_exotic_currency")
    return sum(st.get(k, 0) for k in parts), st.get("listings_fetched", 0)


# ───────── 1) funil fecha também quando o canário dispara ─────────
def test_canary_flow_keeps_the_funnel_closed_with_its_own_parcel():
    raws = [_raw(i) for i in range(60)] + [_raw(100 + i, top=("graded",)) for i in range(40)]
    s = _flow(raws)
    assert s._set_status == "operational_failure" and s._set_reason == "api_format_changed_graded"
    st = s.stats
    assert st["listings_fetched"] == 100 and st["skipped_unexpected_payload"] == 40
    assert st["listings_canary_discarded"] == 60 and st.get("listings_after_filters", 0) == 0
    got, total = _closed(st)
    assert got == total == 100
    assert "descartadas pelo canário de formato: 60" in "\n".join(s.funnel_summary_lines())


def test_normal_flow_keeps_the_funnel_closed():
    s = _flow([_raw(i) for i in range(5)] + [_raw(50, top=("price",))])
    got, total = _closed(s.stats)
    assert got == total == 6 and s.stats["skipped_invalid_price"] == 1


# ───────── 4) canário em set pequeno / tudo descartado por payload nunca é "complete" ─────────
def test_small_set_all_listings_missing_a_key_is_operational_failure():
    s = _flow([_raw(i, top=("graded",)) for i in range(10)])
    assert s._set_status == "operational_failure" and s._set_reason == "api_format_changed_graded"


def test_single_listing_missing_a_key_is_operational_failure():
    s = _flow([_raw(0, top=("graded",))])
    assert s._set_status == "operational_failure"


def test_set_where_every_offer_is_dropped_by_different_missing_keys_is_not_complete():
    s = _flow([_raw(i, top=("graded",)) for i in range(5)] + [_raw(10 + i, props=("condition",)) for i in range(5)])
    assert s._set_status == "operational_failure" and s._set_reason.startswith("api_format_changed_")


def test_small_set_with_one_bad_listing_among_good_ones_is_not_a_canary():
    s = _flow([_raw(i) for i in range(9)] + [_raw(50, top=("graded",))])
    assert s._set_status != "operational_failure"


# ───────── 3) pokemon_reverse ausente: oferta segue como INFERIDO, nunca declarada ─────────
def test_missing_pokemon_reverse_is_kept_as_inferred_with_reason_and_counted_in_the_funnel():
    s = _stub("en")
    s.stats = {"skipped_exotic_currency": 0}
    raw = _raw(1, props=("pokemon_reverse",))
    best, _ = s._ingest_raw_listings([raw], {117903: BP[0]})
    l = next(iter(best.values()))
    assert l.reverse_unknown is True and l.foil is False
    assert s._pl_defaults == {"pokemon_reverse": 1}
    s.funnel_defaults_total = None
    assert "pokemon_reverse 1" in "\n".join(s.funnel_summary_lines())


def test_inferred_note_is_attached_to_the_opportunity():
    s = _stub("en")
    s.stats = {"skipped_exotic_currency": 0}
    l = next(iter(s._ingest_raw_listings([_raw(1, props=("pokemon_reverse",))], {117903: BP[0]})[0].values()))
    prov = MagicMock()
    prov.last_ref_inferred = ""
    prov.last_variant_used = "normal"
    assert "campo pokemon_reverse ausente no payload" in s._inferred_note(l, prov)
    ok = next(iter(s._ingest_raw_listings([_raw(2)], {117903: BP[0]})[0].values()))
    assert s._inferred_note(ok, prov) == ""


# ───────── 5) matriz do exit code com parciais e códigos que não colidem ─────────
def _o(status, live=None):
    return SimpleNamespace(validation_status=status, live_price_brl=live)


@pytest.mark.parametrize("opps,code", [
    ([], 0),
    ([_o("STALE"), _o("STALE")], 0),
    ([_o("VALIDATED_REAL", 10.0), _o("PRECO_INVALIDO")], 0),
    ([_o("PRECO_INVALIDO"), _o("STALE")], 21),
    ([_o("VALIDATED_REAL", 0.0)], 21),
    ([_o("API_ERROR"), _o("API_ERROR")], 22),
    ([_o("API_ERROR"), _o("STALE")], 20),                      # falha parcial de API: nunca 0 silencioso
    ([_o("VALIDATED_REAL", 10.0), _o("API_ERROR")], 20),
    ([_o("MOEDA_NAO_SUPORTADA"), _o("MOEDA_NAO_SUPORTADA")], 20),
    ([_o("VALIDATED_MARKUP", 10.0), _o("MOEDA_NAO_SUPORTADA")], 20),
])
def test_exit_code_matrix_with_partials(opps, code):
    assert sc.validation_exit_code(opps) == code


def test_exit_codes_do_not_collide_with_existing_ones():
    codes = {sc.EXIT_VALIDATION_PARTIAL, sc.EXIT_NO_VALID_LIVE_PRICE, sc.EXIT_VALIDATION_API_FAILED}
    assert codes == {20, 21, 22}
    assert codes.isdisjoint({0, 1, 2, 97, 98, 99, 130})
    assert "TABELA DE CÓDIGOS DE SAÍDA" in (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")


def test_validation_summary_counts_api_errors_and_unsupported_currency(caplog):
    from test_b1m import _scanner, _opp_for
    s = _scanner()
    s.ct = MagicMock()
    s.language = "en"
    a, b, c = _opp_for("PokePosta-Store", 345.0), _opp_for("Derek Lankford", 345.0), _opp_for("PokePosta-Store", 345.0)
    c.listing = c.listing.__class__(**{**c.listing.__dict__, "blueprint_id": 5})
    b.listing = b.listing.__class__(**{**b.listing.__dict__, "blueprint_id": 6})
    gbp = [dict(l, price={"cents": 1000, "currency": "GBP"}) for l in REAL]

    def per_bp(bp, language=None):
        if bp == 5:
            raise RuntimeError("boom")
        if bp == 6:
            return {"6": gbp}
        return {"117903": REAL}
    s.ct.list_listings_by_blueprint.side_effect = per_bp
    s.stats = {}
    with caplog.at_level(logging.INFO, logger=sc.log.name):
        s.validate_per_blueprint([a, b, c])
    assert s.stats["v2_api_error"] == 1 and s.stats["v2_moeda_nao_suportada"] == 1
    assert any("1 erro de API" in r.getMessage() and "1 moeda não suportada" in r.getMessage() for r in caplog.records)


# ───────── 2) launchers: só segue com XLSX DESTE run (função testada de verdade) ─────────
DECISION = REPO_ROOT / "scripts" / "scanner_exit_decision.ps1"


def _decide(exit_code, raw_exists, raw_age_s, tmp_path):
    raw = tmp_path / "raw.xlsx"
    if raw_exists:
        raw.write_bytes(b"x")
        t = time.time() - raw_age_s
        os.utime(raw, (t, t))
    run_start = "(Get-Date).AddSeconds(-60)"          # o run começou há 60 s
    cmd = f". '{DECISION}'; Get-PostprocessDecision -ExitCode {exit_code} -RawOut '{raw}' -RunStart {run_start}"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("code,exists,age,expect", [
    (0, True, 10, "run"),
    (20, True, 10, "run"), (21, True, 10, "run"), (22, True, 10, "run"),     # XLSX escrito DURANTE este run
    (21, True, 3600, "abort"),                                                # XLSX de run ANTERIOR
    (2, True, 10, "abort"),                                                   # exit 2 = run-guard/args: nada escrito
    (2, True, 3600, "abort"),
    (21, False, 0, "abort"),
    (1, True, 10, "abort"), (130, True, 10, "abort"),
])
def test_launcher_decision_runs_the_real_powershell_logic(tmp_path, code, exists, age, expect):
    assert _decide(code, exists, age, tmp_path) == expect


@pytest.mark.parametrize("ps1", ["run_weekly_local.ps1", "run_priority_scan.ps1"])
def test_launchers_use_the_decision_function_and_record_the_run_start(ps1):
    t = (REPO_ROOT / "scripts" / ps1).read_text(encoding="utf-8")
    assert "scanner_exit_decision.ps1" in t and "Get-PostprocessDecision" in t and "$runStart" in t
    assert t.index("$runStart = Get-Date") < t.index("& $py @scannerArgs")


# ───────── 6) coluna LIVE só com preço validado; preço usado na conta em coluna própria ─────────
FINAL4 = json.loads((REPO_ROOT / "tests" / "fixtures" / "ct" / "final4_live0_rows.json").read_text(encoding="utf-8"))["rows"]


def test_enrich_df_keeps_live_empty_when_invalid_and_uses_a_separate_purchase_column():
    df = pp.enrich_df(pd.DataFrame(FINAL4))
    assert df["live_brl"].isna().all()                                   # "LIVE" nunca exibe preço não validado
    assert list(df["compra_brl"]) == pytest.approx([293.78, 439.93, 169.75])
    assert not df["compra_inclui_hub"].any()
    for _, r in df.iterrows():
        d, why = pp.classify_decision(r, pp.DecisionConfig())
        assert d == "REVISAR" and "preço não validado" in why
    assert pp._SHEET_RENAME.get("compra_brl") and "compra_brl" in pp._SHEET_COLS
