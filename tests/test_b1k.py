"""B1k — ensaio real de liquidez (final3/vintage34-pc): divergência de referências, margem pela menor,
campo de preço, drift de margem, contabilidade do PriceCharting."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_b1e import _real_provider  # noqa: E402


def _row(**k):
    r = {"net_margin": 0.50, "lucro_liq": 100.0, "validation_status": "VALIDATED_REAL", "compra_inclui_hub": True,
         "ref_compativel": "Sim", "card_number": "1", "set_code": "n1", "ref_age_dias": 0.0,
         "pc_status": "OK", "pc_vendas_30d": 10, "pc_vendas_90d": 28, "pc_truncado": False,
         "reference_price_usd": 100.0, "pc_median_usd": 100.0}
    r.update(k)
    return pd.Series(r)


# linhas REAIS do ensaio (relatorio.md): CT US$, TCG US$, PC US$, margem sobre a venda
@pytest.mark.parametrize("name,tcg,pc,nm", [("Typhlosion uf 017", 979.82, 11.25, 0.94),
                                            ("Meowth skg 078", 220.00, 69.99, 0.61)])
def test_diverging_references_are_never_compra(name, tcg, pc, nm):
    d, why = pp.classify_decision(_row(net_margin=nm, reference_price_usd=tcg, pc_median_usd=pc), pp.DecisionConfig())
    assert d == "REVISAR" and f"referências divergem: TCG US${tcg:.2f} x PC US${pc:.2f}" in why, (name, d, why)


def test_magneton_is_revisar_because_margin_by_the_lower_reference_is_below_the_cut():
    # CT 28.83, TCG 46.70, PC 39.50: divergência 15% (< 30%), mas margem pela PC = 1-(1-0.38)*46.70/39.50 = 27% < 30%
    d, why = pp.classify_decision(_row(net_margin=0.38, reference_price_usd=46.70, pc_median_usd=39.50, lucro_liq=300.0),
                                  pp.DecisionConfig())
    assert d == "REVISAR" and "menor referência" in why and "PC US$39.50" in why and "27%" in why


def test_coherent_references_stay_compra_and_missing_pc_keeps_the_liquidity_rule():
    cfg = pp.DecisionConfig()
    assert pp.classify_decision(_row(net_margin=0.50, reference_price_usd=100.0, pc_median_usd=95.0), cfg)[0] == "COMPRA"
    sem_pc = _row(pc_status="SEM_PAGINA_COMPATIVEL", pc_median_usd=float("nan"))
    d, why = pp.classify_decision(sem_pc, cfg)
    assert d == "REVISAR" and "liquidez não verificada" in why           # regra atual intacta


def test_divergence_limit_is_configurable_and_validated():
    row = _row(net_margin=0.60, reference_price_usd=100.0, pc_median_usd=60.0)        # divergência 40% da maior
    assert pp.classify_decision(row, pp.DecisionConfig())[0] == "REVISAR"
    assert pp.classify_decision(row, pp.DecisionConfig(max_ref_divergence=0.50))[0] == "COMPRA"
    parser = pp.build_parser()                                         # B1l: comportamento, nao grep no fonte
    assert parser.parse_args(["-i", "a", "-o", "b"]).max_ref_divergence == pytest.approx(0.30)
    assert parser.parse_args(["-i", "a", "-o", "b", "--max-ref-divergence", "0.5"]).max_ref_divergence == 0.5
    with pytest.raises(SystemExit):
        parser.parse_args(["-i", "a", "-o", "b", "--max-ref-divergence", "abc"])


def test_pc_diverge_flag_uses_the_same_function_as_the_rule():
    assert pp.ref_divergence(100.0, 60.0) == pytest.approx(0.40)
    assert pp.ref_divergence(60.0, 100.0) == pytest.approx(0.40)             # simétrica, sobre a MAIOR


# ───────── (2) campo de preço: só marketPrice; nunca mid/high/low ─────────
def test_tcgcsv_never_falls_back_to_mid_low_or_high_when_market_is_null():
    rows = [{"pid": 90103, "name": "Typhlosion", "number": "17/115", "rarity": "Holo Rare", "prices": [["Holofoil", None]]}]
    p = _real_provider("uf", 1398, "EX Unseen Forces", "2005-08-22T00:00:00", rows)
    # injeta mid/low/high no índice como o tcgcsv real faria
    for idx in p._set_index.values():
        for v in idx.values():
            for var in v.values():
                var.update({"low": 504.58, "mid": 589.99, "high": 1104.25})
    assert p.market_price_usd("Typhlosion", "uf", "017", rarity="Holo Rare") is None
    assert p.last_ref_status == cv.SEM_PRECO


# ───────── (3) drift de margem: scanner e postprocess gravam a MESMA margem ─────────
def test_no_drift_warning_when_the_scanner_writes_the_gross_margin_columns(capsys):
    from test_p1_postprocess import _raw
    live, ref = 60.0, 100.0
    gross = (ref - live) / ref                                  # margem sobre a venda (mesma função do postprocess)
    raw = _raw(**{"LIVE R$ (real)": live, "Scan R$ (raw)": 55.0, "TCG Market (BRL)": ref,
                  "Margem % REAL": round(gross, 4), "Margem % (scan)": 0.45, "Net Margin % REAL": gross - 0.09,
                  "Net Margin % (scan)": 0.36})
    df = pp.enrich_df(raw)
    assert "divergia de ct_economics" not in capsys.readouterr().out
    assert df["margin_source"].iloc[0] == "input" and df["net_margin"].iloc[0] == pytest.approx(gross)


# ───────── (4) contabilidade do PriceCharting ─────────
def test_pc_stats_count_duplicates_avoided_and_status_breakdown():
    from test_pricecharting_ref import _pc_enriched, _OK
    df, cfg = _pc_enriched()
    df = pd.concat([df, df.iloc[[0]].copy()], ignore_index=True)           # linha repetida = 1 consulta
    calls = []

    def resolver(*a, **k):
        calls.append(a)
        return dict(_OK)
    pp.attach_pc_refs(df, cfg, top_md=0, limit=10, demand_resolver=resolver, page_fetcher=lambda *a, **k: "")
    st = df.attrs["pc_stats"]
    assert st["consultas_duplicadas_evitadas"] == st["linhas_atendidas"] - st["consultas_unicas"] >= 1
    assert st["por_status"] == {"OK": st["consultas_unicas"]}


def test_budget_exhausted_has_its_own_not_consulted_status_and_text():
    assert "NAO_CONSULTADO_ORCAMENTO" in pp._PC_STATUS_TEXT
    from test_pricecharting_ref import _pc_enriched
    df, cfg = _pc_enriched()
    pp.attach_pc_refs(df, cfg, top_md=0, limit=10,
                      demand_resolver=lambda *a, **k: {"pc_status": "INDISPONIVEL_ORCAMENTO", "pc_motivo": "teto 40"},
                      page_fetcher=lambda *a, **k: "")
    assert set(df["pc_status"].dropna()) & {"NAO_CONSULTADO_ORCAMENTO"}
    assert df.attrs["pc_stats"]["por_status"].get("NAO_CONSULTADO_ORCAMENTO", 0) >= 1


def test_footer_and_xlsx_carry_the_pc_summary_and_motive():
    assert "pc_motivo" in pp._SHEET_COLS and pp._SHEET_RENAME.get("pc_motivo") == "PC Motivo"
    from test_pricecharting_ref import _pc_enriched
    df, cfg = _pc_enriched()                                           # B1l: rodape GERADO, nao grep no fonte
    md = pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0, pc_summary={
        "consultas_unicas": 2, "linhas_atendidas": 5, "consultas_duplicadas_evitadas": 3, "por_status": {"OK": 2}})
    assert "3 consulta(s) duplicada(s) evitada(s)" in md and "por status: OK 2" in md


def test_truncated_count_meets_the_minimum_only_when_the_floor_reaches_it():
    cfg = pp.DecisionConfig()
    ok, _ = pp.liquidity_verdict(_row(pc_vendas_90d=17, pc_vendas_30d=5, pc_truncado=True), cfg)
    assert ok
    ok, why = pp.liquidity_verdict(_row(pc_vendas_90d=3, pc_vendas_30d=1, pc_truncado=True), cfg)
    assert not ok and "pelo menos 3" in why
