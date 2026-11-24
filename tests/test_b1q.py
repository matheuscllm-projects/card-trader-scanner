"""B1q — Summary do XLSX com o aviso de sets, skip-list visível, postprocess falho nos launchers (96), mensagem única
de código de saída, diagnóstico do canário. Testes PELO FLUXO."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
from test_b1o import FINAL4, _flow, _raw  # noqa: E402
from test_b1p import _fake_repo, SCRIPTS  # noqa: E402

import datetime as _dt
_TODAY = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
SKIP = "asc: no_coverage_x | 2026-11-01 | pokemontcg"
STATS = {"sets_operational_failure": "uf: api_format_changed_graded", "sets_no_coverage": "aq: 5/5 sem preço",
         "sets_skip_list": SKIP}


# ───────── 1) Summary do XLSX ─────────
def test_summary_sheet_has_the_same_set_warnings_as_the_markdown():
    df = pp.enrich_df(pd.DataFrame(FINAL4))
    s = pp.build_summary(df, pp.DecisionConfig(), None, STATS)
    text = "\n".join(f"{a} {b}" for a, b in s.itertuples(index=False))
    assert "1 set(s) NÃO avaliados por falha operacional: uf (api_format_changed_graded)" in text
    assert "1 set(s) sem cobertura: aq (5/5 sem preço)" in text
    assert "1 set(s) pulados pela skip-list" in text
    clean = pp.build_summary(df, pp.DecisionConfig(), None, {"sets_operational_failure": "(nenhum)",
                                                              "sets_no_coverage": "(nenhum)", "sets_skip_list": "(nenhum)"})
    assert "NÃO avaliados" not in "\n".join(f"{a} {b}" for a, b in clean.itertuples(index=False))


def test_summary_sheet_says_unavailable_for_xlsx_without_stats():
    df = pp.enrich_df(pd.DataFrame(FINAL4))
    s = pp.build_summary(df, pp.DecisionConfig(), None, {})
    assert "desfecho por set indisponível" in "\n".join(f"{a} {b}" for a, b in s.itertuples(index=False))


# ───────── 2) skip-list visível ─────────
def test_header_lists_skip_list_sets_with_date_reason_and_provider():
    h = pp._set_outcome_header(STATS)
    assert "1 set(s) pulados pela skip-list" in h
    assert "asc" in h and "2026-11-01" in h and "no_coverage_x" in h and "pokemontcg" in h
    assert "sem cobertura registrada em 2026-11-01" in h


def test_delivery_markdown_shows_skip_list_without_other_warnings():
    df = pp.enrich_df(pd.DataFrame(FINAL4))
    md = pp.build_delivery_markdown(df, pp.DecisionConfig(), scan_stats={
        "sets_operational_failure": "(nenhum)", "sets_no_coverage": "(nenhum)", "sets_skip_list": SKIP})
    assert "pulados pela skip-list" in md and "NÃO avaliados" not in md


def test_scan_records_skipped_sets_in_stats_and_does_not_change_exit(tmp_path, monkeypatch):
    from test_tcgcsv_fallback import _scanner_with
    s = _scanner_with({}, None, [])
    (tmp_path / "skip.json").write_text(json.dumps({"skipped": ["asc"], "reasons": {"asc": {
        "reason": "no_coverage_x", "added_at": _TODAY + "T10:00:00Z", "provider": "pokemontcg"}}}), encoding="utf-8")
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    s.ignore_skip_list, s.language = False, "en"
    s.scan([{"id": 1, "code": "asc", "name": "Ascended"}])
    v = s.stats["sets_skip_list"]
    assert v.startswith(f"asc: no_coverage_x | {_TODAY}") and v.endswith("| pokemontcg")
    assert sc.run_exit_decision([], s.set_outcomes, False) == (0, [])    # decisão registrada, não falha


def test_scan_without_skipped_sets_records_nenhum(tmp_path, monkeypatch):
    from test_tcgcsv_fallback import _scanner_with
    s = _scanner_with({}, None, [])
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "skip.json")
    s.language = "en"
    s.scan([])
    assert s.stats["sets_skip_list"] == "(nenhum)"


# ───────── 4) mensagem única de código de saída ─────────
def _o(status, live=None):
    return SimpleNamespace(validation_status=status, live_price_brl=live)


def test_individual_messages_have_no_exit_code_and_one_final_line_has_the_effective_one():
    code, msgs = sc.run_exit_decision([_o("VALIDATED_REAL", 10.0), _o("API_ERROR")],
                                      [{"set": "uf", "status": "operational_failure", "reason": "r"}], True)
    assert code == 23
    assert all("Saída com código" not in m for m in msgs[:-1])
    assert msgs[-1] == "Código de saída efetivo: 23"
    assert sum("código de saída efetivo" in m.lower() for m in msgs) == 1
    for c in (20, 21, 22):
        assert "Saída com código" not in sc.validation_exit_message(c)


def test_no_final_line_when_exit_is_zero():
    assert sc.run_exit_decision([], [], True) == (0, [])


# ───────── 3) postprocess falhando nos launchers ─────────
def test_exit_96_is_in_the_single_table():
    t = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8").split("TABELA DE CÓDIGOS DE SAÍDA")[1][:4000]
    assert "96" in t


@pytest.mark.parametrize("ps1,extra", [("run_weekly_local.ps1", []), ("run_priority_scan.ps1", ["-Sets", "uf"]),
                                       ("run_critical_resscan.ps1", ["-Sets", "uf"]), ("run_weekly_2026-05-19.ps1", [])])
@pytest.mark.parametrize("scanner_exit,post_exit,expect", [
    (0, 1, 96), (23, 1, 96), (22, 3, 96),          # postprocess falho vence o código do scanner
    (23, 0, 23), (0, 0, 0)])
def test_launchers_report_postprocess_failure_with_96(tmp_path, ps1, extra, scanner_exit, post_exit, expect):
    repo = _fake_repo(tmp_path)
    (repo / "cardtrader_postprocess.py").write_text(
        "import os,sys\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)),'post_ran.txt'),'w').write('1')\n"
        "sys.exit(int(os.environ.get('FAKE_POST_EXIT','0')))\n", encoding="utf-8")
    env = dict(os.environ, CT_SCANNER_REPO=str(repo), FAKE_SCANNER_EXIT=str(scanner_exit), FAKE_POST_EXIT=str(post_exit))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / ps1),
                        "-Stamp", "t", *extra], capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == expect, (r.stdout, r.stderr)
    logs = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (repo / "logs").glob("*.log"))
    if expect == 96:
        assert "postprocess falhou: nenhuma entrega gerada" in logs
    # override ativo e visivel
    assert "CT_SCANNER_REPO" in (r.stderr + r.stdout)


# ───────── canário: diagnóstico no log ─────────
def test_canary_log_has_counts_per_key_and_one_example_listing_id(caplog):
    raws = [_raw(i) for i in range(10)] + [_raw(300 + i, top=("graded",)) for i in range(4)]
    with caplog.at_level(logging.ERROR, logger=sc.log.name):
        s = _flow(raws)
    assert s._set_status == "operational_failure"
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "graded=4" in msg and "exemplo" in msg and "1300" in msg
