"""P1 — postprocess ligado aos modulos unicos (economia, chase, liquidez PC).

Regras do dono: margem sobre VENDA no corte (30%), ROI so informativo; Hub 6% nunca em
dobro; chase so informativo; COMPRA exige liquidez verificada (>=5 vendas/90d e >=1/30d);
margem negativa fora da tabela comercial (aba Auditoria); nada some em silencio.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import pytest

import cardtrader_postprocess as pp
import pricecharting_ref as pcr

CT = "https://www.cardtrader.com/cards/1"
TCG = "https://www.tcgplayer.com/product/1"
OK_PC = dict(pc_status="OK", pc_vendas_30d=2, pc_vendas_90d=7, pc_truncado=False,
             pc_edicao="unl", pc_url="https://www.pricecharting.com/game/x/y-1")


def _raw(**over):
    base = {
        "Card Name": "Lugia", "Nº": "9", "Set": "Neo Genesis (n1)", "Rarity": "Holo Rare",
        "Condição": "NM", "Qtd": 1, "Scan R$ (raw)": 60.0, "TCG Market (BRL)": 100.0,
        "TCG Market (USD)": 18.0, "Validation Status": "NOT_VALIDATED",
        "Variant": "holofoil", "Ref Compatível": "Sim", "Link CardTrader": CT, "Link TCG": TCG, "Edição": "Unlimited",
    }
    base.update(over)
    return pd.DataFrame([{k: v for k, v in base.items() if v is not None}])


def _enrich(raw, **kw):
    return pp.enrich_df(raw, **kw)


def _row(df, i=0):
    return df.iloc[i]


# ───────── item 1: margem unica (ct_economics) ─────────
def test_margem_sobre_venda_e_roi_separados():
    r = _row(_enrich(_raw(**{"Scan R$ (raw)": 75.0})))
    assert r["net_margin"] == pytest.approx(0.25)          # (100-75)/100, NAO 33,3%
    assert r["roi_aquisicao"] == pytest.approx(1 / 3)
    d, _ = pp.classify_decision(r, pp.DecisionConfig(min_net_margin=0.30))
    assert d != "COMPRA"


def test_hub_nunca_conta_duas_vezes():
    scan = _row(_enrich(_raw()))                                   # preco cru: Hub entra
    live = _row(_enrich(_raw(**{"LIVE R$ (real)": 60.0, "Validation Status": "VALIDATED_MARKUP"})))
    assert not scan["compra_inclui_hub"] and live["compra_inclui_hub"]
    assert scan["lucro_liquido_parcial"] == pytest.approx(100 - (60 * 1.06 + 0.50))
    assert live["lucro_liquido_parcial"] == pytest.approx(100 - (60 + 0.50))  # sem 2o Hub


def test_liquida_e_parcial_com_custos_nao_informados_e_frete_por_carta():
    r1 = _row(_enrich(_raw(Qtd=1)))
    r5 = _row(_enrich(_raw(Qtd=5)))
    assert str(r1["liquida_status"]).startswith("PARCIAL")
    for c in ("iof_rate", "spread_cambio_rate", "import_tax_rate"):
        assert c in r1["liquida_status"]
    assert r1["lucro_liquido_parcial"] == r5["lucro_liquido_parcial"]   # sem desconto por qtd


def test_custos_so_vem_de_flag_explicita():
    r = _row(_enrich(_raw(), costs=pp.Costs(iof_rate=0.0038)))
    assert "iof_rate" not in r["liquida_status"]


def test_corte_padrao_30_e_cabecalho_mostra_o_usado():
    assert pp.DecisionConfig().min_net_margin == 0.30
    assert pp.build_parser().parse_args(["-i", "a", "-o", "b"]).min_net_margin == 0.30
    df = _enrich(_raw())
    assert "corte 30%" in pp.build_delivery_markdown(df, pp.DecisionConfig())
    assert "corte 25%" in pp.build_delivery_markdown(df, pp.DecisionConfig(min_net_margin=0.25))


# ───────── item 2: chase informativo ─────────
@pytest.mark.parametrize("rarity", ["Common", "Holo Rare", "Double Rare"])
def test_chase_nao_decide(rarity):
    df = _enrich(_raw(Rarity=rarity, **{"Scan R$ (raw)": 50.0, "Validation Status": "VALIDATED_REAL",
                                         "LIVE R$ (real)": 50.0}))
    for k, v in OK_PC.items():
        df[k] = v
    assert pp.classify_decision(_row(df), pp.DecisionConfig())[0] == "COMPRA"


def test_chase_vem_da_coluna_do_scanner():
    df = _enrich(_raw(Rarity="Common", **{"Chase Tier": "TOP"}))
    assert _row(df)["chase_tier"] == "TOP"


def test_sem_copia_do_chase_nem_ramo_de_chase():
    src = open(pp.__file__, encoding="utf-8").read()
    assert "CHASE_TIER_PATTERNS" not in src and "revisar_chase_modest" not in src
    assert not hasattr(pp.DecisionConfig(), "revisar_chase_modest_min_net")


# ───────── item 3: liquidez ─────────
def _cand(**pc):
    df = _enrich(_raw(**{"Scan R$ (raw)": 50.0, "Validation Status": "VALIDATED_REAL",
                         "LIVE R$ (real)": 50.0}))
    for k, v in {**OK_PC, **pc}.items():
        df[k] = v
    return _row(df)


def test_compra_com_liquidez_ok_tem_motivo():
    d, why = pp.classify_decision(_cand(), pp.DecisionConfig())
    assert d == "COMPRA" and "7 vendas/90d" in why


@pytest.mark.parametrize("pc,frag", [
    (dict(pc_vendas_90d=4), "liquidez baixa"),
    (dict(pc_vendas_30d=0), "liquidez baixa"),
    (dict(pc_status="INDISPONIVEL_403"), "liquidez não verificada: INDISPONIVEL_403"),
    (dict(pc_status="EDICAO_DIVERGENTE"), "liquidez não verificada: EDICAO_DIVERGENTE"),
    (dict(pc_status="SEM_PAGINA_COMPATIVEL"), "liquidez não verificada"),
])
def test_sem_liquidez_vira_revisar_com_motivo(pc, frag):
    d, why = pp.classify_decision(_cand(**pc), pp.DecisionConfig())
    assert d == "REVISAR" and frag in why


def test_sem_consulta_pc_e_revisar_mesmo_com_margem_altissima():
    df = _enrich(_raw(**{"Scan R$ (raw)": 10.0, "Validation Status": "VALIDATED_REAL",
                         "LIVE R$ (real)": 10.0}))
    d, why = pp.classify_decision(_row(df), pp.DecisionConfig())
    assert d == "REVISAR" and why.startswith("liquidez não verificada")


def test_piso_truncado_conta_como_pelo_menos():
    d, why = pp.classify_decision(_cand(pc_truncado=True, pc_vendas_90d=30, pc_vendas_30d=12),
                                  pp.DecisionConfig())
    assert d == "COMPRA" and "≥30" in why
    d, why = pp.classify_decision(_cand(pc_truncado=True, pc_vendas_90d=3), pp.DecisionConfig())
    assert d == "REVISAR" and "pelo menos 3" in why


def test_limites_configuraveis():
    cfg = pp.DecisionConfig(min_sales_90d=8, min_sales_30d=3)
    assert pp.classify_decision(_cand(), cfg)[0] == "REVISAR"
    assert pp.build_parser().parse_args(["-i", "a", "-o", "b"]).min_sales_90d == 5
    assert pp.build_parser().parse_args(["-i", "a", "-o", "b"]).min_sales_30d == 1


def test_ofertas_reverse_nao_confirmam_acabamento():
    df = _enrich(_raw(Variant="reverseHolofoil", Acabamento="Reverse",
                      **{"Scan R$ (raw)": 50.0, "LIVE R$ (real)": 50.0,
                         "Validation Status": "VALIDATED_REAL"}))
    for k, v in OK_PC.items():
        df[k] = v
    d, why = pp.classify_decision(_row(df), pp.DecisionConfig())
    assert d == "REVISAR" and "acabamento" in why


# ───────── item 4: margem negativa ─────────
def _neg_alpha():
    return _raw(**{"Nº": "50a", "Scan R$ (raw)": 120.0})   # alpha-suffix + margem -20%


def test_margem_negativa_nao_entra_na_tabela_e_vai_para_auditoria():
    df = _enrich(pd.concat([_raw(), _neg_alpha().assign(**{"Card Name": "Golduck"})],
                           ignore_index=True))
    d, why = pp.classify_decision(df.iloc[1], pp.DecisionConfig())
    assert d == "AUDITORIA" and "margem negativa" in why
    md = pp.build_delivery_markdown(df, pp.DecisionConfig())
    assert "Golduck" not in md
    assert "1 oportunidade(s) com margem negativa" in md
    assert len(pp.build_auditoria_sheet(df, pp.DecisionConfig())) == 1


def test_so_margem_negativa_nao_vira_near_miss():
    df = _enrich(_neg_alpha())
    md = pp.build_delivery_markdown(df, pp.DecisionConfig())
    assert "Lugia" not in md and "margem negativa" in md


# ───────── item 5: blocos Sem preço / Sem Ref Compatível ─────────
def test_blocos_extras_com_dois_links_e_motivo():
    df = _enrich(_raw())
    extra = pd.DataFrame([{"Card Name": "Mew", "Set": "wiz", "Nº": "8", "Qtd": 2,
                           "Motivo": "sem preço no provider", "Link CardTrader": CT,
                           "Link TCG": None}])
    md = pp.build_delivery_markdown(df, pp.DecisionConfig(), extra_blocks={"Sem preço": extra})
    blk = md.split("### Sem preço")[1]
    assert "sem preço no provider" in blk and "TCG: sem link" in blk and "[oferta](" in blk
    assert "Margem" not in blk.split("\n")[2]


def test_sem_aba_sem_bloco():
    md = pp.build_delivery_markdown(_enrich(_raw()), pp.DecisionConfig())
    assert "### Sem preço" not in md and "Sem Ref Compatível" not in md


# ───────── item 6: PriceCharting ─────────
def _five_same():
    return _enrich(pd.concat([_raw(**{"Scan R$ (raw)": 50.0 + i, "Validation Status": "VALIDATED_REAL",
                                      "LIVE R$ (real)": 50.0 + i, "Link CardTrader": CT + str(i)})
                              for i in range(5)], ignore_index=True))


def test_cinco_linhas_mesma_referencia_uma_consulta():
    df, calls = _five_same(), []

    def dem(name, number, set_label, *, edition, cache_dir=None, variant=None, today=None):
        calls.append((name, edition))
        return {**OK_PC, "pc_url": "https://www.pricecharting.com/game/a/b-9"}

    pp.attach_pc_refs(df, pp.DecisionConfig(), top_md=None, limit=100, demand_resolver=dem,
                      page_fetcher=lambda url, cache_dir=None: "<html></html>")
    assert calls == [("Lugia", "unl")]
    assert (df["pc_vendas_90d"] == 7).all()
    assert df.attrs["pc_stats"] == {"consultas_unicas": 1, "linhas_atendidas": 5}


def test_edicao_ausente_nao_consulta_e_marca():
    raw = _raw(**{"Scan R$ (raw)": 50.0, "Validation Status": "VALIDATED_REAL", "LIVE R$ (real)": 50.0})
    df = _enrich(raw.drop(columns=["Edição"]))
    calls = []
    pp.attach_pc_refs(df, pp.DecisionConfig(), top_md=None, limit=10,
                      demand_resolver=lambda *a, **k: calls.append(1))
    assert not calls and df.iloc[0]["pc_status"] == "EDICAO_NAO_INFORMADA"
    d, why = pp.classify_decision(df.iloc[0], pp.DecisionConfig())
    assert d == "REVISAR" and "edição não informada" in why


def test_consultas_ordenadas_por_lucro_e_limitadas():
    raw = pd.concat([_raw(**{"Card Name": n, "Scan R$ (raw)": c, "TCG Market (BRL)": t,
                             "Validation Status": "VALIDATED_REAL", "LIVE R$ (real)": c})
                     for n, c, t in [("A", 50, 100), ("B", 100, 500), ("C", 30, 100)]],
                    ignore_index=True)
    df, calls = _enrich(raw), []

    def dem(name, *a, edition, **k):
        calls.append(name)
        return {**OK_PC}

    pp.attach_pc_refs(df, pp.DecisionConfig(), top_md=None, limit=2, demand_resolver=dem,
                      page_fetcher=lambda *a, **k: "")
    assert calls == ["B", "C"]          # lucro 400, 70; A (50) fica sem credito


def test_teto_firecrawl_maximo_100():
    with pytest.raises(SystemExit):
        pp.build_parser().parse_args(["-i", "a", "-o", "b", "--pc-firecrawl", "101"])
    assert pp.build_parser().parse_args(["-i", "a", "-o", "b", "--pc-firecrawl", "100"]).pc_firecrawl == 100
    assert pp.build_parser().parse_args(["-i", "a", "-o", "b"]).pc_firecrawl == 0


def test_mediana_pc_exclui_graduadas_e_lotes():
    html = open(os.path.join(os.path.dirname(__file__), "fixtures", "pricecharting_real",
                             "lugia_unlimited.html"), encoding="utf-8").read()
    sales = pcr.parse_sold_listings(html)
    med, n = pp.pc_median_ungraded(html)
    keep = [s for s in sales if pcr._exclusion_reason(s["title"]) is None]
    assert n > 0 and med == pcr.median_recent_sold(keep)[0]


def test_ajuda_nao_diz_cache_24h():
    assert "cache 24h" not in open(pp.__file__, encoding="utf-8").read()


def test_colunas_de_liquidez_na_tabela_e_dois_links():
    df = _enrich(_raw(**{"Scan R$ (raw)": 50.0, "Validation Status": "VALIDATED_REAL",
                         "LIVE R$ (real)": 50.0}))
    for k, v in {**OK_PC, "pc_truncado": True, "pc_vendas_90d": 30}.items():
        df[k] = v
    md = pp.build_delivery_markdown(df, pp.DecisionConfig())
    assert "| Vendas 30d | Vendas 90d |" in md and "≥30" in md
    line = next(l for l in md.splitlines() if l.startswith("| 1 |"))
    assert "[oferta](" in line and "[TCG](" in line
