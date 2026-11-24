"""B1b — entrega: edicao/acabamento/fonte/data, top-md honesto, origem dos numeros, liquidas PARCIAIS."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_set_outcomes import _cards  # noqa: E402


def _opp(i, fe=False, rev=False, ed=cv.ED_UNL, fin=cv.FIN_NORMAL, source="tcgcsv", data="2026-11-23T20:05:58+00:00",
         label="dado de", ct=20.0, ref=100.0, seller="s1"):
    l = dataclasses.replace(_cards(i + 1, set_code="n1")[i], first_edition=fe, foil=rev, seller_username=seller)
    o = sc.Opportunity(listing=l, tcg_market_usd=ref / 5, tcg_market_brl=ref, ct_price_brl=ct,
                       margin_pct=(ref - ct) / ref, margin_brl=ref - ct, estimated_shipping_brl=0.5,
                       net_margin_pct=0.7)
    o.edition, o.finish, o.ref_compatible = ed, fin, True
    o.price_source, o.price_fetched_at = source, "2026-11-24T05:00:00-03:00"
    o.ref_data_at, o.ref_data_label = data, label
    o.tcg_url = f"https://www.tcgplayer.com/product/{i + 1}"
    return o


def _run_pp(tmp_path, opps, stats=None, extra_args=()):
    x = tmp_path / "in.xlsx"
    sc.export_xlsx(opps, stats or {}, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    out = tmp_path / "rel.xlsx"
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "-i", str(x), "-o", str(out), *extra_args]):
        pp.main()
    return out.with_suffix(".md").read_text(encoding="utf-8"), out


def test_table_shows_edition_finish_source_and_reference_date(tmp_path):
    opps = [_opp(0, fe=True, ed=cv.ED_1ST, fin=cv.FIN_HOLO),
            _opp(1, fe=False, ed=cv.ED_UNL, fin=cv.FIN_HOLO),
            _opp(2, rev=True, ed=cv.ED_NONE, fin=cv.FIN_REVERSE, source="pokemontcg",
                 data="2026-11-24T05:00:00-03:00", label="buscado em")]
    md, _ = _run_pp(tmp_path, opps)
    for h in ("| Edição |", "| Acabamento |", "| Fonte ref. |", "| Data ref. |"):
        assert h in md, h
    assert "1st Edition" in md and "Unlimited" in md and "Sem divisão de edição" in md
    assert "Reverse" in md and "Holo" in md
    assert "dado de 2026-11-23" in md and "buscado em 2026-11-24" in md
    assert "tcgcsv" in md and "pokemontcg" in md
    assert md.count("[oferta](") >= 3 and md.count("[TCG](") >= 3     # contrato dos 2 links intacto


def test_top_md_limit_is_declared_and_default_shows_all(tmp_path):
    opps = [_opp(i, seller=f"s{i}") for i in range(6)]
    md_all, _ = _run_pp(tmp_path, opps)
    assert "mostrando" not in md_all and md_all.count("[oferta](") == 6
    md, _ = _run_pp(tmp_path, opps, extra_args=("--top-md", "2"))
    assert "mostrando 2 de 6" in md
    assert "4 linha(s)" in md and "--top-md" in md and "aba" in md.lower()


def test_scan_md_and_menu_test_do_not_cap_the_delivery():
    t = (REPO_ROOT / ".claude" / "commands" / "scan.md").read_text(encoding="utf-8")
    assert "--top-md 50" not in t
    assert "--top-md 50" not in (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").split("Arquitetura")[0]


def test_delivery_states_where_the_numbers_come_from(tmp_path):
    stats = {"listings_fetched": 100, "listings_after_filters": 80,
             "filtros_aplicados": "NM exato; idioma EN; não graduada; piso US$ 10",
             "skipped_non_chase": 7, "opportunities_only_descartadas": 3}
    md, out = _run_pp(tmp_path, [_opp(0)], stats=stats)
    assert "Ofertas buscadas: 100" in md and "após filtros: 80" in md
    assert "NM exato; idioma EN; não graduada; piso US$ 10" in md
    assert "--chase-only descartou 7" in md and "--opportunities-only descartou 3" in md
    from openpyxl import load_workbook
    ws = load_workbook(out)["Summary"]
    cells = {r[0].value: r[1].value for r in ws.iter_rows(min_row=2) if r[0].value}
    assert cells.get("Ofertas buscadas (CardTrader)") == 100
    assert cells.get("Ofertas após filtros") == 80
    assert "Total listings escaneados" not in cells


def test_scanner_net_columns_are_marked_partial_with_missing_costs(tmp_path):
    from openpyxl import load_workbook
    x = tmp_path / "x.xlsx"
    sc.export_xlsx([_opp(0)], {}, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    ws = load_workbook(x)["Oportunidades"]
    head = [c.value for c in ws[1]]
    row = [c.value for c in ws[2]]
    assert row[head.index("Líquida")] == "PARCIAL"
    assert "iof_rate" in row[head.index("Custos Não Informados")]


def test_scanner_records_the_filters_and_discards(tmp_path, monkeypatch):
    from test_set_outcomes import _run
    from test_tcgcsv_fallback import _scanner_with
    listings = _cards(3, set_code="asc")
    scanner = _scanner_with({("asc", l.collector_number): 50.0 for l in listings}, None, listings,
                            tcgcsv_fallback=False, max_misses=0)
    scanner.language = "en"
    _run(scanner, listings, tmp_path, monkeypatch)
    f = scanner.stats["filtros_aplicados"]
    assert "NM" in f and "EN" in f.upper() and "graduad" in f and "piso" in f and "10" in f
