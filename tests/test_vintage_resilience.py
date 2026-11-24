"""Lote 1 (resiliência vintage): skip-list transiente, erro de rede, status do
set_complete, log de groupId ausente e overrides de timeout.

Todos os testes isolam a skip-list em tmp_path (monkeypatch de SKIP_LIST_FILE).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cardtrader_scanner as sc  # noqa: E402


def _old_entry(reason: str, days: int = 10) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return {"reason": reason, "added_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _scanner(tmp_path, monkeypatch, per_set_timeout_s=480):
    """Scanner stub mínimo; skip-list isolada em tmp_path."""
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    s = sc.Scanner.__new__(sc.Scanner)
    s.ct = MagicMock()
    s.pricing = MagicMock()
    s.cache = MagicMock()
    s.language = "en"
    s.min_price_usd = 10.0
    s.exclude_graded = True
    s.per_set_timeout_s = per_set_timeout_s
    s.ignore_skip_list = False
    s.max_consecutive_misses = 0
    s.tcgcsv = None
    s.tcgcsv_fallback = False
    s.heartbeat = lambda *_: None
    s._checkpoint = None
    s.usd_brl = 5.0
    s.eur_brl = 5.9
    s.stats = {k: 0 for k in (
        "expansions_scanned", "listings_fetched", "listings_after_filters",
        "expansions_skipped_by_list", "expansions_timed_out", "pricing_failures",
        "expansions_mass_pricing_abort", "expansions_no_coverage_abort",
    )}
    s.mass_pricing_failure_threshold = 0.50
    s.mass_pricing_failure_min_sample = 20
    return s


# ── #4: no_coverage_ expira ────────────────────────────────────────────────
def test_no_coverage_skip_entry_expires_after_ttl():
    old = _old_entry("no_coverage_40_consecutive_misses_at_40_of_73")
    fresh = _old_entry("no_coverage_40_consecutive_misses_at_40_of_73", days=1)
    assert sc._skip_entry_is_expired(old) is True
    assert sc._skip_entry_is_expired(fresh) is False


# ── #5 (superado pelo Lote 3): erro de rede/inesperado NUNCA vai à skip-list ──
# Cobertura nova em tests/test_set_outcomes.py (network_error_/unexpected_error_
# viram operational_failure sem skip-list). Entradas ANTIGAS na skip-list seguem
# lidas e expiram normalmente (no_coverage_/network_error_ são transientes).
def test_old_network_error_entry_in_skiplist_still_expires():
    assert sc._skip_entry_is_expired(_old_entry("network_error_ConnectionError")) is True


# ── #11: set_complete registra status ──────────────────────────────────────
def _run_with_checkpoint(s, tmp_path, exp):
    cp = sc.CheckpointWriter(tmp_path / "cp.jsonl", every_n=10)
    s.scan([exp], checkpoint=cp)
    cp.close()
    lines = [json.loads(x) for x in (tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()]
    return [d for d in lines if d.get("_type") == "set_complete"]


def test_set_complete_marks_failed_set_with_reason(tmp_path, monkeypatch):
    s = _scanner(tmp_path, monkeypatch)
    s.ct.list_blueprints.side_effect = TimeoutError("deadline")
    done = _run_with_checkpoint(s, tmp_path, {"id": 7, "code": "cg", "name": "EX Crystal Guardians"})
    assert len(done) == 1
    assert done[0]["status"] == "operational_failure", done[0]
    assert done[0]["reason"].startswith("ct_blueprints_timeout_"), done[0]


def test_set_complete_marks_finished_set_complete(tmp_path, monkeypatch):
    s = _scanner(tmp_path, monkeypatch)
    s.ct.list_blueprints.return_value = []
    s.ct.list_listings_by_expansion.return_value = []
    done = _run_with_checkpoint(s, tmp_path, {"id": 7, "code": "cg", "name": "EX Crystal Guardians"})
    assert len(done) == 1
    assert done[0]["status"] == "complete", done[0]
    assert done[0].get("reason") is None


def test_write_set_complete_legacy_call_defaults_to_complete(tmp_path):
    """Chamada antiga (4 args posicionais) continua válida e vira 'complete'."""
    cp = sc.CheckpointWriter(tmp_path / "cp.jsonl", every_n=10)
    cp.write_set_complete("sfa", "Shrouded Fable", {"opps_found": 1}, 9.0)
    cp.close()
    rec = json.loads((tmp_path / "cp.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["status"] == "complete"
    assert rec["opps_found"] == 1


# ── #12: groupId ausente sobe pra WARNING ──────────────────────────────────
def test_prefill_without_group_id_logs_warning(caplog):
    prov = sc.TcgCsvFallbackProvider.__new__(sc.TcgCsvFallbackProvider)
    prov.cache = MagicMock()
    prov._groups = [{"groupId": 1, "name": "Outro Set", "abbreviation": "XX"}]
    prov._groups_fetched = True
    prov._set_index = {}
    prov._pid_index = {}
    with caplog.at_level(logging.WARNING, logger=sc.log.name):
        ok = prov.prefill_set("zzz_nope", ["zzz_nope"], "Set Inexistente")
    assert ok is False
    assert any(r.levelno >= logging.WARNING and "sem groupId" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]


# ── #15: overrides de timeout ──────────────────────────────────────────────
@pytest.mark.parametrize("code", ["cg", "g1", "g2", "tr", "hp", "aq"])
def test_vintage_timeout_overrides_added(code):
    assert sc.effective_set_timeout_s(code, 480) >= 1080
