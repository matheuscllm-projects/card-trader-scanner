"""Margem unica do CardTrader scanner (D8). Funcao pura, sem I/O.

- margem_bruta = (ref - compra) / compra   (base compra; canonica da frota, sem taxa)
- desconto     = (ref - compra) / ref      (o "Margem %" antigo do CT)
- roi_liquido  = lucro_liquido / custo_total (alimenta --min-net-margin)
Custos entram por `Costs`, todos zero por padrao (nenhum valor inventado).
Entrada invalida (compra/ref ausente, NaN, <= 0) -> compute() devolve None.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Costs:
    hub_fee_rate: float = 0.0
    iof_rate: float = 0.0
    card_fee_rate: float = 0.0
    frete_compra_brl: float = 0.0
    sell_fee_rate: float = 0.0
    frete_venda_brl: float = 0.0


@dataclass(frozen=True)
class Economics:
    lucro_bruto: float
    margem_bruta: float
    desconto: float
    custo_total: float
    receita_liquida: float
    lucro_liquido: float
    margem_liquida: float
    roi_liquido: float


def _valid(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def compute(ref_brl: float, compra_brl: float,
            costs: Costs = Costs()) -> Optional[Economics]:
    """None = sem margem (ref ou compra invalida)."""
    if not (_valid(ref_brl) and _valid(compra_brl)):
        return None
    lucro_bruto = ref_brl - compra_brl
    custo_total = (compra_brl * (1 + costs.hub_fee_rate)
                   * (1 + costs.iof_rate + costs.card_fee_rate)
                   + costs.frete_compra_brl)
    receita = ref_brl * (1 - costs.sell_fee_rate) - costs.frete_venda_brl
    lucro_liq = receita - custo_total
    return Economics(
        lucro_bruto=lucro_bruto,
        margem_bruta=lucro_bruto / compra_brl,
        desconto=lucro_bruto / ref_brl,
        custo_total=custo_total,
        receita_liquida=receita,
        lucro_liquido=lucro_liq,
        margem_liquida=lucro_liq / ref_brl,
        roi_liquido=lucro_liq / custo_total,
    )
