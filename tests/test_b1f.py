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


# ───────── 4: fontes consultadas / não consultadas ─────────
import dataclasses  # noqa: E402
from datetime import datetime  # noqa: E402

from test_b1e import EXP, _build  # noqa: E402
from test_tcgcsv_fallback import _fake_groups, _fake_prices, _fake_products, _provider_with, _scanner_with  # noqa: E402
from test_set_outcomes import _cards  # noqa: E402


def test_breaker_open_set_says_which_source_was_not_consulted_and_why():
    rows = [(k, "1st Edition Holofoil", 9.0) for k in range(1, 4)] + [(k, "Unlimited Holofoil", 9.0) for k in range(5, 7)]
    s, listings = _build(6, rows, lambda i: 99.0)             # card 4 não existe no tcgcsv; 1-3 só 1st; 5-6 ok
    s.breaker = sc.SourceBreaker()
    s.breaker.is_open, s.breaker.opened_at = True, datetime(2026, 11, 24, 8, 28)
    s.scan([EXP])
    assert s.noref_rows and s.unpriced_rows
    for r in s.noref_rows:
        assert "pokemontcg.io não consultada: fonte degradada desde 08:28" in r["motivo"]
        assert "tcgcsv" in r["motivo"]
    for r in s.unpriced_rows:
        assert "pokemontcg.io não consultada: fonte degradada desde 08:28" in r["detail"]
        assert "tcgcsv" in r["detail"]


def _tcgcsv_primary(tmp_rows, n=2, alt=None):
    listings = [dataclasses.replace(l, rarity="Holo Rare") for l in _cards(n, set_code="asc")]
    tc = _provider_with(_fake_groups(), _fake_products({k: f"{k:03d}/100" for k in range(1, n + 1)}),
                        _fake_prices(tmp_rows))
    s = _scanner_with({}, None, listings, tcgcsv_fallback=False, max_misses=0)
    s.pricing, s.language = tc, "en"
    s.ptcg_alt = alt
    s.ct.list_blueprints = MagicMock(return_value=[{"id": l.blueprint_id, "name": l.card_name} for l in listings])
    s.ct.list_listings_by_expansion = MagicMock(return_value=[
        {"id": l.product_id, "blueprint_id": l.blueprint_id} for l in listings])
    by = {l.product_id: l for l in listings}
    s._parse_listing = MagicMock(side_effect=lambda raw, idx: by.get(raw["id"]))
    s._passes_filters = MagicMock(return_value=True)
    return s


def _alt(price=None, status=None):
    a = MagicMock()
    a.name = "pokemontcg"
    a.market_price_usd.return_value = price
    a.last_tcg_url, a.last_variant_used, a.last_ptcg_rarity = None, "holofoil", None
    a.last_set_release_date, a.last_price_source, a.last_ref_data_at = None, "pokemontcg", None
    a.last_ref_reason, a.last_ref_status, a.last_available_keys = "sem preço Unlimited Holo (disponíveis: normal)", status, ["normal"]
    return a


def test_fallback_works_both_ways_tcgcsv_first_without_variant_asks_pokemontcg():
    rows = [(1, "Normal", 3.0), (2, "Normal", 3.0)]           # só Normal: oferta Holo não casa no tcgcsv
    alt = _alt(price=42.0)
    s = _tcgcsv_primary(rows, alt=alt)
    opps = list(s.scan_expansion(EXP))
    assert len(opps) == 2 and all(o.price_source == "pokemontcg" for o in opps)
    assert alt.market_price_usd.call_count == 2


def test_both_sources_without_variant_register_both_reasons():
    alt = _alt(price=None, status=cv.INCOMPATIVEL)
    s = _tcgcsv_primary([(1, "Normal", 3.0), (2, "Normal", 3.0)], alt=alt)
    assert list(s.scan_expansion(EXP)) == []
    r = s.noref_rows[0]
    assert "tcgcsv:" in r["motivo"] and "pokemontcg:" in r["motivo"]


def test_degraded_second_source_is_not_called_just_to_fill_the_table():
    alt = _alt(price=42.0)
    s = _tcgcsv_primary([(1, "Normal", 3.0), (2, "Normal", 3.0)], alt=alt)
    s.ptcg_alt_breaker = sc.SourceBreaker()
    s.ptcg_alt_breaker.is_open, s.ptcg_alt_breaker.opened_at = True, datetime(2026, 11, 24, 8, 28)
    s.ptcg_alt_breaker._last_probe = 10 ** 12                   # sonda não vencida
    assert list(s.scan_expansion(EXP)) == []
    assert alt.market_price_usd.call_count == 0
    assert "pokemontcg.io não consultada: fonte degradada desde 08:28" in s.noref_rows[0]["motivo"]


# ───────── 6: baixas ─────────
def test_health_line_uses_why_and_the_time_degradation_started_and_counts_sub_threshold_failures():
    t = [0.0]
    b = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=10.0, clock=lambda: t[0])
    for ok in (True, False, True, True, True):
        b.record(ok, 0.2)
    assert not b.is_open and b.total_fail == 1 and b.total_n == 5
    s = sc.Scanner.__new__(sc.Scanner)
    s.breaker = b
    assert s._source_health_line() == "pokemontcg.io saudável neste run, com 1 falha(s) em 5 ofertas (abaixo do limite)"
    s2 = sc.Scanner.__new__(sc.Scanner)
    s2.breaker = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=10.0)
    for _ in range(2):
        s2.breaker.record(True, 40.0)                          # só lentidão (sem falha)
    line = s2._source_health_line()
    assert "por latência" in line and "falhas" not in line.split(";")[0]
    assert "degradada desde" in line or "degradada às" in line
    s3 = sc.Scanner.__new__(sc.Scanner)
    s3.breaker = sc.SourceBreaker()
    for _ in range(3):
        s3.breaker.record(True, 0.1)
    assert s3._source_health_line() == "pokemontcg.io saudável neste run (disjuntor não abriu)"   # nenhuma falha


def test_probe_runs_a_representative_query_and_needs_a_card_with_prices(tmp_path):
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.session = MagicMock()
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"data": [{"id": "base1-4", "tcgplayer": {"prices": {"holofoil": {"market": 300.0}}}}]}
    p.session.get.return_value = ok
    assert p.probe() is True
    params = p.session.get.call_args.kwargs["params"]
    assert "q" in params and params["q"]                            # consulta de carta, não só pageSize=1
    empty = MagicMock(status_code=200)
    empty.json.return_value = {"data": []}
    p.session.get.return_value = empty
    assert p.probe() is False                                       # 200 vazio não prova saúde
    bad = MagicMock(status_code=200)
    bad.json.side_effect = ValueError("x")
    p.session.get.return_value = bad
    assert p.probe() is False


def test_probe_spacing_is_respected_by_the_clock():
    t = [100.0]
    b = sc.SourceBreaker(window=10, min_samples=2, fail_rate=0.5, probe_every_s=120.0, clock=lambda: t[0])
    b.record(False, 1.0)
    b.record(False, 1.0)
    assert b.is_open and not b.probe_due()
    t[0] += 119
    assert not b.probe_due()
    t[0] += 2
    assert b.probe_due()
    b.mark_probe()
    assert not b.probe_due()


def test_latency_measured_by_the_scanner_reaches_the_breaker(monkeypatch):
    from test_b1e import _all_rows
    now = [0.0]
    monkeypatch.setattr(sc.time, "monotonic", lambda: now[0])

    def slow(i):
        now[0] += 40.0                                               # cada consulta custa 40 s, sem falha
        return 55.0
    s, listings = _build(30, _all_rows(30), slow)
    s.breaker = sc.SourceBreaker(window=10, min_samples=6, fail_rate=0.5, slow_s=15.0, clock=lambda: now[0])
    list(s.scan_expansion(EXP))
    assert len(s._calls) == 2 and s.breaker.events[0]["why"] == "latência"


def test_http_403_counts_as_failure_for_the_breaker(tmp_path):
    import requests as rq
    s, listings = _build(30, [(k, "Unlimited Holofoil", 5.0 + k) for k in range(1, 31)], lambda i: 1.0)
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.cache = sc.Cache(db_path=tmp_path / "c.db")
    p._ptcg_get = MagicMock(return_value=MagicMock(status_code=403))
    p.retry_5xx = 0
    s.pricing = p
    list(s.scan_expansion(EXP))
    assert s.breaker.is_open and s.breaker.fail_count >= 3
    assert p._ptcg_get.call_count <= 10


def test_5xx_path_opens_the_breaker_without_hand_incremented_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(sc.time, "sleep", lambda *_: None)
    s, listings = _build(30, [(k, "Unlimited Holofoil", 5.0 + k) for k in range(1, 31)], lambda i: 1.0)
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.cache = sc.Cache(db_path=tmp_path / "c.db")
    p.delay, p._last_call, p.retry_5xx = 0.0, 0.0, 0
    p.session = MagicMock()
    p.session.get.return_value = MagicMock(status_code=502, headers={})
    s.pricing = p
    out = list(s.scan_expansion(EXP))
    assert s.breaker.is_open and p.retry_5xx >= 3 * 3                 # contador do PRÓPRIO provider
    assert len(out) == 30 and s._set_status == "complete"


def test_source_fail_rate_is_validated_between_0_and_1():
    with patch.object(sys, "argv", ["cardtrader_scanner.py", "--source-fail-rate", "5", "--dry-run"]):
        with pytest.raises(SystemExit) as e:
            sc.main()
    assert e.value.code == 2


def test_holo_only_override_never_beats_an_explicit_non_holo_label():
    assert cv.holo_detection("Promo", set_code="det").is_holo
    assert not cv.holo_detection("Non-Holo", set_code="det").is_holo
    assert not cv.holo_detection("Common Non-Holo", "Promo", set_code="det").is_holo


def test_groups_retry_wait_is_simulated_in_the_suite():
    assert sc.TcgCsvFallbackProvider.GROUPS_RETRY_WAIT_S == 0
