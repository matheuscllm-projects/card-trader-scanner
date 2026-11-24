"""Lote 3c — defeitos da segunda revisão do PR #74.

1 validação NUNCA é reaproveitada entre runs (só --resume-validation, de run que
não terminou, mesma oferta e mesma referência) · 2 referência nunca anterior ao
início do run · 3 exceção no meio do set não quebra a soma · 4 Ctrl-C no meio do
set · 5 /groups do tcgcsv: retry curto + cache negativo que expira · 6 baixas.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_scanner as sc  # noqa: E402
from test_lote3b import _assert_accounted, _provider_with_responses  # noqa: E402
from test_set_outcomes import _cards, _run, _scan  # noqa: E402
from test_tcgcsv_fallback import _scanner_with  # noqa: E402

TZ_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"


# ───────────────────────── helpers ─────────────────────────
def _opp(bp_id, ct=100.0, ref=200.0):
    l = sc.Listing(
        product_id=bp_id, blueprint_id=bp_id, card_name=f"Card {bp_id}",
        set_code="aq", set_name="Aquapolis", collector_number=f"{bp_id:03d}/147",
        condition="Near Mint", language="en", price_cents=int(ct * 100),
        price_currency="BRL", price_brl=ct, quantity=1, foil=False, graded=False,
        seller_username=f"s{bp_id}", seller_can_sell_via_hub=True,
        seller_user_type="professional", cardtrader_url=f"https://x/{bp_id}", rarity="Rare")
    return sc.Opportunity(listing=l, tcg_market_usd=ref / 5, tcg_market_brl=ref,
                          ct_price_brl=ct, margin_pct=(ref - ct) / ref, margin_brl=ref - ct,
                          estimated_shipping_brl=0.0, net_margin_pct=(ref - ct) / ref)


def _live(bp_id, cents=10000):
    return [{"user": {"username": f"s{bp_id}"}, "price_cents": cents,
             "price_currency": "BRL",
             "properties_hash": {"condition": "Near Mint", "pokemon_reverse": False}}]


def _validator(ct_side_effect):
    s = sc.Scanner.__new__(sc.Scanner)
    s.usd_brl, s.eur_brl, s.hub_fee_rate, s.stats, s.language = 5.0, 5.9, 0.0, {}, "en"
    s.ct = MagicMock()
    s.ct.rate_limit_hits = 0
    s.ct.list_listings_by_blueprint = MagicMock(side_effect=ct_side_effect)
    return s


def _validate(cp_path, ct_fn, opps, resume=False):
    cp = sc.CheckpointWriter(cp_path, every_n=10, resume_validation=resume)
    s = _validator(ct_fn)
    s.validate_per_blueprint(opps, checkpoint=cp)
    cp.close()
    return s


def _records(path, typ):
    return [r for r in (json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines())
            if r.get("_type") == typ]


# ───────────── 1: validação nunca atravessa runs ─────────────────────────────
def test_second_run_same_output_never_reuses_validation(tmp_path):
    # cenário exato do diretor: run 1 completo live R$100; run 2 mesmo --output,
    # vendedor agora em R$130 e referência caída pra 150
    cp_path = tmp_path / "out.xlsx.checkpoint.jsonl"
    run1 = [_opp(1, ct=100.0, ref=200.0)]
    _validate(cp_path, lambda bp, language=None: _live(bp, 10000), run1)
    assert run1[0].live_price_brl == 100.0

    run2 = [_opp(1, ct=100.0, ref=150.0)]
    s2 = _validate(cp_path, lambda bp, language=None: _live(bp, 13000), run2)
    assert s2.ct.list_listings_by_blueprint.call_count == 1   # foi à API
    assert run2[0].live_price_brl == 130.0
    assert run2[0].real_margin_pct == pytest.approx(20 / 150, abs=1e-3)   # 0,133
    assert run2[0].validation_status != "VALIDATED_REAL" or run2[0].real_margin_pct < 0.2


def test_unfinished_run_is_still_not_reused_without_the_flag(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    cp1 = sc.CheckpointWriter(cp_path, every_n=10)
    s1 = _validator(lambda bp, language=None: _live(bp))
    s1.validate_per_blueprint([_opp(1)], checkpoint=cp1)
    cp1.close()
    # simula run interrompido: remove o marcador de validação concluída
    lines = [l for l in cp_path.read_text(encoding="utf-8").splitlines()
             if '"validation_complete"' not in l]
    cp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    s2 = _validate(cp_path, lambda bp, language=None: _live(bp), [_opp(1)])
    assert s2.ct.list_listings_by_blueprint.call_count == 1


def _interrupted_run(cp_path, opps, fail_bp):
    """Run 1 que cai no meio da validação (sem validation_complete)."""
    cp = sc.CheckpointWriter(cp_path, every_n=10)
    s = _validator(lambda bp, language=None: _live(bp))
    done = opps[:fail_bp]
    s.validate_per_blueprint(done, checkpoint=cp)
    cp.close()
    lines = [l for l in cp_path.read_text(encoding="utf-8").splitlines()
             if '"validation_complete"' not in l]
    cp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_resume_flag_reuses_only_unfinished_run_same_offer_and_reference(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    _interrupted_run(cp_path, [_opp(1), _opp(2), _opp(3)], 2)   # 1 e 2 validadas
    run2 = [_opp(1), _opp(2, ct=110.0), _opp(3)]               # 2 mudou de preço
    s2 = _validate(cp_path, lambda bp, language=None: _live(bp), run2, resume=True)
    called = sorted(c.args[0] for c in s2.ct.list_listings_by_blueprint.call_args_list)
    assert called == [2, 3], called          # só 1 foi reaproveitada
    assert run2[0].validation_reused is True
    assert run2[1].validation_reused is False and run2[2].validation_reused is False


def test_resume_flag_does_not_reuse_when_reference_changed(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    _interrupted_run(cp_path, [_opp(1)], 1)
    s2 = _validate(cp_path, lambda bp, language=None: _live(bp), [_opp(1, ref=150.0)], resume=True)
    assert s2.ct.list_listings_by_blueprint.call_count == 1


def test_resume_flag_never_reuses_from_a_finished_run(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    _validate(cp_path, lambda bp, language=None: _live(bp), [_opp(1)])     # run completo
    s2 = _validate(cp_path, lambda bp, language=None: _live(bp), [_opp(1)], resume=True)
    assert s2.ct.list_listings_by_blueprint.call_count == 1


def test_every_validated_row_carries_validation_time_and_reuse_mark(tmp_path):
    cp_path = tmp_path / "cp.jsonl"
    t0 = datetime.now().astimezone().replace(microsecond=0)
    _interrupted_run(cp_path, [_opp(1)], 1)
    run2 = [_opp(1), _opp(2)]
    _validate(cp_path, lambda bp, language=None: _live(bp), run2, resume=True)
    for o in run2:
        assert re.fullmatch(TZ_ISO, o.validated_at), o.validated_at
        assert datetime.fromisoformat(o.validated_at) >= t0 - timedelta(seconds=1)
    assert [o.validation_reused for o in run2] == [True, False]


def test_rerun_same_output_archives_previous_checkpoint_instead_of_stacking(tmp_path):
    cp_path = tmp_path / "out.xlsx.checkpoint.jsonl"
    cp1 = sc.CheckpointWriter(cp_path, every_n=10)
    cp1.write_opportunity(_opp(1))
    cp1.close()
    cp2 = sc.CheckpointWriter(cp_path, every_n=10)
    cp2.write_opportunity(_opp(2))
    cp2.close()
    prev = [p for p in tmp_path.iterdir() if p.name != cp_path.name]
    assert len(prev) == 1 and '"Card 1"' in prev[0].read_text(encoding="utf-8")  # nada apagado
    now = _records(cp_path, "opportunity")
    assert [r["listing"]["card_name"] for r in now] == ["Card 2"]               # sem mistura


def test_recovery_of_a_rerun_contains_only_the_new_run(tmp_path):
    cp_path = tmp_path / "o.checkpoint.jsonl"
    for n in (1, 2):
        cp = sc.CheckpointWriter(cp_path, every_n=10)
        cp.write_opportunity(_opp(n))
        cp.close()
    rec = _recover_module()
    opps, _, _ = rec.parse_checkpoint(cp_path)
    assert [o.listing.card_name for o in opps] == ["Card 2"]


def _recover_module():
    spec = importlib.util.spec_from_file_location(
        "recover_from_checkpoint", REPO_ROOT / "scripts" / "recover_from_checkpoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resume_validation_flag_exists_and_defaults_off(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py"])
    assert sc.parse_args().resume_validation is False
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py", "--resume-validation"])
    assert sc.parse_args().resume_validation is True


def test_xlsx_has_validation_time_and_reuse_columns(tmp_path):
    from openpyxl import load_workbook
    o = _opp(1)
    o.validated_at, o.validation_reused = "2026-11-24T10:00:00-03:00", True
    out = tmp_path / "x.xlsx"
    sc.export_xlsx([o], {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3, hub_fee_rate=0.0)
    ws = load_workbook(out)["Oportunidades"]
    head = [c.value for c in ws[1]]
    row = [c.value for c in ws[2]]
    assert row[head.index("Validado em")] == "2026-11-24T10:00:00-03:00"
    assert row[head.index("Validação")] == "reaproveitada"


# ───────────── 2: referência nunca anterior ao início do run ─────────────────
def test_cache_rejects_reference_fetched_before_run_start(tmp_path):
    cache = sc.Cache(db_path=tmp_path / "c.db")
    cache.set_price("k", 10.0, 9.0, 9.5, {})
    old = (datetime.now() - timedelta(hours=2)).isoformat()
    cache.db.execute("UPDATE price_cache SET fetched_at=?", (old,))
    cache.db.commit()
    assert cache.get_price("k") is not None          # TTL 24h aceitaria
    cache.begin_run()                                # início do run
    assert cache.get_price("k") is None              # referência de ANTES não vale
    cache.set_price("k2", 11.0, 10.0, 10.5, {})
    assert cache.get_price("k2") is not None         # a de agora vale


def test_run_start_bound_survives_even_if_clear_is_skipped(tmp_path):
    cache = sc.Cache(db_path=tmp_path / "c.db")
    cache.set_price("k", 10.0, 9.0, 9.5, {})
    cache.db.execute("UPDATE price_cache SET fetched_at=?",
                     ((datetime.now() - timedelta(hours=3)).isoformat(),))
    cache.db.commit()
    cache.set_fx("USD_BRL", 5.0)
    cache.db.execute("UPDATE fx_cache SET fetched_at=?",
                     ((datetime.now() - timedelta(hours=3)).isoformat(),))
    cache.db.commit()
    cache.begin_run()
    assert cache.get_price("k") is None and cache.get_fx("USD_BRL") is None


# ───────────── 3: exceção no meio do set mantém a soma ──────────────────────
def test_exception_mid_set_keeps_the_sum(tmp_path, monkeypatch):
    listings = _cards(6)
    prices = {("asc", l.collector_number): 100.0 for l in listings}
    scanner = _scanner_with(prices, None, listings, tcgcsv_fallback=False, max_misses=0)
    real = scanner._build_opportunity
    calls = {"n": 0}

    def boom(l, tcg, src):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ValueError("schema drift")
        return real(l, tcg, src)

    scanner._build_opportunity = boom
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {}
    assert len(opps) == 2
    _assert_accounted(scanner, opps, 6)                       # 2 + 4 = 6
    assert done[0]["status"] == "operational_failure"
    assert done[0]["unpriced"] == 4
    assert {r["reason"] for r in scanner.unpriced_rows} == {"falha_operacional"}
    assert len(_records(tmp_path / "cp.jsonl", "unpriced")) == 4


# ───────────── 4: Ctrl-C no meio do set ─────────────────────────────────────
def test_keyboard_interrupt_mid_set(tmp_path, monkeypatch):
    listings = _cards(6)
    prices = {("asc", l.collector_number): 100.0 for l in listings}
    scanner = _scanner_with(prices, None, listings, tcgcsv_fallback=False, max_misses=0)
    real = scanner._build_opportunity
    calls = {"n": 0}

    def boom(l, tcg, src):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt()
        return real(l, tcg, src)

    scanner._build_opportunity = boom
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert scanner.interrupted is True
    assert skip == {}
    assert len(opps) == 2
    _assert_accounted(scanner, opps, 6)
    assert done[0]["status"] == "operational_failure"
    assert done[0]["reason"] == "interrupted_by_user"
    assert {r["reason"] for r in scanner.unpriced_rows} == {"falha_operacional"}
    assert any("interrupted_by_user" in l for l in scanner.run_summary_lines())
    # nenhum scan_complete: o run NÃO terminou
    assert not _records(tmp_path / "cp.jsonl", "scan_complete")


def test_keyboard_interrupt_marks_remaining_sets_not_started(tmp_path, monkeypatch):
    listings = _cards(3)
    prices = {("asc", l.collector_number): 100.0 for l in listings}
    scanner = _scanner_with(prices, None, listings, tcgcsv_fallback=False, max_misses=0)
    scanner._build_opportunity = MagicMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    scanner.language = "en"
    scanner.ct.list_blueprints = MagicMock(return_value=[
        {"id": l.blueprint_id, "name": l.card_name} for l in listings])
    scanner.ct.list_listings_by_expansion = MagicMock(return_value=[
        {"id": l.product_id, "blueprint_id": l.blueprint_id} for l in listings])
    by_pid = {l.product_id: l for l in listings}
    scanner._parse_listing = MagicMock(side_effect=lambda raw, idx: by_pid.get(raw["id"]))
    scanner._passes_filters = MagicMock(return_value=True)
    scanner.scan([{"id": 1, "code": "asc", "name": "A"}, {"id": 2, "code": "bog", "name": "B"}])
    outs = {o["set"]: o for o in scanner.set_outcomes}
    assert outs["asc"]["reason"] == "interrupted_by_user"
    assert outs["bog"]["status"] == "operational_failure"
    assert outs["bog"]["reason"] == "interrupted_not_started"


def _fake_main_env(monkeypatch, tmp_path, scan_fn, argv_extra=()):
    class FakeScanner:
        def __init__(self, **kw):
            self.stats = {k: 0 for k in (
                "expansions_scanned", "listings_fetched", "listings_after_filters",
                "tcg_price_found", "opportunities_found")}
            self.usd_brl, self.eur_brl = 5.0, 5.9
            self.keep_all_priced = True
            self.unpriced_rows = []
            self.interrupted = False
            self.validated = False

        def scan(self, expansions, checkpoint=None):
            return scan_fn(self)

        def validate_per_blueprint(self, *a, **k):
            self.validated = True

        def run_summary_lines(self):
            return ["Sets: resumo"]

    holder = {}

    def factory(**kw):
        holder["s"] = FakeScanner(**kw)
        return holder["s"]

    ct = MagicMock()
    ct.list_expansions.return_value = [{"id": 1, "code": "asc", "name": "Asc"}]
    monkeypatch.setattr(sc, "Scanner", factory)
    monkeypatch.setattr(sc, "CardTraderClient", lambda jwt: ct)
    monkeypatch.setattr(sc, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(sc, "acquire_run_guard", lambda sd: object())
    monkeypatch.setattr(sc, "PROVIDERS", {"pokemontcg": lambda key, cache: MagicMock()})
    monkeypatch.setenv("CT_JWT", "x")
    monkeypatch.setenv("POKEMONTCG_API_KEY", "y")
    out = tmp_path / "o.xlsx"
    monkeypatch.setattr(sys, "argv", [
        "cardtrader_scanner.py", "--sets", "asc", "--state-dir", str(tmp_path / "st"),
        "--output", str(out), "--no-tcgcsv-fallback", "--provider", "pokemontcg", *argv_extra])
    return holder, out


def test_main_exits_nonzero_writes_partial_xlsx_and_skips_validation_on_ctrl_c(tmp_path, monkeypatch):
    def scan_fn(s):
        s.interrupted = True
        return [_opp(1)]

    holder, out = _fake_main_env(monkeypatch, tmp_path, scan_fn)
    with pytest.raises(SystemExit) as ei:
        sc.main()
    assert ei.value.code not in (0, None)
    assert out.exists()                                   # XLSX parcial escrito
    assert holder["s"].validated is False                 # nada validado no parcial
    cp = tmp_path / "st" / "o.xlsx.checkpoint.jsonl"
    assert not _records(cp, "scan_complete")


# ───────────── 5: /groups do tcgcsv — retry curto e cache negativo que expira ─
def test_groups_transient_failure_is_retried_before_giving_up(monkeypatch):
    from test_set_outcomes import _tcgcsv_for
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    prov = _tcgcsv_for([1])
    orig = prov.session.get.side_effect
    state = {"n": 0}

    def flaky(url, **kw):
        if url.endswith("/groups"):
            state["n"] += 1
            if state["n"] == 1:
                raise requests.ConnectionError("blip")
        return orig(url, **kw)

    prov.session.get.side_effect = flaky
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is True
    assert state["n"] == 2   # um blip em /groups no 1º set não condena o run


def test_negative_groups_cache_expires_within_the_run(monkeypatch):
    sleeps = []
    monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))
    prov = _provider_with_responses(requests.ConnectionError("down"))

    def groups_calls():
        return len([c for c in prov.session.get.call_args_list if c.args[0].endswith("/groups")])

    assert prov.prefill_set("a", ["a"], "A") is False
    first = groups_calls()
    assert 1 < first <= 3 and sleeps and max(sleeps) <= 5   # retry com espera curta
    assert prov.prefill_set("b", ["b"], "B") is False
    assert groups_calls() == first                           # dentro do TTL: cache negativo
    prov._groups_failed_at -= sc.TcgCsvFallbackProvider.GROUPS_NEGATIVE_TTL_S + 1
    assert prov.prefill_set("c", ["c"], "C") is False
    assert groups_calls() > first                            # expirou: tenta de novo


# ───────────── 6: baixas ────────────────────────────────────────────────────
def test_stats_scanned_at_has_timezone(tmp_path):
    from openpyxl import load_workbook
    out = tmp_path / "x.xlsx"
    sc.export_xlsx([_opp(1)], {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3, hub_fee_rate=0.0)
    ws = load_workbook(out)["Stats"]
    val = [r[1].value for r in ws.iter_rows(min_row=2) if r[0].value == "scanned_at"][0]
    assert re.fullmatch(TZ_ISO, val), val


def test_recover_fallback_scanned_at_has_timezone():
    from dataclasses import asdict
    rec = _recover_module()
    d = asdict(_opp(1))
    d.pop("scanned_at")
    assert re.fullmatch(TZ_ISO, rec._reconstruct_opportunity(d).scanned_at)


def test_checkpoint_to_partial_applies_validation_and_unfinished_validation_is_not_finished(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "checkpoint_to_partial", REPO_ROOT / "scripts" / "checkpoint_to_partial.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cp_path = tmp_path / "cp.jsonl"
    cp = sc.CheckpointWriter(cp_path, every_n=10)
    o = _opp(1)
    cp.write_opportunity(o)
    cp.write_scan_complete(1, 1.0)
    s = _validator(lambda bp, language=None: _live(bp, 10000))
    s.validate_per_blueprint([o], checkpoint=cp)
    cp.close()
    # tira o marcador: validação em curso
    lines = [l for l in cp_path.read_text(encoding="utf-8").splitlines()
             if '"validation_complete"' not in l]
    cp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    deals, meta = mod.parse_checkpoint(cp_path)
    assert meta["finished"] is False
    assert deals[0]["validation"] == "VALIDATED_REAL"


def test_test_helper_ids_are_unique():
    from test_tcgcsv_fallback import _listing
    ids = {(_listing(f"C{k}", f"{k:03d}/100").product_id,
            _listing(f"C{k}", f"{k:03d}/100").blueprint_id) for k in range(1, 400)}
    assert len({i[0] for i in ids}) == 399 and len({i[1] for i in ids}) == 399


def test_run_summary_shows_priced_fraction_and_flags_below_half(tmp_path, monkeypatch):
    s = sc.Scanner.__new__(sc.Scanner)
    s.set_outcomes = [
        {"set": "aaa", "name": "A", "status": "complete_with_unpriced", "reason": "",
         "unpriced": 5, "total": 100, "note": None},
        {"set": "bbb", "name": "B", "status": "complete_with_unpriced", "reason": "",
         "unpriced": 5, "total": 6, "note": None},
    ]
    s.unpriced_rows = []
    text = "\n".join(s.run_summary_lines())
    assert "aaa (95/100 precificadas" in text
    assert "bbb (1/6 precificadas" in text
    assert re.search(r"⚠️.*bbb", text)            # abaixo de metade é destacado
    assert not re.search(r"⚠️[^\n]*aaa", text)


# ───────────── 7: nota de calibração ─────────────────────────────────────────
def test_docs_carry_the_calibration_note():
    for rel in ("CLAUDE.md", ".claude/commands/scan.md"):
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "30 validações" in txt and "remedida" in txt, rel
