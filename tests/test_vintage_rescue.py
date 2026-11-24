"""Lote 2 (#6, versão restrita): no abort por misses consecutivos com hits
prévios, os listings que AINDA SOBRAM depois do corte são resgatados via tcgcsv.

Regra: só quando i < total_listings e existe groupId. Se o corte cai no último
listing (caso de test_tcgcsv_fallback::test_e_no_fallback_when_pokemontcg_has_any_hit)
nada muda."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cardtrader_scanner as sc  # noqa: E402
from test_tcgcsv_fallback import (  # noqa: E402
    _fake_groups, _fake_prices, _fake_products, _listing, _provider_with,
    _scanner_with,
)


def _scan_set(scanner, listings, tmp_path, monkeypatch):
    """Roda scanner.scan() (com checkpoint) sobre `listings`, skip-list em tmp."""
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
    cp = sc.CheckpointWriter(tmp_path / "cp.jsonl", every_n=10)
    opps = scanner.scan([{"id": 1, "code": listings[0].set_code, "name": "Ascended Heroes"}],
                        checkpoint=cp)
    cp.close()
    recs = [json.loads(x) for x in (tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()]
    done = [r for r in recs if r.get("_type") == "set_complete"]
    skip = {}
    if (tmp_path / "skip.json").exists():
        skip = json.loads((tmp_path / "skip.json").read_text(encoding="utf-8"))["reasons"]
    return opps, done, skip


def _real_shaped_listings(n=6):
    # 1 hit no início, depois misses seguidos, com listings sobrando depois do corte
    return [_listing(f"Card {k}", f"{k:03d}/100", set_code="asc", rarity="Holo Rare")
            for k in range(1, n + 1)]


def test_rescue_prices_remaining_listings_after_cap(tmp_path, monkeypatch):
    listings = _real_shaped_listings(6)
    products = _fake_products({k: f"{k:03d}/100" for k in range(1, 7)})
    prices = _fake_prices([(k, "Holofoil", 50.0 + k) for k in range(1, 7)])
    tcgcsv = _provider_with(_fake_groups(), products, prices)
    # só a carta 1 tem preço na pokemontcg.io; cap=2 → corte em Card 3 (i=3 de 6)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, tcgcsv, listings, max_misses=2)
    opps, done, skip = _scan_set(scanner, listings, tmp_path, monkeypatch)

    by_name = {o.listing.card_name: o.price_source for o in opps}
    assert by_name["Card 1"] == "pokemontcg", by_name
    for k in range(2, 7):  # os misses até o corte + os restantes
        assert by_name.get(f"Card {k}") == "tcgcsv", by_name
    assert "asc" not in skip, skip  # sem no_coverage quando o resgate cobre
    assert len(done) == 1 and done[0]["status"] == "complete", done
    assert str(done[0].get("note", "")).startswith("tcgcsv_rescue"), done


def test_no_group_id_keeps_old_no_coverage_abort(tmp_path, monkeypatch):
    listings = _real_shaped_listings(6)
    # /groups sem nenhum group que case: resgate impossível
    tcgcsv = _provider_with([{"groupId": 9, "name": "Outro", "abbreviation": "ZZ"}],
                            _fake_products({}), _fake_prices([]))
    scanner = _scanner_with({("asc", "001/100"): 100.0}, tcgcsv, listings, max_misses=2)
    opps, done, skip = _scan_set(scanner, listings, tmp_path, monkeypatch)
    assert [o.listing.card_name for o in opps] == ["Card 1"]
    assert skip["asc"]["reason"].startswith("no_coverage_"), skip
    assert done[0]["status"] == "aborted", done


def test_cut_at_last_listing_does_not_call_tcgcsv(tmp_path, monkeypatch):
    """Espelho do teste antigo: corte no ÚLTIMO listing → tcgcsv não é tocado."""
    listings = _real_shaped_listings(2)
    tcgcsv = _provider_with(_fake_groups(), _fake_products({}), _fake_prices([]))
    scanner = _scanner_with({("asc", "001/100"): 100.0}, tcgcsv, listings, max_misses=1)
    _scan_set(scanner, listings, tmp_path, monkeypatch)
    tcgcsv.session.get.assert_not_called()
