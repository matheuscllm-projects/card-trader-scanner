"""P1 ponta a ponta: postprocess sobre um XLSX REAL de scan (4062 linhas, 34 sets vintage).

O XLSX tem precos de mercado e por isso NAO e versionado (DELIVERY_CHAT: nada de resultados
no GitHub; ver .gitignore). O teste le de tests/fixtures/ ou do diretorio de comparacao do
dono e e PULADO se nenhum existir.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openpyxl
import pandas as pd
import pytest

import cardtrader_postprocess as pp
import pricecharting_ref as pcr

_CANDIDATES = [Path(__file__).parent / "fixtures" / "scan_full34.xlsx",
               Path(r"C:\Users\mathe\ct-vintage-compare\full34\scan_full34.xlsx")]
REAL = next((p for p in _CANDIDATES if p.exists()), None)
pytestmark = pytest.mark.skipif(REAL is None, reason="XLSX real do scan nao disponivel")

ROW = re.compile(r"^\| \d+ \|")


def _rows(md):
    return [l for l in md.splitlines() if ROW.match(l)]


@pytest.fixture(scope="module")
def raw():
    return pd.read_excel(REAL)


def _run(raw, tmp_path, extra=None):
    cfg = pp.DecisionConfig()
    out = tmp_path / "rel.xlsx"
    md = pp.write_report(raw, cfg, out, fx_usd_brl=5.5, extra_blocks=extra)
    return cfg, md, openpyxl.load_workbook(out)


def test_real_xlsx_sem_pc_nenhuma_compra_e_contabilidade_fecha(raw, tmp_path):
    extra = {"Sem preço": pd.DataFrame([{"Card Name": "Mew", "Set": "wiz", "Qtd": 1,
                                           "Motivo": "sem preço no provider",
                                           "Link CardTrader": "https://www.cardtrader.com/cards/9"}]),
             "Sem Ref Compatível": pd.DataFrame([{"Card Name": "Lugia", "Set": "n1", "Qtd": 2,
                                                   "Motivo": "sem ref 1st",
                                                   "Link CardTrader": "https://www.cardtrader.com/cards/8",
                                                   "Link TCG": "https://www.tcgplayer.com/product/8"}])}
    cfg, md, wb = _run(raw, tmp_path, extra)
    main = md.split("### Sem preço")[0]
    # 1) nenhuma margem negativa na tabela comercial
    for line in _rows(main):
        assert not line.split("|")[2].strip().startswith("-"), line
    # 2) toda linha de TODOS os blocos tem os 2 links (ou a marca explicita de ausencia)
    for line in _rows(md):
        assert ("[oferta](" in line or "oferta: sem link" in line), line
        assert ("[TCG](" in line or "TCG: sem link" in line), line
    # 3) sem consulta ao PC → nenhuma COMPRA (liquidez nao verificada), so REVISAR com motivo
    ws = wb["All Listings"]
    head = [c.value for c in ws[1]]
    dec = [r[head.index("Decisão")] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert "COMPRA" not in dec and "REVISAR" in dec
    assert "não certificada pelo scanner" in main   # XLSX antigo: sem coluna 'Ref Compatível'
    # 4) soma dos baldes + extras == linhas de entrada; auditoria == linha informada no chat
    c = pp.bucket_counts(pp.enrich_df(raw, costs=cfg.costs), cfg, extra)
    assert c["COMPRA"] + c["REVISAR"] + c["NAO"] + c["AUDITORIA"] + sum(c["EXTRAS"].values()) == len(raw) + 2
    assert c["ENTRADA"] == len(raw) + 2
    assert c["AUDITORIA"] > 0
    assert f"{c['AUDITORIA']} oportunidade(s) com margem negativa" in md
    assert wb["Auditoria"].max_row - 1 == c["AUDITORIA"]
    # 5) blocos extras presentes, com motivo, sem margem
    assert "sem preço no provider" in md and "sem ref 1st" in md
    assert "Sem preço" in wb.sheetnames and "Sem Ref Compatível" in wb.sheetnames
    assert len(_rows(main)) == c["COMPRA"] + c["REVISAR"]


def test_real_xlsx_com_pc_simulado_so_compra_com_liquidez(raw, tmp_path, monkeypatch):
    raw = raw.copy()
    raw["Edição"] = "Unlimited"
    raw["Ref Compatível"] = "Sim"
    calls = []

    def fake_demand(name, number, set_label, *, edition, cache_dir=None, variant=None, today=None):
        calls.append((name, number, set_label))
        n = len(calls)
        if n % 3 == 0:
            return {"pc_status": "INDISPONIVEL_403", "pc_url": None}
        return {"pc_status": "OK", "pc_url": f"https://www.pricecharting.com/game/x/y-{n}",
                "pc_vendas_30d": 0 if n % 3 == 1 else 3, "pc_vendas_90d": 9, "pc_truncado": False}

    monkeypatch.setattr(pcr, "resolve_pc_demand", fake_demand)
    monkeypatch.setattr(pcr, "fetch_page", lambda url, cache_dir=None: "<html></html>")
    cfg = pp.DecisionConfig()
    out = tmp_path / "rel.xlsx"
    pp.write_report(raw, cfg, out, fx_usd_brl=5.5, pc_refs=10)
    assert 0 < len(calls) <= 10 and len(set(calls)) == len(calls)   # teto e sem consulta repetida
    wb = openpyxl.load_workbook(out)
    ws = wb["All Listings"]
    head = [c.value for c in ws[1]]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    compras = [r for r in rows if r[head.index("Decisão")] == "COMPRA"]
    assert compras, "o mock libera liquidez em parte das consultas"
    for r in compras:
        assert r[head.index("PC Status")] == "OK"
        assert int(str(r[head.index("Vendas 90d")]).lstrip("≥")) >= 5
        assert int(str(r[head.index("Vendas 30d")]).lstrip("≥")) >= 1
        assert float(r[head.index("Margem venda %")]) >= cfg.min_net_margin


def test_real_xlsx_ref_certificada_mas_sem_consulta_pc_e_revisar_por_liquidez(raw, tmp_path):
    raw = raw.copy()
    raw["Ref Compatível"] = "Sim"
    cfg, md, wb = _run(raw, tmp_path)
    rows = _rows(md)
    assert any("liquidez não verificada: NAO_CONSULTADO" in l for l in rows)
    assert not any("| COMPRA" in l for l in rows)
