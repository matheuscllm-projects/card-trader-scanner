"""B1p — falha operacional de set visível (exit 23 + cabeçalho da entrega), canário contínuo, launchers propagam o
exit code do scanner, hyperlinks das colunas novas. Testes PELO FLUXO (main real, PowerShell real, openpyxl real)."""
from __future__ import annotations

import os
import shutil
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
from test_b1o import _flow, _raw  # noqa: E402


# ───────── 2) canário contínuo: sem descontinuidade 19/20 ─────────
def _mixed(n_good, n_bad):
    return [_raw(i) for i in range(n_good)] + [_raw(500 + i, top=("graded",)) for i in range(n_bad)]


@pytest.mark.parametrize("good,bad,fires", [
    (1, 18, True),     # total 19 (antes: no_coverage silencioso)
    (2, 18, True),     # total 20
    (1, 2, True),      # 2 ruins de 3
    (9, 1, False),     # 1 ruim em 10: não dispara
    (0, 1, True),      # tudo ruim
    (95, 5, False),    # 5% < 10%
    (80, 20, True),    # 20%
])
def test_canary_has_no_discontinuity_between_small_and_large_sets(good, bad, fires):
    s = _flow(_mixed(good, bad))
    assert (s._set_status == "operational_failure") is fires


# ───────── 1a) exit 23 e precedência ─────────
def _o(status, live=None):
    return SimpleNamespace(validation_status=status, live_price_brl=live)


OP = [{"set": "uf", "status": "operational_failure", "reason": "api_format_changed_graded"}]
OK = [{"set": "skg", "status": "complete", "reason": ""}]


def test_exit_23_is_in_the_single_table_and_does_not_collide():
    assert sc.EXIT_SET_OPERATIONAL_FAILURE == 23
    assert {20, 21, 22, 23}.isdisjoint({0, 1, 2, 97, 98, 99, 130})
    assert "23" in (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8").split("TABELA DE CÓDIGOS DE SAÍDA")[1][:3000]


@pytest.mark.parametrize("opps,outs,validate,code", [
    ([], OK, True, 0),
    ([], OP, True, 23),
    ([], OP, False, 23),                                        # vale também com --validate-top 0
    ([_o("API_ERROR")], OP, True, 22),                          # 22 > 23
    ([_o("PRECO_INVALIDO")], OP, True, 21),                     # 21 > 23
    ([_o("VALIDATED_REAL", 10.0), _o("API_ERROR")], OP, True, 23),   # 23 > 20
    ([_o("VALIDATED_REAL", 10.0), _o("API_ERROR")], OK, True, 20),
    ([_o("VALIDATED_REAL", 10.0)], OK, True, 0),
])
def test_run_exit_decision_precedence(opps, outs, validate, code):
    got, msgs = sc.run_exit_decision(opps, outs, validate)
    assert got == code
    assert bool(msgs) == bool(code)


def test_run_exit_decision_prints_every_condition():
    _, msgs = sc.run_exit_decision([_o("VALIDATED_REAL", 10.0), _o("API_ERROR")], OP, True)
    text = "\n".join(msgs)
    assert "código 20" in text and "código 23" in text and "uf" in text


def test_main_exits_23_when_a_set_failed_operationally_and_xlsx_is_written(tmp_path, monkeypatch):
    from test_lote3c import _fake_main_env, _opp

    def scan_fn(s):
        s.set_outcomes = list(OP)
        s.stats["sets_operational_failure"] = "uf: api_format_changed_graded"
        return [_opp(1)]
    holder, out = _fake_main_env(monkeypatch, tmp_path, scan_fn, argv_extra=("--validate-top", "0"))
    with pytest.raises(SystemExit) as ei:
        sc.main()
    assert ei.value.code == 23
    assert out.exists()


def test_main_exits_0_when_every_set_is_complete(tmp_path, monkeypatch):
    from test_lote3c import _fake_main_env, _opp

    def scan_fn(s):
        s.set_outcomes = list(OK)
        return [_opp(1)]
    holder, out = _fake_main_env(monkeypatch, tmp_path, scan_fn, argv_extra=("--validate-top", "0"))
    sc.main()                                                    # sem SystemExit
    assert out.exists()


# ───────── 1b) cabeçalho da entrega ─────────
def test_header_warns_about_operational_failure_and_no_coverage():
    h = pp._set_outcome_header({"sets_operational_failure": "uf: api_format_changed_graded; skg: timeout",
                                "sets_no_coverage": "aq: 5/5 sem preço"})
    assert "⚠ 2 set(s) NÃO avaliados por falha operacional: uf (api_format_changed_graded), skg (timeout)" in h
    assert "1 set(s) sem cobertura: aq (5/5 sem preço)" in h


def test_header_is_silent_when_nothing_failed():
    assert pp._set_outcome_header({"sets_operational_failure": "(nenhum)", "sets_no_coverage": "(nenhum)"}) == ""


def test_header_says_unavailable_for_old_xlsx_without_stats():
    assert "desfecho por set indisponível" in pp._set_outcome_header({"outra": 1})
    assert pp._set_outcome_header(None) == ""


def _df_one_row():
    return pd.DataFrame(pp.__dict__.get("_B1P_ROWS", []))


def test_delivery_markdown_carries_the_warning_in_every_return_path():
    from test_b1o import FINAL4
    df = pp.enrich_df(pd.DataFrame(FINAL4))
    stats = {"sets_operational_failure": "uf: api_format_changed_graded", "sets_no_coverage": "(nenhum)"}
    md = pp.build_delivery_markdown(df, pp.DecisionConfig(), scan_stats=stats)
    assert "⚠ 1 set(s) NÃO avaliados por falha operacional: uf (api_format_changed_graded)" in md
    md0 = pp.build_delivery_markdown(df.iloc[0:0], pp.DecisionConfig(), scan_stats=stats)
    assert "⚠ 1 set(s) NÃO avaliados" in md0
    clean = pp.build_delivery_markdown(df, pp.DecisionConfig(),
                                       scan_stats={"sets_operational_failure": "(nenhum)", "sets_no_coverage": "(nenhum)"})
    assert "NÃO avaliados" not in clean and "sem cobertura:" not in clean


# ───────── 4) hyperlinks das colunas de preço novas ─────────
def test_price_columns_link_to_the_ct_offer():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    cols = ["Carta", "Preço CT validado (R$)", "Preço usado na conta (R$)", "Link CT", "Link TCG", "TCG (R$)"]
    ws.append(cols)
    ws.append(["X", 10, 11, "https://ct/x", "https://tcg/x", 30])
    pp.apply_card_hyperlinks(ws, pd.DataFrame([["X", 10, 11, "https://ct/x", "https://tcg/x", 30]], columns=cols))
    assert ws.cell(row=2, column=2).hyperlink.target == "https://ct/x"
    assert ws.cell(row=2, column=3).hyperlink.target == "https://ct/x"


# ───────── 3) launchers: PowerShell real, repo falso ─────────
SCRIPTS = REPO_ROOT / "scripts"
VENV_PY = Path(sys.executable).parent


def _fake_repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("outputs", "logs", "scripts", ".venv/Scripts"):
        (repo / d).mkdir(parents=True)
    for f in ("python.exe", "pythonw.exe"):
        if (VENV_PY / f).exists():
            shutil.copy(VENV_PY / f, repo / ".venv/Scripts" / f)
    for f in VENV_PY.parent.glob("pyvenv.cfg"):
        shutil.copy(f, repo / ".venv" / "pyvenv.cfg")
    (repo / "scripts" / "all_set_codes.txt").write_text("uf skg", encoding="utf-8")
    (repo / "cardtrader_scanner.py").write_text(
        "import os,sys\nout=sys.argv[sys.argv.index('--output')+1]\nopen(out,'wb').write(b'x')\n"
        "sys.exit(int(os.environ.get('FAKE_SCANNER_EXIT','0')))\n", encoding="utf-8")
    (repo / "cardtrader_postprocess.py").write_text(
        "import os\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)),'post_ran.txt'),'w').write('1')\n",
        encoding="utf-8")
    return repo


@pytest.mark.parametrize("ps1,extra", [("run_weekly_local.ps1", []), ("run_priority_scan.ps1", ["-Sets", "uf"])])
@pytest.mark.parametrize("scanner_exit,expect_exit,post_runs", [
    (0, 0, True), (23, 23, True), (22, 22, True), (20, 20, True), (2, 2, False), (1, 1, False)])
def test_launchers_propagate_the_scanner_exit_code(tmp_path, ps1, extra, scanner_exit, expect_exit, post_runs):
    repo = _fake_repo(tmp_path)
    env = dict(os.environ, CT_SCANNER_REPO=str(repo), FAKE_SCANNER_EXIT=str(scanner_exit))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / ps1),
                        "-Stamp", "t", *extra], capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == expect_exit, (r.stdout, r.stderr)
    assert (repo / "post_ran.txt").exists() is post_runs


@pytest.mark.parametrize("scanner_exit,run", [(23, True), (22, True), (21, True), (20, True), (0, True), (2, False)])
def test_decision_accepts_23(tmp_path, scanner_exit, run):
    from test_b1o import _decide
    assert _decide(scanner_exit, True, 10, tmp_path) == ("run" if run else "abort")


@pytest.mark.parametrize("ps1", ["run_critical_resscan.ps1", "run_weekly_2026-05-19.ps1"])
def test_old_launchers_use_the_decision_function(ps1):
    t = (SCRIPTS / ps1).read_text(encoding="utf-8")
    assert "Get-PostprocessDecision" in t and "$runStart" in t
    assert t.index("$runStart = Get-Date") < t.index("& $py @scannerArgs")
