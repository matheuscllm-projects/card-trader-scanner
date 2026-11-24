"""Testes de ct_variants (spec-estrutural D1 + decisao do dono 2026-11-24:
correspondencia EXATA de edicao e acabamento; sem referencia compativel, sem compra).

Fixtures em tests/fixtures/variants/ (cada arquivo traz data e URL de origem).
Inline = sintetico (marcado `sintetico` no nome do teste).
"""
from __future__ import annotations

import itertools
import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
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


def _to_ptcg(rows):
    prices, ignored = cv.map_tcgcsv_prices(rows)
    assert not ignored
    return prices


def tcgcsv(group, number):
    """Preços de um card real do tcgcsv, no vocabulário pokemontcg.io."""
    for c in _load("tcgcsv_cards.json")["cards"]:
        if c["groupId"] == group and c["number"] == number:
            return _to_ptcg(c["prices"])
    raise KeyError((group, number))


def base_group(group, name):
    """Carta real do Base Set (604) ou Base Set (Shadowless) (1663)."""
    for c in _load("tcgcsv_base_groups.json")["cards"]:
        if c["groupId"] == group and c["name"] == name:
            return _to_ptcg(c["prices"])
    raise KeyError((group, name))


def match(prices, first_edition, reverse, is_holo, **kw):
    ed, fin = cv.offer_variant(first_edition, reverse, is_holo)
    return cv.match_reference_variant(prices, ed, fin, **kw)


def mk(**kv):
    return {k: {"market": v} for k, v in kv.items()}


# ---- oferta / casamento base -------------------------------------------------

def test_offer_variant():
    assert cv.offer_variant(True, False, True) == ("1st", "holo")
    assert cv.offer_variant(False, False, False) == ("unl", "normal")
    assert cv.offer_variant(False, True, True) == ("unl", "reverse")  # reverse vence holo


def test_constantes_de_vocabulario_exportadas():
    assert (cv.ED_1ST, cv.ED_UNL, cv.ED_NONE) == ("1st", "unl", "")
    assert (cv.FIN_NORMAL, cv.FIN_HOLO, cv.FIN_REVERSE) == ("normal", "holo", "reverse")
    assert not hasattr(cv, "pc_slug_compatible")  # regra de slug fica em pricecharting_ref.py


def test_v1_lugia_unlimited():
    r = match(ptcg("neo1-9"), False, False, True)
    assert (r[0], r[1]) == ("unlimitedHolofoil", OK)
    assert r.canon == ("unl", "holo")


def test_v2_lugia_first_edition():
    r = match(ptcg("neo1-9"), True, False, True)
    assert (r[0], r[1]) == ("1stEditionHolofoil", OK)
    assert r.canon == ("1st", "holo")


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
    r = match(tcgcsv(604, "043/102"), True, False, False)
    assert (r[0], r[1]) == (None, INC)
    assert "sem preço 1st Edition" in r[2]


def test_v6_base_set_holofoil_sem_rotulo_vale_como_unlimited_exato():
    # dado real: tcgcsv 604 so tem Normal/Holofoil, sem NENHUM produto misturando rotulos
    r = match(tcgcsv(604, "001/102"), False, False, True)
    assert (r[0], r[1]) == ("holofoil", OK) and r.canon == ("", "holo")


def test_v7_reverse_sem_chave_reverse_nao_cai_no_holofoil():
    r = match(tcgcsv(604, "001/102"), False, True, True)
    assert (r[0], r[1]) == (None, INC)
    assert "sem preço Unlimited Reverse Holo" in r[2] or "sem preço Reverse Holo" in r[2]
    r = cv.match_reference_variant(mk(holofoil=1.0), "unl", "reverse")
    assert (r[0], r[1]) == (None, INC)


def test_v8_normal_e_reverse_tcgcsv_moderno():
    prices = tcgcsv(23473, "001/167")  # Tangela: normal + reverseHolofoil
    assert match(prices, False, False, False)[:2] == ("normal", OK)
    assert match(prices, False, True, False)[:2] == ("reverseHolofoil", OK)
    assert match(ptcg("ex12-56"), False, False, False)[0] == "normal"


def test_v9_lileep_reverse_mantem_chave_e_guard_outlier_dispara():
    key, status, _ = match(ptcg("ex12-56"), False, True, False)[:3]
    assert (key, status) == ("reverseHolofoil", OK)
    import cardtrader_scanner as scanner  # guard v2.24 continua no scanner
    p = ptcg("ex12-56")
    assert scanner._reverse_nonholo_market_outlier(
        key, False, p[key]["market"], p["normal"]["market"])


def test_v10_zubat_reverse_sem_flag():
    key, status, _ = match(ptcg("ecard3-118"), False, True, False)[:3]
    assert (key, status) == ("reverseHolofoil", OK)
    import cardtrader_scanner as scanner
    p = ptcg("ecard3-118")
    assert not scanner._reverse_nonholo_market_outlier(
        key, False, p[key]["market"], p["normal"]["market"])


def test_v12_moderno_oferta_1st_incompativel():
    r = match(tcgcsv(23473, "001/167"), True, False, False)
    assert (r[0], r[1]) == (None, INC)


def test_unlimited_nunca_cai_em_1st_e_vice_versa_sintetico():
    assert match(mk(**{"1stEdition": 5.0}), False, False, False)[1] == INC
    assert match(mk(unlimited=1.0), True, False, False)[1] == INC


def test_so_reverse_oferta_nao_reverse_incompativel_sintetico():
    r = cv.match_reference_variant(mk(reverseHolofoil=2.0), "", "normal")
    assert (r[0], r[1]) == (None, INC)
    assert "reverseHolofoil" in r[2]


def test_chave_desconhecida_ignorada_e_listada_sintetico():
    prices = mk(normal=1.0, foo=9.0)
    assert match(prices, False, False, False)[0] == "normal"
    assert cv.available_keys(prices) == ["normal"]


def test_sem_precos_nenhuma_chave_e_nao_encontrada():
    for empty in ({}, None):
        r = match(empty, False, False, False)
        assert r[0] is None and r[1] == "CARTA_NAO_ENCONTRADA"


# ---- item 1: correspondencia EXATA de acabamento (decisao do dono) ----------

def test_i1_holofoil_mais_reverse_oferta_normal_incompativel_sintetico():
    r = match(mk(holofoil=5.0, reverseHolofoil=2.0), False, False, False)
    assert (r[0], r[1]) == (None, INC)
    assert "holofoil" in r[2] and "reverseHolofoil" in r[2]  # chaves disponiveis no motivo
    assert r.canon is None


def test_i1_unlimited_holofoil_so_oferta_normal_incompativel_sintetico():
    r = match(mk(unlimitedHolofoil=9.0), False, False, False)
    assert (r[0], r[1]) == (None, INC)


def test_i1_normal_so_oferta_holo_incompativel_sintetico():
    r = match(mk(normal=5.0), False, False, True)
    assert (r[0], r[1]) == (None, INC)


def test_i1_moderno_rare_so_holofoil_com_oferta_nao_holo_vira_incompativel():
    # dado real tcgcsv 23473 (Iron Leaves Rare: Holofoil + Reverse). Antes: OK com low_confidence.
    prices = tcgcsv(23473, "019/167")
    assert match(prices, False, False, True)[:2] == ("holofoil", OK)
    assert match(prices, False, False, False)[1] == INC
    assert match(prices, False, True, False)[:2] == ("reverseHolofoil", OK)


# ---- deteccao de acabamento da oferta (decisao do diretor, 2026-11-24) -------
# Evidencia: tests/fixtures/variants/rarity_evidence.json (tcgcsv, 150 grupos, 2026-11-24).

def _ev():
    return _load("rarity_evidence.json")


def _ev_rarity(name):
    for k, v in _ev()["rarities"].items():
        if k.lower() == name.lower():
            return v["all"]
    raise KeyError(name)


def test_r1_holo_por_natureza_so_com_evidencia_sem_excecao():
    assert len(cv.HOLO_NATURAL_NAMES) >= 14
    for name in cv.HOLO_NATURAL_NAMES:
        c = _ev_rarity(name)
        assert c.get("normal_present", 0) == 0, (name, c)  # nenhuma excecao
        assert c.get("holo_only", 0) >= 5, (name, c)  # evidencia minima


def test_r1_raridades_fora_da_lista_tem_excecao_ou_pouca_evidencia():
    for name in ("Ultra Rare", "Secret Rare", "Rare", "Promo", "Common", "Uncommon"):
        assert name.lower() not in cv.HOLO_NATURAL_NAMES
    # Ultra/Secret: so com data de corte, depois da ultima excecao observada
    g = _ev()["gated_from_date"]
    for name, cut in cv.HOLO_FROM.items():
        assert g[name.title()]["from"] == cut and g[name.title()].get("normal_present", 0) == 0
        assert g[name.title()]["holo_only"] >= 100


@pytest.mark.parametrize("rar", [
    "Illustration Rare", "Special Illustration Rare", "Hyper Rare", "ACE SPEC Rare",
    "Double Rare", "Shiny Rare", "Rainbow Rare", "Radiant Rare", "Amazing Rare",
    "Rare BREAK", "Rare Ace", "Prism Rare", "Shiny Ultra Rare", "Classic Collection",
    # grafias ptcg.io (ordem de palavras invertida)
    "Rare Rainbow", "Rare Prism Star", "Rare Shiny",
    # grafias do scanner/ptcg ja cobertas por 'holo'
    "Rare Holo V", "Rare Holo VMAX", "Rare Holo EX", "Rare Holo", "Holo Rare",
    "  ILLUSTRATION   rare ",
])
def test_r1_holo_sem_precisar_de_era(rar):
    d = cv.holo_detection(rar)
    assert d.is_holo and not d.era_missing, rar


def test_r1_nao_holo_basicas():
    for rar in ("Common", "Uncommon", "Promo", "Token", "Reverse Holo", "Non-Holo", None, ""):
        d = cv.holo_detection(rar)
        assert not d.is_holo and not d.era_missing, rar


def test_r2_rare_depende_da_era():
    assert cv.rarity_is_holo("Rare", set_released="2024-05-24") is True      # SV06
    assert cv.rarity_is_holo("Rare", set_released="2023-03-31") is True      # SV01 (inicio)
    assert cv.rarity_is_holo("Rare", set_released="2023-03-30") is False
    assert cv.rarity_is_holo("Rare", set_released="2022/11/11") is False     # formato ptcg
    assert cv.rarity_is_holo("Rare", set_released="2025-09-26") is True      # ME
    import datetime
    assert cv.rarity_is_holo("Rare", set_released=datetime.date(2024, 1, 1)) is True


def test_r2_rare_sem_era_e_conservador_e_avisa():
    d = cv.holo_detection("Rare")
    assert (d.is_holo, d.era_missing) == (False, True)
    d = cv.holo_detection("Rare", set_released="lixo")
    assert (d.is_holo, d.era_missing) == (False, True)
    assert cv.rarity_is_holo("Rare") is False
    # Common nunca precisa de era
    assert cv.holo_detection("Common").era_missing is False


def test_r2_prova_rare_por_era_no_dado_real():
    r = _ev()["rarities"]["Rare"]
    assert r["SV+"].get("normal_present", 0) == 0 and r["SV+"]["holo_only"] > 400
    assert r["pre"]["normal_present"] > 2000 and r["pre"].get("holo_only", 0) < 20
    assert _ev()["_sv_start"] == cv.SV_START == "2023-03-31"


@pytest.mark.parametrize("rar,rel,esperado", [
    ("Ultra Rare", "2005-05-09", False), ("Ultra Rare", "2005-05-10", True),
    ("Ultra Rare", "2024-01-01", True),
    ("Secret Rare", "2008-11-04", False), ("Secret Rare", "2008-11-05", True),   # B1f: dado real, 0 exceção desde Stormfront
    ("Secret Rare", "2016-11-03", True),
    ("Rare Ultra", "2020-01-01", True), ("Rare Secret", "2020-01-01", True),
    ("Rare Secret", "2010-01-01", True), ("Rare Secret", "2005-02-14", False),
])
def test_r3_ultra_e_secret_so_depois_da_ultima_excecao(rar, rel, esperado):
    assert cv.rarity_is_holo(rar, set_released=rel) is esperado


def test_r3_ultra_e_secret_sem_era_avisam():
    for rar in ("Ultra Rare", "Secret Rare", "Rare Ultra"):
        d = cv.holo_detection(rar)
        assert (d.is_holo, d.era_missing) == (False, True), rar


def test_r3_qualquer_rotulo_vence_e_era_so_avisa_se_ninguem_resolveu():
    assert cv.holo_detection("Rare", "Holo Rare").era_missing is False
    d = cv.holo_detection("Rare", "Common")
    assert (d.is_holo, d.era_missing) == (False, True)


def test_r4_resultado_diz_que_a_era_nao_foi_informada():
    prices = tcgcsv(23473, "019/167")  # Iron Leaves: Holofoil + Reverse
    d = cv.holo_detection("Rare")
    r = cv.match_reference_variant(prices, "unl", cv.offer_variant(False, False, d.is_holo)[1],
                                   era_missing=d.era_missing)
    assert r.status == INC and "era do set não informada" in r.reason
    d = cv.holo_detection("Rare", set_released="2024-05-24")
    r = cv.match_reference_variant(prices, "unl", cv.offer_variant(False, False, d.is_holo)[1],
                                   era_missing=d.era_missing)
    assert (r.key, r.status) == ("holofoil", OK)


def test_i1_canon_devolvido_para_auditoria():
    r = match(mk(unlimited=1.0, **{"1stEdition": 3.0}), True, False, False)
    assert (r.key, r.status, r.canon) == ("1stEdition", OK, ("1st", "normal"))
    assert r.reason == ""


@pytest.mark.parametrize("rar,esperado", [
    ("Non-Holo", False), ("non-holo", False), ("Nonholo", False), ("Non Holo", False),
    ("Holo Rare", True), ("Rare Holo EX", True), ("Rare Shining", True),
    ("Reverse Holo", False), ("Common", False), ("", False), (None, False),
])
def test_i1_rarity_is_holo(rar, esperado):
    assert cv.rarity_is_holo(rar) is esperado


def test_i1_rarity_is_holo_qualquer_rotulo():
    assert cv.rarity_is_holo("Common", "Holo Rare") is True
    assert cv.rarity_is_holo("Common", "Non-Holo") is False


# ---- item 2: edicao x rotulos, com dado real ---------------------------------

def test_i2_dado_real_base_set_regular_so_tem_chaves_sem_rotulo():
    inv = _load("tcgcsv_base_groups.json")["subtype_inventory"]
    assert set(inv["604"]) == {"Normal", "Holofoil"}
    assert set(inv["1663"]) == {"1st Edition", "1st Edition Holofoil", "Unlimited",
                                "Unlimited Holofoil", "Normal"}
    # nenhum produto real mistura chave sem rotulo com 1st Edition
    for g, combos in _load("tcgcsv_base_groups.json")["subtype_combinations_per_product"].items():
        for combo in combos:
            parts = combo.split(" + ")
            if any(p.startswith("1st Edition") for p in parts):
                assert not {"Normal", "Holofoil", "Reverse Holofoil"} & set(parts), (g, combo)


def test_i2_base_set_regular_alakazam_unlimited_ok_1st_incompativel():
    p = base_group(604, "Alakazam")  # so Holofoil
    assert match(p, False, False, True)[:2] == ("holofoil", OK)
    assert match(p, True, False, True)[1] == INC


def test_i2_shadowless_unlimited_nunca_e_referencia_para_1st_nem_para_unlimited_regular():
    p = base_group(1663, "Alakazam")  # 1st Edition Holofoil + Unlimited Holofoil
    for fe in (True, False):
        r = match(p, fe, False, True, group_name="Base Set (Shadowless)")
        assert (r[0], r[1]) == (None, INC) and "Shadowless" in r[2]
    # sem o nome de grupo o modulo nao adivinha: cabe ao chamador passar group_name
    assert match(p, True, False, True)[:2] == ("1stEditionHolofoil", OK)


def test_i2_mistura_sem_rotulo_com_1st_unlimited_continua_incompativel_sintetico():
    prices = mk(holofoil=300.0, **{"1stEditionHolofoil": 5000.0})
    r = match(prices, False, False, True)
    assert (r[0], r[1]) == (None, INC)
    assert "sem rótulo" in r[2] and "holofoil" in r[2]
    # a oferta 1st Edition casa com a chave explicitamente 1st Edition
    assert match(prices, True, False, True)[:2] == ("1stEditionHolofoil", OK)


def test_i2_mistura_vale_mesmo_com_chave_1st_sem_preco_sintetico():
    prices = {"holofoil": {"market": 300.0}, "1stEditionHolofoil": {"market": 0}}
    assert match(prices, False, False, True)[1] == INC


# ---- item 3: _usable ---------------------------------------------------------

@pytest.mark.parametrize("val", [np.int64(3), np.float64(2.5), np.float32(1.5),
                                 Decimal("4.2"), 7, 0.01])
def test_i3_numeros_reais_sao_aceitos(val):
    r = match({"normal": {"market": val}}, False, False, False)
    assert (r[0], r[1]) == ("normal", OK)


@pytest.mark.parametrize("val", [True, False, np.bool_(True), float("inf"), float("-inf"),
                                 float("nan"), Decimal("NaN"), Decimal("Infinity"),
                                 np.float64("nan"), "5", None, 0, -1, [1]])
def test_i3_invalidos_sao_rejeitados(val):
    assert cv.available_keys({"normal": {"market": val}}) == []


# ---- item 4: encontrada sem preco -------------------------------------------

def test_i4_todas_as_chaves_com_market_zero_e_encontrada_sem_preco():
    prices = {"1stEdition": {"market": 0}, "unlimited": {"market": None}}
    r = match(prices, False, False, False)
    assert r[0] is None and r[1] == cv.SEM_PRECO != cv.NAO_ENCONTRADA
    assert "1stEdition" in r[2] and "unlimited" in r[2]


def test_i4_so_chaves_desconhecidas_e_incompativel_sintetico():
    r = match(mk(foo=1.0), False, False, False)
    assert r[1] == INC and "foo" in r[2]


# ---- item 5: subtype do tcgcsv fora do mapa ---------------------------------

def test_i5_subtype_desconhecido_nunca_levanta():
    assert cv.tcgcsv_variant("Cosmos Holofoil") == cv.DESCONHECIDO
    assert cv.tcgcsv_variant("Unlimited") == "unlimited"
    prices, ignored = cv.map_tcgcsv_prices([
        {"subTypeName": "Normal", "marketPrice": 1.0},
        {"subTypeName": "Cosmos Holofoil", "marketPrice": 9.0},
        {"subTypeName": None, "marketPrice": 2.0},
    ])
    assert prices == {"normal": {"market": 1.0}}
    assert ignored == ["Cosmos Holofoil", None]


def test_i5_mapa_so_tem_grafias_vistas_em_dado_real():
    visto = set()
    for inv in _load("tcgcsv_base_groups.json")["subtype_inventory"].values():
        visto |= set(inv)
    assert set(cv.TCGCSV_SUBTYPE_TO_VARIANT) == visto
    assert "1st Edition Normal" not in cv.TCGCSV_SUBTYPE_TO_VARIANT  # nunca visto


# ---- item 6: uid / cache key sem colisao -------------------------------------

def test_uid_separa_edicao_e_reverse():
    base = cv.offer_uid(1, "s", "Near Mint", False, False)
    assert base == "1:s:Near Mint:unl:std"
    assert cv.offer_uid(1, "s", "Near Mint", True, False) == "1:s:Near Mint:1st:std"
    assert cv.offer_uid(1, "s", "Near Mint", False, True).endswith(":unl:rev")
    assert len({base, cv.offer_uid(1, "s", "Near Mint", True, False),
                cv.offer_uid(1, "s", "Near Mint", False, True)}) == 3


def test_i6_uid_sem_colisao_por_dois_pontos():
    a = cv.offer_uid(1, "a:b", "NM", False, False)
    b = cv.offer_uid(1, "a", "b:NM", False, False)
    assert a != b
    assert cv.offer_uid(1, "a\\", ":NM", False, False) != cv.offer_uid(1, "a", "\\:NM", False, False)


def test_i6_uid_normaliza_tipo():
    assert cv.offer_uid(1, "s", "NM", False, False) == cv.offer_uid("1", "s", "NM", False, False)


def test_v16_chave_de_cache_e_versao():
    a = cv.price_cache_key("neo1", "9", "Lugia", True, False, True)
    b = cv.price_cache_key("neo1", "9", "Lugia", False, False, True)
    assert a != b and cv.PRICE_LOGIC_VERSION == "4" and a.startswith("pokemontcg:4:")
    assert cv.price_cache_key("neo1", "9", "Lugia", False, False, True) != \
        cv.price_cache_key("neo1", "9", "Lugia", False, False, False)  # is_holo na chave
    assert a != cv.price_cache_key("neo1", "9", "Lugia", True, True, True)


def test_i6_cache_key_sem_colisao_e_normaliza_tipo():
    assert cv.price_cache_key("a:b", "1", "x", False, False, False) != \
        cv.price_cache_key("a", "b:1", "x", False, False, False)
    assert cv.price_cache_key("neo1", 9, "Lugia", False, False, True) == \
        cv.price_cache_key("neo1", "9", "Lugia", False, False, True)


# ---- item 9: propriedade -----------------------------------------------------

_ALL_KEYS = ["normal", "holofoil", "reverseHolofoil", "1stEdition", "1stEditionHolofoil",
             "unlimited", "unlimitedHolofoil"]


def _all_price_sets():
    for n in range(len(_ALL_KEYS) + 1):
        for combo in itertools.combinations(_ALL_KEYS, n):
            yield {k: {"market": 1.0 + i} for i, k in enumerate(combo)}


def test_propriedade_nunca_ok_com_edicao_ou_acabamento_diferente():
    seen_ok = 0
    for prices in _all_price_sets():
        labeled = any(cv.PTCG_KEY_TO_CANON[k][0] for k in prices)
        for ed, fin in itertools.product(("1st", "unl"), ("normal", "holo", "reverse")):
            r = cv.match_reference_variant(prices, ed, fin)
            if r.status != OK:
                assert r.key is None and r.canon is None
                continue
            seen_ok += 1
            assert r.key in prices and cv.PTCG_KEY_TO_CANON[r.key] == r.canon
            c_ed, c_fin = r.canon
            assert c_fin == fin, (prices, ed, fin, r)
            if ed == "1st":
                assert c_ed == "1st", (prices, ed, fin, r)
            else:  # unl: rotulo unl, ou sem rotulo SO se nenhuma chave da carta e rotulada
                assert c_ed == "unl" or (c_ed == "" and not labeled), (prices, ed, fin, r)
    assert seen_ok > 100  # a varredura nao e vazia
