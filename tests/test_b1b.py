"""B1b — fallback tcgcsv p/ ref incompativel, entrega com edicao/acabamento/fonte/data, top-md,
filtros visiveis, liquidas PARCIAIS, baixas, chase fora de score, motivo de holo."""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_scanner as sc  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_set_outcomes import _cards, _run  # noqa: E402
from test_tcgcsv_fallback import (  # noqa: E402
    _fake_groups, _fake_prices, _fake_products, _provider_with, _scanner_with,
)

SRC = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")

# Pichu e-Card (caso removido do fixture em B1): pokemontcg mistura `holofoil` sem rotulo com
# `1stEditionHolofoil` -> ambiguo -> sem ref compativel NA pokemontcg; tcgcsv tem chaves limpas.
PICHU = {
    "id": "ecard1-22", "name": "Pichu", "number": "1", "rarity": "Rare Holo",
    "set": {"id": "ecard1", "releaseDate": "2002/09/15", "printedTotal": 165},
    "tcgplayer": {"url": "https://prices.pokemontcg.io/tcgplayer/ecard1-22", "prices": {
        "holofoil": {"market": 224.99}, "reverseHolofoil": {"market": 120.57},
        "1stEditionHolofoil": {"market": 750.0}}},
}


def _fallback_scanner(tmp_path, tcgcsv_rows, n=1):
    listings = [dataclasses.replace(l, rarity="Holo Rare") for l in _cards(n, set_code="asc")]
    tcgcsv = _provider_with(_fake_groups(), _fake_products({k: f"{k:03d}/100" for k in range(1, n + 1)}),
                            _fake_prices(tcgcsv_rows))
    scanner = _scanner_with({}, tcgcsv, listings, tcgcsv_fallback=True, max_misses=40)
    ptcg = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    ptcg.cache = sc.Cache(db_path=tmp_path / "c.db")
    ptcg._search = lambda *a, **k: PICHU
    scanner.pricing = ptcg
    return scanner, listings


# ───────────── 1: tcgcsv como fallback p/ ref incompativel ─────────────
def test_incompatible_in_pokemontcg_is_priced_by_tcgcsv(tmp_path, monkeypatch):
    scanner, listings = _fallback_scanner(
        tmp_path, [(1, "Unlimited Holofoil", 224.99), (1, "1st Edition Holofoil", 750.0)])
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 1 and scanner.noref_rows == []
    o = opps[0]
    assert o.price_source == "tcgcsv" and o.price_variant_used == "unlimitedHolofoil"
    assert o.ref_compatible is True and o.price_fetched_at
    assert o.tcg_market_usd == 224.99
    assert skip == {}


def test_both_sources_incompatible_replaces_row_with_two_reasons_and_sum_closes(tmp_path, monkeypatch):
    scanner, listings = _fallback_scanner(tmp_path, [(1, "1st Edition Holofoil", 750.0)], n=3)
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    assert opps == []
    assert len(scanner.noref_rows) == 3                      # SUBSTITUIDA, nao duplicada
    r = scanner.noref_rows[0]
    assert "pokemontcg" in r["motivo"] and "tcgcsv" in r["motivo"]
    n_un = len([x for x in scanner.unpriced_rows if x["set"] == "asc"])
    assert len(opps) + n_un + len(scanner.noref_rows) == 3
    cp = [json.loads(x) for x in (tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([c for c in cp if c.get("_type") == "noref"]) == 3


def test_tcgcsv_fetch_failure_is_operational_not_definitive_noref(tmp_path, monkeypatch):
    """B1c-1 cenario A: pokemontcg acha a carta sem variante compativel e o tcgcsv FALHA (rede/5xx):
    NAO e 'Sem Ref Compativel' definitivo; vai p/ 'Sem preço' como falha operacional (com a 1ª causa)
    e o set sai operational_failure ('tentar de novo'), nunca complete."""
    scanner, listings = _fallback_scanner(tmp_path, [(1, "Unlimited Holofoil", 1.0)])
    scanner.tcgcsv.prefill_set = MagicMock(return_value=False)
    scanner.tcgcsv.last_prefill_status = "fetch_failed"
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    assert opps == [] and scanner.noref_rows == []
    assert [r["reason"] for r in scanner.unpriced_rows] == ["falha_operacional"]
    assert "pokemontcg" in scanner.unpriced_rows[0]["detail"]
    assert done and done[0]["status"] == "operational_failure"


def test_tcgcsv_pricing_exception_is_operational_not_noref(tmp_path, monkeypatch):
    """B1c-1 cenario B: market_price_usd lanca excecao -> falha operacional, nao 'carta nao encontrada'."""
    scanner, listings = _fallback_scanner(tmp_path, [(1, "Unlimited Holofoil", 1.0)])
    scanner.tcgcsv.market_price_usd = MagicMock(side_effect=RuntimeError("boom"))
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    assert opps == [] and scanner.noref_rows == []
    assert [r["reason"] for r in scanner.unpriced_rows] == ["falha_operacional"]
    assert done and done[0]["status"] == "operational_failure"


def test_scan_never_loses_validated_rows_below_min_net(tmp_path):
    """B1c-2: 'após filtros' = soma de todos os destinos. Validada com líquida real < --min-net-margin
    continua na lista final (o postprocess classifica), com o contador de marcadas."""
    from test_validate_all import _opp
    rows = [_opp(1, status="VALIDATED_REAL", real_net=0.05), _opp(2, status="VALIDATED_REAL", real_net=0.50)]
    kept, marked = sc.apply_validation_filters(rows, 0.20)
    assert len(kept) == 2 and len(marked) == 1
