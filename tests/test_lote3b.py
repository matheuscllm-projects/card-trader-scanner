"""Lote 3b — defeitos reproduzidos pela revisão independente do PR #74.

1 rescue com tcgcsv fora do ar não pode gravar skip-list · 2 falha em massa não
pode descartar carta já precificada (invariante: precificadas + sem preço =
total) · 3 validação com progresso e retomada · 4 sem código morto · 5 tcgcsv:
200 vazio = sem cobertura ≠ falha, cache negativo de /groups · 6 recovery
preserva fonte/data-hora e linhas "Sem preço" · 7 data/hora com fuso.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_scanner as sc  # noqa: E402
from test_set_outcomes import _cards, _run, _tcgcsv_for  # noqa: E402
from test_tcgcsv_fallback import (  # noqa: E402
    _fake_groups, _fake_prices, _fake_products, _provider_with, _scanner_with,
)


def _assert_accounted(scanner, opps, total, code="asc"):
    """Invariante: nenhuma linha some — precificadas + sem preço == total."""
    unpriced = [r for r in scanner.unpriced_rows if r["set"] == code]
    assert len(opps) + len(unpriced) == total, (len(opps), len(unpriced), total)


# ───────────── 1: rescue com tcgcsv fora do ar → falha operacional ──────────
def _dead_tcgcsv():
    tcgcsv = _provider_with(_fake_groups(), _fake_products({}), _fake_prices([]))
    tcgcsv.session.get.side_effect = requests.ConnectionError("tcgcsv fora do ar")
    return tcgcsv


def test_rescue_fetch_failure_after_cap_is_operational_not_skiplisted(tmp_path, monkeypatch):
    # cenário exato da revisão: 6 listings, pokemontcg sem preço em nenhum, cap 2
    listings = _cards(6)
    scanner = _scanner_with({}, _dead_tcgcsv(), listings, max_misses=2)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {}, skip
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"] == "tcgcsv_rescue_fetch_failed", done
    assert done[0]["unpriced"] == 6
    _assert_accounted(scanner, opps, 6)


def test_rescue_fetch_failure_at_natural_end_is_operational(tmp_path, monkeypatch):
    listings = _cards(3)
    scanner = _scanner_with({}, _dead_tcgcsv(), listings, max_misses=40)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {} and done[0]["status"] == "operational_failure", (done, skip)
    _assert_accounted(scanner, opps, 3)


def test_no_group_id_with_nothing_priced_keeps_no_coverage_abort(tmp_path, monkeypatch):
    # restaura o caso do antigo test_vintage_rescue: tcgcsv RESPONDEU e não tem o
    # set → ausência efetiva de cobertura → skip-list (nada precificado)
    listings = _cards(6)
    tcgcsv = _provider_with([{"groupId": 9, "name": "Outro", "abbreviation": "ZZ"}],
                            _fake_products({}), _fake_prices([]))
    scanner = _scanner_with({}, tcgcsv, listings, max_misses=2)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert done[0]["status"] == "no_coverage" and done[0]["unpriced"] == 6, done
    assert skip["asc"]["reason"].startswith("no_coverage_"), skip
    _assert_accounted(scanner, opps, 6)


def test_no_group_id_with_a_prior_hit_is_not_skiplisted(tmp_path, monkeypatch):
    listings = _cards(6)
    tcgcsv = _provider_with([{"groupId": 9, "name": "Outro", "abbreviation": "ZZ"}],
                            _fake_products({}), _fake_prices([]))
    scanner = _scanner_with({("asc", "001/100"): 100.0}, tcgcsv, listings, max_misses=2)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert [o.listing.card_name for o in opps] == ["Card 1"]
    # set coberto (1 precificada) com 5 sem referência ≠ "sem cobertura"
    # B1b: cortado com ofertas não alcançadas = cobertura interrompida (tentar de novo), nunca "completo"
    assert skip == {} and done[0]["status"] == "operational_failure" and done[0]["unpriced"] == 5
    assert done[0]["reason"].startswith("coverage_interrupted_")
    _assert_accounted(scanner, opps, 6)


# ───────────── 9: quatro desfechos (números reais do scan do bs) ────────────
def test_119_of_121_priced_is_complete_with_2_unpriced_not_no_coverage(tmp_path, monkeypatch):
    # bs real: 119 de 121 precificadas, 2 sem referência → NÃO é "sem cobertura"
    listings = _cards(121, set_code="bs")
    no_price = {"060/100", "061/100"}
    prices = {("bs", f"{k:03d}/100"): 100.0 for k in range(1, 122)
              if f"{k:03d}/100" not in no_price}
    scanner = _scanner_with(prices, _tcgcsv_for([]), listings, tcgcsv_fallback=False, max_misses=40)
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 119
    assert done[0]["status"] == "complete_with_unpriced", done
    assert done[0]["unpriced"] == 2 and skip == {}, (done, skip)
    _assert_accounted(scanner, opps, 121, code="bs")
    lines = " | ".join(scanner.run_summary_lines())
    assert "0 completos | 1 completos com sem preço | 0 sem cobertura | 0 com falha operacional" in lines, lines
    assert "bs (119/121 precificadas, 2 sem preço)" in lines, lines


def test_summary_shows_the_four_outcome_counts(tmp_path, monkeypatch):
    scanner = _scanner_with({}, _tcgcsv_for([]), _cards(1), tcgcsv_fallback=False, max_misses=40)
    scanner.set_outcomes = [
        {"set": "a", "status": "complete", "reason": None, "unpriced": 0, "total": 5},
        {"set": "b", "status": "complete_with_unpriced", "reason": "x", "unpriced": 2, "total": 9},
        {"set": "c", "status": "no_coverage", "reason": "y", "unpriced": 4, "total": 4},
        {"set": "d", "status": "operational_failure", "reason": "per_set_timeout_480s", "unpriced": 0, "total": 0},
    ]
    scanner.unpriced_rows = []
    first = scanner.run_summary_lines()[0]
    assert first == "Sets: 1 completos | 1 completos com sem preço | 1 sem cobertura | 1 com falha operacional", first


# ───────────── 2: falha em massa não descarta carta já precificada ──────────
def test_mass_failure_does_not_drop_a_priced_listing(tmp_path, monkeypatch):
    # cenário exato: 25 listings, 19 primeiros dão Timeout, o 20º é precificado
    listings = _cards(25)
    scanner = _scanner_with({}, _tcgcsv_for([]), listings, tcgcsv_fallback=False, max_misses=0)

    def pricing(card_name, set_code, num, foil=False, rarity=None, first_edition=False):
        if int(num[:3]) <= 19:
            raise requests.Timeout("500 persistente")
        return 100.0

    scanner.pricing.market_price_usd.side_effect = pricing
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert [o.listing.card_name for o in opps] == ["Card 20"], [o.listing.card_name for o in opps]
    assert done[0]["status"] == "operational_failure", done
    assert done[0]["reason"] == "mass_pricing_failure_19_of_20", done
    assert done[0]["unpriced"] == 24, done
    assert skip == {}
    _assert_accounted(scanner, opps, 25)


def test_accounting_invariant_in_other_outcomes(tmp_path, monkeypatch):
    # corte por misses + resgate parcial + timeout: soma sempre fecha
    listings = _cards(6)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([2, 3]), listings, max_misses=2)
    opps, _, _ = _run(scanner, listings, tmp_path, monkeypatch)
    _assert_accounted(scanner, opps, 6)


# ───────────── 3: validação com progresso e retomada ────────────────────────
def _opp(bp_id, ct=100.0):
    l = sc.Listing(
        product_id=bp_id, blueprint_id=bp_id, card_name=f"Card {bp_id}",
        set_code="aq", set_name="Aquapolis", collector_number=f"{bp_id:03d}/147",
        condition="Near Mint", language="en", price_cents=int(ct * 100),
        price_currency="BRL", price_brl=ct, quantity=1, foil=False, graded=False,
        seller_username=f"s{bp_id}", seller_can_sell_via_hub=True,
        seller_user_type="professional", cardtrader_url=f"https://x/{bp_id}", rarity="Rare")
    return sc.Opportunity(listing=l, tcg_market_usd=40.0, tcg_market_brl=200.0,
                          ct_price_brl=ct, margin_pct=0.5, margin_brl=100.0,
                          estimated_shipping_brl=0.0, net_margin_pct=0.5)


def _live(bp_id):
    return [{"user": {"username": f"s{bp_id}"}, "price_cents": 10000,
             "price_currency": "BRL", "graded": False,
             "properties_hash": {"condition": "Near Mint", "pokemon_reverse": False}}]


def _validator(ct_side_effect):
    s = sc.Scanner.__new__(sc.Scanner)
    s.usd_brl, s.eur_brl, s.hub_fee_rate, s.stats, s.language = 5.0, 5.9, 0.0, {}, "en"
    s.ct = MagicMock()
    s.ct.rate_limit_hits = 0
    s.ct.list_listings_by_blueprint = MagicMock(side_effect=ct_side_effect)
    return s


def test_validation_logs_periodic_progress(caplog):
    s = _validator(lambda bp, language=None: [])
    opps = [_opp(i) for i in range(1, 61)]
    with caplog.at_level(logging.INFO, logger=sc.log.name):
        s.validate_per_blueprint(opps)
    msgs = [r.getMessage() for r in caplog.records if "Validação per-blueprint:" in r.getMessage()]
    assert any("25/60" in m for m in msgs) and any("60/60" in m for m in msgs), msgs
    assert all("erros" in m and "429" in m for m in msgs), msgs


def test_validation_results_are_checkpointed_and_resumed_only_with_the_flag(tmp_path):
    # Lote 3c: retomada é opt-in (--resume-validation), de run que NÃO terminou
    cp_path = tmp_path / "cp.jsonl"

    def first(bp, language=None):
        if bp == 2:
            raise KeyboardInterrupt()   # run 1 morre no meio da validação
        return _live(bp) if bp == 1 else []

    cp1 = sc.CheckpointWriter(cp_path, every_n=10)
    s1 = _validator(first)
    run1 = [_opp(1), _opp(2), _opp(3)]
    try:
        s1.validate_per_blueprint(run1, checkpoint=cp1)
    except KeyboardInterrupt:
        pass
    cp1.close()
    assert run1[0].validation_status == "VALIDATED_REAL"

    cp2 = sc.CheckpointWriter(cp_path, every_n=10, resume_validation=True)
    s2 = _validator(lambda bp, language=None: _live(bp))
    run2 = [_opp(1), _opp(2), _opp(3)]
    s2.validate_per_blueprint(run2, checkpoint=cp2)
    cp2.close()
    called = sorted(c.args[0] for c in s2.ct.list_listings_by_blueprint.call_args_list)
    assert called == [2, 3], called  # só a 1 (já validada) foi reaproveitada
    assert run2[0].live_price_brl == 100.0 and run2[0].real_net_margin_pct == pytest.approx(0.4975)  # D8: frete de compra R$0,50 fixo
    assert run2[0].validation_reused is True


def test_validation_records_older_than_limit_are_not_reused(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    old = (datetime.now(timezone.utc) - timedelta(hours=sc.VALIDATION_RESUME_MAX_AGE_H + 5)).isoformat(timespec="seconds")
    cp_path.write_text(json.dumps({
        "_type": "validation", "product_id": 1, "blueprint_id": 1, "seller": "s1",
        "validated_at": old, "validation_status": "VALIDATED_REAL", "live_price_brl": 1.0,
    }) + "\n", encoding="utf-8")
    cp = sc.CheckpointWriter(cp_path, every_n=10, resume_validation=True)
    s = _validator(lambda bp, language=None: _live(bp))
    opps = [_opp(1)]
    s.validate_per_blueprint(opps, checkpoint=cp)
    cp.close()
    assert s.ct.list_listings_by_blueprint.call_count == 1  # registro velho ignorado
    assert opps[0].live_price_brl == 100.0


# ───────────── 4: sem código morto ──────────────────────────────────────────
def test_dead_price_set_via_tcgcsv_removed():
    assert not hasattr(sc.Scanner, "_price_set_via_tcgcsv")


# ───────────── 5: tcgcsv — sem cobertura ≠ falha; cache negativo ────────────
def _provider_with_responses(groups_resp, products_resp=None, prices_resp=None):
    """session.get programável: cada resp é (status, json) ou Exception."""
    prov = _provider_with(_fake_groups(), _fake_products({}), _fake_prices([]))

    def fake_get(url, headers=None, timeout=None):
        key = ("groups" if url.endswith("/groups") else
               "products" if url.endswith("/products") else "prices")
        resp = {"groups": groups_resp, "products": products_resp, "prices": prices_resp}[key]
        if isinstance(resp, Exception):
            raise resp
        r = MagicMock()
        r.status_code, payload = resp
        r.json.return_value = payload
        return r

    prov.session.get.side_effect = fake_get
    return prov


def test_tcgcsv_200_with_empty_groups_is_no_coverage_not_failure():
    prov = _provider_with_responses((200, {"results": []}))
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert prov.last_prefill_status == "no_group"


def test_tcgcsv_200_with_empty_products_and_prices_is_no_coverage():
    prov = _provider_with_responses((200, {"results": _fake_groups()}), (200, []), (200, []))
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert prov.last_prefill_status == "no_group"


def test_tcgcsv_404_for_group_is_no_coverage():
    prov = _provider_with_responses((200, {"results": _fake_groups()}), (404, {}), (404, {}))
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert prov.last_prefill_status == "no_group"


def test_tcgcsv_5xx_and_exceptions_are_fetch_failures():
    prov = _provider_with_responses((503, {}))
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert prov.last_prefill_status == "fetch_failed"
    prov2 = _provider_with_responses((200, {"results": _fake_groups()}),
                                     requests.Timeout("t"), (200, {"results": []}))
    assert prov2.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert prov2.last_prefill_status == "fetch_failed"


def test_tcgcsv_groups_failure_is_not_refetched_for_every_set(monkeypatch):
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    prov = _provider_with_responses(requests.ConnectionError("fora"))
    for code in ("a", "b", "c"):
        assert prov.prefill_set(code, [code], "Set") is False
        assert prov.last_prefill_status == "fetch_failed"
    group_calls = [c for c in prov.session.get.call_args_list if c.args[0].endswith("/groups")]
    # 1ª busca = N tentativas (retry curto, Lote 3c); sets seguintes: cache negativo
    assert len(group_calls) == sc.TcgCsvFallbackProvider.GROUPS_ATTEMPTS, len(group_calls)


# ───────────── 6: recovery preserva fonte/data-hora e "Sem preço" ───────────
def _recover_module():
    spec = importlib.util.spec_from_file_location(
        "recover_from_checkpoint", REPO_ROOT / "scripts" / "recover_from_checkpoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recover_keeps_price_source_and_reference_time():
    from dataclasses import asdict
    rec = _recover_module()
    o = _opp(7)
    o.price_source, o.price_fetched_at = "tcgcsv", "2026-11-24T10:00:00-03:00"
    o.below_threshold = True
    back = rec._reconstruct_opportunity(asdict(o))
    assert back.price_source == "tcgcsv"
    assert back.price_fetched_at == "2026-11-24T10:00:00-03:00"
    assert back.below_threshold is True


def test_unpriced_rows_and_validations_survive_checkpoint_recovery(tmp_path, monkeypatch):
    listings = _cards(4)
    scanner = _scanner_with({("asc", "001/100"): 100.0}, _tcgcsv_for([2, 3]), listings, max_misses=40)
    _run(scanner, listings, tmp_path, monkeypatch)  # Card 4 fica sem preço
    rec = _recover_module()
    opps, _, summary = rec.parse_checkpoint(tmp_path / "cp.jsonl")
    assert [r["card"] for r in summary["unpriced"]] == ["Card 4"], summary["unpriced"]
    assert {o.price_source for o in opps} == {"pokemontcg", "tcgcsv"}


# ───────────── 7: um só formato de data/hora, com fuso ─────────────────────
def test_now_iso_has_timezone():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", sc.now_iso()), sc.now_iso()


def test_opportunity_scanned_at_uses_the_same_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", _opp(1).scanned_at)
