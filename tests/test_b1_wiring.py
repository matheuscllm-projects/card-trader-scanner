"""B1 — liga ct_variants / ct_economics / ct_chase ao scanner (spec D1/D6/D8 + decisoes do dono).

Itens: 1 oferta (first_edition, uid) · 2 referencia por match_reference_variant ·
3 sem ref compativel (aba, soma) · 4 colunas XLSX · 5 validacao per-blueprint por edicao ·
6 margem via ct_economics · 7 chase unico · 8 vocabulario de raridade.
"""
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


# ───────────────────────── fixtures reais (spec 0.2) ─────────────────────────
NEO1_9 = {   # Lugia Rare Holo
    "id": "neo1-9", "name": "Lugia", "number": "9", "rarity": "Rare Holo",
    "set": {"id": "neo1", "releaseDate": "2000/12/16", "printedTotal": 111},
    "tcgplayer": {"url": "https://prices.pokemontcg.io/tcgplayer/neo1-9", "prices": {
        "1stEditionHolofoil": {"market": 1300.0, "low": 6100.0},
        "unlimitedHolofoil": {"market": 534.65}}},
}
NEO1_56 = {  # Cyndaquil Common
    "id": "neo1-56", "name": "Cyndaquil", "number": "56", "rarity": "Common",
    "set": {"id": "neo1", "releaseDate": "2000/12/16", "printedTotal": 111},
    "tcgplayer": {"url": "https://prices.pokemontcg.io/tcgplayer/neo1-56", "prices": {
        "1stEdition": {"market": 16.46}, "unlimited": {"market": 1.62}}},
}
EX1_ONLY_HOLO = {  # carta so com holofoil (8 em ex1) + oferta reverse
    "id": "ex1-9", "name": "Zzz", "number": "9", "rarity": "Rare Holo",
    "set": {"id": "ex1", "releaseDate": "2003/06/18", "printedTotal": 109},
    "tcgplayer": {"url": "https://x/ex1-9", "prices": {"holofoil": {"market": 20.0}}},
}


def _ptcg(tmp_path, card):
    prov = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    prov.cache = sc.Cache(db_path=tmp_path / "c.db")
    prov._search = lambda *a, **k: card
    return prov


def _price(prov, card, **kw):
    return prov.market_price_usd(card["name"], card["set"]["id"], card["number"], **kw)


# ───────────────── 1: oferta — first_edition e uid ─────────────────
def _raw_offer(bp, seller, cents, fe, rev=False, cond="Near Mint"):
    return {"id": bp * 100 + (7 if fe else 3) + (50 if rev else 0), "blueprint_id": bp, "quantity": 1,
            "price": {"cents": cents, "currency": "USD"}, "graded": False,
            "user": {"username": seller, "can_sell_via_hub": True, "user_type": "professional"},
            "expansion": {"code": "n1", "name_en": "Neo Genesis", "id": 1482},
            "properties_hash": {"condition": cond, "collector_number": "059", "first_edition": fe,
                                "pokemon_language": "en", "pokemon_reverse": rev,
                                "pokemon_rarity": "Common"}}


def _plain_scanner():
    s = sc.Scanner.__new__(sc.Scanner)
    s.usd_brl, s.eur_brl = 5.0, 5.9
    s.stats = {"skipped_exotic_currency": 0}
    return s


@pytest.mark.parametrize("name,num,unl,first", [("Gligar", "059", 253, 315),
                                                ("Ledyba", "063", 264, 644),
                                                ("Snubbull", "074", 105, 277)])
def test_real_n1_pairs_first_edition_and_unlimited_are_two_listings(name, num, unl, first):
    s = _plain_scanner()
    bp = {1: {"name": name, "fixed_properties": {"pokemon_rarity": "Common"}}}
    a, b = _raw_offer(1, "sellerX", unl, False), _raw_offer(1, "sellerX", first, True)
    la, lb = s._parse_listing(a, bp), s._parse_listing(b, bp)
    assert la.first_edition is False and lb.first_edition is True
    assert la.uid != lb.uid
    assert la.uid == cv.offer_uid(1, "sellerX", "Near Mint", False, False)


def test_reverse_and_normal_same_seller_do_not_merge():
    s = _plain_scanner()
    bp = {1: {"name": "X", "fixed_properties": {}}}
    n = s._parse_listing(_raw_offer(1, "S", 100, False, rev=False), bp)
    r = s._parse_listing(_raw_offer(1, "S", 120, False, rev=True), bp)
    assert n.uid != r.uid


def test_dedup_in_scan_keeps_both_editions(tmp_path, monkeypatch):
    base = _cards(1, set_code="n1")[0]
    l1 = dataclasses.replace(base, product_id=1, first_edition=False, price_brl=100.0)
    l2 = dataclasses.replace(base, product_id=2, first_edition=True, price_brl=300.0)
    prices = {("n1", base.collector_number): 50.0}
    scanner = _scanner_with(prices, None, [l1, l2], tcgcsv_fallback=False, max_misses=0)
    opps, done, _ = _run(scanner, [l1, l2], tmp_path, monkeypatch)
    assert scanner.stats["listings_after_filters"] == 2
    assert done[0]["status"] != "no_coverage"


# ───────────────── 2: referencia por match_reference_variant ─────────────────
def test_v1_v2_holo_each_edition_prices_itself(tmp_path):
    prov = _ptcg(tmp_path, NEO1_9)
    assert _price(prov, NEO1_9, foil=False, rarity="Holo Rare", first_edition=False) == 534.65
    assert prov.last_variant_used == "unlimitedHolofoil" and prov.last_ref_status == cv.OK
    assert _price(prov, NEO1_9, foil=False, rarity="Holo Rare", first_edition=True) == 1300.0
    assert prov.last_variant_used == "1stEditionHolofoil"


def test_v3_common_unlimited_and_first(tmp_path):
    prov = _ptcg(tmp_path, NEO1_56)
    assert _price(prov, NEO1_56, rarity="Common", first_edition=False) == 1.62
    assert prov.last_variant_used == "unlimited"
    assert _price(prov, NEO1_56, rarity="Common", first_edition=True) == 16.46
    assert prov.last_variant_used == "1stEdition"


def test_reverse_without_reverse_key_is_incompatible_never_holofoil(tmp_path):
    prov = _ptcg(tmp_path, EX1_ONLY_HOLO)
    assert _price(prov, EX1_ONLY_HOLO, foil=True, rarity="Holo Rare") is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
    assert "Reverse" in prov.last_ref_reason and prov.last_available_keys == ["holofoil"]


def test_first_edition_offer_never_gets_unlimited_price(tmp_path):
    card = json.loads(json.dumps(NEO1_56))
    card["tcgplayer"]["prices"] = {"unlimited": {"market": 1.62}}
    prov = _ptcg(tmp_path, card)
    assert _price(prov, card, rarity="Common", first_edition=True) is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
    assert prov.last_tcg_url   # a pagina da carta fica p/ o operador conferir


def test_cache_key_distinguishes_edition_and_cached_hit_is_exact(tmp_path):
    prov = _ptcg(tmp_path, NEO1_9)
    _price(prov, NEO1_9, rarity="Holo Rare", first_edition=False)
    _price(prov, NEO1_9, rarity="Holo Rare", first_edition=True)
    prov._search = lambda *a, **k: pytest.fail("deveria vir do cache")
    assert _price(prov, NEO1_9, rarity="Holo Rare", first_edition=False) == 534.65
    assert _price(prov, NEO1_9, rarity="Holo Rare", first_edition=True) == 1300.0
    keys = [r[0] for r in prov.cache.db.execute("SELECT key FROM price_cache")]
    assert len(keys) == 2 and all(f":{cv.PRICE_LOGIC_VERSION}:" in k for k in keys)


def _tcgcsv_n1(groups, products, prices):
    prov = _provider_with(groups, products, prices)
    return prov


def test_tcgcsv_reads_editions_and_shadowless_group_is_never_a_reference():
    groups = [{"groupId": 1396, "name": "Neo Genesis", "abbreviation": "N1", "publishedOn": "2000-12-16T00:00:00"}]
    products = _fake_products({1: "059/111"})
    prices = _fake_prices([(1, "1st Edition", 1.93), (1, "Unlimited", 0.81)])
    prov = _provider_with(groups, products, prices)
    assert prov.prefill_set("n1", ["neo1"], "Neo Genesis")
    assert prov.market_price_usd("Gligar", "n1", "059/111", rarity="Common", first_edition=False) == 0.81
    assert prov.last_variant_used == "unlimited" and prov.last_price_source == "tcgcsv"
    assert prov.market_price_usd("Gligar", "n1", "059/111", rarity="Common", first_edition=True) == 1.93
    # grupo Shadowless: nunca referencia
    g2 = [{"groupId": 604, "name": "Base Set (Shadowless)", "abbreviation": "BS", "publishedOn": "1999-01-09T00:00:00"}]
    p2 = _provider_with(g2, _fake_products({1: "004/102"}), _fake_prices([(1, "Unlimited Holofoil", 300.0)]))
    assert p2.prefill_set("bs", ["base1"], "Base Set")
    assert p2.market_price_usd("Charizard", "bs", "004/102", rarity="Holo Rare") is None
    assert p2.last_ref_status == cv.INCOMPATIVEL and "Shadowless" in p2.last_ref_reason


def test_tcgcsv_base_set_normal_only_first_edition_is_incompatible():
    groups = [{"groupId": 604, "name": "Base Set", "abbreviation": "BS", "publishedOn": "1999-01-09T00:00:00"}]
    prov = _provider_with(groups, _fake_products({1: "058/102"}), _fake_prices([(1, "Normal", 5.0)]))
    assert prov.prefill_set("bs", ["base1"], "Base Set")
    assert prov.market_price_usd("Pikachu", "bs", "058/102", rarity="Common", first_edition=True) is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
    assert prov.market_price_usd("Pikachu", "bs", "058/102", rarity="Common", first_edition=False) == 5.0


def test_old_ladder_and_exclusion_are_gone():
    assert "_EXCLUDED_TCG_VARIANTS" not in SRC
    assert "def select_tcgplayer_variant_price" not in SRC
    assert "def _rarity_is_holo" not in SRC
    assert not hasattr(sc, "TCGCSV_SUBTYPE_TO_VARIANT") or sc.TCGCSV_SUBTYPE_TO_VARIANT is cv.TCGCSV_SUBTYPE_TO_VARIANT


# ───────────────── 3: sem ref compativel — aba, soma, sem miss ─────────────────
def _incompat_scan(tmp_path, monkeypatch, n=6, max_misses=2, fe=True):
    listings = [dataclasses.replace(l, first_edition=fe) for l in _cards(n, set_code="bs")]
    card_prices = {}
    scanner = _scanner_with(card_prices, None, listings, tcgcsv_fallback=False, max_misses=max_misses)

    def price_fn(card_name, set_code, num, foil=False, rarity=None, first_edition=False, **kw):
        p = scanner.pricing
        p.last_ref_status, p.last_ref_reason = cv.INCOMPATIVEL, "sem preço 1st Edition (disponíveis: normal)"
        p.last_available_keys = ["normal"]
        p.last_offer_variant = (cv.ED_1ST, cv.FIN_NORMAL)
        p.last_tcg_url = "https://www.tcgplayer.com/product/9"
        return None

    scanner.pricing.market_price_usd.side_effect = price_fn
    res = _run(scanner, listings, tmp_path, monkeypatch)
    return scanner, listings, res


def test_incompatible_reference_is_not_an_opportunity_and_not_a_miss(tmp_path, monkeypatch):
    scanner, listings, (opps, done, skip) = _incompat_scan(tmp_path, monkeypatch)
    assert opps == [] and skip == {}                         # nada de skip-list
    assert done[0]["status"] != "no_coverage"                # nao e miss de cobertura
    assert len(scanner.noref_rows) == 6
    r = scanner.noref_rows[0]
    assert r["motivo"].startswith("sem preço 1st Edition") and r["chaves"] == "normal"
    assert r["edicao"] == "1st Edition" and r["link"] and r["card"] and r["number"] and r["ct_price_brl"]
    assert len(scanner.unpriced_rows) == 0
    cp = [json.loads(x) for x in (tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([c for c in cp if c.get("_type") == "noref"]) == 6


def test_sum_priced_plus_unpriced_plus_noref_equals_total_everywhere(tmp_path, monkeypatch):
    # 2 precificadas, 1 sem ref compativel, 1 sem preco (miss), 2 nao alcancadas por excecao
    listings = _cards(6, set_code="bs")
    scanner = _scanner_with({("bs", listings[0].collector_number): 50.0,
                             ("bs", listings[1].collector_number): 50.0}, None, listings,
                            tcgcsv_fallback=False, max_misses=0)
    base = scanner.pricing.market_price_usd.side_effect

    def price_fn(card_name, set_code, num, foil=False, rarity=None, first_edition=False, **kw):
        p = scanner.pricing
        p.last_ref_status = ""
        if num == listings[2].collector_number:
            p.last_ref_status, p.last_ref_reason, p.last_available_keys = cv.INCOMPATIVEL, "x", ["normal"]
            return None
        if num == listings[4].collector_number:
            raise KeyboardInterrupt()
        return base(card_name, set_code, num, foil=foil, rarity=rarity)

    scanner.pricing.market_price_usd.side_effect = price_fn
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    n_un = len([r for r in scanner.unpriced_rows if r["set"] == "bs"])
    assert len(opps) + n_un + len(scanner.noref_rows) == 6, (len(opps), n_un, len(scanner.noref_rows))
    assert len(scanner.noref_rows) == 1 and scanner.interrupted is True


def test_card_found_without_usable_price_has_its_own_reason(tmp_path):
    card = json.loads(json.dumps(NEO1_56))
    card["tcgplayer"]["prices"] = {"unlimited": {"market": 0}}
    prov = _ptcg(tmp_path, card)
    assert _price(prov, card, rarity="Common") is None
    assert prov.last_ref_status == cv.SEM_PRECO


# ───────────────── 4: colunas do XLSX ─────────────────
def _xlsx_rows(tmp_path, opps, noref=None):
    from openpyxl import load_workbook
    out = tmp_path / "x.xlsx"
    sc.export_xlsx(opps, {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3, noref=noref)
    wb = load_workbook(out)
    ws = wb["Oportunidades"]
    head = [c.value for c in ws[1]]
    return wb, head, [{h: c.value for h, c in zip(head, r)} for r in ws.iter_rows(min_row=2)]


def _opp(**kw):
    l = _cards(1, set_code="n1")[0]
    o = sc.Opportunity(listing=l, tcg_market_usd=10.0, tcg_market_brl=50.0, ct_price_brl=20.0,
                       margin_pct=0.6, margin_brl=30.0, estimated_shipping_brl=0.5,
                       net_margin_pct=0.5)
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_xlsx_edition_values_and_compatible_flag(tmp_path):
    rows = _xlsx_rows(tmp_path, [
        _opp(edition=cv.ED_1ST, finish=cv.FIN_HOLO, ref_compatible=True, price_variant_used="1stEditionHolofoil"),
        _opp(edition=cv.ED_UNL, finish=cv.FIN_NORMAL, ref_compatible=True),
        _opp(edition=cv.ED_NONE, finish=cv.FIN_REVERSE, ref_compatible=True),
        _opp(edition=cv.ED_UNL, finish=cv.FIN_NORMAL, ref_compatible=False)])[2]
    assert [r["Edição"] for r in rows] == ["1st Edition", "Unlimited", cv.ED_NONE_LABEL, "Unlimited"]
    assert cv.ED_NONE_LABEL not in ("", "Unlimited", "1st Edition")
    assert [r["Acabamento"] for r in rows] == ["Holo", "Normal", "Reverse", "Normal"]
    assert [r["Ref Compatível"] for r in rows] == ["Sim", "Sim", "Sim", None] or rows[3]["Ref Compatível"] in (None, "", "Não")
    assert rows[0]["Variant"] == "1stEditionHolofoil"


def test_xlsx_sem_ref_compativel_sheet_has_the_contract_columns(tmp_path):
    row = {"set": "bs", "set_name": "Base Set", "card": "Pikachu", "number": "058/102", "rarity": "Common",
           "edicao": "1st Edition", "acabamento": "Normal", "ct_price_brl": 12.0, "currency": "BRL",
           "qty": 1, "seller": "s", "link": "https://www.cardtrader.com/cards/1",
           "tcg_url": "https://www.tcgplayer.com/product/9", "source": "tcgcsv",
           "motivo": "sem preço 1st Edition", "chaves": "normal", "status": cv.INCOMPATIVEL}
    wb, _, _ = _xlsx_rows(tmp_path, [_opp()], noref=[row])
    ws = wb["Sem Ref Compatível"]
    head = [c.value for c in ws[1]]
    for need in ("Card Name", "Set", "Nº", "Edição", "Acabamento", "Link CardTrader", "Motivo"):
        assert need in head, head
    vals = {h: c.value for h, c in zip(head, ws[2])}
    assert vals["Card Name"] == "Pikachu" and vals["Motivo"].startswith("sem preço 1st")


def test_postprocess_reads_the_new_edition_label_and_empty_stays_unknown():
    import cardtrader_postprocess as pp
    import pandas as pd
    for label, expect in (("1st Edition", cv.ED_1ST), ("Unlimited", cv.ED_UNL),
                          (cv.ED_NONE_LABEL, cv.ED_UNL)):
        ed, mot = pp._row_edition(pd.Series({"edicao": label}))
        assert ed == expect and mot is None, (label, ed, mot)
    ed, mot = pp._row_edition(pd.Series({"edicao": ""}))
    assert ed is None and mot


# ───────────────── 5: validacao per-blueprint por edicao ─────────────────
def _val_opp(fe):
    o = _opp()
    o.listing = dataclasses.replace(o.listing, first_edition=fe, seller_username="S", condition="Near Mint", foil=False)
    o.edition, o.finish = (cv.ED_1ST if fe else cv.ED_UNL), cv.FIN_NORMAL
    return o


def _pb(cents, fe=None, cond="Near Mint"):
    ph = {"condition": cond, "pokemon_reverse": False}
    if fe is not None:
        ph["first_edition"] = fe
    return {"user": {"username": "S"}, "price_cents": cents, "price_currency": "BRL", "properties_hash": ph}


def _validator():
    s = _plain_scanner()
    s.hub_fee_rate = 0.06
    s.costs = sc.Costs() if hasattr(sc, "Costs") else None
    return s


def test_per_blueprint_only_matches_same_edition():
    s = _validator()
    o = _val_opp(True)
    s._enrich_validation(o, [_pb(2000, fe=False), _pb(3000, fe=True)])
    assert o.live_price_brl == 30.0
    o2 = _val_opp(False)
    s._enrich_validation(o2, [_pb(3000, fe=True)])
    assert o2.validation_status == "STALE"          # so havia a outra edicao


def test_per_blueprint_without_first_edition_field_is_not_confirmable():
    s = _validator()
    o = _val_opp(True)
    s._enrich_validation(o, [_pb(2000, fe=None)])
    assert o.validation_status == "NAO_CONFIRMAVEL"
    assert o.live_price_brl is None and "first_edition" in o.validation_reason


# ───────────────── 6: margem so via ct_economics ─────────────────
def test_cut_is_margin_on_sale_not_roi(tmp_path, monkeypatch):
    # compra 75 / ref 100 -> margem 25% (ROI 33%): NAO passa em 30%
    l = _cards(1, set_code="n1")[0]
    l = dataclasses.replace(l, price_brl=75.0)
    scanner = _scanner_with({("n1", l.collector_number): 20.0}, None, [l], tcgcsv_fallback=False, max_misses=0)
    scanner.threshold = 0.30
    scanner.usd_brl = 5.0
    opps, _, _ = _run(scanner, [l], tmp_path, monkeypatch)
    assert len(opps) == 1 and opps[0].below_threshold is True
    assert opps[0].margin_pct == pytest.approx(0.25)


def test_no_inline_margin_math_in_the_scanner():
    assert "ct_economics" in SRC
    assert not re.search(r"\(\s*tcg_brl\s*-\s*custo_brl\s*\)\s*/\s*tcg_brl", SRC)
    assert not re.search(r"custo_real\s*=", SRC)
    assert "hub_fee_brl" not in SRC


def test_validated_price_is_not_charged_hub_twice():
    s = _validator()
    o = _val_opp(False)
    o.tcg_market_brl = 100.0
    s._enrich_validation(o, [_pb(7000, fe=False)])
    assert o.real_margin_pct == pytest.approx(0.30)     # (100-70)/100, Hub ja embutido no checkout


# ───────────────── 7: chase unico ─────────────────
def test_chase_has_a_single_owner():
    import ct_chase
    assert "CHASE_TIER_PATTERNS =" not in SRC and "def classify_chase_tier" not in SRC
    assert sc.classify_chase_tier is ct_chase.classify_chase_tier
    assert sc.CHASE_ONLY_TIERS is ct_chase.CHASE_ONLY_TIERS


# ───────────────── 8: vocabulario de raridade (evidencia real em fixture) ─────────────────
def test_rarity_vocabulary_from_real_cardtrader_data_is_recognised():
    ev = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "ct_rarity_evidence.json")
                    .read_text(encoding="utf-8"))
    for r in ev["holo"]:
        assert cv.holo_detection(r, set_released=ev["set_released"]).is_holo, r
    for r in ev["not_holo"]:
        assert not cv.holo_detection(r, set_released=ev["set_released"]).is_holo, r
