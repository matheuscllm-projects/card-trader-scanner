"""Chase tier unico (A3/D6). Copia fiel das regras antigas do scanner e do postprocess.

Indicador EXCLUSIVAMENTE INFORMATIVO (vintage e moderno): nunca entra em margem,
corte ou decisao. Divergencia conhecida (travada em tests/test_ct_chase.py):
rarity vazia + proxies None -> "" aqui e no scanner antigo; o postprocess antigo
devolvia "MODEST". Regra de unificacao: rarity vazia E sem proxies
(card_number e markup_tier None) -> "" (comportamento do scanner); com proxies,
cai nos proxies do postprocess.
"""
from __future__ import annotations

import re
from typing import Optional

TRAINER_GALLERY_RE = re.compile(r'^(?:TG|GG)\d+', re.IGNORECASE)

CHASE_TIER_PATTERNS = {
    "TOP": [
        "special illustration rare", "sir", "illustration rare",
        "special art rare", "sar", "hyper rare", "ultra hyper rare",
        "secret rare", "rara secreta",
    ],
    "MID": [
        "full art", "alt art", "alternate art", "alternative art",
        "rainbow rare", "gold rare", "trainer gallery", "double rare",
        "rara hiper", "ultra rare",
    ],
    "MODEST": [
        "holo rare", "reverse holo", "reverse foil", "promo",
        "rare holo",
    ],
    "BULK": [
        "common", "comum", "uncommon", "incomum",
    ],
}
# Ordem de prioridade (alto->baixo) pra ranquear e filtrar --chase-only.
CHASE_TIER_ORDER = {"TOP": 3, "MID": 2, "MODEST": 1, "BULK": 0, "": -1}
# Tiers considerados "chase" pelo filtro --chase-only.
CHASE_ONLY_TIERS = {"TOP", "MID"}


def classify_chase_tier(rarity: Optional[str], card_number: Optional[str] = None,
                        markup_tier: Optional[str] = None) -> str:
    if rarity:
        r = str(rarity).lower().strip()
        for tier, patterns in CHASE_TIER_PATTERNS.items():
            if any(p in r for p in patterns):
                return tier
        return "MODEST"  # rarity presente mas nao mapeada (conservador)

    if card_number is None and markup_tier is None:
        return ""

    num = str(card_number or "").strip()
    if TRAINER_GALLERY_RE.match(num):
        return "MID"
    if "/" in num:
        try:
            n, total = num.split("/")[:2]
            if int("".join(c for c in n if c.isdigit())) > int("".join(c for c in total if c.isdigit())):
                return "TOP"
        except (ValueError, IndexError):
            pass
    mt = str(markup_tier or "").lower()
    if "non-vat" in mt or "+20%" in mt:
        return "MID"
    return "MODEST"
