"""Sinal de demanda por vendas reais (spec D5 / A4) em pricecharting_ref.

Offline. Fixture `pc_sold_listings.html` = HTML SINTÉTICO montado a partir da
estrutura que parse_sold_listings espera (não é captura real de página).
Datas fixas da fixture: 2026-04-07, 02-27, 02-23, 02-12, 02-11 (preços
51.76, 51.78, 42.00, 150.26, 40.00).
"""
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pricecharting_ref as pcr

FIXTURE = Path(__file__).parent / "fixtures" / "pc_sold_listings.html"
SEARCH = ('<a href="/game/pokemon-neo-genesis/lugia-1st-edition-9">1st</a>'
          '<a href="/game/pokemon-neo-genesis/lugia-9">unl</a>')


def _html():
    return FIXTURE.read_text(encoding="utf-8")


def _sales():
    return pcr.parse_sold_listings(_html())


def test_demand_counts_30_90_sum_last_and_truncated():
    # janela 90d = desde 2026-01-20: pega as 5; 30d desde 03-21: só 04-07
    d = pcr.demand_signal(_sales(), today=dt.date(2026, 4, 20))
    assert (d["pc_vendas_30d"], d["pc_vendas_90d"]) == (1, 5)
    assert d["pc_valor_90d_usd"] == round(51.76 + 51.78 + 42.0 + 150.26 + 40.0, 2)
    assert d["pc_ultima_venda"] == "2026-04-07"
    # venda mais antiga (02-11) >= início da janela (01-20): lista pode estar cortada
    assert d["pc_truncado"] is True
    assert d["pc_status"] == "OK"


def test_demand_not_truncated_when_list_reaches_before_window():
    d = pcr.demand_signal(_sales(), today=dt.date(2026, 6, 30))  # janela 90d desde 04-01
    assert (d["pc_vendas_30d"], d["pc_vendas_90d"]) == (0, 1)
    assert d["pc_truncado"] is False
    assert d["pc_ultima_venda"] == "2026-04-07"


def test_demand_no_sales_is_explicit_not_zero():
    d = pcr.demand_signal([], today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "ZERO_VENDAS_LISTADAS"
    assert d["pc_vendas_30d"] is None and d["pc_vendas_90d"] is None
    assert d["pc_ultima_venda"] is None


def test_structure_not_recognized_when_div_missing():
    assert pcr.demand_from_page("<html>nada</html>", "u",
                                today=dt.date(2026, 4, 20))["pc_status"] == "ESTRUTURA_NAO_RECONHECIDA"


def test_empty_table_is_zero_sales_listed():
    page = '<div class="completed-auctions-used"><table></table></div>'
    d = pcr.demand_from_page(page, "u", today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "ZERO_VENDAS_LISTADAS"


def test_edition_slug_rules():
    assert pcr.edition_slug_ok("/game/x/lugia-1st-edition-9", "1st")
    assert not pcr.edition_slug_ok("/game/x/lugia-9", "1st")
    assert pcr.edition_slug_ok("/game/x/lugia-9", "unlimited")
    assert not pcr.edition_slug_ok("/game/x/lugia-1st-edition-9", "unlimited")
    assert pcr.edition_slug_ok("/game/x/lugia-1st-edition-9", None)  # legado: sem filtro


def _patch(monkeypatch):
    def fake(url, cache_dir=None):
        return SEARCH if "search-products" in url else _html()
    monkeypatch.setattr(pcr, "fetch_page", fake)


def test_demand_1st_edition_picks_1st_page(monkeypatch):
    _patch(monkeypatch)
    d = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="1st",
                              today=dt.date(2026, 4, 20))
    assert d["pc_url"].endswith("/lugia-1st-edition-9") and d["pc_status"] == "OK"
    assert d["pc_vendas_90d"] == 5


def test_demand_unlimited_picks_unlimited_page(monkeypatch):
    _patch(monkeypatch)
    d = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="unlimited",
                              today=dt.date(2026, 4, 20))
    assert d["pc_url"].endswith("/lugia-9")


def test_demand_no_compatible_edition_page(monkeypatch):
    only_unl = '<a href="/game/pokemon-neo-genesis/lugia-9">unl</a>'
    monkeypatch.setattr(pcr, "fetch_page",
                        lambda url, cache_dir=None: only_unl if "search-products" in url else _html())
    d = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="1st",
                              today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "SEM_PAGINA_COMPATIVEL" and d["pc_url"] is None
    assert d["pc_motivo"] and d["pc_vendas_90d"] is None


def test_demand_403_without_budget(monkeypatch):
    import urllib.error

    def boom(url, cache_dir=None):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
    monkeypatch.setattr(pcr, "fetch_page", boom)
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition="1st",
                              today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "INDISPONIVEL_403" and d["pc_vendas_90d"] is None


def test_demand_budget_exhausted(monkeypatch):
    def boom(url, cache_dir=None):
        raise RuntimeError("PriceCharting 403 e Firecrawl falhou: sem orçamento")
    monkeypatch.setattr(pcr, "fetch_page", boom)
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "INDISPONIVEL_ORCAMENTO"


# ─── cache por run ───────────────────────────────────────────────────────────

def _fake_urlopen(counter):
    class R:
        headers = {}

        def read(self):
            counter.append(1)
            return b"<html>v</html>"

        def __enter__(self): return self
        def __exit__(self, *a): return False
    return lambda req, timeout=30: R()


def test_cache_is_per_run_and_stamped(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _fake_urlopen(calls))
    monkeypatch.setattr(pcr, "REQUEST_GAP_SECONDS", 0)
    pcr.new_run()
    u = "https://www.pricecharting.com/game/x/y-1"
    pcr.fetch_page(u, cache_dir=str(tmp_path))
    pcr.fetch_page(u, cache_dir=str(tmp_path))
    assert len(calls) == 1                      # 2ª leitura no mesmo run: cache
    assert pcr.page_fetched_at(u, cache_dir=str(tmp_path))  # carimbo ISO
    pcr.new_run()
    pcr.fetch_page(u, cache_dir=str(tmp_path))
    assert len(calls) == 2                      # novo run: refaz a busca


def test_no_cross_run_disk_reuse(monkeypatch, tmp_path):
    """Arquivo velho no cache_dir (de outro scan) nunca é servido."""
    calls = []
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _fake_urlopen(calls))
    monkeypatch.setattr(pcr, "REQUEST_GAP_SECONDS", 0)
    u = "https://www.pricecharting.com/game/x/old-2"
    slug = pcr.re.sub(r"[^a-z0-9]+", "_", u.lower())[-120:]
    (tmp_path / (slug + ".html")).write_text("<html>VELHO</html>", encoding="utf-8")
    pcr.new_run()
    assert pcr.fetch_page(u, cache_dir=str(tmp_path)) == "<html>v</html>"
    assert len(calls) == 1
