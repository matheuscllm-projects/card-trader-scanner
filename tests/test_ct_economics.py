"""Testes de ct_economics (D8): margem_venda (corte) x roi_aquisicao (informativo), custos parciais."""
from __future__ import annotations

import math
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ct_economics import Costs, compute  # noqa: E402

THRESHOLD = 0.30
ALL_ZERO = dict(hub_fee_rate=0.0, iof_rate=0.0, spread_cambio_rate=0.0, card_fee_rate=0.0,
                import_tax_rate=0.0, frete_compra_brl=0.0, sell_fee_rate=0.0, frete_venda_brl=0.0)
ZERO = Costs(**ALL_ZERO)


def test_exemplo_75_100_margem_25_roi_333_e_nao_passa_no_corte():
    e = compute(100, 75, compra_inclui_hub=True, costs=ZERO)
    assert e.margem_venda == pytest.approx(0.25)
    assert e.roi_aquisicao == pytest.approx(1 / 3)
    assert e.lucro_bruto == pytest.approx(25)
    assert e.passa_corte(THRESHOLD) is False  # 33% de ROI nao flexibiliza o corte
    assert compute(100, 70, compra_inclui_hub=True, costs=ZERO).passa_corte(THRESHOLD) is True


def test_sem_nomes_ambiguos():
    e = compute(100, 75, compra_inclui_hub=True)
    assert not hasattr(e, "margem_bruta") and not hasattr(e, "desconto")
    assert not hasattr(e, "margem_liquida") and not hasattr(e, "roi_liquido")


def test_custo_zero_informado_liquidas_igualam_brutas():
    for ref, compra in [(100, 60), (100, 75), (100, 78), (100, 40), (550, 330)]:
        e = compute(ref, compra, compra_inclui_hub=True, costs=ZERO)
        assert e.liquida_definitiva is True
        assert e.roi_liquido_aquisicao == pytest.approx(e.roi_aquisicao)
        assert e.margem_liquida_venda == pytest.approx(e.margem_venda)


def test_custos_padrao_hub6_frete050_resultado_parcial_com_lista():
    e = compute(100, 50, compra_inclui_hub=False)  # compra crua 50
    assert e.custo_total == pytest.approx(50 * 1.06 + 0.50)
    assert e.liquida_definitiva is False
    assert set(e.custos_nao_informados) == {
        "iof_rate", "spread_cambio_rate", "card_fee_rate", "import_tax_rate",
        "sell_fee_rate", "frete_venda_brl"}
    assert e.completude == pytest.approx(2 / 8)
    assert e.lucro_liquido == pytest.approx(100 - (50 * 1.06 + 0.50))


def test_todos_informados_e_definitivo():
    c = Costs(hub_fee_rate=0.06, iof_rate=0.035, spread_cambio_rate=0.01, card_fee_rate=0.01,
              import_tax_rate=0.0, frete_compra_brl=0.5, sell_fee_rate=0.1, frete_venda_brl=5)
    e = compute(200, 100, compra_inclui_hub=False, costs=c)
    assert e.liquida_definitiva is True
    assert e.custos_nao_informados == ()
    assert e.completude == 1.0
    assert e.custo_total == pytest.approx(100 * 1.06 * (1 + 0.035 + 0.01 + 0.01 + 0.0) + 0.5)
    assert e.receita_liquida == pytest.approx(200 * 0.9 - 5)
    assert e.margem_liquida_venda == pytest.approx(e.lucro_liquido / e.receita_liquida)
    assert e.roi_liquido_aquisicao == pytest.approx(e.lucro_liquido / e.custo_total)


def test_hub_incluso_x_nao_incluso_mesmo_custo_total():
    cru = compute(200, 100, compra_inclui_hub=False, costs=Costs())
    incl = compute(200, 106, compra_inclui_hub=True, costs=Costs())
    assert cru.custo_total == pytest.approx(incl.custo_total) == pytest.approx(106.5)
    assert cru.lucro_liquido == pytest.approx(incl.lucro_liquido)
    # Hub incluso: nunca aplica a taxa, e hub nao conta como nao informado
    assert "hub_fee_rate" not in incl.custos_nao_informados


def test_compra_inclui_hub_obrigatorio_e_bool():
    with pytest.raises(TypeError):
        compute(100, 50)
    with pytest.raises(TypeError):
        compute(100, 50, compra_inclui_hub=1)


@pytest.mark.parametrize("make", [
    lambda v: v, float, Decimal, str,
])
def test_tipos_numericos_aceitos(make):
    e = compute(make(100), make(75), compra_inclui_hub=True, costs=ZERO)
    assert e.tem_margem and e.margem_venda == pytest.approx(0.25)


def test_numpy_aceito():
    np = pytest.importorskip("numpy")
    for t in (np.int64, np.float64, np.float32):
        e = compute(t(100), t(75), compra_inclui_hub=True, costs=ZERO)
        assert e.margem_venda == pytest.approx(0.25)


@pytest.mark.parametrize("ref,compra", [
    (0, 50), (-1, 50), (None, 50), (float("nan"), 50), (math.inf, 50), (True, 50), ("abc", 50),
    (100, 0), (100, -5), (100, None), (100, float("nan")), (100, math.inf), (100, False),
    (Decimal("NaN"), 50), (100, ""),
])
def test_entradas_invalidas_sem_margem_com_motivo(ref, compra):
    e = compute(ref, compra, compra_inclui_hub=True)
    assert e.tem_margem is False
    assert e.sem_margem_motivo
    assert e.margem_venda is None and e.roi_aquisicao is None
    assert e.passa_corte(THRESHOLD) is False


def test_compra_minuscula_nao_gera_inf():
    e = compute(100, 1e-320, compra_inclui_hub=True, costs=ZERO)
    assert e.tem_margem is False and e.sem_margem_motivo


@pytest.mark.parametrize("kw", [
    dict(hub_fee_rate=-1), dict(hub_fee_rate=1), dict(hub_fee_rate=float("nan")),
    dict(iof_rate=-0.1), dict(sell_fee_rate=1.5), dict(card_fee_rate=math.inf),
    dict(frete_compra_brl=-1), dict(frete_venda_brl=float("nan")), dict(hub_fee_rate=True),
    dict(frete_compra_brl="x"),
])
def test_costs_invalido_levanta(kw):
    with pytest.raises(ValueError):
        Costs(**kw)


def test_costs_defaults_e_none_vs_zero():
    c = Costs()
    assert c.hub_fee_rate == 0.06 and c.frete_compra_brl == 0.50
    assert c.iof_rate is None and c.sell_fee_rate is None
    assert Costs(iof_rate=0).iof_rate == 0.0  # zero explicito = informado
    assert Costs(hub_fee_rate=Decimal("0.06")).hub_fee_rate == 0.06
