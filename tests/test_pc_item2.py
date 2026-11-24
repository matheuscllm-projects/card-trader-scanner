"""Item 2 (2026-11-24): mediana ungraded publica, teto de creditos no modulo, acabamento."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cardtrader_postprocess as pp  # noqa: E402
import pricecharting_ref as pcr  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "pricecharting_real"


def _page(name):
    return (FIX / name).read_text(encoding="utf-8")


def _table(rows):
    trs = "".join(
        f'<tr id="ebay-{i}"><td class="date">{d}</td><td class="title">{t}</td>'
        f'<td><span class="js-price">${p:.2f}</span></td></tr>'
        for i, (d, t, p) in enumerate(rows))
    return f'<div class="completed-auctions-used"><table>{trs}</table>'


ROWS = [("2026-11-20", "Lugia 9 Neo Genesis", 100.0),
        ("2026-11-19", "Lugia PSA 10 Neo Genesis", 5000.0),
        ("2026-11-18", "Lugia lot of 3 cards", 9000.0),
        ("2026-11-17", "Lugia 9 Neo Genesis", 120.0)]


def test_mediana_publica_exclui_graduada_e_lote():
    med, n = pcr.median_ungraded_sold(_table(ROWS))
    assert (med, n) == (110.0, 2)


def test_real_fixture_mediana_publica_igual_ao_filtro_do_sinal():
    html = _page("lugia_unlimited.html")
    keep = [s for s in pcr.parse_sold_listings(html) if pcr._exclusion_reason(s["title"]) is None]
    assert pcr.median_ungraded_sold(html) == pcr.median_recent_sold(keep)


def test_resolve_pc_ref_nao_inclui_graduada_nem_lote(monkeypatch):
    monkeypatch.setattr(pcr, "_resolve_pc_path", lambda *a, **k: "/game/x/y-1")
    monkeypatch.setattr(pcr, "fetch_page", lambda *a, **k: _table(ROWS))
    ref = pcr.resolve_pc_ref("Y", "1", "Set (st)")
    assert ref["median"] == 110.0 and ref["n_sales"] == 2


def test_postprocess_nao_usa_nome_privado_do_modulo():
    src = Path(pp.__file__).read_text(encoding="utf-8")
    assert not re.search(r"pricecharting_ref\._\w", src)
    assert not hasattr(pp, "pc_median_ungraded")


def test_teto_de_creditos_no_modulo():
    assert pcr.MAX_FIRECRAWL_CREDITS_PER_RUN == 100
    assert pp.MAX_PC_FIRECRAWL == pcr.MAX_FIRECRAWL_CREDITS_PER_RUN
    pcr.set_firecrawl_budget(100)
    with pytest.raises(ValueError, match="100"):
        pcr.set_firecrawl_budget(101)
    pcr.set_firecrawl_budget(0)


def test_fixtures_reais_nao_trazem_sinal_de_acabamento():
    # Lacuna documentada: nenhuma das 4 paginas reais e reverse/holo-rotulada; o titulo
    # real so rotula a edicao ("[1st Edition]"), nao o acabamento.
    for f in FIX.glob("*.html"):
        assert not re.search(r"(?i)reverse", _page(f.name)), f.name


def test_acabamento_reverse_nao_confirmavel():
    assert pcr.finish_status("reverseHolofoil") == pcr.FINISH_REVERSE_NAO_CONFIRMAVEL
    assert pcr.finish_status("normal") == "NAO_REVERSE"
    assert pcr.finish_status(None) == "NAO_REVERSE"
