"""B1j — correções da revisão independente de e12f0f2."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
import ct_refage  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_b1e import EXP, _real_provider  # noqa: E402
from test_b1f import _alt, _tcgcsv_primary  # noqa: E402


# ───────── A1: qualquer raridade CT inconclusiva segue o ramo de única impressão ─────────
@pytest.mark.parametrize("label", ["Fixed", "Xyz", "Promo", ""])
@pytest.mark.parametrize("ref", [None, "Common", "Holo Rare"])
def test_inconclusive_label_with_two_non_reverse_prints_is_incompatible(label, ref):
    prices = {"normal": {"market": 1.0}, "holofoil": {"market": 9.0}}
    om = cv.match_offer(prices, False, False, label, ref_rarity=ref, set_released="2016-08-03")
    assert om.match.status == cv.INCOMPATIVEL and om.inferred is None


@pytest.mark.parametrize("label", ["Fixed", "Xyz"])
def test_unknown_label_with_a_single_normal_print_is_inferred_never_sim(label):
    om = cv.match_offer({"normal": {"market": 1.0}}, False, False, label, ref_rarity="Common")
    assert om.match.status == cv.OK and om.match.key == "normal" and om.inferred and label in om.inferred


def test_unknown_label_single_holo_print_needs_a_holo_reference_rarity():
    prices = {"holofoil": {"market": 5.0}}
    assert cv.match_offer(prices, False, False, "Fixed", ref_rarity="Rare BREAK", set_released="2016-08-03").inferred
    assert cv.match_offer(prices, False, False, "Fixed", ref_rarity="Common", set_released="2016-08-03"
                          ).match.status == cv.INCOMPATIVEL
    assert cv.match_offer(prices, False, False, "Promo", ref_rarity="Rare BREAK", set_released="2016-08-03"
                          ).match.status == cv.INCOMPATIVEL      # vazia/Promo: política "holo" = sem referência


# ───────── M1: primário tcgcsv + 2ª fonte: cada linha conta UMA vez ─────────
def test_primary_tcgcsv_plus_second_source_counts_each_line_once():
    alt = _alt(price=42.0)
    s = _tcgcsv_primary([(1, "Holofoil", 3.0), (2, "Normal", 3.0)], alt=alt)
    opps = list(s.scan_expansion(EXP))
    by = s._set_by_source
    rows = {}
    for o in opps:
        rows[o.price_source] = rows.get(o.price_source, 0) + 1
    assert sum(by.values()) == len(opps)
    assert {k: v for k, v in by.items() if v} == rows


# ───────── M2 / B1: idade ausente, negativa ou futura = desconhecida = REVISAR ─────────
def _row(**k):
    r = {"net_margin": 0.5, "lucro_liq": 100.0, "validation_status": "VALIDATED_REAL", "compra_inclui_hub": True,
         "ref_compativel": "Sim", "card_number": "1", "set_code": "n1"}
    r.update(k)
    return r


def test_missing_age_column_is_unknown_and_never_compra():
    d, why = pp.classify_decision(_row(), pp.DecisionConfig(), check_liquidity=False)
    assert d == "REVISAR" and "idade da referência desconhecida" in why


def test_future_date_is_unknown_age():
    now = datetime(2026, 11, 24, 4, 51, tzinfo=timezone(timedelta(hours=-3)))
    assert ct_refage.ref_age_days("2999-01-01", "dado de", now) is None
    assert ct_refage.ref_age_days("2026-11-25", "dado de", now) is None
    assert ct_refage.ref_age_days("2026-11-24", "dado de", now) == 0


# ───────── B3: data de lançamento do set com vários groups ─────────
def test_only_four_multi_group_sets_and_none_crosses_an_era_cut():
    multi = {c for c, g in sc.CT_SET_TO_TCGCSV_GROUP_IDS.items() if len(g) > 1}
    # publishedOn real (tcgcsv 2026-11-24): iguais dentro de cada set, longe dos cortes de era
    assert multi == {"shf", "hif", "gen", "ltr"}


# ───────── índice: mesmo subtipo duas vezes no mesmo produto ─────────
def test_same_subtype_twice_with_different_prices_is_ambiguous():
    rows = [{"pid": 1, "name": "Card", "number": "001/100", "rarity": "Common",
             "prices": [["Normal", 1.0], ["Normal", 5.0]]}]
    p = _real_provider("asc", 24541, "ME2.5: Ascended Heroes", "2026-01-30T00:00:00", rows)
    assert p.market_price_usd("Card", "asc", "001/100", rarity="Common") is None
    assert "referência ambígua" in p.last_ref_reason
    same = [{"pid": 2, "name": "Card", "number": "002/100", "rarity": "Common",
             "prices": [["Normal", 2.0], ["Normal", 2.0]]}]
    p2 = _real_provider("asc", 24541, "ME2.5: Ascended Heroes", "2026-01-30T00:00:00", same)
    assert p2.market_price_usd("Card", "asc", "002/100", rarity="Common") == 2.0


def test_map_tcgcsv_prices_marks_the_same_ambiguity():
    prices = cv.map_tcgcsv_prices([{"subTypeName": "Normal", "marketPrice": 1.0},
                                   {"subTypeName": "Normal", "marketPrice": 5.0}])
    p = prices[0] if isinstance(prices, tuple) else prices
    assert p["normal"]["market"] is None and "ambígua" in p["normal"]["ambiguous"]


# ───────── pokemontcg.io: >1 resultado só casa se um dado declarado desempata ─────────
def _resp(data):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"data": list(data), "totalCount": len(data)}
    return r


def _card(cid, name, number="205", total=165, price=5.0, set_id="sv3pt5"):
    return {"id": cid, "name": name, "number": number, "rarity": "Rare Holo",
            "set": {"id": set_id, "releaseDate": "2023/09/22", "printedTotal": total},
            "tcgplayer": {"url": f"u{cid}", "prices": {"holofoil": {"market": price}}}}


def _ptcg(tmp_path, data, name="c.db"):
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.cache = sc.Cache(db_path=tmp_path / name)
    p._ptcg_get = MagicMock(return_value=_resp(data))
    p._search_memo = {}
    p._reset_ref()
    return p


def test_ptcg_two_results_with_same_name_number_and_set_are_ambiguous(tmp_path):
    p = _ptcg(tmp_path, [_card("a", "Mew ex", price=5.0), _card("b", "Mew ex", price=50.0)])
    assert p.market_price_usd("Mew ex", "sv3pt5", "205", rarity="Rare Holo") is None
    assert p.last_ref_status == cv.INCOMPATIVEL and "referência ambígua: 2 produtos" in p.last_ref_reason


def test_ptcg_exact_name_breaks_the_tie_and_a_single_result_is_unchanged(tmp_path):
    p = _ptcg(tmp_path, [_card("a", "Mew", price=1.0), _card("b", "Mew ex", price=50.0)])
    assert p.market_price_usd("Mew ex", "sv3pt5", "205", rarity="Rare Holo") == 50.0
    q = _ptcg(tmp_path, [_card("z", "Mew ex", price=7.0)], "c2.db")
    assert q.market_price_usd("Mew ex", "sv3pt5", "206", rarity="Rare Holo") == 7.0


def test_ptcg_full_number_with_denominator_breaks_the_tie(tmp_path):
    p = _ptcg(tmp_path, [_card("a", "Mew ex", total=165, price=5.0), _card("b", "Mew ex", total=191, price=50.0)])
    assert p.market_price_usd("Mew ex", "sv3pt5", "205/165", rarity="Rare Holo") == 5.0
