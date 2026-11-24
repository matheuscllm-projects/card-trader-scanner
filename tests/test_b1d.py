"""B1d — ajustes da revisão do B1c."""
from __future__ import annotations

import json
import re
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
from test_b1b import _fallback_scanner  # noqa: E402
from test_b1b_delivery import _opp  # noqa: E402
from test_set_outcomes import _run  # noqa: E402


# ───────── 1: preço da oferta nos dois blocos ─────────
def test_noref_block_shows_the_offer_price_from_scan_column(tmp_path):
    x = tmp_path / "in.xlsx"
    noref = {"set": "n1", "set_name": "Neo", "card": "Pichu", "number": "1", "rarity": "Rare",
             "edicao": "1st Edition", "acabamento": "Holo", "ct_price_brl": 123.45, "currency": "BRL",
             "qty": 2, "seller": "vend_x", "link": "https://www.cardtrader.com/cards/9",
             "tcg_url": "", "source": "pokemontcg+tcgcsv", "motivo": "m", "chaves": "k", "status": "VARIANTE_INCOMPATIVEL"}
    sc.export_xlsx([_opp(0)], {}, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3, noref=[noref],
                   unpriced=[{"set": "n1", "set_name": "Neo", "card": "Y", "number": "2", "ct_price_brl": 77.0,
                              "seller": "vend_y", "link": "https://www.cardtrader.com/cards/8",
                              "reason": "falha_operacional", "detail": "d", "qty": 1,
                              "edicao": "Unlimited", "acabamento": "Normal"}])
    out = tmp_path / "r.xlsx"
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "-i", str(x), "-o", str(out)]):
        pp.main()
    md = out.with_suffix(".md").read_text(encoding="utf-8")
    row_noref = [l for l in md.splitlines() if "vend_x" in l][0]
    row_unp = [l for l in md.splitlines() if "vend_y" in l][0]
    assert "123.45" in row_noref and "77.00" in row_unp


# ───────── 2: recovery nunca remove; varredura de comandos ─────────
def test_recover_min_net_only_marks_never_removes():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import recover_from_checkpoint as rc
    from test_b1b_delivery import _opp as mk
    rows = [mk(0), mk(1)]
    rows[0].real_net_margin_pct, rows[1].real_net_margin_pct = 0.01, 0.9
    out = rc.mark_below_min_net(rows, 0.20)
    assert out == rows and len(out) == 2


def _read(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


def test_no_scanner_command_outside_the_canonical_form():
    """Nenhum comando do scanner (ps1/md/workflows) traz --validate-top ou --min-net-margin.
    --min-net-margin é legítimo só no postprocess (arquivo/comando que o chama)."""
    files = (list((REPO_ROOT / "scripts").glob("*.ps1")) + list((REPO_ROOT / ".claude" / "commands").glob("*.md"))
             + list((REPO_ROOT / ".github" / "workflows").glob("*")))
    bad = []
    for f in files:
        infence = False
        for n, line in enumerate(_read(f).splitlines(), 1):
            s = line.strip()
            if f.suffix == ".md":
                if s.startswith("```"):
                    infence = not infence
                    continue
                if not infence:
                    continue    # prosa do .md: só os comandos (blocos de código) contam
            if "--validate-top" not in s and "--min-net-margin" not in s:
                continue
            if s.startswith("#") or re.search(r"\bsem\b|\bnão\b|\bnao\b", s, re.I):
                continue    # comentário / prosa que explica a ausência
            if "--min-net-margin" in s and "--validate-top" not in s and "postprocess" in _read(f) \
                    and "cardtrader_scanner" not in _read(f):
                continue    # arquivo só do postprocess
            bad.append(f"{f.name}:{n}: {s}")
    assert not bad, "\n".join(bad)


# ───────── 3: D1 (skip-list, caso misto, grupo ausente) e D2 (run completo) ─────────
def test_d1_fetch_failure_leaves_skip_list_empty(tmp_path, monkeypatch):
    scanner, listings = _fallback_scanner(tmp_path, [(1, "Unlimited Holofoil", 1.0)])
    scanner.tcgcsv.prefill_set = MagicMock(return_value=False)
    scanner.tcgcsv.last_prefill_status = "fetch_failed"
    _, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert skip == {} and done[0]["status"] == "operational_failure"


def test_d1_mixed_case_two_priced_one_pending_operational(tmp_path, monkeypatch):
    rows = [(k, "Unlimited Holofoil", 10.0 * k) for k in (1, 2, 3)]
    scanner, listings = _fallback_scanner(tmp_path, rows, n=3)
    real = scanner.tcgcsv.market_price_usd
    n = {"i": 0}

    def flaky(*a, **k):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("boom")
        return real(*a, **k)
    scanner.tcgcsv.market_price_usd = flaky
    opps, done, skip = _run(scanner, listings, tmp_path, monkeypatch)
    assert len(opps) == 2 and scanner.noref_rows == []
    assert [r["reason"] for r in scanner.unpriced_rows] == ["falha_operacional"]
    assert done[0]["status"] == "operational_failure" and skip == {}
    assert len(opps) + len(scanner.unpriced_rows) + len(scanner.noref_rows) == 3


def test_d1_tcgcsv_without_the_group_is_a_valid_noref_and_set_complete(tmp_path, monkeypatch):
    scanner, listings = _fallback_scanner(tmp_path, [(1, "Unlimited Holofoil", 1.0)])
    scanner.tcgcsv.prefill_set = MagicMock(return_value=False)
    scanner.tcgcsv.last_prefill_status = "no_group"
    opps, done, _ = _run(scanner, listings, tmp_path, monkeypatch)
    assert opps == [] and len(scanner.noref_rows) == 1 and scanner.unpriced_rows == []
    assert done[0]["status"] == "complete"


def test_d2_main_never_reduces_the_list_after_validation(tmp_path, monkeypatch):
    """Run completo (main): qualquer etapa depois da validação que reduza a lista falha aqui.
    Soma dos destinos = linhas do XLSX = o que o scan devolveu."""
    from test_lote3c import _fake_main_env, _opp as mk
    rows = [mk(i) for i in range(1, 7)]

    def scan_fn(s):
        s.stats["listings_after_filters"] = len(rows)
        return list(rows)

    holder, out = _fake_main_env(monkeypatch, tmp_path, scan_fn, argv_extra=("--min-net-margin", "0.20"))

    orig_factory = sc.Scanner

    def wrapped(**kw):
        s = orig_factory(**kw)

        def fake_validate(opps, *a, **k):
            for i, o in enumerate(opps):
                o.validation_status = "VALIDATED_REAL" if i % 2 == 0 else "STALE"
                o.real_net_margin_pct = 0.01 if i % 2 == 0 else None   # validadas com líquida real BAIXA
        s.validate_per_blueprint = fake_validate
        return s
    monkeypatch.setattr(sc, "Scanner", wrapped)
    try:
        sc.main()
    except SystemExit as e:
        assert e.code in (0, None)
    import pandas as pd
    df = pd.read_excel(out, sheet_name="Oportunidades")
    assert len(df) == len(rows) == 6


# ───────── 4: baixas ─────────
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


def test_4xx_other_than_429_is_a_failure_not_a_miss_and_is_not_memoized(tmp_path):
    import requests
    p = _ptcg(tmp_path, lambda *a, **k: _resp(403))
    with pytest.raises(requests.RequestException) as ei:
        p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare")
    assert "403" in str(ei.value)
    n = p._ptcg_get.call_count
    with pytest.raises(requests.RequestException):
        p.market_price_usd("Mew ex", "mew", "205", rarity="Ultra Rare")
    assert p._ptcg_get.call_count > n          # não ficou guardado como "não encontrada"


def test_search_memo_card_dict_is_not_mutated(tmp_path):
    card = {"id": "x-1", "name": "Mew ex", "number": "205", "rarity": "Rare Holo",
            "set": {"id": "mew", "releaseDate": "2023/09/22", "printedTotal": 165},
            "tcgplayer": {"url": "u", "prices": {"holofoil": {"market": 5.0, "low": 4.0, "mid": 4.5}}}}
    p = _ptcg(tmp_path, lambda *a, **k: _resp(200, [card]))
    p.market_price_usd("Mew ex", "mew", "205", rarity="Rare Holo")
    assert "_variant_used" not in card
    assert "_variant_used" not in p.__dict__["_search_memo"][("Mew ex", "mew", "205")]


def test_stale_comments_and_unused_variable_are_gone():
    t = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")
    assert "só o corte --min-net-margin (explícito) remove" not in t
    assert "before = len(opps)" not in t
    assert "(status inválido, --min-net-margin) só culam" not in t
