"""B1i — colisão de chave no índice da referência: ambígua, nunca "um dos dois"."""
from __future__ import annotations

import json
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
from test_b1e import EXP, _real_provider  # noqa: E402

_FX = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1i_collisions.json").read_text(encoding="utf-8"))


def _wiz():
    return _real_provider("wiz", 1418, "Wizards Black Star Promos", "1999-07-01T00:00:00", _FX["wiz"])


# ───────── a colisão real do wiz (Mew "08/53" × "Mew - 8 (Glossy Finish)") ─────────
def test_mew_008_with_two_products_on_the_same_key_is_ambiguous_not_one_of_the_two():
    p = _wiz()
    assert p.market_price_usd("Mew", "wiz", "008", rarity="Promo") is None       # antes: 11,90 ou 38,14 (ordem de chegada)
    assert p.last_ref_status == cv.INCOMPATIVEL
    assert "referência ambígua: 3 produtos com a mesma chave" in p.last_ref_reason   # Mew (8), Dark Gyarados 08/82, Mew - 8 (Glossy)
    assert not p.last_ref_inferred and p.last_variant_used is None and p.last_tcg_url is None


def test_pikachu_001_with_three_products_says_how_many():
    p = _wiz()
    assert p.market_price_usd("Pikachu", "wiz", "001", rarity="Promo") is None
    assert "referência ambígua: 4 produtos com a mesma chave" in p.last_ref_reason


def test_exact_product_name_breaks_the_tie_unambiguously():
    p = _wiz()
    assert p.market_price_usd("Smeargle", "wiz", "032", rarity="Promo") == 19.08   # só 1 "Smeargle" exato na chave 32


def test_pattern_variants_are_not_confused_with_the_base_product():
    asc = _real_provider("asc", 24541, "ME2.5: Ascended Heroes", "2026-01-30T00:00:00", _FX["asc"])
    assert asc.market_price_usd("Erika's Oddish", "asc", "001/217", rarity="Common") == 0.2
    assert asc.last_variant_used == "normal"
    pre = _real_provider("pre", 23821, "SV8.5: Prismatic Evolutions", "2025-01-17T00:00:00", _FX["pre"])
    assert pre.market_price_usd("Exeggcute", "pre", "001/131", rarity="Common") == 0.06
    assert pre.market_price_usd("Exeggcute", "pre", "001/131", foil=True, rarity="Common") == 0.12   # reverse do PRÓPRIO produto


def test_full_number_with_denominator_breaks_the_tie_when_names_do_not():
    rows = [{"pid": 1, "name": "Mew", "number": "08/53", "rarity": "Promo", "prices": [["Normal", 11.9]]},
            {"pid": 2, "name": "Mew", "number": "8", "rarity": "Promo", "prices": [["Normal", 38.14]]}]
    p = _real_provider("wiz", 1418, "Wizards Black Star Promos", "1999-07-01T00:00:00", rows)
    assert p.market_price_usd("Mew", "wiz", "008", rarity="Promo") is None            # sem denominador e mesmo nome: ambígua
    assert p.market_price_usd("Mew", "wiz", "008/053", rarity="Promo") == 11.9        # número completo desempata


def test_two_criteria_that_disagree_are_ambiguous_not_a_coin_flip():
    rows = [{"pid": 1, "name": "Mew", "number": "08/53", "rarity": "Promo", "prices": [["Normal", 11.9]]},
            {"pid": 2, "name": "Mew (Glossy)", "number": "8", "rarity": "Promo", "prices": [["Normal", 38.14]]}]
    cands = [{"pid": 1, "name": "Mew", "number": "08/53"}, {"pid": 2, "name": "Mew (Glossy)", "number": "8"}]
    # número completo aponta o pid 1 e o nome "Mew (Glossy)" aponta o pid 2
    chosen, why = cv.resolve_candidates(cands, "Mew (Glossy)", "008/053")
    assert chosen is None and "ambígua" in why


def test_resolve_candidates_never_uses_order_or_price_or_partial_name():
    cands = [{"pid": 1, "name": "Mew", "number": "08/53"}, {"pid": 2, "name": "Mew", "number": "08/53"}]
    assert cv.resolve_candidates(cands, "Mew", "008")[0] is None
    assert cv.resolve_candidates(cands[::-1], "Mew", "008")[0] is None
    one = [{"pid": 1, "name": "Mew (8)", "number": "08/53"}, {"pid": 2, "name": "Mew - 8 (Glossy Finish)", "number": "8"}]
    assert cv.resolve_candidates(one, "Mew", "008")[0] is None                        # nome parcial não vale


# ───────── scanner: soma fecha e a linha vai para "Sem Ref Compatível" com o motivo ─────────
def test_scanner_routes_the_ambiguous_offer_to_sem_ref_compativel_and_the_sum_closes():
    import dataclasses
    from test_set_outcomes import _cards
    from test_b1f import _tcgcsv_primary
    s = _tcgcsv_primary([(1, "Holofoil", None), (2, "Holofoil", None)], alt=None)
    # trocar o índice do set por uma colisão real: 2 produtos na mesma chave
    prov = s.pricing
    listings = _cards(3, set_code="asc")
    prov2 = _real_provider("asc", 24541, "ME2.5: Ascended Heroes", "2026-01-30T00:00:00", _FX["wiz"][:0] or [
        {"pid": 1, "name": "Card 1", "number": "001/100", "rarity": "Common", "prices": [["Normal", 3.0]]},
        {"pid": 2, "name": "Card 1 (Poke Ball)", "number": "001/100", "rarity": "Common", "prices": [["Reverse Holofoil", 4.0]]},
        {"pid": 3, "name": "Card 2", "number": "002/100", "rarity": "Common", "prices": [["Normal", 3.0]]},
        {"pid": 4, "name": "Card 2", "number": "002/100", "rarity": "Common", "prices": [["Normal", 9.0]]},
    ])
    assert prov2.market_price_usd("Card 1", "asc", "001/100", rarity="Common") == 3.0      # nome exato resolve
    assert prov2.market_price_usd("Card 2", "asc", "002/100", rarity="Common") is None     # 2 "Card 2" iguais: ambígua
    assert "referência ambígua: 2 produtos" in prov2.last_ref_reason
