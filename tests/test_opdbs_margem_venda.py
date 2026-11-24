# -*- coding: utf-8 -*-
"""Margem SOBRE A VENDA (op + dbs): margem_venda = (tcg − ct)/tcg ; roi = (tcg − ct)/ct.
Corte 0.30 aplica-se à margem sobre a venda. ROI é só informativo. Ct ou tcg ≤ 0 → None."""

import pytest

import dbs_scanner as dbs
import op_scanner as op


@pytest.mark.parametrize("mod", [op, dbs])
def test_compra_75_ref_100_nao_passa_no_corte(mod):
    margem, roi = mod.margem_venda_roi(75.0, 100.0)
    assert margem == pytest.approx(0.25)
    assert roi == pytest.approx(0.3333, abs=1e-4)
    assert mod.classify(margem, 75.0, 100.0, 0.30)[0] != "compra"


@pytest.mark.parametrize("mod", [op, dbs])
def test_compra_70_ref_100_passa_no_corte(mod):
    margem, roi = mod.margem_venda_roi(70.0, 100.0)
    assert margem == pytest.approx(0.30)
    assert roi == pytest.approx(0.4286, abs=1e-4)
    assert mod.classify(margem, 70.0, 100.0, 0.30)[0] == "compra"


@pytest.mark.parametrize("mod", [op, dbs])
def test_compra_100_ref_80_negativa(mod):
    margem, roi = mod.margem_venda_roi(100.0, 80.0)
    assert margem == pytest.approx(-0.25)
    assert roi == pytest.approx(-0.20)


@pytest.mark.parametrize("mod", [op, dbs])
@pytest.mark.parametrize("ct, tcg", [(0.0, 100.0), (-5.0, 100.0), (75.0, 0.0), (75.0, -1.0)])
def test_ct_ou_tcg_nao_positivo_devolve_none(mod, ct, tcg):
    assert mod.margem_venda_roi(ct, tcg) == (None, None)
