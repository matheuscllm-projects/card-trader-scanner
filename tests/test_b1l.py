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


# ───────── (3) versao da logica de preco: a ambiguidade/holo mudaram, cache de 24h antigo nao serve ─────────
def test_price_cache_key_changes_with_b1l_logic_version():
    import ct_variants as cv
    k = cv.price_cache_key("neo1", "9", "Lugia", False, False, True)
    assert k.startswith("pokemontcg:4:") and ":3:" not in k.split("neo1")[0]


# ───────── (4) denominador declarado que contradiz TODOS os candidatos = ambiguo (nome nao desempata) ─────────
_MEW = [{"name": "Mew", "number": "08/53"}, {"name": "Mew - 8 (Glossy Finish)", "number": "8"}]


def test_declared_denominator_contradicting_all_candidates_is_ambiguous():
    import ct_variants as cv
    chosen, why = cv.resolve_candidates(_MEW, "mew", "8/100")
    assert chosen is None and "ambígua" in why


def test_matching_denominator_still_resolves_and_exact_name_without_denominator_needs_one_candidate():
    import ct_variants as cv
    assert cv.resolve_candidates(_MEW, "Mew", "8/53")[0] is _MEW[0]
    assert cv.resolve_candidates(_MEW, "  MEW ", "8")[0] is _MEW[0]                 # nome exato (caixa/espacos), unico
    assert cv.resolve_candidates(_MEW, "Mew - 8", "8")[0] is None                  # prefixo/substring nunca
    dup = [{"name": "Mew", "number": "8"}, {"name": "mew", "number": "08"}]
    assert cv.resolve_candidates(dup, "Mew", "8")[0] is None                       # 2 nomes identicos = ambiguo


# ───────── (6) skip-list x provider: entrada sem provider / de outro provider NAO pula o set ─────────
def test_skip_list_entry_records_the_provider_that_wrote_it(tmp_path, monkeypatch):
    import cardtrader_scanner as sc
    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "scanner_skip_list.json")
    sc.add_to_skip_list("n1", "no_coverage_40_consecutive_misses", provider="pokemontcg")
    entry = sc.load_skip_list()["reasons"]["n1"]
    assert entry["provider"] == "pokemontcg" and entry["reason"].startswith("no_coverage")


def test_skip_set_only_keeps_entries_written_by_the_current_provider():
    import cardtrader_scanner as sc
    data = {"skipped": ["a", "b", "c", "d"], "reasons": {
        "a": {"reason": "no_coverage_x", "added_at": "2099-01-01T00:00:00Z", "provider": "tcgcsv"},
        "b": {"reason": "no_coverage_x", "added_at": "2099-01-01T00:00:00Z", "provider": "pokemontcg"},
        "c": {"reason": "no_coverage_x", "added_at": "2099-01-01T00:00:00Z"},      # dict sem provider
        "d": "unexpected_error_legada"}}                                           # str legada
    assert sc.effective_skip_set(data, "tcgcsv") == {"a"}
    assert sc.effective_skip_set(data, "pokemontcg") == {"b"}


def _parse_scanner(monkeypatch, argv):
    import cardtrader_scanner as sc
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py", *argv])
    return sc.parse_args()


def test_default_provider_is_tcgcsv_and_fallback_flag_help_tells_the_truth(monkeypatch, capsys):
    assert _parse_scanner(monkeypatch, []).provider == "tcgcsv"
    assert _parse_scanner(monkeypatch, ["--provider", "pokemontcg", "--no-tcgcsv-fallback"]).no_tcgcsv_fallback
    with pytest.raises(SystemExit):
        _parse_scanner(monkeypatch, ["--help"])
    out = " ".join(capsys.readouterr().out.split())
    help_txt = out[out.rindex("--no-tcgcsv-fallback"):][:900]
    assert "só vale com --provider pokemontcg" in help_txt.lower() and "inócua" in help_txt


# ───────── (7) "Margem % REAL" e "Margem % (scan)" ambas vazias: recalcula por ct_economics, nunca fica NaN ─────────
def test_row_with_both_gross_margin_columns_empty_is_recomputed_from_prices():
    from test_p1_postprocess import _raw
    raw = _raw(**{"LIVE R$ (real)": 60.0, "TCG Market (BRL)": 100.0, "Margem % REAL": float("nan"),
                  "Margem % (scan)": float("nan")})
    df = pp.enrich_df(raw)
    assert df["net_margin"].iloc[0] == pytest.approx(0.40)
    assert df["margin_source"].iloc[0] == "recomputed"


def test_row_without_prices_goes_to_sem_preco_with_a_reason_never_vanishes():
    from test_p1_postprocess import _raw
    raw = _raw(**{"LIVE R$ (real)": float("nan"), "Scan R$ (raw)": float("nan"), "Margem % REAL": float("nan"),
                  "Margem % (scan)": float("nan")})
    df = pp.enrich_df(raw)
    assert pd.isna(df["net_margin"].iloc[0]) and df["margin_source"].iloc[0] == "sem_margem"
    assert str(df["sem_margem_motivo"].iloc[0]).strip()
    cfg = pp.DecisionConfig()
    d, why = pp.classify_decision(df.iloc[0], cfg)
    assert d == "SEM REF" and why
    md = pp.build_delivery_markdown(df, cfg, fx_usd_brl=5.0)
    assert "Sem referência" in md or "Sem preço" in md
