"""ct_variants.py - variante (edicao, acabamento) da oferta CardTrader e casamento
com as chaves de preco dos providers (spec-estrutural D1). Modulo PURO: sem rede,
sem estado.

Regra dura (dono, 2026-11-24): correspondencia EXATA de edicao e acabamento. Nenhuma
referencia de preco e associada a variante incompativel; sem chave compativel ->
INCOMPATIVEL (nunca um palpite) e o chamador nao recomenda compra.
"""
from __future__ import annotations

import math
import re
from typing import NamedTuple, Optional

PRICE_LOGIC_VERSION = "3"

OK = "OK"
INCOMPATIVEL = "VARIANTE_INCOMPATIVEL"
NAO_ENCONTRADA = "CARTA_NAO_ENCONTRADA"
SEM_PRECO = "CARTA_SEM_PRECO"  # encontrada, mas nenhuma chave com market utilizavel
DESCONHECIDO = "desconhecido"

# Vocabulario de edicao/acabamento (importar daqui; nao redefinir em outros modulos).
ED_1ST, ED_UNL, ED_NONE = "1st", "unl", ""  # ED_NONE = carta sem divisao de edicao
FIN_NORMAL, FIN_HOLO, FIN_REVERSE = "normal", "holo", "reverse"

# chave pokemontcg.io -> (edicao, acabamento). So grafias vistas em dado real
# (pokemontcg.io neo1/ex1; "1stEditionNormal" nunca apareceu: fora).
PTCG_KEY_TO_CANON = {
    "normal": (ED_NONE, FIN_NORMAL),
    "holofoil": (ED_NONE, FIN_HOLO),
    "reverseHolofoil": (ED_NONE, FIN_REVERSE),
    "1stEdition": (ED_1ST, FIN_NORMAL),
    "1stEditionHolofoil": (ED_1ST, FIN_HOLO),
    "unlimited": (ED_UNL, FIN_NORMAL),
    "unlimitedHolofoil": (ED_UNL, FIN_HOLO),
}

# subTypeName do tcgcsv -> chave no vocabulario pokemontcg.io. Os 7 abaixo sao TODOS
# os subTypeName vistos em tcgcsv 604/605/635/1372/1374/1396/1663/23473 (2026-11-24).
TCGCSV_SUBTYPE_TO_VARIANT = {
    "Normal": "normal",
    "Holofoil": "holofoil",
    "Reverse Holofoil": "reverseHolofoil",
    "1st Edition": "1stEdition",
    "1st Edition Holofoil": "1stEditionHolofoil",
    "Unlimited": "unlimited",
    "Unlimited Holofoil": "unlimitedHolofoil",
}


class Match(NamedTuple):
    key: Optional[str]      # chave original do provider (None se nao casou)
    status: str             # OK | INCOMPATIVEL | NAO_ENCONTRADA | SEM_PRECO
    reason: str
    canon: Optional[tuple]  # (edicao, acabamento) da chave casada, p/ o chamador auditar


def tcgcsv_variant(subtype) -> str:
    """subTypeName do tcgcsv -> chave ptcg, ou DESCONHECIDO (nunca KeyError)."""
    if not isinstance(subtype, str):
        return DESCONHECIDO
    return TCGCSV_SUBTYPE_TO_VARIANT.get(subtype, DESCONHECIDO)


def map_tcgcsv_prices(rows) -> tuple[dict, list]:
    """Linhas de preco do tcgcsv ({subTypeName, marketPrice}) -> ({chave_ptcg: {"market"}},
    [subTypeName ignorados])."""
    prices, ignored = {}, []
    for r in rows or []:
        sub = r.get("subTypeName") if isinstance(r, dict) else None
        key = tcgcsv_variant(sub)
        if key == DESCONHECIDO:
            ignored.append(sub)
        else:
            prices[key] = {"market": r.get("marketPrice")}
    return prices, ignored


_NON_HOLO = re.compile(r"non[\s_-]*holo")
_WORDS = re.compile(r"[a-z0-9]+")

# Raridades holo-POR-NATUREZA: em dado real do tcgcsv (150 grupos, 2026-11-24;
# tests/fixtures/variants/rarity_evidence.json) TODAS as cartas com a raridade tem so
# chave holofoil entre as nao-reverse (0 excecao, >=5 cartas). Grafia tcgcsv, minuscula.
# Raridade com excecao (Ultra/Secret Rare, Promo, Rare) fica fora ou depende de era.
HOLO_NATURAL_NAMES = (
    "illustration rare", "special illustration rare", "hyper rare", "ace spec rare",
    "double rare", "shiny rare", "rainbow rare", "radiant rare", "amazing rare",
    "rare break", "rare ace", "prism rare", "shiny ultra rare", "mega hyper rare",
    "mega attack rare", "classic collection",
)
# Grafias de ptcg.io com palavras diferentes das do tcgcsv (alias por nome; a ordem
# de palavras ja e normalizada pelo conjunto de palavras).
_ALIASES = {"rare prism star": "prism rare"}
# Ultra/Secret Rare: tem excecao so ate esta data (ultima excecao observada: Ultra
# 2005-05-09 EX Emerald; Secret 2016-11-02 XY Evolutions). Daqui em diante, 0 excecao.
HOLO_FROM = {"ultra rare": "2005-05-10", "secret rare": "2016-11-03"}
# "Rare" simples: holo so a partir de Scarlet & Violet (SV01 = 2023-03-31).
SV_START = "2023-03-31"


def _words(s: str) -> frozenset:
    return frozenset(_WORDS.findall(s.lower()))


_NATURAL = {_words(n) for n in HOLO_NATURAL_NAMES} | {_words(a) for a in _ALIASES}
_FROM = {_words(n): d for n, d in HOLO_FROM.items()}


def _iso(d) -> Optional[str]:
    """data de lancamento do set -> 'YYYY-MM-DD' (aceita date, 'YYYY-MM-DD' e 'YYYY/MM/DD')."""
    if hasattr(d, "isoformat"):
        d = d.isoformat()
    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", str(d or ""))
    return "-".join(m.groups()) if m else None


class HoloDetection(NamedTuple):
    is_holo: bool
    era_missing: bool  # True: alguma raridade dependia da era do set e ela nao foi informada
    basis: str         # texto | natureza | era | ""


def holo_detection(*rarities: Optional[str], set_released=None) -> HoloDetection:
    """Acabamento holo da oferta a partir da(s) raridade(s) (CardTrader, pokemontcg.io, tcgcsv).

    Qualquer rotulo holo vence. "Reverse" e "Non-Holo" nao contam (reverse e propriedade da
    oferta). `set_released` = data de lancamento do SET (o chamador passa); sem ela, "Rare"
    simples, Ultra Rare e Secret Rare ficam nao-holo (conservador) e `era_missing` avisa.
    """
    rel = _iso(set_released)
    needs_era = False
    for r in rarities:
        rl = _NON_HOLO.sub("", (r or "").lower())
        if not rl or "reverse" in rl:
            continue
        if "holo" in rl or "shining" in rl:
            return HoloDetection(True, False, "texto")
        w = _words(rl)
        if w in _NATURAL:
            return HoloDetection(True, False, "natureza")
        cut = SV_START if w == frozenset({"rare"}) else _FROM.get(w)
        if cut is not None:
            if rel is None:
                needs_era = True
            elif rel >= cut:
                return HoloDetection(True, False, "era")
    return HoloDetection(False, needs_era, "")


def rarity_is_holo(*rarities: Optional[str], set_released=None) -> bool:
    return holo_detection(*rarities, set_released=set_released).is_holo


def offer_variant(first_edition: bool, reverse: bool, is_holo: bool) -> tuple[str, str]:
    """(edicao, acabamento) da oferta. Reverse vence holo."""
    return (ED_1ST if first_edition else ED_UNL,
            FIN_REVERSE if reverse else (FIN_HOLO if is_holo else FIN_NORMAL))


def _esc(x) -> str:
    return str(x).replace("\\", "\\\\").replace(":", "\\:")


def offer_uid(blueprint_id, seller, condition, first_edition: bool, reverse: bool) -> str:
    """Injetivo: ':' e '\\' dentro dos campos sao escapados; tipo normalizado (1 == "1")."""
    return (f"{_esc(blueprint_id)}:{_esc(seller)}:{_esc(condition)}:"
            f"{'1st' if first_edition else 'unl'}:{'rev' if reverse else 'std'}")


def price_cache_key(set_code, number, name, first_edition: bool, foil: bool,
                    is_holo: bool) -> str:
    return (f"pokemontcg:{PRICE_LOGIC_VERSION}:{_esc(set_code)}:{_esc(number)}:{_esc(name)}:"
            f"fe={int(first_edition)}:rev={int(foil)}:holo={int(is_holo)}")


def _market(v) -> Optional[float]:
    """market como float finito > 0; aceita numpy/Decimal; rejeita bool, str, inf, NaN."""
    m = v.get("market") if isinstance(v, dict) else None
    if m is None or isinstance(m, (bool, str, bytes)) or type(m).__name__ in ("bool", "bool_"):
        return None
    try:
        f = float(m)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _usable(prices: dict) -> dict:
    """{chave: (edicao, acabamento)} so das chaves conhecidas com market valido."""
    return {k: PTCG_KEY_TO_CANON[k] for k, v in (prices or {}).items()
            if k in PTCG_KEY_TO_CANON and _market(v) is not None}


def available_keys(prices: dict) -> list[str]:
    return sorted(_usable(prices))


_FIN_LABEL = {FIN_NORMAL: "Normal", FIN_HOLO: "Holo", FIN_REVERSE: "Reverse Holo"}
_ED_LABEL = {ED_1ST: "1st Edition", ED_UNL: "Unlimited", ED_NONE: "Unlimited"}


def match_reference_variant(prices: dict, edicao: str, acabamento: str,
                            group_name: Optional[str] = None,
                            era_missing: bool = False) -> Match:
    """Correspondencia EXATA (edicao, acabamento) -> Match. Ver spec D1.3 + decisao do dono.

    `prices` TEM de ser do produto/grupo da propria carta. Edicao `unl`/"" so casa chave
    `unl`; chave sem rotulo (`normal/holofoil/reverseHolofoil`) so vale como Unlimited em
    carta sem NENHUMA chave de edicao (dado real: tcgcsv 604/605 e ptcg moderno);
    misturada com chaves de edicao e ambigua -> INCOMPATIVEL. Grupo "Shadowless" nunca e
    referencia. Nao ha tolerancia de acabamento (holo<->normal<->reverse).
    """
    def fail(status, msg):
        return Match(None, status, msg, None)

    if group_name and "shadowless" in group_name.lower():
        return fail(INCOMPATIVEL, f"grupo '{group_name}' (Shadowless) nunca é referência")
    if not prices:
        return fail(NAO_ENCONTRADA, "sem preços utilizáveis")
    known = [k for k in prices if k in PTCG_KEY_TO_CANON]
    if not known:
        ign = ", ".join(sorted(str(k) for k in prices))
        return fail(INCOMPATIVEL, f"só chaves desconhecidas (ignoradas: {ign})")
    usable = _usable(prices)
    if not usable:
        return fail(SEM_PRECO,
                    f"carta encontrada sem preço utilizável (chaves: {', '.join(sorted(known))})")
    avail = ", ".join(sorted(usable))
    want = f"{_ED_LABEL.get(edicao, edicao)} {_FIN_LABEL.get(acabamento, acabamento)}"

    note = " [era do set não informada: raridade tratada como não-holo]" if era_missing else ""

    def inc(msg):
        return fail(INCOMPATIVEL, f"{msg} (disponíveis: {avail}){note}")

    # carta "dividida" = tem chave de edicao (mesmo sem preco): chave sem rotulo e ambigua
    divided = any(PTCG_KEY_TO_CANON[k][0] for k in known)
    want_ed = ED_1ST if edicao == ED_1ST else ED_UNL
    if divided:
        pool = {k: c for k, c in usable.items() if c[0] == want_ed}
        unlabeled = sorted(k for k, c in usable.items() if c[0] == ED_NONE)
        if want_ed == ED_UNL and unlabeled and not pool:
            return inc(f"sem preço {want}: chave sem rótulo de edição ({', '.join(unlabeled)}) "
                       "misturada com chaves de edição, sem prova de que seja Unlimited")
    else:
        if want_ed == ED_1ST:
            return inc("sem preço 1st Edition")
        pool = usable
    for k, c in pool.items():
        if c[1] == acabamento:
            return Match(k, OK, "", c)
    return inc(f"sem preço {want}")
