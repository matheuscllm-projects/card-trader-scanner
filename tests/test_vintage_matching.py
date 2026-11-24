"""Lote 2 (casamento de carta/set em vintage).

Fonte de verdade dos ids/nomes do lado pokemontcg.io: JSON estático do repo
PokemonTCG/pokemon-tcg-data (sets/en.json, cards/en/<id>.json), conferido em
2026-11-24. Cada caso abaixo cita o trecho que o comprova.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cardtrader_scanner as sc  # noqa: E402


def _provider_capturing_queries():
    """PokemonTcgIoProvider sem rede; captura os `q` enviados à API."""
    prov = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    sent: list[str] = []

    def fake_get(params):
        sent.append(params["q"])
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"data": [], "totalCount": 0}
        return r

    prov._ptcg_get = fake_get
    return prov, sent


# ── #1: nomes CT "δ Delta Species" / "☆ Gold Star" → nome da referência ─────
# JSON: ex15 "Ampharos δ", ex15 #100 "Charizard ★ δ", ex11 #111 "Groudon ★",
#       ex14 #99 "Alakazam ★", ex14 "Blastoise δ", ex11 "Beedrill δ".
@pytest.mark.parametrize("ct_name, ptcg_name", [
    ("Ampharos δ Delta Species", "Ampharos δ"),           # df
    ("Feraligatr δ Delta Species", "Feraligatr δ"),       # df
    ("Beedrill δ Delta Species", "Beedrill δ"),           # ds
    ("Blastoise δ Delta Species", "Blastoise δ"),         # cg
    ("Charizard ☆ Gold Star δ Delta Species", "Charizard ★ δ"),  # df #100
    ("Groudon ☆ Gold Star", "Groudon ★"),                 # ds #111
    ("Alakazam ☆ Gold Star", "Alakazam ★"),               # cg #99
])
def test_ct_vintage_names_are_normalized_for_query(ct_name, ptcg_name):
    prov, sent = _provider_capturing_queries()
    prov._search(ct_name, "df", "001/101")
    assert sent and f'name:"{ptcg_name}"' in sent[0], sent


def test_plain_names_are_untouched():
    prov, sent = _provider_capturing_queries()
    prov._search("Banette", "cg", "001/100")
    assert 'name:"Banette"' in sent[0], sent


# ── #2: número preserva letra/prefixo no caminho pokemontcg.io ──────────────
# JSON ecard2: {'number': 'H1', name 'Ampharos'} e {'number': '1', 'Ampharos'};
# '50' Golduck e '103' Porygon existem SEM variante a/b (a/b só no CT).
@pytest.mark.parametrize("ct_number, expected", [
    ("H1", "number:H1"),
    ("H16/H32", "number:H16"),
    ("001/147", "number:1 "),
    ("002/147", "number:2 "),
])
def test_number_query_keeps_letter_prefix(ct_number, expected):
    prov, sent = _provider_capturing_queries()
    prov._search("Ampharos", "aq", ct_number)
    assert expected in sent[0] + " ", sent


@pytest.mark.parametrize("ct_number, expected", [
    ("50a/147", "number:50A"),
    ("50b/147", "number:50B"),
    ("103a/147", "number:103A"),
])
def test_number_query_does_not_collapse_suffix_variants(ct_number, expected):
    prov, sent = _provider_capturing_queries()
    prov._search("Golduck", "aq", ct_number)
    assert expected in sent[0], sent
    assert "number:50 " not in sent[0] + " " and "number:103 " not in sent[0] + " "


# ── #3: aliases (parcial: wcd2010) ──────────────────────────────────────────
# md/la/dp/ar (dp5/dp6/dp1/pl4 confirmados no JSON) aguardam decisão: adicioná-los
# muda o universo de tests/test_scan_skill_profiles.py (skill /scan).
def test_every_vintage_code_has_an_alias():
    aliases = sc.PokemonTcgIoProvider.SET_ALIAS_TO_PTCG
    missing = [c for c in sc.VINTAGE_SET_CODES if not aliases.get(c)]
    assert missing == [], missing


def test_wcd2010_is_not_aliased_to_legends_awakened():
    # JSON: dp6 = "Legends Awakened" (set de verdade), não World Championship Deck.
    assert "dp6" not in sc.PokemonTcgIoProvider.SET_ALIAS_TO_PTCG.get("wcd2010", [])


# ── #13: CT g1 (Gym Heroes) × ptcg g1 (Generations) ─────────────────────────
# JSON sets/en.json: {"id": "g1", "name": "Generations"}; gym1 = "Gym Heroes".
def test_ct_g1_does_not_match_ptcg_generations_by_identity():
    assert sc.ptcg_expected_sets("g1") == {"gym1"}


def test_ct_gen_still_maps_to_ptcg_generations():
    assert "g1" in sc.ptcg_expected_sets("gen")


def test_identity_still_works_for_pop_series():
    assert "pop2" in sc.ptcg_expected_sets("pop2")  # JSON: pop2 "POP Series 2"
