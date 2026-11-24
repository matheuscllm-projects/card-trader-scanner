"""Economia do CardTrader scanner (D8). Funcao pura, sem I/O.

CAMPO QUE ALIMENTA O CORTE (--threshold 0.30): `Economics.margem_venda`
  margem_venda   = (ref - compra) / ref      sobre a VENDA; unica metrica do corte
  roi_aquisicao  = (ref - compra) / compra   INFORMATIVO; nunca substitui a margem no corte
  (compra 75, ref 100 -> margem 25% NAO passa em 30%, mesmo com ROI 33,3%)
  margem_liquida_venda   = lucro liquido / receita liquida
  roi_liquido_aquisicao  = lucro liquido / custo total de aquisicao

Custos: so Hub (6%) e frete de compra (R$ 0,50/carta) tem valor (decisao do dono).
Os demais valem None = NAO INFORMADO (diferente de 0). Enquanto houver custo nao
informado, as liquidas saem PARCIAIS (`liquida_definitiva=False`, `custos_nao_informados`);
o calculo parcial trata o nao informado como 0 so para ter um numero, nunca como definitivo.

Hub: o preco validado no checkout da CardTrader ja embute o Hub; `compra_inclui_hub`
e obrigatorio e a taxa nunca e aplicada duas vezes.
Entrada invalida -> Economics com `sem_margem_motivo` (nunca None mudo).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Optional


def _num(x) -> Optional[float]:
    """float finito ou None. bool nao e numero; numpy/Decimal/str numerica convertem."""
    if x is None or isinstance(x, bool) or type(x).__name__ == "bool_":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _pos(x) -> Optional[float]:
    v = _num(x)
    return v if v is not None and v > 0 else None


_RATES = ("hub_fee_rate", "iof_rate", "spread_cambio_rate", "card_fee_rate",
          "import_tax_rate", "sell_fee_rate")
_BRL = ("frete_compra_brl", "frete_venda_brl")


@dataclass(frozen=True)
class Costs:
    hub_fee_rate: Optional[float] = 0.06        # valor do dono
    frete_compra_brl: Optional[float] = 0.50    # por carta, valor do dono
    iof_rate: Optional[float] = None            # None = NAO INFORMADO (0 informado conta)
    spread_cambio_rate: Optional[float] = None
    card_fee_rate: Optional[float] = None
    import_tax_rate: Optional[float] = None
    sell_fee_rate: Optional[float] = None
    frete_venda_brl: Optional[float] = None

    def __post_init__(self):
        for name in _RATES + _BRL:
            raw = getattr(self, name)
            if raw is None:
                continue
            v = _num(raw)
            if v is None or v < 0 or (name in _RATES and v >= 1):
                raise ValueError(f"Costs.{name}={raw!r} invalido "
                                 f"(taxa em [0,1), frete >= 0, finito, nao bool)")
            object.__setattr__(self, name, v)


@dataclass(frozen=True)
class Economics:
    sem_margem_motivo: Optional[str]
    lucro_bruto: Optional[float] = None
    margem_venda: Optional[float] = None          # ALIMENTA O CORTE
    roi_aquisicao: Optional[float] = None         # informativo
    custo_total: Optional[float] = None
    receita_liquida: Optional[float] = None
    lucro_liquido: Optional[float] = None
    margem_liquida_venda: Optional[float] = None
    roi_liquido_aquisicao: Optional[float] = None
    liquida_definitiva: bool = False
    custos_nao_informados: tuple = ()
    completude: float = 0.0                        # fracao dos custos informados
    compra_inclui_hub: bool = False

    @property
    def tem_margem(self) -> bool:
        return self.sem_margem_motivo is None

    def passa_corte(self, threshold: float) -> bool:
        """Corte = margem_venda >= threshold (fracao). Nunca usa o ROI."""
        return self.margem_venda is not None and self.margem_venda >= threshold


def compute(ref_brl, compra_brl, *, compra_inclui_hub: bool,
            costs: Optional[Costs] = None) -> Economics:
    if not isinstance(compra_inclui_hub, bool):
        raise TypeError("compra_inclui_hub deve ser bool explicito")
    costs = costs if costs is not None else Costs()
    nomes = [f.name for f in fields(Costs)]
    # Hub ja embutido no checkout conta como resolvido, nao como "nao informado".
    faltam = tuple(n for n in nomes if getattr(costs, n) is None
                   and not (n == "hub_fee_rate" and compra_inclui_hub))
    comum = dict(custos_nao_informados=faltam,
                 completude=(len(nomes) - len(faltam)) / len(nomes),
                 compra_inclui_hub=compra_inclui_hub)

    ref, compra = _pos(ref_brl), _pos(compra_brl)
    if ref is None or compra is None:
        quem = [n for n, v in (("referencia", ref), ("compra", compra)) if v is None]
        return Economics(f"{' e '.join(quem)} invalida (ausente, nao numerica, nao finita ou <= 0)",
                         **comum)

    g = lambda n: getattr(costs, n) or 0.0  # noqa: E731 - None tratado como 0 so no parcial
    hub = 0.0 if compra_inclui_hub else g("hub_fee_rate")
    try:
        lucro_bruto = ref - compra
        custo = (compra * (1 + hub)
                 * (1 + g("iof_rate") + g("spread_cambio_rate") + g("card_fee_rate")
                    + g("import_tax_rate"))
                 + g("frete_compra_brl"))
        receita = ref * (1 - g("sell_fee_rate")) - g("frete_venda_brl")
        lucro_liq = receita - custo
        vals = dict(
            lucro_bruto=lucro_bruto, margem_venda=lucro_bruto / ref,
            roi_aquisicao=lucro_bruto / compra, custo_total=custo,
            receita_liquida=receita, lucro_liquido=lucro_liq,
            margem_liquida_venda=lucro_liq / receita if receita > 0 else None,
            roi_liquido_aquisicao=lucro_liq / custo)
    except (OverflowError, ZeroDivisionError):
        vals = {"margem_venda": math.nan}
    if not all(v is None or math.isfinite(v) for v in vals.values()):
        return Economics("resultado nao finito (compra/referencia fora de escala)", **comum)
    return Economics(None, liquida_definitiva=not faltam, **vals, **comum)
