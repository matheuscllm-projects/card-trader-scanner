"""Contrato dos 2 links na entrega + paridade do chase tier scanner<->postprocess.

Linha sem URL de oferta ou de referência TCG nunca sai calada com 1 link só:
fica na tabela, a célula Links diz o que falta e a Flag marca a linha.
Nunca inventa URL.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import pytest

import cardtrader_postprocess as pp
import cardtrader_scanner as sc

CT = "https://www.cardtrader.com/cards/111"
TCG = "https://prices.pokemontcg.io/tcgplayer/sv4-193"


@pytest.mark.parametrize("missing", ["", None, float("nan"), "   ", "n/a", "ftp://x"])
def test_links_cell_missing_tcg_is_explicit(missing):
    cell = pp._md_links_cell(CT, missing)
    assert f"[oferta]({CT})" in cell
    assert "TCG: sem link" in cell
    assert "[TCG](" not in cell


@pytest.mark.parametrize("missing", ["", None, float("nan")])
def test_links_cell_missing_oferta_is_explicit(missing):
    cell = pp._md_links_cell(missing, TCG)
    assert f"[TCG]({TCG})" in cell
    assert "oferta: sem link" in cell
    assert "[oferta](" not in cell


def test_links_cell_both_present_unchanged():
    assert pp._md_links_cell(CT, TCG) == f"[oferta]({CT}) · [TCG]({TCG})"


def _df(link_ct, link_tcg):
    raw = pd.DataFrame({
        "Card Name": ["Plusle"], "Nº": [193], "Set": ["Paradox Rift (par)"],
        "Rarity": ["Double Rare"], "Condição": ["NM"], "Qtd": [3],
        "LIVE R$ (real)": [120.0], "TCG Market (BRL)": [240.0],
        "TCG Market (USD)": [44.0], "Net Margin % REAL": [0.50],
        "Lucro R$ REAL": [120.0], "Validation Status": ["VALIDATED_REAL"],
        "Link CardTrader": [link_ct], "Link TCG": [link_tcg],
    })
    cfg = pp.DecisionConfig()
    return pp.enrich_df(raw, hub_fee_rate=cfg.hub_fee_rate), cfg


def _row_line(md):
    return next(l for l in md.splitlines() if "Plusle" in l)


@pytest.mark.parametrize("link_ct,link_tcg,cell,flag", [
    (CT, "", "TCG: sem link", "sem link TCG"),
    (CT, None, "TCG: sem link", "sem link TCG"),
    ("", TCG, "oferta: sem link", "sem link oferta"),
])
def test_row_with_missing_link_stays_and_is_flagged(link_ct, link_tcg, cell, flag):
    df, cfg = _df(link_ct, link_tcg)
    line = _row_line(pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0))
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    assert cell in cells[-1]
    assert flag in cells[-2]  # coluna Flag


def test_row_with_both_links_has_no_missing_flag():
    df, cfg = _df(CT, TCG)
    line = _row_line(pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0))
    assert "sem link" not in line


def test_chase_tier_patterns_parity_scanner_vs_postprocess():
    import ct_chase
    assert not hasattr(sc, "CHASE_TIER_PATTERNS")  # B1: o scanner importa do ct_chase (sem copia)
    assert sc.classify_chase_tier is ct_chase.classify_chase_tier
    assert pp.classify_chase_tier is ct_chase.classify_chase_tier  # sem copia no postprocess


@pytest.mark.parametrize("bad", ["http", "httpfoo", "http:", "https://", "http://  "])
def test_url_without_host_is_invalid_in_cell_and_flag(bad):
    assert "TCG: sem link" in pp._md_links_cell(CT, bad)
    df, cfg = _df(CT, bad)
    line = _row_line(pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0))
    assert "sem link TCG" in line


def test_uppercase_scheme_is_valid_in_cell_and_flag():
    url = "HTTPS://exemplo.com/x"
    assert f"[TCG]({url})" in pp._md_links_cell(CT, url)
    df, cfg = _df(CT, url)
    line = _row_line(pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0))
    assert "sem link" not in line
