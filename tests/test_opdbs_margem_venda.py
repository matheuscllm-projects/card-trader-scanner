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


# ── sem preço válido: nenhuma oferta some sem registro ──

def _bp_n(bp_id, num):
    return {"id": bp_id, "name": f"Carta {num}", "version": "", "tcg_player_id": bp_id,
            "fixed_properties": {"collector_number": num}}


def _offer(cents):
    return {"price": {"cents": cents, "currency": "BRL"}, "quantity": 1,
            "properties_hash": {"condition": "Near Mint"}}


@pytest.mark.parametrize("mod", [op, dbs])
def test_tcg_zero_conta_e_avisa_sem_sumir(mod, capsys):
    exp = {"id": 1, "code": "x", "name": "Expansão X"}
    rates = {"BRL": 5.0, "USD": 1.0, "EUR": 0.8}
    tcg_index = {
        1: {"name": "A", "url": "https://tcg/1", "prices": {"Foil": 74.0}},
        2: {"name": "B", "url": "https://tcg/2", "prices": {"Foil": 50.0}},
        3: {"name": "C", "url": "https://tcg/3", "prices": {"Foil": 0.0}},
    }
    bps = [_bp_n(1, "X-001"), _bp_n(2, "X-002"), _bp_n(3, "X-003")]
    offers = {1: [_offer(2000)], 2: [_offer(2000)], 3: [_offer(2000)]}
    rows, stats, _ = mod.build_rows(exp, bps, offers, tcg_index, rates, 0.0)
    assert len(rows) == 2
    assert stats["sem_preco_valido"] == 1
    # soma bate: cada blueprint cai em exatamente um balde
    assert (stats["selados_pulados"] + stats["sem_oferta_nm"] + stats["sem_ref_tcg"]
            + stats["abaixo_piso"] + stats["avaliadas"] + stats["sem_preco_valido"]) == stats["blueprints"] == 3
    assert "X-003" in capsys.readouterr().err  # log por carta, com número
    md = mod.build_markdown(rows, stats, {"data": "t", "expansoes": "x", "fx": 5.0,
                                          "fx_fonte": "t", "threshold": 0.30, "min_price_usd": 0.0})
    assert "1 sem preço válido" in md


@pytest.mark.parametrize("mod", [op, dbs])
def test_ct_zero_nao_derruba_scan_e_conta(mod, capsys):
    exp = {"id": 1, "code": "x", "name": "Expansão X"}
    rates = {"BRL": 5.0, "USD": 1.0, "EUR": 0.8}
    tcg_index = {1: {"name": "A", "url": "https://tcg/1", "prices": {"Foil": 74.0}}}
    rows, stats, _ = mod.build_rows(exp, [_bp_n(1, "X-001")], {1: [_offer(0)]}, tcg_index, rates, 10.0)
    assert rows == [] and stats["sem_preco_valido"] == 1
    assert "X-001" in capsys.readouterr().err
