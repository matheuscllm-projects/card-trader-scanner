"""B1c — itens 3-6 do lote de correções (itens 1-2 estão em test_b1b.py / test_validate_all.py)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
from test_b1b_delivery import _opp, _run_pp  # noqa: E402


def _unpriced(seller, qty=1, ed="Unlimited", fin="Holo"):
    return {"set": "mew", "set_name": "151", "card": "Mew ex Gold Metal", "number": "205",
            "ct_price_brl": 80.0, "seller": seller, "link": f"https://www.cardtrader.com/cards/{seller}",
            "reason": "sem_referencia_na_fonte", "detail": "x", "qty": qty, "edicao": ed, "acabamento": fin}


# ───────── 3: bloco "Sem preço" distinguível ─────────
def test_unpriced_block_has_edition_finish_seller_qty_price_and_explicit_no_tcg_link(tmp_path):
    x = tmp_path / "in.xlsx"
    sc.export_xlsx([_opp(0)], {}, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3,
                   unpriced=[_unpriced("vend_a", 2), _unpriced("vend_b", 1, fin="Reverse")])
    out = tmp_path / "r.xlsx"
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "-i", str(x), "-o", str(out)]):
        pp.main()
    md = out.with_suffix(".md").read_text(encoding="utf-8")
    blk = md.split("### Sem preço")[1]
    rows = [l for l in blk.splitlines() if l.startswith("| 1 |") or l.startswith("| 2 |")]
    assert len(rows) == 2 and rows[0] != rows[1]
    assert "vend_a" in rows[0] and "vend_b" in rows[1]
    assert "Unlimited" in rows[0] and "Reverse" in rows[1]
    assert "TCG: sem link" in rows[0] and "[oferta](" in rows[0]
    hdr = [l for l in blk.splitlines() if l.startswith("| # |")][0]
    for h in ("Vendedor", "Qtd", "CT R$"):
        assert h in hdr


def test_scanner_unpriced_rows_carry_qty_edition_finish(tmp_path, monkeypatch):
    from test_set_outcomes import _cards, _run
    from test_tcgcsv_fallback import _scanner_with
    listings = _cards(3, set_code="asc")
    scanner = _scanner_with({}, None, listings, tcgcsv_fallback=False, max_misses=0)
    scanner.language = "en"
    _run(scanner, listings, tmp_path, monkeypatch)
    assert scanner.unpriced_rows
    r = scanner.unpriced_rows[0]
    assert r["qty"] == listings[0].quantity and r["edicao"] and r["acabamento"]


def test_delivery_chat_does_not_claim_two_links_everywhere_without_caveat():
    t = (REPO_ROOT / "DELIVERY_CHAT.md").read_text(encoding="utf-8")
    assert "dois links em todos os blocos" not in t
    assert "TCG: sem link" in t


# ───────── 4: fuso / fonte / idade do lote ─────────
def test_ref_date_shows_timezone_and_old_column_is_labeled_buscado_em():
    s = pp._fmt_ref_date("dado de", "2026-11-23T20:05:58+00:00")
    assert s.startswith("dado de 2026-11-23") and "UTC" in s     # fuso explícito, nunca ambíguo
    assert pp._fmt_ref_date("", "2026-11-24T04:51:23-03:00").startswith("buscado em ")
    assert pp._fmt_ref_date(None, None) == "—"


def test_footer_states_source_of_each_reference_and_batch_age(tmp_path):
    md, _ = _run_pp(tmp_path, [_opp(0), _opp(1, source="pokemontcg", data="2026-11-24T05:00:00-03:00",
                                             label="dado de")],
                    stats={"scanned_at": "2026-11-24T04:51:58-03:00"})
    foot = [l for l in md.splitlines() if l.startswith("_Fontes das referências")]
    assert foot, md[-1500:]
    t = foot[0]
    assert "tcgcsv" in t and "lote diário" in t and "publicado há" in t and "pokemontcg" in t


def test_old_xlsx_with_only_ref_data_hora_uses_it_as_buscado_em(tmp_path):
    from openpyxl import load_workbook
    x = tmp_path / "in.xlsx"
    sc.export_xlsx([_opp(0)], {}, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    wb = load_workbook(x)
    ws = wb["Oportunidades"]
    for name in ("Data Ref.", "Rótulo Data Ref."):
        head = [c.value for c in ws[1]]
        ws.delete_cols(head.index(name) + 1)
    wb.save(x)
    out = tmp_path / "r.xlsx"
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "-i", str(x), "-o", str(out)]):
        pp.main()
    md = out.with_suffix(".md").read_text(encoding="utf-8")
    assert "buscado em 2026-11-24" in md


# ───────── 5: miss por carta dentro do run ─────────
def _resp(status=200, data=()):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"data": list(data), "totalCount": len(data)}
    return r


def _ptcg(tmp_path, side_effect):
    p = sc.PokemonTcgIoProvider.__new__(sc.PokemonTcgIoProvider)
    p.cache = sc.Cache(db_path=tmp_path / "c.db")
    p._ptcg_get = MagicMock(side_effect=side_effect)
    return p


def test_pokemontcg_miss_is_remembered_within_the_run(tmp_path):
    p = _ptcg(tmp_path, lambda *a, **k: _resp(200, []))
    assert p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare") is None
    assert p._ptcg_get.call_count > 0
    p._ptcg_get.reset_mock()
    for _ in range(5):
        assert p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare") is None
    assert p._ptcg_get.call_count == 0     # a mesma carta não refaz a busca


def test_infrastructure_failure_is_not_remembered_as_miss(tmp_path):
    import requests
    calls = {"n": 0}

    def get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout("t")
        return _resp(200, [])
    p = _ptcg(tmp_path, get)
    with pytest.raises(requests.Timeout):
        p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare")
    assert p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare") is None   # refaz: não guardou
    assert calls["n"] >= 2


# ───────── 6: baixas ─────────
def test_labels_are_precise(tmp_path):
    md, out = _run_pp(tmp_path, [_opp(0)], stats={"listings_fetched": 100, "listings_after_filters": 80,
                                                  "filtros_aplicados": "NM exato"})
    assert "bruto da API" in md and "todos os idiomas" in md
    from openpyxl import load_workbook
    cells = {r[0].value for r in load_workbook(out)["Summary"].iter_rows(min_row=2) if r[0].value}
    assert any("bruto da API" in str(c) for c in cells)


def test_scanner_filter_text_mentions_per_offer_dedup(tmp_path, monkeypatch):
    from test_set_outcomes import _cards, _run
    from test_tcgcsv_fallback import _scanner_with
    listings = _cards(2, set_code="asc")
    scanner = _scanner_with({("asc", l.collector_number): 50.0 for l in listings}, None, listings,
                            tcgcsv_fallback=False, max_misses=0)
    scanner.language = "en"
    _run(scanner, listings, tmp_path, monkeypatch)
    assert "dedup" in scanner.stats["filtros_aplicados"].lower()


def test_unpriced_offer_reason_is_not_confused_with_set_outcome():
    t = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")
    assert '"miss": "sem_cobertura"' not in t and "sem_referencia_na_fonte" in t


def test_holo_note_does_not_call_an_edition_key_a_finish():
    from test_b1b_more import _twm_provider
    prov = _twm_provider([(1, "Holofoil", 5.0), (1, "Normal", 2.0)])
    assert prov.market_price_usd("Greninja ex", "twm", "106/167", rarity="Promo") is None
    assert "inconclusiv" in prov.last_ref_reason
    assert "só tem o acabamento" not in prov.last_ref_reason


def test_valorization_column_says_what_it_measures():
    t = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")
    assert '"Valorização (0-100)"' not in t
    assert "Score heurístico" in t
