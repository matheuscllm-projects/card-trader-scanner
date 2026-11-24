"""B1e — disjuntor da fonte por oferta, desfecho pela cobertura FINAL, resumo do run."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_scanner as sc  # noqa: E402
from test_set_outcomes import _cards  # noqa: E402
from test_tcgcsv_fallback import (  # noqa: E402
    _fake_groups, _fake_prices, _fake_products, _provider_with, _scanner_with,
)

EXP = {"id": 1, "code": "asc", "name": "Ascended Heroes"}


def _build(n, tcgcsv_rows, price_fn, breaker="default", per_set_timeout=0):
    """Scanner com a fonte principal = `price_fn(i)` (i = nº da chamada, 0-based; devolve USD,
    None ou levanta) e o tcgcsv real (fake de rede) com `tcgcsv_rows`."""
    listings = [dataclasses.replace(l, rarity="Holo Rare") for l in _cards(n, set_code="asc")]
    tcgcsv = _provider_with(_fake_groups(), _fake_products({k: f"{k:03d}/100" for k in range(1, n + 1)}),
                            _fake_prices(tcgcsv_rows))
    s = _scanner_with({}, tcgcsv, listings, tcgcsv_fallback=True, max_misses=40)
    s.per_set_timeout_s = per_set_timeout
    s.language = "en"
    calls = []

    def fn(*a, **k):
        i = len(calls)
        calls.append(i)
        return price_fn(i)
    s.pricing.market_price_usd.side_effect = fn
    s.pricing.probe = MagicMock(return_value=False)
    s._calls = calls
    by_pid = {l.product_id: l for l in listings}
    s.ct.list_blueprints = MagicMock(return_value=[{"id": l.blueprint_id, "name": l.card_name} for l in listings])
    s.ct.list_listings_by_expansion = MagicMock(return_value=[
        {"id": l.product_id, "blueprint_id": l.blueprint_id} for l in listings])
    s._parse_listing = MagicMock(side_effect=lambda raw, idx: by_pid.get(raw["id"]))
    s._passes_filters = MagicMock(return_value=True)
    if breaker == "off":
        s.breaker = None
    elif breaker != "default":
        s.breaker = breaker
    return s, listings


def _flaky_60(i):
    """5xx em 60% das chamadas (3 de cada 5), o resto devolve preço."""
    if i % 5 < 3:
        raise requests.Timeout("pokemontcg.io: status 502 persistente após 3 tentativas")
    return 55.0


def _all_rows(n):
    return [(k, "Unlimited Holofoil", 40.0 + k) for k in range(1, n + 1)]


# ───────── 1: disjuntor ─────────
def test_breaker_unit_opens_on_failure_rate_and_on_latency():
    t = [0.0]
    b = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=10.0, probe_every_s=60.0, clock=lambda: t[0])
    for ok in (True, True, True, True, True):
        b.record(ok, 0.2)
    assert not b.is_open
    b.record(False, 0.2)                                   # 1/6 falhas: continua fechado
    assert not b.is_open
    b2 = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=10.0, clock=lambda: t[0])
    for ok in (False, False, False, True, True, False):
        b2.record(ok, 0.2)
    assert b2.is_open and b2.fail_count == 4 and b2.sample_count == 6
    b3 = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=10.0, clock=lambda: t[0])
    for _ in range(6):
        b3.record(True, 12.0)                               # sem falha, mas lenta demais
    assert b3.is_open


def test_run_switches_to_tcgcsv_after_few_offers_not_after_8_minutes(tmp_path):
    s, listings = _build(100, _all_rows(100), _flaky_60)
    opps = list(s.scan_expansion(EXP))
    assert len(s._calls) <= 10, len(s._calls)              # trocou de fonte depois de POUCAS ofertas
    assert len(opps) == 100 and s._set_status == "complete"
    assert sum(1 for o in opps if getattr(o, "price_source", None) == "tcgcsv") >= 90
    assert s.breaker.is_open


def test_next_sets_start_on_tcgcsv_and_return_when_the_source_recovers():
    t = [0.0]
    b = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=15.0, probe_every_s=0.0, clock=lambda: t[0])
    state = {"healthy": False}

    def price(i):
        if not state["healthy"] and i % 5 < 3:
            raise requests.Timeout("502")
        return 55.0
    s, listings = _build(30, _all_rows(30), price, breaker=b)
    snaps = []

    def probe():
        snaps.append(len(s._calls))
        ok = len(snaps) >= 2                               # 1ª sonda (início do set 2) falha; a 2ª (set 3) volta
        if ok:
            state["healthy"] = True
        return ok
    s.pricing.probe = probe
    s.scan([EXP, EXP, EXP])
    assert len(snaps) == 2
    assert snaps[1] == snaps[0], "set 2 não pode ter chamado a fonte principal (breaker aberto, sonda falhou)"
    outs = s.set_outcomes
    assert [o["status"] for o in outs] == ["complete"] * 3
    assert outs[1]["by_source"].get("pokemontcg", 0) == 0 and outs[1]["by_source"]["tcgcsv"] == 30
    assert outs[2]["by_source"]["pokemontcg"] == 30        # voltou à fonte principal
    assert len(s._calls) > snaps[1]
    assert not b.is_open


def test_breaker_is_logged_in_summary_and_set_note(tmp_path):
    s, listings = _build(60, _all_rows(60), _flaky_60)
    s.scan([EXP])
    text = "\n".join(s.run_summary_lines())
    assert "pokemontcg.io degradada às" in text and "após 4 falhas em 6" in text
    assert "1 sets atendidos pelo tcgcsv" in text or "1 set atendido pelo tcgcsv" in text
    assert "disjuntor" in (s.set_outcomes[0]["note"] or "")


def test_breaker_never_writes_skip_list_nor_changes_matching(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    s, listings = _build(30, [(k, "1st Edition Holofoil", 9.0) for k in range(1, 31)], _flaky_60)
    s.ignore_skip_list = False
    s.scan([EXP])
    assert not (tmp_path / "skip.json").exists()
    # regra exata: o tcgcsv só tem 1st Edition; as ofertas são Unlimited -> sem referência compatível
    assert len(s.noref_rows) >= 25 and s.set_outcomes[0]["status"] == "complete"


# ───────── 2: desfecho pela cobertura final ─────────
def _fst_rows():
    rows = []
    for k in range(1, 253):
        rows.append((k, "Unlimited Holofoil" if k <= 221 else "1st Edition Holofoil", 30.0 + k))
    return rows


def test_fst_primary_down_221_priced_31_noref_is_complete_with_note():
    s, listings = _build(252, _fst_rows(), lambda i: (_ for _ in ()).throw(requests.Timeout("502")),
                         breaker="off")
    s.scan([EXP])
    o = s.set_outcomes[0]
    assert o["status"] == "complete", o
    assert len(s.noref_rows) == 31 and s.unpriced_rows == []
    assert "fonte principal falhou" in o["note"] and "tcgcsv" in o["note"]
    assert o["by_source"] == {"pokemontcg": 0, "tcgcsv": 221}
    assert o["noref"] == 31 and o["status"] != "operational_failure"


def test_timeout_abort_with_full_rescue_is_complete(monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(sc.time, "monotonic", lambda: t["now"])
    s, listings = _build(20, _all_rows(20), lambda i: 55.0, breaker="off", per_set_timeout=480)

    def slow(i):
        t["now"] += 100.0                                  # 5 ofertas = estoura os 480 s
        return 55.0
    s.pricing.market_price_usd.side_effect = lambda *a, **k: slow(0)
    s.scan([EXP])
    o = s.set_outcomes[0]
    assert o["status"] == "complete", o                    # tudo terminou precificado
    assert "fonte principal falhou" in o["note"]


def test_teu_one_offer_without_valid_answer_is_operational_failure_listing_it():
    s, listings = _build(10, _all_rows(10), lambda i: (_ for _ in ()).throw(requests.Timeout("502")),
                         breaker="off")
    real = s.tcgcsv.market_price_usd
    n = {"i": 0}

    def flaky(*a, **k):
        n["i"] += 1
        if n["i"] == 4:
            raise RuntimeError("boom")
        return real(*a, **k)
    s.tcgcsv.market_price_usd = flaky
    s.scan([EXP])
    o = s.set_outcomes[0]
    assert o["status"] == "operational_failure", o
    assert [r["reason"] for r in s.unpriced_rows] == ["falha_operacional"]
    assert o["by_source"]["tcgcsv"] == 9


def test_not_reached_offer_still_fails_the_set():
    s, listings = _build(10, _all_rows(10), lambda i: 55.0, breaker="off")
    s.tcgcsv_fallback = False                              # sem resgate: as não alcançadas ficam pendentes
    s.per_set_timeout_s = 0
    s.mass_pricing_failure_min_sample = 3
    s.pricing.market_price_usd.side_effect = lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("x"))
    s.scan([EXP])
    assert s.set_outcomes[0]["status"] == "operational_failure"


# ───────── 4: resumo do run ─────────
def test_ptcg_get_counts_5xx_retries_and_probe_is_cheap(tmp_path, monkeypatch):
    monkeypatch.setattr(sc.time, "sleep", lambda *_: None)
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.cache = sc.Cache(db_path=tmp_path / "c.db")
    p.delay, p._last_call = 0.0, 0.0
    r500 = MagicMock(status_code=500, headers={})
    p.session = MagicMock()
    p.session.get.return_value = r500
    with pytest.raises(requests.Timeout):
        p._ptcg_get({"q": "x"})
    assert p.retry_5xx == 3
    p.session.get.reset_mock()
    assert p.probe() is False and p.session.get.call_count == 1      # sonda = 1 chamada, sem retry
    p.session.get.return_value = MagicMock(status_code=200)
    assert p.probe() is True
    p.session.get.side_effect = requests.ConnectionError("x")
    assert p.probe() is False


def test_run_summary_has_source_totals_retries_time_per_set_and_health_sentence():
    s, listings = _build(60, _all_rows(60), _flaky_60)
    s.pricing.retry_5xx = 852
    s.scan([EXP])
    text = "\n".join(s.run_summary_lines())
    assert "Preços por fonte:" in text and "tcgcsv" in text and "pokemontcg" in text
    assert "852 retries por 5xx" in text
    assert "Tempo por set:" in text and "asc" in text
    assert s.set_outcomes[0]["elapsed_s"] >= 0
    assert "Sets atendidos por resgate" in text


# ───────── 3: det / fst / viv com dado real (fixture = tcgcsv 2026-11-24) ─────────
import json as _json  # noqa: E402

import ct_variants as cv  # noqa: E402

_EV = _json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1e_evidence.json").read_text(encoding="utf-8"))


def _real_provider(code, group_id, name, published, rows):
    """tcgcsv fake com as linhas REAIS (número, raridade do produto, subtypes+preços)."""
    products = {"results": [
        {"productId": r["pid"], "name": r["name"], "extendedData": (
            [{"name": "Number", "value": r["number"]}]
            + ([{"name": "Rarity", "value": r["rarity"]}] if r.get("rarity") else []))}
        for r in rows]}
    prices = {"results": [
        {"productId": r["pid"], "subTypeName": sub, "marketPrice": mkt, "lowPrice": mkt, "midPrice": mkt}
        for r in rows for sub, mkt in r["prices"]]}
    groups = [{"groupId": group_id, "name": name, "abbreviation": code.upper(), "publishedOn": published}]
    prov = _provider_with(groups, products, prices)
    assert prov.prefill_set(code, [code], name)
    return prov


def test_evidence_det_is_holofoil_only_in_all_18_cards():
    """A base de HOLO_ONLY_SETS['det']: 18/18 cartas só têm Holofoil (nenhum Normal/Reverse)."""
    assert len(_EV["det"]) == 18
    assert all([s for s, _ in r["prices"]] == ["Holofoil"] for r in _EV["det"])
    assert "det" in cv.HOLO_ONLY_SETS


def test_det_promo_offer_matches_the_holofoil_reference():
    prov = _real_provider("det", 2409, "Detective Pikachu", "2019-04-05T00:00:00", _EV["det"])
    px = prov.market_price_usd("Charizard", "det", "05/18", rarity="Promo")      # CT manda 'Promo'
    assert px == 14.47 and prov.last_variant_used == "holofoil"
    # reverse nunca casa com a chave holofoil (regra exata intacta)
    assert prov.market_price_usd("Charizard", "det", "05/18", foil=True, rarity="Promo") is None
    assert prov.last_ref_status == cv.INCOMPATIVEL


def test_promo_in_a_set_that_is_not_holo_only_stays_incompatible():
    rows = [{"pid": 1, "name": "X", "number": "106/167", "rarity": "Common", "prices": [["Holofoil", 5.0]]}]
    prov = _real_provider("twm", 23473, "SV06: Twilight Masquerade", "2024-05-24T00:00:00", rows)
    assert prov.market_price_usd("Greninja ex", "twm", "106/167", rarity="Promo") is None


def test_fst_alt_art_with_the_cardtrader_typo_matches_holofoil():
    assert cv.rarity_is_holo("Special Illustraion Rare")            # grafia REAL da CardTrader (typo)
    assert cv.rarity_conclusive("Special Illustraion Rare")
    prov = _real_provider("fst", 2906, "SWSH08: Fusion Strike", "2021-11-12T00:00:00", _EV["fst_alt_art"])
    assert prov.market_price_usd("Gengar VMAX", "fst", "271/264", rarity="Special Illustraion Rare") == 997.53


def test_viv_rare_that_tcgcsv_calls_amazing_rare_matches_holofoil_but_plain_rare_does_not():
    prov = _real_provider("viv", 2701, "SWSH04: Vivid Voltage", "2020-11-13T00:00:00",
                          _EV["viv_138"] + _EV["viv_donphan"])
    # Rayquaza 138/185: CT 'Rare', tcgcsv 'Amazing Rare' (holo por natureza, só Holofoil)
    assert prov.market_price_usd("Rayquaza", "viv", "138/185", rarity="Rare") == 25.0
    # Donphan 087/185: 'Rare' de verdade (Normal+Reverse) -> continua Normal, não vira holo
    assert prov.market_price_usd("Donphan", "viv", "087/185", rarity="Rare") == 0.19
    assert prov.last_variant_used == "normal"
    assert _EV["viv_rare_summary"] == {"Normal+Reverse Holofoil": 33}   # 33/33 'Rare' SWSH são não-holo


def test_viv_regirock_label_conflict_stays_incompatible():
    """CT diz Holo Rare, a referência só tem normal+reverse: conflito real, NÃO se afrouxa."""
    rows = [{"pid": 9, "name": "Regirock", "number": "088/185", "rarity": "Rare",
             "prices": [["Normal", 0.2], ["Reverse Holofoil", 0.3]]}]
    prov = _real_provider("viv", 2701, "SWSH04: Vivid Voltage", "2020-11-13T00:00:00", rows)
    assert prov.market_price_usd("Regirock", "viv", "088/185", rarity="Holo Rare") is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
