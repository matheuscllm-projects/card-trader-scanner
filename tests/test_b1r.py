"""B1r — regressão B1p: o hyperlink da coluna "Preço CT validado (R$)" escrevia a URL na célula VAZIA (openpyxl define
o valor da célula = URL quando ela está vazia), então toda linha NÃO validada parecia ter preço validado no XLSX.
O teste do B1o só olhava o DataFrame; aqui o teste lê o ARQUIVO GERADO (valor + hyperlink por célula, todas as abas)."""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
from test_b1b_delivery import _opp, _run_pp  # noqa: E402

LIVE, USED, TCG = "Preço CT validado (R$)", "Preço usado na conta (R$)", "TCG (R$)"


def _opps():
    ok, bad1, bad2 = _opp(0, seller="a"), _opp(1, seller="b"), _opp(2, seller="c")
    ok.validation_status, ok.live_price_brl = "VALIDATED_REAL", 18.0
    for o in (bad1, bad2):
        o.validation_status, o.live_price_brl = "NOT_VALIDATED", None
    return [ok, bad1, bad2]


def test_generated_xlsx_keeps_unvalidated_live_cells_truly_empty_in_every_sheet(tmp_path):
    _, out = _run_pp(tmp_path, _opps())
    wb = openpyxl.load_workbook(out)
    seen = 0
    for ws in wb.worksheets:
        head = [c.value for c in ws[1]]
        if LIVE not in head:
            continue
        i_live, i_used = head.index(LIVE) + 1, head.index(USED) + 1
        n_live = n_used = 0
        for r in range(2, ws.max_row + 1):
            cl, cu = ws.cell(row=r, column=i_live), ws.cell(row=r, column=i_used)
            if cl.value is not None:
                n_live += 1
                assert isinstance(cl.value, (int, float)), (ws.title, r, cl.value)     # nunca a URL
                assert cl.hyperlink is not None
            else:
                assert cl.hyperlink is None, (ws.title, r)                              # vazio de verdade
            assert isinstance(cu.value, (int, float)) and cu.hyperlink is not None     # usado na conta: sempre
            n_used += 1
        n_rows = ws.max_row - 1
        if n_rows:
            assert n_live == 1 and n_used == n_rows, (ws.title, n_live, n_used, n_rows)
        seen += 1
    assert seen >= 2


def test_hyperlinking_never_turns_an_empty_cell_into_a_url_string():
    wb = openpyxl.Workbook()
    ws = wb.active
    cols = ["Carta", LIVE, USED, "Link CT", "Link TCG", TCG]
    ws.append(cols)
    ws.append(["X", None, 11, "https://ct/x", "https://tcg/x", None])
    pp.apply_card_hyperlinks(ws, pd.DataFrame([["X", None, 11, "https://ct/x", "https://tcg/x", None]], columns=cols))
    assert ws.cell(row=2, column=2).value is None and ws.cell(row=2, column=2).hyperlink is None
    assert ws.cell(row=2, column=6).value is None and ws.cell(row=2, column=6).hyperlink is None
    assert ws.cell(row=2, column=3).hyperlink.target == "https://ct/x"


def test_dataframe_and_markdown_were_never_affected(tmp_path):
    md, out = _run_pp(tmp_path, _opps())
    df = pp.enrich_df(pd.read_excel(out.parent / "in.xlsx", sheet_name=0))
    assert int(df["live_brl"].notna().sum()) == 1
    assert int(df["compra_inclui_hub"].sum()) == 1
    assert md.count("[oferta](") == 3
