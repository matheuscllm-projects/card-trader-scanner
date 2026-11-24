"""CardTrader Postprocess v2.0 — núcleo simplificado (operador 2026-05-16).

Mudancas vs v1.5:
- REMOVE bucket CORE/HYPE/DEAD classification
- REMOVE fundamental_analysis original (iconicidade/chase/meta heuristicas subjetivas)
- REMOVE long_term tier
- REMOVE coluna "Acao" (substituida por Decisao mecanica)
- ADICIONA Chase Tier (TOP/MID/MODEST/BULK) baseado em rarity oficial PokemonTCG
- ADICIONA Fundamental Score (0-100) derivado de metricas OBJETIVAS (chase + margin + lucro + validation)
- ADICIONA Decisao (COMPRA/REVISAR/NAO) via regra MECANICA (nao opiniao Claude)
- ADICIONA Porque (1 linha factual)
- REDUZ de 10 sheets pra 3 (Deals, All Listings, Summary). Expandido pra 6
  desde PR-K (+ Top 50 Margin, Validate Manually, TCG Suspect — modelo MYP)
- MANTEM: TG## auto-filter, hyperlinks, alias fixes
- v2.12 (2026-06-06): margem BRUTA — custo = preco_pagina, SEM taxa (default
  --hub-fee 0.0). SUPERSEDE o × 1.06. Operador soma fees por fora.

v2.1 (bug-hunt 2026-05-17):
- #2 Defensive recompute de net_margin/lucro_liq via fórmula 1.06 quando o
  input carrega `live_brl` + `reference_price_brl` válidos. Compara com o
  net_margin do input — drift > 0.5pp → WARN + usa recomputado. Coluna
  `margin_source` ("input" | "recomputed") preserva auditoria.
- #3 Força UTF-8 no stdout/encoding pra eliminar mojibake em headers
  (`Decis�o` → `Decisão`) quando invocado fora do wrapper PS sem
  PYTHONIOENCODING=utf-8. openpyxl pega encoding do interpreter locale.
- #4 Summary separa `Total listings escaneados` (input completo) de
  `Total deals exportados` (COMPRA + REVISAR). Antes o label estava
  errado — número era de deals, não listings totais.

v2.3 Layer 5 (bug-hunt 2026-05-18):
- ALPHA_SUFFIX_RE detecta `153a`, `022a`, `156b` no collector number.
  Tipicamente promo/League variant (1st/2nd/3rd/4th Place ou Prerelease)
  cega pra pokemontcg.io. classify_decision retorna REVISAR antes de
  qualquer outro check.
- Pareado com Scanner v2.8 Layer 4 (foil-aware variant disambiguation
  no provider) — cobre as 2 classes de falsos positivos de variante
  detectados na validação manual do weekly v2.6 (Pichu/Tyranitar e
  Lusamine).

Decisao mecanica (P1, 2026-11-24 — decisoes do dono; thresholds via CLI):
  margem = margem_venda = (ref - compra) / ref, vinda de ct_economics.compute (unica conta).
  O ROI sobre aquisicao e a margem liquida (Hub 6% + frete R$0,50/carta) sao INFORMATIVOS
  (liquida sempre PARCIAL enquanto houver custo nao informado).
  COMPRA:  margem_venda >= corte (0.30) AND lucro >= R$50 AND validacao real do preco
           AND referencia de variante compativel AND liquidez verificada no PriceCharting
           (vendas 90d >= --min-sales-90d E vendas 30d >= --min-sales-30d; ungraded, unitarias,
           pagina da MESMA edicao; contagem truncada vale "pelo menos N").
  REVISAR: faixa 20-30%, validacao ausente/anomala, flags de variante, ou liquidez baixa /
           NAO VERIFICADA (nunca COMPRA sem dado de liquidez).
  NAO:     abaixo do piso, TG/GG, STALE.
  AUDITORIA: margem negativa — fora da tabela comercial, so na aba Auditoria do XLSX.
  Chase tier e EXCLUSIVAMENTE informativo: nao aparece em nenhum ramo da decisao.

Memorias relevantes respeitadas:
  - margem BRUTA (operador 2026-06-06): custo = preco do site, sem taxa;
    fees calculados FORA do scanner. SUPERSEDE ct_margin_formula (× 1.06).
  - feedback_no_purchase_decisions: Decisao e REGRA mecanica, nao opiniao Claude
  - cardtrader_trainer_gallery_bug: TG## auto-filter mantido
"""
from __future__ import annotations

from chat_format import reference_price
import argparse, os, re, sys
import ct_variants
import pricecharting_ref
from ct_chase import classify_chase_tier  # unico dono do chase (informativo)
from ct_economics import BASES_COMPRA, BASES_VENDA, Costs, compute as compute_economics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Caminho 1 DoubleHolo (2ª opinião): join por productId TCGplayer + nota DH.
# Opcional — só ativa com a flag --doubleholo. Sem ela, comportamento idêntico.
import doubleholo_join

# ─── v2.1 fix #3 (bug-hunt 2026-05-17): força UTF-8 no I/O ───────────────────
# openpyxl.Workbook.save() pega encoding do interpreter locale via algum
# caminho interno. Em Windows com locale pt-BR, sys.stdout.encoding default
# é cp1252 → headers UTF-8 são gravados como bytes UTF-8 mas LIDOS como
# latin-1, produzindo mojibake (`Decis�o`, `Pre�o CT`). PYTHONIOENCODING=utf-8
# resolve, mas só quando o invocador seta a var (wrappers PS setam; scripts
# ad-hoc esquecem). Garantia defensiva aqui:
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    # Python <3.7 ou stdout não-reconfigurável (raro). Fallback silencioso.
    pass

# ─── Margem (P1, 2026-11-24): ct_economics.compute e a UNICA conta ────────────
# Corte = margem sobre a VENDA (ref - compra)/ref; ROI sobre aquisicao e so informativo.
# Hub 6% e frete R$0,50/carta entram so nas colunas LIQUIDAS (parciais); o preco de
# checkout (LIVE) ja embute o Hub, o preco cru do scan nao (compra_inclui_hub por linha).

# ─── Net % threshold pra Validate Manually (PR-L 2026-05-30) ─────────────────
# Net % chega em fração (0.30 = 30%). EXTREME_NET_PCT = 2.0 significa 200% —
# margens dessa magnitude são quase sempre falso positivo (provider error,
# inflação reverseHolofoil vintage, etc.) e vão pra revisão manual.
EXTREME_NET_PCT = 2.0

# ─── Gallery subset filter (Trainer Gallery TG## + Galarian Gallery GG##) ─────
# Cartas dos subsets de galeria geram FP massivo: o pricing pokemontcg.io casa
# com uma variante secret-rare alt-art de MESMO NOME (preço 5-10x maior) →
# margem falsa (35/38 oportunidades de um scan SWSH 2026-04-29 eram FP). Produção
# guardava só TG## (^TG\d+), mas o subset irmão Galarian Gallery é numerado GG##
# (confirmado: pokemontcg.io numera "GG01"… com rarity "Trainer Gallery Rare
# Holo", a MESMA classe) e escapava do guard → virava COMPRA com margem falsa.
# O próprio scanner já trata swsh12pt5gg (Crown Zenith Galarian Gallery) como
# gallery split problemático (não-aliasado de propósito) — esta regex só COMPLETA
# essa intenção no postprocess. Achado via ASI-Evolve (experimento
# cardtrader_classify: baseline COMPRA-F1 0,73 → 1,0 ao generalizar o guard).
# CONSERVADOR: roteia GG## pra NAO/manual igual TG##, nunca auto-compra. O nome
# TRAINER_GALLERY_RE é mantido por compat (agora cobre TG+GG).
TRAINER_GALLERY_RE = re.compile(r'^(?:TG|GG)\d+', re.IGNORECASE)

# ─── CT set base totals (PR-K — alinhamento com modelo MYP, 2026-05-29) ──────
# Formato Carta MYP-style: "Plusle (193/197)". Total = printedTotal do
# pokemontcg.io (números BASE do set, NÃO incluindo SIR/HR/secret rares).
# Fonte: api.pokemontcg.io/v2/sets queried 2026-05-29.
#   sv4 par   = 182 base / 266 total (Paradox Rift)
#   sv4pt5 paf= 91 base / 245 total  (Paldean Fates)
#   sv5 tef   = 162 base / 218 total (Temporal Forces)
#   sv6 twm   = 167 base / 226 total (Twilight Masquerade)
#   sv6pt5 sfa= 64 base / 99 total   (Shrouded Fable)
#   sv7 scr   = 142 base / 175 total (Stellar Crown)
#   sv8 ssp   = 191 base / 252 total (Surging Sparks)
#   sv8pt5 pre= 131 base / 180 total (Prismatic Evolutions)
#   sv9 jtg   = 159 base / 190 total (Journey Together)
#   sv10 dri  = 182 base / 244 total (Destined Rivals)
#   zsv10pt5 blk = 86 base / 172 total (Black Bolt)
#   me2pt5 asc= 217 base / 295 total (Ascended Heroes)
# Para sets fora desta tabela → fallback "Nome (NNN)" sem total.
CT_SET_TOTAL: dict[str, int] = {
    "par": 182,
    "paf": 91,
    "tef": 162,
    "twm": 167,
    "sfa": 64,
    "scr": 142,
    "ssp": 191,
    "pre": 131,
    "jtg": 159,
    "dri": 182,
    "asc": 217,
    "me2pt5": 217,  # PR-L CT-LOW-a: alias do code pokemontcg.io (= asc)
    "blk": 86,
}

# ─── Vintage suspect filter (PR-K — Validate Manually heuristic) ─────────────
# Sets confirmados como inflados na memória ct_scanner_session_handoff_2026_05_19
# (LC + BA-20 inflados confirmados). Pokemontcg.io aplica reverseHolofoil
# fallback que infla 5-30× quando o card-base tem preço baixo.
VINTAGE_SUSPECT_SETS = {
    "lc",       # Legendary Collection
    "ba-20", "ba20",  # Battle Academy 2020
    "ba-22", "ba22",  # Battle Academy 2022
}

# ─── Alpha suffix filter (v2.3 Layer 5 — bug-hunt 2026-05-18) ────────────────
# Cards com collector number `\d+[a-zA-Z]+` (ex `153a`, `022a`, `156b`) são
# tipicamente variantes promo/league cegas pra pokemontcg.io:
#   - "1st Place Pokemon League" / "2nd Place" / "3rd Place" / "4th Place"
#   - Prerelease (alguns sets)
#   - Staff variants (Champion's Festival, World Championships)
# Pokemontcg.io agrega TODAS sob o número-base (ex `153`) com o preço da
# variante mais cara → margem inflada 5-30× quando seller CT está vendendo
# a promo barata. Caso histórico operador: Lusamine sm5/153a — scanner
# pegou main set Lusamine ($160) mas seller CT vende 1st Place ($13.77).
#
# Estratégia: REVISAR forçado (operador valida via Link TCG → variant
# selector visual). NÃO marcar NÃO automático pq alguns alpha suffixes
# legítimos existem em sets vintage (Topps Movie, Black Star Promos
# numerados como `TVR_1a`, etc — fora do escopo CT).
#
# NÃO confundir com TG##: TG## tem letras ANTES do número, então a regex
# `^\d+[a-zA-Z]+` não casa. TG## fica com sua flag separada.
ALPHA_SUFFIX_RE = re.compile(r'^\d+[a-zA-Z]+', re.IGNORECASE)

# ─── Unsupported sets filter (v2.2 Layer 3 bug-hunt 2026-05-18) ──────────────
# Sets onde pokemontcg.io tem cobertura ruim OU os codes do CT divergem de
# forma que mesmo com Layer 1 (strict set match) acabamos pegando o set
# errado. Quando um listing CT vem de um destes sets, qualquer Decisão
# automática vira REVISAR_MANUAL — operador valida preço TCG manual antes
# de comprar.
#
# Lista canônica (operador 2026-05-18 pós-debug weekly v2.6):
#   - Promo/legacy sets sem alias em pokemontcg.io: phs, pplf, pupr, xybsp
#   - World Championship decks (não-tradeable na ptcg.io): wcd2004/06/07
#   - Theme deck exclusives sem reverse map: deckexclusives, xytkn
#   - Pokemon TCG Classic reprint set: clb (matched Team Rocket originals)
#   - McDonald's promo sets: m24
UNSUPPORTED_SETS = {
    "clb", "wcd2004", "wcd2006", "wcd2007", "deckexclusives",
    "xytkn", "m24", "phs", "pplf", "xybsp",
}

def _extract_set_code_from_label(set_label: str | None) -> str:
    """Set label vem como 'Jungle (ju)' ou direto 'ju'. Extrai código entre
    parênteses se presente, senão devolve label normalizado."""
    if not set_label:
        return ""
    s = str(set_label).strip()
    m = re.search(r"\(([^)]+)\)\s*$", s)
    if m:
        return m.group(1).strip().lower()
    return s.lower()

# ─── Decisao mecanica + Porque ────────────────────────────────────────────────
@dataclass
class DecisionConfig:
    min_net_margin: float = 0.30        # corte do dono: 30% de margem sobre a VENDA (nao ROI)
    min_lucro_liq: float = 50.0          # R$50 lucro minimo pra COMPRA
    revisar_min_net: float = 0.20        # 20-30% → REVISAR
    min_sales_90d: int = 5               # liquidez: vendas ungraded em 90d (valor do dono, configuravel)
    min_sales_30d: int = 1               # liquidez: ao menos 1 venda em 30d (idem)
    max_ref_age_days: float = 7.0        # idade maxima da referencia (DEFAULT provisorio; o valor definitivo e do dono)
    costs: Costs = Costs()               # Hub 6% + frete R$0,50/carta; demais = nao informado

    @property
    def hub_fee_rate(self):              # compat: leitura do Hub dos custos
        return self.costs.hub_fee_rate


def _num(v):
    """float ou None (NaN/vazio/nao numerico → None)."""
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _is_reverse_offer(row) -> bool:
    """Unica fonte da decisao: pricecharting_ref.finish_status (variante OU acabamento)."""
    return any(pricecharting_ref.finish_status(row.get(k)) == pricecharting_ref.FINISH_REVERSE_NAO_CONFIRMAVEL
               for k in ("variant", "acabamento"))


def _truncado(v):
    """True | False | None (desconhecido: NA/NaN/None/'desconhecido'/qualquer nao-bool)."""
    return bool(v) if isinstance(v, (bool, np.bool_)) else None


_PC_STATUS_TEXT = {
    "EDICAO_NAO_INFORMADA": "edição não informada",
    "LIMITE_CONSULTAS": "limite de consultas PriceCharting (--pc-refs) esgotado antes desta referência",
}


def liquidity_verdict(row, cfg: DecisionConfig):
    """(verificada: bool, motivo). Liquidez = sinal de demanda da pagina PriceCharting da
    MESMA edicao (ungraded, sem lotes). Sem dado / pagina nao confirmada → NAO verificada.
    Acabamento: pricecharting_ref nao expoe confirmacao do acabamento da pagina; por isso
    oferta reverse nunca conta como verificada (lacuna do modulo, relatada no PR)."""
    st = str(row.get("pc_status") or "NAO_CONSULTADO")
    if st != "OK":
        why = _PC_STATUS_TEXT.get(st, st)
        mot = row.get("pc_motivo")
        if st in _PC_STATUS_TEXT and isinstance(mot, str) and mot.strip():
            why += f" ({mot.strip()})"
        return False, f"liquidez não verificada: {why}"
    if _is_reverse_offer(row):
        return False, ("liquidez não verificada: acabamento reverse não confirmável "
                       "na página PriceCharting")
    v90, v30 = _num(row.get("pc_vendas_90d")), _num(row.get("pc_vendas_30d"))
    if v90 is None or v30 is None:
        return False, "liquidez não verificada: contagens ausentes"
    trunc = _truncado(row.get("pc_truncado"))   # None = desconhecido (nunca presumido exato)
    piso = trunc is not False
    n90, n30 = int(v90), int(v30)
    pre = "≥" if piso else ""
    if n90 < cfg.min_sales_90d or n30 < cfg.min_sales_30d:
        if trunc is None:
            return False, (f"liquidez não verificada: truncamento desconhecido, pelo menos {n90} "
                           f"vendas/90d e {n30}/30d (mínimo {cfg.min_sales_90d}/90d e "
                           f"{cfg.min_sales_30d}/30d)")
        if piso:
            return False, (f"liquidez não verificada: contagem truncada, pelo menos {n90} "
                           f"vendas/90d e {n30}/30d (mínimo {cfg.min_sales_90d}/90d e "
                           f"{cfg.min_sales_30d}/30d)")
        return False, (f"liquidez baixa: {n90} vendas/90d e {n30}/30d "
                       f"(mínimo {cfg.min_sales_90d}/90d e {cfg.min_sales_30d}/30d)")
    return True, (f"liquidez {pre}{n90} vendas/90d, {pre}{n30}/30d"
                  + (" (truncamento desconhecido)" if trunc is None else ""))


def classify_decision(row, cfg: DecisionConfig, check_liquidity: bool = True):
    """Aplica regra mecanica. Retorna (decisao, porque). O chase NAO participa.
    `check_liquidity=False` so serve p/ escolher quais linhas consultar no PriceCharting."""
    sm = row.get("sem_margem_motivo")   # compute devolveu "sem margem": nunca herda numero do XLSX
    if isinstance(sm, str) and sm.strip():
        return "SEM REF", sm.strip()
    nm = row.get("net_margin", 0)
    profit = row.get("lucro_liq", 0)
    val = str(row.get("validation_status", "")).upper()
    is_tg = bool(row.get("trainer_gallery_potential_fp", False))

    if pd.isna(nm) or pd.isna(profit):
        return "NAO", "Dados insuficientes (margem/lucro ausentes)"
    # Margem negativa: nunca em tabela comercial. Vem ANTES das regras de REVISAR
    # (alpha-suffix/set sem cobertura) — era o que deixava Golduck 50a/-15% na entrega.
    if nm < 0:
        return "AUDITORIA", f"margem negativa {nm:.0%} (só registro de auditoria)"

    # v2.3 Layer 5: alpha-suffix (153a, 022a) = promo/League cega p/ pokemontcg.io.
    card_num = str(row.get("card_number") or "").strip()
    if ALPHA_SUFFIX_RE.match(card_num) and not TRAINER_GALLERY_RE.match(card_num):
        return ("REVISAR",
                f"Alpha suffix '{card_num}' — provável promo/League variant "
                f"(1st/2nd/3rd/4th Place ou Prerelease); pokemontcg.io cega "
                f"pra essas, valide via Link TCG antes")
    # v2.2 Layer 3: unsupported sets → REVISAR forçado.
    set_code = _extract_set_code_from_label(row.get("set_code"))
    if set_code in UNSUPPORTED_SETS:
        return "REVISAR", f"Set {set_code} sem cobertura confiável em pokemontcg.io — valide TCG manual"

    if is_tg:
        return "NAO", "TG##/GG## gallery potencial FP (pokemontcg.io infla 5-10x)"
    if val in ("STALE",):
        return "NAO", "Validation STALE — preço inseguro"
    if nm < cfg.revisar_min_net:
        return "NAO", f"Margem {nm:.0%} < {cfg.revisar_min_net:.0%} (abaixo do piso)"
    if nm < cfg.min_net_margin:
        return "REVISAR", f"Margem {nm:.0%} entre {cfg.revisar_min_net:.0%}-{cfg.min_net_margin:.0%} (borderline)"
    if profit < cfg.min_lucro_liq:
        return "REVISAR", f"Margem {nm:.0%} OK mas lucro R${profit:.0f} < R${cfg.min_lucro_liq:.0f}"
    if val == "MARKUP_TIER_ANOMALOUS" or val == "ANOMALOUS_MARKUP":
        return "REVISAR", f"Markup anomalo (>45%); margem {nm:.0%}"
    if val not in ("VALIDATED_REAL", "VALIDATED_MARKUP"):
        return "REVISAR", f"Validation {val or 'ausente'}; margem {nm:.0%} (preço sem checkout real)"
    if not _is_truthy_flag(row.get("compra_inclui_hub")):   # VALIDATED sem LIVE na linha = sem preço de checkout
        return "REVISAR", (f"Validation {val} mas sem preço de checkout (LIVE ausente ou não "
                           f"finito); margem {nm:.0%} sobre preço cru do scan")
    if _is_truthy_flag(row.get("variant_low_confidence")):
        return ("REVISAR",
                "Variante Baixa Confiança — preço de referência casou numa variante "
                "reverse/holo possivelmente inflada (não-holo); valide a variante via "
                "Link TCG antes de comprar")
    # Dono: sem referencia COMPATIVEL (edicao+variante exatas) nao se recomenda compra.
    # Coluna ausente (XLSX de scanner antigo) = scanner nao certificou → nao confirmada.
    if str(row.get("ref_compativel")).strip().lower() not in ("sim", "true", "1", "yes"):
        return "REVISAR", ("referência de variante/edição não certificada pelo scanner "
                           "(coluna 'Ref Compatível' ausente ou ≠ Sim)")
    # B1f: referencia velha demais (limite configuravel) nunca vira COMPRA; a margem segue exibida.
    age = _num(row.get("ref_age_dias"))
    if age is not None and age > cfg.max_ref_age_days:
        return "REVISAR", (f"referência desatualizada ({age:.0f} dias); máximo {cfg.max_ref_age_days:g}; "
                           f"margem {nm:.0%} sobre preço velho")
    if not check_liquidity:
        return "COMPRA", ""
    ok, liq = liquidity_verdict(row, cfg)
    if not ok:
        return "REVISAR", f"{liq}; margem {nm:.0%} + lucro R${profit:.0f}"
    return "COMPRA", f"margem {nm:.0%} + lucro R${profit:.0f}; {liq}"

# ─── Fundamental Score objetivo (0-100) ──────────────────────────────────────
def fundamental_score(row) -> int:
    """Score derivado de 4 metricas objetivas (operador-pedido em 2026-05-16).
    Nao usa heuristicas subjetivas (iconicidade, meta competitivo, etc)."""
    score = 0
    # Chase tier: FORA do score (B1b) — é só informativo (coluna `Chase Tier`), nunca ordena
    # nem ranqueia linhas.
    # Net margin (peso 20)
    nm = row.get("net_margin", 0)
    if nm >= 0.40: score += 20
    elif nm >= 0.30: score += 15
    elif nm >= 0.25: score += 10
    elif nm >= 0.20: score += 5
    # Lucro absoluto (peso 25)
    p = row.get("lucro_liq", 0)
    if p >= 200: score += 25
    elif p >= 100: score += 18
    elif p >= 50: score += 12
    elif p >= 25: score += 6
    # Validation status (peso 15)
    val = str(row.get("validation_status", "")).upper()
    if val == "VALIDATED_REAL": score += 15
    elif val == "VALIDATED_MARKUP": score += 10
    elif val == "ANOMALOUS_MARKUP": score += 3
    return min(score, 100)

# ─── Column aliases (preserva v1.5 fixes) ────────────────────────────────────
COLUMN_ALIASES = {
    "card_name": ["card_name","name","card","Card","Name","Card Name","Carta"],
    "card_number": ["card_number","number","Number","Card Number","card_no","No","Numero","Nº","No."],
    "set_code": ["set_code","set","Set","expansion","Expansion","set_id"],
    "rarity": ["rarity","Rarity","Raridade"],
    "variant": ["variant","Variant","version","Version","foil","Foil","Variante"],
    "condition": ["condition","Condition","cond","Cond","Condicao","Condição"],
    "language": ["language","Language","lang","Lang","Idioma"],
    "seller": ["seller","Seller","seller_name"],
    "live_brl": ["live_brl","LIVE R$","LIVE R$ (real)","live_price_brl"],
    "markup_pct": ["markup_pct","Markup %","markup_percent","markup"],
    "markup_tier": ["markup_tier","Markup Tier","tier"],
    "validation_status": ["validation_status","Validation Status","valid_status","status"],
    "reference_price_brl": ["reference_price_brl","TCG Market (BRL)","TCG R$","TCG Market (R$)"],
    # Preço de referência TCGPlayer na MOEDA ORIGINAL (USD). Usado só na tabela
    # de entrega no chat (colunas "CT US$"/"TCG US$"). O raw do scanner grava
    # "TCG Market (USD)"; pode faltar em provider != pokemontcg → fallback FX.
    "reference_price_usd": ["reference_price_usd","TCG Market (USD)","TCG USD","TCG US$","tcg_market_usd"],
    "net_margin": ["net_margin","Net Margin % REAL","Net Margin %","Net REAL"],
    "lucro_liq": ["lucro_liq","Lucro R$ REAL","Lucro REAL","Lucro Liq (R$)","Net Profit (R$)"],
    "link_ct": ["link_ct","Link CT","Link CardTrader","CardTrader URL","CardTrader Link","Link"],
    "quantity": ["quantity","Quantity","qty","estoque","Qtd"],
    # v2.7.1 postprocess (2026-05-18): URL TCGPlayer da carta exata
    # matched no pokemontcg.io. Operador valida variante (ex Lusamine 1st Place
    # vs normal) antes de comprar. None aceitável (não-pokemontcg providers).
    "link_tcg": ["link_tcg","Link TCG","tcg_url","TCG URL","TCGPlayer URL","TCGPlayer Link"],
    # v2.24 (2026-06-26): sinal "Variante Baixa Confiança" do scanner ("Sim"/"").
    # Lê o flag de baixa confiança de variante (v2.18 holo/unlimited não-holo +
    # v2.24 reverse-outlier) pra forçar REVISAR — fim do "clean COMPRA" em linhas
    # com âncora de variante suspeita.
    # P1: colunas do contrato D1.8 (podem faltar em XLSX antigo) + chase do scanner
    "edicao": ["edicao","Edição","Edicao"],
    "acabamento": ["acabamento","Acabamento"],
    "ref_compativel": ["ref_compativel","Ref Compatível","Ref Compativel"],
    "chase_tier": ["chase_tier","Chase Tier"],
    # B1b: fonte e data da referência (a data é a do DADO quando a fonte expõe)
    "price_source": ["price_source","Fonte Preço","Fonte Preco"],
    "ref_data_at": ["ref_data_at","Data Ref.","Ref. Data/Hora"],   # antigo: hora da busca ("buscado em")
    "ref_data_label": ["ref_data_label","Rótulo Data Ref.","Rotulo Data Ref."],
    "ref_swap": ["ref_swap","Troca de Referência","Troca de Referencia"],   # B1f: fonte principal velha trocada pelo tcgcsv
    "variant_low_confidence": ["variant_low_confidence","Variante Baixa Confiança","Variante Baixa Confianca","low_confidence_variant"],
}


def _is_truthy_flag(v) -> bool:
    """v2.24: interpreta o valor da coluna "Variante Baixa Confiança" do XLSX.
    O scanner grava "Sim"/"" (string); aceita também bool/1/true por robustez.
    NaN / vazio → False."""
    if v is None:
        return False
    try:
        if isinstance(v, float) and pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("sim", "true", "1", "yes", "y")

def detect_column(df, logical):
    aliases = COLUMN_ALIASES.get(logical, [logical])
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for a in aliases:
        if a in df.columns: return a
        if a.lower() in cols_lower: return cols_lower[a.lower()]
    return None

def normalize_columns(df):
    rename = {}
    for logical in COLUMN_ALIASES:
        actual = detect_column(df, logical)
        if actual: rename[actual] = logical
    return df.rename(columns=rename)

# ─── Hyperlink helper (preservado de v1.5) ────────────────────────────────────
HYPERLINK_FONT = Font(color="0563C1", underline="single")

def apply_card_hyperlinks(ws, df):
    """Aplica hyperlink ativo em Carta → Link CT, e na própria célula Link TCG.

    v2.7.1 (postprocess 2026-05-18): Link TCG (URL TCGPlayer) ganha
    hyperlink no próprio texto (operador clica diretamente). Distinção
    de design vs Link CT: Carta vira link clicável apontando pro CT
    (workflow de compra primário); Link TCG é texto URL clicável
    (workflow de validação de variante secundário).
    """
    cols = list(df.columns)
    # Carta → Link CT
    if "Carta" in cols and "Link CT" in cols:
        carta_idx = cols.index("Carta") + 1
        link_idx = cols.index("Link CT") + 1
        for ri in range(2, len(df) + 2):
            url = ws.cell(row=ri, column=link_idx).value
            if isinstance(url, str) and url.startswith("http"):
                c = ws.cell(row=ri, column=carta_idx)
                c.hyperlink = url
                c.font = HYPERLINK_FONT
    # Link TCG → célula própria (URL clicável)
    if "Link TCG" in cols:
        tcg_idx = cols.index("Link TCG") + 1
        for ri in range(2, len(df) + 2):
            cell = ws.cell(row=ri, column=tcg_idx)
            v = cell.value
            if isinstance(v, str) and v.startswith("http"):
                cell.hyperlink = v
                cell.font = HYPERLINK_FONT
    # Preço CT → Link CT (clicar no preço abre a página do card no CT pra conferir)
    if "Preço CT (R$)" in cols and "Link CT" in cols:
        price_idx = cols.index("Preço CT (R$)") + 1
        link_idx = cols.index("Link CT") + 1
        for ri in range(2, len(df) + 2):
            url = ws.cell(row=ri, column=link_idx).value
            if isinstance(url, str) and url.startswith("http"):
                c = ws.cell(row=ri, column=price_idx)
                c.hyperlink = url
                c.font = HYPERLINK_FONT
    # TCG (R$) → Link TCG (clicar no preço abre a página TCGplayer pra conferir)
    if "TCG (R$)" in cols and "Link TCG" in cols:
        tprice_idx = cols.index("TCG (R$)") + 1
        link_idx = cols.index("Link TCG") + 1
        for ri in range(2, len(df) + 2):
            url = ws.cell(row=ri, column=link_idx).value
            if isinstance(url, str) and url.startswith("http"):
                c = ws.cell(row=ri, column=tprice_idx)
                c.hyperlink = url
                c.font = HYPERLINK_FONT

# ─── Main pipeline ────────────────────────────────────────────────────────────
DECISAO_FILL = {
    "COMPRA":  PatternFill("solid", fgColor="C6EFCE"),
    "REVISAR": PatternFill("solid", fgColor="FFEB9C"),
    "NAO":     PatternFill("solid", fgColor="F4CCCC"),
}
CHASE_FILL = {
    "TOP":    PatternFill("solid", fgColor="A9D08E"),
    "MID":    PatternFill("solid", fgColor="FFE699"),
    "MODEST": PatternFill("solid", fgColor="F8CBAD"),
    "BULK":   PatternFill("solid", fgColor="D9D9D9"),
}

def _recompute_margin_with_fee(df: pd.DataFrame, costs: Costs | None = None,
                               drift_threshold_pp: float = 0.005) -> pd.DataFrame:
    """Margem por linha = ct_economics.compute (UNICA conta; nenhuma formula inline aqui).

    net_margin = margem_venda = (ref - compra)/ref  (alimenta o corte e a coluna Margem %)
    lucro_liq  = lucro_bruto  = ref - compra
    + roi_aquisicao (informativo), lucro/margem/roi LIQUIDOS PARCIAIS (Hub 6% + frete
    R$0,50/carta; custos nao informados listados em `liquida_status`).

    `compra_inclui_hub` (coluna, True/False por linha) decide se o Hub e aplicado: o preco
    de checkout (LIVE R$ real) ja embute o Hub; o preco cru do scan (Scan R$ raw) nao.
    Sem live_brl/ref validos a linha fica SEM margem e SEM lucro (NaN) com o motivo do
    compute em `sem_margem_motivo` → decisao "SEM REF"; nunca herda numero do input.
    """
    costs = costs if costs is not None else Costs()
    n = len(df)
    df["margin_source"] = "input"
    df["sem_margem_motivo"] = None
    for c in ("live_brl", "reference_price_brl"):
        if c not in df.columns:
            df[c] = float("nan")   # coluna ausente = dado ausente: compute devolve o motivo
    if "compra_inclui_hub" not in df.columns:
        df["compra_inclui_hub"] = False
    for c in ("roi_aquisicao", "lucro_liquido_parcial", "margem_liquida_parcial",
              "roi_liquido_parcial"):
        df[c] = float("nan")
    df["liquida_status"] = "sem cálculo (compra/referência inválida)"
    if "net_margin" not in df.columns:
        df["net_margin"] = float("nan")
    if "lucro_liq" not in df.columns:
        df["lucro_liq"] = float("nan")
    df["net_margin"] = pd.to_numeric(df["net_margin"], errors="coerce")
    df["lucro_liq"] = pd.to_numeric(df["lucro_liq"], errors="coerce")
    live = pd.to_numeric(df["live_brl"], errors="coerce")
    ref = pd.to_numeric(df["reference_price_brl"], errors="coerce")
    n_drift, max_drift = 0, 0.0
    cols = {c: df[c].tolist() for c in ("net_margin", "lucro_liq", "roi_aquisicao",
            "lucro_liquido_parcial", "margem_liquida_parcial", "roi_liquido_parcial",
            "liquida_status", "margin_source", "sem_margem_motivo")}
    hub = df["compra_inclui_hub"].astype(bool).tolist()
    for pos in range(n):
        eco = compute_economics(ref.iat[pos], live.iat[pos], compra_inclui_hub=hub[pos],
                                costs=costs)
        if not eco.tem_margem:
            # Sem margem calculavel: a linha NAO herda margem/lucro do XLSX (dado nao presumido).
            cols["net_margin"][pos] = cols["lucro_liq"][pos] = float("nan")
            cols["margin_source"][pos] = "sem_margem"
            cols["sem_margem_motivo"][pos] = eco.sem_margem_motivo
            continue
        old = cols["net_margin"][pos]
        drift = abs(old - eco.margem_venda) / max(1.0, abs(eco.margem_venda)) if pd.notna(old) else 0.0  # relativo: margens negativas gigantes vem arredondadas do scanner
        if drift > drift_threshold_pp:
            n_drift += 1
            max_drift = max(max_drift, drift)
        cols["margin_source"][pos] = ("recomputed" if (pd.isna(old) or drift > drift_threshold_pp)
                                      else "input")
        cols["net_margin"][pos] = eco.margem_venda
        cols["lucro_liq"][pos] = eco.lucro_bruto
        cols["roi_aquisicao"][pos] = eco.roi_aquisicao
        cols["lucro_liquido_parcial"][pos] = eco.lucro_liquido
        cols["margem_liquida_parcial"][pos] = eco.margem_liquida_venda
        cols["roi_liquido_parcial"][pos] = eco.roi_liquido_aquisicao
        cols["liquida_status"][pos] = (
            "DEFINITIVA" if eco.liquida_definitiva else
            "PARCIAL — não informados: " + ", ".join(eco.custos_nao_informados))
    for c, v in cols.items():
        df[c] = v
    if n_drift:
        print(f"[postprocess P1] WARNING: margem do input divergia de ct_economics em "
              f"{n_drift}/{n} rows (drift máx {max_drift * 100:.2f}pp). Usando ct_economics.")
    return df


def _chase_for_row(r):
    """Chase tier INFORMATIVO: coluna do scanner quando existir; senao ct_chase."""
    v = r.get("chase_tier")
    if isinstance(v, str) and v.strip() and v.strip().lower() != "nan":
        return v.strip()
    return classify_chase_tier(r.get("rarity"), r.get("card_number"), r.get("markup_tier"))


def enrich_df(raw_df: pd.DataFrame, hub_fee_rate: float | None = None,
              costs: Costs | None = None) -> pd.DataFrame:
    """`costs` (ou `hub_fee_rate` por compat) so afeta as colunas LIQUIDAS parciais;
    margem_venda (corte) nao depende de custos."""
    if costs is None:
        costs = Costs() if hub_fee_rate is None else Costs(hub_fee_rate=hub_fee_rate)
    df = normalize_columns(raw_df).copy()
    # v2.22: fallback near-miss — preenche live_brl/net_margin do SCAN onde o REAL falta.
    # P1: marca QUAL preco cada linha usa (checkout ja embute o Hub; scan cru nao).
    scan_brl_col = next((c for c in raw_df.columns if str(c).strip() == "Scan R$ (raw)"), None)
    scan_net_col = next((c for c in raw_df.columns if str(c).strip() == "Net Margin % (scan)"), None)
    if "live_brl" in df.columns:
        df["live_brl"] = pd.to_numeric(df["live_brl"], errors="coerce")
        df["compra_inclui_hub"] = df["live_brl"].notna()
    else:
        df["compra_inclui_hub"] = False
    if scan_brl_col is not None:
        if "live_brl" not in df.columns:
            df["live_brl"] = pd.to_numeric(raw_df[scan_brl_col], errors="coerce")
        else:
            df["live_brl"] = df["live_brl"].fillna(pd.to_numeric(raw_df[scan_brl_col], errors="coerce"))
    if scan_net_col is not None:
        scan_net = pd.to_numeric(raw_df[scan_net_col], errors="coerce")
        if "net_margin" not in df.columns:
            df["net_margin"] = scan_net
        else:
            df["net_margin"] = pd.to_numeric(df["net_margin"], errors="coerce").fillna(scan_net)
    df = _recompute_margin_with_fee(df, costs=costs)
    # TG##/GG## gallery flag (Trainer + Galarian Gallery — mesma inflação pokemontcg.io)
    if "card_number" in df.columns:
        df["trainer_gallery_potential_fp"] = df["card_number"].astype(str).str.match(r"^(?:TG|GG)\d+", case=False, na=False)
    else:
        df["trainer_gallery_potential_fp"] = False
    df["chase_tier"] = df.apply(_chase_for_row, axis=1)   # so informativo
    df["fundamental_score"] = df.apply(fundamental_score, axis=1)
    return df

def _combine_name_number(df: pd.DataFrame) -> pd.DataFrame:
    """Junta card_name + card_number numa célula só, formato MYP-style.

    PR-K (2026-05-29) — alinhamento com MYP scanner:
      - Com total mapeado: "Plusle (193/197)" (parens + total do set)
      - Sem total mapeado: "Plusle (193)" (parens só, sem total)

    ⚠️ CONTRATO IMPORTANTE (PR-L 2026-05-30): chamado em build_deals_sheet
    e build_all_listings_sheet ANTES do rename. Sheets derivadas (Top 50
    Margin / Validate Manually / TCG Suspect) recebem o df JÁ TRANSFORMADO
    — card_name é "Plusle (193/182)", card_number=193 fica preservado
    separado. Filtros nessas sheets usam Nº ou Set crus, NÃO Carta texto;
    se mudar essa convenção verifique todos os build_*_sheet PR-K.
      - Sem número: "Plusle" (só nome)

    set_code é extraído da coluna 'set_code' (string como "Stellar Crown (scr)"
    ou direto "scr"). Robusto a número float ('182.0'→'182'), ausente,
    alfanumérico (TG12, SV161, 153a) e total ausente.
    """
    if "card_name" not in df.columns or "card_number" not in df.columns:
        return df
    df = df.copy()
    has_set = "set_code" in df.columns

    def _combine(row):
        name = row["card_name"]
        num = row["card_number"]
        if num is None or (isinstance(num, float) and pd.isna(num)):
            return name
        s = str(num).strip()
        if s.endswith(".0"):
            s = s[:-2]
        if not s or s.lower() == "nan":
            return name
        # Resolve total via CT_SET_TOTAL se set_code mapeado
        total = None
        if has_set:
            code = _extract_set_code_from_label(row.get("set_code"))
            total = CT_SET_TOTAL.get(code)
        if total is not None:
            return f"{name} ({s}/{total})"
        return f"{name} ({s})"

    df["card_name"] = df.apply(_combine, axis=1)
    return df

MARGIN_COL = "Margem venda %"   # (ref - compra)/ref — a MESMA do corte; nao e "net"


def _decide(df: pd.DataFrame, cfg: DecisionConfig) -> pd.DataFrame:
    """Anexa decisao/porque (classify_decision) — unico ponto que decide. write_report
    decide UMA vez (depois de anexar PC/DH) e as demais funcoes reaproveitam as colunas."""
    df = df.copy()
    if {"decisao", "porque"} <= set(df.columns):
        return df
    res = [classify_decision(r, cfg) for _, r in df.iterrows()]
    df["decisao"] = [r[0] for r in res]
    df["porque"] = [r[1] for r in res]
    return df


def _sales_text(v, truncado) -> str:
    """Contagem de vendas PC → '7' | '≥30' (piso, pagina truncada) | '—' (sem dado)."""
    n = _num(v)
    if n is None:
        return "—"
    return f"{'≥' if truncado is True or truncado == 'desconhecido' else ''}{int(n)}"


_SHEET_COLS = ["decisao", "porque", "ref_age_dias", "ref_desatualizada", "ref_swap", "chase_tier", "fundamental_score",
               "dh_score",  # 2ª opinião DoubleHolo (só se --doubleholo; senão ausente)
               "pc_median_usd", "pc_n_sales", "pc_url",  # Ref PC (só se --pc-refs)
               "pc_status", "edicao", "acabamento",
               "set_code", "card_name", "card_number", "language",
               "live_brl", "reference_price_brl", "net_margin", "lucro_liq",
               "roi_aquisicao", "lucro_liquido_parcial", "margem_liquida_parcial",
               "roi_liquido_parcial", "liquida_status", "compra_inclui_hub",
               "pc_vendas_30d", "pc_vendas_90d", "pc_valor_90d_usd", "pc_ultima_venda",
               "validation_status", "seller", "link_ct", "link_tcg"]
_SHEET_RENAME = {
    "decisao": "Decisão", "porque": "Porque", "chase_tier": "Chase Tier (info)",
    "fundamental_score": "Score", "dh_score": "DH", "set_code": "Set", "card_name": "Carta",
    "pc_median_usd": "Ref PC (US$)", "pc_n_sales": "PC Nº Vendas", "pc_url": "Link PC",
    "pc_status": "PC Status", "edicao": "Edição", "acabamento": "Acabamento",
    "card_number": "Nº", "language": "Idioma", "live_brl": "Preço CT (R$)",
    "reference_price_brl": "TCG (R$)", "net_margin": MARGIN_COL,
    "lucro_liq": "Lucro bruto (R$)", "roi_aquisicao": "ROI aquisição % (info)",
    "lucro_liquido_parcial": "Lucro líquido PARCIAL (R$)",
    "margem_liquida_parcial": "Margem líquida PARCIAL %",
    "roi_liquido_parcial": "ROI líquido PARCIAL %", "liquida_status": "Líquida: custos",
    "compra_inclui_hub": "Preço inclui Hub",
    "pc_vendas_30d": "Vendas 30d", "pc_vendas_90d": "Vendas 90d",
    "pc_valor_90d_usd": "Valor 90d (US$)", "pc_ultima_venda": "Última venda",
    "validation_status": "Validação",
    "seller": "Seller", "link_ct": "Link CT", "link_tcg": "Link TCG",
}


def _sheet_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "pc_vendas_90d" in df.columns:   # texto com "≥" quando a contagem e piso
        trunc = df["pc_truncado"] if "pc_truncado" in df.columns else [None] * len(df)
        for c in ("pc_vendas_30d", "pc_vendas_90d"):
            df[c] = [_sales_text(v, t) for v, t in zip(df[c], trunc)]
    cols = [c for c in _SHEET_COLS if c in df.columns]
    df = _combine_name_number(df[cols])
    return df.rename(columns=_SHEET_RENAME)


def build_deals_sheet(df: pd.DataFrame, cfg: DecisionConfig) -> pd.DataFrame:
    """Sheet principal: deals com Decisao mecanica (COMPRA + REVISAR, ordenado por lucro)."""
    df = _decide(df, cfg)
    deals = df[df["decisao"].isin(["COMPRA", "REVISAR"])].copy()
    if "lucro_liq" in deals.columns:
        deals = deals.sort_values("lucro_liq", ascending=False)
    return _sheet_frame(deals)


def build_all_listings_sheet(df: pd.DataFrame, cfg: DecisionConfig) -> pd.DataFrame:
    """Sheet completa: TUDO com Decisao + Chase (informativo) + Score (inclui NAO/AUDITORIA)."""
    return _sheet_frame(_decide(df, cfg))


def build_auditoria_sheet(df: pd.DataFrame, cfg: DecisionConfig) -> pd.DataFrame:
    """Oportunidades de margem NEGATIVA: fora da tabela comercial, so aqui (auditoria)."""
    d = _decide(df, cfg)
    d = d[d["decisao"] == "AUDITORIA"]
    if "net_margin" in d.columns:
        d = d.sort_values("net_margin")
    return _sheet_frame(d)


def build_top50_margin_sheet(all_listings: pd.DataFrame) -> pd.DataFrame:
    """PR-K: Top 50 listings por margem desc (ranking puro do universo All Listings).
    Recebe DataFrame JÁ na forma final (mesmas colunas das outras sheets).
    Aceita ranking puro: qualquer Decisão (inclusive NÃO) — operador vê o teto."""
    if all_listings.empty or MARGIN_COL not in all_listings.columns:
        return all_listings.head(0)
    return all_listings.sort_values(MARGIN_COL, ascending=False).head(50)


def build_validate_manually_sheet(all_listings: pd.DataFrame) -> pd.DataFrame:
    """PR-K: listings que pedem revisão manual via heurísticas:
      - Carta TG##/GG## (Trainer + Galarian Gallery, ^(?:TG|GG)\\d+) no Nº
      - Validação ∈ {STALE, PRICE_CHANGED, API_ERROR}
      - Set vintage suspect (lc, ba-20, ba-22)
      - Margem > 200% (provável FP)
    """
    if all_listings.empty:
        return all_listings
    df = all_listings.copy()
    mask = pd.Series(False, index=df.index)
    # TG##/GG## gallery
    if "Nº" in df.columns:
        mask = mask | df["Nº"].astype(str).str.match(r"^(?:TG|GG)\d+", case=False, na=False)
    # Validation flags
    if "Validação" in df.columns:
        val_up = df["Validação"].astype(str).str.upper()
        mask = mask | val_up.isin({"STALE", "PRICE_CHANGED", "API_ERROR"})
    # Vintage suspect set
    if "Set" in df.columns:
        codes = df["Set"].astype(str).apply(_extract_set_code_from_label)
        mask = mask | codes.isin(VINTAGE_SUSPECT_SETS)
    # Margem extrema
    if MARGIN_COL in df.columns:
        nm = pd.to_numeric(df[MARGIN_COL], errors="coerce")
        mask = mask | nm.gt(EXTREME_NET_PCT)
    return df[mask].sort_values(MARGIN_COL, ascending=False) if MARGIN_COL in df.columns else df[mask]


def build_tcg_suspect_sheet(all_listings: pd.DataFrame) -> pd.DataFrame:
    """PR-K: listings cujo preço TCG parece inflado (provável per-expansion bug ou
    vintage reverseHolofoil inflation):
      - TCG (R$) > 10× mediana TCG do mesmo Set (proxy de inflação per-blueprint)
      - Set vintage não-coberto bem por pokemontcg.io (mesmo critério)
    """
    if all_listings.empty or "TCG (R$)" not in all_listings.columns:
        return all_listings.head(0)
    df = all_listings.copy()
    tcg = pd.to_numeric(df["TCG (R$)"], errors="coerce")
    mask = pd.Series(False, index=df.index)
    # 10× mediana por Set
    if "Set" in df.columns:
        med = tcg.groupby(df["Set"]).transform("median")
        mask = mask | (tcg > med * 10)
        # Vintage set heuristic
        codes = df["Set"].astype(str).apply(_extract_set_code_from_label)
        mask = mask | codes.isin(VINTAGE_SUSPECT_SETS)
    return df[mask].sort_values(MARGIN_COL, ascending=False) if MARGIN_COL in df.columns else df[mask]


def bucket_counts(df: pd.DataFrame, cfg: DecisionConfig, extra_blocks: dict | None = None) -> dict:
    """Contabilidade unica: cada linha de entrada cai em EXATAMENTE um balde.
    COMPRA+REVISAR = tabela comercial; NAO = abaixo do corte/rejeitada; AUDITORIA = margem
    negativa; SEM_REF = compute nao deu margem (bloco proprio); extras = abas 'Sem preço'/
    'Sem Ref Compatível' (sem margem). Soma == entrada."""
    if "decisao" in df.columns:
        dec = df["decisao"]
    else:
        dec = df.apply(lambda r: classify_decision(r, cfg)[0], axis=1) if len(df) else pd.Series([], dtype=str)
    out = {k: int((dec == k).sum()) for k in ("COMPRA", "REVISAR", "NAO", "AUDITORIA")}
    out["SEM_REF"] = int((dec == "SEM REF").sum())   # sem margem calculavel (compra/referencia invalida)
    out["EXTRAS"] = {k: len(v) for k, v in (extra_blocks or {}).items()}
    out["ENTRADA"] = len(df) + sum(out["EXTRAS"].values())
    return out


def build_summary(df: pd.DataFrame, cfg: DecisionConfig, extra_blocks: dict | None = None,
                  scan_stats: dict | None = None) -> pd.DataFrame:
    c = bucket_counts(df, cfg, extra_blocks)
    total = len(df)
    pct = lambda n: f"{n} ({n / total * 100:.1f}%)" if total else 0  # noqa: E731
    d = _decide(df, cfg)
    lucro_compra = d.loc[d["decisao"] == "COMPRA", "lucro_liq"].sum() if "lucro_liq" in d.columns else 0
    k = cfg.costs
    st = scan_stats or {}
    origin = []
    for lbl, key in (("Ofertas buscadas (CardTrader, bruto da API: todos os idiomas e condições, antes dos filtros)", "listings_fetched"),
                     ("Ofertas após filtros", "listings_after_filters")):
        v = st.get(key)
        try:
            origin.append((lbl, int(float(v))))
        except (TypeError, ValueError):
            origin.append((lbl, "não informado (XLSX sem aba Stats)"))
    if st.get("filtros_aplicados") is not None:
        origin.append(("Filtros aplicados", str(st.get("filtros_aplicados"))))
    if str(st.get("saude_fonte_principal") or "").strip() not in ("", "nan"):
        origin.append(("Fonte principal de preço", str(st.get("saude_fonte_principal"))))
    for lbl, key in (("--chase-only descartou", "skipped_non_chase"),
                     ("--opportunities-only descartou", "opportunities_only_descartadas")):
        try:
            if int(float(st.get(key) or 0)) > 0:
                origin.append((lbl, int(float(st[key]))))
        except (TypeError, ValueError):
            pass
    rows = [
        *origin,
        ("Linhas neste relatório (precificadas + sem preço + sem ref. compatível)", total),
        ("Total deals exportados (COMPRA + REVISAR)", c["COMPRA"] + c["REVISAR"]),
        ("COMPRA", pct(c["COMPRA"])),
        ("REVISAR (zona cinza / liquidez não verificada)", pct(c["REVISAR"])),
        ("NÃO", pct(c["NAO"])),
        ("AUDITORIA (margem negativa — fora da tabela)", pct(c["AUDITORIA"])),
        ("SEM REFERÊNCIA (sem margem calculável — bloco à parte)", pct(c["SEM_REF"])),
        *[(f"Bloco extra: {n}", q) for n, q in c["EXTRAS"].items()],
        ("Lucro bruto potencial (COMPRA)", f"R$ {lucro_compra:,.0f}"),
        ("", ""),
        ("Corte COMPRA — margem sobre a VENDA", f"≥ {cfg.min_net_margin:.0%}"),
        ("Corte COMPRA — lucro bruto", f"≥ R$ {cfg.min_lucro_liq:.0f}"),
        ("Corte COMPRA — liquidez (PriceCharting, ungraded)",
         f"≥ {cfg.min_sales_90d} vendas/90d e ≥ {cfg.min_sales_30d}/30d"),
        ("Chase tier", "só informativo (nunca decide)"),
        ("Corte REVISAR — margem", f"≥ {cfg.revisar_min_net:.0%}"),
        ("", ""),
        ("Math: margem (corte)", "(referência − compra) / referência  [ct_economics.margem_venda]"),
        ("Math: ROI aquisição (info)", "(referência − compra) / compra — nunca usado no corte"),
        ("Math: custos", f"Hub {k.hub_fee_rate:.0%} (só se o preço é cru; checkout já embute) + "
                         f"frete R$ {k.frete_compra_brl:.2f}/carta; demais = não informados → líquida PARCIAL"),
    ]
    return pd.DataFrame(rows, columns=["Métrica", "Valor"])


def style_sheet(ws, df, decisao_col=None, chase_col=None):
    # Header style
    for ci in range(1, len(df.columns) + 1):
        c = ws.cell(row=1, column=ci)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    # Color rows by Decisao
    if decisao_col and decisao_col in df.columns:
        ci = list(df.columns).index(decisao_col) + 1
        for ri in range(2, len(df) + 2):
            cell = ws.cell(row=ri, column=ci)
            if cell.value in DECISAO_FILL:
                cell.fill = DECISAO_FILL[cell.value]
                cell.font = Font(bold=True)
    # Color Chase Tier column
    if chase_col and chase_col in df.columns:
        ci = list(df.columns).index(chase_col) + 1
        for ri in range(2, len(df) + 2):
            cell = ws.cell(row=ri, column=ci)
            if cell.value in CHASE_FILL:
                cell.fill = CHASE_FILL[cell.value]
                cell.font = Font(bold=True)
    # Column widths
    for ci, cn in enumerate(df.columns, 1):
        try:
            vals = [str(v) for v in df.iloc[:50, ci-1].tolist()]
        except Exception:
            vals = []
        ml = max([len(str(cn))] + [len(v) for v in vals]) if vals else len(str(cn))
        ws.column_dimensions[get_column_letter(ci)].width = min(ml + 2, 50)
    # Hyperlinks na coluna Carta
    apply_card_hyperlinks(ws, df)

def _safe_val(val):
    """Módulo-level (PR-L 2026-05-30, CT-M4): NaN/None → None (openpyxl
    escreve célula vazia, evita 'nan' literal). Aplicado em TODAS as
    sheets (Deals/All Listings/PR-K/Summary) pra uniformidade defensiva."""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


# ─── Tabela de ENTREGA no chat (markdown, links clicáveis) ───────────────────
# Formato aprovado pelo operador 2026-06-09 (paridade com o scanner COMC):
# entrega = tabela markdown no chat, NÃO planilha. CSV/XLSX seguem com colunas
# separadas + URLs cruas; só esta tabela compõe Carta (nome+número) e Links.
#
#   | # | Margem % | CT US$ | TCG US$ | Dif | Carta | Set | Raridade | Cond | Qtd | Flag | Links |
#
# Coluna Links = "[oferta](url_ct) · [TCG](url_tcg)" — o link da oferta aponta
# pra página do CardTrader (de preferência per-blueprint, preço final com markup
# — lembrar dos ~76% de falsos positivos sem validação per-blueprint); o link TCG
# é o workflow canônico de validação manual do operador.
#
# Coluna Flag = sinaliza, por linha, o que a regra MECÂNICA (classify_decision)
# concluiu: COMPRA → "" (limpo); REVISAR → "validar manual" (zona cinza /
# suspeito de margem inflada — TG##, alpha-suffix promo/league, set sem cobertura
# confiável, markup anômalo, etc.). Reusa a MESMA classificação do XLSX, não
# duplica regra. NÃO é recomendação de compra — é o flag de cautela que o
# operador usa pra decidir o que conferir no Link TCG antes.
#
# Margem é a net_margin já enriquecida = margem BRUTA (regra 2026-06-06, sem Hub
# fee). Esta função NÃO altera threshold/filtro/classificação — só APRESENTA os
# deals que classify_decision marcou COMPRA/REVISAR (TODOS eles, até top_n).
_DELIVERY_HEADERS = [
    "#", "Margem %", "CT US$", "TCG US$", "Dif",
    "Carta", "Edição", "Acabamento", "Set", "Raridade", "Cond", "Qtd", "Vendas 30d", "Vendas 90d",
    "Fonte ref.", "Data ref.", "Flag", "Links",
]


def _cell_or_dash(v) -> str:
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) or not str(v).strip() else _md_escape(v)


def _parse_dt(at):
    """ISO -> datetime (ou None). Com fuso: convertido p/ o fuso LOCAL de quem lê."""
    from datetime import datetime as _dt
    try:
        d = _dt.fromisoformat(str(at).strip())
    except ValueError:
        return None
    return d.astimezone() if d.tzinfo else d


def _ref_date(at):
    """Data do dado de referência -> datetime naive local (date-only vira meia-noite; com fuso é
    convertida ao horário local). None se inválida."""
    s = str(at or "").strip()
    if not s or s.lower() == "nan":
        return None
    d = _parse_dt(s)
    if d is None:
        return None
    return d.replace(tzinfo=None)


def _add_ref_age(df: pd.DataFrame, scan_stats: dict | None, cfg: DecisionConfig) -> pd.DataFrame:
    """B1f: `ref_age_dias` (dias entre a data do DADO e o dia do scan; só linhas "dado de") e
    `ref_desatualizada` (marca textual quando passa do limite)."""
    df = df.copy()
    sa = (scan_stats or {}).get("scanned_at")
    base = _ref_date(sa) or datetime.now()
    ages, marks = [], []
    for _, r in df.iterrows():
        d = _ref_date(r.get("ref_data_at")) if str(r.get("ref_data_label") or "").strip() == "dado de" else None
        age = float((base.date() - d.date()).days) if d is not None else float("nan")
        ages.append(age)
        marks.append(f"referência desatualizada ({age:.0f} dias)" if age == age and age > cfg.max_ref_age_days else "")
    df["ref_age_dias"], df["ref_desatualizada"] = ages, marks
    return df


def _fmt_ref_date(label, at) -> str:
    """"dado de 2026-11-23 17:05 (UTC-03:00)" (data do DADO) ou "buscado em ..." (hora da busca,
    também o rótulo quando a coluna é a antiga "Ref. Data/Hora"). Mostra SEMPRE o fuso quando o
    valor o tem (convertido ao horário local). Nunca inventa."""
    if at is None or (isinstance(at, float) and pd.isna(at)) or not str(at).strip():
        return "—"
    lbl = "" if label is None or (isinstance(label, float) and pd.isna(label)) else str(label).strip()
    lbl = lbl or "buscado em"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(at).strip()):
        return f"{lbl} {str(at).strip()}"                       # data do dado sem hora/fuso (pokemontcg.io)
    d = _parse_dt(at)
    if d is None:
        return f"{lbl} {str(at).strip()[:16].replace('T', ' ')}"
    if d.tzinfo:
        off = d.strftime("%z")
        tz = "UTC" if off in ("+0000", "") else f"UTC{off[:3]}:{off[3:]}"
        return f"{lbl} {d.strftime('%Y-%m-%d %H:%M')} ({tz})"
    return f"{lbl} {d.strftime('%Y-%m-%d %H:%M')} (fuso não informado)"


def _sources_line(df: pd.DataFrame, scan_stats: dict | None) -> str:
    """Rodapé: fonte de cada referência, natureza do lote (tcgcsv = dump diário) e a idade do
    lote usado NESTE scan (relativa à hora do scan, não a hoje)."""
    if df is None or "price_source" not in df.columns:
        return ""
    ref_at = df["ref_data_at"] if "ref_data_at" in df.columns else None
    lbl = df["ref_data_label"] if "ref_data_label" in df.columns else None
    sa = (scan_stats or {}).get("scanned_at")
    from datetime import datetime as _dt
    ref_now = _ref_date(sa) or _dt.now()
    parts = []
    for src, g in df.groupby(df["price_source"].fillna("—").astype(str)):
        txt = f"{src}: {len(g)} linha(s)"
        if src == "tcgcsv":
            txt += " — lote diário (preço do TCGplayer congelado uma vez por dia)"
        dts = []
        if ref_at is not None:
            for k in g.index:
                lv = lbl.get(k) if lbl is not None else None
                if str(lv or "").strip() != "dado de":
                    continue
                d = _ref_date(ref_at.get(k)) if pd.notna(ref_at.get(k)) else None
                if d is not None:
                    dts.append(d)
        if dts:
            old, new = min(dts), max(dts)
            hrs = max(0.0, (ref_now - old).total_seconds() / 3600)
            age = f"{hrs:.0f} h" if hrs < 48 else f"{int((ref_now.date() - old.date()).days)} dias"

            def f(d):
                return d.strftime("%Y-%m-%d") if (d.hour, d.minute) == (0, 0) else d.strftime("%Y-%m-%d %H:%M")
            txt += f"; dado mais antigo {f(old)} (publicado há {age} no momento do scan), mais novo {f(new)}"
        else:
            txt += "; sem data do dado (só a hora da busca)"
        parts.append(txt)
    return "_Fontes das referências: " + " | ".join(parts) + "._" if parts else ""


def _read_scan_stats(input_path) -> dict:
    """Aba Stats do XLSX do scanner -> {metrica: valor}. Ausente/ilegivel -> {} (XLSX antigo)."""
    try:
        st = pd.read_excel(input_path, sheet_name="Stats", header=None)
    except Exception:
        return {}
    out = {}
    for _, r in st.iterrows():
        if len(r) >= 2 and pd.notna(r.iloc[0]):
            out[str(r.iloc[0]).strip()] = r.iloc[1]
    return out


def _origin_lines(scan_stats: dict | None, n_priced: int) -> list[str]:
    """De onde vêm os números: ofertas buscadas -> após filtros -> filtros aplicados (+ descartes)."""
    st = scan_stats or {}

    def num(k):
        v = st.get(k)
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    fetched, after = num("listings_fetched"), num("listings_after_filters")
    if fetched is None and after is None:
        return ["_Origem dos números: Ofertas buscadas: não informado (XLSX de scanner antigo, sem a aba "
                f"Stats); linhas neste relatório: {n_priced}._"]
    filt = st.get("filtros_aplicados")
    txt = f" (filtros: {filt})" if filt is not None and str(filt).strip() and str(filt) != "nan" else ""
    out = [f"_Origem dos números: Ofertas buscadas (bruto da API: todos os idiomas e condições, antes dos "
           f"filtros): {fetched if fetched is not None else '?'} → após filtros: "
           f"{after if after is not None else '?'}{txt}; linhas neste relatório (precificadas + sem preço + sem "
           f"ref. compatível): {n_priced}._"]
    sh = st.get("saude_fonte_principal")
    if sh is not None and str(sh).strip() and str(sh) != "nan":
        out.append(f"_Fonte principal de preço: {str(sh).strip()}._")
    nc, no = num("skipped_non_chase"), num("opportunities_only_descartadas")
    if nc:
        out.append(f"_--chase-only descartou {nc} oferta(s) antes da precificação (não aparecem em nenhuma aba)._")
    if no:
        out.append(f"_--opportunities-only descartou {no} oferta(s) precificada(s) abaixo do corte (não aparecem em nenhuma aba)._")
    return out


def _fmt_usd(v) -> str:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def _fmt_pct(v) -> str:
    """net_margin chega em fração (0.30 = 30%) → '30%'."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return ""


_URL_RE = re.compile(r"https?://\S", re.IGNORECASE)


def _valid_url(v) -> bool:
    """True se `v` é string http(s):// com algo depois do esquema (sem diferenciar
    maiúsculas). Critério ÚNICO da célula Links e da Flag."""
    return isinstance(v, str) and _URL_RE.match(v.strip()) is not None


def _md_links_cell(link_ct, link_tcg, link_pc=None, link_ebay=None) -> str:
    """'[oferta](url_ct) · [TCG](url_tcg)[ · [PC](url_pc)]'. Oferta e TCG são
    obrigatórios: se um faltar, a célula traz "oferta: sem link"/"TCG: sem link".

    `link_pc` (opcional, metodologia 2026-08-28): link da página PriceCharting
    usada como referência de vendas reais — EXTRA, nunca substitui os 2 links
    obrigatórios do contrato.

    URLs percent-encodadas (espaço, aspas, parênteses) sem re-encodar %XX
    existentes: em `[label](url)` o `)` cru fecha o link no primeiro
    parêntese e o wrap `<url>` não é respeitado por todo renderizador
    (oferta truncada no remote-control, operador 2026-08-04 — fix
    cross-scanner, espelho do sealed snapshot.md_link)."""
    from urllib.parse import quote
    parts = []
    ct = "" if link_ct is None else str(link_ct).strip()
    tcg = "" if link_tcg is None else str(link_tcg).strip()
    # Contrato dos 2 links: o que falta aparece EXPLÍCITO (nunca URL inventada).
    parts.append(f"[oferta]({quote(ct, safe='%/?&=:+,*')})" if _valid_url(ct)
                 else "oferta: sem link")
    parts.append(f"[TCG]({quote(tcg, safe='%/?&=:+,*')})" if _valid_url(tcg)
                 else "TCG: sem link")
    pc = "" if link_pc is None else str(link_pc).strip()
    if pc.startswith("http"):
        parts.append(f"[PC]({quote(pc, safe='%/?&=:+,*')})")
    eb = "" if link_ebay is None or (isinstance(link_ebay, float) and pd.isna(link_ebay)) else str(link_ebay).strip()
    if eb.startswith("http"):
        # v2.29: página com as vendas eBay concluídas que sustentam a Ref eBay.
        parts.append(f"[eBay]({quote(eb, safe='%/?&=:+,*')})")
    return " · ".join(parts)


def _md_escape(s) -> str:
    """Pipe quebra a tabela markdown → vira '/'. None → ''."""
    if s is None:
        return ""
    try:
        if isinstance(s, float) and pd.isna(s):
            return ""
    except (TypeError, ValueError):
        pass
    return str(s).replace("|", "/").strip()


def _set_name_from_label(set_label) -> str:
    """'Paradox Rift (par)' → 'Paradox Rift'; sem parênteses → o próprio label.
    Usado como nome do set p/ o fallback-por-nome do resolver tcgcsv."""
    if not set_label:
        return ""
    s = str(set_label).strip()
    return s.rsplit(" (", 1)[0].strip() if " (" in s else s


def attach_product_ids(df: pd.DataFrame, resolver,
                       set_col: str = "set_code", num_col: str = "card_number",
                       variant_col: str = "variant",  # canonical pós-normalize_columns (era "Variant" → nunca casava)
                       url_col: str = "link_tcg",
                       resolve_mask=None) -> int:
    """Adiciona a coluna `tcg_product_id` (str ou None) por linha — chave de join DH.

    Ordem (menos invasiva 1º): (1) se `link_tcg` já é tcgplayer.com/product/<id>
    (sets via tcgcsv — Fix(1) do scanner) usa esse id direto; (2) senão resolve
    OFFLINE via tcgcsv por (set CT, número, variante priceada) — Fix(2). Linha
    sem resolução UNÍVOCA → None (DH = '—', honesto). NÃO toca preço/margem; o
    productId é só identidade p/ link/join. `resolver=None` → só o passo (1).

    `resolve_mask` (follow-up #4): sequência booleana alinhada às linhas de `df`;
    quando passada, o passo (2) (resolver OFFLINE, que faz I/O via tcgcsv) só roda
    nas linhas marcadas True — tipicamente só as que viram deal (COMPRA/REVISAR).
    Num `--all-sets` (milhares de linhas, a maioria NÃO) isso evita o I/O nas
    linhas que nunca aparecem na entrega. O passo (1) (productId direto do link,
    SEM I/O) continua valendo p/ TODAS as linhas. `None` = resolve todas (antigo).
    """
    have_url = url_col in df.columns
    mask = list(resolve_mask) if resolve_mask is not None else None
    pids = []
    n = 0
    for pos, (_, row) in enumerate(df.iterrows()):
        pid = doubleholo_join.extract_product_id(row.get(url_col)) if have_url else None
        allow_resolve = mask is None or (pos < len(mask) and bool(mask[pos]))
        if pid is None and resolver is not None and allow_resolve:
            label = row.get(set_col)
            try:
                pid = resolver.resolve(
                    _extract_set_code_from_label(label),
                    _set_name_from_label(label),
                    row.get(num_col),
                    row.get(variant_col) if variant_col in df.columns else None,
                )
            except Exception:  # noqa: BLE001 — resolução é best-effort; falha → '—'
                pid = None
        pids.append(pid)
        if pid is not None:
            n += 1
    df["tcg_product_id"] = pids
    return n


def _delivery_resolve_mask(df: pd.DataFrame, cfg: DecisionConfig, top_md: int):
    """Máscara booleana (alinhada às linhas de `df`) das linhas que aparecem na
    ENTREGA markdown COM coluna DH — o conjunto p/ o qual vale rodar o resolver
    OFFLINE (Fix(2), que faz I/O). ESPELHA a seleção de `build_delivery_markdown`:
    os deals (COMPRA/REVISAR) quando existirem; senão (near-miss) os `top_md`
    candidatos por margem. Sem cobrir o near-miss, quando NÃO há deal o resolver
    rodaria em ZERO linhas e a tabela near-miss entregue perderia a coluna DH."""
    decisao = df.apply(lambda r: classify_decision(r, cfg)[0], axis=1)
    is_deal = decisao.isin(["COMPRA", "REVISAR"])
    if bool(is_deal.any()):
        return is_deal
    mask = pd.Series(False, index=df.index)
    if "net_margin" in df.columns and len(df):
        top_idx = df["net_margin"].sort_values(ascending=False).head(top_md if top_md else len(df)).index
        mask.loc[top_idx] = True
    else:
        mask.loc[:] = True  # sem margem p/ ordenar → não arrisca, resolve todas
    return mask


def _fmt_dh(v) -> str:
    """Nota DH (0-100) → string; None/NaN → '—' (sem dado Double Holo, honesto)."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return f"{int(round(float(v)))}"
    except (TypeError, ValueError):
        return "—"


# Referência PriceCharting (mediana de sold listings) — metodologia 2026-08-28.
# TCG US$ mais de PC_DIVERGENCE_RATIO acima (ou abaixo) da mediana PC → flag
# "PC diverge" na linha (sinal-only, espelho da coluna DH: margem/decisão intactas).
PC_DIVERGENCE_RATIO = 0.30


# Vocabulario de edicao: SO o de ct_variants (codigos ED_1ST/ED_UNL e os rotulos de _ED_LABEL,
# ex. "1st Edition"/"Unlimited"). Nao ha segunda copia nem lista de sets com 1st Edition aqui:
# quem sabe se o set tem divisao de edicao e o scanner, que emite a coluna `Edição`.
_ED_VOCAB = {**{lbl.lower(): k for k, lbl in ct_variants._ED_LABEL.items() if k != ct_variants.ED_NONE},
             ct_variants.ED_1ST: ct_variants.ED_1ST, ct_variants.ED_UNL: ct_variants.ED_UNL,
             # carta SEM divisao de edicao (rotulo proprio do scanner): para a pagina PC e a
             # pagina nao-1st, ou seja, "unl". Celula vazia continua "nao informada".
             ct_variants.ED_NONE_LABEL.lower(): ct_variants.ED_UNL}


def _row_edition(row):
    """(edicao, motivo): edicao = ED_1ST | ED_UNL | None (None = NAO informada, com motivo).
    Coluna `Edição` ausente (XLSX antigo), vazia/NaN ou fora do vocabulario → None: nunca
    presume Unlimited. Valor fora do vocabulario traz o texto original no motivo."""
    if "edicao" not in row.index:
        return None, "coluna 'Edição' ausente no XLSX (scanner antigo)"
    v = row.get("edicao")
    t = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    if not t:
        return None, "coluna 'Edição' vazia nesta linha"
    ed = _ED_VOCAB.get(t.lower())
    if ed is None:
        return None, f"valor de 'Edição' fora do vocabulário do scanner: {t!r}"
    return ed, None


def _pc_key(row, edition):
    """Uma pagina PC por (carta, set, edicao, acabamento): dedup das consultas."""
    name = pricecharting_ref.clean_card_name(row.get("card_name")).lower()
    return (name, pricecharting_ref.norm_number(row.get("card_number")),
            _extract_set_code_from_label(row.get("set_code")), edition,
            "reverse" if _is_reverse_offer(row) else "std")


_PC_COLS = ("pc_median_usd", "pc_n_sales", "pc_url", "pc_status", "pc_motivo", "pc_edicao",
            "pc_vendas_30d", "pc_vendas_90d", "pc_valor_90d_usd", "pc_ultima_venda",
            "pc_truncado", "pc_volume_rotulo")


def attach_pc_refs(df: pd.DataFrame, cfg: DecisionConfig, top_md: int,
                   limit: int, demand_resolver=None, page_fetcher=None,
                   cache_dir: str | None = None):
    """Anexa mediana PC (ungraded, sem lotes) + SINAL DE LIQUIDEZ da pagina da MESMA edicao.

    - So consulta linhas que seriam COMPRA nao fosse a liquidez (financeiramente relevantes),
      em ordem de lucro bruto decrescente: o teto de creditos Firecrawl e "quem chega
      primeiro", entao vai primeiro para as de maior valor.
    - DEDUP: linhas da mesma carta/set/edicao/acabamento = UMA consulta (alem do cache do run).
    - `limit` = maximo de consultas UNICAS. Edicao ausente → nao consulta, pc_status
      EDICAO_NAO_INFORMADA. Oferta reverse → nao consulta (acabamento nao confirmavel).
    Retorna (paginas_ok, consultas_unicas); detalhes em df.attrs['pc_stats'].
    `demand_resolver`/`page_fetcher` injetaveis p/ teste offline.
    """
    resolve = demand_resolver or pricecharting_ref.resolve_pc_demand
    fetch = page_fetcher or pricecharting_ref.fetch_page
    for c in _PC_COLS:
        df[c] = None
    df["pc_status"] = "NAO_CONSULTADO"
    keys, editions = {}, {}
    for idx, row in df.iterrows():
        ed, ed_motivo = _row_edition(row)
        editions[idx] = ed
        if ed is None:
            df.at[idx, "pc_status"] = "EDICAO_NAO_INFORMADA"
            df.at[idx, "pc_motivo"] = ed_motivo
        elif _is_reverse_offer(row):
            df.at[idx, "pc_status"] = pricecharting_ref.FINISH_REVERSE_NAO_CONFIRMAVEL
        else:
            keys[idx] = _pc_key(row, ed)
    cand = [i for i in keys
            if classify_decision(df.loc[i], cfg, check_liquidity=False)[0] == "COMPRA"]
    cand.sort(key=lambda i: -(_num(df.at[i, "lucro_liq"]) or 0.0))
    order = []
    for i in cand:
        if keys[i] not in order:
            order.append(keys[i])
    ok = served = 0
    lim = max(0, int(limit))
    cortadas = set(order[lim:])   # referencias cobertas pelo criterio mas sem orcamento de consulta
    n_lim_linhas = 0
    for idx in keys:
        if keys[idx] in cortadas and idx in cand:
            df.at[idx, "pc_status"] = "LIMITE_CONSULTAS"
            df.at[idx, "pc_motivo"] = f"limite --pc-refs {lim} esgotado ({len(order)} referências únicas)"
            n_lim_linhas += 1
    for key in order[:lim]:
        rep = next(i for i in cand if keys[i] == key)
        row = df.loc[rep]
        try:
            res = resolve(row.get("card_name"), row.get("card_number"), row.get("set_code"),
                          edition=editions[rep], cache_dir=cache_dir, variant=row.get("variant"))
        except Exception as e:  # noqa: BLE001 — falha da fonte, rotulada (nunca "0 vendas")
            res = {"pc_status": "INDISPONIVEL_REDE", "pc_motivo": f"{type(e).__name__}: {e}"[:120]}
        med = n_med = None
        if res.get("pc_status") == "OK" and res.get("pc_url"):
            try:
                med, n_med = pricecharting_ref.median_ungraded_sold(fetch(res["pc_url"], cache_dir=cache_dir))
            except Exception:  # noqa: BLE001 — mediana e extra; a liquidez ja foi lida
                med = None
        ok += res.get("pc_status") == "OK"
        for idx in [i for i in keys if keys[i] == key]:
            served += 1
            for c in _PC_COLS[3:]:
                if c in res:
                    df.at[idx, c] = res[c]
            df.at[idx, "pc_url"] = res.get("pc_url")
            if med:
                df.at[idx, "pc_median_usd"] = float(med)
                df.at[idx, "pc_n_sales"] = n_med
    df.attrs["pc_stats"] = {"consultas_unicas": min(len(order), lim),
                            "linhas_atendidas": served,
                            "sem_consulta_limite_refs": len(cortadas),
                            "sem_consulta_limite_linhas": n_lim_linhas}
    return ok, df.attrs["pc_stats"]["consultas_unicas"]


def attach_ebay_refs(df: pd.DataFrame, resolver=None, cache_dir: str | None = None,
                     return_errors: bool = False):
    """v2.29: anexa `ebay_median_usd`/`ebay_n_sales`/`ebay_url`/`ebay_span` a
    TODAS as linhas precificadas (o corte --min-ratio corre sobre todas).
    Fonte: vendas concluídas eBay da carta INGLESA (pricecharting_ref.
    resolve_ebay_ref). Cada linha = 2 requests HTTP (busca + página, cache do
    dia). Sem venda comparável → NaN ("—" + fallback TCG rotulado na entrega).
    Retorna (resolvidas, tentadas). `resolver` injetável p/ teste offline."""
    if resolver is None:
        import pricecharting_ref
        resolver = pricecharting_ref.resolve_ebay_ref
    df["ebay_median_usd"] = pd.NA
    df["ebay_n_sales"] = pd.NA
    df["ebay_url"] = None
    df["ebay_span"] = None
    df["ebay_error"] = None
    df["ebay_miss"] = None
    resolved = attempted = errors = 0
    for idx, row in df.iterrows():
        attempted += 1
        try:
            ref = resolver(row.get("card_name"), row.get("card_number"),
                           row.get("set_code"), cache_dir=cache_dir,
                           variant=row.get("variant"))
        except Exception as e:  # noqa: BLE001 — falha da fonte, rotulada
            ref = {"error": f"{type(e).__name__}: {e}"[:120]}
        if ref and ref.get("error"):
            df.at[idx, "ebay_error"] = str(ref["error"])
            errors += 1
            continue
        if ref and ref.get("miss"):
            df.at[idx, "ebay_miss"] = str(ref["miss"])
            if ref.get("url"):
                df.at[idx, "ebay_url"] = ref.get("url")   # página existe: link auditável
            continue
        if ref and ref.get("median") is not None and float(ref["median"]) > 0:
            df.at[idx, "ebay_median_usd"] = float(ref["median"])
            df.at[idx, "ebay_n_sales"] = ref.get("n_sales")
            df.at[idx, "ebay_url"] = ref.get("url")
            if ref.get("oldest") and ref.get("newest"):
                df.at[idx, "ebay_span"] = f"{ref['oldest']}→{ref['newest']}"
            resolved += 1
    if return_errors:
        return resolved, attempted, errors
    return resolved, attempted


def _ratio_header_label(deals: pd.DataFrame) -> str:
    """Nome da coluna de razão: 'Razão EN/<IDIOMA>' quando TODAS as linhas são
    de um único idioma ≠ EN (scan --language zh-CN → 'Razão EN/ZH-CN'); senão
    o genérico 'Razão TCG/CT'. Nunca inventa idioma: sem coluna → genérico."""
    if "language" in deals.columns:
        langs = {str(v).strip().upper() for v in deals["language"].dropna()
                 if str(v).strip() and str(v).strip().lower() != "nan"}
        if len(langs) == 1:
            (lang,) = tuple(langs)
            if lang != "EN":
                return f"Razão EN/{lang}"
    return "Razão TCG/CT"


def _price_ratio(tcg_usd, ct_usd):
    """TCG US$ ÷ CT US$ (razão de PREÇO). None se faltar lado ou CT ≤ 0 —
    nunca inventa."""
    if tcg_usd is None or ct_usd is None:
        return None
    try:
        ct = float(ct_usd)
        tcg = float(tcg_usd)
    except (TypeError, ValueError):
        return None
    if ct <= 0 or pd.isna(ct) or pd.isna(tcg):
        return None
    return tcg / ct


def _fmt_ratio(v) -> str:
    return "—" if v is None else f"{v:.1f}×"


def _extra_blocks_markdown(extra_blocks) -> str:
    """Blocos 'Sem preço' / 'Sem Ref Compatível': SEM margem, com motivo e os links que
    existirem (padrao 'TCG: sem link'). Leitura por nome, tolerando colunas ausentes."""
    out = []
    for name, ex in (extra_blocks or {}).items():
        if ex is None or len(ex) == 0:
            continue
        col = lambda *names: next((c for c in names if c in ex.columns), None)  # noqa: E731
        c_name, c_set = col("Card Name", "Carta", "card_name"), col("Set", "set_code")
        c_num, c_qtd = col("Nº", "N°", "No", "card_number"), col("Qtd", "quantity")
        c_mot = col("Motivo", "motivo")
        c_ct, c_tcg = col("Link CardTrader", "Link CT", "link_ct"), col("Link TCG", "link_tcg")
        c_ed, c_ac = col("Edição", "edicao"), col("Acabamento", "acabamento")
        c_sel, c_brl = col("Seller", "Vendedor", "seller"), col("CT R$", "ct_price_brl", "Scan R$ (raw)")
        out += [f"\n\n### {name} — {len(ex)} linha(s), sem margem (não é recomendação)",
                "", "| # | Carta | Set | Edição/Acab. | Qtd | Vendedor | CT R$ | Motivo | Links |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for i, (_, r) in enumerate(ex.iterrows(), 1):
            g = lambda c: _md_escape(r.get(c)) if c else ""  # noqa: E731
            nm = f"{g(c_name)} ({g(c_num)})" if c_num and g(c_num) else g(c_name)
            ed = " · ".join(x for x in (g(c_ed), g(c_ac)) if x)
            brl = r.get(c_brl) if c_brl else None
            brl = "" if brl is None or (isinstance(brl, float) and pd.isna(brl)) else f"{float(brl):.2f}"
            out.append(f"| {i} | {nm} | {g(c_set)} | {ed or '—'} | {g(c_qtd) or '—'} | {g(c_sel) or '—'} | "
                       f"{brl or '—'} | {g(c_mot) or name} | "
                       f"{_md_links_cell(r.get(c_ct) if c_ct else None, r.get(c_tcg) if c_tcg else None)} |")
    return "\n".join(out)


def _sem_ref_frame(work: pd.DataFrame) -> pd.DataFrame:
    """Linhas SEM REF no formato dos blocos extras: sem margem, motivo do compute, links."""
    d = work[work["decisao"] == "SEM REF"]
    g = lambda c: d[c] if c in d.columns else None  # noqa: E731
    return pd.DataFrame({"Card Name": g("card_name"), "Nº": g("card_number"), "Set": g("set_code"),
                         "Qtd": g("quantity"), "Edição": g("edicao"), "Acabamento": g("acabamento"),
                         "Motivo": d["porque"], "Link CardTrader": g("link_ct"), "Link TCG": g("link_tcg")})


def _sem_ref_markdown(work: pd.DataFrame) -> str:
    blk = _sem_ref_frame(work)
    return _extra_blocks_markdown({"Sem referência (margem não calculável)": blk}) if len(blk) else ""


def build_delivery_markdown(
    df: pd.DataFrame,
    cfg: DecisionConfig,
    fx_usd_brl: float | None = None,
    top_n: int | None = None,
    show_dh: bool = False,
    show_ratio: bool = False,
    min_ratio: float | None = None,
    ref_source: str = "tcg",
    min_ref_usd: float | None = None,
    extra_blocks: dict | None = None,
    pc_summary: dict | None = None,
    scan_stats: dict | None = None,
) -> str:
    """Monta a tabela markdown de entrega (chat-first) a partir do df ENRIQUECIDO.

    Espera `df` já passado por `enrich_df` (colunas lógicas + net_margin/chase_tier).
    Reaproveita `classify_decision` p/ filtrar COMPRA+REVISAR (mesma classificação
    do XLSX — NÃO duplica regra), `_combine_name_number` p/ a coluna 'Carta'.

    USD:
      - "TCG US$" = `reference_price_usd` (nativo do raw, TCG Market USD).
      - "CT US$"  = `live_usd` se existir, senão `live_brl / fx_usd_brl`.
      - "Dif"     = TCG US$ − CT US$ (lacuna bruta em dólar).
    `fx_usd_brl` vem do Stats sheet do raw (usd_brl_rate). Sem FX nem live_usd,
    a célula CT US$ fica vazia (não inventa câmbio).
    """
    work = _decide(df, cfg)
    work["motivo"] = work["porque"]
    counts = bucket_counts(df, cfg, extra_blocks)
    deals = work[work["decisao"].isin(["COMPRA", "REVISAR"])].copy()
    # Fallback near-miss: sem COMPRA/REVISAR, a entrega NÃO vira um beco
    # "nenhum deal" (que historicamente levava a montar tabela à mão, fora do
    # padrão). Em vez disso, mostra os candidatos mais próximos por margem, no
    # MESMO formato canônico, marcados "abaixo do limiar". Garante que a entrega
    # seja SEMPRE a tabela da ferramenta (modelo MYP + coluna Links combinada).
    near_miss = deals.empty
    if near_miss:
        # candidatos abaixo do corte (margem >= 0); margem NEGATIVA nunca entra aqui
        deals = work[~work["decisao"].isin(["AUDITORIA", "SEM REF"])].copy()
    if "net_margin" in deals.columns:
        deals = deals.sort_values("net_margin", ascending=False)

    def _ct_usd(row):
        # live_usd direto se o raw trouxer; senão converte BRL via FX.
        for k in ("live_usd", "ct_price_usd"):
            if k in row and pd.notna(row.get(k)):
                return float(row[k])
        live_brl = row.get("live_brl")
        if fx_usd_brl and pd.notna(live_brl) and float(fx_usd_brl) > 0:
            return float(live_brl) / float(fx_usd_brl)
        return None

    def _tcg_usd(row):
        v = row.get("reference_price_usd")
        try:
            return float(v) if pd.notna(v) else None
        except (TypeError, ValueError):
            return None

    use_ebay = (ref_source == "ebay")

    def _ebay_usd(row):
        v = row.get("ebay_median_usd")
        try:
            return float(v) if v is not None and pd.notna(v) and float(v) > 0 else None
        except (TypeError, ValueError):
            return None

    def _ref_usd(row):
        """Referência da RAZÃO: eBay (principal, --ref-source ebay) → TCG
        (fallback rotulado na Flag). Default tcg = comportamento anterior."""
        if use_ebay:
            e = _ebay_usd(row)
            if e is not None:
                return e
        return _tcg_usd(row)

    # v2.29: razão de PREÇO TCG US$ ÷ CT US$ (--ratio-column / --min-ratio).
    # É uma coluna/corte ADICIONAL: margem, classificação e buckets canônicos
    # ficam intactos. Uso típico: scan `--language zh-CN` — a referência é a
    # carta INGLESA, logo o número é "quantas vezes a oferta chinesa é mais
    # barata que a inglesa", NÃO margem de revenda.
    ratio_cut_applied = False
    n_ratio_none = 0
    n_ratio_below = 0
    n_ref_below = 0
    if min_ratio is not None:
        # Revisão #71: o corte corre sobre TODAS as linhas precificadas — não só
        # COMPRA/REVISAR. Pra um screen de RAZÃO, uma comum 6× mais barata (que a
        # regra mecânica marcaria NÃO por ser BULK) é exatamente o que se pediu;
        # a decisão aparece na coluna Flag, nunca esconde a linha.
        # screen de RAZAO: corre sobre todas as precificadas (margem nao e o criterio), MAS margem
        # negativa (AUDITORIA) e sem-referencia (SEM REF) nunca entram na tabela comercial.
        deals = work[~work["decisao"].isin(["AUDITORIA", "SEM REF"])].copy()
        if "net_margin" in deals.columns:
            deals = deals.sort_values("net_margin", ascending=False)
        near_miss = False
        # Piso na REFERÊNCIA (operador, 2026-10-03): a carta inglesa precisa
        # valer ≥ min_ref_usd. O piso do scanner (--min-price-usd) é na oferta;
        # num screen de razão ele esconderia chinesas baratas de cartas boas,
        # por isso o run de idioma coleta com --min-price-usd 0 e o piso vive aqui.
        if min_ref_usd is not None and len(deals):
            refs = [_ref_usd(r) for _, r in deals.iterrows()]
            # Sem referência ≠ abaixo do piso: passa e cai em n_ratio_none.
            ok_ref = [v is None or v >= float(min_ref_usd) for v in refs]
            n_ref_below = int(sum(1 for v in refs if v is not None and v < float(min_ref_usd)))
            deals = deals[pd.Series(ok_ref, index=deals.index)]
        deals["_ratio"] = [_price_ratio(_ref_usd(r), _ct_usd(r)) for _, r in deals.iterrows()]
        n_ratio_none = int(sum(1 for v in deals["_ratio"] if v is None))
        keep = [v is not None and v >= float(min_ratio) for v in deals["_ratio"]]
        n_ratio_below = int(len(deals) - sum(keep) - n_ratio_none)
        deals = deals[pd.Series(keep, index=deals.index)] if len(deals) else deals
        ratio_cut_applied = True
    elif show_ratio:
        deals["_ratio"] = [_price_ratio(_ref_usd(r), _ct_usd(r)) for _, r in deals.iterrows()]
    ratio_label = _ratio_header_label(deals) if show_ratio else None
    if ratio_label and use_ebay:
        ratio_label = ratio_label.replace("Razão EN/", "Razão eBay-EN/").replace(
            "Razão TCG/CT", "Razão eBay/CT")
    n_deals_total = len(deals)
    deals = deals.head(top_n) if top_n else deals
    deals = _combine_name_number(deals)  # 'card_name' vira "Nome (NNN/Total)"

    k = cfg.costs
    title = (
        f"### CardTrader — entrega ({'mostrando ' + str(len(deals)) + ' de ' + str(n_deals_total) if len(deals) < n_deals_total else str(len(deals)) + ' linha(s)'} por margem · margem sobre a VENDA "
        f"(ref−compra)/ref, corte {cfg.min_net_margin:.0%} · liquidez ≥{cfg.min_sales_90d} "
        f"vendas/90d e ≥{cfg.min_sales_30d}/30d)"
    )
    # Rodape de contabilidade: nada some em silencio (ver bucket_counts).
    foot = [
        f"_Entrada: {counts['ENTRADA']} linha(s) = {counts['COMPRA']} COMPRA + "
        f"{counts['REVISAR']} REVISAR + {counts['NAO']} abaixo do corte/rejeitadas + "
        f"{counts['AUDITORIA']} margem negativa + {counts['SEM_REF']} sem referência/compra "
        "(sem margem)"
        + "".join(f" + {q} {n}" for n, q in counts["EXTRAS"].items()) + "._",
        f"_{counts['AUDITORIA']} oportunidade(s) com margem negativa enviada(s) para a aba "
        "Auditoria do XLSX (fora desta tabela)._",
        f"_Custos: Hub {k.hub_fee_rate:.0%} (só quando o preço é cru; o checkout já embute) + "
        f"frete R$ {k.frete_compra_brl:.2f}/carta. Margem líquida só no XLSX e sempre PARCIAL "
        "(custos não informados: " + ", ".join(
            n for n in ("iof_rate", "spread_cambio_rate", "card_fee_rate", "import_tax_rate",
                        "sell_fee_rate", "frete_venda_brl") if getattr(k, n) is None) + ")._",
    ]
    foot += _origin_lines(scan_stats, counts["ENTRADA"])
    _src = _sources_line(df, scan_stats)
    if _src:
        foot.append(_src)
    if len(deals) < n_deals_total:
        foot.append(
            f"_{n_deals_total - len(deals)} linha(s) de COMPRA/REVISAR ficaram FORA desta tabela por "
            f"--top-md {top_n}; estão completas na aba 'Deals' do XLSX do relatório (e nas abas "
            "'All Listings'/'Validate Manually'). O comando canônico não usa --top-md._")
    if pc_summary:
        foot.append(
            f"_PriceCharting: {pc_summary.get('consultas_unicas', 0)} consulta(s) única(s) para "
            f"{pc_summary.get('linhas_atendidas', 0)} linha(s) atendida(s); "
            f"{pc_summary.get('firecrawl_creditos_gastos', 0)} crédito(s) Firecrawl de "
            f"{pc_summary.get('firecrawl_teto', 0)} liberados._")
        if pc_summary.get("sem_consulta_limite_refs"):
            foot.append(
                f"_PriceCharting: {pc_summary['sem_consulta_limite_refs']} referência(s) sem consulta "
                f"por limite ({pc_summary.get('sem_consulta_limite_linhas', 0)} linha(s)) — limite "
                "--pc-refs esgotado; ficam REVISAR com status LIMITE_CONSULTAS (não é falha da fonte)._")
    extra_md = _extra_blocks_markdown(extra_blocks) + _sem_ref_markdown(work)
    if ratio_cut_applied:
        title += f" · corte razão ≥ {float(min_ratio):.1f}× (sobre todas as linhas precificadas)"
        if min_ref_usd is not None:
            title += f" · piso ref ≥ US${float(min_ref_usd):g}"
    if ratio_cut_applied and deals.empty:
        # 'sem dado' ≠ 'abaixo do corte': dizer os dois números, nunca culpar a
        # razão quando ela nem pôde ser calculada (sem câmbio/CT US$).
        parts = [f"{n_ratio_below} abaixo do corte"] if (n_ratio_below or not n_ref_below) else []
        if n_ref_below:
            parts.append(f"{n_ref_below} abaixo do piso ref US${float(min_ref_usd):g}")
        if n_ratio_none:
            parts.append(f"{n_ratio_none} sem CT US$ (sem câmbio/preço — razão não calculável)")
        msg = (f"\n\n_(0 linha com razão ≥ {float(min_ratio):.1f}× entre "
               f"{n_ratio_below + n_ratio_none + n_ref_below} precificada(s): " + "; ".join(parts) + ". ")
        if n_ratio_below and not n_ratio_none and not n_ref_below:
            msg += "Nenhuma oferta precificada é tão mais barata que a referência inglesa. "
        msg += "Linhas abaixo do corte NÃO são mostradas como resultado.)_"
        return title + msg + "\n\n" + "\n".join(foot) + extra_md
    if deals.empty:
        # Sob o contrato de entrega v2.22, o scanner persiste TODO listing
        # precificado no XLSX (mesmo abaixo do threshold). Logo, df vazio aqui
        # significa MESMO "0 precificado" (set sem cobertura TCG / 0 listing
        # passou os filtros NM/EN/preço), não "precificou mas nada bateu o
        # threshold" — esse caso vira a tabela near-miss acima.
        return title + (
            "\n\n_(0 listing precificado — nada a entregar. Nenhuma carta passou "
            "os filtros (NM/EN/≥preço) com preço de referência TCG. Não confundir "
            "com 'precificou mas 0 acima do threshold' — esse caso mostra a tabela "
            "near-miss.)_"
        ) + "\n\n" + "\n".join(foot) + extra_md

    # Coluna DH = 2ª opinião Double Holo (EXTRA, condicional à --doubleholo).
    # Inserida logo após "Margem %" (perto da margem), sem remover/reordenar as
    # colunas existentes nem colapsar a coluna Links — contrato de 2 links/linha
    # intacto. Só aparece se a coluna `dh_score` foi anexada (flag passada).
    show_dh = show_dh and "dh_score" in deals.columns
    # Colunas PC (metodologia 2026-08-28): presentes quando attach_pc_refs rodou
    # (--pc-refs). Inseridas após "TCG US$" ANTES do insert DH (que desloca os
    # índices), sem remover/reordenar as existentes — contrato intacto.
    show_pc = "pc_median_usd" in deals.columns
    headers = list(_DELIVERY_HEADERS)
    show_ebay = use_ebay and "ebay_median_usd" in deals.columns
    if show_ebay:
        headers.insert(headers.index("TCG US$") + 1, "Ref eBay US$")
    if show_pc:
        pc_at = headers.index("TCG US$") + 1
        headers.insert(pc_at, "Margem PC %")
        headers.insert(pc_at, "Ref PC US$")
    if show_ratio:
        headers.insert(2, ratio_label)  # após "#" (0) e "Margem %" (1)
    if show_dh:
        headers.insert(2, "DH")  # após "#" (0) e "Margem %" (1)
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    lines = [title]
    if near_miss:
        lines.append(
            "\n_⚠️ Nenhum deal acima do limiar — mostrando os candidatos mais "
            "próximos por margem (todos ABAIXO do limiar, só referência)._"
        )
    lines += ["", header, sep]

    for rank, (_, row) in enumerate(deals.iterrows(), 1):
        ct_usd = _ct_usd(row)
        tcg_usd = _tcg_usd(row)
        dif =(tcg_usd - ct_usd) if (ct_usd is not None and tcg_usd is not None) else None
        # Flag por linha: near-miss → "abaixo do limiar"; REVISAR (zona cinza /
        # suspeito de margem inflada) → "validar manual"; COMPRA → célula limpa.
        # Mesma classificação do XLSX.
        if near_miss:
            flag = "abaixo do limiar"
            if str(row.get("decisao")) == "NAO":
                flag += f": {row.get('motivo')}"
        elif str(row.get("decisao")) == "NAO":
            # Só alcançável com --min-ratio (corte sobre TODAS as precificadas):
            # a linha passou na razão mas a regra mecânica a rejeitaria — dizer
            # por quê, em vez de escondê-la.
            flag = f"NÃO: {row.get('motivo') or 'rejeitada pela regra mecânica'}"
        else:
            flag = (f"validar manual: {row.get('motivo')}"
                    if str(row.get("decisao")) == "REVISAR" else "")
        _mk = str(row.get("ref_desatualizada") or "").strip()
        if _mk and _mk.lower() != "nan":
            flag = (flag + " · " + _mk).strip(" ·")
        _sw = str(row.get("ref_swap") or "").strip()
        if _sw and _sw.lower() != "nan":
            flag = (flag + " · " + _sw).strip(" ·")
        # PC: mediana das vendas reais + margem sobre ela (mesma base revenda do
        # scanner: (PC − CT)/PC). Sem dado → "—". Divergência TCG↔PC > ratio →
        # flag "PC diverge" (sinal-only, não muda margem/decisão).
        pc_med = row.get("pc_median_usd") if show_pc else None
        try:
            pc_med = float(pc_med) if pd.notna(pc_med) else None
        except (TypeError, ValueError):
            pc_med = None
        pc_margin = ((pc_med - ct_usd) / pc_med
                     if (pc_med and ct_usd is not None) else None)
        if (show_pc and pc_med and tcg_usd is not None
                and abs(tcg_usd - pc_med) / pc_med > PC_DIVERGENCE_RATIO):
            flag = (flag + " · PC diverge").strip(" ·")
        ebay_med = _ebay_usd(row) if show_ebay else None
        if show_ratio and use_ebay and ebay_med is None:
            # Razão veio do TCG — rotular, nunca apresentar como se fosse eBay.
            # Erro de FONTE ≠ "sem venda": dizer qual dos dois.
            err = row.get("ebay_error")
            if err is not None and not (isinstance(err, float) and pd.isna(err)) and str(err).strip():
                why = f"eBay indisponível: {str(err)[:60]}"
            else:
                miss = row.get("ebay_miss")
                why = (str(miss) if miss is not None and not (isinstance(miss, float) and pd.isna(miss))
                       and str(miss).strip() else "sem venda eBay")
            flag = (flag + f" · fallback TCG ({why})").strip(" ·")
        elif show_ebay and ebay_med is not None and pd.notna(row.get("ebay_n_sales")):
            flag = (flag + f" · eBay n={int(row.get('ebay_n_sales'))}"
                    + (f" ({row.get('ebay_span')})" if row.get("ebay_span") else "")).strip(" ·")
        # Contrato dos 2 links: linha sem URL de oferta/TCG fica na tabela, marcada.
        for _k, _lbl in (("link_ct", "oferta"), ("link_tcg", "TCG")):
            _u = row.get(_k)
            if not _valid_url(_u):
                flag = (flag + f" · sem link {_lbl}").strip(" ·")
        cells = [
            str(rank),
            _fmt_pct(row.get("net_margin")),
            _fmt_usd(ct_usd),
            reference_price(_fmt_usd(tcg_usd), row.get("link_tcg")),
            _fmt_usd(dif),
            _md_escape(row.get("card_name")),
            _cell_or_dash(row.get("edicao")),
            _cell_or_dash(row.get("acabamento")),
            _md_escape(row.get("set_code")),
            _md_escape(row.get("rarity")),
            _md_escape(row.get("condition")),
            _md_escape(row.get("quantity")),
            _sales_text(row.get("pc_vendas_30d"), row.get("pc_truncado")),
            _sales_text(row.get("pc_vendas_90d"), row.get("pc_truncado")),
            _cell_or_dash(row.get("price_source")),
            _fmt_ref_date(row.get("ref_data_label"), row.get("ref_data_at")),
            _md_escape(flag),
            _md_links_cell(row.get("link_ct"), row.get("link_tcg"),
                           row.get("pc_url") if show_pc else None,
                           row.get("ebay_url") if show_ebay else None),
        ]
        if show_ebay:
            # Mesmo índice-fonte do header (inserido ANTES das colunas PC).
            cells.insert(_DELIVERY_HEADERS.index("TCG US$") + 1,
                         reference_price(_fmt_usd(ebay_med), row.get("ebay_url"))
                         if ebay_med is not None else "—")
        if show_pc:
            # Mesmo índice-fonte do insert dos headers (índice em
            # _DELIVERY_HEADERS, ANTES do insert DH) — nunca hardcodar os dois
            # lados separados, senão um reorder desalinha célula↔header em
            # silêncio.
            pc_cell_at = _DELIVERY_HEADERS.index("TCG US$") + 1
            cells.insert(pc_cell_at, _fmt_pct(pc_margin) or "—")
            cells.insert(pc_cell_at, reference_price(_fmt_usd(pc_med) or "—", row.get("pc_url")))
        if show_ratio:
            # Razão calculada UMA vez (coluna `_ratio`) — mesmo número do corte.
            cells.insert(2, _fmt_ratio(row.get("_ratio")))
        if show_dh:
            cells.insert(2, _fmt_dh(row.get("dh_score")))
        lines.append("| " + " | ".join(cells) + " |")
    if show_ratio and use_ebay:
        lines.append(
            f"\n_{ratio_label} = Ref eBay US$ (mediana das até 10 vendas eBay "
            "concluídas mais recentes da carta INGLESA raw, 365 dias, ≥3 vendas; "
            "títulos em outro idioma, gradeados e lotes excluídos; fonte: tabela "
            "pública do PriceCharting, link [eBay]) ÷ CT US$ (oferta no idioma "
            "escaneado). Sem venda eBay comparável → razão via TCG US$, rotulada "
            "'fallback TCG'. É razão de PREÇO entre dois mercados — não é margem "
            "de revenda. '—' = sem um dos lados._"
        )
    elif show_ratio:
        lines.append(
            f"\n_{ratio_label} = TCG US$ (referência da carta INGLESA, NM) ÷ "
            "CT US$ (oferta no idioma escaneado). É razão de PREÇO entre dois "
            "mercados — não é margem de revenda: carta em outro idioma não vende "
            "pelo preço TCGplayer da inglesa. '—' = sem um dos lados._"
        )
    if show_dh:
        lines.append(
            "\n_DH = 2ª opinião Double Holo 0-100 (50=neutro), não entra na "
            "margem/decisão; '—' = sem dado._"
        )
    if show_pc:
        lines.append(
            "\n_Ref PC = mediana das últimas vendas REAIS (PriceCharting, "
            "eBay+TCGPlayer, ungraded); Margem PC = (PC − CT)/PC. '—' = sem "
            "match/venda (nunca inventa). Flag 'PC diverge' = ref TCG a mais "
            f"de {PC_DIVERGENCE_RATIO:.0%} da mediana PC — margem canônica e "
            "decisão NÃO mudam (sinal-only)._"
        )
    lines.append("")
    lines += foot
    return "\n".join(lines) + extra_md


def _read_fx_usd_brl(input_path: Path) -> float | None:
    """Lê usd_brl_rate da aba Stats do raw XLSX do scanner (pra converter CT US$).

    Retorna None silenciosamente se a aba/linha não existir (input de origem
    diferente, raw antigo). Sem FX, a coluna CT US$ fica vazia — não inventa."""
    try:
        stats = pd.read_excel(input_path, sheet_name="Stats", header=None)
    except Exception:
        return None
    for _, r in stats.iterrows():
        if str(r.iloc[0]).strip().lower() == "usd_brl_rate":
            try:
                return float(r.iloc[1])
            except (TypeError, ValueError):
                return None
    return None


MAX_PC_FIRECRAWL = pricecharting_ref.MAX_FIRECRAWL_CREDITS_PER_RUN   # teto do dono (2026-11-24)
EXTRA_SHEETS = ("Sem preço", "Sem Preço", "Sem Ref Compatível")


def read_extra_blocks(input_path) -> dict:
    """Abas 'Sem preço' (PR #74) / 'Sem Ref Compatível' (B1) do XLSX do scanner, se existirem.
    Ausente → {} (a entrega segue sem o bloco)."""
    try:
        names = pd.ExcelFile(input_path).sheet_names
    except Exception:
        return {}
    out = {}
    for n in EXTRA_SHEETS:
        if n in names:
            ex = pd.read_excel(input_path, sheet_name=n)
            if len(ex):
                out[n] = ex
    return out


def write_report(df: pd.DataFrame, cfg: DecisionConfig, output_path: Path,
                 fx_usd_brl: float | None = None, top_md: int | None = None,
                 dh_signals: dict | None = None, pid_resolver=None,
                 pc_refs: int = 0, show_ratio: bool = False,
                 min_ratio: float | None = None, ref_source: str = "tcg",
                 pc_firecrawl: int = 0, min_ref_usd: float | None = None,
                 extra_blocks: dict | None = None,
                 scan_stats: dict | None = None) -> str:
    # Run novo: nenhuma pagina/falha PC de outra coleta vaza para esta (DELIVERY_CHAT).
    pricecharting_ref.new_run()
    if pc_firecrawl > MAX_PC_FIRECRAWL:
        raise ValueError(f"--pc-firecrawl {pc_firecrawl} acima do teto de {MAX_PC_FIRECRAWL} "
                         "créditos por scan (autorização do dono)")
    pricecharting_ref.set_firecrawl_budget(pc_firecrawl)   # default 0 = nunca paga
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = enrich_df(df, costs=cfg.costs)
    df = _add_ref_age(df, scan_stats, cfg)
    # Referência PriceCharting (--pc-refs N): liquidez (vendas 30d/90d da pagina da MESMA
    # edicao) + mediana ungraded, por consulta UNICA, em ordem de lucro decrescente.
    # Cache so DESTE run (pasta nova por coleta). 0 = desligado (liquidez nao verificada).
    pc_summary = None
    if ref_source == "ebay":
        # v2.29: eBay = referência PRINCIPAL da razão (vendas concluídas da
        # carta inglesa). Rede: 2 req/linha, 2 s entre requests. Cache NOVO por
        # coleta (DELIVERY_CHAT.md: nunca reaproveitar preço de outro run).
        run_cache = os.path.join("outputs", "ebay_ref_cache", run_stamp)
        res, att, errs = attach_ebay_refs(df, cache_dir=run_cache, return_errors=True)
        print(f"[ebay-ref] vendas eBay comparáveis: {res}/{att} linha(s) resolvidas; "
              f"{errs} com ERRO de fonte (rotuladas 'eBay indisponível'); "
              f"{att - res - errs} sem venda comparável. Firecrawl: "
              f"{pricecharting_ref.firecrawl_used()} crédito(s) de {pc_firecrawl} liberados.")
    if pc_refs > 0:
        pc_cache = os.path.join(os.path.dirname(os.path.abspath(output_path)), f"pc_cache_{run_stamp}")
        resolved, attempted = attach_pc_refs(df, cfg, top_md=top_md, limit=pc_refs,
                                             cache_dir=pc_cache)
        pc_summary = {**df.attrs.get("pc_stats", {}), **pricecharting_ref.run_summary()}
        print(f"[PC] {resolved}/{attempted} consulta(s) única(s) com página compatível; "
              f"{pc_summary.get('linhas_atendidas', 0)} linha(s) atendida(s); "
              f"{pc_summary['firecrawl_creditos_gastos']} crédito(s) Firecrawl de "
              f"{pc_summary['firecrawl_teto']} liberados.")
    # Caminho 1 DoubleHolo: anexa a coluna `dh_score` (2ª opinião). Só quando
    # --doubleholo foi passado; sem a flag a coluna não existe e a saída é
    # idêntica. NÃO toca margem/decisão.
    if dh_signals is not None:
        # 1º resolve o productId TCGplayer por linha (link tcgcsv direto via
        # Fix(1) OU ponte offline tcgcsv via Fix(2)); 2º casa a nota DH por ele.
        # Follow-up #4: o resolver OFFLINE (I/O) só roda nas linhas da ENTREGA
        # markdown — os deals (COMPRA/REVISAR) ou, sem nenhum, os candidatos
        # near-miss (ver _delivery_resolve_mask). Num --all-sets a maioria é NÃO e
        # nunca entra na entrega, então evita o I/O nelas. O Fix(1) (productId do
        # link direto, SEM I/O) segue valendo p/ TODAS as linhas — logo a coluna DH
        # do XLSX "All Listings" tem cobertura best-effort (deal/near-miss + linhas
        # com link tcgplayer.com/product direto); linha NÃO-deal sem link de produto
        # mostra "—" (honesto: DH é 2ª opinião de deal, não de listing rejeitado).
        deliver_mask = _delivery_resolve_mask(df, cfg, top_md)
        resolved = attach_product_ids(df, pid_resolver, resolve_mask=deliver_mask)
        matched = doubleholo_join.attach_scores_df(
            df, dh_signals, url_col="link_tcg", pid_col="tcg_product_id")
        # Follow-up #5: "casaram" (productId no índice) ≠ "com nota DH" (dh_score
        # não-None) — separa as duas contagens p/ a telemetria não inflar.
        scored = int(df["dh_score"].notna().sum())
        print(f"[DH] productId resolvido em {resolved}/{len(df)} linhas; "
              f"{matched} casaram com o DoubleHolo, {scored} com nota DH "
              f"(sem match ou sem nota → '—').")
    df = _decide(df, cfg)   # decide UMA vez (PC/DH ja anexados); o resto reaproveita
    wb = Workbook(); wb.remove(wb.active)
    extra_blocks = extra_blocks or {}

    deals = build_deals_sheet(df, cfg)
    ws = wb.create_sheet("Deals")
    if deals.empty:
        ws.cell(row=1, column=1, value="Nenhum deal (COMPRA ou REVISAR) encontrado.")
    else:
        for ri, row in enumerate([deals.columns.tolist()] + deals.values.tolist(), 1):
            for ci, val in enumerate(row, 1):
                ws.cell(row=ri, column=ci, value=_safe_val(val) if ri > 1 else val)
        style_sheet(ws, deals, decisao_col="Decisão", chase_col="Chase Tier")

    all_l = build_all_listings_sheet(df, cfg)
    ws = wb.create_sheet("All Listings")
    if all_l.empty:
        ws.cell(row=1, column=1, value="Vazio.")
    else:
        for ri, row in enumerate([all_l.columns.tolist()] + all_l.values.tolist(), 1):
            for ci, val in enumerate(row, 1):
                ws.cell(row=ri, column=ci, value=_safe_val(val) if ri > 1 else val)
        style_sheet(ws, all_l, decisao_col="Decisão", chase_col="Chase Tier")

    # ─── PR-K: 3 sheets MYP-style adicionais ────────────────────────────────
    # Derivadas de All Listings — preservam mesmas colunas, só mudam filtro/sort.
    def _write_styled(sheet_name: str, sheet_df: pd.DataFrame):
        ws = wb.create_sheet(sheet_name)
        if sheet_df.empty:
            ws.cell(row=1, column=1, value="Nenhum listing nesta categoria.")
            return
        for ri, row in enumerate([sheet_df.columns.tolist()] + sheet_df.values.tolist(), 1):
            for ci, val in enumerate(row, 1):
                ws.cell(row=ri, column=ci, value=_safe_val(val) if ri > 1 else val)
        style_sheet(ws, sheet_df, decisao_col="Decisão", chase_col="Chase Tier")

    _write_styled("Top 50 Margin", build_top50_margin_sheet(all_l))
    _write_styled("Validate Manually", build_validate_manually_sheet(all_l))
    _write_styled("TCG Suspect", build_tcg_suspect_sheet(all_l))
    _write_styled("Auditoria", build_auditoria_sheet(df, cfg))   # margem negativa
    _write_styled("Sem referência", _sheet_frame(df[df["decisao"] == "SEM REF"]))   # sem margem calculavel
    for _name, _ex in extra_blocks.items():   # linhas sem margem: nao somem
        _write_styled(_name, _ex)

    summary = build_summary(df, cfg, extra_blocks, scan_stats)
    ws = wb.create_sheet("Summary")
    for ri, row in enumerate([summary.columns.tolist()] + summary.values.tolist(), 1):
        for ci, val in enumerate(row, 1):
            ws.cell(row=ri, column=ci, value=_safe_val(val) if ri > 1 else val)
    # Style summary
    for ci in range(1, len(summary.columns) + 1):
        c = ws.cell(row=1, column=ci)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
    for ci, cn in enumerate(summary.columns, 1):
        ws.column_dimensions[get_column_letter(ci)].width = 40

    # Garante o diretório-alvo antes de salvar (outputs/ é gitignored → ausente
    # num clone limpo): sem isto o wb.save() quebra com FileNotFoundError.
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    print(f"OK: {output_path}")

    # ─── Entrega no chat: tabela markdown (links clicáveis) ──────────────────
    # Formato aprovado 2026-06-09. A entrega ao operador é a TABELA no chat;
    # o .md sidecar é só conveniência (mesmo conteúdo). XLSX segue cru/colunar.
    md = build_delivery_markdown(df, cfg, fx_usd_brl=fx_usd_brl, top_n=top_md,
                                 show_dh=dh_signals is not None,
                                 show_ratio=show_ratio, min_ratio=min_ratio,
                                 ref_source=ref_source, min_ref_usd=min_ref_usd,
                                 extra_blocks=extra_blocks, pc_summary=pc_summary,
                                 scan_stats=scan_stats)
    md_path = output_path.with_suffix(".md")
    try:
        md_path.write_text(md + "\n", encoding="utf-8")
        print(f"OK: {md_path} (tabela de entrega — copie pro chat)")
    except OSError as e:
        print(f"[postprocess] aviso: não gravou {md_path} ({e}); tabela só no stdout.")
    print("\n" + md + "\n")
    return md

def _pc_firecrawl_arg(v):
    n = int(v)
    if not 0 <= n <= MAX_PC_FIRECRAWL:
        raise argparse.ArgumentTypeError(
            f"--pc-firecrawl deve estar entre 0 e {MAX_PC_FIRECRAWL} (teto por scan autorizado "
            f"pelo dono); recebido {n}")
    return n


def build_parser():
    p = argparse.ArgumentParser(description="CardTrader postprocess P1 — margem sobre a venda, "
                                            "liquidez PriceCharting, chase informativo")
    p.add_argument("--input", "-i", required=True, help="XLSX raw do scanner")
    p.add_argument("--output", "-o", required=True, help="XLSX relatorio destino")
    p.add_argument("--min-net-margin", type=float, default=0.30,
                   help="Corte de COMPRA: margem sobre a VENDA (ref-compra)/ref, em FRACAO "
                        "(default 0.30 = 30%%; decisao do dono). Nao e ROI.")
    p.add_argument("--max-ref-age-days", type=float, default=7.0,
                   help=("B1f: idade máxima (dias) do dado da referência; linha mais velha leva a marca "
                         "'referência desatualizada (N dias)' e nunca sai COMPRA (vai a REVISAR; a margem "
                         "continua exibida). Default 7 é PROVISÓRIO: o valor definitivo é do dono."))
    p.add_argument("--min-sales-90d", type=int, default=5,
                   help="Liquidez: minimo de vendas ungraded nos ultimos 90 dias na pagina "
                        "PriceCharting da mesma edicao (default 5; configuravel). "
                        "Sem dado de liquidez a linha vai a REVISAR, nunca COMPRA.")
    p.add_argument("--min-sales-30d", type=int, default=1,
                   help="Liquidez: minimo de vendas nos ultimos 30 dias (default 1; configuravel).")
    p.add_argument("--iof", type=float, default=None, help="IOF (fracao) — so entra se informado")
    p.add_argument("--spread-cambio", type=float, default=None,
                   help="Spread cambial (fracao) — so entra se informado")
    p.add_argument("--card-fee", type=float, default=None, help="Taxa do cartao (fracao) — so se informada")
    p.add_argument("--import-tax", type=float, default=None,
                   help="Imposto de importacao (fracao) — so se informado")
    p.add_argument("--sell-fee", type=float, default=None, help="Taxa de venda (fracao) — so se informada")
    p.add_argument("--sell-shipping-brl", type=float, default=None,
                   help="Frete de venda por carta (R$) — so se informado")
    for _flag, _bases in (("iof", BASES_COMPRA), ("spread-cambio", BASES_COMPRA),
                          ("card-fee", BASES_COMPRA), ("import-tax", BASES_COMPRA),
                          ("sell-fee", BASES_VENDA)):
        p.add_argument(f"--{_flag}-base", choices=_bases, default=None,
                       help=f"Base de incidencia de --{_flag} (obrigatoria junto com a taxa; "
                            "nenhuma base e presumida)")
    p.add_argument("--shipping-brl", type=float, default=0.50,
                   help="Frete de compra POR CARTA em R$ (default 0.50, dono; sem desconto por "
                        "quantidade do mesmo vendedor)")
    p.add_argument("--min-lucro", type=float, default=50.0,
                   help="Lucro liquido R$ minimo pra COMPRA (default 50)")
    p.add_argument("--revisar-min-net", type=float, default=0.20,
                   help="Net margin minimo pra zona REVISAR (default 0.20)")
    p.add_argument("--hub-fee", type=float, default=0.06,
                   help=("Hub fee (default 0.06, dono). So afeta a margem LIQUIDA parcial do "
                         "XLSX, e so nas linhas com preco cru do scan: o preco de checkout "
                         "(LIVE) ja embute o Hub e nunca recebe a taxa duas vezes."))
    p.add_argument("--top-md", type=int, default=None,
                   help=("Quantas linhas na tabela de entrega markdown do chat "
                         "(default: todas). XLSX sempre traz todos os deals."))
    p.add_argument("--doubleholo", default=None, metavar="JSON",
                   help=("Caminho do JSON canônico do DoubleHolo (saída de "
                         "doubleholo_signals.py ingest --json). Adiciona a coluna "
                         "DH (2ª opinião 0-100, 50=neutro) por productId TCGplayer. "
                         "NÃO entra na margem/decisão. Sem a flag, saída idêntica."))
    p.add_argument("--pc-refs", type=int, default=0, metavar="N",
                   help="Metodologia 2026-08-28: anexa a coluna 'Ref PC US$' "
                        "(mediana das vendas REAIS do PriceCharting) às N linhas "
                        "de maior lucro da entrega que passariam nao fosse a liquidez, "
                        "uma consulta por carta/set/edicao/acabamento (dedup), + liquidez "
                        "(Vendas 30d/90d da pagina da MESMA edicao) + link [PC]. Faz rede "
                        "(2 req/consulta, cache so deste run). N = maximo de consultas "
                        "unicas. Sem liquidez verificada nada vira COMPRA. 0 = off.")
    p.add_argument("--ratio-column", action="store_true",
                   help=("v2.29: adiciona a coluna 'Razão EN/<IDIOMA>' (TCG US$ ÷ "
                         "CT US$) logo após 'Margem %%'. Para scans com "
                         "`--language ≠ en`: a referência é a carta INGLESA, então "
                         "o número é razão de PREÇO entre mercados, não margem de "
                         "revenda. Margem/decisão/buckets canônicos intactos."))
    p.add_argument("--min-ratio", type=float, default=None, metavar="X",
                   help=("v2.29: só entrega linhas com razão TCG/CT ≥ X (ex.: 4 = "
                         "oferta ≤ 25%% da referência). Corte explícito no título; "
                         "0 linhas → mensagem honesta, nunca a tabela near-miss."))
    p.add_argument("--min-ref-usd", type=float, default=10.0, metavar="USD",
                   help=("v2.29: piso da REFERÊNCIA inglesa (eBay/TCG) no corte "
                         "--min-ratio (default 10). Só vale com --min-ratio; colete "
                         "o scan de idioma com --min-price-usd 0 para não aplicar o "
                         "piso também à oferta. 0 = sem piso."))
    p.add_argument("--ref-source", choices=["tcg", "ebay"], default="tcg",
                   help=("v2.29: referência da coluna/corte de RAZÃO. 'ebay' = "
                         "mediana das vendas eBay concluídas da carta INGLESA raw "
                         "(PriceCharting público; ≥3 vendas/365d; sem outro idioma/"
                         "gradeada/lote) como fonte PRINCIPAL, TCG como fallback "
                         "rotulado. Liga a coluna de razão. Rede: 2 req/linha."))
    p.add_argument("--pc-firecrawl", type=_pc_firecrawl_arg, default=0, metavar="N",
                   help=("v2.29: PriceCharting bloqueia (403) cliente HTTP comum em "
                         "alguns IPs. Libera até N páginas via Firecrawl (PAGO, 1 "
                         "crédito/página, FIRECRAWL_API_KEY) quando isso ocorrer. "
                         "Default 0 = nunca paga; maximo aceito 100 por scan (dono); "
                         "erro vira 'indisponível'. Linhas de maior lucro primeiro."))
    p.add_argument("--no-pid-resolve", action="store_true",
                   help=("Desliga a resolução OFFLINE de productId via tcgcsv "
                         "(Fix(2)) usada p/ casar DH nas linhas via pokemontcg.io. "
                         "Só tem efeito junto com --doubleholo; sem ela, só casam "
                         "linhas cujo Link TCG já é tcgplayer.com/product/<id>."))
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Paridade com o scanner: aceita `6` ou `0.06` (auto-converte percentual).
    if args.hub_fee > 1.0:
        print(f"[postprocess v2.12] --hub-fee {args.hub_fee} > 1.0 parece "
              f"percentual; convertendo para fração: {args.hub_fee/100}")
        args.hub_fee = args.hub_fee / 100.0

    try:
        costs = Costs(hub_fee_rate=args.hub_fee, frete_compra_brl=args.shipping_brl,
                      iof_rate=args.iof, iof_base=args.iof_base,
                      spread_cambio_rate=args.spread_cambio, spread_cambio_base=args.spread_cambio_base,
                      card_fee_rate=args.card_fee, card_fee_base=args.card_fee_base,
                      import_tax_rate=args.import_tax, import_tax_base=args.import_tax_base,
                      sell_fee_rate=args.sell_fee, sell_fee_base=args.sell_fee_base,
                      frete_venda_brl=args.sell_shipping_brl)
    except ValueError as e:
        parser.error(str(e))
    cfg = DecisionConfig(
        min_net_margin=args.min_net_margin,
        min_lucro_liq=args.min_lucro,
        revisar_min_net=args.revisar_min_net,
        min_sales_90d=args.min_sales_90d,
        min_sales_30d=args.min_sales_30d,
        max_ref_age_days=args.max_ref_age_days,
        costs=costs,
    )
    df = pd.read_excel(args.input)
    print(f"Carregado: {args.input} | {len(df)} rows | cols: {len(df.columns)}")
    # FX usd_brl da aba Stats do raw → converte CT (BRL) p/ "CT US$" na tabela.
    fx = _read_fx_usd_brl(Path(args.input))
    if fx:
        print(f"FX usd_brl_rate (Stats) = {fx:.4f} — usado p/ coluna CT US$.")
    else:
        print("FX usd_brl_rate ausente no input — coluna CT US$ ficará vazia.")
    dh_signals = None
    pid_resolver = None
    if args.doubleholo:
        # A coluna DH é um EXTRA não-essencial: arquivo faltando/malformado NÃO
        # pode derrubar a entrega dos deals (espelha run_outlook.py, que degrada
        # com "--doubleholo ignorado"). Falhou → segue sem DH, saída idêntica.
        try:
            dh_signals = doubleholo_join.load_signals(args.doubleholo)
            print(f"DoubleHolo: {len(dh_signals)} registros com productId TCGplayer "
                  f"carregados de {args.doubleholo} — coluna DH ativa.")
        except Exception as e:  # noqa: BLE001 — DH é opcional; não aborta os deals
            dh_signals = None
            print(f"[DH] aviso: --doubleholo ignorado ({e}); entrega segue sem a "
                  f"coluna DH.")
        if dh_signals is not None and not args.no_pid_resolve:
            # Resolver OFFLINE de productId p/ linhas via pokemontcg.io (Fix(2)).
            # Import lazy: só paga o custo (e o import do scanner) quando há DH.
            try:
                import tcgcsv_productid
                pid_resolver = tcgcsv_productid.ProductIdResolver()
            except Exception as e:  # noqa: BLE001 — sem resolver → cai p/ Fix(1) só
                print(f"[DH] aviso: resolver de productId indisponível ({e}); "
                      f"só linhas com link tcgplayer.com/product casam.")
    write_report(df, cfg, Path(args.output), fx_usd_brl=fx, top_md=args.top_md,
                 dh_signals=dh_signals, pid_resolver=pid_resolver,
                 pc_refs=args.pc_refs,
                 show_ratio=bool(args.ratio_column or args.min_ratio is not None
                                 or args.ref_source == "ebay"),
                 min_ratio=args.min_ratio, ref_source=args.ref_source,
                 pc_firecrawl=args.pc_firecrawl,
                 min_ref_usd=(args.min_ref_usd or None),
                 extra_blocks=read_extra_blocks(args.input),
                 scan_stats=_read_scan_stats(args.input))

if __name__ == "__main__":
    main()
