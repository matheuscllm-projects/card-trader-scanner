"""Testes de ct_variants (spec-estrutural D1, casos V1-V12, V16, V17).

Fixtures em tests/fixtures/variants/ (preços tcgcsv reais; pokemontcg.io da spec).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ct_variants as cv  # noqa: E402

FX = Path(__file__).parent / "fixtures" / "variants"
OK, INC = "OK", "VARIANTE_INCOMPATIVEL"


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def ptcg(card_id):
    return _load("ptcg_cards.json")["cards"][card_id]["prices"]


def tcgcsv(group, number):
    """Preços de um card real do tcgcsv, no vocabulário pokemontcg.io."""
    for c in _load("tcgcsv_cards.json")["cards"]:
        if c["groupId"] == group and c["number"] == number:
            return {
                cv.TCGCSV_SUBTYPE_TO_VARIANT[r["subTypeName"]]: {"market": r["marketPrice"]}
                for r in c["prices"]
            }
    raise KeyError((group, number))


def match(prices, first_edition, reverse, is_holo):
    ed, fin = cv.offer_variant(first_edition, reverse, is_holo)
    return cv.match_reference_variant(prices, ed, fin, is_holo)


def test_offer_variant():
    assert cv.offer_variant(True, False, True) == ("1st", "holo")
    assert cv.offer_variant(False, False, False) == ("unl", "normal")
    assert cv.offer_variant(False, True, True) == ("unl", "reverse")  # reverse vence holo


def test_v1_lugia_unlimited():
    key, status, _ = match(ptcg("neo1-9"), False, False, True)
    assert (key, status) == ("unlimitedHolofoil", OK)


def test_v2_lugia_first_edition():
    key, status, _ = match(ptcg("neo1-9"), True, False, True)
    assert (key, status) == ("1stEditionHolofoil", OK)


def test_v3_cyndaquil_unlimited_e_1st():
    assert match(ptcg("neo1-56"), False, False, False)[:2] == ("unlimited", OK)
    assert match(ptcg("neo1-56"), True, False, False)[:2] == ("1stEdition", OK)


def test_v4_tcgcsv_gligar_mapeia_para_vocabulario_ptcg():
    assert cv.TCGCSV_SUBTYPE_TO_VARIANT["1st Edition"] == "1stEdition"
    assert cv.TCGCSV_SUBTYPE_TO_VARIANT["Unlimited"] == "unlimited"
    csv = tcgcsv(1396, "059/111")
    assert set(csv) == {"1stEdition", "unlimited"}
    for fe in (False, True):  # mesma seleção que a pokemontcg.io (V3)
        assert match(csv, fe, False, False)[0] == match(ptcg("neo1-59"), fe, False, False)[0]


def test_v5_base_set_normal_oferta_1st_incompativel():
    key, status, reason = match(tcgcsv(604, "043/102"), True, False, False)
    assert (key, status) == (None, INC)
    assert "sem preço 1st Edition" in reason


def test_v6_base_set_holofoil_impressao_unica():
    # Alakazam Holofoil sozinho; oferta unlimited (o CT não rotula edição no Base Set)
    assert match(tcgcsv(604, "001/102"), False, False, True)[:2] == ("holofoil", OK)


def test_v7_reverse_sem_chave_reverse_nao_cai_no_holofoil():
    key, status, reason = match(tcgcsv(604, "001/102"), False, True, True)
    assert (key, status) == (None, INC)
    assert "sem preço Reverse Holo" in reason
    # forma ex1 (chaves reais da spec: carta só com holofoil)
    key, status, _ = cv.match_reference_variant({"holofoil": {"market": 1.0}}, "unl", "reverse", True)
    assert (key, status) == (None, INC)


def test_v8_normal_e_reverse_tcgcsv_moderno():
    prices = tcgcsv(23473, "001/167")  # Tangela: normal + reverseHolofoil
    assert match(prices, False, False, False)[:2] == ("normal", OK)
    assert match(prices, False, True, False)[:2] == ("reverseHolofoil", OK)
    assert match(ptcg("ex12-56"), False, False, False)[0] == "normal"


def test_v9_lileep_reverse_mantem_chave_e_guard_outlier_dispara():
    key, status, _ = match(ptcg("ex12-56"), False, True, False)
    assert (key, status) == ("reverseHolofoil", OK)
    import cardtrader_scanner as scanner  # guard v2.24 continua no scanner
    p = ptcg("ex12-56")
    assert scanner._reverse_nonholo_market_outlier(
        key, False, p[key]["market"], p["normal"]["market"])


def test_v10_zubat_reverse_sem_flag():
    key, status, _ = match(ptcg("ecard3-118"), False, True, False)
    assert (key, status) == ("reverseHolofoil", OK)
    import cardtrader_scanner as scanner
    p = ptcg("ecard3-118")
    assert not scanner._reverse_nonholo_market_outlier(
        key, False, p[key]["market"], p["normal"]["market"])


def test_v11_moderno_rare_holofoil_com_reverse_continua_precificando():
    prices = tcgcsv(23473, "019/167")  # Iron Leaves Rare: Holofoil + Reverse Holofoil
    assert match(prices, False, False, True)[:2] == ("holofoil", OK)
    assert match(prices, False, False, False)[:2] == ("holofoil", OK)  # impressão única
    assert match(prices, False, True, False)[:2] == ("reverseHolofoil", OK)


def test_v12_moderno_oferta_1st_incompativel():
    key, status, _ = match(tcgcsv(23473, "001/167"), True, False, False)
    assert (key, status) == (None, INC)


def test_unlimited_nunca_cai_em_1st_e_vice_versa():
    only_1st = {"1stEdition": {"market": 5.0}}
    only_unl = {"unlimited": {"market": 1.0}}
    assert match(only_1st, False, False, False)[1] == INC
    assert match(only_unl, True, False, False)[1] == INC


def test_so_reverse_oferta_nao_reverse_incompativel():
    key, status, reason = cv.match_reference_variant(
        {"reverseHolofoil": {"market": 2.0}}, "", "normal", False)
    assert (key, status) == (None, INC)
    assert "Reverse" in reason


def test_market_zero_ou_ausente_e_descartado():
    prices = {"1stEdition": {"market": None}, "unlimited": {"market": 0}, "normal": {"market": 3.0}}
    assert match(prices, True, False, False)[1] == INC  # nem 1st nem divisão
    assert match({"1stEditionNormal": {"market": 4.0}}, True, False, False)[:2] == ("1stEditionNormal", OK)


def test_chave_desconhecida_ignorada_e_listada():
    prices = {"normal": {"market": 1.0}, "foo": {"market": 9.0}}
    assert match(prices, False, False, False)[0] == "normal"
    assert cv.available_keys(prices) == ["normal"]


def test_sem_precos_utilizaveis():
    key, status, _ = match({}, False, False, False)
    assert key is None and status == "CARTA_NAO_ENCONTRADA"


def test_v16_chave_de_cache_e_versao():
    a = cv.price_cache_key("neo1", "9", "Lugia", True, False, True)
    b = cv.price_cache_key("neo1", "9", "Lugia", False, False, True)
    assert a != b and cv.PRICE_LOGIC_VERSION == "3" and a.startswith("pokemontcg:3:")
    assert cv.price_cache_key("neo1", "9", "Lugia", False, False, True) != \
        cv.price_cache_key("neo1", "9", "Lugia", False, False, False)  # is_holo na chave
    assert a != cv.price_cache_key("neo1", "9", "Lugia", True, True, True)


def test_uid_separa_edicao_e_reverse():
    base = cv.offer_uid(1, "s", "Near Mint", False, False)
    assert base == "1:s:Near Mint:unl:std"
    assert cv.offer_uid(1, "s", "Near Mint", True, False) == "1:s:Near Mint:1st:std"
    assert cv.offer_uid(1, "s", "Near Mint", False, True).endswith(":unl:rev")
    assert len({base, cv.offer_uid(1, "s", "Near Mint", True, False),
                cv.offer_uid(1, "s", "Near Mint", False, True)}) == 3


def test_v17_pc_slug_compatible():
    paths = _load("pc_paths_lugia.json")["paths"]
    pick = lambda ed, fin: [p for p in paths if cv.pc_slug_compatible(p, ed, fin)]  # noqa: E731
    assert pick("1st", "holo") == ["/game/pokemon-neo-genesis/lugia-1st-edition-9"]
    assert pick("unl", "holo") == ["/game/pokemon-neo-genesis/lugia-9"]
    assert pick("1st", "reverse") == []
    assert cv.pc_slug_compatible("/game/pokemon-ex-legend-maker/zubat-reverse-holo-118", "unl", "reverse")
    assert not cv.pc_slug_compatible("/game/pokemon-ex-legend-maker/zubat-reverse-holo-118", "unl", "normal")
