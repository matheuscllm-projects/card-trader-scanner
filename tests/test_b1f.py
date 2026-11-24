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
