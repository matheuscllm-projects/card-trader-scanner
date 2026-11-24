"""B1l — achados da revisao independente: PC compativel sem mediana, limite unico de divergencia,
versao de preco, denominador contraditorio, skip-list x provider, margem sem fonte."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
from test_b1k import _row  # noqa: E402


# ───────── (1) pc_status OK sem mediana / referencia principal invalida nunca e COMPRA ─────────
@pytest.mark.parametrize("med", [float("nan"), 0.0, None, -3.0])
def test_pc_ok_without_finite_positive_median_is_revisar(med):
    row = _row(pc_median_usd=med)
    d, why = pp.classify_decision(row, pp.DecisionConfig())
    assert d == "REVISAR" and "PC compatível sem mediana" in why, (d, why)


def test_pc_ok_with_missing_median_column_is_revisar():
    row = _row().drop("pc_median_usd")
    d, why = pp.classify_decision(row, pp.DecisionConfig())
    assert d == "REVISAR" and "PC compatível sem mediana" in why


@pytest.mark.parametrize("tcg", [float("nan"), 0.0, None, -1.0])
def test_pc_ok_with_invalid_main_reference_is_revisar(tcg):
    d, why = pp.classify_decision(_row(reference_price_usd=tcg), pp.DecisionConfig())
    assert d == "REVISAR" and "referência principal inválida" in why, (d, why)


def test_median_failure_is_recorded_in_pc_motivo_and_log(capsys):
    from test_pricecharting_ref import _pc_enriched, _OK
    df, cfg = _pc_enriched()

    def boom(*a, **k):
        raise ValueError("pagina quebrada")
    pp.attach_pc_refs(df, cfg, top_md=0, limit=10, demand_resolver=lambda *a, **k: dict(_OK), page_fetcher=boom)
    ok = df[df["pc_status"] == "OK"]
    assert len(ok) and all("mediana" in str(m) and "ValueError" in str(m) for m in ok["pc_motivo"])
    assert "mediana" in capsys.readouterr().err


def test_empty_median_is_recorded_in_pc_motivo():
    from test_pricecharting_ref import _pc_enriched, _OK
    df, cfg = _pc_enriched()
    pp.attach_pc_refs(df, cfg, top_md=0, limit=10, demand_resolver=lambda *a, **k: dict(_OK),
                      page_fetcher=lambda *a, **k: "")
    ok = df[df["pc_status"] == "OK"]
    assert len(ok) and all("mediana" in str(m) for m in ok["pc_motivo"])


# ───────── (2) flag "PC diverge" usa o MESMO limite da decisao ─────────
def _flag_md(limit):
    from test_pricecharting_ref import _pc_enriched, _OK
    df, cfg = _pc_enriched()
    cfg.max_ref_divergence = limit
    df["reference_price_usd"] = 100.0
    df["pc_median_usd"] = 60.0                      # divergencia 40% da maior
    df["pc_status"] = "OK"
    return pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0, pc_summary={"consultas_unicas": 1})


@pytest.mark.parametrize("limit,expect", [(0.5, False), (0.2, True)])
def test_pc_diverge_flag_follows_cfg_limit(limit, expect):
    md = _flag_md(limit)
    assert ("PC diverge" in md.split("\n_")[0]) is expect
