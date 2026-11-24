"""B1m — regressão bloqueante: a validação per-blueprint gravava LIVE R$ 0,00 como VALIDATED_REAL.

Causa: `_enrich_validation` lia `price_cents`/`price_currency` NO TOPO do listing; a API real devolve
`price: {cents, currency}` (fixture REAL gravada em tests/fixtures/ct/). Os testes antigos usavam um payload
inventado com `price_cents` no topo, então nunca pegaram.
"""
from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cardtrader_postprocess as pp  # noqa: E402
import cardtrader_scanner as sc  # noqa: E402
from test_b1_wiring import _opp, _plain_scanner, _val_opp  # noqa: E402

REAL = json.loads((REPO_ROOT / "tests" / "fixtures" / "ct" / "blueprint_117903_listings.json").read_text(encoding="utf-8"))
REAL_LISTINGS = REAL["listings"]


def _scanner():
    s = _plain_scanner()
    s.hub_fee_rate = 0.06
    s.costs = sc.Costs()
    return s


def _opp_for(seller, price_brl=250.0, tcg_brl=1000.0):
    o = _val_opp(False)
    o.listing = dataclasses.replace(o.listing, seller_username=seller, blueprint_id=REAL["blueprint_id"],
                                    condition="Near Mint", foil=False)
    o.ct_price_brl, o.tcg_market_brl = price_brl, tcg_brl
    return o


def test_real_fixture_has_no_top_level_price_cents():
    assert all("price_cents" not in l and isinstance(l.get("price"), dict) for l in REAL_LISTINGS)


def test_real_payload_gives_a_live_price_and_a_validated_status():
    s, o = _scanner(), _opp_for("PokePosta-Store")
    s._enrich_validation(o, REAL_LISTINGS)
    assert o.live_price_brl == pytest.approx(345.36)
    assert o.validation_status in ("VALIDATED_REAL", "VALIDATED_MARKUP", "PRICE_CHANGED")
    assert o.real_margin_pct == pytest.approx((1000.0 - 345.36) / 1000.0)


@pytest.mark.parametrize("bad", [0, None, float("nan"), float("inf"), -5, "x"])
def test_invalid_live_price_is_never_validated_real(bad):
    s, o = _scanner(), _opp_for("PokePosta-Store")
    listing = dict(REAL_LISTINGS[0])
    listing["price"] = {"cents": bad, "currency": "BRL"}
    s._enrich_validation(o, [listing])
    assert o.validation_status == "PRECO_INVALIDO", o.validation_status
    assert o.live_price_brl is None and o.real_margin_pct is None and o.real_lucro_brl is None
    assert o.validation_reason and "preço live" in o.validation_reason


def test_missing_price_field_entirely_is_invalid_not_zero():
    s, o = _scanner(), _opp_for("PokePosta-Store")
    listing = {k: v for k, v in REAL_LISTINGS[0].items() if k != "price"}
    s._enrich_validation(o, [listing])
    assert o.validation_status == "PRECO_INVALIDO" and o.live_price_brl is None


def test_legacy_top_level_shape_still_works():
    s, o = _scanner(), _opp_for("PokePosta-Store")
    listing = {k: v for k, v in REAL_LISTINGS[0].items() if k != "price"}
    listing.update(price_cents=34536, price_currency="BRL")
    s._enrich_validation(o, [listing])
    assert o.live_price_brl == pytest.approx(345.36)


def test_summary_counts_real_only_when_the_live_price_is_valid(caplog):
    import logging
    s = _scanner()
    good, bad = _opp_for("PokePosta-Store", price_brl=345.0), _opp_for("Derek Lankford", price_brl=345.0)
    bad_listings = [dict(l, price={"cents": 0, "currency": "BRL"}) if l["user"]["username"] == "Derek Lankford" else l
                    for l in REAL_LISTINGS]
    s.ct = MagicMock()
    s.language = "en"
    s.ct.list_listings_by_blueprint.return_value = {"117903": bad_listings}
    s.stats = {}
    with caplog.at_level(logging.INFO, logger=sc.log.name):
        s.validate_per_blueprint([good, bad])
    assert good.validation_status.startswith("VALIDATED") and bad.validation_status == "PRECO_INVALIDO"
    assert any("1 REAL" in r.getMessage() and "1 preço live inválido" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]
    assert s.stats["v2_validated"] == 1


def test_top5_block_never_crashes_on_none_fields(capsys):
    o = _opp()
    o.live_price_brl, o.real_lucro_brl, o.real_margin_pct, o.real_net_margin_pct = 0.0, None, None, None
    o.validation_status = "VALIDATED_REAL"
    sc.print_top_opportunities([o], validated=True)            # não pode levantar
    out = capsys.readouterr().out
    assert "TOP 5" in out and "não validado" in out


def test_end_to_end_validation_to_xlsx_to_postprocess_reaches_revisar_with_live_price(tmp_path):
    s = _scanner()
    s.ct = MagicMock()
    s.language = "en"
    s.ct.list_listings_by_blueprint.return_value = {"117903": REAL_LISTINGS}
    s.stats = {}
    o = _opp_for("PokePosta-Store")
    o.margin_pct, o.net_margin_pct = (1000 - 250) / 1000, 0.7
    s.validate_per_blueprint([o])
    out = tmp_path / "scan.xlsx"
    sc.export_xlsx([o], {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    raw = pd.read_excel(out)
    assert raw["LIVE R$ (real)"].iloc[0] == pytest.approx(345.36)
    df = pp.enrich_df(raw)
    row = df.iloc[0]
    assert row["compra_inclui_hub"] is True or bool(row["compra_inclui_hub"])
    assert row["net_margin"] == pytest.approx((1000 - 345.36) / 1000, abs=1e-3)
    d, why = pp.classify_decision(row, pp.DecisionConfig())
    assert d in ("REVISAR", "COMPRA") and "sem referência" not in why.lower() and d != "SEM REF"


def test_end_to_end_invalid_live_price_stays_visible_as_revisar_not_sem_ref(tmp_path):
    s = _scanner()
    s.ct = MagicMock()
    s.language = "en"
    s.ct.list_listings_by_blueprint.return_value = {"117903": [dict(l, price={"cents": 0, "currency": "BRL"}) for l in REAL_LISTINGS]}
    s.stats = {}
    o = _opp_for("PokePosta-Store")
    o.margin_pct, o.net_margin_pct = 0.75, 0.7
    s.validate_per_blueprint([o])
    out = tmp_path / "scan.xlsx"
    sc.export_xlsx([o], {}, out, usd_brl=5.0, eur_brl=5.9, threshold=0.3)
    raw = pd.read_excel(out)
    assert pd.isna(raw["LIVE R$ (real)"].iloc[0]) and raw["Validation Status"].iloc[0] == "PRECO_INVALIDO"
    df = pp.enrich_df(raw)
    d, why = pp.classify_decision(df.iloc[0], pp.DecisionConfig())
    assert d == "REVISAR" and "preço não validado" in why
