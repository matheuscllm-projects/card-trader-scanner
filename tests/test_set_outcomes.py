"""Lote 3 (B + C): skip-list só para ausência EFETIVA de cobertura; três
desfechos por set (complete | no_coverage | operational_failure); resgate
tcgcsv para tudo que a fonte principal não precificou; linhas sem preço não
somem; referência leva fonte + data/hora.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import cardtrader_scanner as sc  # noqa: E402
from test_tcgcsv_fallback import (  # noqa: E402
    _fake_groups, _fake_prices, _fake_products, _listing, _provider_with,
    _scanner_with,
)


# ───────────────────────── harness ─────────────────────────
def _run(scanner, listings, tmp_path, monkeypatch, code=None):
    """scan() completo (com checkpoint) sobre `listings`; skip-list em tmp."""
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    scanner.ignore_skip_list = False
    scanner.language = "en"
    scanner.ct.list_blueprints = MagicMock(return_value=[
        {"id": l.blueprint_id, "name": l.card_name} for l in listings])
    scanner.ct.list_listings_by_expansion = MagicMock(return_value=[
        {"id": l.product_id, "blueprint_id": l.blueprint_id} for l in listings])
    by_pid = {l.product_id: l for l in listings}
    scanner._parse_listing = MagicMock(side_effect=lambda raw, idx: by_pid.get(raw["id"]))
    scanner._passes_filters = MagicMock(return_value=True)
    return _scan(scanner, listings[0].set_code if code is None else code, tmp_path)


def _scan(scanner, code, tmp_path):
    cp = sc.CheckpointWriter(tmp_path / "cp.jsonl", every_n=10)
    opps = scanner.scan([{"id": 1, "code": code, "name": "Ascended Heroes"}],
                        checkpoint=cp)
    cp.close()
    recs = [json.loads(x) for x in (tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()]
    done = [r for r in recs if r.get("_type") == "set_complete"]
    skip = {}
    if (tmp_path / "skip.json").exists():
        skip = json.loads((tmp_path / "skip.json").read_text(encoding="utf-8"))["reasons"]
    return opps, done, skip


def _cards(n, set_code="asc"):
    return [_listing(f"Card {k}", f"{k:03d}/100", set_code=set_code, rarity="Holo Rare")
            for k in range(1, n + 1)]


def _tcgcsv_for(numbers):
    products = _fake_products({k: f"{k:03d}/100" for k in numbers})
    prices = _fake_prices([(k, "Holofoil", 50.0 + k) for k in numbers])
    return _provider_with(_fake_groups(), products, prices)


def _stub_scanner(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    s = sc.Scanner.__new__(sc.Scanner)
    s.ct = MagicMock()
    s.pricing = MagicMock()
    s.cache = MagicMock()
    s.language = "en"
    s.min_price_usd = 10.0
    s.exclude_graded = True
    s.per_set_timeout_s = 480
    s.ignore_skip_list = False
    s.max_consecutive_misses = 0
    s.tcgcsv = None
    s.tcgcsv_fallback = False
    s.heartbeat = lambda *_: None
    s._checkpoint = None
    s.usd_brl = 5.0
    s.eur_brl = 5.9
    s.stats = {k: 0 for k in (
        "expansions_scanned", "listings_fetched", "listings_after_filters",
        "expansions_skipped_by_list", "expansions_timed_out", "pricing_failures",
        "expansions_mass_pricing_abort", "expansions_no_coverage_abort")}
    s.mass_pricing_failure_threshold = 0.50
    s.mass_pricing_failure_min_sample = 20
    return s


# ───────────────────────── B: falha operacional NUNCA vai à skip-list ─────────
def test_ct_timeout_is_operational_failure_not_skiplisted(tmp_path, monkeypatch):
    s = _stub_scanner(monkeypatch, tmp_path)
    s.ct.list_blueprints.side_effect = TimeoutError("deadline")
    _, done, skip = _scan(s, "cg", tmp_path)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"].startswith("ct_blueprints_timeout_"), done


def test_network_error_is_operational_failure_not_skiplisted(tmp_path, monkeypatch):
    s = _stub_scanner(monkeypatch, tmp_path)

    def boom(exp):
        raise requests.ConnectionError("CT: esgotou 3 tentativas")
        yield  # pragma: no cover

    s.scan_expansion = boom
    _, done, skip = _scan(s, "aq", tmp_path)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"] == "network_error_ConnectionError", done


def test_unexpected_error_is_operational_failure_not_skiplisted(tmp_path, monkeypatch):
    s = _stub_scanner(monkeypatch, tmp_path)

    def boom(exp):
        raise ValueError("schema drift")
        yield  # pragma: no cover

    s.scan_expansion = boom
    _, done, skip = _scan(s, "aq", tmp_path)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure"
    assert done[0]["reason"] == "unexpected_error_ValueError"


def test_mass_pricing_failure_is_operational_not_skiplisted(tmp_path, monkeypatch):
    listings = _cards(25)
    scanner = _scanner_with({}, _tcgcsv_for([]), listings, tcgcsv_fallback=False, max_misses=0)
    scanner.pricing.market_price_usd.side_effect = requests.Timeout("500 persistente")
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"].startswith("mass_pricing_failure_"), done
    assert done[0]["unpriced"] == 25, done  # nenhuma linha some: todas contadas


def test_per_set_timeout_in_pricing_loop_is_operational(tmp_path, monkeypatch):
    listings = _cards(4)
    scanner = _scanner_with({}, _tcgcsv_for([]), listings, tcgcsv_fallback=False, max_misses=0)
    scanner.per_set_timeout_s = 0.0001
    scanner.pricing.market_price_usd.side_effect = lambda *a, **k: (__import__("time").sleep(0.01), None)[1]
    _, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"].startswith("per_set_timeout_"), done


def test_no_coverage_cap_skiplists_only_when_nothing_was_priced(tmp_path, monkeypatch):
    # nada precificado + cap atingido = ausência efetiva de cobertura → skip-list
    listings = _cards(6)
    scanner = _scanner_with({}, _tcgcsv_for([]), listings, tcgcsv_fallback=False, max_misses=2)
    _, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert done[0]["status"] == "no_coverage", done
    assert skip["asc"]["reason"].startswith("no_coverage_"), skip
    assert done[0]["unpriced"] == 6


def test_partial_coverage_is_not_skiplisted(tmp_path, monkeypatch, ):
    # houve hit: o set tem cobertura parcial → NÃO vai pra skip-list
    listings = _cards(6)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([]), listings,
                            tcgcsv_fallback=False, max_misses=2)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {}, skip
    assert done[0]["status"] == "no_coverage", done
    assert done[0]["unpriced"] == 5, done


def test_operational_failures_listed_in_run_summary(tmp_path, monkeypatch):
    s = _stub_scanner(monkeypatch, tmp_path)
    s.ct.list_blueprints.side_effect = TimeoutError("deadline")
    _scan(s, "cg", tmp_path)
    lines = "\n".join(s.run_summary_lines())
    assert "tentar de novo" in lines and "cg" in lines, lines
    assert "cg" in s.stats["sets_operational_failure"], s.stats


# ───────────────────────── C: resgate tcgcsv ─────────────────────────
def test_rescue_after_cap_prices_all_rows_and_labels_source(tmp_path, monkeypatch):
    listings = _cards(6)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for(range(1, 7)),
                            listings, max_misses=2)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 6, [o.listing.card_name for o in opps]  # B4: contagem de linhas
    by = {o.listing.card_name: o.price_source for o in opps}
    assert by["Card 1"] == "pokemontcg"
    assert all(by[f"Card {k}"] == "tcgcsv" for k in range(2, 7)), by
    assert skip == {}, skip
    assert done[0]["status"] == "complete" and done[0]["unpriced"] == 0, done
    assert "tcgcsv_rescue" in (done[0]["note"] or ""), done


def test_rescue_covers_end_of_set_misses_even_with_prior_hits(tmp_path, monkeypatch):
    # cap nunca atingido (misses só no fim) — antes só resgatava se hits == 0
    listings = _cards(4)
    scanner = _scanner_with({("asc", "001/100"): 100.0, ("asc", "002/100"): 100.0},
                            _tcgcsv_for([3, 4]), listings, max_misses=40)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    by = {o.listing.card_name: o.price_source for o in opps}
    assert len(opps) == 4 and by["Card 3"] == "tcgcsv" and by["Card 4"] == "tcgcsv", by
    assert done[0]["status"] == "complete", done


def test_pricing_exception_rows_are_rescued_not_lost(tmp_path, monkeypatch):
    listings = _cards(3)
    scanner = _scanner_with({}, _tcgcsv_for([1, 2, 3]), listings, max_misses=40)

    def flaky(card_name, set_code, num, foil=False, rarity=None):
        if num == "002/100":
            raise requests.Timeout("500")
        return 100.0

    scanner.pricing.market_price_usd.side_effect = flaky
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    by = {o.listing.card_name: o.price_source for o in opps}
    assert len(opps) == 3 and by["Card 2"] == "tcgcsv", by


def test_partial_rescue_is_never_complete_and_rows_are_kept(tmp_path, monkeypatch):
    listings = _cards(4)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([2, 3]),
                            listings, max_misses=40)  # Card 4 sem preço em nenhuma fonte
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 3
    assert done[0]["status"] == "no_coverage" and done[0]["unpriced"] == 1, done
    kept = [r for r in scanner.unpriced_rows if r["card"] == "Card 4"]
    assert len(kept) == 1 and kept[0]["reason"] == "sem_cobertura", scanner.unpriced_rows
    assert kept[0]["link"].startswith("https://"), kept


def test_reference_carries_source_and_timestamp(tmp_path, monkeypatch):
    listings = _cards(2)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([2]), listings, max_misses=40)
    scanner.pricing.last_price_fetched_at = "2026-11-24T10:00:00"
    opps, _, _ = _run(scanner, listings, tmp_path, monkeypatch)
    by = {o.listing.card_name: o for o in opps}
    assert by["Card 1"].price_fetched_at == "2026-11-24T10:00:00"
    assert by["Card 2"].price_source == "tcgcsv"
    assert len(by["Card 2"].price_fetched_at) >= 19  # ISO datetime do prefill deste run


def test_xlsx_has_reference_time_column_and_unpriced_sheet(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    listings = _cards(3)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([2]), listings, max_misses=40)
    scanner.pricing.last_price_fetched_at = "2026-11-24T10:00:00"
    opps, _, _ = _run(scanner, listings, tmp_path, monkeypatch)
    out = tmp_path / "out.xlsx"
    sc.export_xlsx(opps, scanner.stats, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3,
                   unpriced=scanner.unpriced_rows)
    wb = load_workbook(out)
    hdr = [c.value for c in wb["Oportunidades"][1]]
    assert hdr[-2:] == ["Fonte Preço", "Ref. Data/Hora"], hdr[-4:]
    assert "Sem preço" in wb.sheetnames, wb.sheetnames
    rows = [[c.value for c in r] for r in wb["Sem preço"].iter_rows(min_row=2)]
    assert any("Card 3" in str(r) for r in rows), rows


# ───────────────────────── primário tcgcsv: gap da fonte × falha ─────────────
def test_primary_tcgcsv_fetch_failure_is_operational(tmp_path, monkeypatch):
    listings = _cards(2)
    tcgcsv = _provider_with(_fake_groups(), _fake_products({}), _fake_prices([]))
    tcgcsv.session.get.side_effect = requests.ConnectionError("rede")
    scanner = _scanner_with({}, tcgcsv, listings, max_misses=40)
    scanner.pricing = tcgcsv  # primário
    scanner.tcgcsv = None
    scanner.tcgcsv_fallback = False
    _, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {} and done[0]["status"] == "operational_failure", (done, skip)
