"""B1f — conflito de rótulo, propriedade do caminho inteiro, idade da referência, fontes
consultadas, data de lançamento inválida, baixas."""
from __future__ import annotations

import itertools
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
from test_b1e import _real_provider  # noqa: E402

_EV = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1f_evidence.json").read_text(encoding="utf-8"))
_EV1 = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1e_evidence.json").read_text(encoding="utf-8"))


# ───────── 1: conflito de rótulo (dado real tcgcsv 2026-11-24) ─────────
@pytest.mark.parametrize("ct_rarity", ["Rare", "Common"])
def test_exploud_conflict_is_incompatible_not_priced_by_the_dearer_holo(ct_rarity):
    prov = _real_provider("em", 1410, "EX Emerald", "2005-05-09T00:00:00", _EV["exploud"])
    assert prov.market_price_usd("Exploud", "em", "3/106", rarity=ct_rarity) is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
    assert "raridades em conflito" in prov.last_ref_reason
    assert ct_rarity in prov.last_ref_reason and "Holo Rare" in prov.last_ref_reason


def test_exploud_agreeing_labels_still_match():
    prov = _real_provider("em", 1410, "EX Emerald", "2005-05-09T00:00:00", _EV["exploud"])
    assert prov.market_price_usd("Exploud", "em", "3/106", rarity="Holo Rare") == 28.71
    assert prov.market_price_usd("Exploud", "em", "3/106", foil=True, rarity="Common") == 49.0   # reverse: oferta decide


def test_card_that_only_exists_as_holo_is_holo_even_if_cardtrader_says_rare():
    v = _real_provider("viv", 2701, "SWSH04: Vivid Voltage", "2020-11-13T00:00:00", _EV1["viv_138"])
    assert v.market_price_usd("Rayquaza", "viv", "138/185", rarity="Rare") == 25.0           # Amazing Rare, sem Normal
    n = _real_provider("n3", 1389, "Neo Revelation", "2001-09-21T00:00:00", _EV["suicune"])
    assert n.market_price_usd("Suicune", "n3", "14/64", rarity="Rare") == 223.82            # só chaves holo
    assert n.last_variant_used == "unlimitedHolofoil"


def test_regirock_ct_holo_reference_not_holo_stays_incompatible():
    rows = [{"pid": 9, "name": "Regirock", "number": "088/185", "rarity": "Rare",
             "prices": [["Normal", 0.2], ["Reverse Holofoil", 0.3]]}]
    prov = _real_provider("viv", 2701, "SWSH04: Vivid Voltage", "2020-11-13T00:00:00", rows)
    assert prov.market_price_usd("Regirock", "viv", "088/185", rarity="Holo Rare") is None
    assert prov.last_ref_status == cv.INCOMPATIVEL


# ───────── 2: propriedade do CAMINHO INTEIRO ─────────
_CT = [None, "", "Common", "Uncommon", "Rare", "Holo Rare", "Rare Holo", "Promo", "Ultra Rare", "Secret Rare",
       "Illustration Rare", "Special Illustraion Rare"]
_REF = [None, "Common", "Rare", "Holo Rare", "Amazing Rare", "Secret Rare", "Ultra Rare"]
_KEYSETS = ([frozenset(c) for n in (1, 2, 3) for c in itertools.combinations(
    ["normal", "holofoil", "reverseHolofoil"], n)]
    + [frozenset(c) for n in (1, 2, 3, 4) for c in itertools.combinations(
        ["unlimited", "unlimitedHolofoil", "1stEdition", "1stEditionHolofoil"], n)])


def test_property_full_path_never_contradicts_a_conclusive_cardtrader_rarity():
    """Nunca sai OK com chave cujo acabamento a raridade CT (conclusiva) contradiz enquanto o
    produto tem a chave do acabamento que ela indica."""
    checked = violations = 0
    for ct, ref, keys, rev, era, fe in itertools.product(
            _CT, _REF, _KEYSETS, (False, True), (None, "2002-01-01", "2024-05-01"), (False, True)):
        prices = {k: {"market": 1.0 + i} for i, k in enumerate(sorted(keys))}
        om = cv.match_offer(prices, fe, rev, ct, ref_rarity=ref, set_released=era)
        checked += 1
        if rev or om.match.status != cv.OK or not cv.rarity_conclusive(ct):
            continue
        want = cv.FIN_HOLO if cv.holo_detection(ct, set_released=era).is_holo else cv.FIN_NORMAL
        got = om.match.canon[1]
        exists = any(c[1] == want for c in cv._usable(prices).values())
        if got != want and exists:
            violations += 1
    assert checked > 20_000
    assert violations == 0


# ───────── 5: publishedOn inválido (carimbo do lote) ─────────
def test_group_published_on_with_the_batch_stamp_is_not_a_release_date():
    assert cv.valid_published_on("2005-05-09T00:00:00") == "2005-05-09"
    for bad in ("2026-11-23T20:00:05.735172Z", "", None, "lixo"):
        assert cv.valid_published_on(bad) is None


def test_pop_series_rare_does_not_become_holo_with_the_batch_stamp():
    pop = _EV["pop5"]
    prov = _real_provider("pop5", 1439, "POP Series 5", "2026-11-23T20:00:05.735172Z", pop)
    assert prov.market_price_usd("Double Rainbow Energy", "pop5", "004/017", rarity="Rare") == next(
        p for r in pop if r["number"] == "004/017" for s, p in r["prices"] if s == "Normal")
    assert prov.last_variant_used == "normal"


# ───────── 3: idade da referência ─────────
from unittest.mock import patch  # noqa: E402

import cardtrader_postprocess as pp  # noqa: E402
from test_b1b_delivery import _opp, _run_pp  # noqa: E402

_SCAN = {"scanned_at": "2026-11-24T04:51:58-03:00", "listings_fetched": 10, "listings_after_filters": 2}


def _mixed(tmp_path, extra=()):
    return _run_pp(tmp_path, [_opp(0, source="pokemontcg", data="2026-10-15", label="dado de", seller="a"),
                              _opp(1, source="tcgcsv", seller="b")], stats=_SCAN, extra_args=extra)


def test_footer_shows_oldest_newest_and_age_per_source_even_without_timezone(tmp_path):
    md, _ = _mixed(tmp_path)
    foot = [l for l in md.splitlines() if l.startswith("_Fontes das referências")][0]
    pk = foot.split("|")[0]
    assert "sem data do dado" not in pk                       # data sem fuso não é mais descartada
    assert "2026-10-15" in pk and "40 dias" in pk
    assert "mais antigo" in pk and "mais novo" in pk
    assert "tcgcsv" in foot and "h" in foot.split("|")[1]


def _row(**k):
    r = {"net_margin": 0.5, "lucro_liq": 100.0, "validation_status": "VALIDATED_REAL",
         "compra_inclui_hub": True, "ref_compativel": "Sim", "card_number": "1", "set_code": "n1"}
    r.update(k)
    return r


def test_stale_reference_is_never_compra_and_limit_is_configurable():
    cfg = pp.DecisionConfig()
    assert pp.classify_decision(_row(ref_age_dias=3), cfg, check_liquidity=False)[0] == "COMPRA"
    d, why = pp.classify_decision(_row(ref_age_dias=40), cfg, check_liquidity=False)
    assert d == "REVISAR" and "referência desatualizada (40 dias)" in why
    assert pp.classify_decision(_row(ref_age_dias=40), pp.DecisionConfig(max_ref_age_days=60),
                                check_liquidity=False)[0] == "COMPRA"


def test_stale_row_keeps_margin_and_carries_the_mark_in_the_table(tmp_path):
    md, out = _mixed(tmp_path)
    row = [l for l in md.splitlines() if "| a |" in l or "/a" in l][:1]
    stale = [l for l in md.splitlines() if "referência desatualizada (40 dias)" in l and l.startswith("|")]
    fresh = [l for l in md.splitlines() if l.startswith("| 2 |") or l.startswith("| 1 |")]
    assert len(stale) == 1 and "80%" in stale[0]              # margem continua exibida
    assert all("desatualizada" not in l for l in fresh if l not in stale)


def test_max_ref_age_flag_exists_with_owner_note(tmp_path):
    md, _ = _mixed(tmp_path, extra=("--max-ref-age-days", "60"))
    assert "desatualizada" not in md.split("_Fontes")[0]
    import io, contextlib
    buf = io.StringIO()
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "--help"]), contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit):
            pp.main()
    assert "--max-ref-age-days" in buf.getvalue() and "dono" in buf.getvalue()


def test_scanner_swaps_a_stale_main_reference_for_a_fresher_tcgcsv_one():
    from test_b1e import _build, _all_rows, EXP
    s, listings = _build(5, _all_rows(5), lambda i: 99.0)
    s.pricing.last_ref_data_at = "2020-01-01"                 # pokemontcg.io com dado velho
    s.max_ref_age_days = 7.0
    opps = list(s.scan_expansion(EXP))
    assert len(opps) == 5
    assert all(o.price_source == "tcgcsv" and o.tcg_market_usd != 99.0 for o in opps)
    assert all("pokemontcg" in o.ref_swap and "tcgcsv" in o.ref_swap and "2020-01-01" in o.ref_swap for o in opps)
    fresh, _l = _build(5, _all_rows(5), lambda i: 99.0)
    fresh.pricing.last_ref_data_at = None
    fresh.max_ref_age_days = 7.0
    assert all(o.price_source != "tcgcsv" and o.ref_swap == "" for o in fresh.scan_expansion(EXP))
