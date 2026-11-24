"""Gera tests/fixtures/scan_sintetico.xlsx — XLSX SINTETICO no formato do scan real.

DELIVERY_CHAT.md: resultados/precos de coleta real nao vao para o GitHub. Por isso esta
fixture NAO e um recorte do scan real: tem as MESMAS colunas, abas (Oportunidades + Stats)
e tipos do XLSX real de 34 sets vintage, mas nomes de vendedor, links, precos e margens sao
INVENTADOS (semente fixa). Rode `python tests/fixtures/make_scan_sintetico.py` para regerar.

Casos cobertos: margem alta validada (checkout real), margem negativa (validada e nao),
linha sem referencia (TCG ausente), numero com letra (50a), linha sem validacao (so preco
cru do scan), reverse, variante baixa confianca, TG##.
"""
import os
import random

import pandas as pd

COLS = ['Card Name', 'Set', 'Nº', 'Rarity', 'Condição', 'Idioma', 'Scan R$ (raw)',
        'Moeda Original CT', 'LIVE R$ (real)', 'Markup %', 'Markup Tier', 'Validation Status',
        'TCG Market (BRL)', 'TCG Market (USD)', 'Margem % (scan)', 'Margem % REAL',
        'Net Margin % (scan)', 'Net Margin % REAL', 'Lucro R$ REAL', 'Frete Est. R$', 'Qtd',
        'Foil', 'Variant', 'Seller', 'Tipo Seller', 'Hub', 'Link CardTrader', 'Link TCG',
        'Scanned At', 'Chase Tier', 'Desconto %', 'Score heurístico (raridade+idade+preço, 0-100)',
        'Valorização — Notas', 'Variante Baixa Confiança', 'Fonte Preço']
FX = 5.5
SETS = ["Jungle (ju)", "Fossil (fo)", "Base Set (bs)", "Neo Genesis (n1)", "Aquapolis (aq)",
        "EX Dragon (dr)", "Skyridge (skg)", "Team Rocket (tr)"]
NAMES = ["Alakazam", "Pidgeot", "Scyther", "Kabutops", "Lanturn", "Umbreon", "Tyranitar",
         "Raichu", "Gengar", "Dragonite", "Misty", "Erika", "Mewtwo", "Snorlax", "Charmeleon"]


def _row(i, rng, *, tcg_usd, scan_brl, live=None, number=None, variant="normal", rarity="Rare",
         low_conf=False, validated=None):
    ref_brl = None if tcg_usd is None else round(tcg_usd * FX, 2)
    base = live if live is not None else scan_brl
    margem = None if ref_brl is None else round((ref_brl - base) / ref_brl, 4)
    lucro = None if (live is None or ref_brl is None) else round(ref_brl - live, 2)
    return {
        'Card Name': NAMES[i % len(NAMES)], 'Set': SETS[i % len(SETS)],
        'Nº': number or f"{(i * 7) % 99 + 1:03d}/102", 'Rarity': rarity,
        'Condição': 'Near Mint', 'Idioma': 'EN', 'Scan R$ (raw)': scan_brl,
        'Moeda Original CT': 'USD', 'LIVE R$ (real)': live,
        'Markup %': 0.15 if live is not None else None,
        'Markup Tier': 'non-VAT (+20%)' if live is not None else None,
        'Validation Status': validated or ('VALIDATED_MARKUP' if live is not None else 'NOT_VALIDATED'),
        'TCG Market (BRL)': ref_brl, 'TCG Market (USD)': tcg_usd,
        'Margem % (scan)': margem if live is None else round((ref_brl - scan_brl) / ref_brl, 4) if ref_brl else None,
        'Margem % REAL': margem if live is not None else None,
        'Net Margin % (scan)': round((ref_brl - scan_brl) / ref_brl, 4) if ref_brl else None,
        'Net Margin % REAL': margem if live is not None else None,
        'Lucro R$ REAL': lucro, 'Frete Est. R$': 0, 'Qtd': 1 + i % 3,
        'Foil': 'Yes' if variant != 'normal' else 'No', 'Variant': variant,
        'Seller': f"vendedor-sintetico-{i % 5}", 'Tipo Seller': 'pro' if i % 2 else 'normal',
        'Hub': 'Yes', 'Link CardTrader': f"https://www.cardtrader.com/cards/9{i:05d}",
        'Link TCG': None if tcg_usd is None else f"https://www.tcgplayer.com/product/8{i:05d}",
        'Scanned At': '2026-01-01T00:00:00', 'Chase Tier': ['BULK', 'MODEST', 'TOP'][i % 3],
        'Desconto %': margem, 'Score heurístico (raridade+idade+preço, 0-100)': 30 + i % 20,
        'Valorização — Notas': 'sintetico', 'Variante Baixa Confiança': 'Sim' if low_conf else None,
        'Fonte Preço': 'tcgcsv',
    }


def build() -> pd.DataFrame:
    rng = random.Random(7)
    rows, i = [], 0
    # 6 validadas com margem alta e lucro >= R$50 (checkout real)
    for ref_usd, scan in [(60, 120), (45, 100), (80, 150), (30, 70), (120, 260), (25, 60)]:
        rows.append(_row(i, rng, tcg_usd=ref_usd, scan_brl=scan, live=round(scan * 1.15, 2)))
        i += 1
    # 2 validadas com margem negativa (LIVE acima da referencia)
    for ref_usd, scan in [(20, 140), (12, 90)]:
        rows.append(_row(i, rng, tcg_usd=ref_usd, scan_brl=scan, live=round(scan * 1.15, 2)))
        i += 1
    # 2 sem referencia (TCG ausente) — uma com preco validado
    rows.append(_row(i, rng, tcg_usd=None, scan_brl=80)); i += 1
    rows.append(_row(i, rng, tcg_usd=None, scan_brl=95, live=109.25)); i += 1
    # numeros com letra (promo/League) com margem alta
    rows.append(_row(i, rng, tcg_usd=70, scan_brl=130, number="50a", live=149.5)); i += 1
    rows.append(_row(i, rng, tcg_usd=40, scan_brl=90, number="12b")); i += 1
    # TG##, variante baixa confianca, reverse
    rows.append(_row(i, rng, tcg_usd=90, scan_brl=150, number="TG05", live=172.5)); i += 1
    rows.append(_row(i, rng, tcg_usd=55, scan_brl=100, live=115.0, low_conf=True)); i += 1
    rows.append(_row(i, rng, tcg_usd=50, scan_brl=95, live=109.25, variant="reverseHolofoil",
                     rarity="Common")); i += 1
    # 24 sem validacao (so preco cru): faixas de margem alta, borderline, baixa e negativa
    for k in range(24):
        ref_usd = 10 + (k * 13) % 60
        factor = [0.35, 0.55, 0.72, 0.85, 1.2, 2.0][k % 6]
        scan = round(ref_usd * FX * factor, 2)
        v = ["normal", "holofoil", "reverseHolofoil", "unlimitedHolofoil"][k % 4]
        rows.append(_row(i, rng, tcg_usd=ref_usd, scan_brl=scan, variant=v,
                         rarity=["Common", "Uncommon", "Rare", "Holo Rare"][k % 4]))
        i += 1
    return pd.DataFrame(rows, columns=COLS)


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_sintetico.xlsx")
    stats = pd.DataFrame([("language_filter", "en"), ("usd_brl_rate", FX),
                          ("threshold_margin", "30%"), ("margin_basis", "BRUTA (sem taxa)"),
                          ("fixture", "SINTETICA — valores inventados")],
                         columns=["Métrica", "Valor"])
    with pd.ExcelWriter(out) as w:
        build().to_excel(w, sheet_name="Oportunidades", index=False)
        stats.to_excel(w, sheet_name="Stats", index=False)
    print("OK", out)


if __name__ == "__main__":
    main()
