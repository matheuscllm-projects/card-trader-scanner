"""Lote 3 (D): validação per-blueprint de TODAS as oportunidades elegíveis (sem
corte top-N por padrão); linha que não pôde ser validada continua na saída com o
status real; o que é descartado por --min-net-margin é contado e logado."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cardtrader_scanner as sc  # noqa: E402


def _opp(bp_id, margin=0.5, status="NOT_VALIDATED", real_net=None, name=None):
    l = sc.Listing(
        product_id=bp_id, blueprint_id=bp_id, card_name=name or f"Card {bp_id}",
        set_code="aq", set_name="Aquapolis", collector_number=f"{bp_id:03d}/147",
        condition="Near Mint", language="en", price_cents=10000,
        price_currency="BRL", price_brl=100.0, quantity=1, foil=False,
        graded=False, seller_username=f"s{bp_id}", seller_can_sell_via_hub=True,
        seller_user_type="professional", cardtrader_url=f"https://x/{bp_id}",
        rarity="Rare")
    o = sc.Opportunity(listing=l, tcg_market_usd=40.0, tcg_market_brl=200.0,
                       ct_price_brl=100.0, margin_pct=margin, margin_brl=100.0,
                       estimated_shipping_brl=0.0, net_margin_pct=margin)
    o.validation_status = status
    o.real_net_margin_pct = real_net
    return o


def _scanner():
    s = sc.Scanner.__new__(sc.Scanner)
    s.usd_brl, s.eur_brl, s.hub_fee_rate, s.stats = 5.0, 5.9, 0.0, {}
    s.language = "en"
    s.ct = MagicMock()
    s.ct.list_listings_by_blueprint = MagicMock(return_value=[])
    return s


def test_validate_per_blueprint_default_validates_every_candidate():
    s = _scanner()
    opps = [_opp(i, margin=0.9 - i / 1000) for i in range(1, 46)]  # 45 > 30
    s.validate_per_blueprint(opps)  # sem top_n → TODAS
    assert s.ct.list_listings_by_blueprint.call_count == 45
    assert all(o.validation_status != "NOT_VALIDATED" for o in opps)


def test_validate_per_blueprint_explicit_limit_still_works():
    s = _scanner()
    opps = [_opp(i, margin=0.9 - i / 1000) for i in range(1, 46)]
    s.validate_per_blueprint(opps, top_n=10)
    assert s.ct.list_listings_by_blueprint.call_count == 10
    assert sum(o.validation_status == "NOT_VALIDATED" for o in opps) == 35


def test_filter_keeps_rows_that_could_not_be_validated(caplog):
    rows = [
        _opp(1, status="STALE"),
        _opp(2, status="API_ERROR"),
        _opp(3, status="PRICE_CHANGED"),
        _opp(4, status="NOT_VALIDATED"),
        _opp(5, status="VALIDATED_REAL", real_net=0.40),
    ]
    with caplog.at_level(logging.INFO, logger=sc.log.name):
        kept, dropped = sc.apply_validation_filters(rows, min_net_margin=0.20)
    assert [o.listing.blueprint_id for o in kept] == [1, 2, 3, 4, 5]
    assert dropped == []
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "STALE/API_ERROR/PRICE_CHANGED" not in text  # texto antigo enganoso


def test_filter_drops_only_validated_rows_below_min_net_and_reports_them(caplog):
    rows = [
        _opp(1, status="VALIDATED_REAL", real_net=0.10, name="Barata"),
        _opp(2, status="VALIDATED_MARKUP", real_net=0.35),
        _opp(3, status="STALE"),
    ]
    with caplog.at_level(logging.INFO, logger=sc.log.name):
        kept, dropped = sc.apply_validation_filters(rows, min_net_margin=0.20)
    assert [o.listing.blueprint_id for o in kept] == [2, 3]
    assert [o.listing.blueprint_id for o in dropped] == [1]
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Barata" in text and "min-net-margin" in text, text  # nada some em silêncio


def test_validate_top_default_is_all_and_flag_still_accepts_a_limit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py"])
    assert sc.parse_args().validate_top is None  # padrão = todas
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py", "--validate-top", "5"])
    assert sc.parse_args().validate_top == 5
    monkeypatch.setattr(sys, "argv", ["cardtrader_scanner.py", "--validate-top", "0"])
    assert sc.parse_args().validate_top == 0  # 0 = desliga a validação
