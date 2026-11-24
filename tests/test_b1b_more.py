"""B1b (parte 2): cobertura, holo inconclusivo, baixas, chase fora de score."""
from __future__ import annotations

import dataclasses
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_scanner as sc  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_set_outcomes import _cards, _run  # noqa: E402
from test_tcgcsv_fallback import _fake_groups, _fake_prices, _fake_products, _provider_with, _scanner_with  # noqa: E402

SRC = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "recover_from_checkpoint.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _noref_opp(**kw):
    l = dataclasses.replace(_cards(1, set_code="n1")[0], **kw)
    return sc.Opportunity(listing=l, tcg_market_usd=10.0, tcg_market_brl=50.0, ct_price_brl=20.0,
                          margin_pct=0.6, margin_brl=30.0, estimated_shipping_brl=0.5, net_margin_pct=0.5)


# ───────────── 9: cobertura (corte por misses) ─────────────
def _tcgcsv_primary_scanner(listings, rows, max_misses=40):
    tcgcsv = _provider_with(_fake_groups(), _fake_products({k: f"{k:03d}/100" for k in range(1, 800)}),
                            _fake_prices(rows))
    scanner = _scanner_with({}, tcgcsv, listings, tcgcsv_fallback=False, max_misses=max_misses)
    scanner.pricing = tcgcsv
    return scanner


def test_batch_provider_never_leaves_not_reached_even_with_40_misses_of_one_card(tmp_path, monkeypatch):
    # numeros reais do mew: 824 ofertas, 40 de UMA carta fora do padrao logo no inicio
    base = _cards(1, set_code="asc")[0]
    odd = [dataclasses.replace(base, product_id=900_000 + i, blueprint_id=999_999,
                               seller_username=f"s{i}", collector_number="999/100",
                               card_name="Mew ex Gold Metal") for i in range(40)]
    rest = _cards(784, set_code="asc")
    listings = odd + rest
    scanner = _tcgcsv_primary_scanner(listings, [(k, "Holofoil", 50.0) for k in range(1, 785)])
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert "nao_alcancado" not in {r["reason"] for r in scanner.unpriced_rows}
    assert len(opps) == 784 and len(scanner.unpriced_rows) == 40
    assert done[0]["status"] == "complete_with_unpriced" and skip == {}
    assert len(opps) + len(scanner.unpriced_rows) + len(scanner.noref_rows) == 824


def test_misses_are_counted_per_distinct_card_not_per_offer(tmp_path, monkeypatch):
    base = _cards(1, set_code="asc")[0]
    odd = [dataclasses.replace(base, product_id=900_000 + i, blueprint_id=999_999,
                               seller_username=f"s{i}", collector_number="999/100") for i in range(45)]
    rest = _cards(5, set_code="asc")
    listings = odd + rest
    prices = {("asc", l.collector_number): 50.0 for l in rest}
    scanner = _scanner_with(prices, None, listings, tcgcsv_fallback=False, max_misses=40)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 5                      # 45 misses de UMA carta = 1 miss
    assert not [r for r in scanner.unpriced_rows if r["reason"] == "nao_alcancado"]


def test_cut_with_not_reached_is_not_complete_it_is_try_again(tmp_path, monkeypatch):
    listings = _cards(60, set_code="asc")
    prices = {("asc", l.collector_number): 50.0 for l in listings[:5]}
    scanner = _scanner_with(prices, None, listings, tcgcsv_fallback=False, max_misses=40)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert done[0]["status"] == "operational_failure"
    assert done[0]["reason"].startswith("coverage_interrupted_")
    assert any("tentar de novo" in ln for ln in scanner.run_summary_lines())
    assert skip == {}
    assert len(opps) + len(scanner.unpriced_rows) + len(scanner.noref_rows) == 60


# ───────────── 8: motivo de holo inconclusivo ─────────────
def _twm_provider(rows):
    groups = [{"groupId": 23473, "name": "SV06: Twilight Masquerade", "abbreviation": "TWM",
               "publishedOn": "2024-05-24T00:00:00"}]
    prov = _provider_with(groups, _fake_products({1: "106/167"}), _fake_prices(rows))
    assert prov.prefill_set("twm", ["sv6"], "Twilight Masquerade")
    return prov


def test_inconclusive_rarity_is_explained_in_the_reason_without_changing_the_rule():
    prov = _twm_provider([(1, "Holofoil", 5.0), (1, "Normal", 2.0)])
    assert prov.market_price_usd("Greninja ex", "twm", "106/167", rarity="Promo") is None   # duas impressões: não se presume
    assert prov.last_ref_status == cv.INCOMPATIVEL                     # regra exata intacta
    assert "inconclusiv" in prov.last_ref_reason and "holofoil" in prov.last_ref_reason
    p2 = _twm_provider([(1, "Holofoil", 5.0)])
    assert p2.market_price_usd("X", "twm", "106/167", rarity="Common") is None
    assert "inconclusiv" not in p2.last_ref_reason


# ───────────── 6: baixas ─────────────
def test_price_logic_version_has_a_single_owner():
    assert not re.search(r'^PRICE_LOGIC_VERSION\s*=\s*"', SRC, re.M)
    assert sc.PRICE_LOGIC_VERSION == cv.PRICE_LOGIC_VERSION


def test_validation_key_includes_edition_and_reverse():
    a = _noref_opp(first_edition=False, foil=False)
    b = _noref_opp(first_edition=True, foil=False)
    c = _noref_opp(first_edition=False, foil=True)
    assert len({sc.validation_key(a), sc.validation_key(b), sc.validation_key(c)}) == 3


@pytest.mark.parametrize("raw,expected", [(True, True), (False, False), ("false", False), ("False", False),
                                          ("true", True), ("0", False), (0, False), (1, True), (None, False)])
def test_first_edition_reading_is_robust_to_strings(raw, expected):
    assert sc.to_bool(raw) is expected
    s = sc.Scanner.__new__(sc.Scanner)
    s.usd_brl, s.eur_brl, s.stats = 5.0, 5.9, {"skipped_exotic_currency": 0}
    rawo = {"id": 1, "blueprint_id": 1, "quantity": 1, "price": {"cents": 100, "currency": "BRL"},
            "user": {"username": "u"}, "expansion": {"code": "n1"}, "graded": False,
            "properties_hash": {"condition": "Near Mint", "pokemon_language": "en", "first_edition": raw, "pokemon_reverse": raw}}
    l = s._parse_listing(rawo, {1: {"name": "X", "fixed_properties": {}}})
    assert l.first_edition is expected and l.foil is expected


def test_margin_not_computable_records_the_right_set_code(tmp_path, monkeypatch):
    listings = _cards(1, set_code="asc")
    listings[0] = dataclasses.replace(listings[0], set_code="OTHER")   # codigo da oferta != set do scan
    scanner = _scanner_with({("OTHER", listings[0].collector_number): 50.0}, None, listings,
                            tcgcsv_fallback=False, max_misses=0)
    scanner.usd_brl = float("nan")
    _run(scanner, listings, tmp_path, monkeypatch, code="asc")
    assert [r["set"] for r in scanner.noref_rows] == ["asc"]
    assert scanner.noref_rows[0]["status"] == "MARGEM_NAO_CALCULAVEL"


def test_recovery_of_old_checkpoint_labels_unknown_edition(tmp_path):
    from dataclasses import asdict
    rec = _load("rec")
    d = asdict(_noref_opp())
    for k in ("edition", "finish", "ref_compatible", "validated_at", "validation_reason"):
        d.pop(k)
    d["listing"].pop("first_edition"), d["listing"].pop("first_edition_known")
    o = rec._reconstruct_opportunity(d)
    assert o.edition is None and o.finish is None and o.ref_compatible is False
    out = tmp_path / "x.xlsx"
    sc.export_xlsx([o], {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    from openpyxl import load_workbook
    ws = load_workbook(out)["Oportunidades"]
    head = [c.value for c in ws[1]]
    row = [c.value for c in ws[2]]
    assert row[head.index("Edição")] in (None, "") and row[head.index("Acabamento")] in (None, "")


def test_parse_checkpoint_reads_noref_and_new_fields(tmp_path):
    rec = _load("rec2")
    cp = sc.CheckpointWriter(tmp_path / "cp.jsonl", every_n=10)
    o = _noref_opp(first_edition=True)
    o.edition, o.finish, o.ref_compatible = cv.ED_1ST, cv.FIN_HOLO, True
    cp.write_opportunity(o)
    cp.write_noref({"set": "n1", "card": "X", "number": "1", "motivo": "m", "edicao": "1st Edition",
                    "acabamento": "Holo", "ct_price_brl": 1.0, "link": "https://x", "chaves": "a",
                    "tcg_url": "", "source": "tcgcsv", "status": cv.INCOMPATIVEL, "set_name": "N",
                    "rarity": "", "currency": "BRL", "qty": 1, "seller": "s"})
    cp.close()
    opps, _, summary = rec.parse_checkpoint(tmp_path / "cp.jsonl")
    assert opps[0].edition == cv.ED_1ST and opps[0].finish == cv.FIN_HOLO
    assert opps[0].ref_compatible is True and opps[0].listing.first_edition is True
    assert len(summary["noref"]) == 1 and summary["noref"][0]["card"] == "X"


def test_claude_md_has_no_hub_fee_or_margin_basis_contradictions():
    t = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "tem **default 0.0**" not in t
    assert "só `(revenda − compra)/compra`" not in t
    assert "mesma escada de variante" not in t


# ───────────── 7: chase fora de qualquer score ─────────────
def test_fundamental_score_does_not_use_chase():
    import cardtrader_postprocess as pp
    import pandas as pd
    base = {"net_margin": 0.35, "lucro_liq": 120.0}
    a = pp.fundamental_score(pd.Series({**base, "chase_tier": "TOP"}))
    b = pp.fundamental_score(pd.Series({**base, "chase_tier": "BULK"}))
    assert a == b
