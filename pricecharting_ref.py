"""Referência PriceCharting — mediana das vendas REAIS (sold listings) ungraded.

Metodologia aprovada pelo operador em 2026-08-28: pra sets vintage/back-catalog
a referência mais honesta não é o market price do TCGplayer (fino, infla por
variante errada), e sim as VENDAS CONCLUÍDAS que o PriceCharting agrega (eBay +
TCGPlayer). Este módulo busca a página pública da carta e devolve a MEDIANA das
N vendas ungraded mais recentes (mediana, não média — anti-outlier).

Invariantes da frota respeitados:
  - NUNCA inventa preço: busca que não casa nome+número (guarda de slug), página
    sem vendas, ou erro de rede → None. O consumidor mostra "—".
  - É coluna de SANIDADE na entrega (`--pc-refs` no postprocess): não muda a
    margem canônica nem a classificação COMPRA/REVISAR — espelho da coluna DH.

Scrape leve com urllib + cache SÓ DENTRO DO RUN, em memória (DELIVERY_CHAT: nunca
reutilizar preço de outro scan; `new_run()` zera; cada valor guarda quando foi
buscado — padrão validado no
ebay-arbitrage-scanner em 2026-06-09: HTTP 200 sem bloqueio; projetos da frota
não compartilham código — este arquivo adapta o padrão, não importa de lá).
"""
from __future__ import annotations

import datetime as _dt
import gzip
import html
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://www.pricecharting.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}
REQUEST_GAP_SECONDS = 2.0   # educação com o site
DEFAULT_CACHE_DIR = os.path.join("outputs", "pc_cache")
MEDIAN_WINDOW = 10          # mediana das 10 vendas mais recentes

_last_request_at = [0.0]
_run_cache: dict = {}   # (cache_dir, url) -> (body, fetched_at ISO); vale só neste run
_run_failures: dict = {}  # (cache_dir, url) -> exceção; falha NÃO é refeita no mesmo run


def new_run() -> None:
    """Começa um run novo: descarta páginas E falhas registradas (nenhuma página de
    outro scan é reusada). O CHAMADOR deve chamar `new_run()` no INÍCIO de cada
    coleta (antes de `set_firecrawl_budget`): sem isso, páginas e falhas de uma
    coleta anterior do mesmo processo vazam para a seguinte."""
    _run_cache.clear()
    _run_failures.clear()


class PcFetchError(RuntimeError):
    """Falha de busca com causa conhecida (a mensagem diz qual)."""


class FirecrawlBudgetExhausted(PcFetchError):
    """O teto de créditos Firecrawl do run acabou (ou foi alcançado) — status ORÇAMENTO."""


class FirecrawlRouteError(PcFetchError):
    """A rota Firecrawl foi tentada e falhou (chave ausente, erro HTTP, página vazia)."""


def page_fetched_at(url: str, cache_dir: str | None = None):
    """ISO da busca da página neste run, ou None se não foi buscada por fetch_page."""
    hit = _run_cache.get((cache_dir or DEFAULT_CACHE_DIR, url))
    return hit[1] if hit else None


_firecrawl_budget = [0]   # créditos Firecrawl liberados NESTE run (0 = rota paga desligada)
_firecrawl_used = [0]
_firecrawl_cap = [0]      # teto liberado neste run (0 = rota paga desligada)
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
FIRECRAWL_RETRY_WAIT_S = 3.0


MAX_FIRECRAWL_CREDITS_PER_RUN = 100   # teto por run autorizado pelo dono (2026-11-24)


def set_firecrawl_budget(n: int) -> None:
    """Libera até `n` páginas via Firecrawl quando o PriceCharting bloquear (403/429).

    O teto é "quem chega primeiro": a ORDEM DE PRIORIDADE (linhas de maior valor
    primeiro, para que o orçamento acabe nas de menor valor) é responsabilidade do
    CHAMADOR — este módulo não reordena nada. Acima de `MAX_FIRECRAWL_CREDITS_PER_RUN`
    → ValueError (o módulo recusa o orçamento; nada é configurado)."""
    if int(n or 0) > MAX_FIRECRAWL_CREDITS_PER_RUN:
        raise ValueError(f"orçamento Firecrawl {n} acima do teto de "
                         f"{MAX_FIRECRAWL_CREDITS_PER_RUN} créditos por run (autorização do dono)")
    _firecrawl_budget[0] = _firecrawl_cap[0] = max(0, int(n or 0))
    _firecrawl_used[0] = 0


def firecrawl_used() -> int:
    return _firecrawl_used[0]


def run_summary() -> dict:
    """Agregado do run: créditos Firecrawl gastos/teto, páginas buscadas e falhas
    registradas (cada URL que falhou conta uma vez; não é refeita no run)."""
    return {"firecrawl_creditos_gastos": _firecrawl_used[0],
            "firecrawl_teto": _firecrawl_cap[0],
            "paginas_buscadas": len(_run_cache),
            "falhas_registradas": len(_run_failures)}


def _firecrawl_scrape(url: str) -> str:
    """rawHtml da página via Firecrawl (chave em FIRECRAWL_API_KEY; nunca logada)."""
    import json
    key = (os.environ.get("FIRECRAWL_API_KEY") or "").strip().lstrip("﻿")
    if not key:
        raise RuntimeError("FIRECRAWL_API_KEY ausente — rota Firecrawl indisponível")
    payload = json.dumps({"url": url, "formats": ["rawHtml"], "onlyMainContent": False,
                          "maxAge": 0}).encode("utf-8")
    req = urllib.request.Request(FIRECRAWL_SCRAPE_URL, data=payload, method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read().decode("utf-8"))
    data = out.get("data") or {}
    status = (data.get("metadata") or {}).get("statusCode")
    html_body = data.get("rawHtml") or ""
    if not out.get("success", True) or not html_body or (status and int(status) >= 400):
        raise RuntimeError(f"Firecrawl falhou p/ {url} (status {status})")
    return html_body


def fetch_page(url: str, cache_dir: str | None = None) -> str:
    """Baixa uma página do PriceCharting; cache em memória válido só neste run.

    `cache_dir` só nomeia o escopo do cache (nada é lido/escrito em disco: o
    cache em disco reutilizava preço de outro scan). FALHA também fica registrada
    no run: a mesma URL não é refeita (nem gasta crédito Firecrawl de novo); a
    exceção original é relançada. `new_run()` zera páginas e falhas."""
    key = (cache_dir or DEFAULT_CACHE_DIR, url)
    if key in _run_cache:
        return _run_cache[key][0]
    if key in _run_failures:
        raise _run_failures[key]
    try:
        body = _fetch_uncached(url)
    except Exception as e:  # noqa: BLE001
        _run_failures[key] = e
        raise
    _run_cache[key] = (body, _dt.datetime.now().isoformat(timespec="seconds"))
    return body


def _fetch_uncached(url: str) -> str:
    wait = REQUEST_GAP_SECONDS - (time.time() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
        return data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # v2.29: PriceCharting passou a devolver 403 pra cliente HTTP comum
        # neste IP (2026-10-03, também via curl). Rota paga OPT-IN e COM TETO:
        # Firecrawl (1 crédito/página). Rota desligada → o HTTPError sobe (o
        # consumidor rotula "indisponível", nunca "sem venda"); teto alcançado →
        # FirecrawlBudgetExhausted; rota tentada e falhou → FirecrawlRouteError.
        if e.code not in (403, 429) or _firecrawl_cap[0] <= 0:
            raise
        if _firecrawl_budget[0] <= 0:
            raise FirecrawlBudgetExhausted(
                f"PriceCharting 403 e orçamento Firecrawl esgotado (teto {_firecrawl_cap[0]})") from e
        body, last_err = None, None
        for attempt in range(2):            # 1 nova tentativa (escada de desbloqueio)
            if _firecrawl_budget[0] <= 0:
                break
            if attempt:
                time.sleep(FIRECRAWL_RETRY_WAIT_S)
            _firecrawl_budget[0] -= 1
            _firecrawl_used[0] += 1
            try:
                body = _firecrawl_scrape(url)
                break
            except Exception as fe:  # noqa: BLE001
                last_err = fe
        if body is None:
            raise FirecrawlRouteError(f"PriceCharting 403 e Firecrawl falhou: {last_err}") from e
        return body
    finally:
        # Também em FALHA: senão, durante throttling, cada retry sai sem gap
        # (a espera era calculada do último SUCESSO) e martela o site.
        _last_request_at[0] = time.time()


_TR_RE = re.compile(r'<tr id="([^"]+)">(.*?)</tr>', re.S)
_DATE_CELL_RE = re.compile(r'<td class="date">\s*([^<]*?)\s*</td>')
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VOLUME_RE = re.compile(
    r'data-show-tab="completed-auctions-used"[^>]*>\s*<span[^>]*>volume:(?:&nbsp;|\s)*</span>'
    r'\s*<a[^>]*>([^<]+)</a>', re.S)
_PAGE_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def _row_title(row: str) -> str:
    t = _ROW_TITLE_RE.search(row)
    title = html.unescape(re.sub(r"<[^>]+>", " ", t.group(1) if t else ""))
    return re.sub(r"\s+", " ", _TITLE_NOISE_RE.sub(" ", title)).strip()


def _parse_rows(body: str) -> list[dict]:
    """TODAS as linhas da tabela ungraded, uma a uma (cada `<tr id="fonte-ID">`):
    `{date (texto cru), price (float|None), source, title}`. Linha sem preço fica com
    price=None — nunca herda o preço da vizinha. O id da TCGplayer NÃO é numérico
    (real: `tcgplayer-nvAA+SAKFVCy`), então o id é lido como texto livre."""
    m = re.search(r'<div class="completed-auctions-used"[^>]*>(.*?)</table>', body, re.S)
    if not m:
        return []
    rows = []
    for rid, row in _TR_RE.findall(m.group(1)):
        d, p = _DATE_CELL_RE.search(row), _ROW_PRICE_RE.search(row)
        rows.append({"date": d.group(1) if d else "",
                     "price": float(p.group(1).replace(",", "")) if p else None,
                     "source": rid.split("-", 1)[0], "title": _row_title(row)})
    return rows


def _parse_iso_date(text):
    """'YYYY-MM-DD' estrito e real (2026-13-45 e 2026-9-30 → None)."""
    if not isinstance(text, str) or not _ISO_DATE_RE.fullmatch(text):
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def parse_sold_listings(body: str) -> list[dict]:
    """Vendas UNGRADED da página da carta, de TODAS as fontes (eBay e TCGplayer):
    `{date, source, price, title}`. Só linhas com preço e data válidos (as demais
    são contadas por `demand_signal`). As vendas moram em
    `<div class="completed-auctions-used">`; as abas graded usam outras classes.
    Atenção: a aba "used" TAMBÉM traz lotes e cartas graduadas anunciadas como
    raw (ver `demand_signal`)."""
    return [r for r in _parse_rows(body)
            if r["price"] is not None and _parse_iso_date(r["date"])]


def parse_volume_label(body: str):
    """Texto literal do indicador de volume da linha Ungraded (ex. '1 sale per week'),
    ou None. Fica em `<tr class="sales_volume">`, 1ª célula (`completed-auctions-used`)."""
    m = _VOLUME_RE.search(body)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else None


def median_recent_sold(sales: list[dict], n: int = MEDIAN_WINDOW):
    """Mediana das `n` vendas mais recentes. Vazio → (None, 0) — nunca inventa."""
    if not sales:
        return None, 0
    recent = sorted(sales, key=lambda s: s["date"], reverse=True)[:n]
    prices = [s["price"] for s in recent]
    return statistics.median(prices), len(prices)


def norm_number(number) -> str:
    """Número CT → dígitos comparáveis com o slug PC.

    '004' → '4'; '95b/147' → '95' (variante a/b do e-Card colapsa no número
    base — o PC tem UMA página por número); '012/107' → '12'. Sem dígito → ''.
    """
    if number is None:
        return ""
    head = str(number).strip().split("/", 1)[0]
    digits = re.sub(r"\D", "", head)
    return digits.lstrip("0") or ("0" if digits else "")


def _norm_token(t: str) -> str:
    """'erika's' → 'erika' (possessivo cai — o PC mantém o apóstrofo no slug,
    ex. /game/pokemon-gym-challenge/erika's-venusaur-4); pontos caem
    ('lv.x' → 'lvx', casa o token do nome)."""
    t = t.lower().strip()
    if t.endswith("'s"):
        t = t[:-2]
    return t.replace("'", "").replace(".", "")


# Sufixo de nível da era DP ("Celebi Lv.39") — display do CT, não identidade da
# carta; o slug PC é só "celebi-7". "Lv.X" NÃO casa (X não é dígito): Lv.X é
# variante REAL que distingue carta e fica no nome.
_LEVEL_SUFFIX_RE = re.compile(r"(?i)\blv\.?\s*\d+\b")


def clean_card_name(card_name) -> str:
    """Nome CT → nome comparável/pesquisável: remove 'Lv.NN' e parênteses."""
    s = re.sub(r"\(.*?\)", "", str(card_name or ""))
    return _LEVEL_SUFFIX_RE.sub(" ", s).strip()


def _name_tokens(card_name) -> list[str]:
    """Tokens do nome, normalizados. Sem filtro de tamanho: 'N' (BW) é nome
    legítimo de 1 letra; o ruído de possessivo já cai no _norm_token."""
    name = clean_card_name(card_name).replace(".", "")
    return [t for t in
            (_norm_token(x) for x in
             re.findall(r"[a-z0-9']+", name.lower()))
            if t]


def slug_matches(path: str, card_name, number) -> bool:
    """Guarda anti-match-errado (por carta):

    1. o slug termina no MESMO número da carta;
    2. o PRIMEIRO token do slug é o primeiro token do nome — mata prefixo de
       outra carta ('dark-charizard-4' não casa 'Charizard');
    3. TODOS os tokens do nome aparecem no slug OU no console — 'charizard-6'
       não casa 'Charizard ex' (falta o 'ex'), mas 'Starmie δ Delta Species' →
       /game/pokemon-delta-species/starmie-30 casa (delta/species no console).

    Falhou → não usa (None). Review 2026-08-28: sem (2)/(3) a mediana entregue
    podia ser de OUTRA carta (ex/V/dark/light no mesmo console).
    """
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    console_tokens = {_norm_token(t) for t in parts[1].split("-")}
    slug = parts[-1].lower()
    num = norm_number(number)
    if not num or not re.search(rf"(?:^|-){re.escape(num)}$", slug):
        return False
    slug_tokens = [_norm_token(t) for t in slug.split("-")]
    tokens = _name_tokens(card_name)
    if not tokens or not slug_tokens or slug_tokens[0] != tokens[0]:
        return False
    pool = set(slug_tokens) | console_tokens
    return all(t in pool for t in tokens)


def _set_name_from_label(set_label) -> str:
    """'EX Emerald (em)' → 'EX Emerald'; sem parênteses → o próprio label."""
    s = str(set_label or "").strip()
    return s.rsplit(" (", 1)[0].strip() if " (" in s else s


def console_matches(path: str, set_label) -> bool:
    """Guarda de SET: o console do path (/game/{console}/{carta}) tem que conter
    todos os tokens do nome do set CT (o prefixo 'EX' cai — o PC não o usa:
    'EX Hidden Legends' → 'pokemon-hidden-legends').

    Sem isso o smoke de 2026-08-28 casou cross-set: Relicanth Hidden Legends →
    plasma-blast, Porygon Aquapolis → burning-shadows, Fire Energy Emerald →
    japanese-gx-battle-boost. Nome+número baterem em OUTRO set é FP clássico.
    """
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    console_tokens = {t for t in
                      (re.sub(r"[^a-z0-9]", "", x)
                       for x in parts[1].lower().split("-"))
                      if t} - {"pokemon"}
    set_tokens = {t for t in re.findall(r"[a-z0-9]+",
                                        _set_name_from_label(set_label).lower())
                  if t != "ex"}
    # Bidirecional (review 2026-08-28): além de conter todos os tokens do set,
    # o console não pode ter tokens EXTRAS ('pokemon-japanese-aquapolis' NÃO
    # casa 'Aquapolis' — a mediana da tiragem japonesa corromperia o sinal).
    if not set_tokens:
        return False
    if console_tokens == set_tokens:
        return True
    # v2.29: o PC prefixa sets da era SV com "scarlet-&-violet-" ("Scarlet &
    # Violet 151") e o CT chama só "151". Remove SÓ o prefixo de era e exige
    # igualdade exata do resto — token de idioma (japanese/chinese/korean)
    # continua sobrando e reprova; base set "Scarlet & Violet" segue exato.
    for prefix in _PC_ERA_PREFIXES:
        if prefix <= console_tokens and not (prefix <= set_tokens):
            rest = console_tokens - prefix
            if rest and rest == set_tokens:
                return True
    return False


_PC_ERA_PREFIXES = (frozenset({"scarlet", "violet"}),)


def search_card_urls(query: str, cache_dir: str | None = None) -> list[str]:
    """Busca no PriceCharting e devolve os paths /game/ dos resultados, na ordem.

    Os hrefs da página de busca vêm ABSOLUTOS (https://www.pricecharting.com/
    game/...) — verificado ao vivo em 2026-08-28; aceita relativo também. A carta
    certa pode estar longe da 1ª posição (Gardevoir Emerald apareceu na 41ª), por
    isso devolve TODOS e o chamador escolhe pelo slug.
    """
    q = urllib.parse.quote(query)
    url = f"{BASE_URL}/search-products?q={q}&type=prices"
    body = fetch_page(url, cache_dir=cache_dir)
    # v2.29: aspas simples OU duplas, e `&amp;` desescapado (HTML via Firecrawl
    # vem `pokemon-scarlet-&amp;-violet-151` — o regex antigo não casava).
    paths = [html.unescape(p) for p in re.findall(
        r"""href=["'](?:https?://www\.pricecharting\.com)?(/game/[^"'#?]+)["']""", body)]
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def resolve_pc_ref(card_name, number, set_label,
                   cache_dir: str | None = None, variant=None, edition=None) -> dict | None:
    """Nome+número+set → {'median', 'n_sales', 'url'} ou None (nunca inventa).

    Busca "pokemon <set> <nome> <número>", escolhe o PRIMEIRO resultado cujo
    slug casa nome+número (guarda anti-match-errado) e tira a mediana das
    vendas ungraded recentes. Nenhum resultado casa → None.

    `variant`: a variante PRICEADA da oferta CT (coluna Variant do raw, ex.
    'reverseHolofoil'). Oferta reverse tem que casar a página REVERSE do PC —
    caso real 2026-08-29: Breloom EX Deoxys reverse (ref TCG $180) saía com a
    mediana da página holo BASE ($15), comparando variantes diferentes.
    """
    path = _resolve_pc_path(card_name, number, set_label, cache_dir, variant,
                            edition=edition)
    if not path:
        return None
    try:
        page = fetch_page(BASE_URL + path, cache_dir=cache_dir)
    except Exception:  # noqa: BLE001 — rede/parse é best-effort; falha → "—"
        return None
    # ATENÇÃO (2026-11-24): o regex antigo só lia ids numéricos, então as vendas
    # reais da TCGplayer (id `tcgplayer-nvAA+SAKFVCy`) NUNCA entravam nesta mediana;
    # agora entram (eBay + TCGplayer, como o docstring do módulo sempre disse).
    median, n_sales = median_ungraded_sold(page)
    if median is None:
        return None
    return {"median": median, "n_sales": n_sales, "url": BASE_URL + path}


def median_ungraded_sold(body: str, n: int = MEDIAN_WINDOW):
    """ÚNICA mediana de referência: as `n` vendas mais recentes da página, EXCLUINDO
    graduadas, lotes e outro idioma (`_exclusion_reason`, o mesmo filtro do sinal de
    demanda). A página é a da edição já resolvida pelo chamador (`edition_slug_ok`).
    Sem venda comparável → (None, 0)."""
    sales = [s for s in parse_sold_listings(body) if _exclusion_reason(s.get("title")) is None]
    return median_recent_sold(sales, n)


FINISH_REVERSE_NAO_CONFIRMAVEL = "ACABAMENTO_REVERSE_NAO_CONFIRMAVEL"


def finish_status(variant) -> str:
    """Acabamento da página PC × oferta. LACUNA (2026-11-24): as 4 páginas reais em
    tests/fixtures/pricecharting_real/ não têm nenhum rótulo de acabamento (nem
    'reverse'; o título só rotula a edição), então NÃO há padrão provado para confirmar
    que uma página é a reverse. Oferta reverse → FINISH_REVERSE_NAO_CONFIRMAVEL; as
    demais → 'NAO_REVERSE' (a busca já recusa slugs com 'reverse' para elas). Para
    liberar reverse falta capturar UMA página real reverse (ex.: .../mr-mime-reverse-holo-95)."""
    return FINISH_REVERSE_NAO_CONFIRMAVEL if "reverse" in str(variant or "").lower() else "NAO_REVERSE"


EDITIONS = ("1st", "unl")   # vocabulário canônico (ct_variants.offer_variant)
_SLUG_1ST_RE = re.compile(r"(?:^|-)1st-edition(?:-|$)")   # token inteiro, início/meio/fim


def check_edition(edition) -> str:
    """Só '1st' ou 'unl' (ValueError para qualquer outra coisa, inclusive None/'')."""
    if edition not in EDITIONS:
        raise ValueError(f"edição inválida {edition!r}: use '1st' ou 'unl'")
    return edition


def edition_slug_ok(path: str, edition) -> bool:
    """ÚNICA regra de edição × slug PC. Real (2026-11-24): 1st Edition =
    `/game/pokemon-neo-genesis/lugia-1st-edition-9`, Unlimited = `.../lugia-9`.
    '1st' só aceita slug com o token `1st-edition` (token inteiro: 'pre1st-edition'
    não conta; no início do slug conta); 'unl' só quem NÃO tem. Edição inválida →
    ValueError. edition=None → sem filtro (legado: só resolve_pc_ref/resolve_ebay_ref)."""
    if edition is None:
        return True
    check_edition(edition)
    has_1st = bool(_SLUG_1ST_RE.search(path.rsplit("/", 1)[-1].lower()))
    return has_1st if edition == "1st" else not has_1st


def _resolve_pc_path(card_name, number, set_label, cache_dir=None, variant=None,
                     raise_errors: bool = False, edition=None):
    """Busca a página PC da carta com as guardas (slug nome+número, console =
    set, reverse ↔ reverse). Nenhuma casa / erro → None."""
    if edition is not None:
        check_edition(edition)     # fora do try abaixo: ValueError não vira None
    set_name = _set_name_from_label(set_label)
    base_name = clean_card_name(card_name)
    num = norm_number(number)
    query = " ".join(p for p in ("pokemon", set_name, base_name, num) if p)
    want_reverse = "reverse" in str(variant or "").lower()
    try:
        paths = search_card_urls(query, cache_dir=cache_dir)
        matches = [p for p in paths
                   if slug_matches(p, card_name, number)
                   and console_matches(p, set_label)
                   and edition_slug_ok(p, edition)]
        # Oferta reverse → SÓ página reverse (sem ela, None — nunca compara
        # variantes diferentes). Oferta não-reverse → só páginas sem 'reverse';
        # entre elas o slug mais CURTO = versão base ("mr-mime-95" vence
        # "mr-mime-holo-95"). Empate → ordem da busca.
        if want_reverse:
            matches = [p for p in matches
                       if "reverse" in p.rsplit("/", 1)[-1].lower()]
        else:
            matches = [p for p in matches
                       if "reverse" not in p.rsplit("/", 1)[-1].lower()]
        return min(matches, key=lambda p: len(p.rsplit("/", 1)[-1])) if matches else None
    except Exception:  # noqa: BLE001 — rede/parse é best-effort; falha → None
        if raise_errors:
            raise
        return None


# ─── v2.29: referência eBay (vendas concluídas) — fonte PRINCIPAL da razão ───
# Pedido do operador (2026-10-03): no screen "carta em outro idioma ≥ N× mais
# barata que a inglesa", a referência da carta INGLESA vem do eBay. A Browse API
# oficial só mostra anúncios ATIVOS; as vendas concluídas `[eBay]` estão na
# página pública da carta no PriceCharting (mesma fonte do ebay-arbitrage-scanner,
# `src/pc_sales.py` — adaptado aqui, projetos da frota não importam entre si).
EBAY_MIN_SALES = 3            # < 3 vendas comparáveis → None (nunca inventa)
EBAY_MAX_AGE_DAYS = 365
EBAY_MEDIAN_WINDOW = 10

_EBAY_ROW_RE = re.compile(r'<tr id="ebay-(\d+)">(.*?)</tr>', re.S)
_ROW_DATE_RE = re.compile(r'<td class="date">(\d{4}-\d{2}-\d{2})</td>')
_ROW_PRICE_RE = re.compile(r'class="js-price"[^>]*>\s*\$([\d,]+\.\d{2})')
_ROW_TITLE_RE = re.compile(r'<td class="title">(.*?)</td>', re.S)
_TITLE_NOISE_RE = re.compile(
    r"Time Warp shows photos of completed sales\..*?to see photos\.\s*(?:OK\b)?"
    r"|\[(?:eBay|TCGPlayer)\]", re.I | re.S)
# A referência é a carta INGLESA raw: venda de outro idioma, gradeada ou lote
# nunca é comparável (regras do ebay-arbitrage-scanner, pc_sales.py).
_FOREIGN_LANG_RE = re.compile(
    r"\b(japanese|japan|jpn|chinese|china|korean|korea|german|french|italian|"
    r"spanish|portuguese|thai|indonesian)\b", re.I)
_GRADED_RE = re.compile(
    r"\b(PSA|BGS|BECKETT|CGC|SGC|TAG|ACE|MNT|GMA|HGA|AGS|KSA|RCG|CSG)\s*-?\s*(10|[1-9](?:\.5)?)(?![\d.])"
    r"|\bTAG\s+score\b|\bgraded\b|\bslab\b", re.I)
_LOT_RE = re.compile(
    r"\b(lots?|bundle|playset|booster|sealed|collection|choose|pick|set\s+of|"
    r"x\s*\d{1,}|\d{1,}\s*x)\b|\bpacks?\b(?![\s-]*fresh)", re.I)


def parse_ebay_sales(body: str) -> list[dict]:
    """Vendas `[eBay]` da tabela UNGRADED (`completed-auctions-used`):
    `{date, price, title, source:'ebay', sale_id}`. TCGPlayer e abas graded fora."""
    m = re.search(r'<div class="completed-auctions-used"[^>]*>(.*?)</table>', body, re.S)
    if not m:
        return []
    out, seen = [], set()
    for sale_id, row in _EBAY_ROW_RE.findall(m.group(1)):
        if sale_id in seen:
            continue
        d, p = _ROW_DATE_RE.search(row), _ROW_PRICE_RE.search(row)
        if not d or not p:
            continue
        try:
            price = float(p.group(1).replace(",", ""))
        except ValueError:
            continue
        t = _ROW_TITLE_RE.search(row)
        title = html.unescape(re.sub(r"<[^>]+>", " ", t.group(1) if t else row))
        title = re.sub(r"\s+", " ", _TITLE_NOISE_RE.sub(" ", title)).strip()
        seen.add(sale_id)
        out.append({"date": d.group(1), "price": price, "title": title,
                    "source": "ebay", "sale_id": sale_id})
    return out


def ebay_comparable(sales: list[dict]) -> list[dict]:
    """Só vendas comparáveis à carta INGLESA raw (sem idioma estrangeiro,
    sem nota de gradeadora, sem lote/pack)."""
    return [s for s in sales
            if s.get("source") == "ebay"
            and not _FOREIGN_LANG_RE.search(s.get("title") or "")
            and not _GRADED_RE.search(s.get("title") or "")
            and not _LOT_RE.search(s.get("title") or "")]


def ebay_median_reference(sales: list[dict], today=None) -> dict | None:
    """Mediana das até 10 vendas mais recentes em 365 dias; exige ≥3. Senão None."""
    import datetime as _dt
    today = today or _dt.date.today()
    cutoff = (today - _dt.timedelta(days=EBAY_MAX_AGE_DAYS)).isoformat()
    recent = sorted((s for s in sales if s["date"] >= cutoff),
                    key=lambda s: s["date"], reverse=True)[:EBAY_MEDIAN_WINDOW]
    if len(recent) < EBAY_MIN_SALES:
        return None
    return {"median": statistics.median(s["price"] for s in recent),
            "n_sales": len(recent),
            "oldest": recent[-1]["date"], "newest": recent[0]["date"]}


def resolve_ebay_ref(card_name, number, set_label,
                     cache_dir: str | None = None, variant=None, edition=None) -> dict | None:
    """Nome+número+set (+variante) → {'median','n_sales','oldest','newest','url'}
    das vendas eBay comparáveis da carta INGLESA, ou None. Mesma guarda de
    página do `resolve_pc_ref` (slug nome+número, console = set, reverse ↔ reverse)."""
    # v2.29: ERRO de fonte (403, rede, Firecrawl sem orçamento) volta como
    # {'error': ...} — o consumidor rotula "eBay indisponível", distinto de
    # "sem venda eBay" (None). Confundir os dois esconde fonte quebrada.
    if edition is not None:
        check_edition(edition)
    try:
        path = _resolve_pc_path(card_name, number, set_label, cache_dir, variant,
                                raise_errors=True, edition=edition)
        if not path:
            return {"miss": "sem página PriceCharting casada"}
        page = fetch_page(BASE_URL + path, cache_dir=cache_dir)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:120]}
    comps = ebay_comparable(parse_ebay_sales(page))
    ref = ebay_median_reference(comps)
    if not ref or not ref["median"] or ref["median"] <= 0:
        # Motivo explícito (≠ erro de fonte, ≠ página não achada).
        return {"miss": f"<3 vendas eBay comparáveis em 365d ({len(comps)} no total)",
                "url": BASE_URL + path}
    ref["url"] = BASE_URL + path
    return ref


# ─── D5 (spec estrutural): sinal de demanda por vendas reais ungraded ────────
# Mesma página que o --pc-refs já baixa: zero requisição extra. Sem dado → status
# explícito, nunca zero presumido. A edição é OBRIGATÓRIA (só '1st' ou 'unl').
#
# Fatos medidos em páginas reais (Firecrawl, 2026-11-24; fixtures em
# tests/fixtures/pricecharting_real/, procedência em PROVENIENCIA.jsonl):
#  - a tabela mostra no máximo 30 linhas POR FONTE (eBay=30 nas 3 páginas com
#    mais vendas; TCGplayer=24 e 30). Fonte com 30 linhas pode estar cortada.
#  - as datas são só `YYYY-MM-DD`, SEM fuso. Aqui: "hoje" = data local da máquina;
#    venda com data > hoje+1 dia é tratada como futura (a margem de 1 dia cobre a
#    diferença de fuso EUA x Brasil); janelas comparam objetos `date`, não strings.
#  - a aba "used" traz lotes e cartas graduadas (PSA/CGC/TAG/ACE) vendidas como raw:
#    são excluídas e contadas (`pc_excluidas`).
DEMAND_WINDOWS_DAYS = (30, 90)
PC_ROWS_CAP_PER_SOURCE = 30      # observado, não documentado pelo site
FUTURE_MARGIN_DAYS = 1


def _demand_empty(status: str, url=None, motivo=None, fetched_at=None,
                  lidas=0, ignoradas=None, excluidas=None, volume=None, edition=None) -> dict:
    return {"pc_url": url, "pc_status": status, "pc_motivo": motivo,
            "pc_edicao": edition, "pc_volume_rotulo": volume,
            "pc_vendas_30d": None, "pc_vendas_90d": None, "pc_valor_90d_usd": None,
            "pc_ultima_venda": None, "pc_truncado": None, "pc_buscado_em": fetched_at,
            "pc_linhas_lidas": lidas,
            "pc_ignoradas": ignoradas or {"sem_preco": 0, "data_invalida": 0, "data_futura": 0},
            "pc_excluidas": excluidas or {"lote": 0, "graduada": 0, "idioma": 0},
            "pc_creditos_run": _firecrawl_used[0]}


def _exclusion_reason(title):
    """Venda não comparável à carta raw inglesa: 'graduada' | 'lote' | 'idioma' | None
    (mesmos filtros do `ebay_comparable`)."""
    title = title or ""
    if _GRADED_RE.search(title):
        return "graduada"
    if _LOT_RE.search(title):
        return "lote"
    if _FOREIGN_LANG_RE.search(title):
        return "idioma"
    return None


def _truncado(dates_by_source: dict, cut90):
    """True se alguma fonte atingiu o teto de 30 linhas e a mais antiga ainda está
    dentro da janela de 90d (a contagem é PISO); 'desconhecido' se alguma fonte passa
    do teto (a premissa do teto quebrou); senão False."""
    verdict = False
    for dates in dates_by_source.values():
        if dates and len(dates) >= PC_ROWS_CAP_PER_SOURCE and min(dates) >= cut90:
            if len(dates) == PC_ROWS_CAP_PER_SOURCE:
                return True
            verdict = "desconhecido"
    return verdict


def demand_signal(sales: list[dict], today=None, url=None, fetched_at=None,
                  volume=None, edition=None) -> dict:
    """Contagens 30/90d, valor 90d, última venda, `pc_truncado` e a contabilidade de
    tudo que ficou de fora. `sales` = linhas `{date, price, source, title}`.

    Fora do sinal, SEMPRE com contagem: `pc_ignoradas` (sem preço, data malformada,
    data futura) e `pc_excluidas` (lote, graduada, idioma estrangeiro; sobre todas
    as linhas válidas da tabela, qualquer data). Conta fecha:
    lidas = ignoradas + excluídas + usadas. Sem linhas → ZERO_VENDAS_LISTADAS;
    linhas só ignoradas/excluídas → SEM_VENDAS_COMPARAVEIS (números None)."""
    today = today or _dt.date.today()
    limit_future = today + _dt.timedelta(days=FUTURE_MARGIN_DAYS)
    cut30 = today - _dt.timedelta(days=DEMAND_WINDOWS_DAYS[0])
    cut90 = today - _dt.timedelta(days=DEMAND_WINDOWS_DAYS[1])
    ign = {"sem_preco": 0, "data_invalida": 0, "data_futura": 0}
    exc = {"lote": 0, "graduada": 0, "idioma": 0}
    kept, dates_by_source = [], {}
    for s in sales:
        d = _parse_iso_date(s.get("date"))
        if s.get("price") is None:
            ign["sem_preco"] += 1
        elif d is None:
            ign["data_invalida"] += 1
        elif d > limit_future:
            ign["data_futura"] += 1
        else:
            dates_by_source.setdefault(s.get("source"), []).append(d)
            reason = _exclusion_reason(s.get("title"))
            if reason:
                exc[reason] += 1
            else:
                kept.append((d, s["price"]))
    common = dict(url=url, fetched_at=fetched_at, lidas=len(sales), ignoradas=ign,
                  excluidas=exc, volume=volume, edition=edition)
    if not sales:
        return _demand_empty("ZERO_VENDAS_LISTADAS", motivo="tabela de vendas vazia", **common)
    if not kept:
        return _demand_empty("SEM_VENDAS_COMPARAVEIS", **common,
                             motivo="todas as linhas foram ignoradas ou excluídas (ver contagens)")
    in90 = [(d, p) for d, p in kept if d >= cut90]
    out = _demand_empty("OK", **common)
    out.update({"pc_vendas_30d": sum(1 for d, _ in kept if d >= cut30),
                "pc_vendas_90d": len(in90),
                "pc_valor_90d_usd": round(sum(p for _, p in in90), 2),
                "pc_ultima_venda": max(d for d, _ in kept).isoformat(),
                "pc_truncado": _truncado(dates_by_source, cut90)})
    return out


def _page_edition_matches(body: str, url, edition: str) -> bool:
    """A página é da edição pedida? Confere o slug da URL (se for /game/...) e o
    título real da página ('Lugia [1st Edition] #9 Prices' vs 'Lugia #9 Prices')."""
    if url and "/game/" in url and not edition_slug_ok(urllib.parse.urlparse(url).path, edition):
        return False
    t = _PAGE_TITLE_RE.search(body)
    if t:
        return ("[1st Edition]" in t.group(1)) == (edition == "1st")
    return True


def demand_from_page(body: str, edition, url=None, today=None, fetched_at=None) -> dict:
    """Parse da página já baixada. `edition` OBRIGATÓRIA ('1st'|'unl', senão
    ValueError). Página de outra edição → EDICAO_DIVERGENTE; sem a div
    `completed-auctions-used` → ESTRUTURA_NAO_RECONHECIDA (o HTML mudou ≠ zero vendas)."""
    check_edition(edition)
    if not _page_edition_matches(body, url, edition):
        return _demand_empty("EDICAO_DIVERGENTE", url, f"a página não é da edição {edition!r}",
                             fetched_at, edition=edition)
    if not re.search(r'<div class="completed-auctions-used"', body):
        return _demand_empty("ESTRUTURA_NAO_RECONHECIDA", url,
                             "div completed-auctions-used ausente", fetched_at, edition=edition)
    return demand_signal(_parse_rows(body), today, url, fetched_at,
                         volume=parse_volume_label(body), edition=edition)


def resolve_pc_demand(card_name, number, set_label, *, edition, cache_dir: str | None = None,
                      variant=None, today=None) -> dict:
    """Nome+número+set+edição → sinal de demanda da página PC COMPATÍVEL.

    `edition` OBRIGATÓRIA e só '1st' | 'unl' (ValueError caso contrário): nunca
    cai em "sem filtro". Nunca usa a página de outra edição; sem página →
    SEM_PAGINA_COMPATIVEL. Falhas, cada uma com status próprio: 403 sem rota paga →
    INDISPONIVEL_403; teto Firecrawl alcançado → INDISPONIVEL_ORCAMENTO; rota
    Firecrawl tentada e falhou → INDISPONIVEL_FIRECRAWL; outro erro (rede, etc.) →
    INDISPONIVEL_REDE. Falhas ficam registradas no run (não gastam crédito de novo).
    O chamador deve chamar `new_run()` no início de cada coleta e ordenar as linhas
    por prioridade (maior valor primeiro): o teto de créditos é "quem chega primeiro"."""
    check_edition(edition)
    url = None
    try:
        path = _resolve_pc_path(card_name, number, set_label, cache_dir, variant,
                                raise_errors=True, edition=edition)
        if not path:
            return _demand_empty("SEM_PAGINA_COMPATIVEL", None,
                                 f"nenhuma página PC casa nome+número+set+edição={edition}",
                                 edition=edition)
        url = BASE_URL + path
        page = fetch_page(url, cache_dir=cache_dir)
    except FirecrawlBudgetExhausted as e:
        return _demand_empty("INDISPONIVEL_ORCAMENTO", url, str(e)[:120], edition=edition)
    except FirecrawlRouteError as e:
        return _demand_empty("INDISPONIVEL_FIRECRAWL", url, str(e)[:120], edition=edition)
    except urllib.error.HTTPError as e:
        return _demand_empty("INDISPONIVEL_403" if e.code in (403, 429) else "INDISPONIVEL_REDE",
                             url, f"HTTP {e.code}", edition=edition)
    except Exception as e:  # noqa: BLE001
        return _demand_empty("INDISPONIVEL_REDE", url, f"{type(e).__name__}: {e}"[:120],
                             edition=edition)
    return demand_from_page(page, edition, url, today, page_fetched_at(url, cache_dir))
