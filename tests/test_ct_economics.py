"""Testes de ct_economics (D8): margem unica, base compra, custos opt-in."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ct_economics import Costs, compute  # noqa: E402


def test_exemplo_75_100():
    e = compute(100, 75)
    assert e.margem_bruta == pytest.approx(1 / 3)
    assert e.desconto == pytest.approx(0.25)
    assert e.lucro_bruto == pytest.approx(25)


def test_custo_zero_roi_igual_bruta_e_liquida_igual_desconto():
    for ref, compra in [(100, 60), (100, 75), (100, 78), (100, 40), (550, 330)]:
        e = compute(ref, compra)
        assert e.roi_liquido == pytest.approx(e.margem_bruta)
        assert e.margem_liquida == pytest.approx(e.desconto)
        assert e.lucro_liquido == pytest.approx(e.lucro_bruto)


def test_tabela_d85():
    assert compute(100, 60).margem_bruta == pytest.approx(0.6667, abs=1e-4)
    assert compute(100, 76.9).margem_bruta == pytest.approx(0.30, abs=1e-3)
    assert compute(100, 78).margem_bruta == pytest.approx(0.2821, abs=1e-4)
    assert compute(100, 40).margem_bruta == pytest.approx(1.5)


def test_hub_6pct_exemplo_spec():
    e = compute(550, 330, Costs(hub_fee_rate=0.06))
    assert e.custo_total == pytest.approx(349.80)
    assert e.lucro_liquido == pytest.approx(200.20)
    assert e.margem_liquida == pytest.approx(0.364, abs=1e-3)
    assert e.roi_liquido == pytest.approx(0.572, abs=1e-3)


def test_custos_compostos():
    c = Costs(hub_fee_rate=0.06, iof_rate=0.035, card_fee_rate=0.01,
              frete_compra_brl=10, sell_fee_rate=0.1, frete_venda_brl=5)
    e = compute(200, 100, c)
    assert e.custo_total == pytest.approx(100 * 1.06 * 1.045 + 10)
    assert e.receita_liquida == pytest.approx(200 * 0.9 - 5)
    assert e.lucro_liquido == pytest.approx(e.receita_liquida - e.custo_total)


def test_costs_default_tudo_zero():
    assert Costs() == Costs(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("ref,compra", [
    (0, 50), (-1, 50), (None, 50), (float("nan"), 50), (math.inf, 50),
    (100, 0), (100, -5), (100, None), (100, float("nan")),
])
def test_entradas_invalidas_devolvem_none(ref, compra):
    assert compute(ref, compra) is None


