"""P1b — defeitos reproduzidos por revisao independente (A1-A6 + Extra 1).

Cada teste e o cenario exato do relatorio. Regras do dono: nenhum dado presumido; sem
referencia compativel = sem margem e sem recomendacao; margem negativa nunca na tabela
comercial; edicao exata; causas distintas; nenhuma linha some.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import pytest

import cardtrader_postprocess as pp
import pricecharting_ref as pcr
from test_p1_postprocess import CT, TCG, OK_PC, _raw, _enrich, _row

NAN = float("nan")
CFG = pp.DecisionConfig()
ROW = re.compile(r"^\| \d+ \|")


def _table_rows(md):
    main = md.split("### Sem ")[0]
    return [l for l in main.splitlines() if ROW.match(l)]


def _validated(**over):
    base = {"Scan R$ (raw)": 50.0, "LIVE R$ (real)": 50.0, "Validation Status": "VALIDATED_REAL"}
    base.update(over)
    return _raw(**base)


# ───────── A1: sem margem calculavel = sem margem, sem herdar do XLSX ─────────
@pytest.mark.parametrize("over,heranca", [
    ({"TCG Market (BRL)": NAN, "Net Margin % REAL": 0.5, "Lucro R$ REAL": 80.0}, "50%"),
    ({"LIVE R$ (real)": NAN, "Scan R$ (raw)": NAN, "Net Margin % REAL": 0.25,
      "Lucro R$ REAL": 30.0}, "25%"),
])
def test_a1_sem_calculo_nao_herda_margem_do_xlsx(over, heranca):
    df = _enrich(_validated(**over))
    r = _row(df)
    assert pd.isna(r["net_margin"]) and pd.isna(r["lucro_liq"])
    d, why = pp.classify_decision(r, CFG)
    assert d == "SEM REF" and "invalida" in why
    md = pp.build_delivery_markdown(df, CFG)
    assert _table_rows(md) == []                       # fora da tabela comercial
    assert heranca not in md and "Margem 25%" not in md
    blk = md.split("### Sem referência")[1]
    assert "[oferta](" in blk and "[TCG](" in blk and "invalida" in blk


def test_a1_rodape_conta_sem_referencia_e_soma_fecha():
    raw = pd.concat([_validated(), _validated(**{"TCG Market (BRL)": NAN, "Net Margin % REAL": 0.5}),
                     _validated(**{"Scan R$ (raw)": 150.0, "LIVE R$ (real)": 150.0})],
                    ignore_index=True)
    df = pp._decide(_enrich(raw), CFG)
    c = pp.bucket_counts(df, CFG)
    assert c["SEM_REF"] == 1
    assert (c["COMPRA"] + c["REVISAR"] + c["NAO"] + c["AUDITORIA"] + c["SEM_REF"]
            + sum(c["EXTRAS"].values())) == c["ENTRADA"] == 3
    md = pp.build_delivery_markdown(df, CFG)
    assert "1 sem referência" in md
    summ = pp.build_summary(df, CFG)
    assert any("sem referência" in str(m).lower() for m in summ["Métrica"])


# ───────── A2: margem negativa fora da tabela em TODOS os modos ─────────
def _neg_and_ok():
    neg = _raw(**{"Card Name": "Golduck", "Scan R$ (raw)": 400.0, "LIVE R$ (real)": 400.0,
                  "TCG Market (BRL)": 300.0, "TCG Market (USD)": 60.0,
                  "Validation Status": "VALIDATED_REAL", "Link CardTrader": CT + "9"})
    return pd.concat([_validated(), neg], ignore_index=True)


MODES = {
    "padrao": {}, "top_n": {"top_n": 5}, "show_ratio": {"show_ratio": True},
    "min_ratio": {"show_ratio": True, "min_ratio": 0.1},
    "min_ratio_ebay": {"show_ratio": True, "min_ratio": 0.1, "ref_source": "ebay"},
    "min_ratio_piso": {"show_ratio": True, "min_ratio": 0.1, "min_ref_usd": 1.0},
}


@pytest.mark.parametrize("mode", list(MODES))
@pytest.mark.parametrize("so_negativa", [False, True])
@pytest.mark.parametrize("com_pc", [False, True])
def test_a2_margem_negativa_nunca_na_tabela_comercial(mode, so_negativa, com_pc):
    raw = _neg_and_ok()
    if so_negativa:
        raw = raw.iloc[[1]].reset_index(drop=True)
    df = _enrich(raw)
    if com_pc:
        df["pc_median_usd"] = 20.0
        df["pc_url"] = "https://www.pricecharting.com/game/x/y-1"
    md = pp.build_delivery_markdown(df, CFG, fx_usd_brl=5.0, **MODES[mode])
    assert not any("Golduck" in l for l in _table_rows(md)), md
    assert "1 oportunidade(s) com margem negativa" in md


# ───────── A3: edicao vazia/estranha nao e Unlimited ─────────
def _pc_run(edicao, limit=10):
    raw = _validated(**{"Set": "Base Set (base1)", "Edição": edicao})
    df = _enrich(raw)
    calls = []

    def dem(name, number, set_label, *, edition, cache_dir=None, variant=None, today=None):
        calls.append(edition)
        return {**OK_PC}

    pp.attach_pc_refs(df, CFG, top_md=None, limit=limit, demand_resolver=dem,
                      page_fetcher=lambda *a, **k: "")
    return df, calls


@pytest.mark.parametrize("edicao,frag", [("", "edição não informada"), (NAN, "edição não informada"),
                                          ("Shadowless", "Shadowless"), ("  ", "edição não informada")])
def test_a3_edicao_vazia_ou_fora_do_vocabulario_nao_consulta_e_revisa(edicao, frag):
    df, calls = _pc_run(edicao)
    assert calls == []
    r = df.iloc[0]
    assert r["pc_status"] == "EDICAO_NAO_INFORMADA"
    d, why = pp.classify_decision(r, CFG)
    assert d == "REVISAR" and frag in why


@pytest.mark.parametrize("edicao,esperada", [("1st Edition", "1st"), ("Unlimited", "unl"),
                                              ("1st", "1st"), ("unl", "unl")])
def test_a3_vocabulario_vem_do_ct_variants(edicao, esperada):
    df, calls = _pc_run(edicao)
    assert calls == [esperada]
    assert pp.classify_decision(df.iloc[0], CFG)[0] == "COMPRA"


def test_a3_sem_segunda_copia_do_vocabulario():
    import ct_variants
    src = open(pp.__file__, encoding="utf-8").read()
    assert "ct_variants" in src and ct_variants.ED_1ST == "1st"
    assert 'startswith("1st")' not in src


# ───────── A4: orcamento esgotado tem status proprio ─────────
def _tres_refs():
    raw = pd.concat([_validated(**{"Card Name": n, "Scan R$ (raw)": c, "LIVE R$ (real)": c,
                                   "TCG Market (BRL)": 500.0, "Link CardTrader": CT + n})
                     for n, c in [("A", 100), ("B", 120), ("C", 140)]], ignore_index=True)
    df = _enrich(raw)
    pp.attach_pc_refs(df, CFG, top_md=None, limit=2, demand_resolver=lambda *a, **k: {**OK_PC},
                      page_fetcher=lambda *a, **k: "")
    return df


def test_a4_limite_esgotado_status_proprio_motivo_e_contagem():
    df = _tres_refs()
    por = dict(zip(df["card_name"], df["pc_status"]))
    assert por["A"] == "OK" and por["B"] == "OK" and por["C"] == "LIMITE_CONSULTAS"
    d, why = pp.classify_decision(df[df["card_name"] == "C"].iloc[0], CFG)
    assert d == "REVISAR" and "limite" in why and "NAO_CONSULTADO" not in why
    st = df.attrs["pc_stats"]
    assert st["sem_consulta_limite_refs"] == 1 and st["sem_consulta_limite_linhas"] == 1
    md = pp.build_delivery_markdown(df, CFG, pc_summary=st)
    assert "1 referência(s) sem consulta por limite (1 linha(s))" in md


# ───────── A5: pc_truncado NA/NaN/None = desconhecido, sem excecao ─────────
@pytest.mark.parametrize("val", [pd.NA, NAN, None])
def test_a5_truncado_desconhecido_nao_lanca(val):
    row = {**OK_PC, "pc_truncado": val}
    ok, why = pp.liquidity_verdict(row, CFG)        # nao levanta TypeError
    assert ok and "desconhecido" in why
    ok, why = pp.liquidity_verdict({**row, "pc_vendas_90d": 3}, CFG)
    assert not ok and "truncamento desconhecido" in why


# ───────── A6: COMPRA exige LIVE presente ─────────
def test_a6_validated_sem_live_nao_e_compra():
    raw = _raw(**{"Scan R$ (raw)": 50.0, "Validation Status": "VALIDATED_REAL"})   # sem LIVE
    df = _enrich(raw)
    for k, v in OK_PC.items():
        df[k] = v
    d, why = pp.classify_decision(_row(df), CFG)
    assert d == "REVISAR" and "checkout" in why and "LIVE" in why


# ───────── Extra 1: reverse = pricecharting_ref.finish_status, sem logica paralela ─────────
@pytest.mark.parametrize("variant,acab", [("reverseHolofoil", None), ("normal", "Reverse"),
                                          ("normal", "Reverse Holo")])
def test_extra1_reverse_vem_do_modulo(variant, acab):
    assert pp._is_reverse_offer({"variant": variant, "acabamento": acab})
    assert pcr.finish_status(acab or variant) == pcr.FINISH_REVERSE_NAO_CONFIRMAVEL


def test_extra1_nao_reverse():
    assert not pp._is_reverse_offer({"variant": "holofoil", "acabamento": "Holo"})
