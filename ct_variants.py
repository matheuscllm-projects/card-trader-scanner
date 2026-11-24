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

PRICE_LOGIC_VERSION = "4"

OK = "OK"
INCOMPATIVEL = "VARIANTE_INCOMPATIVEL"
NAO_ENCONTRADA = "CARTA_NAO_ENCONTRADA"
SEM_PRECO = "CARTA_SEM_PRECO"  # encontrada, mas nenhuma chave com market utilizavel
DESCONHECIDO = "desconhecido"

# Vocabulario de edicao/acabamento (importar daqui; nao redefinir em outros modulos).
ED_1ST, ED_UNL, ED_NONE = "1st", "unl", ""  # ED_NONE = carta sem divisao de edicao
FIN_NORMAL, FIN_HOLO, FIN_REVERSE = "normal", "holo", "reverse"

# Rotulos exibidos nas colunas `Edição` / `Acabamento` do XLSX do scanner (o postprocess le
# daqui). ED_NONE_LABEL = valor PROPRIO p/ carta sem divisao de edicao (moderno, EX, e-Card):
# distinto de "Unlimited" e da celula vazia (= "nao informada").
ED_NONE_LABEL = "Sem divisão de edição"
FIN_LABELS = {FIN_NORMAL: "Normal", FIN_HOLO: "Holo", FIN_REVERSE: "Reverse"}

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
            add_price_row(prices, key, sub, {"market": r.get("marketPrice")})
    return prices, ignored


def add_price_row(variants: dict, key: str, sub, row: dict) -> None:
    """B1j: o MESMO subTypeName duas vezes no mesmo produto. Preços iguais = uma linha; preços diferentes =
    chave AMBÍGUA (market None + `ambiguous`): nunca last-wins."""
    old = variants.get(key)
    if old is None or old.get("ambiguous") is None and old.get("market") == row.get("market"):
        variants[key] = row if old is None else old
        return
    if old.get("ambiguous"):
        return
    variants[key] = {"market": None, "low": None, "mid": None,
                     "ambiguous": f"referência ambígua: o produto tem 2 linhas '{sub}' com preços diferentes "
                                  f"({old.get('market')}; {row.get('market')})"}


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
_ALIASES = {"rare prism star": "prism rare",
            # grafia REAL da CardTrader (leitura 2026-11-24, fst 266/270/271): "Illustraion"
            "special illustraion rare": "special illustration rare"}
# Sets em que TODA carta é holofoil. Evidência (tcgcsv grupo 2409, 2026-11-24; ver
# tests/fixtures/variants/b1e_evidence.json): 18/18 cartas só têm chave Holofoil (0 Normal,
# 0 Reverse) e a CardTrader rotula as 18 como "Promo" (inconclusivo). Só `det`.
HOLO_ONLY_SETS = {"det": "Detective Pikachu: 18/18 cartas só têm Holofoil no TCGplayer"}
# Ultra/Secret Rare: tem excecao so ate esta data (ultima excecao observada: Ultra
# 2005-05-09 EX Emerald; Secret 2016-11-02 XY Evolutions). Daqui em diante, 0 excecao.
# B1f: Secret Rare: dado real (tcgcsv, 43 groups, 2026-11-24; tests/fixtures/variants/b1f_secret_evidence.json)
# = 0 exceção de 2008-11-05 (Stormfront) a 2016-08-03; as exceções são Skyridge, FRLG, Deoxys (antes)
# e XY Evolutions (2016-11-02, 5/5 só Normal) -> o corte vira 2008-11-05 e `evo` é exceção por set.
HOLO_FROM = {"ultra rare": "2005-05-10", "secret rare": "2008-11-05"}
HOLO_FROM_EXCEPT_SETS = {"secret rare": frozenset({"evo"})}
# "Rare" simples: holo so a partir de Scarlet & Violet (SV01 = 2023-03-31).
SV_START = "2023-03-31"


def _words(s: str) -> frozenset:
    return frozenset(_WORDS.findall(s.lower()))


_NATURAL = {_words(n) for n in HOLO_NATURAL_NAMES} | {_words(a) for a in _ALIASES}
_FROM = {_words(n): d for n, d in HOLO_FROM.items()}
_FROM_EXCEPT = {_words(n): s for n, s in HOLO_FROM_EXCEPT_SETS.items()}


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


def holo_detection(*rarities: Optional[str], set_released=None,
                   set_code: Optional[str] = None) -> HoloDetection:
    """Acabamento holo da oferta a partir da(s) raridade(s) (CardTrader, pokemontcg.io, tcgcsv).

    Qualquer rotulo holo vence. "Reverse" e "Non-Holo" nao contam (reverse e propriedade da
    oferta). `set_released` = data de lancamento do SET (o chamador passa); sem ela, "Rare"
    simples, Ultra Rare e Secret Rare ficam nao-holo (conservador) e `era_missing` avisa.
    """
    rel = _iso(set_released)
    needs_era = False
    if ((set_code or "").lower() in HOLO_ONLY_SETS
            and not any(_NON_HOLO.search((r or "").lower()) for r in rarities)          # "Non-Holo" explícito vence
            and not any(rarity_conclusive(r) for r in rarities if r)):                   # rótulo conclusivo vence
        return HoloDetection(True, False, "set")
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
        if cut is not None and (set_code or "").lower() in _FROM_EXCEPT.get(w, ()):
            continue                      # set com exceção comprovada em dado real (ex.: evo)
        if cut is not None:
            if rel is None:
                needs_era = True
            elif rel >= cut:
                return HoloDetection(True, False, "era")
    return HoloDetection(False, needs_era, "")


def rarity_conclusive(rarity: Optional[str]) -> bool:
    """A raridade da CardTrader permite decidir holo/nao-holo? Inconclusiva = vazia, "Promo" ou
    qualquer grafia fora das listas conhecidas (so p/ EXPLICAR o motivo; nao muda o casamento)."""
    rl = _NON_HOLO.sub("", (rarity or "").lower()).strip()
    if not rl:
        return False
    if "holo" in rl or "shining" in rl:
        return True
    w = _words(rl)
    return (w in _NATURAL or w in _FROM
            or w in (frozenset({"rare"}), frozenset({"common"}), frozenset({"uncommon"})))


def rarity_is_holo(*rarities: Optional[str], set_released=None,
                   set_code: Optional[str] = None) -> bool:
    return holo_detection(*rarities, set_released=set_released, set_code=set_code).is_holo


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


def edition_label(edicao: str, divided: bool) -> str:
    """Rotulo da coluna `Edição`. 1st e sempre "1st Edition" (atributo da oferta); a oferta
    nao-1st e "Unlimited" so se a carta tem divisao de edicao, senao ED_NONE_LABEL."""
    if edicao == ED_1ST:
        return _ED_LABEL[ED_1ST]
    return _ED_LABEL[ED_UNL] if divided else ED_NONE_LABEL


def is_divided(prices: dict) -> bool:
    """A carta tem chave de edicao (1stEdition*/unlimited*) entre as chaves conhecidas?"""
    return any(PTCG_KEY_TO_CANON[k][0] for k in (prices or {}) if k in PTCG_KEY_TO_CANON)


def is_exact(match: "Match", edicao: str, acabamento: str) -> bool:
    """`Ref Compatível` = Sim: Match OK cujo par e IDENTICO ao da oferta (sem rotulo de
    edicao so vale como Unlimited, e so em carta sem divisao)."""
    if match.status != OK or match.canon is None:
        return False
    ed, fin = match.canon
    return fin == acabamento and (ed == edicao or (ed == ED_NONE and edicao == ED_UNL))


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
    for k in sorted(known):      # B1j: chave certa AMBÍGUA (mesmo subtipo duas vezes, preços diferentes)
        c = PTCG_KEY_TO_CANON[k]
        if (prices[k] or {}).get("ambiguous") and c[1] == acabamento and c[0] in (ED_1ST if edicao == ED_1ST else ED_UNL, ED_NONE):
            return fail(INCOMPATIVEL, prices[k]["ambiguous"])
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
    # a chave certa EXISTE no produto mas sem preço: "encontrada, sem preço" (nunca vira outra chave)
    for k in sorted(known):
        c = PTCG_KEY_TO_CANON[k]
        if c[1] == acabamento and (c[0] == want_ed or (not divided and c[0] == ED_NONE)) and k not in pool:
            return fail(SEM_PRECO, f"a chave {k} ({want}) existe no produto mas sem preço (encontrada, sem preço; "
                                   f"disponíveis: {avail}){note}")
    return inc(f"sem preço {want}")


_PUBLISHED_OK = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00$")


def valid_published_on(value) -> Optional[str]:
    """`publishedOn` de group do tcgcsv -> 'YYYY-MM-DD' SÓ se tem o formato de data real
    (`...T00:00:00`). Em 2026-11-24, 19 groups (POP Series 1-9, EX Trainer Kits, promos...) trazem o
    CARIMBO DO LOTE (`2026-11-23T20:00:05.735172Z`): não é data de lançamento (None = era
    não informada -> detecção conservadora)."""
    m = _PUBLISHED_OK.match(str(value or "").strip())
    return m.group(1) if m else None


# DECISÃO DO DONO PENDENTE (ponto único e nomeado): raridades da CardTrader que NUNCA inferem o
# acabamento da referência — a oferta fica SEM referência compatível. Hoje: vazia e "Promo" (a CT não
# informa o acabamento). Outro rótulo INCONCLUSIVO (grafia que não conhecemos, ex.: "Fixed" nas cartas BREAK)
# + produto holo SEM nenhuma impressão normal = acabamento INFERIDO ("Inferido", nunca COMPRA).
NO_INFERENCE_CT_RARITIES = frozenset({"", "promo"})


# DECISÃO DO DONO PENDENTE (ponto único e nomeado): raridade CT vazia/"Promo" (não informa o acabamento)
# + referência com UMA única impressão não-reverse -> política por acabamento dessa impressão:
#   "inferir"        = casa como INFERIDO (margem exibida, nunca COMPRA)
#   "sem_referencia" = continua SEM referência compatível
# Mais de uma impressão não-reverse = INCOMPATIVEL (a oferta é de acabamento desconhecido). Hoje: a única
# impressão normal infere (wiz 76); a única holo fica sem referência (xybsp 187, wiz 9, nbsp 5).
INCONCLUSIVE_SINGLE_PRINT_POLICY = {"normal": "inferir", "holo": "inferir"}      # decisão do dono 2026-11-24 (opção B)


def _may_infer_from_reference(ct_rarity) -> bool:
    return str(ct_rarity or "").strip().lower() not in NO_INFERENCE_CT_RARITIES


class OfferMatch(NamedTuple):
    match: "Match"
    hd: "HoloDetection"
    offer: tuple
    inferred: Optional[str] = None   # texto da inferência (acabamento deduzido da referência) ou None = DECLARADO


def _known(prices: dict) -> dict:
    """{chave: (edicao, acabamento)} das chaves CANÔNICAS que EXISTEM no produto, com ou sem preço."""
    return {k: PTCG_KEY_TO_CANON[k] for k in (prices or {}) if k in PTCG_KEY_TO_CANON}


def match_offer(prices: dict, first_edition: bool, reverse: bool, ct_rarity: Optional[str],
                ref_rarity: Optional[str] = None, set_released=None, set_code: Optional[str] = None,
                group_name: Optional[str] = None) -> OfferMatch:
    """Caminho INTEIRO: acabamento da oferta (a partir das raridades) + casamento exato.

    A existência de uma impressão é dada pela CHAVE no produto, com ou sem preço (um normal sem
    market hoje continua sendo uma impressão normal que existe).

    DECLARADO: o acabamento sai do rótulo da própria CardTrader (era e set) e a referência tem a chave
    igual. INFERIDO (`inferred` preenchido; o chamador marca "Inferido" e nunca recomenda compra): a
    CardTrader diz outra coisa/não diz e o acabamento foi deduzido da referência: (a) raridade
    CT conclusiva p/ não-holo, produto holo e a carta SEM nenhuma chave normal (Rayquaza viv 138);
    (b) override de set holo-only (det). Se a carta TEM impressão normal e as raridades divergem =
    INCOMPATIVEL ("raridades em conflito"); CT inconclusiva + as duas impressões = INCOMPATIVEL."""
    known = _known(prices)
    normal_keys = sorted(k for k, c in known.items() if c[1] == FIN_NORMAL)
    has_holo = any(c[1] == FIN_HOLO for c in known.values())
    hd_ct = holo_detection(ct_rarity, set_released=set_released, set_code=set_code)
    hd, inferred, blocked = hd_ct, None, None
    if reverse:
        hd = holo_detection(ct_rarity, ref_rarity, set_released=set_released, set_code=set_code)
    elif hd_ct.is_holo:
        if hd_ct.basis == "set":
            inferred = (f"acabamento holo inferido pelo set {set_code} ({HOLO_ONLY_SETS[set_code.lower()]}); "
                        f"a CardTrader diz {ct_rarity!r}")
    elif not rarity_conclusive(ct_rarity) and not _NON_HOLO.search(str(ct_rarity or "").lower()):
        # B1j-A1: QUALQUER rótulo inconclusivo (vazio, "Promo", "Fixed", desconhecido): a CardTrader NÃO informa
        # o acabamento -> nada é "declarado"; só a política de única impressão pode inferir (nunca "Sim")
        labeled = any(c[0] for c in known.values())
        want_ed = ED_1ST if first_edition else ED_UNL
        pool = {k: c for k, c in known.items() if c[1] != FIN_REVERSE and (not labeled or c[0] == want_ed)}
        fins = sorted({c[1] for c in pool.values()})
        if len(fins) > 1:
            blocked = (f"acabamento da oferta desconhecido (raridade CardTrader {ct_rarity!r} inconclusiva) e a "
                       f"carta tem mais de uma impressão não-reverse ({', '.join(sorted(pool))}); não se presume")
        elif len(fins) == 1 and fins[0] == FIN_NORMAL and INCONCLUSIVE_SINGLE_PRINT_POLICY.get(FIN_NORMAL) == "inferir":
            hd = HoloDetection(False, False, "")
            inferred = (f"raridade {ct_rarity if ct_rarity else 'vazia'!r} não informa o acabamento; a referência "
                        f"só tem a impressão normal")
        elif len(fins) == 1 and fins[0] == FIN_HOLO and INCONCLUSIVE_SINGLE_PRINT_POLICY.get(FIN_HOLO) == "inferir":
            hd = HoloDetection(True, False, "")
            inferred = (f"raridade {ct_rarity if ct_rarity else 'vazia'!r} não informa o acabamento; a referência "
                        f"só tem a impressão holo")
        elif len(fins) == 1 and fins[0] == FIN_HOLO and _may_infer_from_reference(ct_rarity):
            # rótulo desconhecido (não vazio/Promo) + única impressão holo: infere só se o PRODUTO é holo (BREAK)
            hd_ref = holo_detection(ref_rarity, set_released=set_released, set_code=set_code)
            if hd_ref.is_holo:
                hd = hd_ref
                inferred = (f"CardTrader {ct_rarity!r} inconclusiva; acabamento holo deduzido da referência "
                            f"({ref_rarity!r}, sem impressão normal)")
            elif hd_ref.era_missing:
                hd = HoloDetection(False, True, "")
    else:
        hd_ref = holo_detection(ref_rarity, set_released=set_released, set_code=set_code)   # exceções de era valem p/ os 2 lados
        if hd_ref.is_holo:
            if rarity_conclusive(ct_rarity):
                if normal_keys:
                    blocked = (f"raridades em conflito (CardTrader: {ct_rarity!r}; referência: {ref_rarity!r}) — "
                               f"a carta tem impressão normal ({', '.join(normal_keys)}); o acabamento não é presumido")
                else:
                    hd = hd_ref
                    inferred = (f"CardTrader diz {ct_rarity!r} (não-holo) e a referência diz {ref_rarity!r} (holo); "
                                "a carta não tem nenhuma impressão normal, então o acabamento foi deduzido da referência")
            elif normal_keys and has_holo:
                blocked = (f"acabamento da oferta desconhecido (raridade CardTrader {ct_rarity!r} inconclusiva) e a "
                           f"carta tem as duas impressões ({', '.join(normal_keys)} e holofoil); não se presume")
            elif not normal_keys and _may_infer_from_reference(ct_rarity):
                hd = hd_ref
                inferred = (f"CardTrader {ct_rarity!r} inconclusiva; acabamento holo deduzido da referência "
                            f"({ref_rarity!r}, sem impressão normal)")
        elif hd_ref.era_missing:
            hd = HoloDetection(False, True, "")
    offer = offer_variant(first_edition, reverse, hd.is_holo)
    if blocked:
        avail = ", ".join(sorted(_usable(prices)))
        return OfferMatch(Match(None, INCOMPATIVEL, f"{blocked} (disponíveis: {avail})", None), hd, offer, None)
    m = match_reference_variant(prices, *offer, group_name=group_name, era_missing=hd.era_missing)
    return OfferMatch(m, hd, offer, inferred if m.status == OK else None)


# ─── B1i: colisão de chave no índice da referência ───────────────────────────
def _norm_name(x) -> str:
    return re.sub(r"\s+", " ", str(x or "").strip().lower())


def _full_number(raw) -> tuple:
    """'08/53' -> ('8', '53'); '008' -> ('8', None); letras preservadas; zeros à esquerda de cada run
    numérico removidos (mesma ideia da chave do tcgcsv)."""
    s = str(raw or "").strip().upper()
    num, _, den = s.partition("/")

    def z(t):
        return re.sub(r"(?<!\d)0+(?=\d)", "", t.strip())
    return (z(num), z(den) if den.strip() else None)


def resolve_candidates(cands: list, card_name, collector_number):
    """Vários PRODUTOS da referência com a mesma chave (numerador). Devolve (candidato|None, motivo).

    Só casa se um dado DECLARADO da oferta desempata de forma inequívoca: (1) número COMPLETO com
    denominador igual ao do produto; (2) nome EXATO do produto (igualdade após caixa/espaços, sem prefixo/substring); denominador declarado que
    contradiz todos os candidatos = ambígua. Critérios que apontam produtos diferentes,
    ou que não reduzem a lista a exatamente um, = ambígua. Nunca ordem de chegada, preço ou nome parcial."""
    n = len(cands)
    if n <= 1:
        return (cands[0] if cands else None), ""
    lists = []
    if "/" in str(collector_number or ""):
        off_num = _full_number(collector_number)
        a = [c for c in cands if "/" in str(c.get("number") or "") and _full_number(c.get("number")) == off_num]
        if a:
            lists.append(a)
        elif off_num[1] is not None:   # B1l: denominador declarado contradiz TODOS os candidatos -> o nome nao desempata
            names = "; ".join(f"{c.get('name')} [{c.get('number')}]" for c in cands[:4])
            return None, (f"referência ambígua: o denominador declarado ({collector_number}) não confere com nenhum "
                          f"dos {n} produtos ({names}{'…' if n > 4 else ''})")
    b = [c for c in cands if _norm_name(c.get("name")) == _norm_name(card_name)]
    if b:
        lists.append(b)
    if lists:
        pool = [c for c in cands if all(any(c is x for x in l) for l in lists)]   # todos os critérios aplicáveis concordam
        if len(pool) == 1:
            return pool[0], ""
    names = "; ".join(f"{c.get('name')} [{c.get('number')}]" for c in cands[:4])
    return None, f"referência ambígua: {n} produtos com a mesma chave ({names}{'…' if n > 4 else ''})"
