"""B1g — chave existente sem preço, acabamento inferido, idade desconhecida, 2ª fonte, propriedade."""
from __future__ import annotations

import itertools
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
import ct_variants as cv  # noqa: E402
from test_b1b_delivery import _opp, _run_pp  # noqa: E402
from test_b1e import EXP, _build, _real_provider  # noqa: E402

_FX = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1g_unpriced_normal.json").read_text(encoding="utf-8"))
_CASES = [(code, r) for code, rows in _FX.items() for r in rows]


# ───────── A: a existência da impressão vem da CHAVE, com ou sem preço ─────────
@pytest.mark.parametrize("code,row", _CASES, ids=[f"{c}-{r['number']}" for c, r in _CASES])
@pytest.mark.parametrize("ct_rarity", ["Rare", "Common"])
def test_normal_key_without_price_still_means_the_card_has_a_normal_print(code, row, ct_rarity):
    prov = _real_provider(code, row["gid"], row["group"], "2005-01-01T00:00:00", [row])
    num = row["number"]
    assert prov.market_price_usd(row["name"], code, num, rarity=ct_rarity) is None
    assert prov.last_ref_status == cv.INCOMPATIVEL
    assert "raridades em conflito" in prov.last_ref_reason and "normal" in prov.last_ref_reason


def test_declared_finish_whose_key_exists_without_price_is_found_without_price_not_another_key():
    prices = {"normal": {"market": None}, "reverseHolofoil": {"market": 1.0}}
    om = cv.match_offer(prices, False, False, "Common", ref_rarity="Common")
    assert om.match.status == cv.SEM_PRECO and om.match.key is None
    assert "sem preço" in om.match.reason and "normal" in om.match.reason


# ───────── B: casos que hoje presumem ─────────
@pytest.mark.parametrize("ct", ["Promo", "", None])
def test_inconclusive_cardtrader_rarity_with_both_prints_is_incompatible(ct):
    prices = {"normal": {"market": 1.0}, "holofoil": {"market": 9.0}}
    om = cv.match_offer(prices, False, False, ct, ref_rarity="Holo Rare", set_released="2005-01-01")
    assert om.match.status == cv.INCOMPATIVEL
    assert "desconhecido" in om.match.reason and om.inferred is None


def test_conclusive_non_holo_vs_holo_only_product_is_ok_but_marked_inferred():
    prices = {"holofoil": {"market": 9.0}}
    om = cv.match_offer(prices, False, False, "Common", ref_rarity="Holo Rare", set_released="2005-01-01")
    assert om.match.status == cv.OK and om.match.key == "holofoil"
    assert om.inferred and "Common" in om.inferred and "Holo Rare" in om.inferred


# ───────── C: acabamento declarado × inferido ─────────
def test_declared_matches_have_no_inference_and_inferred_ones_say_where_it_came_from():
    declared = cv.match_offer({"holofoil": {"market": 9.0}}, False, False, "Holo Rare", ref_rarity="Holo Rare")
    assert declared.match.status == cv.OK and declared.inferred is None
    plain = cv.match_offer({"normal": {"market": 1.0}}, False, False, "Common", ref_rarity="Common")
    assert plain.match.status == cv.OK and plain.inferred is None
    ray = cv.match_offer({"holofoil": {"market": 25.0}}, False, False, "Rare", ref_rarity="Amazing Rare",
                         set_released="2020-11-13")
    assert ray.match.status == cv.OK and ray.inferred and "Amazing Rare" in ray.inferred
    det = cv.match_offer({"holofoil": {"market": 14.0}}, False, False, "Promo", ref_rarity="Rare",
                         set_released="2019-04-05", set_code="det")
    assert det.match.status == cv.OK and det.inferred and "det" in det.inferred


def test_inconclusive_cardtrader_rarity_policy_is_one_named_decision_point():
    assert cv.NO_INFERENCE_CT_RARITIES == frozenset({"", "promo"})
    prices = {"holofoil": {"market": 14.0}}
    om = cv.match_offer(prices, False, False, "Promo", ref_rarity="Holo Rare", set_released="2019-04-05")
    assert om.match.status == cv.INCOMPATIVEL and om.inferred is None             # promo continua sem referência
    om = cv.match_offer(prices, False, False, None, ref_rarity="Holo Rare", set_released="2019-04-05")
    assert om.match.status == cv.INCOMPATIVEL
    # rótulo desconhecido da CT (BREAK = "Fixed") + produto holo-only: acabamento INFERIDO, não "Sim"
    om = cv.match_offer({"holofoil": {"market": 5.0}}, False, False, "Fixed", ref_rarity="Rare BREAK",
                        set_released="2016-08-03")
    assert om.match.status == cv.OK and om.inferred and "Fixed" in om.inferred


def test_inferred_line_is_marked_in_the_xlsx_never_compra_and_counted(tmp_path):
    o = _opp(0)
    o.ref_inferred = "CardTrader 'Rare' × referência 'Amazing Rare' (carta só existe em holo)"
    md, out = _run_pp(tmp_path, [o, _opp(1, seller="b")], stats={"scanned_at": "2026-11-24T04:51:58-03:00"})
    import pandas as pd
    raw = pd.read_excel(tmp_path / "in.xlsx", sheet_name="Oportunidades")
    assert sorted(raw["Ref Compatível"].tolist()) == ["Inferido", "Sim"]
    assert "acabamento inferido da referência" in md
    d = pd.read_excel(out, sheet_name="All Listings")
    col = next(c for c in d.columns if str(c).lower().startswith("decis"))
    assert not (d[col] == "COMPRA").any()


def test_classify_inferred_is_review_with_reason_even_if_everything_else_passes():
    cfg = pp.DecisionConfig()
    r = {"net_margin": 0.5, "lucro_liq": 100.0, "validation_status": "VALIDATED_REAL", "compra_inclui_hub": True,
         "ref_compativel": "Inferido", "ref_inferido": "motivo X", "card_number": "1", "set_code": "n1",
         "ref_age_dias": 1.0}
    d, why = pp.classify_decision(r, cfg, check_liquidity=False)
    assert d == "REVISAR" and "acabamento inferido da referência" in why and "motivo X" in why


def test_run_summary_counts_inferred_lines_per_set():
    s, listings = _build(4, [(k, "Unlimited Holofoil", 40.0 + k) for k in range(1, 5)], lambda i: None, breaker="off")
    ops = list(s.scan_expansion(EXP))
    for o in ops[:3]:
        o.ref_inferred = "x"
    s.stats = dict(s.stats)
    s._count_inferred(ops)
    assert "asc 3" in s.stats["acabamento_inferido"]
    assert any("INFERIDO" in l and "asc 3" in l for l in s.run_summary_lines())


# ───────── D: idade desconhecida não é "atual"; uma só função de idade ─────────
def test_unknown_reference_age_is_review_never_compra():
    cfg = pp.DecisionConfig()
    base = {"net_margin": 0.5, "lucro_liq": 100.0, "validation_status": "VALIDATED_REAL", "compra_inclui_hub": True,
            "ref_compativel": "Sim", "card_number": "1", "set_code": "n1"}
    d, why = pp.classify_decision({**base, "ref_age_dias": float("nan")}, cfg, check_liquidity=False)
    assert d == "REVISAR" and "idade da referência desconhecida" in why
    assert pp.classify_decision({**base, "ref_age_dias": 2.0}, cfg, check_liquidity=False)[0] == "COMPRA"


@pytest.mark.parametrize("at,label", [("2026-11-24T05:00:00-03:00", "buscado em"), ("", "dado de"),
                                      ("lixo", "dado de"), (None, "")])
def test_postprocess_marks_unknown_age(tmp_path, at, label):
    o = _opp(0, data=at, label=label)
    md, out = _run_pp(tmp_path, [o], stats={"scanned_at": "2026-11-24T04:51:58-03:00"})
    assert "idade da referência desconhecida" in md


def test_scanner_and_postprocess_compute_age_with_the_same_function():
    import ct_refage
    now = datetime(2026, 11, 24, 4, 51, 58, tzinfo=timezone(timedelta(hours=-3)))
    assert ct_refage.ref_age_days("2026-11-23T20:05:58+00:00", "dado de", now) == 1
    assert ct_refage.ref_age_days("2026-10-15", "dado de", now) == 40
    assert ct_refage.ref_age_days("2026-10-15", "buscado em", now) is None
    assert ct_refage.ref_age_days("lixo", "dado de", now) is None
    s = sc.Scanner.__new__(sc.Scanner)
    p = MagicMock()
    p.last_ref_data_at = "2020-01-01"
    assert s._ref_age_days(p) == ct_refage.ref_age_days("2020-01-01", "dado de", datetime.now().astimezone())
    p.last_ref_data_at = None
    assert s._ref_age_days(p) is None


def test_unknown_age_never_swaps_and_undated_tcgcsv_says_batch_date_not_informed():
    s, listings = _build(3, [(k, "Unlimited Holofoil", 40.0 + k) for k in range(1, 4)], lambda i: 99.0)
    s.max_ref_age_days = 7.0
    s.pricing.last_ref_data_at = None                      # sem data: não troca
    assert all(o.ref_swap == "" for o in s.scan_expansion(EXP))
    s2, _l = _build(3, [(k, "Unlimited Holofoil", 40.0 + k) for k in range(1, 4)], lambda i: 99.0)
    s2.max_ref_age_days = 7.0
    s2.pricing.last_ref_data_at = "2020-01-01"
    ops = list(s2.scan_expansion(EXP))
    assert all("data do lote não informada" in o.ref_swap and "lote do dia" not in o.ref_swap for o in ops)


# ───────── E: a 2ª fonte opcional não derruba o set; mesmas flags do disjuntor ─────────
def _primary_tcgcsv(alt):
    from test_b1f import _tcgcsv_primary
    return _tcgcsv_primary([(1, "Normal", 3.0), (2, "Normal", 3.0)], alt=alt)


def test_second_source_arbitrary_exception_is_a_per_offer_failure_not_a_failed_set():
    alt = MagicMock()
    alt.name = "pokemontcg"
    alt.market_price_usd.side_effect = ValueError("JSON inválido")
    s = _primary_tcgcsv(alt)
    s.breaker = None
    assert list(s.scan_expansion(EXP)) == []
    assert s._set_status == "complete"
    assert all("fonte alternativa falhou" in r["motivo"] and "ValueError" in r["motivo"] for r in s.noref_rows)
    assert len(s.noref_rows) == 2


def test_second_source_breaker_obeys_the_same_flags_and_is_in_the_health_line():
    alt = MagicMock()
    alt.name = "pokemontcg"
    alt.market_price_usd.side_effect = requests.Timeout("502")
    s = _primary_tcgcsv(alt)
    s.breaker = sc.SourceBreaker(window=4, min_samples=2, fail_rate=0.5, slow_s=7.0, probe_every_s=33.0)
    list(s.scan_expansion(EXP))
    b = s.ptcg_alt_breaker
    assert (b.window, b.min_samples, b.fail_rate, b.slow_s, b.probe_every_s) == (4, 2, 0.5, 7.0, 33.0)
    assert b.is_open and "2ª fonte" in s._source_health_line()
    s2 = _primary_tcgcsv(alt)
    s2.breaker = None                                       # --no-source-breaker
    list(s2.scan_expansion(EXP))
    assert "ptcg_alt_breaker" not in s2.__dict__


# ───────── F: baixas ─────────
def test_health_label_names_latency_and_failures_correctly():
    s = sc.Scanner.__new__(sc.Scanner)
    s.breaker = sc.SourceBreaker(window=10, min_samples=2, fail_rate=0.5, slow_s=10.0)
    s.breaker.record(False, 40.0)
    s.breaker.record(True, 40.0)                            # 1 falha em 2, e lento
    line = s._source_health_line()
    assert "latência" in line and "1 falha" in line and "1 falhas" not in line


@pytest.mark.parametrize("bad", ["nan", "0", "-3", "inf"])
def test_max_ref_age_days_rejects_nan_and_non_positive_in_both_programs(bad, tmp_path):
    with patch.object(sys, "argv", ["cardtrader_scanner.py", "--max-ref-age-days", bad, "--dry-run"]):
        with pytest.raises(SystemExit) as e:
            sc.main()
    assert e.value.code == 2
    with patch.object(sys, "argv", ["cardtrader_postprocess.py", "-i", str(tmp_path / "x.xlsx"), "-o",
                                    str(tmp_path / "o.xlsx"), "--max-ref-age-days", bad]):
        with pytest.raises(SystemExit) as e2:
            pp.main()
    assert e2.value.code == 2


def test_groups_retry_waits_between_attempts_and_default_is_two_seconds(monkeypatch):
    import re
    src = (REPO_ROOT / "cardtrader_scanner.py").read_text(encoding="utf-8")
    assert re.search(r"GROUPS_RETRY_WAIT_S\s*=\s*2(\.0)?\b", src)
    sleeps = []
    monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(sc.TcgCsvFallbackProvider, "GROUPS_RETRY_WAIT_S", 2.5)
    monkeypatch.setattr(sc, "tcgcsv_fetch_groups", lambda session: None)
    prov = sc.TcgCsvFallbackProvider.__new__(sc.TcgCsvFallbackProvider)
    prov.cache, prov._groups, prov._groups_fetched, prov._set_index, prov._pid_index = MagicMock(), None, False, {}, {}
    prov._groups_failed_at = None
    prov.session = MagicMock()
    assert prov.prefill_set("asc", ["me2pt5"], "Ascended Heroes") is False
    assert sleeps == [2.5] * (sc.TcgCsvFallbackProvider.GROUPS_ATTEMPTS - 1)


# ───────── G: propriedade do caminho inteiro com ORÁCULO ESCRITO À MÃO ─────────
_ERA_SV, _ERA_ULTRA, _ERA_SECRET = "2023-03-31", "2005-05-10", "2008-11-05"


def _declared(rar, era, code):
    """Acabamento DECLARADO pelo rótulo da CardTrader (tabela à mão; None = inconclusivo)."""
    if rar in (None, "", "Promo", "Fixed"):      # inconclusivos (CT não declara o acabamento)
        return None
    if rar in ("Common", "Uncommon", "Common Non-Holo", "Non-Holo"):
        return "normal"
    if rar in ("Holo Rare", "Rare Holo", "Illustration Rare"):
        return "holo"
    if rar == "Rare":
        return "holo" if era and era >= _ERA_SV else "normal"
    if rar == "Ultra Rare":
        return "holo" if era and era >= _ERA_ULTRA else "normal"
    if rar == "Secret Rare":
        return "holo" if era and era >= _ERA_SECRET and code != "evo" else "normal"
    raise AssertionError(rar)


_CT_R = [None, "", "Promo", "Fixed", "Common", "Uncommon", "Rare", "Holo Rare", "Rare Holo", "Ultra Rare", "Secret Rare",
         "Illustration Rare", "Non-Holo", "Common Non-Holo"]
_REF_R = [None, "Common", "Rare", "Holo Rare", "Amazing Rare", "Secret Rare", "Ultra Rare"]
_KEYS = [("normal",), ("holofoil",), ("reverseHolofoil",), ("normal", "holofoil"), ("normal", "reverseHolofoil"),
         ("holofoil", "reverseHolofoil"), ("normal", "holofoil", "reverseHolofoil"),
         ("unlimited", "unlimitedHolofoil"), ("1stEdition", "1stEditionHolofoil"),
         ("1stEdition", "1stEditionHolofoil", "unlimited", "unlimitedHolofoil")]
_PRICE_STATES = ("all", "first_missing", "only_last")
_FIN_OF = {"normal": "normal", "unlimited": "normal", "1stEdition": "normal", "holofoil": "holo",
           "unlimitedHolofoil": "holo", "1stEditionHolofoil": "holo", "reverseHolofoil": "reverse"}
_ED_OF = {"normal": "none", "holofoil": "none", "reverseHolofoil": "none", "unlimited": "unl",
          "unlimitedHolofoil": "unl", "1stEdition": "1st", "1stEditionHolofoil": "1st"}


def _prices(keys, state):
    out = {}
    for i, k in enumerate(keys):
        missing = (state == "first_missing" and i == 0) or (state == "only_last" and i != len(keys) - 1)
        out[k] = {"market": (None if i % 2 else 0) if missing else 2.0 + i}
    return out


def test_property_full_path_with_hand_written_oracle():
    n = viol = 0
    for ct, ref, keys, state, rev, era, code, fe, grp in itertools.product(
            _CT_R, _REF_R, _KEYS, _PRICE_STATES, (False, True), (None, "2002-01-01", "2010-01-01", "2024-05-01"),
            (None, "evo", "det"), (False, True), (None, "Base Set (Shadowless)")):
        prices = _prices(keys, state)
        om = cv.match_offer(prices, fe, rev, ct, ref_rarity=ref, set_released=era, set_code=code, group_name=grp)
        n += 1
        m = om.match
        if ref == ct and ct is not None and ct != "":
            assert "raridades em conflito" not in m.reason, (ct, keys, era, code)
        if grp:
            assert m.status != cv.OK, "Shadowless nunca é referência"
        if m.status != cv.OK:
            continue
        fin, ed = _FIN_OF[m.key], _ED_OF[m.key]
        assert m.key in prices and (prices[m.key]["market"] or 0) > 0, "OK exige chave COM preço"
        assert (ed == "1st") == fe, ("edição diferente da oferta", m.key, fe)
        decl = _declared(ct, era, code)
        if rev:
            assert fin == "reverse", (m.key, "reverse")
            continue
        if om.inferred is not None and decl is not None:
            # inferir o holo contra um rótulo CT conclusivo só vale se a carta NÃO tem nenhuma chave normal (com ou sem preço)
            assert not any(_FIN_OF[k] == "normal" for k in prices), ("inferiu holo com impressão normal existente", ct, keys, state)
        if om.inferred is None:
            assert ct not in (None, "", "Promo"), ("promo/vazia nunca é 'Sim' (acabamento não declarado)", ct, m.key, era, code)
            want = decl if decl is not None else "normal"          # inconclusivo sem inferência = normal (política)
            if code == "det" and ct in (None, "", "Promo"):
                want = "holo" if fin == "holo" else want
            assert fin == want, ("'Sim' com acabamento diferente do declarado", ct, ref, m.key, era, code)
        # nunca OK com outra chave quando a chave CERTA (acabamento declarado) existe SEM preço
        if decl is not None and om.inferred is None:
            right = [k for k in prices if _FIN_OF[k] == decl and (_ED_OF[k] == "1st") == fe
                     and (prices[k]["market"] or 0) <= 0]
            assert not right or fin == decl, ("OK com outra chave com a certa sem preço", keys, state, ct)
    assert n > 30_000


# ───────── H: todo número de fonte do resumo é derivável das linhas do XLSX ─────────
def test_source_counters_match_the_xlsx_rows_including_age_swaps(tmp_path):
    import pandas as pd
    s, listings = _build(6, [(k, "Unlimited Holofoil", 40.0 + k) for k in range(1, 7)], lambda i: 99.0 if i < 2 else None,
                         breaker="off")
    s.max_ref_age_days = 7.0
    s.pricing.last_ref_data_at = "2020-01-01"          # as 2 primeiras ofertas (hits) serão trocadas por idade
    opps = s.scan([EXP])
    x = tmp_path / "scan.xlsx"
    sc.export_xlsx(opps, s.stats, x, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    df = pd.read_excel(x, sheet_name="Oportunidades")
    rows = df["Fonte Preço"].value_counts().to_dict()
    text = "\n".join(s.run_summary_lines())
    by = {}
    for o in s.set_outcomes:
        for k, v in o["by_source"].items():
            by[k] = by.get(k, 0) + v
    for src in ("pokemontcg", "tcgcsv"):
        assert by.get(src, 0) == rows.get(src, 0), (src, by, rows)
    assert s.stats["linhas_por_fonte"] == "; ".join(f"{k} {v}" for k, v in sorted(rows.items()))
    swaps = int(df["Troca de Referência"].notna().sum())
    assert swaps == 2 == s.stats["refs_trocadas_por_idade"]
    assert s.stats["tcgcsv_fallback_priced"] + swaps == rows["tcgcsv"]       # parcelas fecham com o total da fonte
    assert f"{swaps} referências trocadas por idade" in text


# ───────── B1h: promo com raridade inconclusiva + única impressão ─────────
_PRM = json.loads((REPO_ROOT / "tests" / "fixtures" / "variants" / "b1h_promos.json").read_text(encoding="utf-8"))


def _wiz():
    return _real_provider("wiz", 1418, "Wizards Black Star Promos", "1999-07-01T00:00:00", _PRM["wiz"])


@pytest.mark.parametrize("name,num,price", [("Smeargle", "032", 19.08), ("Mew", "008", 11.9)])
def test_promo_with_only_a_normal_print_matches_but_as_inferred(name, num, price):
    p = _wiz()
    assert p.market_price_usd(name, "wiz", num, rarity="Promo") == price      # margem calculável
    assert p.last_ref_inferred and "raridade 'Promo' não informa o acabamento" in p.last_ref_inferred
    assert "só tem a impressão normal" in p.last_ref_inferred
    assert p.last_ref_exact in (True, False)                                  # ainda é Match OK; o rótulo é "Inferido"


def test_mirror_case_promo_with_only_a_holofoil_print_stays_without_reference():
    xy = _PRM["xybsp"][0]
    p = _real_provider("xybsp", 1451, "XY Black Star Promos", "2014-02-05T00:00:00", [xy])
    assert p.market_price_usd(xy["name"], "xybsp", xy["number"], rarity="Promo") is None
    assert p.last_ref_status == cv.INCOMPATIVEL and not p.last_ref_inferred
    # a escolha mora num único mapa nomeado: trocar o valor muda o resultado
    assert cv.INCONCLUSIVE_SINGLE_PRINT_POLICY == {"normal": "inferir", "holo": "sem_referencia"}


def test_policy_map_is_the_single_switch(monkeypatch):
    prices = {"holofoil": {"market": 7.0}}
    assert cv.match_offer(prices, False, False, "Promo", ref_rarity="Promo").match.status == cv.INCOMPATIVEL
    monkeypatch.setitem(cv.INCONCLUSIVE_SINGLE_PRINT_POLICY, "holo", "inferir")
    om = cv.match_offer(prices, False, False, "Promo", ref_rarity="Promo")
    assert om.match.status == cv.OK and om.inferred and "só tem a impressão holo" in om.inferred


def test_promo_with_more_than_one_non_reverse_print_is_incompatible():
    prices = {"normal": {"market": 1.0}, "holofoil": {"market": 9.0}}
    om = cv.match_offer(prices, False, False, "Promo", ref_rarity="Promo")
    assert om.match.status == cv.INCOMPATIVEL and "desconhecido" in om.match.reason


def test_promo_reverse_offer_needs_a_reverse_key_declared_by_the_offer_field():
    prices = {"normal": {"market": 1.0}}
    assert cv.match_offer(prices, False, True, "Promo", ref_rarity="Promo").match.status == cv.INCOMPATIVEL
    both = {"normal": {"market": 1.0}, "reverseHolofoil": {"market": 3.0}}
    om = cv.match_offer(both, False, True, "Promo", ref_rarity="Promo")
    assert om.match.status == cv.OK and om.match.key == "reverseHolofoil" and om.inferred is None
    om2 = cv.match_offer(both, False, False, "Promo", ref_rarity="Promo")        # a mesma carta, oferta normal
    assert om2.match.key == "normal" and om2.inferred


def test_inferred_promo_is_counted_marked_and_never_compra(tmp_path):
    o = _opp(0)
    o.ref_inferred = "raridade 'Promo' não informa o acabamento; a referência só tem a impressão normal"
    md, out = _run_pp(tmp_path, [o], stats={"scanned_at": "2026-11-24T04:51:58-03:00"})
    assert "acabamento inferido da referência" in md and "[oferta](" in md
    import pandas as pd
    d = pd.read_excel(out, sheet_name="All Listings")
    col = next(c for c in d.columns if str(c).lower().startswith("decis"))
    assert not (d[col] == "COMPRA").any()


def test_claude_md_documents_the_inconclusive_single_print_policy():
    t = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "INCONCLUSIVE_SINGLE_PRINT_POLICY" in t and "Inferido" in t
