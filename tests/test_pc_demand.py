"""Sinal de demanda por vendas reais (spec D5 / A4) em pricecharting_ref.

Offline. Fixture `pc_sold_listings.html` = HTML SINTÉTICO montado a partir da
estrutura que parse_sold_listings espera (não é captura real de página).
Fixtures REAIS (Firecrawl, 2026-11-24) em fixtures/pricecharting_real/ (ver
PROVENIENCIA.jsonl): lugia_unlimited, lugia_1st_edition, search_lugia_neo_genesis,
cyndaquil_1st_edition_poucas_vendas. Os testes que as usam rodam sem rede.
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
    # 5 linhas < teto de 30 por fonte: a lista inteira está na página (não cortada)
    assert d["pc_truncado"] is False
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
    assert pcr.demand_from_page("<html>nada</html>", "1st", "u",
                                today=dt.date(2026, 4, 20))["pc_status"] == "ESTRUTURA_NAO_RECONHECIDA"


def test_empty_table_is_zero_sales_listed():
    page = '<div class="completed-auctions-used"><table></table></div>'
    d = pcr.demand_from_page(page, "1st", "u", today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "ZERO_VENDAS_LISTADAS"


def test_edition_slug_rules():
    assert pcr.edition_slug_ok("/game/x/lugia-1st-edition-9", "1st")
    assert not pcr.edition_slug_ok("/game/x/lugia-9", "1st")
    assert pcr.edition_slug_ok("/game/x/lugia-9", "unl")
    assert not pcr.edition_slug_ok("/game/x/lugia-1st-edition-9", "unl")
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
    d = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="unl",
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


def test_demand_generic_runtime_error_is_not_budget(monkeypatch):
    def boom(url, cache_dir=None):
        raise RuntimeError("PriceCharting 403 e Firecrawl falhou: sem orçamento")
    monkeypatch.setattr(pcr, "fetch_page", boom)
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition="1st",
                              today=dt.date(2026, 4, 20))
    assert d["pc_status"] == "INDISPONIVEL_REDE"   # RuntimeError genérico != orçamento


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


# ═══ Revisão independente 2026-11-24 — fixtures REAIS + correções 1-9 ═════════
import urllib.error  # noqa: E402

import pytest  # noqa: E402

REAL = Path(__file__).parent / "fixtures" / "pricecharting_real"
CAPTURE_DAY = dt.date(2026, 11, 24)     # dia da captura das fixtures reais
UNL_URL = "https://www.pricecharting.com/game/pokemon-neo-genesis/lugia-9"
FIRST_URL = "https://www.pricecharting.com/game/pokemon-neo-genesis/lugia-1st-edition-9"


def _real(name):
    return (REAL / name).read_text(encoding="utf-8")


def _row(rid, date, price, title="Lugia #9 Near Mint English"):
    p = f'<span class="js-price">${price}</span>' if price else ""
    return (f'<tr id="{rid}"><td class="date">{date}</td><td class="title">'
            f'<a>{title}</a> [eBay]</td><td class="numeric">{p}</td></tr>')


def _page(*rows):
    return ('<div class="completed-auctions-used"><table><tbody>'
            + "".join(rows) + "</tbody></table></div>")


# ── 1. edição obrigatória e validada ─────────────────────────────────────────
@pytest.mark.parametrize("bad", ["1st Edition", "first", "", "unlimited", "1ST", None])
def test_new_api_rejects_invalid_edition(bad):
    with pytest.raises(ValueError):
        pcr.demand_from_page(_page(), bad, url="u", today=CAPTURE_DAY)
    with pytest.raises(ValueError):
        pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition=bad)


def test_new_api_edition_is_required():
    with pytest.raises(TypeError):
        pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)")
    with pytest.raises(TypeError):
        pcr.demand_from_page(_page())


@pytest.mark.parametrize("bad", ["1st Edition", "first", "", "unlimited"])
def test_old_api_validates_edition_when_given(bad, monkeypatch):
    monkeypatch.setattr(pcr, "fetch_page", lambda u, cache_dir=None: SEARCH)
    with pytest.raises(ValueError):
        pcr.resolve_pc_ref("Lugia", "9", "Neo Genesis (n1)", edition=bad)
    with pytest.raises(ValueError):
        pcr.resolve_ebay_ref("Lugia", "9", "Neo Genesis (n1)", edition=bad)


def test_demand_from_page_rejects_page_of_other_edition():
    d = pcr.demand_from_page(_real("lugia_unlimited.html"), "1st", url=UNL_URL, today=CAPTURE_DAY)
    assert d["pc_status"] == "EDICAO_DIVERGENTE" and d["pc_vendas_90d"] is None
    d = pcr.demand_from_page(_real("lugia_1st_edition.html"), "unl", url=None, today=CAPTURE_DAY)
    assert d["pc_status"] == "EDICAO_DIVERGENTE"      # título "[1st Edition]" da página


# ── 2. regra de slug única ───────────────────────────────────────────────────
def test_slug_rule_token_boundaries():
    assert pcr.edition_slug_ok("/game/x/1st-edition-lugia-9", "1st")       # início do slug
    assert not pcr.edition_slug_ok("/game/x/1st-edition-lugia-9", "unl")
    assert not pcr.edition_slug_ok("/game/x/pre1st-edition-9", "1st")      # dentro de outro nome
    assert pcr.edition_slug_ok("/game/x/pre1st-edition-9", "unl")
    assert not pcr.edition_slug_ok("/game/x/lugia-1st-editions-9", "1st")


def test_real_search_page_picks_each_edition(monkeypatch):
    search, unl, first = (_real("search_lugia_neo_genesis.html"),
                          _real("lugia_unlimited.html"), _real("lugia_1st_edition.html"))
    monkeypatch.setattr(pcr, "fetch_page", lambda url, cache_dir=None:
                        search if "search-products" in url else (first if "1st-edition" in url else unl))
    a = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="1st", today=CAPTURE_DAY)
    b = pcr.resolve_pc_demand("Lugia", "9/111", "Neo Genesis (n1)", edition="unl", today=CAPTURE_DAY)
    assert a["pc_url"] == FIRST_URL and b["pc_url"] == UNL_URL
    assert a["pc_status"] == b["pc_status"] == "OK"


# ── 3. lotes e graduadas excluídos, com contagem ─────────────────────────────
def test_lots_and_graded_excluded_with_counts():
    page = _page(_row("ebay-1", "2026-11-20", "10.00", "Lugia Neo Genesis NM"),
                 _row("ebay-2", "2026-11-20", "500.00", "Lot of 20 cards Neo Genesis"),
                 _row("ebay-3", "2026-11-19", "900.00", "PSA 10 Lugia Neo Genesis"),
                 _row("tcgplayer-A+b", "2026-11-18", "700.00", "CGC 7.5 Lugia"),
                 _row("ebay-4", "2026-11-17", "30.00", "Lugia Neo Genesis LP"))
    d = pcr.demand_from_page(page, "unl", url="u", today=CAPTURE_DAY)
    assert (d["pc_vendas_90d"], d["pc_valor_90d_usd"]) == (2, 40.0)
    assert d["pc_excluidas"] == {"lote": 1, "graduada": 2, "idioma": 0}
    assert d["pc_linhas_lidas"] == 5


def test_real_unlimited_exclusions_and_numbers():
    d = pcr.demand_from_page(_real("lugia_unlimited.html"), "unl", url=UNL_URL, today=CAPTURE_DAY)
    # 54 linhas (30 eBay + 24 TCGplayer); 7 graduadas (1 eBay "Graded 5" + 6 TCGplayer PSA/CGC)
    assert d["pc_linhas_lidas"] == 54
    assert d["pc_excluidas"]["graduada"] == 7 and d["pc_excluidas"]["lote"] == 0
    assert sum(d["pc_ignoradas"].values()) == 0
    assert d["pc_vendas_90d"] == 54 - 7 - _older_than_90(d)


def _older_than_90(d):   # a conta fecha: lidas = ignoradas + excluídas + 90d + mais antigas
    return d["pc_linhas_lidas"] - sum(d["pc_ignoradas"].values()) \
        - sum(d["pc_excluidas"].values()) - d["pc_vendas_90d"]


# ── 4. linha sem preço não rouba o preço da vizinha ──────────────────────────
def test_row_without_price_is_not_paired_with_next_row():
    page = _page(_row("ebay-1", "2026-11-20", None), _row("ebay-2", "2026-11-19", "42.00"))
    sales = pcr.parse_sold_listings(page)
    assert sales == [{"date": "2026-11-19", "source": "ebay", "price": 42.0,
                      "title": "Lugia #9 Near Mint English"}]
    d = pcr.demand_from_page(page, "unl", url="u", today=CAPTURE_DAY)
    assert d["pc_ignoradas"]["sem_preco"] == 1 and d["pc_vendas_90d"] == 1
    assert d["pc_valor_90d_usd"] == 42.0


def test_real_tcgplayer_ids_are_parsed():
    # ids reais da TCGplayer têm letras/+ ("tcgplayer-nvAA+SAKFVCy"): o regex antigo as perdia
    s = pcr.parse_sold_listings(_real("lugia_unlimited.html"))
    assert sum(1 for x in s if x["source"] == "tcgplayer") == 24 and len(s) == 54


# ── 5. datas ─────────────────────────────────────────────────────────────────
def test_bad_and_future_dates_are_ignored_and_counted():
    page = _page(_row("ebay-1", "2026-13-45", "10.00"),
                 _row("ebay-2", "2026-12-30", "20.00"),            # futura
                 _row("ebay-3", "2026-11-25", "30.00"),            # hoje+1: margem de fuso, entra
                 _row("ebay-4", "2026-11-26", "40.00"),            # hoje+2: futura
                 _row("ebay-5", "2026-11-20", "50.00"))
    d = pcr.demand_from_page(page, "unl", url="u", today=CAPTURE_DAY)
    assert d["pc_ignoradas"] == {"sem_preco": 0, "data_invalida": 1, "data_futura": 2}
    assert d["pc_vendas_90d"] == 2 and d["pc_valor_90d_usd"] == 80.0
    assert d["pc_ultima_venda"] == "2026-11-25"


def test_window_compares_dates_not_strings():
    # "2026-9-30" não é ISO: ignorada (em ordem de string venceria "2026-11-..")
    page = _page(_row("ebay-1", "2026-9-30", "10.00"), _row("ebay-2", "2026-11-20", "20.00"))
    d = pcr.demand_from_page(page, "unl", url="u", today=CAPTURE_DAY)
    assert d["pc_vendas_90d"] == 1 and d["pc_ignoradas"]["data_invalida"] == 1


# ── 6. pc_truncado baseado no teto real de 30 linhas por fonte ───────────────
def test_cap_is_30_rows_per_source_on_real_pages():
    for name, ebay_n, tcg_n in (("lugia_unlimited.html", 30, 24), ("lugia_1st_edition.html", 30, 0),
                                ("cyndaquil_1st_edition_poucas_vendas.html", 30, 30)):
        s = pcr.parse_sold_listings(_real(name))
        assert (sum(x["source"] == "ebay" for x in s),
                sum(x["source"] == "tcgplayer" for x in s)) == (ebay_n, tcg_n)
    assert pcr.PC_ROWS_CAP_PER_SOURCE == 30


def test_truncado_true_when_a_source_hits_cap_inside_window():
    for name, ed in (("lugia_unlimited.html", "unl"), ("lugia_1st_edition.html", "1st")):
        d = pcr.demand_from_page(_real(name), ed, url="u", today=CAPTURE_DAY)
        assert d["pc_truncado"] is True


def test_truncado_false_when_all_sources_below_cap():
    assert pcr.demand_from_page(_page(_row("ebay-1", "2026-11-20", "5.00")), "unl",
                                today=CAPTURE_DAY)["pc_truncado"] is False


def test_truncado_unknown_when_cap_assumption_breaks():
    rows = [_row(f"ebay-{i}", "2026-11-20", "5.00") for i in range(31)]
    assert pcr.demand_from_page(_page(*rows), "unl", today=CAPTURE_DAY)["pc_truncado"] == "desconhecido"


# ── 7. falha registrada no run; status por causa ─────────────────────────────
def _deny_urlopen(counter):
    def f(req, timeout=30):
        counter.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    return f


def _fresh(monkeypatch, budget):
    monkeypatch.setattr(pcr, "REQUEST_GAP_SECONDS", 0)
    monkeypatch.setattr(pcr, "FIRECRAWL_RETRY_WAIT_S", 0)
    pcr.new_run()
    pcr.set_firecrawl_budget(budget)


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_failed_fetch_is_remembered_within_run(monkeypatch):
    calls, fc = [], []
    _fresh(monkeypatch, 2)
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _deny_urlopen(calls))

    def scrape(u):
        fc.append(u)
        raise OSError("x")
    monkeypatch.setattr(pcr, "_firecrawl_scrape", scrape)
    u = "https://www.pricecharting.com/search-products?q=a"
    for _ in range(2):
        with pytest.raises(RuntimeError):
            pcr.fetch_page(u)
    assert len(calls) == 1 and len(fc) == 2 and pcr.firecrawl_used() == 2   # 2ª leitura: zero crédito
    pcr.new_run()
    assert pcr.page_fetched_at(u) is None


def test_route_failure_budget_exhausted_and_network_have_own_status(monkeypatch):
    _fresh(monkeypatch, 1)
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _deny_urlopen([]))
    monkeypatch.setattr(pcr, "_firecrawl_scrape", _raise(OSError("fc down")))
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition="1st", today=CAPTURE_DAY)
    assert d["pc_status"] == "INDISPONIVEL_FIRECRAWL"            # falha da rota (gastou o único crédito)
    d = pcr.resolve_pc_demand("Lugia", "10", "Neo Genesis (n1)", edition="1st", today=CAPTURE_DAY)
    assert d["pc_status"] == "INDISPONIVEL_ORCAMENTO"            # teto acabou
    _fresh(monkeypatch, 0)
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition="1st", today=CAPTURE_DAY)
    assert d["pc_status"] == "INDISPONIVEL_403"                  # rota paga desligada
    pcr.new_run()
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _raise(urllib.error.URLError("dns")))
    d = pcr.resolve_pc_demand("Lugia", "9", "Neo Genesis (n1)", edition="1st", today=CAPTURE_DAY)
    assert d["pc_status"] == "INDISPONIVEL_REDE"


# ── 8. créditos do run no resultado e teto respeitado ────────────────────────
def test_credits_spent_reported_and_cap_respected(monkeypatch):
    _fresh(monkeypatch, 2)
    monkeypatch.setattr(pcr.urllib.request, "urlopen", _deny_urlopen([]))
    monkeypatch.setattr(pcr, "_firecrawl_scrape", lambda u: "<html>" + u + "</html>")
    pcr.fetch_page("https://www.pricecharting.com/game/x/y-1")
    pcr.fetch_page("https://www.pricecharting.com/game/x/y-2")
    with pytest.raises(RuntimeError):
        pcr.fetch_page("https://www.pricecharting.com/game/x/y-3")
    assert pcr.firecrawl_used() == 2
    s = pcr.run_summary()
    assert s["firecrawl_creditos_gastos"] == 2 and s["firecrawl_teto"] == 2
    d = pcr.demand_from_page(_page(_row("ebay-1", "2026-11-20", "5.00")), "unl", today=CAPTURE_DAY)
    assert d["pc_creditos_run"] == 2


# ── 9. nada de "cache 24h" no módulo ─────────────────────────────────────────
def test_module_does_not_mention_24h_cache():
    assert "24h" not in Path(pcr.__file__).read_text(encoding="utf-8")


# ── volume (texto real da página) ────────────────────────────────────────────
def test_volume_label_real_text():
    assert pcr.parse_volume_label(_real("lugia_unlimited.html")) == "1 sale per week"
    assert pcr.parse_volume_label(_real("lugia_1st_edition.html")) == "1 sale per day"
    assert pcr.parse_volume_label("<html></html>") is None
