"""Testes de ct_chase (A3): caracterizacao contra as duas copias antigas."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ct_chase  # noqa: E402
import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402

RARITIES = [
    "Special Illustration Rare", "SIR", "Illustration Rare", "Special Art Rare",
    "SAR", "Hyper Rare", "Ultra Hyper Rare", "Secret Rare", "Rara Secreta",
    "Full Art", "Alt Art", "Alternate Art", "Rainbow Rare", "Gold Rare",
    "Trainer Gallery Rare Holo", "Double Rare", "Rara Hiper", "Ultra Rare",
    "Holo Rare", "Reverse Holo", "Reverse Foil", "Promo", "Rare Holo",
    "Rare Holo EX", "Rare Secret", "Rare Shining", "Rare", "Rare Holo GX",
    "Common", "Uncommon", "Comum", "Incomum", "COMMON ", "  uncommon",
    "Amazing Rare", "Radiant Rare", "ACE SPEC Rare", "Shiny Rare",
    "Black White Rare", "Mega Hyper Rare", "Classic Collection", "Legend",
    "Rare Prime", "Rare BREAK", "Rare Ultra", "Weird Unknown",
]


def test_rarity_igual_as_duas_copias():
    for r in RARITIES:
        assert ct_chase.classify_chase_tier(r) == sc.classify_chase_tier(r), r
        assert ct_chase.classify_chase_tier(r) == pp.classify_chase_tier(r), r
        assert ct_chase.classify_chase_tier(r, "10/100", "x") == pp.classify_chase_tier(r, "10/100", "x")


def test_patterns_order_only_iguais():
    # B1: o scanner IMPORTA do ct_chase (sem copia): identidade, nao paridade
    assert not hasattr(sc, "CHASE_TIER_PATTERNS")
    assert sc.CHASE_TIER_ORDER is ct_chase.CHASE_TIER_ORDER
    assert sc.CHASE_ONLY_TIERS is ct_chase.CHASE_ONLY_TIERS


def test_proxies_iguais_ao_postprocess():
    casos = [("TG05", None), ("GG10/GG70", None), ("200/150", None),
             ("10/150", None), ("abc", "Hub +20% non-VAT"), ("5", "Hub +6%"),
             ("x/y", None)]
    for num, mt in casos:
        assert ct_chase.classify_chase_tier("", num, mt) == pp.classify_chase_tier("", num, mt), (num, mt)


def test_rarity_vazia_sem_proxies_e_string_vazia():
    assert ct_chase.classify_chase_tier("") == ""
    assert ct_chase.classify_chase_tier(None) == ""
    assert sc.classify_chase_tier(None) == ""


def test_divergencia_conhecida_rarity_vazia_proxies_none():
    """DIVERGENCIA DOCUMENTADA (nao e bug a corrigir aqui): raridade vazia e proxies None.

    scanner antigo -> ""; postprocess antigo -> "MODEST"; ct_chase unificado segue o scanner.
    """
    assert sc.classify_chase_tier("") == ""
    assert sc.classify_chase_tier(None) == ""
    # P1: o postprocess nao tem mais copia; importa de ct_chase (a divergencia "MODEST" acabou).
    assert pp.classify_chase_tier is ct_chase.classify_chase_tier
    assert pp.classify_chase_tier("") == ""
    assert ct_chase.classify_chase_tier("") == ""
    assert ct_chase.classify_chase_tier(None) == ""


def test_supranumerario_top():
    assert ct_chase.classify_chase_tier("", card_number="200/150") == "TOP"
