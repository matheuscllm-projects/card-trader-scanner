"""ct_variants.py - variante (edicao, acabamento) da oferta CardTrader e casamento
com as chaves de preco dos providers (spec-estrutural D1). Modulo PURO: sem rede,
sem estado.

Regra dura: nunca associar preco a variante incompativel. Sem chave compativel
-> (None, "VARIANTE_INCOMPATIVEL", motivo), nunca um palpite.
"""
from __future__ import annotations

from typing import Optional

PRICE_LOGIC_VERSION = "3"

OK = "OK"
INCOMPATIVEL = "VARIANTE_INCOMPATIVEL"
NAO_ENCONTRADA = "CARTA_NAO_ENCONTRADA"

# chave pokemontcg.io -> (edicao, acabamento). edicao "" = carta sem divisao de edicao.
PTCG_KEY_TO_CANON = {
    "normal": ("", "normal"),
    "holofoil": ("", "holo"),
    "reverseHolofoil": ("", "reverse"),
    "1stEdition": ("1st", "normal"),
    "1stEditionNormal": ("1st", "normal"),
    "1stEditionHolofoil": ("1st", "holo"),
    "unlimited": ("unl", "normal"),
    "unlimitedHolofoil": ("unl", "holo"),
}

# subTypeName do tcgcsv -> chave no vocabulario pokemontcg.io (o resto do codigo
# continua lendo chaves ptcg).
TCGCSV_SUBTYPE_TO_VARIANT = {
    "Normal": "normal",
    "Holofoil": "holofoil",
    "Reverse Holofoil": "reverseHolofoil",
    "1st Edition": "1stEdition",
    "1st Edition Normal": "1stEditionNormal",
    "1st Edition Holofoil": "1stEditionHolofoil",
    "Unlimited": "unlimited",
    "Unlimited Holofoil": "unlimitedHolofoil",
}


def rarity_is_holo(*rarities: Optional[str]) -> bool:
    """True se QUALQUER rotulo de raridade indicar holo ("Holo Rare", "Rare Holo EX",
    "Rare Shining"). "Reverse" nao conta (e propriedade da oferta)."""
    for r in rarities:
        rl = (r or "").lower()
        if rl and "reverse" not in rl and ("holo" in rl or "shining" in rl):
            return True
    return False


def offer_variant(first_edition: bool, reverse: bool, is_holo: bool) -> tuple[str, str]:
    """(edicao, acabamento) da oferta. Reverse vence holo."""
    return ("1st" if first_edition else "unl",
            "reverse" if reverse else ("holo" if is_holo else "normal"))


def offer_uid(blueprint_id, seller: str, condition: str,
              first_edition: bool, reverse: bool) -> str:
    return (f"{blueprint_id}:{seller}:{condition}:"
            f"{'1st' if first_edition else 'unl'}:{'rev' if reverse else 'std'}")


def price_cache_key(set_code: str, number: str, name: str,
                    first_edition: bool, foil: bool, is_holo: bool) -> str:
    return (f"pokemontcg:{PRICE_LOGIC_VERSION}:{set_code}:{number}:{name}:"
            f"fe={int(first_edition)}:rev={int(foil)}:holo={int(is_holo)}")


def _usable(prices: dict) -> dict:
    """{chave: (edicao, acabamento)} so das chaves conhecidas com market > 0."""
    out = {}
    for k, v in (prices or {}).items():
        canon = PTCG_KEY_TO_CANON.get(k)
        m = v.get("market") if isinstance(v, dict) else None
        if canon and isinstance(m, (int, float)) and m > 0:
            out[k] = canon
    return out


def available_keys(prices: dict) -> list[str]:
    return sorted(_usable(prices))


def match_reference_variant(prices: dict, edicao: str, acabamento: str,
                            is_holo: Optional[bool] = None
                            ) -> tuple[Optional[str], str, str]:
    """-> (chave_original|None, status, motivo). Ver spec D1.3.

    `is_holo` so desempata quando existem normal E holo; default = acabamento=="holo".
    """
    usable = _usable(prices)
    avail = ", ".join(sorted(usable)) or "nenhuma"
    if not usable:
        return None, NAO_ENCONTRADA, "sem preços utilizáveis"
    if is_holo is None:
        is_holo = acabamento == "holo"

    def inc(msg):
        return None, INCOMPATIVEL, f"{msg} (disponíveis: {avail})"

    divided = any(c[0] for c in usable.values())
    if edicao == "1st":
        pool = {k: c for k, c in usable.items() if c[0] == "1st"}
        if not pool:
            return inc("sem preço 1st Edition")
    elif divided:  # unl (ou "") em carta dividida: so Unlimited
        pool = {k: c for k, c in usable.items() if c[0] == "unl"}
        if not pool:
            return inc("sem preço Unlimited")
    else:
        pool = usable

    if acabamento == "reverse":
        for k, c in pool.items():
            if c[1] == "reverse":
                return k, OK, ""
        return inc("sem preço Reverse Holo")

    cands = {k: c for k, c in pool.items() if c[1] != "reverse"}
    if not cands:
        return inc("só existe preço Reverse")
    if len(cands) == 1:  # impressao unica (shortcut da spec: moderno SV Rare, Base Set)
        return next(iter(cands)), OK, ""
    want = "holo" if is_holo else "normal"
    for k, c in cands.items():
        if c[1] == want:
            return k, OK, ""
    return inc(f"sem preço {want}")


def pc_slug_compatible(slug: str, edicao: str, acabamento: str) -> bool:
    """Pagina PriceCharting compativel com a oferta? So olha o ultimo segmento."""
    last = slug.rsplit("/", 1)[-1].lower()
    if ("-1st-edition-" in last) != (edicao == "1st"):
        return False
    return ("reverse" in last) == (acabamento == "reverse")
