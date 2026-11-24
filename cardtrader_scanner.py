#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║     CardTrader Arbitrage Scanner — Pokémon TCG Singles             ║
║                                                                      ║
║  Compara preços de singles (EN, Near Mint, não-graded) no           ║
║  cardtrader.com vs preço TCG Player (market price).                 ║
║  Gera planilha .xlsx com alertas de arbitragem (default ≥ 30%).     ║
╚══════════════════════════════════════════════════════════════════════╝

Por que CardTrader em vez de MYP?
    MYP é Brasil (compra em BRL) → o scanner MYP busca cartas baratas no
    Brasil para exportar aos EUA. Já o CardTrader é marketplace europeu
    (Itália) → agregador de sellers da UE com preços em EUR. Oportunidade:
    cartas valorizadas no mercado US que estão desatualizadas na UE.
    Setup inverso, mesma tese.

Modelo operacional (2026-06-06, decisão do operador — SUPERSEDE o × 1.06):
    A margem reportada é BRUTA. Nenhuma taxa é embutida pelo scanner:

        margem bruta = (preço de referência TCG − preço do site CT) / TCG

    O operador calcula Hub fee, frete, cartão e IOF POR FORA, manualmente.
    Por isso `--hub-fee` agora tem DEFAULT 0.0 e `--shipping-brl` segue 0.0.
    (Histórico: até v2.11 o scanner embutia 6% de Hub fee — `custo = preço × 1.06`.
    Quem quiser reproduzir aquele comportamento passa `--hub-fee 0.06`.)

Uso:
    python cardtrader_scanner.py                          # Scan padrão
    python cardtrader_scanner.py --sets sv1 sv2 sv3       # Sets específicos
    python cardtrader_scanner.py --threshold 35           # Margem mín 35%
    python cardtrader_scanner.py --min-price-usd 15       # Preço mín USD
    python cardtrader_scanner.py --dry-run                # Usa só cache
    python cardtrader_scanner.py --provider justtcg       # Troca pricing API

Env vars (arquivo .env na mesma pasta):
    CT_JWT=<JWT do CardTrader: Settings → API Access → Create New Token>
    POKEMONTCG_API_KEY=<opcional, grátis em pokemontcg.io/dev>
    JUSTTCG_API_KEY=<opcional, se usar provider justtcg>

Requisitos:
    pip install requests openpyxl python-dotenv pyyaml

Autor: Elizandra / Claude
Data: 2026-04-20 (v1.0) | 2026-04-29 (v2.1) | 2026-05-12 (v2.2 + v2.3)
      | 2026-05-16 (v2.5) | 2026-05-18 (v2.7/v2.8) | 2026-05-19 (v2.9/v2.10)
      | 2026-06-02 (v2.11) | 2026-06-06 (v2.12) | 2026-06-15 (v2.14/v2.15)
      | 2026-06-20 (v2.17/v2.18) | 2026-06-21 (v2.19/v2.20/v2.21)
      | 2026-06-22 (v2.22) | 2026-06-23 (v2.23) | 2026-06-26 (v2.24)
      | 2026-07-03 (v2.25) | 2026-08-22 (v2.26) | 2026-08-28 (v2.27)
Versão: v2.29
    (v2.27 vive no cardtrader_postprocess.py + pricecharting_ref.py — flag
     --pc-refs, mediana de vendas reais do PriceCharting na entrega; este
     scanner não mudou nessa versão.)
    (= changelog inline mais recente. Manter em sync ao adicionar novos blocos
     de changelog abaixo.)

Changelog v2.25 (2026-07-03 — fix no POSTPROCESS; bookkeeping registrado 2026-07-20):
  - [BUG #52] Linhas near-miss (abaixo do threshold, persistidas desde o
    contrato v2.22) chegam ao postprocess SEM lucro_liq/net_margin e caíam
    TODAS em "Dados insuficientes" no classify_decision, mesmo com
    --revisar-min-net rebaixado de propósito. Fix no cardtrader_postprocess.py:
    net_margin/lucro_liq recomputados SÓ onde faltam; linha validada (valor
    real da validação per-blueprint) não muda. Nenhuma mudança NESTE arquivo —
    o bump aqui é o bookkeeping do stack (era a pendência (a) do CLAUDE.md).

Changelog v2.24 (2026-06-26 — guard reverse-outlier pra vintage barato não-holo):
  - [BUG] No scan vintage 2026-06-26, 16/40 "deals" referenciaram o
    `reverseHolofoil` da pokemontcg.io. Pra commons/uncommons da era EX esses
    listings SÃO genuinamente reverse (foil=True), então a seleção de variante
    acerta ao cair em reverseHolofoil — MAS o `reverseHolofoil.market` pra
    vintage barato é um número fino, dirigido por outlier, NÃO uma âncora líquida.
    Ex.: Lileep ex12-56 Common normal $0.55 vs reverse $37.50 = 68×. Esses
    passaram como COMPRA limpa porque a flag v2.18 "Variante Baixa Confiança"
    deliberadamente NÃO dispara pra reverse genuíno (exclusão pensada pra Holo
    Rares, onde reverse é o fallback intencional). Buraco: non-holo casando em
    reverseHolofoil com razão reverse/normal absurda.
  - [FIX — sinal-only, NÃO mexe na margem] Estende a flag "Variante Baixa
    Confiança" pra TAMBÉM disparar quando: (1) variante == reverseHolofoil, (2)
    carta NÃO intrinsecamente holo (`_rarity_is_holo` False), (3) existe
    `normal.market` E `reverseHolofoil.market` > RATIO × normal.market (RATIO =
    `REVERSE_NONHOLO_OUTLIER_RATIO`, default 5.0). Se `normal.market` ausente,
    NÃO dispara (tipicamente holo rares, já excluídas por #2). Verificado nos
    dados reais: flagga Lileep(68×)/Slugma(56×)/Kakuna(57×)/Persian(22×)/
    Volbeat(14×); NÃO flagga Zubat ecard3-118 Skyridge (3.1×, prêmio reverse real).
  - [ROTEAMENTO] O postprocess agora LÊ a coluna "Variante Baixa Confiança" e
    força REVISAR ("validar manual") nas linhas que SERIAM COMPRA limpa — fim do
    "clean COMPRA" com âncora de variante suspeita. Aplicado por último em
    classify_decision: NÃO promove um NAO (margem/TG/STALE seguem NAO); só rebaixa
    COMPRA→REVISAR. Margem/preço/bucket INALTERADOS.
  - [PLUMBING] Providers expõem `last_normal_market` (pokemontcg live + cache hit
    + tcgcsv); `Cache.get_price` extrai `normal.market` do raw cacheado (run
    diário usa cache). Helper module-level `_reverse_nonholo_market_outlier`.
  - Testes: +22 (`tests/test_reverse_lowvalue_guard.py`) → 172 no total.

Changelog v2.22 (2026-06-22 — contrato de entrega scanner→postprocess + GG## scan-time + fix dir XLSX):
  - [CONTRATO] keep_all_priced (default ON): o scanner agora PERSISTE todo
    listing precificado no XLSX, mesmo abaixo do threshold (Opportunity.below_threshold);
    o threshold vira classificação downstream. Fim da "entrega vazia" (223
    precificados, 0 acima do threshold → o postprocess agora mostra near-miss).
  - [GG##] Galarian Gallery (GG##) agora é pulado em SCAN TIME, igual TG## — a
    regex anti-Trainer-Gallery virou `^(?:TG|GG)\\d+` (antes só TG##). GG## sofre
    a mesma inflação de referência (5-10×) e era pego só downstream, gastando
    chamadas de pricing. Defense-in-depth: o postprocess mantém o guard (#36).
  - [ROBUSTEZ] write_xlsx garante o diretório-alvo antes de salvar
    (out_path.parent.mkdir(parents=True, exist_ok=True)): outputs/ é gitignored
    e NÃO vem num clone limpo (sessão na nuvem) — sem isto o wb.save() quebrava
    com FileNotFoundError DEPOIS de horas de rastreio, perdendo tudo (#37).
  - INALTERADO: margem bruta, threshold fração, seleção de variante v2.18,
    validação v2.19, cache-bust v2.20, vintage core v2.21.

Changelog v2.21 (2026-06-21 — lista curada vintage core + flag --vintage):
  - [ESCOPO] Nova constante VINTAGE_SET_CODES (34 sets): WOTC (bs ju fo b2 tr g1
    g2 n1 n2 n3 n4 si lc wiz bog) + e-Card (ex aq skg) + EX Series COMPLETA (16:
    rs ss dr exma hl rg trr dx em uf ds lm hp cg df pk). Códigos CT REAIS
    verificados contra a API de expansões (não os chutes do briefing: Base Set =
    `bs` não `b1`; Southern Islands = `si` não `si1`; Best of Game = `bog` não
    `bp`; WOTC promos = `wiz` não `basep`).
  - [FLAG] --vintage: restringe o scan ao vintage core na ordem curada. Sozinho
    filtra TODAS as expansões; com --sets intersecta. Helper puro
    filter_vintage_sets (espelha filter_modern_sets; testável offline).
  - [ALIAS] +3 aliases pokemontcg.io confirmados por cobertura: bs→base1 (102
    cards), si→si1 (18), bog→bp (9). dr→ex3 e df→ex15 já existiam — eram os 2
    sets EX faltando nos scans anteriores (EX Dragon + Dragon Frontiers, Gold
    Stars/Charizard secret). n2→neo2 mantido mas baixo yield (cobertura pobre de
    variantes não-1stEd; 1stEd é excluída no pricing).
  - INALTERADO: seleção de variante v2.18, validação v2.19, cache-bust v2.20,
    margem bruta, threshold fração, --skip-backcatalog.
  - Testes: tests/test_vintage_sets.py (7 casos). Suíte 117/117 verde.

Changelog v2.20 (2026-06-21 — cache-bust da lógica de pricing; run diário não serve preço stale):
  - [ROBUSTEZ] A chave do price_cache não incluía a raridade, então entradas
    cacheadas ANTES do v2.18 (holo rare com preço reverseHolofoil inflado,
    foil=False) continuariam sendo servidas até o TTL (24h) — inclusive no run
    DIÁRIO do GitHub Actions, que NÃO usa --no-cache. Nova constante
    PRICE_LOGIC_VERSION embutida na chave (`pokemontcg:{versão}:...`); bump de
    "1"→"2" invalida todas as entradas pré-v2.18 de uma vez (custo único:
    1 refetch). Mudanças futuras na lógica de pricing → bumpe a constante.
  - INALTERADO: tudo o mais (seleção de variante v2.18, validação v2.19, etc.).

Changelog v2.19 (2026-06-21 — validação per-blueprint casa condição NM + reverse/variante):
  - [CORREÇÃO] validate_per_blueprint casava o listing per-blueprint SÓ pelo
    username do vendedor, IGNORANDO condição e reverse. Um vendedor com uma cópia
    Poor barata (ou a versão não-reverse) "contaminava" a validação. Caso real
    Shiftry hl: o scan achou a NM reverse (~R$140) referenciada a reverseHolofoil
    $42.95, mas a validação casava a Poor não-reverse do MESMO vendedor (R$46,46)
    → comparava preço de carta Poor vs referência reverse → falso "79%" (o
    ground-truth real: holo NM R$86,15 vs $20,27 ≈ 18%; reverse NM R$139,70 vs
    $42,94 ≈ 37% — nunca 79%). Isso RESSUSCITAVA falsos positivos DEPOIS do fix
    v2.18, na etapa que deveria ser o ground-truth.
  - [FIX] o match agora exige condition == listing.condition (Near Mint, garantido
    pelo filtro NM-only) E reverse igual (pokemon_reverse/mtg_foil/foil == listing.foil,
    simétrico com o parse do scan v2.18); entre os que batem, pega o MAIS BARATO.
    Se nenhum bate → STALE honesto (a cópia exata que o scan viu sumiu), em vez
    de casar a cópia errada.
  - [LIMPEZA] removido script órfão local validate_vintage_candidates.py (gitignored,
    one-off) que carregava o mesmo padrão de match buggy.
  - INALTERADO: tiers de markup, recálculo de margem real, contrato STALE→NÃO no
    postprocess, threshold fração, margem bruta.
  - Testes: tests/test_per_blueprint_variant_match.py (4 casos: reverse, holo
    padrão, mais-barato-entre-iguais, STALE). Suíte 110/110 verde.

Changelog v2.18 (2026-06-20 — fim da inflação de holo rare vintage; pricing por raridade+reverse):
  - [CORREÇÃO-RAIZ] Cartas Pokémon SEMPRE chegavam foil=False: o parse do listing
    lia props["mtg_foil"]/["foil"] (campos MTG, inexistentes em Pokémon) e IGNORAVA
    `pokemon_reverse`. Consequência: TODA "Holo Rare" PADRÃO caía no ramo foil=False
    e, sem variante `normal` na TCGPlayer (holo rare não tem printagem normal),
    escorregava pra `reverseHolofoil` — variante reverse, mais rara e CARA →
    margem inflada sistemática. Exemplos reais (pokemontcg.io 2026-06-20):
    Gengar Legendary Collection holofoil $146.89 vs reverse $1599.99 (10×!);
    Claydol EX Hidden Legends $14.47 vs $44.95 (+210%); Shiftry hl $19.92 vs
    $42.95 (+116%). A varredura vintage de 2026-06-19 era quase toda falso
    positivo por causa disso.
  - [FIX] (1) o parse lê `pokemon_reverse` → reverse-holo chega como foil=True.
    (2) seleção de variante ciente de raridade (novo helper _rarity_is_holo +
    param `rarity` em market_price_usd, alimentado por l.rarity no call site):
      • foil=True (reverse)        → reverseHolofoil primeiro;
      • foil=False + raridade holo → holofoil/unlimitedHolofoil (printagem holo
        base), reverseHolofoil POR ÚLTIMO;
      • foil=False + não-holo      → normal, reverse por último (era 2º).
    Verificado no data model do CardTrader: pokemon_rarity="Holo Rare" +
    pokemon_reverse=false = holo padrão (→ holofoil); reverse=true (→ reverse).
  - [FLAG] "Variante Baixa Confiança" NÃO dispara mais pra holo rare (holofoil é
    a variante CORRETA, não um casamento errado); só p/ carta NÃO-holo que casou
    preço holo (o caso Gengar não-foil → $1600).
  - INALTERADO: margem bruta, threshold fração, validação per-blueprint, skip-list,
    overrides de timeout por set, filtro TG##, --skip-backcatalog.
  - Testes: scripts/test_variant_disambiguation.py reescrito (semântica
    rarity+reverse; +regressões Shiftry/Gengar LC/Pidgey). Suíte 106/106 verde.

Changelog v2.17 (2026-06-20 — flag --skip-backcatalog; foco em sets recentes):
  - Nova flag --skip-backcatalog: restringe o scan às coleções modernas/curadas
    (PRIORITY_SET_CODES), pulando o back-catalog. Lição da auditoria 2026-06-08:
    back-catalog = mercado eficiente = ~0 deal acionável; o gap mora em
    lançamentos novos. Mais útil com --all-sets (corta ~832 → ~30 sets);
    combinado com --sets, intersecta com a lista do usuário.
  - Novo helper PURO filter_modern_sets(expansions, priority_codes=PRIORITY_SET_CODES):
    mantém só codes na lista priority, preserva ordem, case-insensitive, tolera
    code ausente/None. Testável offline (tests/test_skip_backcatalog.py, 11 casos).
  - INALTERADO: margem bruta, threshold fração, --hub-fee 0.0, validação
    per-blueprint, skip-list, overrides de timeout por set, filtro TG##.
  - Obs: v2.16 foi postprocess-only (tabela de entrega obrigatória); por isso o
    header do scanner pula de v2.15 → v2.17.

Changelog v2.15 (2026-06-15 — overrides de timeout por SET; fim do "churn" vintage):
  - [TIMEOUT vintage] Novo mapa code-level SET_TIMEOUT_OVERRIDES (código CT →
    segundos): df=1200s (20min), ds/n1/n4=1080s (18min). Sets vintage pesados
    NÃO cabiam no per-set-timeout default (8min) → estouravam SEMPRE → iam pra
    skip-list → eram pulados → nunca escaneados por completo ("churn"). Agora
    ganham fôlego sem o operador lembrar de passar --per-set-timeout à mão.
  - [RESOLVER] Novo effective_set_timeout_s(exp_code, default_s): o override só
    ELEVA o teto (max(default, override)); --per-set-timeout global maior ainda
    vence; --per-set-timeout 0 (desligado) deixa TUDO sem timeout (override não
    reativa); set sem override = comportamento histórico; case-insensitive.
  - scan_expansion resolve o timeout efetivo UMA vez no topo e o usa em todos os
    checks (pré-blueprints, pré-listings, loop de pricing) + na deadline_ts que
    governa retries/429-sleeps. _check_set_timeout ganhou param opcional
    timeout_s (None = retrocompat: cai no default da instância).
  - n2 (Neo Discovery) NÃO recebe override: é no-coverage genuíno (pokemontcg.io
    ~zero referência), tratado pelo cap de --max-consecutive-misses, não timeout.
  - INALTERADO: flag --per-set-timeout (default 8min); skip-list; cap de misses;
    mass-pricing-abort; margem bruta; threshold fração; filtro TG##.
  - Testes: tests/test_set_timeout_overrides.py (11 casos).

Changelog v2.14 (2026-06-15 — correção + robustez; resultados corretos e sem bug):
  - [CORREÇÃO timeout] _get._sleep_capped: quando o backoff pedido NÃO cabia no
    tempo restante (ex.: 429 Retry-After 60s com 3s de deadline), o retorno
    `time.monotonic() > deadline_ts` podia dar False por uma fração de segundo,
    o loop re-tentava e MASCARAVA o timeout. Agora um backoff TRUNCADO sinaliza
    estouro de forma determinística. (Teste pré-existente test_per_set_timeout_
    initial_calls estava VERMELHO no main por causa disso.)
  - [CORREÇÃO silent-failure pricing] pokemontcg.io: 429 (rate-limit) e 5xx
    eram tratados como "carta não encontrada" (miss) → sumiam deals em silêncio,
    envenenavam o contador de misses (abort no_coverage falso) e inflavam a taxa
    de falha. Novo _ptcg_get faz retry bounded em 429/5xx e, se persistir,
    LEVANTA requests.Timeout (→ contado como pricing_failure VISÍVEL, não miss).
    4xx ≠ 429 segue como sem-match legítimo.
  - [ROBUSTEZ concorrência] Run-guard: o scanner agora RECUSA iniciar se já há
    outra instância no mesmo --state-dir (lockfile scanner_run.lock). Evita o
    incidente de contenção de lock SQLite (pricing → ~9s/listing) que envenenava
    a skip-list. Escape hatch: --allow-concurrent.
  - [CORREÇÃO recovery FX] O checkpoint JSONL agora grava usd_brl/eur_brl no
    header; recover_from_checkpoint.py reconstrói a célula Stats usd_brl_rate.
    Antes o XLSX recuperado tinha FX=0.0 → a coluna "CT US$" da tabela de
    entrega do postprocess ficava vazia. (Classificação COMPRA/REVISAR NÃO era
    afetada — usa colunas em BRL.)
  - [SINAL variante] Nova coluna "Variante Baixa Confiança": "Sim" quando o
    listing é NÃO-foil mas o único preço veio de variante metálica premium
    (holofoil/unlimitedHolofoil). Só FLAG — não muda preço nem decisão.
    reverseHolofoil NÃO dispara (fallback intencional p/ Holo Rare vintage).

Changelog v2.12 (2026-06-06 — margem BRUTA pura; remove Hub fee do cálculo):
  - Decisão do operador (cross-scanner): scanner reporta APENAS margem bruta
    `(tcg − preço_site) / tcg`, threshold 30%, SEM nenhuma taxa embutida.
    Hub fee/frete/cartão/IOF passam a ser calculados FORA, pelo operador.
    SUPERSEDE a fórmula `× 1.06` (v2.3).
  - --hub-fee default 0.06 → 0.0 (constante HUB_FEE_RATE mantida só como
    referência histórica / opt-in via --hub-fee 0.06).
  - Construtor Scanner: hub_fee_rate default 0.06 → 0.0 (paridade programática).
  - --shipping-brl segue default 0.0; piso de preço $10 MANTIDO (é filtro).
  - --threshold segue fração 0.30 (=30%) — convenção inalterada.

Changelog v2.11 (2026-06-02 — scan completo + parciais ao vivo; integrado ao
main no saneamento 2026-06-05):
  - Flag --all-sets: escaneia TODAS as ~832 expansões (ignora --sets e config),
    pro scan COMPLETO (weekly).
  - PRIORITY_SET_CODES: no modo --all-sets, sets SV/curados são escaneados
    PRIMEIRO (catálogo CT vem old→new; protege os modernos do corte por timeout).
  - Companion `scripts/checkpoint_to_partial.py`: lê o .checkpoint.jsonl DURANTE
    o scan e emite PARTIAL_DEALS.md + .csv (revisão incremental; stdlib puro).
  - Validado em scan real de ~4h (2026-06-02, GH Actions, 832 exp).

Changelog v2.3 (2026-05-12 — alinhamento Hub fee scanner ↔ postprocess):
  - HUB_FEE_RATE = 0.06 promovido a constante; CLI flag --hub-fee
  - validate_per_blueprint agora aplica live_brl × (1 + hub_fee) como custo
    real no recalc de real_margin_pct / real_net_margin_pct / real_lucro_brl
  - Antes scanner era ~6pp otimista vs realidade (apenas postprocess aplicava
    a taxa). Agora margem REAL bate com BUY NOW/REJECT do relatório.
  - hub_fee_rate exportado na aba Stats do XLSX
  - Auto-conversão de --hub-fee > 1.0 (operador pode passar `6` ou `0.06`)

Changelog v2.2 (2026-05-12 — auditoria 9 bugs C/H/M + alinhamento modelo
consolidação):
  - C1: tier markup 30-45% reclassificado como "Alto markup" / VALIDATED_MARKUP
    (era PRICE_CHANGED descartado como erro)
  - C2: clean_collector_number aplicado no fallback bp.version
  - H1: --threshold > 1.0 auto-converte com warning (UX trap "25 vs 0.25")
  - H2: pricing provider agora aceita `foil=` e prioriza variante correta
    (reverseHolofoil vs normal); cache key inclui foil flag
  - M1: filter de validation_status sempre roda quando validate_top > 0
  - M2: opps sempre re-ordenados por real_net_margin_pct após validação
  - M3: SHIPPING_EUR_* promovidas a constantes; flag --shipping-brl
  - M4: log + counter pra moedas exóticas (GBP/JPY) dropadas
  - M5: log de supranumerários (collector_number > set.printedTotal) detecta
    SIR/SAR/HR pra revisão manual
  - Modelo de consolidação: frete default = 0 (cartas consolidadas em
    deposito Hub depot, frete diluído per-card ~R$0.30 → desprezível).
    Override via --shipping-brl X.

Changelog v2.1 (2026-04-29):
  - validate_per_blueprint: validação per-blueprint com tier markup
  - filtro anti-Trainer Gallery (_TRAINER_GALLERY_RE)
  - --validate-top, --min-net-margin CLI flags
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import portalocker
import requests
import yaml
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import ct_variants
from ct_chase import CHASE_ONLY_TIERS, CHASE_TIER_ORDER, classify_chase_tier  # unico dono do chase (informativo)
from ct_economics import Costs, compute as compute_economics  # unico dono da margem

# ─── v2.3.2 fix (bug-hunt 2026-05-17): força UTF-8 no I/O ─────────────────────
# Paridade com postprocess (commit 26c27bd). openpyxl.Workbook.save() pega
# encoding do interpreter locale via algum caminho interno. Em Windows com
# locale pt-BR, sys.stdout.encoding default é cp1252 → headers UTF-8 são
# gravados como bytes UTF-8 mas LIDOS como latin-1, produzindo mojibake
# (`Decis�o`, `Pre�o CT`). PYTHONIOENCODING=utf-8 resolve, mas só quando o
# invocador seta a var (wrappers PS setam; scripts ad-hoc esquecem).
# Garantia defensiva aqui (defense-in-depth):
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    # Python <3.7 ou stdout não-reconfigurável (raro). Fallback silencioso.
    pass

# ══════════════════════════════════════════════════════════════════════
# LOGGING — saída para stdout E arquivo (auditoria pós-execução)
# ══════════════════════════════════════════════════════════════════════

# Log file path:
#   - CT_LOG_FILE env var (preferido — set pelo wrapper PS antes de invocar)
#   - default cardtrader_scanner.log no cwd
# Por que via env e nao via --log-file CLI?
#   logging.basicConfig roda no IMPORT (antes de argparse). Env var resolve
#   o problema de ordem sem refactor maior.
_LOG_FILE = os.environ.get("CT_LOG_FILE", "cardtrader_scanner.log")
_log_handlers = [
    logging.StreamHandler(sys.stdout),
    logging.FileHandler(_LOG_FILE, encoding="utf-8"),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# CONFIG — valores default. CLI ou config.yaml sobrescrevem.
# Por que constantes no topo? Uma mudança aqui afeta o scanner inteiro;
# fica fácil ajustar sem ler o código todo.
# ══════════════════════════════════════════════════════════════════════
CT_BASE = "https://api.cardtrader.com/api/v2"
POKEMONTCG_BASE = "https://api.pokemontcg.io/v2"
JUSTTCG_BASE = "https://api.justtcg.com/v1"
FX_BASE = "https://api.frankfurter.app/latest"  # BCE — grátis, sem auth

# Game ID no CardTrader. Pokemon = 5 (MTG=1, Yu-Gi-Oh=4, One Piece=15, etc).
# Descobrível via GET /games se quebrar no futuro.
CT_POKEMON_GAME_ID = 5

# Defaults do scanner (sobrescritos por CLI)
MARGIN_THRESHOLD = 0.30          # 30% margem mínima (requisito do usuário)
MIN_PRICE_USD = 10.0             # filtro extra do usuário
LANGUAGE_FILTER = "en"           # apenas inglês (default; --language muda)
# v2.29: a API aceita apelidos no `?language=` (zh/cn/chinese casam zh-CN), mas
# a OFERTA traz o código canônico (`pokemon_language: "zh-CN"`). Sem normalizar,
# `--language zh` passaria no servidor e filtraria TUDO no cliente, em silêncio.
LANGUAGE_ALIASES = {
    "zh": "zh-CN", "cn": "zh-CN", "zh-cn": "zh-CN", "chinese": "zh-CN",
    "zh-tw": "zh-TW", "english": "en", "italian": "it", "german": "de",
    "french": "fr", "spanish": "es", "portuguese": "pt", "japanese": "jp",
}


def normalize_language(code: Optional[str]) -> str:
    """Código de idioma como a API devolve na oferta ("en", "zh-CN"...).
    Apelido conhecido → canônico; desconhecido → lowercased (a API é
    case-insensitive e `Listing.language` chega .lower())."""
    low = (code or "").strip().lower()
    return LANGUAGE_ALIASES.get(low, low)


CONDITION_FILTER = "Near Mint"   # apenas NM
EXCLUDE_GRADED = True            # exclui PSA/BGS/CGC
# v2.20: versão da LÓGICA de pricing/variante embutida na chave do price_cache.
# Bumpe quando a seleção de variante/preço mudar, pra invalidar entradas antigas
# (senão o cache serve preço calculado com a lógica velha até o TTL). Histórico:
#   1 = pré-v2.18 (reverseHolofoil inflado em holo rare) — agora invalidado.
#   2 = v2.18+ (seleção ciente de raridade+reverse).
#   3 = lotes 2/3 (2026-11): nome CT normalizado (δ Delta Species / Gold Star) e
#       número com letra/prefixo na query — casamento de carta mudou.
PRICE_LOGIC_VERSION = ct_variants.PRICE_LOGIC_VERSION   # dono único: ct_variants
REQUEST_DELAY_CT = 0.15          # CT tem limite 10/s → 0.15s deixa folga
REQUEST_DELAY_PRICING = 0.1      # pokemontcg.io permite 20k/dia (~0.23/s)
TIMEOUT = 30

# ── v2.23: fonte de FALLBACK de preço tcgcsv.com ───────────────────────────
# tcgcsv.com = dump diário grátis dos preços TCGplayer (mesma fonte que a
# pokemontcg.io agrega, capturada por outra rota). Aqui é usada SÓ como
# FALLBACK: quando a pokemontcg.io devolve ZERO match de preço pra um set
# inteiro (caso Ascended Heroes / asc — a pokemontcg.io lista as cartas mas SEM
# bloco tcgplayer.prices → todo listing falha → o set estoura o timeout e cai na
# skip-list, ficando INVISÍVEL). O tcgcsv tem o set completo (asc = 612 produtos,
# 650/650 com preço) e é superset estrito da pokemontcg.io nos sets testados.
# Categoria 3 = Pokémon. User-Agent é OBRIGATÓRIO (sem ele = 401).
TCGCSV_BASE = "https://tcgcsv.com/tcgplayer/3"
TCGCSV_USER_AGENT = (
    "card-trader-scanner/2.23 "
    "(+github.com/matheuscllm-lgtm/card-trader-scanner)"
)

# setcode pokemontcg.io → abreviação tcgcsv (campo `abbreviation` em /groups).
# Portado do MYP (verificado 1-a-1 contra o dump real de /groups, 2026-06-22).
# A ponte CT é em 2 saltos: CT set code → setcode pokemontcg.io (via
# SET_ALIAS_TO_PTCG, já existente) → abbr tcgcsv (esta tabela). Resolução é
# UNIQUE-MATCH-ONLY (ver resolve_tcgcsv_group_id): abbr exata, e o fallback por
# substring de nome só aceita match ÚNICO — ambíguo → None → set pulado (NUNCA
# chuta um group errado, que injetaria preço de promo/energy como "real").
PTCG_SETCODE_TO_TCGCSV_ABBR = {
    "sv10": "DRI",      # Destined Rivals
    "sv9": "JTG",       # Journey Together
    "sv8pt5": "PRE",    # Prismatic Evolutions
    "sv8": "SSP",       # Surging Sparks
    "sv7": "SCR",       # Stellar Crown
    "sv6pt5": "SFA",    # Shrouded Fable
    "sv6": "TWM",       # Twilight Masquerade
    "sv5": "TEF",       # Temporal Forces
    "sv4pt5": "PAF",    # Paldean Fates
    "sv4": "PAR",       # Paradox Rift
    "sv3": "OBF",       # Obsidian Flames
    "sv3pt5": "MEW",    # 151
    "sv2": "PAL",       # Paldea Evolved
    "me2pt5": "ASC",    # Ascended Heroes (pokemontcg.io SEM preço → tcgcsv resgata)
    "me2": "PFL",       # Phantasmal Flames
    "me1": "MEG",       # Mega Evolution (base)
    "swsh12pt5": "CRZ",   # Crown Zenith
    "swsh12": "SWSH12",   # Silver Tempest
    "swsh11": "SWSH11",   # Lost Origin
    "swsh10": "SWSH10",   # Astral Radiance
    "swsh9": "SWSH09",    # Brilliant Stars (tcgcsv usa zero-pad: SWSH09)
    "swsh8": "SWSH08",    # Fusion Strike
    "swsh7": "SWSH07",    # Evolving Skies
    "pgo": "PGO",         # Pokémon GO
    "zsv10pt5": "BLK",    # Black Bolt
    "rsv10pt5": "WHT",    # White Flare
    # v2.26: vintage WotC/EX (G6) — o fallback por NOME falha nesses sets
    # (substring ambígua: "Base Set" ⊂ "Base Set 2"; "Team Rocket" ⊂ "Ash vs
    # Team Rocket..."; "EX Dragon" ⊂ "EX Dragon Frontiers"; "&" vs "and" em
    # Ruby & Sapphire; nome CT "Expedition Base Set" ≠ "Expedition" no tcgcsv).
    # Abbrs verificadas ÚNICAS no /groups em 2026-08-22 (sonda 1/1 cada).
    # wiz (WoTC Promo) e bog (Best of Promos) ficam DE FORA de propósito:
    # no tcgcsv ambos têm abbr "PR" compartilhada por ~8 groups de promo —
    # mapear seria chute (unique-match-only). Saem sem referência, rotulados.
    "base1": "BS",      # Base Set (CT bs)
    "base5": "TR",      # Team Rocket (CT tr)
    "ecard1": "EX",     # Expedition (CT ex)
    "ex1": "RS",        # EX Ruby & Sapphire (CT rs)
    "ex3": "DR",        # EX Dragon (CT dr)
}

# v2.28 (2026-09-12): código CT → groupId(s) tcgcsv EXPLÍCITOS. Caminho primário
# da resolução (antes da abbr/nome). Incidente 2026-09-12: com `--provider
# tcgcsv`, svi/kss/gen/evo saíram SEM referência — só ~21 dos ~130 sets tinham
# abbr aqui e o resto dependia do fallback por NOME, ambíguo justamente nesses
# ("Evolutions" ⊂ "Prismatic Evolutions"; "Scarlet & Violet" ⊂ vários groups SV;
# CT "XY Kalos Starter Set" ≠ tcgcsv "Kalos Starter Set"; GEN = 2 groups). O MYP
# não sofria porque tem o mapa de abbr ampliado (v5.16) + complemento
# pokemontcg.io no modo `auto`. groupId é estável e não depende de abbr única
# (RR, BKP, CL, LTR, GEN e PR são COMPARTILHADAS por >1 group no /groups).
# Verificado contra o snapshot real de /groups (tests/fixtures/
# tcgcsv_groups_pokemon.json) — cada comentário é o `name` do group. Cobertura
# travada por tests/test_tcgcsv_group_map.py (universo do /scan + menu do skill).
# Tupla com >1 id = set que o TCGplayer divide em groups (subset Radiant
# Collection com numeração RC própria): o prefill mescla e DESCARTA número
# presente em >1 group (nunca escolhe um dos preços).
CT_SET_TO_TCGCSV_GROUP_IDS: dict[str, tuple[int, ...]] = {
    # Scarlet & Violet + Mega Evolution
    "svi": (22873,),  # SV01: Scarlet & Violet Base Set
    "pal": (23120,),  # SV02: Paldea Evolved
    "obf": (23228,),  # SV03: Obsidian Flames
    "mew": (23237,),  # SV: Scarlet & Violet 151
    "par": (23286,),  # SV04: Paradox Rift
    "paf": (23353,),  # SV: Paldean Fates
    "tef": (23381,),  # SV05: Temporal Forces
    "twm": (23473,),  # SV06: Twilight Masquerade
    "sfa": (23529,),  # SV: Shrouded Fable
    "scr": (23537,),  # SV07: Stellar Crown
    "ssp": (23651,),  # SV08: Surging Sparks
    "pre": (23821,),  # SV: Prismatic Evolutions
    "jtg": (24073,),  # SV09: Journey Together
    "dri": (24269,),  # SV10: Destined Rivals
    "blk": (24325,),  # SV: Black Bolt
    "wht": (24326,),  # SV: White Flare
    "meg": (24380,),  # ME01: Mega Evolution
    "pfl": (24448,),  # ME02: Phantasmal Flames
    "asc": (24541,),  # ME: Ascended Heroes
    "por": (24587,),  # ME03: Perfect Order
    "cri": (24655,),  # ME04: Chaos Rising
    # Sword & Shield
    "ssh": (2585,),  # SWSH01: Sword & Shield Base Set
    "rcl": (2626,),  # SWSH02: Rebel Clash
    "daa": (2675,),  # SWSH03: Darkness Ablaze
    "cpa": (2685,),  # Champion's Path
    "viv": (2701,),  # SWSH04: Vivid Voltage
    "bst": (2765,),  # SWSH05: Battle Styles
    "cre": (2807,),  # SWSH06: Chilling Reign
    "evs": (2848,),  # SWSH07: Evolving Skies
    "shf": (2754, 2781),  # Shining Fates + Shining Fates: Shiny Vault (SV###)
    "fst": (2906,),  # SWSH08: Fusion Strike
    "brs": (2948,),  # SWSH09: Brilliant Stars
    "astr": (3040,),  # SWSH10: Astral Radiance
    "lorg": (3118,),  # SWSH11: Lost Origin
    "sit": (3170,),  # SWSH12: Silver Tempest
    "crz": (17688,),  # SWSH: Crown Zenith
    "pkmgo": (3064,),  # Pokemon GO
    # Sun & Moon
    "sum": (1863,),  # SM Base Set
    "gri": (1919,),  # SM - Guardians Rising
    "bus": (1957,),  # SM - Burning Shadows
    "slg": (2054,),  # Shining Legends
    "cinv": (2071,),  # SM - Crimson Invasion
    "upr": (2178,),  # SM - Ultra Prism
    "fli": (2209,),  # SM - Forbidden Light
    "ces": (2278,),  # SM - Celestial Storm
    "drm": (2295,),  # Dragon Majesty
    "lot": (2328,),  # SM - Lost Thunder
    "teu": (2377,),  # SM - Team Up
    "unb": (2420,),  # SM - Unbroken Bonds
    "unm": (2464,),  # SM - Unified Minds
    "hif": (2480, 2594),  # Hidden Fates + Hidden Fates: Shiny Vault (SV##)
    "cec": (2534,),  # SM - Cosmic Eclipse
    "det": (2409,),  # Detective Pikachu
    # XY
    "xybsp": (1451,),  # XY Promos (abbr PR compartilhada → só por id)
    "kss": (1522,),  # Kalos Starter Set
    "flf": (1464,),  # XY - Flashfire
    "ffi": (1481,),  # XY - Furious Fists
    "phf": (1494,),  # XY - Phantom Forces
    "prc": (1509,),  # XY - Primal Clash
    "dcr": (1525,),  # Double Crisis
    "ros": (1534,),  # XY - Roaring Skies
    "aor": (1576,),  # XY - Ancient Origins
    "bkt": (1661,),  # XY - BREAKthrough
    "bkp": (1701,),  # XY - BREAKpoint (abbr BKP compartilhada c/ Burger King Promos)
    "gen": (1728, 1729),  # Generations + Generations: Radiant Collection
    "fco": (1780,),  # XY - Fates Collide
    "sts": (1815,),  # XY - Steam Siege
    "evo": (1842,),  # XY - Evolutions
    # Black & White
    "blw": (1400,),  # Black and White
    "epo": (1424,),  # Emerging Powers
    "nvi": (1385,),  # Noble Victories
    "nxd": (1412,),  # Next Destinies
    "dex": (1386,),  # Dark Explorers
    "drx": (1394,),  # Dragons Exalted
    "drv": (1426,),  # Dragon Vault
    "bcr": (1408,),  # Boundaries Crossed
    "pls": (1413,),  # Plasma Storm
    "plf": (1382,),  # Plasma Freeze
    "plb": (1370,),  # Plasma Blast
    "ltr": (1409, 1465),  # Legendary Treasures + Legendary Treasures: Radiant Collection
    # HeartGold & SoulSilver / Diamond & Pearl / Platinum
    "hgs": (1402,),  # HeartGold SoulSilver
    "ul": (1399,),  # Unleashed
    "und": (1403,),  # Undaunted
    "tri": (1381,),  # Triumphant
    "clo": (1415,),  # Call of Legends (abbr CL compartilhada)
    "pdp": (1421,),  # Diamond and Pearl Promos (abbr PR compartilhada)
    "dp": (1430,),  # Diamond and Pearl
    "mt": (1368,),  # Mysterious Treasures
    "sw": (1380,),  # Secret Wonders
    "ge": (1405,),  # Great Encounters
    "md": (1390,),  # Majestic Dawn
    "la": (1417,),  # Legends Awakened
    "sft": (1369,),  # Stormfront
    "pl": (1406,),  # Platinum
    "rr": (1367,),  # Rising Rivals (abbr RR compartilhada c/ EX Team Rocket Returns)
    "sv": (1384,),  # Supreme Victors
    "ar": (1391,),  # Arceus
    # EX / e-Card
    "rs": (1393,),  # EX Ruby and Sapphire
    "ss": (1392,),  # EX Sandstorm
    "dr": (1376,),  # EX Dragon
    "exma": (1377,),  # EX Team Magma vs Team Aqua
    "hl": (1416,),  # EX Hidden Legends
    "rg": (1419,),  # EX FireRed & LeafGreen
    "trr": (1428,),  # EX Team Rocket Returns
    "dx": (1404,),  # EX Deoxys
    "em": (1410,),  # EX Emerald
    "uf": (1398,),  # EX Unseen Forces
    "ds": (1429,),  # EX Delta Species
    "lm": (1378,),  # EX Legend Maker
    "hp": (1379,),  # EX Holon Phantoms
    "cg": (1395,),  # EX Crystal Guardians
    "df": (1411,),  # EX Dragon Frontiers
    "pk": (1383,),  # EX Power Keepers
    "ex": (1375,),  # Expedition
    "aq": (1397,),  # Aquapolis
    "skg": (1372,),  # Skyridge
    # WOTC
    "bs": (604,),  # Base Set
    "ju": (635,),  # Jungle
    "fo": (630,),  # Fossil
    "b2": (605,),  # Base Set 2
    "tr": (1373,),  # Team Rocket
    "g1": (1441,),  # Gym Heroes
    "g2": (1440,),  # Gym Challenge
    "n1": (1396,),  # Neo Genesis
    "n2": (1434,),  # Neo Discovery
    "n3": (1389,),  # Neo Revelation
    "n4": (1444,),  # Neo Destiny
    "lc": (1374,),  # Legendary Collection
    "si": (648,),  # Southern Islands
    "wiz": (1418,),  # WoTC Promo (abbr PR compartilhada → só por id)
    "nbsp": (1423,),  # Nintendo Promos (abbr PR compartilhada → só por id)
    "bog": (1455,),  # Best of Promos (abbr PR compartilhada → só por id)
}

# v2.28: sets do universo que ficam SEM referência tcgcsv DE PROPÓSITO (motivo
# obrigatório). A resolução devolve [] pra eles — nem abbr, nem nome.
# v2.29: códigos CT de sets JAPONESES que colidem com setcodes pokemontcg.io
# (verificado na API CT em 2026-10-03). O scanner usava o código CT como setcode
# pokemontcg.io por identidade → `sv8` (JP Super Electric Breaker) virava Surging
# Sparks e Palossand ex JP 057 era precificada como Pikachu ex 057/191. Estes
# códigos NUNCA resolvem por identidade (pokemontcg.io nem tcgcsv): sem mapa
# explícito → sem referência, nunca a carta de outro set.
CT_JP_SETCODE_COLLISIONS: dict[str, str] = {
    "sv3": "Ruler of the Black Flame (JP) ≠ Obsidian Flames",
    "sv6": "Mask of Change (JP) ≠ Twilight Masquerade",
    "sv7": "Stellar Miracle (JP) ≠ Stellar Crown",
    "sv8": "Super Electric Breaker (JP) ≠ Surging Sparks",
    "sv9": "Battle Partners (JP) ≠ Journey Together",
    "sv10": "The Glory of Team Rocket (JP) ≠ Destined Rivals",
}


# Lote 2 (#13): códigos CT cujo texto é, por coincidência, o id de OUTRO set na
# pokemontcg.io. Conferido em sets/en.json de PokemonTCG/pokemon-tcg-data
# (2026-11-24): {"id": "g1", "name": "Generations"}; Gym Heroes = "gym1". Nunca
# resolvem por identidade (só pelo alias explícito).
CT_PTCG_ID_COLLISIONS: dict[str, str] = {
    "g1": "Gym Heroes (CT) ≠ Generations (ptcg g1)",
}


def ptcg_expected_sets(ct_set_code: str) -> set[str]:
    """setcodes pokemontcg.io aceitos pra um código CT: o próprio código (exceto
    colisão JP) + aliases de SET_ALIAS_TO_PTCG."""
    code = (ct_set_code or "").lower()
    out: set[str] = set()
    if code and code not in CT_JP_SETCODE_COLLISIONS and code not in CT_PTCG_ID_COLLISIONS:
        out.add(code)
    for alias in PokemonTcgIoProvider.SET_ALIAS_TO_PTCG.get(code, []):
        out.add(alias.lower())
    return out


TCGCSV_EXCLUDED_CT_SETS: dict[str, str] = {
    "c25": (
        "Celebrations: o TCGplayer divide em CLB (1-25) e CCC (Classic "
        "Collection, numeração original ex. 4/102) — os números colidem e o "
        "listing CT não diz de qual subset é; mapear seria chutar a carta."
    ),
}

# Frete base por tier de seller (EUR — CT é europeu por origem).
# Convertido pra BRL via FX no Scanner._estimate_shipping_brl.
# 2026-05-12 M3 fix: promovido de magic number a constantes.
SHIPPING_EUR_HUB = 5.0           # Hub seller / zero_fee — CT centraliza envio
SHIPPING_EUR_PROFESSIONAL = 10.0 # Professional seller — envia do país do seller
SHIPPING_EUR_PRIVATE = 12.0      # Private seller — envio mais caro

# Hub fee médio sobre preço do site (per-blueprint LIVE).
# v2.12 (2026-06-06 — decisão do operador): margem reportada agora é BRUTA.
# O DEFAULT efetivo aplicado é 0.0 (--hub-fee default 0.0): custo = preço do
# site, sem nenhuma taxa embutida. O operador calcula Hub fee/frete/cartão/IOF
# por fora, manualmente. Isso SUPERSEDE a fórmula antiga `× 1.06`.
# A constante abaixo permanece apenas como valor de referência histórico/opt-in:
# passe `--hub-fee 0.06` para reembutir os 6% (custo = live_brl × (1 + hub_fee)).
HUB_FEE_RATE = 0.06              # = default de --hub-fee; só afeta as colunas líquidas (B1/D8)

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DB = SCRIPT_DIR / "cache.db"
ENV_FILE = SCRIPT_DIR / ".env"
CONFIG_FILE = SCRIPT_DIR / "config.yaml"

# v2.4: per-set timeout + auto skip-list.
# Run 25898522951 (2026-05-15) cancelou em 30:09 com 5/10 sets processados
# pq o timeout-minutes do GH Actions matou o job, mas o problema mais antigo
# (run 25838570927 de 2026-05-14) foi um set unico travado 24m53s sem progresso.
# Solucao: wall-clock timeout per-set + persistir sets travados em skip-list.
SKIP_LIST_FILE = SCRIPT_DIR / "scanner_skip_list.json"


def skip_list_path(state_dir: Path, language: str = LANGUAGE_FILTER) -> Path:
    """v2.29: skip-list POR IDIOMA. Um run `--language zh-CN` que estoura
    timeout/no_coverage gravaria o set na skip-list global e os runs ingleses
    canônicos passariam a pulá-lo em silêncio. Idioma default mantém o nome
    histórico; os demais ganham sufixo (`scanner_skip_list.zh-cn.json`)."""
    lang = normalize_language(language)
    if lang == LANGUAGE_FILTER:
        return Path(state_dir) / "scanner_skip_list.json"
    return Path(state_dir) / f"scanner_skip_list.{lang.lower()}.json"
DEFAULT_PER_SET_TIMEOUT_MIN = 8  # conservador: pior caso medido foi 7min/set

# v2.14 (2026-06-15): overrides de timeout por SET (vintage churn fix).
# Problema: alguns sets vintage pesados (muitas listings + pokemontcg.io lento)
# NÃO cabem no per-set-timeout default (8min) e estouram SEMPRE. O timeout joga
# o set na skip-list; runs futuros o pulam; ele nunca mais é escaneado por
# completo. Vira "churn": entra na skip-list, é pulado, volta a entrar. O
# operador teria que lembrar de passar `--per-set-timeout 20` manualmente toda
# vez — frágil.
# Solução: um mapa code-level de overrides (segundos) pra sets confirmados que
# precisam de mais fôlego. É código (não config que o operador mantém à mão)
# porque são fatos estáveis sobre sets específicos — pertencem ao lado das
# outras constantes (regex TG, TTLs). O override só ELEVA o teto: se o operador
# passar um `--per-set-timeout` global ainda maior, esse vence (max). Se passar
# 0 (desativado), tudo fica sem timeout. Chaves = códigos CardTrader.
# Casos confirmados na investigação do ciclo vintage 2026-06-15:
#   df (EX Dragon Frontiers) — ~19min p/ 100% das 79 listings; 8min cortava sempre.
#   ds (EX Delta Species), n1 (Neo Genesis), n4 (Neo Destiny) — cobertura PARCIAL
#       cortada por timeout de 12min; escaneariam mais com budget maior.
# NÃO inclui n2 (Neo Discovery): aquele é NO-COVERAGE genuíno (pokemontcg.io ~zero
# referência → ~40 misses consecutivos), tratado pelo --max-consecutive-misses,
# não por timeout. Entrada de n2 na skip-list por miss-cap é defensável.
SET_TIMEOUT_OVERRIDES: dict[str, int] = {
    "df": 1200,  # EX Dragon Frontiers — 20min (medido ~19min p/ 100%)
    "ds": 1080,  # EX Delta Species — 18min (folga sobre os 12min parciais)
    "n1": 1080,  # Neo Genesis — 18min
    "n4": 1080,  # Neo Destiny — 18min
    # Lote 1 (2026-11): estouraram 8min no run 2026-06-27 (skip-list: cg 76/105,
    # g1 97/211, g2 73/345, tr 100/176) ou são sets grandes (hp, aq).
    "cg": 1080,  # EX Crystal Guardians — 18min
    "g1": 1080,  # Gym Heroes — 18min
    "g2": 1080,  # Gym Challenge — 18min
    "tr": 1080,  # Team Rocket — 18min
    "hp": 1080,  # EX Holon Phantoms — 18min
    "aq": 1080,  # Aquapolis — 18min
    # Era Mega Evolution: sets novos que a pokemontcg.io NÃO precifica → caem no
    # fallback tcgcsv (~1 req/listing = lento). Sem override estouram o default de
    # 8min e vão pra skip-list. Só entram aqui sets que o tcgcsv REALMENTE precifica.
    "cri": 1200,  # Chaos Rising (me4) — 20min; tcgcsv precifica (384 rows num scan real)
    # NÃO incluir asc (Ascended Heroes/me2pt5): a pokemontcg.io não precifica o set,
    # mas o tcgcsv SIM (group 24541 'ASC' — 1085 rows num teste real). O resgate
    # tcgcsv é um BULK único (não per-listing), então asc NÃO precisa de timeout
    # maior — a lentidão que eu via era pokemontcg.io consultando listing-a-listing
    # SEM o fallback disparar. ⚠️ O fallback tcgcsv só dispara com
    # --max-consecutive-misses > 0 (o skill /scan passa 40 nos comandos canônicos
    # desde 2026-07-20, travado em tests/test_scan_skill_profiles.py); sem a
    # flag, asc fica com 0 preço apesar do tcgcsv ter os dados.
}


def effective_set_timeout_s(exp_code: str, default_s: float) -> float:
    """Resolve o timeout efetivo (segundos) pra um set.

    Regras:
      - default_s == 0 (timeout global desativado) → 0 (sem timeout pra ninguém,
        incluindo sets com override; o operador desligou de propósito).
      - set com override → max(default_s, override) — o override só ELEVA o teto;
        um --per-set-timeout global ainda maior continua vencendo.
      - set sem override → default_s (comportamento histórico).
    Código normalizado (lower/strip) pra casar com os códigos CardTrader.
    """
    if not default_s:
        return 0.0
    code = (exp_code or "").strip().lower()
    override = SET_TIMEOUT_OVERRIDES.get(code)
    if override is None:
        return default_s
    return float(max(default_s, override))

# TTL do cache. Blueprints praticamente não mudam (cartas impressas uma vez).
# Preços mudam diário → refresh.
BLUEPRINT_TTL = timedelta(days=30)
PRICE_TTL = timedelta(hours=24)
FX_TTL = timedelta(hours=12)


# Regex para extrair o número do collector de strings sujas tipo
# "Special Illustration Rare | 161/131" → "161". Capturamos o último grupo N/N
# (algumas cartas trazem códigos de promo antes).
_NUMBER_IN_VERSION = re.compile(r"(\d+)\s*/\s*\d+")

# v2.1 — Filtro anti-Trainer Gallery. Cartas com collector_number "TG##" do
# subset Trainer Gallery (era SWSH 2021-2023) produzem falsos positivos massivos
# no pricing pokemontcg.io: a base retorna preços inflados em 5-10× pra essas
# cartas, possivelmente porque bate com variantes secret-rare alt-art com mesmo
# nome. Resultado: 35 de 38 oportunidades em scan SWSH (2026-04-29 madrugada)
# eram falsos positivos com margens "90%+ líq" estatisticamente impossíveis.
# Solução: skipar listings cujo collector_number bate `^TG\d+`.
#
# Galarian Gallery (GG##) é o subset irmão (SWSH: Brilliant Stars / Astral
# Radiance / Lost Origin / Silver Tempest / Crown Zenith) e sofre a MESMA
# inflação de referência pokemontcg.io (5-10×). O postprocess já roteia GG## pra
# NAO/manual (cardtrader_postprocess.TRAINER_GALLERY_RE = ^(?:TG|GG)\d+), mas até
# agora só o TG## era skipado no scanner — GG## gastava chamadas de pricing e só
# era pego downstream. Estendemos a regex pra alinhar as duas camadas (defense in
# depth): GG## também é pulado em scan time, igual TG##. O postprocess mantém o
# guard (belt-and-suspenders) — nada é removido lá.
_TRAINER_GALLERY_RE = re.compile(r"^(?:TG|GG)\d+", re.IGNORECASE)


# CHASE TIER: regra única em ct_chase.py (importada acima; só informativa).


# ══════════════════════════════════════════════════════════════════════
# VALORIZAÇÃO — score heurístico honesto (v2.13, frente "médio/longo prazo")
# ══════════════════════════════════════════════════════════════════════
# IMPORTANTE (honestidade de dados): este score NÃO usa preço histórico nem
# dados de tendência — as APIs atuais (CardTrader + pokemontcg.io) NÃO fornecem
# série temporal de preços. O que temos é: (1) data de lançamento do set
# (pokemontcg.io set.releaseDate) → idade; (2) rarity oficial → chase tier;
# (3) preço de mercado atual. O score combina SÓ esses sinais derivávies, e
# cada componente é explicado em texto na coluna "Valorização — Notas".
# Não inventamos "alta histórica" nem "% do topo" porque a fonte não dá isso.
#
# Heurística (0-100), três componentes objetivos:
#   • Raridade (0-45):  TOP=45, MID=30, MODEST=12, BULK=0, desconhecida=8
#   • Maturidade (0-35): sets com 1.5-4 anos pontuam mais (já passaram do
#     dip pós-lançamento e ainda não saíram totalmente de circulação). Recém-
#     lançado (<6m) e muito antigo (>6 anos) pontuam menos — heurística simples,
#     não previsão. Set sem data → 10 (neutro).
#   • Preço-âncora (0-20): cartas de market mais alto têm mais "chão" e
#     histórico de retenção de valor; <$15→4, $15-40→10, $40-100→16, >$100→20.
# Limitações ficam documentadas na própria nota de cada linha.
def _valorization_age_component(set_release_date: Optional[str],
                                now: Optional[datetime] = None) -> tuple[int, str]:
    """Componente de maturidade (0-35) + nota textual. Data no formato
    'YYYY/MM/DD' (pokemontcg.io). Sem data → neutro."""
    if not set_release_date:
        return 10, "idade do set desconhecida (sem data na fonte)"
    now = now or datetime.now()
    parsed = None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(set_release_date, fmt)
            break
        except (ValueError, TypeError):
            continue
    if parsed is None:
        return 10, "idade do set desconhecida (data ilegível)"
    age_days = (now - parsed).days
    age_years = age_days / 365.25
    if age_years < 0.5:
        return 12, f"set recém-lançado (~{age_years:.1f} anos) — preço ainda instável"
    if age_years < 1.5:
        return 22, f"set jovem (~{age_years:.1f} anos) — saindo do dip pós-lançamento"
    if age_years <= 4.0:
        return 35, f"set maduro (~{age_years:.1f} anos) — janela clássica de valorização"
    if age_years <= 6.0:
        return 24, f"set antigo (~{age_years:.1f} anos) — fora de circulação, demanda residual"
    return 16, f"set muito antigo (~{age_years:.1f} anos) — vintage, líquido só em chase"


def compute_valorization(rarity: Optional[str],
                         set_release_date: Optional[str],
                         tcg_market_usd: float,
                         now: Optional[datetime] = None) -> tuple[int, str]:
    """Score de valorização médio/longo prazo (0-100) + nota explicativa.

    Honestidade: combina SÓ sinais que as APIs fornecem (rarity, idade do set,
    preço atual). NÃO usa preço histórico (a fonte não tem). É uma HEURÍSTICA
    de triagem, não previsão. Operador decide capital.
    """
    tier = classify_chase_tier(rarity)
    rarity_pts = {"TOP": 45, "MID": 30, "MODEST": 12, "BULK": 0}.get(tier, 8)
    rarity_note = {
        "TOP": "raridade top (chase forte)",
        "MID": "raridade média-alta (alt/ultra/rainbow)",
        "MODEST": "raridade modesta (holo/promo)",
        "BULK": "bulk (common/uncommon — baixo potencial)",
    }.get(tier, "raridade desconhecida")

    age_pts, age_note = _valorization_age_component(set_release_date, now=now)

    if tcg_market_usd < 15:
        price_pts, price_note = 4, "preço-âncora baixo (<$15)"
    elif tcg_market_usd < 40:
        price_pts, price_note = 10, "preço-âncora médio ($15-40)"
    elif tcg_market_usd < 100:
        price_pts, price_note = 16, "preço-âncora alto ($40-100)"
    else:
        price_pts, price_note = 20, "preço-âncora premium (>$100)"

    score = rarity_pts + age_pts + price_pts
    note = f"{rarity_note}; {age_note}; {price_note} (heurística — sem série histórica)"
    return score, note


_CT_DELTA_SUFFIX = re.compile(r"\s+Delta Species$")


def ptcg_card_name(ct_name: str) -> str:
    """Nome CT → nome usado pela pokemontcg.io (Lote 2, #1).

    Conferido em cards/en/ex15|ex11|ex14.json (PokemonTCG/pokemon-tcg-data):
    CT "Ampharos δ Delta Species" = ptcg "Ampharos δ"; CT "Charizard ☆ Gold Star
    δ Delta Species" = ptcg "Charizard ★ δ"; CT "Groudon ☆ Gold Star" = ptcg
    "Groudon ★". Nome sem esses padrões passa intacto."""
    name = ct_name or ""
    if "δ" in name:
        name = _CT_DELTA_SUFFIX.sub("", name)
    return name.replace("☆ Gold Star", "★")


def to_bool(v) -> bool:
    """Booleano de payload externo: a string "false"/"0" NUNCA vira True."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "sim", "t", "y")
    return False


def now_iso() -> str:
    """Data/hora local COM fuso, em segundos (ex. 2026-11-24T10:00:00-03:00).
    Único formato de data/hora do scanner (scanned_at, price_fetched_at,
    validated_at). Função de módulo p/ os testes poderem congelá-la."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _iso_date(v) -> Optional[str]:
    """'2026/11/23' ou '2026-11-23...' -> '2026-11-23' (data do DADO); outro formato -> None."""
    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", str(v or ""))
    return "-".join(m.groups()) if m else None


def _to_tz_iso(value: Optional[str]) -> Optional[str]:
    """ISO naive (cache SQLite, hora local) → mesmo formato de now_iso()."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return None


def ptcg_number_query(raw: str) -> str:
    """Número de coleção CT → forma gravada no campo `number` do pokemontcg.io.

    Conferido em PokemonTCG/pokemon-tcg-data (cards/en/*.json, 2026-11-24):
    numérico puro sem zero à esquerda ('1', '50'); prefixados mantêm zeros e
    caixa ('SWSH001', 'XY01', 'SM01', 'TG01', 'GG01', 'SV001', 'H1'); sufixo em
    minúscula ('SM30a', 'XY67a', '28a'). Só se remove o zero à esquerda quando
    vem ANTES de uma letra (forma CT '0H2' → 'H2') ou o número é puro."""
    if not raw:
        return ""
    head = str(raw).split("/")[0].strip()
    if "|" in head:
        head = head.split("|")[-1].strip()
    if not head:
        return ""
    if head.isdigit():
        return head.lstrip("0") or "0"
    return re.sub(r"^0+(?=[A-Za-z])", "", head)


def clean_collector_number(raw: str) -> str:
    """Normaliza um collector_number pra uso em query no pokemontcg.io.
    Entrada pode vir limpa ("007") ou com rarity concatenada ("SIR | 161/131").
    Saída: só o dígito, sem zeros à esquerda ("161", "7").
    """
    if not raw:
        return ""
    m = _NUMBER_IN_VERSION.search(raw)
    if m:
        return m.group(1).lstrip("0") or "0"
    # fallback: separador "/" sem total, ou só o número
    head = raw.split("/")[0].strip()
    # mantém só dígitos se houver sujeira ("TG01", "SWSH123")
    digits = "".join(c for c in head if c.isdigit())
    return digits.lstrip("0") or digits or head


# ══════════════════════════════════════════════════════════════════════
# MODELS — dataclasses em vez de dicts soltos. Por quê?
#   1. Autocompletar no IDE
#   2. Typos viram erro em vez de KeyError em produção
#   3. Serialização fácil para .xlsx/.json
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Listing:
    """Uma oferta ativa em CardTrader (um seller + uma carta + 1 condição)."""
    product_id: int                  # ID do listing no CT
    blueprint_id: int                # ID da carta-molde
    card_name: str
    set_code: str                    # ex: "sv1", "sv3pt5"
    set_name: str
    collector_number: str            # ex: "125/165"
    condition: str                   # "Near Mint", "Slightly Played"...
    language: str                    # "en", "it"...
    price_cents: int                 # centavos no currency original do listing
    price_currency: str              # moeda original do listing ("BRL", "EUR", "USD")
    price_brl: float                 # preço normalizado em BRL (moeda interna)
    quantity: int
    foil: bool
    graded: bool
    seller_username: str
    seller_can_sell_via_hub: bool    # envio centralizado (+rápido, +seguro)
    seller_user_type: str            # "private", "professional", "zero_fee"
    cardtrader_url: str
    # v2.5 (2026-05-16): rarity persistida pra Chase Tier no postprocess v2+.
    # Fonte: blueprint CT (preferido) ou properties_hash. String vazia ""
    # se nem CT nem properties trouxerem (raro mas defensivo).
    rarity: str = ""
    # B1: edição da OFERTA (properties_hash.first_edition). `first_edition_known` = a
    # chave veio no payload (sem ela não dá pra afirmar "Unlimited" na conferência).
    first_edition: bool = False
    first_edition_known: bool = False

    @property
    def uid(self) -> str:
        """Identificador único p/ dedup: carta + seller + condição + edição + reverse
        (1st/Unlimited e reverse/normal do mesmo vendedor NÃO se fundem)."""
        return ct_variants.offer_uid(self.blueprint_id, self.seller_username, self.condition,
                                     self.first_edition, bool(self.foil))


@dataclass
class Opportunity:
    """Arbitragem detectada: listing CT com preço TCG conhecido e margem.
    Tudo em BRL (moeda interna do scanner). USD market é mantido como
    referência da fonte (TCGPlayer) pra auditoria.

    Campos `_real` / `live_*` / `markup_*` / `validation_status` são preenchidos
    pela v2.0 (validate_per_blueprint) — quando habilitada, faz uma chamada
    ao endpoint per-blueprint (preço com markup CT embutido) pros top N
    candidatos e recalcula margens reais.
    """
    listing: Listing
    tcg_market_usd: float            # preço market do TCGPlayer (fonte original)
    tcg_market_brl: float            # convertido USD→BRL
    ct_price_brl: float              # preço CT normalizado em BRL (per-expansion, RAW)
    margin_pct: float                # (tcg_brl - ct_brl) / tcg_brl
    margin_brl: float                # tcg_brl - ct_brl em R$ absolutos
    estimated_shipping_brl: float    # frete estimado em BRL (default 0 — modelo consolidação)
    net_margin_pct: float            # margem após dedução de frete (= margem bruta quando frete=0)
    scanned_at: str = field(default_factory=lambda: now_iso())
    # v2.0 — validação per-blueprint (preço REAL com markup CT)
    validation_status: str = "NOT_VALIDATED"
    live_price_brl: Optional[float] = None
    real_margin_pct: Optional[float] = None
    real_net_margin_pct: Optional[float] = None
    real_lucro_brl: Optional[float] = None
    markup_pct: Optional[float] = None
    markup_tier: Optional[str] = None
    # v2.7.1 (2026-05-18): URL TCGPlayer da carta exata matched no pokemontcg.io.
    # Vem de `card.tcgplayer.url` na response da API. Pra operador validar a
    # variante correta (ex: Lusamine 1st Place vs normal) antes de comprar.
    # Pode ser None quando: provider != pokemontcg, card sem entry TCGPlayer,
    # ou cobertura ruim da fonte.
    tcg_url: Optional[str] = None
    # v2.8 Layer 4 (2026-05-18): variante TCGPlayer usada no cálculo de margem.
    # Foil-aware disambiguation: listing CT foil → prioriza `holofoil`;
    # listing CT non-foil → prioriza `reverseHolofoil` (default landing TCG
    # pra 90% dos Holo Rare antigos). Sem essa coluna o operador não sabia
    # se o preço scanner vinha de Holofoil ($224 Pichu ecard1/22) ou Reverse
    # Holofoil ($50 mesma carta). Valores: "holofoil", "reverseHolofoil",
    # "normal", "unlimitedHolofoil", "" (provider != pokemontcg ou sem variant).
    price_variant_used: Optional[str] = None
    # v2.23: FONTE do preço de referência — "pokemontcg" (default) ou "tcgcsv"
    # (fallback consultado só quando a pokemontcg.io não precifica o set inteiro,
    # ex.: asc/Ascended Heroes). Ambos são preços TCGplayer REAIS; o rótulo é só
    # proveniência (honestidade real-vs-fonte) pro operador distinguir um deal de
    # fallback de um da pokemontcg.io. "" quando não setado.
    price_source: Optional[str] = None
    # v2.13 (2026-06-09): frente "chase cards" — tier de raridade (TOP/MID/
    # MODEST/BULK/""). Derivado da rarity oficial pokemontcg.io quando
    # disponível, senão da rarity do blueprint CT. Usado pelo --chase-only e
    # pela coluna Chase Tier no XLSX.
    chase_tier: str = ""
    # v2.13: frente "valorização" — score heurístico 0-100 (rarity + idade do
    # set + preço-âncora) + nota explicativa. NÃO é previsão (sem série
    # histórica na fonte); é triagem. Ver compute_valorization().
    valorization_score: int = 0
    valorization_note: str = ""
    # v2.13: data de lançamento do set (pokemontcg.io set.releaseDate), pra
    # auditoria da idade usada no score. "" quando a fonte não traz.
    set_release_date: str = ""
    # v2.14 (correção de resultado — candidato 4): FLAG de BAIXA CONFIANÇA de
    # variante. True quando o listing CT é NÃO-foil (foil=False) mas o único
    # preço disponível na pokemontcg.io foi de uma variante METÁLICA premium
    # (holofoil/unlimitedHolofoil) — i.e. nem `normal` nem `reverseHolofoil`
    # existiam. Nesse caso o preço de referência pode ser da variante ERRADA
    # (a holo costuma valer 3-10× a não-foil) e a margem fica inflada.
    # NÃO altera preço nem decisão — é só um sinal pro operador validar via
    # Link TCG (caso load-bearing: Gengar não-foil casando preço holo $1600).
    # reverseHolofoil NÃO dispara a flag de propósito: é o fallback INTENCIONAL
    # pra Holo Rare vintage (v2.10 Layer 4.1), onde non-foil↔reverse é correto.
    variant_low_confidence: bool = False
    # v2.22 (2026-06-22): True quando o listing foi precificado mas a margem
    # bruta ficou ABAIXO do threshold. Sob o contrato de entrega (keep_all_priced),
    # essas linhas são persistidas no XLSX pra alimentar o fallback near-miss do
    # postprocess — em vez de serem descartadas no scan (o que esvaziava a
    # entrega). NÃO conta como "oportunidade" no funil; é referência near-miss.
    below_threshold: bool = False
    # Lote 3: data/hora (ISO, local) em que a REFERÊNCIA de preço foi obtida
    # NESTE run (pokemontcg.io: consulta; tcgcsv: prefill do set). "" se a fonte
    # não informa. Acompanha `price_source` (fonte) em toda linha.
    price_fetched_at: str = ""
    # Lote 3c: data/hora (com fuso) em que a validação per-blueprint foi feita e
    # se ela foi REAPROVEITADA de um run interrompido (--resume-validation).
    validated_at: str = ""
    validation_reused: bool = False
    # B1: variante da oferta e do par de referência. `edition` ∈ ED_1ST|ED_UNL|ED_NONE (da
    # chave de referência casada), `finish` ∈ FIN_*; `ref_compatible` = Match OK com par
    # IDÊNTICO ao da oferta (única condição p/ o postprocess aceitar COMPRA).
    edition: Optional[str] = None      # None = NÃO INFORMADA (ex.: checkpoint antigo)
    finish: Optional[str] = None
    ref_compatible: bool = False
    validation_reason: str = ""
    # B1b: data do DADO de referência (dump do tcgcsv / updatedAt do TCGplayer) e o rótulo:
    # "dado de" (data do dado) ou "buscado em" (só a hora da busca, quando a fonte não expõe a data)
    ref_data_at: str = ""
    ref_data_label: str = ""


# ══════════════════════════════════════════════════════════════════════
# CACHE — SQLite local. Por quê?
#   - Evita hammer nas APIs (reduz custo em planos pagos, reduz banimento)
#   - Retomada em caso de crash
#   - Permite --dry-run para testar filtros sem re-buscar tudo
#   - 1 arquivo, zero setup (vs Redis/Postgres)
# ══════════════════════════════════════════════════════════════════════
class Cache:
    # Lote 3c: referência/FX buscada ANTES do início do run nunca vale (trava
    # estrutural além do clear_prices). None = sem limite (--dry-run/debug).
    min_fetched_at: Optional[datetime] = None

    def __init__(self, db_path: Path = CACHE_DB):
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA journal_mode=WAL")  # melhor concorrência
        self._init_schema()

    def _init_schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS blueprints (
            ct_blueprint_id INTEGER PRIMARY KEY,
            ct_expansion_code TEXT,
            name TEXT,
            collector_number TEXT,
            raw_json TEXT,
            fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS price_cache (
            key TEXT PRIMARY KEY,    -- "pokemontcg:<tcg_id>" ou similar
            market_usd REAL,
            low_usd REAL,
            mid_usd REAL,
            raw_json TEXT,
            fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS fx_cache (
            pair TEXT PRIMARY KEY,   -- "USD_BRL", "EUR_BRL"
            rate REAL,
            fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS blueprint_to_pricing (
            -- mapping CT blueprint → pricing provider product ID
            ct_blueprint_id INTEGER,
            provider TEXT,           -- "pokemontcg", "justtcg", "tcgplayer"
            provider_product_id TEXT,
            confidence REAL,         -- 0-1, quão confiante o match é
            matched_at TEXT,
            PRIMARY KEY (ct_blueprint_id, provider)
        );
        CREATE INDEX IF NOT EXISTS idx_bp_exp ON blueprints(ct_expansion_code);
        """)
        self.db.commit()

    def get_fx(self, pair: str) -> Optional[float]:
        row = self.db.execute(
            "SELECT rate, fetched_at FROM fx_cache WHERE pair = ?", (pair,)
        ).fetchone()
        if not row:
            return None
        rate, fetched_at = row
        if datetime.fromisoformat(fetched_at) < datetime.now() - FX_TTL:
            return None
        if self.min_fetched_at and datetime.fromisoformat(fetched_at) < self.min_fetched_at:
            return None
        return rate

    def set_fx(self, pair: str, rate: float):
        self.db.execute(
            "INSERT OR REPLACE INTO fx_cache VALUES (?, ?, ?)",
            (pair, rate, datetime.now().isoformat()),
        )
        self.db.commit()

    def get_price(self, key: str) -> Optional[dict]:
        row = self.db.execute(
            "SELECT market_usd, low_usd, mid_usd, raw_json, fetched_at FROM price_cache WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        market, low, mid, raw_json, fetched_at = row
        if datetime.fromisoformat(fetched_at) < datetime.now() - PRICE_TTL:
            return None
        if self.min_fetched_at and datetime.fromisoformat(fetched_at) < self.min_fetched_at:
            return None
        # v2.7.1: extrai `tcgplayer.url` do raw_json pra hidratar Opportunity
        # mesmo em cache hit (sem refazer _search()). raw_json é o card dict
        # original do pokemontcg.io. Falha de parse = url None (não crash).
        # v2.8 Layer 4: também extrai `_variant_used` (gravado pelo provider
        # no card dict antes de json.dumps). Cache hit antigo (pre-v2.8) não
        # tem essa key → variant_used vira None, scanner persiste vazio.
        tcg_url = None
        variant_used = None
        raw_prices: dict = {}
        ref_data_at = None
        # v2.13 (valorização): extrai metadados do card pokemontcg.io já cacheado
        # (set.releaseDate + rarity oficial). ZERO fetch extra — reusa o raw_json
        # que set_price já persistiu. Usado pelo score de valorização (idade do
        # set) e pela coluna Chase Tier (rarity oficial > rarity do CT).
        ptcg_rarity = None
        set_release_date = None
        # v2.24: `normal.market` do raw cacheado (ZERO fetch extra) — alimenta o
        # guard reverse-outlier mesmo em cache hit (o run diário usa cache).
        normal_market = None
        try:
            if raw_json:
                raw = json.loads(raw_json)
                tcg_url = (raw.get("tcgplayer") or {}).get("url")
                variant_used = raw.get("_variant_used")
                ptcg_rarity = raw.get("rarity")
                set_release_date = (raw.get("set") or {}).get("releaseDate")
                tcg_prices = (raw.get("tcgplayer") or {}).get("prices") or {}
                normal_market = (tcg_prices.get("normal") or {}).get("market")
                raw_prices = tcg_prices if isinstance(tcg_prices, dict) else {}
                ref_data_at = _iso_date((raw.get("tcgplayer") or {}).get("updatedAt"))
        except (json.JSONDecodeError, AttributeError, TypeError):
            tcg_url = None
            variant_used = None
        return {"market_usd": market, "low_usd": low, "mid_usd": mid,
                "tcg_url": tcg_url, "variant_used": variant_used,
                "ptcg_rarity": ptcg_rarity, "set_release_date": set_release_date,
                "normal_market": normal_market, "fetched_at": fetched_at,
                "prices": raw_prices, "ref_data_at": ref_data_at}

    def set_price(self, key: str, market: float, low: float, mid: float, raw: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO price_cache VALUES (?, ?, ?, ?, ?, ?)",
            (key, market, low, mid, json.dumps(raw), datetime.now().isoformat()),
        )
        self.db.commit()

    def get_mapping(self, blueprint_id: int, provider: str) -> Optional[str]:
        row = self.db.execute(
            "SELECT provider_product_id FROM blueprint_to_pricing WHERE ct_blueprint_id=? AND provider=?",
            (blueprint_id, provider),
        ).fetchone()
        return row[0] if row else None

    def set_mapping(self, blueprint_id: int, provider: str, product_id: str, confidence: float):
        self.db.execute(
            "INSERT OR REPLACE INTO blueprint_to_pricing VALUES (?, ?, ?, ?, ?)",
            (blueprint_id, provider, product_id, confidence, datetime.now().isoformat()),
        )
        self.db.commit()

    def begin_run(self) -> None:
        """Início de um run de coleta: marca o limite (nenhuma referência/FX
        anterior a agora é lida) e limpa os caches voláteis."""
        self.min_fetched_at = datetime.now()
        self.clear_prices()

    def clear_prices(self):
        """Limpa caches voláteis (preços TCG e FX). Útil pra --no-cache em
        cenários de arbitragem time-sensitive onde 24h TTL é tempo demais."""
        self.db.execute("DELETE FROM price_cache")
        self.db.execute("DELETE FROM fx_cache")
        self.db.commit()


# ══════════════════════════════════════════════════════════════════════
# FX — Frankfurter API (BCE, grátis, sem auth). Moeda interna = BRL.
# ══════════════════════════════════════════════════════════════════════
def _fetch_fx(pair: str, frm: str, to: str, cache: Cache) -> float:
    cached = cache.get_fx(pair)
    if cached is not None:
        return cached
    r = requests.get(f"{FX_BASE}?from={frm}&to={to}", timeout=TIMEOUT)
    r.raise_for_status()
    rate = r.json()["rates"][to]
    cache.set_fx(pair, rate)
    log.info(f"FX {frm}→{to} atualizado: {rate:.4f}")
    return rate

def get_usd_to_brl(cache: Cache) -> float:
    return _fetch_fx("USD_BRL", "USD", "BRL", cache)

def get_eur_to_brl(cache: Cache) -> float:
    return _fetch_fx("EUR_BRL", "EUR", "BRL", cache)


# ══════════════════════════════════════════════════════════════════════
# CARDTRADER CLIENT — API oficial, JSON REST, JWT Bearer.
# Rate limit (confirmado na docs):
#   - 10 req/s por endpoint
#   - 200 req / 10s no total
# Estratégia: delay de 0.15s entre requests (~6.7/s, folga de 30%)
# ══════════════════════════════════════════════════════════════════════
def _clean_secret(value: Optional[str]) -> Optional[str]:
    """Sanitiza um segredo (token/API key) lido de env/.env/secret do CI.

    Remove BOM (U+FEFF), zero-width space (U+200B) e espacos/quebras nas pontas.
    Headers HTTP sao codificados em latin-1 pelo `requests`; um BOM colado por
    engano no secret (arquivo salvo como UTF-8-with-BOM, copy/paste do site)
    vira `UnicodeEncodeError: 'latin-1' codec can't encode '\\ufeff'` e derruba
    100% das chamadas — foi exatamente o que abortou o scan no GitHub Actions
    (mass pricing failure 20/20). `str.strip()` NAO remove BOM, entao tratamos
    explicitamente. Retorna None se sobrar vazio.
    """
    if value is None:
        return None
    cleaned = value.replace("\ufeff", "").replace("\u200b", "").strip()
    return cleaned or None


class CardTraderClient:
    def __init__(self, jwt: str, delay: float = REQUEST_DELAY_CT):
        jwt = _clean_secret(jwt)
        if not jwt:
            raise ValueError("CT_JWT não configurado no .env")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
            "User-Agent": "MasterBox-TCG-Scanner/1.0 (contato via cardtrader.com)",
        })
        self.delay = delay
        self._last_call = 0.0
        self.rate_limit_hits = 0  # Lote 3b: 429 acumulados (progresso da validação)

    def _get(self, path: str, deadline_ts: Optional[float] = None, **params) -> dict | list:
        """GET com retry. Aceita `deadline_ts` (monotonic): se passar, retries
        e sleeps respeitam a deadline (v2.8 Codex H2 fix — antes uma chamada
        429 com Retry-After 60s podia segurar a set bem além do per-set-timeout).
        """
        elapsed = time.time() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        url = f"{CT_BASE}{path}"

        def _deadline_exceeded() -> bool:
            return deadline_ts is not None and time.monotonic() > deadline_ts

        def _sleep_capped(wait_s: float) -> bool:
            """Sleep cap pra não passar da deadline. Retorna True se a deadline
            estourou OU se o backoff pedido (`wait_s`) não coube no tempo
            restante (não dá pra honrar a espera → não adianta tentar de novo).

            Fix 2026-06-15 (correção/robustez): antes o retorno era só
            `time.monotonic() > deadline_ts` APÓS dormir `min(wait_s, remaining)`.
            Quando `wait_s > remaining`, dormíamos exatamente até a deadline e o
            `>` voltava False por uma fração de segundo (sleep retorna um tiquinho
            cedo / arredondamento), o loop fazia `continue`, re-tentava e
            mascarava o timeout (ex.: 429 Retry-After 60s com 3s restantes
            "passava" em vez de abortar). Agora, se o backoff foi TRUNCADO pela
            deadline, sinalizamos estouro de forma determinística."""
            if deadline_ts is None:
                time.sleep(wait_s)
                return False
            remaining = deadline_ts - time.monotonic()
            if remaining <= 0:
                return True
            truncated = wait_s > remaining
            time.sleep(min(wait_s, remaining))
            # Estourou se: passou da deadline OU o backoff teve que ser cortado
            # (não conseguimos esperar o tempo necessário pra a próxima tentativa).
            return truncated or time.monotonic() > deadline_ts

        if _deadline_exceeded():
            raise TimeoutError(f"CT _get({path}): deadline already exceeded before request")

        # Retry com backoff 2/4/8s pra erros transientes (connection reset, 5xx,
        # rate limit). Descoberto em 2026-04-20 quando scan de 7 sets crashou
        # no 4º por ConnectionResetError no /blueprints/export.
        last_err: Optional[Exception] = None
        for attempt in range(3):
            # v2.8: usa min(TIMEOUT, tempo restante até deadline) pra request timeout
            req_timeout = TIMEOUT
            if deadline_ts is not None:
                remaining = max(1.0, deadline_ts - time.monotonic())
                req_timeout = min(TIMEOUT, remaining)
            try:
                r = self.session.get(url, params=params, timeout=req_timeout)
                self._last_call = time.time()
                if r.status_code == 429:
                    self.rate_limit_hits += 1
                    retry_after = int(r.headers.get("Retry-After", "5"))
                    log.warning(f"Rate limit CT, esperando {retry_after}s...")
                    if _sleep_capped(retry_after):
                        raise TimeoutError(
                            f"CT _get({path}): deadline excedida em sleep pós-429"
                        )
                    continue
                if 500 <= r.status_code < 600:
                    backoff = 2 ** attempt
                    log.warning(f"CT {r.status_code}, retry em {backoff}s...")
                    if _sleep_capped(backoff):
                        raise TimeoutError(
                            f"CT _get({path}): deadline excedida em sleep pós-5xx"
                        )
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                backoff = 2 ** attempt
                log.warning(f"CT {type(e).__name__}, retry em {backoff}s... ({attempt+1}/3)")
                if _sleep_capped(backoff):
                    raise TimeoutError(
                        f"CT _get({path}): deadline excedida em sleep pós-{type(e).__name__}"
                    ) from e
        if last_err:
            raise last_err
        raise requests.ConnectionError("CT: esgotou 3 tentativas")

    def list_expansions(self, game_id: int = CT_POKEMON_GAME_ID) -> list[dict]:
        """Lista todas as expansões (sets) de Pokemon no CT."""
        data = self._get("/expansions")
        # API retorna TODAS as expansões de TODOS os jogos; filtra por game_id
        return [e for e in data if e.get("game_id") == game_id]

    def list_blueprints(self, expansion_id: int, deadline_ts: Optional[float] = None) -> list[dict]:
        """Lista blueprints (cartas-molde) de uma expansão."""
        # Nota: /blueprints/export retorna tudo de uma vez; /blueprints paginado.
        # Usamos /blueprints/export por simplicidade.
        return self._get("/blueprints/export", deadline_ts=deadline_ts, expansion_id=expansion_id)

    def list_listings_by_blueprint(self, blueprint_id: int, language: str = "en",
                                    deadline_ts: Optional[float] = None) -> list[dict]:
        """Lista TODAS as ofertas ativas para um blueprint."""
        return self._get("/marketplace/products",
                         deadline_ts=deadline_ts,
                         blueprint_id=blueprint_id,
                         language=language)

    def list_listings_by_expansion(self, expansion_id: int, language: str = "en",
                                    deadline_ts: Optional[float] = None) -> list[dict]:
        """Lista TODAS as ofertas de uma expansão inteira (bem mais eficiente)."""
        data = self._get("/marketplace/products",
                         deadline_ts=deadline_ts,
                         expansion_id=expansion_id,
                         language=language)
        # API retorna dict[blueprint_id, list[listing]] — flatten para list
        if isinstance(data, dict):
            return [l for listings in data.values() for l in listings]
        return data


# ══════════════════════════════════════════════════════════════════════
# PRICING PROVIDERS — abstração. Trocar fonte = trocar 1 classe.
# Por que interface abstrata (Strategy Pattern)?
#   - TCGPlayer API oficial está fechada em 2026 → precisamos de plano B
#   - JustTCG cobra, pokemontcg.io é grátis → quer escolher dinamicamente
#   - Testabilidade: mock em testes sem chamar API real
# ══════════════════════════════════════════════════════════════════════
class PricingProvider(ABC):
    name: str = "base"
    # v2.7.1 (2026-05-18): URL TCGPlayer da última carta consultada com sucesso.
    # Provider sobrescreve em cada market_price_usd() bem-sucedido (set via
    # `self.last_tcg_url = ...`). scan_expansion lê após cada chamada e
    # propaga pra Opportunity.tcg_url. Reset pra None em cada chamada
    # (qualquer cache hit + lookup miss reseta) pra evitar carry-over entre
    # cards diferentes.
    last_tcg_url: Optional[str] = None
    # v2.8 Layer 4 (2026-05-18): variante TCGPlayer usada pra resolver o preço
    # (`holofoil`, `reverseHolofoil`, `normal`, `unlimitedHolofoil`). Provider
    # foil-aware sobrescreve a cada chamada. scan_expansion propaga pra
    # Opportunity.price_variant_used. Reset pra None igual `last_tcg_url`.
    last_variant_used: Optional[str] = None
    # v2.24 (2026-06-26): `normal.market` (USD) da última carta precificada, quando
    # a fonte expõe a variante `normal`. Usado pelo guard reverse-outlier
    # (_reverse_nonholo_market_outlier) pra comparar o reverseHolofoil casado
    # contra a âncora líquida `normal`. None quando a fonte não tem `normal`
    # (tipicamente holo rares — guard não dispara nesse caso).
    last_normal_market: Optional[float] = None
    # B1: resultado do casamento de variante da ÚLTIMA chamada (ct_variants.Match). Status ""
    # = carta não encontrada na fonte (miss de cobertura).
    last_ref_status: str = ""
    last_ref_reason: str = ""
    last_ref_key: Optional[str] = None
    last_ref_exact: bool = False
    last_available_keys: list = []
    last_offer_variant: Optional[tuple] = None   # (edicao, acabamento) da oferta
    last_divided: bool = False                   # a carta tem chaves de edição na fonte
    last_era_missing: bool = False
    last_ref_data_at: Optional[str] = None   # data do DADO (não da busca), quando a fonte expõe

    def _reset_ref(self) -> None:
        self.last_ref_status, self.last_ref_reason, self.last_ref_key = "", "", None
        self.last_ref_exact, self.last_available_keys = False, []
        self.last_offer_variant, self.last_divided, self.last_era_missing = None, False, False
        self.last_ref_data_at = None

    def _set_ref(self, m, prices: dict, offer: tuple, era_missing: bool,
                 rarity: Optional[str] = None) -> None:
        self.last_offer_variant, self.last_era_missing = offer, era_missing
        self.last_ref_status, self.last_ref_reason = m.status, m.reason
        self.last_ref_key = m.key
        self.last_available_keys = ct_variants.available_keys(prices)
        self.last_divided = ct_variants.is_divided(prices)
        self.last_ref_exact = ct_variants.is_exact(m, *offer)
        # B1b: raridade da CT inconclusiva (Promo, vazia, fora das listas) + referência com UM
        # único acabamento não-reverse: NÃO autoriza casar — só explica por que ficou sem ref.
        if (m.status == ct_variants.INCOMPATIVEL and offer[1] != ct_variants.FIN_REVERSE
                and not ct_variants.rarity_conclusive(rarity)):
            nonrev = sorted(k for k, c in ct_variants._usable(prices).items()
                            if c[1] != ct_variants.FIN_REVERSE)
            if len(nonrev) == 1:
                self.last_ref_reason += (
                    f" — raridade CT {rarity!r} inconclusiva p/ holo; a referência só tem a chave de preço "
                    f"{nonrev[0]} (edição+acabamento; isso não autoriza casar)")

    @abstractmethod
    def market_price_usd(self, card_name: str, set_code: str,
                         collector_number: str,
                         foil: bool = False,
                         rarity: Optional[str] = None,
                         first_edition: bool = False) -> Optional[float]:
        """Retorna preço market em USD ou None se não achar.

        `foil`: indica se o listing CT é reverse-holo (pokemon_reverse=True
        em Pokémon, mtg_foil em MTG). Provider usa pra priorizar a variante
        correta (reverseHolofoil vs holofoil vs normal) no agregador
        pokemontcg.io (fix H2 2026-05-11; v2.18 2026-06-20).
        `rarity`: raridade do listing CT ("Holo Rare", "Common", ...). v2.18
        usa pra distinguir holo rare padrão (→ holofoil) de carta base
        (→ normal) quando foil=False.
        """
        ...


# Escolha de chave de preço: ct_variants.match_reference_variant (correspondência EXATA de
# edição e acabamento; sem escada de fallback e sem exclusão de 1st Edition).


# v2.24 (2026-06-26): razão reverse/normal acima da qual o preço reverseHolofoil
# de uma carta NÃO-holo é tratado como outlier ilíquido (não uma âncora confiável).
# Cartas comuns/incomuns da era EX que são genuinamente reverse (foil=True) casam
# CORRETAMENTE em reverseHolofoil — mas o `reverseHolofoil.market` da pokemontcg.io
# pra vintage barato é um número fino, dirigido por outlier, não líquido. Exemplos
# reais (pokemontcg.io ao vivo, 2026-06-26): Lileep ex12-56 normal $0.55 vs reverse
# $37.50 (68×), Slugma ex8-75 (56×), Kakuna ex6-36 (57×), Persian ex6-44 (22×),
# Volbeat ex9-42 (14×) — todos passaram como COMPRA limpa. Contra-exemplo legítimo:
# Zubat ecard3-118 (Skyridge) normal $33.47 vs reverse $104.99 (3.1×) = prêmio
# reverse Skyridge real, NÃO deve disparar. RATIO=5.0 separa os dois grupos.
REVERSE_NONHOLO_OUTLIER_RATIO = 5.0


def _reverse_nonholo_market_outlier(
    variant_used: Optional[str],
    is_holo: bool,
    selected_market: Optional[float],
    normal_market: Optional[float],
    ratio: float = REVERSE_NONHOLO_OUTLIER_RATIO,
) -> bool:
    """v2.24: True quando o preço de referência casou em `reverseHolofoil` pra uma
    carta NÃO intrinsecamente holo (Common/Uncommon/Rare não-holo) E esse preço
    reverse é um outlier absurdo vs o preço `normal` (> `ratio`× o normal).

    Estende o sinal "Variante Baixa Confiança" (v2.18) pro caso que ele
    DELIBERADAMENTE não pegava: o v2.18 não dispara pra listings reverse genuínos
    (foil=True → reverseHolofoil é a variante CORRETA), porque essa exclusão foi
    pensada pra Holo Rare (onde reverse é o fallback intencional). O buraco: uma
    common/uncommon NÃO-holo que casa em reverseHolofoil cujo market é fino e
    inflado (68× o normal no Lileep). Aqui NÃO se exige `foil` — o sinal é
    independente de foil; o que importa é a variante escolhida + a razão.

    Dispara SÓ quando TODOS valem:
      1. variante escolhida == `reverseHolofoil`;
      2. a carta NÃO é intrinsecamente holo (`is_holo` False);
      3. existe `normal.market` (> 0) E `reverseHolofoil.market` >
         `ratio` × `normal.market`.
    Se `normal.market` está ausente, NÃO dispara — essas são tipicamente holo
    rares (já excluídas por #2 de qualquer modo). Sinal-only: NÃO mexe em
    margem/preço/bucket; só roteia a linha pra validação manual (REVISAR).
    """
    if variant_used != "reverseHolofoil":
        return False
    if is_holo:
        return False
    if not normal_market or normal_market <= 0:
        return False
    if not selected_market or selected_market <= 0:
        return False
    return selected_market > ratio * normal_market


class PokemonTcgIoProvider(PricingProvider):
    """
    pokemontcg.io v2 — GRÁTIS.
    Inclui campo `tcgplayer.prices.{variant}.market` (USD, TCGPlayer).
    Atualização diária. Limite: 20k req/dia com key grátis, 1k sem.

    Por que esse é o default? Porque a API oficial do TCGPlayer está
    fechada para novos devs, e esse agregador entrega o MESMO dado
    (preço market TCGPlayer) com zero custo.
    """
    name = "pokemontcg"

    def __init__(self, api_key: Optional[str], cache: Cache,
                 delay: float = REQUEST_DELAY_PRICING):
        self.session = requests.Session()
        api_key = _clean_secret(api_key)
        if api_key:
            self.session.headers["X-Api-Key"] = api_key
        self.cache = cache
        self.delay = delay
        self._last_call = 0.0
        self.retry_5xx = 0          # B1e: retries por 429/5xx neste run (resumo)

    def probe(self, timeout: float = 5.0) -> bool:
        """B1e: sonda BARATA de saúde — 1 chamada, sem retry, sem backoff. True = HTTP 200."""
        try:
            r = self.session.get(f"{POKEMONTCG_BASE}/cards",
                                 params={"pageSize": 1, "select": "id"}, timeout=timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_call = time.time()

    def _ptcg_get(self, params: dict):
        """GET na pokemontcg.io com retry bounded em erros TRANSIENTES
        (429 rate-limit, 5xx). Distingue:
          - 200            → retorna Response (caller parseia data/totalCount)
          - 429 / 5xx      → retry com backoff curto; se persistir, levanta
                             requests.Timeout (→ scan loop conta como
                             pricing_failure, NÃO como "miss" de cobertura)
          - 4xx ≠ 429      → retorna a Response (caller trata como "sem match";
                             é resposta legítima do servidor, não falha)

        Fix 2026-06-15 (correção/robustez — candidato 5): antes QUALQUER
        status != 200 (incluindo 429 e 5xx) virava `continue` → `_search`
        devolvia None → o loop de pricing contava como "miss" de cobertura.
        Consequências: (a) rate-limit/queda transitória da fonte sumia deals
        em silêncio; (b) o contador de "misses consecutivos" era envenenado e
        podia abortar sets bons com `no_coverage`; (c) inflava a taxa aparente
        de falha. Agora 429/5xx são tratados como falha transiente VISÍVEL
        (logada + contabilizada), não como ausência de carta.
        """
        last_status = None
        for attempt in range(3):
            self._rate_limit()
            r = self.session.get(f"{POKEMONTCG_BASE}/cards",
                                 params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            last_status = r.status_code
            if r.status_code == 429 or 500 <= r.status_code < 600:
                self.retry_5xx = getattr(self, "retry_5xx", 0) + 1
                # Transiente: respeita Retry-After (429) ou backoff exponencial.
                try:
                    retry_after = int(r.headers.get("Retry-After", "0"))
                except (TypeError, ValueError):
                    retry_after = 0
                backoff = retry_after if retry_after > 0 else 2 ** attempt
                # Cap defensivo: nunca dorme mais que TIMEOUT por tentativa.
                backoff = min(backoff, TIMEOUT)
                log.warning(
                    f"pokemontcg.io {r.status_code} (transiente), retry em "
                    f"{backoff}s... ({attempt + 1}/3)"
                )
                time.sleep(backoff)
                continue
            # 4xx ≠ 429 → resposta legítima do servidor; caller decide.
            return r
        # Esgotou retries num status transiente → falha VISÍVEL, não "miss".
        raise requests.Timeout(
            f"pokemontcg.io: status {last_status} persistente após 3 tentativas"
        )

    # v2.7 Layer 1.5 (bug-hunt 2026-05-18): alias map CT → pokemontcg.io.
    # CT usa códigos curtos derivados de TCGPlayer/comunidade; pokemontcg.io
    # usa codes oficiais Wizards/Nintendo da era. Sem alias, Layer 1 (strict
    # set match) rejeita TODA Jungle/Fossil/Neo/Gym/Wizards-era porque
    # ct `ju` ≠ ptcg `base2`. Estende set query no _search: além do código
    # CT, tentamos os aliases listados. Match em qualquer um aceita.
    #
    # Lista derivada do README + probes 2026-05-18. Não exhaustivo, foca
    # sets que apareceram no weekly v2.6 + vintage Wizards essenciais.
    SET_ALIAS_TO_PTCG = {
        # Wizards original era
        "bs": ["base1"],          # Base Set (v2.21: alias confirmado — 102 cards,
                                  # Alakazam holofoil $84). Proteção contra inflação:
                                  # 1stEdition é EXCLUÍDA no pricing + validação
                                  # per-blueprint (Shadowless não é variante TCGPlayer
                                  # separada — o market holofoil é o blend unlimited).
        "ju": ["base2"],          # Jungle
        "fo": ["base3"],          # Fossil
        "b2": ["base4"],          # Base Set 2
        "tr": ["base5"],          # Team Rocket
        "g1": ["gym1"],           # Gym Heroes
        "g2": ["gym2"],           # Gym Challenge
        "n1": ["neo1"],           # Neo Genesis
        "n2": ["neo2"],           # Neo Discovery (cobertura pobre p/ não-1stEd →
                                  # baixo yield; alias mantido por completude)
        "n3": ["neo3"],           # Neo Revelation
        "n4": ["neo4"],           # Neo Destiny
        "lc": ["base6"],          # Legendary Collection
        "si": ["si1"],            # Southern Islands (v2.21: 18 cards)
        "bog": ["bp"],            # Best of Game promos (v2.21: 9 cards, esparso)
        # E-Card era
        "ex": ["ecard1"],         # Expedition Base Set
        "aq": ["ecard2"],         # Aquapolis
        "skg": ["ecard3"],        # Skyridge
        # EX series (Ruby & Sapphire era)
        "dr": ["ex3"],            # EX Dragon
        # Sun & Moon Promos
        "pupr": ["sm5"],          # Ultra Prism Promos → SM Ultra Prism
        # XY Promos
        "xybsp": ["xyp"],         # XY Black Star Promos
        # Sword & Shield era (v2.9 bug-hunt 2026-05-19):
        # CT uses 3-letter ptcgo-style codes; ptcg.io uses positional swsh*.
        # All EN main sets explicitly mapped to avoid Layer 1 strict-set
        # rejection. Verified via CT API (game_id=5) + pokemontcg.io /sets
        # 2026-05-19. Trainer Gallery splits (swsh9tg, swsh10tg, swsh11tg,
        # swsh12tg, swsh12pt5gg) NOT aliased here — TG cards have known
        # inflation bug (regex ^TG\d+ in postprocess routes to MANUAL).
        "ssh":   ["swsh1"],       # Sword & Shield base
        "rcl":   ["swsh2"],       # Rebel Clash
        "daa":   ["swsh3"],       # Darkness Ablaze
        "cpa":   ["swsh35"],      # Champion's Path
        "viv":   ["swsh4"],       # Vivid Voltage
        "shf":   ["swsh45"],      # Shining Fates
        "bst":   ["swsh5"],       # Battle Styles
        "cre":   ["swsh6"],       # Chilling Reign
        "evs":   ["swsh7"],       # Evolving Skies
        "fst":   ["swsh8"],       # Fusion Strike
        "brs":   ["swsh9"],       # Brilliant Stars
        "astr":  ["swsh10"],      # Astral Radiance (CT: astr, NOT asr)
        "pkmgo": ["pgo"],         # Pokémon GO (CT: pkmgo, NOT pgo)
        "lorg":  ["swsh11"],      # Lost Origin (CT: lorg; lot=Lost Thunder)
        "sit":   ["swsh12"],      # Silver Tempest
        "crz":   ["swsh12pt5"],   # Crown Zenith
        # Scarlet & Violet era (v2.9 expansion 2026-05-19):
        # Existing aliases (pre/twm/scr/ssp) retained. Added missing SV core
        # so Layer 1 doesn't drop matches for Paldea Evolved, Obsidian Flames,
        # 151, Paradox Rift, Paldean Fates, Temporal Forces, Shrouded Fable.
        # NOTE: CT codes sv6/sv7/sv8/sv9 point to JP-original sets (Mask of
        # Change, Stellar Miracle, Super Electric Breaker, Battle Partners) —
        # NOT aliased to EN ptcg.io ids on purpose. ptcg.io lacks JP coverage
        # and aliasing would produce wrong cards.
        "svi":   ["sv1"],         # Scarlet & Violet base
        "pal":   ["sv2"],         # Paldea Evolved
        "obf":   ["sv3"],         # Obsidian Flames
        "mew":   ["sv3pt5"],      # 151 (CT: mew)
        "par":   ["sv4"],         # Paradox Rift
        "paf":   ["sv4pt5"],      # Paldean Fates
        "tef":   ["sv5"],         # Temporal Forces
        "twm":   ["sv6"],         # Twilight Masquerade
        "sfa":   ["sv6pt5"],      # Shrouded Fable
        "scr":   ["sv7"],         # Stellar Crown
        "ssp":   ["sv8"],         # Surging Sparks
        "pre":   ["sv8pt5"],      # Prismatic Evolutions
        "jtg":   ["sv9"],         # Journey Together
        "dri":   ["sv10"],        # Destined Rivals
        "blk":   ["zsv10pt5"],    # Black Bolt
        "wht":   ["rsv10pt5"],    # White Flare
        # Mega Evolution era (v2.9 — first ME aliases added 2026-05-19):
        "meg":   ["me1"],         # Mega Evolution base
        "pfl":   ["me2"],         # Phantasmal Flames
        "asc":   ["me2pt5"],      # Ascended Heroes (sfa was timing out → asc same family)
        "por":   ["me3"],         # Perfect Order
        "cri":   ["me4"],         # Chaos Rising (gap pós-v2.10: api_set=me4, alias faltava → todos os cards rejeitados como set mismatch)
        # === v2.10 BATCH (added 2026-05-19 from logs/alias_gaps_2026-05-19.md) ===
        # 110 high-confidence 1-to-1 aliases extracted from 558 rejected
        # (CT_set → api_set) pairs in weekly v2.9 scan log. Criterion: log shows
        # api_set mode with empty runner-ups OR runner-ups with hits ≤ 10% of
        # mode. Ambiguous codes (bs, c25, clb, crz, svpromo, etc.) deferred to
        # v2.11 case-by-case. xytkas/xytkos NOT included — log mapped them to
        # tk1a/tk1b but those are EX Trainer Kits, not XY (pokemontcg.io lacks
        # XY Trainer Kit coverage). EX series core sets dominate this batch.
        # Wizards / vintage era
        "wiz":   ["basep"],       # WotC Promos (Wizards Black Star)
        "nbsp":  ["np"],          # Nintendo Black Star Promos
        # E-Card era (extends existing aq/ex/skg)
        # (nothing new — ecard1/2/3 already covered by ex/aq/skg)
        # EX series (Ruby & Sapphire onwards)
        "rs":    ["ex1"],         # Ruby & Sapphire
        "ss":    ["ex2"],         # Sandstorm
        "exma":  ["ex4"],         # Team Magma vs Team Aqua
        "hl":    ["ex5"],         # Hidden Legends
        "rg":    ["ex6"],         # FireRed & LeafGreen
        "trr":   ["ex7"],         # Team Rocket Returns
        "dx":    ["ex8"],         # Deoxys
        "em":    ["ex9"],         # Emerald
        "uf":    ["ex10"],        # Unseen Forces
        "ds":    ["ex11"],        # Delta Species
        "lm":    ["ex12"],        # Legend Maker
        "hp":    ["ex13"],        # Holon Phantoms
        "cg":    ["ex14"],        # Crystal Guardians
        "df":    ["ex15"],        # Dragon Frontiers
        "pk":    ["ex16"],        # Power Keepers
        # Diamond & Pearl era
        "mt":    ["dp2"],         # Mysterious Treasures
        "sw":    ["dp3"],         # Secret Wonders
        "ge":    ["dp4"],         # Great Encounters
        # (removido no Lote 2: dp6 = Legends Awakened, não WCD 2010 — sets/en.json)
        "sft":   ["dp7"],         # Stormfront
        # Platinum
        "pl":    ["pl1"],         # Platinum base
        "rr":    ["pl2"],         # Rising Rivals
        "prr":   ["pl2"],         # Pre-release Rising Rivals
        "sv":    ["pl3"],         # Supreme Victors (CT 'sv' — NOT Scarlet & Violet!)
        # HeartGold & SoulSilver
        "hgs":   ["hgss1"],       # HeartGold & SoulSilver base
        "ul":    ["hgss2"],       # Unleashed
        "und":   ["hgss3"],       # Undaunted
        "tri":   ["hgss4"],       # Triumphant
        "clo":   ["col1"],        # Call of Legends
        # Black & White era
        "blw":   ["bw1"],         # Black & White base
        "epo":   ["bw2"],         # Emerging Powers
        "nvi":   ["bw3"],         # Noble Victories
        "nxd":   ["bw4"],         # Next Destinies
        "dex":   ["bw5"],         # Dark Explorers
        "drx":   ["bw6"],         # Dragons Exalted
        "bcr":   ["bw7"],         # Boundaries Crossed
        "pbcr":  ["bw7"],         # Promo BCR
        "pls":   ["bw8"],         # Plasma Storm
        "ppls":  ["bw8"],         # Promo PLS
        "plf":   ["bw9"],         # Plasma Freeze
        "pplf":  ["bw9"],         # Promo PLF
        "plb":   ["bw10"],        # Plasma Blast
        "pplb":  ["bw10"],        # Promo PLB
        "ltr":   ["bw11"],        # Legendary Treasures
        "pltr":  ["bw11"],        # Promo LTR
        "drv":   ["dv1"],         # Dragon Vault
        # XY era
        "kss":   ["xy0"],         # Kalos Starter Set
        "xy-en": ["xy1"],         # XY base (EN)
        "flf":   ["xy2"],         # Flashfire
        "ffi":   ["xy3"],         # Furious Fists
        "phf":   ["xy4"],         # Phantom Forces
        "prc":   ["xy5"],         # Primal Clash
        "ros":   ["xy6"],         # Roaring Skies
        "aor":   ["xy7"],         # Ancient Origins
        "bkt":   ["xy8"],         # BREAKthrough
        "bkp":   ["xy9"],         # BREAKpoint
        "pbkp":  ["xy9"],         # Promo BKP
        "fco":   ["xy10"],        # Fates Collide
        "sts":   ["xy11"],        # Steam Siege
        "psts":  ["xy11"],        # Promo STS
        "evo":   ["xy12"],        # Evolutions
        "gen":   ["g1"],          # Generations
        "pgen":  ["g1"],          # Promo Generations
        "dcr":   ["dc1"],         # Double Crisis
        "det":   ["det1"],        # Detective Pikachu (movie set)
        # Sun & Moon era
        "sum":   ["sm1"],         # Sun & Moon base
        "gri":   ["sm2"],         # Guardians Rising
        "bus":   ["sm3"],         # Burning Shadows
        "pbus":  ["sm3"],         # Promo BUS
        "cinv":  ["sm4"],         # Crimson Invasion
        "upr":   ["sm5"],         # Ultra Prism
        "fli":   ["sm6"],         # Forbidden Light
        "ces":   ["sm7"],         # Celestial Storm
        "pces":  ["sm7"],         # Promo CES
        "lot":   ["sm8"],         # Lost Thunder
        "teu":   ["sm9"],         # Team Up
        "unb":   ["sm10"],        # Unbroken Bonds
        "unm":   ["sm11"],        # Unified Minds
        "cec":   ["sm12"],        # Cosmic Eclipse
        "pcec":  ["sm12"],        # Promo CEC
        "slg":   ["sm35"],        # Shining Legends
        "drm":   ["sm75"],        # Dragon Majesty
        "hif":   ["sm115"],       # Hidden Fates
        "pdp":   ["dp1"],         # Promo DP
        # McDonald's promos (trivial 1-to-1)
        "mc11":  ["mcd11"],
        "mc12":  ["mcd12"],
        "mc14":  ["mcd14"],
        "mc15":  ["mcd15"],
        "mc17":  ["mcd17"],
        "mc18":  ["mcd18"],
        "mc19":  ["mcd19"],
        "mc21":  ["mcd21"],
        # World Championship Decks (only mode-strong ones; ambiguous ones skipped)
        "wcd2005": ["ex7"],       # WCD 2005 — Team Rocket Returns
        "wcd2008": ["ex14"],      # WCD 2008 — Crystal Guardians
        "wcd2023": ["swsh9"],     # WCD 2023 — Brilliant Stars
        # Battle Arena / SV-era promo lines (mode-strong)
        "ba-20":   ["dp3"],       # Battle Arena 2020
        "ba-2024": ["svp"],       # Battle Arena 2024
        # Mega Evolution promo lines (m-blk, m-wht — mode-strong)
        "m-blk":   ["zsv10pt5"],  # Mega Black promo line
        "m-wht":   ["rsv10pt5"],  # Mega White promo line
        "p-blk":   ["zsv10pt5"],  # Promo Mega Black
        "p-wht":   ["rsv10pt5"],  # Promo Mega White
    }

    def _search(self, card_name: str, set_code: str, number: str) -> Optional[dict]:
        """B1c: memoriza DENTRO do run (nunca entre runs) o resultado de uma resposta VÁLIDA da
        fonte, inclusive "não encontrada": ofertas repetidas da mesma carta não refazem a busca.
        Exceção de infraestrutura (timeout/5xx) propaga e NÃO é guardada como "não encontrada"."""
        memo = self.__dict__.setdefault("_search_memo", {})
        key = (card_name, (set_code or "").lower(), str(number))
        if key in memo:
            return memo[key]
        card = self._search_uncached(card_name, set_code, number)
        memo[key] = card
        return card

    def _search_uncached(self, card_name: str, set_code: str, number: str) -> Optional[dict]:
        """Busca carta e retorna o primeiro match.
        Estratégia em cascata: primeiro tenta com set.id (mais específico, menor
        risco de falso-match entre reprints). Se retornar 0, tenta sem set.id
        (set codes divergem entre CT e pokemontcg.io — ex: CT `pre` = ptcg
        `sv8pt5`). Na segunda tentativa fica nome+número, que é razoavelmente
        único pra singles.

        v2.7 (bug-hunt 2026-05-18 Layer 1): strict set match no fallback.
        Antes — quando `set.id:X` retornava 0, o fallback aceitava `totalCount==1`
        sem checar set retornado. Isso fez Blastoise CT `clb` matchear
        `base5-3` (Dark Blastoise Team Rocket, 1stEdition $383) e Mewtwo CT
        `xybsp` matchear `rs:101/109` (Mewtwo ex Ruby & Sapphire $269) em vez
        de `xyp:XY101` ($25). Custou ~96% de falsos positivos no weekly v2.6.
        Fix: no fallback, exigir `card.set.id == set_code` (case-insensitive).
        Mismatch → log INFO + skip pra próximo candidato. Trade-off: alguns
        sets perdem cobertura (ex pupr→sm5 = Lusamine Promos Ultra Prism);
        compensado por UNSUPPORTED_SETS no postprocess (Layer 3).
        """
        # Lote 2 (#2): chave que PRESERVA letra/prefixo (H1 ≠ 1; 50A ≠ 50) — a
        # mesma do caminho tcgcsv. O digits-only antigo casava H1 com a carta #1
        # (ex.: Aquapolis: Ampharos "1" e "H1" existem em ecard2.json).
        num_clean = ptcg_number_query(number)
        safe_name = ptcg_card_name(card_name).replace('"', '\\"')
        base_q = f'name:"{safe_name}"'
        if num_clean:
            base_q += f" number:{num_clean}"

        # v2.7 Layer 1.5: monta lista de set_ids aceitos (canonical + aliases).
        # `expected_sets` é o conjunto de set.ids que satisfazem "set match".
        # Inclui o CT code original + qualquer alias mapeado em
        # SET_ALIAS_TO_PTCG. Sem alias → só o code CT (comportamento Layer 1
        # puro). Com alias → varia: pra `ju` aceita {`ju`, `base2`}.
        ct_code = (set_code or "").lower()
        # v2.29: sem identidade pra código CT de set JP que colide (sv8 ≠ SSP).
        expected_sets: set[str] = ptcg_expected_sets(ct_code)
        if not expected_sets:
            return None

        # Cada tupla: (query, strict_set_check).
        # Tentamos uma query por set candidato (CT code + cada alias).
        # strict_set_check só é necessário no fallback sem set.id.
        queries: list[tuple[str, bool]] = []
        for sid in sorted(expected_sets):  # determinism
            queries.append((f'{base_q} set.id:{sid}', False))
        queries.append((base_q, True))

        for q, strict_set_check in queries:
            # _ptcg_get faz retry em 429/5xx e LEVANTA requests.Timeout se
            # persistir (→ pricing_failure no scan loop, não "miss"). Erros 4xx
            # legítimos (≠429) voltam como Response e viram "sem match" abaixo.
            r = self._ptcg_get({"q": q, "pageSize": 5})
            if r.status_code != 200:
                # B1d: 4xx ≠ 429 (401/403…) = credencial/bloqueio, NÃO "carta não encontrada":
                # vira falha operacional visível e nunca entra na memória de busca.
                raise requests.ConnectionError(
                    f"pokemontcg.io HTTP {r.status_code} (credencial/bloqueio?) para {q}")
            resp = r.json()
            results = resp.get("data", [])
            total = resp.get("totalCount", len(results))
            if not results:
                continue
            if strict_set_check:
                # v2.7 Layer 1: rejeita match se set retornado ∉ expected_sets.
                # Não basta totalCount==1 — precisa bater algum set esperado.
                for cand in results:
                    cand_set = (cand.get("set") or {}).get("id", "").lower()
                    if cand_set in expected_sets:
                        return cand
                # Nenhum candidato bate o set_code do CT ou alias
                first_set = (results[0].get("set") or {}).get("id", "")
                log.info(
                    f"set mismatch rejected: CT_set={set_code} (esperado {sorted(expected_sets)}) "
                    f"≠ api_set={first_set} ({total} candidatos) — '{base_q}'"
                )
                continue
            return results[0]
        return None

    def market_price_usd(self, card_name: str, set_code: str,
                         collector_number: str,
                         foil: bool = False,
                         rarity: Optional[str] = None,
                         first_edition: bool = False) -> Optional[float]:
        """Preço market (USD) da variante EXATA da oferta (edição + acabamento).

        B1: a chave de preço sai de `ct_variants.match_reference_variant` (sem escada de
        fallback; 1st Edition é precificada contra 1st Edition). Sem chave compatível devolve
        None com `last_ref_status` ≠ "" e o motivo em `last_ref_reason` — o chamador NÃO
        calcula margem. O cache usa `ct_variants.price_cache_key` (edição, reverse, holo,
        versão da lógica)."""
        self.last_tcg_url = None
        self.last_variant_used = None
        self.last_price_fetched_at = None  # Lote 3: data/hora da referência
        self.last_ptcg_rarity = None
        self.last_set_release_date = None
        self.last_normal_market = None
        self._reset_ref()
        foil = bool(foil)
        pre_holo = ct_variants.rarity_is_holo(rarity, set_code=set_code)   # só p/ a chave de cache; a decisão final usa a era
        cache_key = ct_variants.price_cache_key(set_code, collector_number, card_name,
                                                first_edition, foil, pre_holo)
        cached = self.cache.get_price(cache_key)
        if cached:
            self.last_price_fetched_at = _to_tz_iso(cached.get("fetched_at"))
            self.last_tcg_url = cached.get("tcg_url")
            self.last_variant_used = cached.get("variant_used")
            self.last_ptcg_rarity = cached.get("ptcg_rarity")
            self.last_set_release_date = cached.get("set_release_date")
            self.last_normal_market = cached.get("normal_market")
            self.last_ref_data_at = cached.get("ref_data_at")
            hd = ct_variants.holo_detection(rarity, self.last_ptcg_rarity,
                                            set_released=self.last_set_release_date,
                                            set_code=set_code)
            offer = ct_variants.offer_variant(first_edition, foil, hd.is_holo)
            prices = cached.get("prices") or {}
            m = ct_variants.match_reference_variant(prices, *offer, era_missing=hd.era_missing)
            if m.status == ct_variants.OK and m.key == self.last_variant_used:
                self._set_ref(m, prices, offer, hd.era_missing, rarity)
                return cached["market_usd"]
            # entrada de cache que não reproduz o casamento atual: ignora e refaz (nunca serve palpite)

        card = self._search(card_name, set_code, collector_number)
        if not card:
            return None
        self.last_tcg_url = (card.get("tcgplayer") or {}).get("url")
        self.last_ptcg_rarity = card.get("rarity")
        self.last_set_release_date = (card.get("set") or {}).get("releaseDate")

        # M5 fix (2026-05-12): instrumentação supranumerários (só log).
        try:
            card_num_int = int("".join(c for c in str(card.get("number", "")) if c.isdigit()) or "0")
            printed_total = int((card.get("set") or {}).get("printedTotal") or 0)
        except (TypeError, ValueError):
            card_num_int, printed_total = 0, 0
        if printed_total and card_num_int > printed_total:
            log.debug(
                f"supranumerary match: {card.get('name')} #{card_num_int} > "
                f"set.printedTotal={printed_total} "
                f"(set={card.get('set', {}).get('id')}, rarity={card.get('rarity')}). "
                f"Possível SIR/SAR/HR — validar match contra rarity do listing CT."
            )

        tcg = card.get("tcgplayer", {}).get("prices", {})
        if not tcg:
            return None
        # v2.24: âncora `normal.market` pro guard reverse-outlier.
        self.last_normal_market = (tcg.get("normal") or {}).get("market")

        hd = ct_variants.holo_detection(rarity, card.get("rarity"),
                                        set_released=self.last_set_release_date,
                                        set_code=set_code)
        offer = ct_variants.offer_variant(first_edition, foil, hd.is_holo)
        m = ct_variants.match_reference_variant(tcg, *offer, era_missing=hd.era_missing)
        self._set_ref(m, tcg, offer, hd.era_missing, rarity)
        upd = (card.get("tcgplayer") or {}).get("updatedAt")
        self.last_ref_data_at = _iso_date(upd)
        if m.status != ct_variants.OK:
            log.debug(f"ref {m.status} {card_name} ({set_code}/{collector_number}) "
                      f"fe={first_edition} rev={foil}: {m.reason}")
            return None
        chosen = tcg[m.key]
        self.last_variant_used = m.key
        market = chosen.get("market") or 0.0
        low = chosen.get("low") or 0.0
        mid = chosen.get("mid") or 0.0
        try:
            card_to_cache = {**card, "_variant_used": m.key}   # não muta o dict da memória de busca
        except (TypeError, AttributeError):
            card_to_cache = card
        self.cache.set_price(cache_key, market, low, mid, card_to_cache)
        self.last_price_fetched_at = now_iso()
        return market


# ── v2.23: helpers tcgcsv (módulo-level, sem rede nos testes via mock) ──────

# subTypeName do tcgcsv → chave de variante: ct_variants.TCGCSV_SUBTYPE_TO_VARIANT
# (único dono do vocabulário; subtype desconhecido é ignorado, nunca inventado).


_TCGCSV_KEY_TOKENS = re.compile(r"[A-Z]+|\d+")


def tcgcsv_collector_key(raw: str) -> str:
    """v2.26: chave de join CT↔tcgcsv por numerador PRESERVANDO letras.

    O join antigo (digits-only, via clean_collector_number) colapsava a série
    H dos sets e-Card e os sufixos a/b: "H12"→"12" colidia com "012/147" e o
    last-wins do índice precificava uma carta com a referência de OUTRA
    (Aquapolis: 36 chaves colididas; ex. real do scan 2026-08-22: Exeggutor
    012/147 saiu com o preço do Hypno H12 — $229.99 de referência falsa).

    Normalização (aplicada IGUAL nos dois lados):
      - numerador = antes do "/"; strings sujas "SIR | 161" → após o "|";
      - uppercase; zeros à esquerda do numerador inteiro ("0H2"→"H2",
        "012"→"12") e de cada run numérico ("H08"→"H8", "TG01"→"TG1");
      - letras preservadas: "H12"≠"12", "95A"≠"95B".

    clean_collector_number (digits-only) é o contrato do pokemontcg.io e NÃO
    muda — esta chave é exclusiva do caminho tcgcsv."""
    if not raw:
        return ""
    head = str(raw).split("/")[0].strip()
    if "|" in head:
        head = head.split("|")[-1].strip()
    head = head.upper().lstrip("0") or "0"
    toks = _TCGCSV_KEY_TOKENS.findall(head)
    if not toks:
        return ""
    return "".join(
        (t.lstrip("0") or "0") if t.isdigit() else t for t in toks
    )


def tcgcsv_fetch_groups(session) -> Optional[list]:
    """v2.23: baixa a lista de groups (sets) do tcgcsv (categoria 3 = Pokémon).

    Retorna a lista `results` (cada item: {groupId, name, abbreviation, ...}) ou
    None se a request falhar. User-Agent é OBRIGATÓRIO (sem ele = 401)."""
    try:
        r = session.get(f"{TCGCSV_BASE}/groups",
                        headers={"User-Agent": TCGCSV_USER_AGENT}, timeout=20)
        if r.status_code != 200:
            log.debug(f"tcgcsv /groups status {r.status_code}")
            return None
        results = (r.json() or {}).get("results")
        return results if isinstance(results, list) else None
    except Exception as e:  # noqa: BLE001
        log.debug(f"tcgcsv /groups falhou: {e!r}")
        return None


def resolve_tcgcsv_group_id(
    ptcg_setcodes: list[str], set_name: str, groups: list
) -> Optional[int]:
    """v2.23: setcode(s) pokemontcg.io (+ nome do set CT) → tcgcsv groupId.

    UNIQUE-MATCH-ONLY — nunca chuta um group errado:
      1. Abreviação conhecida: pra cada setcode candidato (CT code → ptcg via
         SET_ALIAS_TO_PTCG), olha PTCG_SETCODE_TO_TCGCSV_ABBR e casa o campo
         `abbreviation` do group. Caminho primário, exato.
      2. Fallback por NOME: o `set_name` (nome EN do set no CT) como substring do
         `name` do group — SÓ se resolver pra EXATAMENTE 1 group. Se a substring
         casar >1 group → AMBÍGUO → None (set pulado). NUNCA pega o primeiro:
         injetar preço de um group errado como "real" é a classe de bug que o
         fallback de nome do MYP evita.
    Retorna None se nada casar UNICAMENTE → caller pula o fallback tcgcsv pro set
    (a pokemontcg.io segue como única fonte; sem preço inventado)."""
    if not groups:
        return None
    # 1) abreviação exata (determinística). v2.28: a abbr também precisa casar
    # UM group só — GEN/RR/BKP/CL/PR são compartilhadas no /groups e o loop
    # antigo devolvia o primeiro silenciosamente.
    for setcode in ptcg_setcodes:
        abbr = PTCG_SETCODE_TO_TCGCSV_ABBR.get(setcode)
        if not abbr:
            continue
        hits = [
            g.get("groupId") for g in groups
            if str(g.get("abbreviation") or "").upper() == abbr.upper()
        ]
        uniq_abbr = list(dict.fromkeys(h for h in hits if h is not None))
        if len(uniq_abbr) == 1:
            return uniq_abbr[0]
    # 2) fallback por nome — exige match ÚNICO
    name_l = (set_name or "").strip().lower()
    if not name_l:
        return None
    matches = [
        g.get("groupId") for g in groups
        if name_l in str(g.get("name") or "").lower()
    ]
    uniq = list(dict.fromkeys(m for m in matches if m is not None))
    return uniq[0] if len(uniq) == 1 else None


def resolve_tcgcsv_group_ids(
    ct_set_code: str, ptcg_setcodes: list[str], set_name: str, groups: list
) -> list[int]:
    """v2.28: código CT → lista de groupIds tcgcsv a pré-carregar.

    Ordem (nenhuma chuta):
      1. CT_SET_TO_TCGCSV_GROUP_IDS (ids explícitos verificados). Tudo-ou-nada:
         se algum id do set não está no /groups atual, o mapa explícito é
         ignorado (um set multi-group carregado pela metade perderia o guard de
         colisão de número) e a resolução segue pros passos abaixo.
      2. TCGCSV_EXCLUDED_CT_SETS → [] (sem referência de propósito).
      3. Resolvedor legado single-group (abbr única → nome único).
    Retorna [] se nada resolver → set sai sem referência, nunca inventada."""
    if not groups:
        return []
    code = (ct_set_code or "").lower()
    explicit = CT_SET_TO_TCGCSV_GROUP_IDS.get(code)
    if explicit:
        present = {g.get("groupId") for g in groups}
        missing = [gid for gid in explicit if gid not in present]
        if not missing:
            return list(explicit)
        log.warning(
            f"  tcgcsv: groupId(s) {missing} de {code} ausentes do /groups — "
            f"mapa explícito ignorado, tentando abbr/nome único"
        )
    if code in TCGCSV_EXCLUDED_CT_SETS or code in CT_JP_SETCODE_COLLISIONS:
        return []
    gid = resolve_tcgcsv_group_id(ptcg_setcodes, set_name, groups)
    return [gid] if gid else []


class TcgCsvFallbackProvider(PricingProvider):
    """v2.23: fonte de FALLBACK de preço via tcgcsv.com.
    v2.26: TAMBÉM selecionável como fonte PRIMÁRIA (`--provider tcgcsv`).

    Como fallback (default, provider primário = pokemontcg): só é consultada
    pra um SET quando a pokemontcg.io devolveu ZERO match de preço pro set
    inteiro (caso asc/Ascended Heroes). NUNCA roda pros sets que a
    pokemontcg.io já precifica (default path byte-for-byte inalterado).

    Como primária (`--provider tcgcsv`, opt-in por run): scan_expansion faz o
    prefill bulk no início de cada set e TODO o pricing sai daqui — útil
    quando a pokemontcg.io degrada com 500/502 intermitentes (incidente
    2026-08-22). Set sem groupId único/dados no tcgcsv aborta SEM entrar na
    skip-list (gap da fonte, não do set) e sai sem referência de preço.

    Carrega o set inteiro de uma vez (`/{groupId}/products` + `/{groupId}/prices`)
    e indexa por numerador do collector number → {variante TCGplayer: {market}}.
    O preço por-card reusa `select_tcgplayer_variant_price` — a MESMA escada de
    variante da pokemontcg.io — então a FIDELIDADE DE VARIANTE é idêntica:
    holo rare → holofoil, reverse → reverseHolofoil. Se a variante REQUERIDA não
    existir no tcgcsv → retorna None (pula o card), nunca substitui outro subtype
    (o atalho "menor subtype" do MYP, que reintroduziria o bug Gengar, é proibido
    aqui por construção: a seleção é por variante, não por preço).

    Os campos de proveniência (`last_variant_used`, `last_tcg_url`,
    `last_ptcg_rarity`, `last_set_release_date`) seguem o contrato do provider
    pokemontcg.io pra que os sinais downstream (low_confidence_variant, Chase
    Tier, valorização) continuem funcionando. `last_price_source` = "tcgcsv"
    rotula a origem distintamente (honestidade real-vs-fonte)."""
    name = "tcgcsv"
    GROUPS_ATTEMPTS = 3            # tentativas de /groups antes de desistir
    GROUPS_RETRY_WAIT_S = 2.0      # espera curta entre tentativas
    GROUPS_NEGATIVE_TTL_S = 180.0  # falha de /groups só vale ~3 min dentro do run
    _groups_failed_at: Optional[float] = None

    def __init__(self, cache: Cache, session: Optional[Any] = None):
        self.cache = cache
        self.session = session or requests.Session()
        # /groups resolvido 1× por run (cacheado).
        self._groups: Optional[list] = None
        self._groups_fetched = False
        # setcode CT → {numerador(str): {variante: {"market", "low", "mid"}}}
        # ou {} se o set não resolve groupId / sem dados. Pré-carregado 1× por set.
        self._set_index: dict[str, dict] = {}
        # v2.25: setcode CT → {numerador: {variante: productId}} — paralelo ao
        # _set_index. SÓ pra montar o link TCGplayer real (tcgplayer.com/product/
        # {id}) da variante priceada: tapa o furo do contrato de 2 links nos sets
        # de fallback E dá a chave de join pro DoubleHolo. NÃO afeta preço/margem.
        self._pid_index: dict[str, dict] = {}
        # Lote 3: setcode CT → data/hora (ISO) do prefill deste run.
        self._fetched_at: dict[str, str] = {}
        self.last_prefill_status: Optional[str] = None
        self.last_price_fetched_at: Optional[str] = None
        # último source rotulado (sempre "tcgcsv" quando este provider responde).
        self.last_price_source: Optional[str] = None

    def _get_json(self, path: str):
        """GET tcgcsv → (json|None, failed). `failed` = FALHA OPERACIONAL (exceção,
        timeout, 5xx, 429, JSON ilegível); HTTP 2xx/4xx = a fonte respondeu
        (4xx = não tem esse recurso → (None, False))."""
        try:
            r = self.session.get(f"{TCGCSV_BASE}/{path}",
                                 headers={"User-Agent": TCGCSV_USER_AGENT},
                                 timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json(), False
            log.debug(f"tcgcsv {path} status {r.status_code}")
            return None, (r.status_code == 429 or r.status_code >= 500)
        except Exception as e:  # noqa: BLE001
            log.debug(f"tcgcsv {path} falhou: {e!r}")
            return None, True

    def prefill_set(self, ct_set_code: str, ptcg_setcodes: list[str],
                    set_name: str) -> bool:
        """Pré-carrega o set inteiro do tcgcsv → índice por numerador→variantes.

        Retorna True se ≥1 card foi indexado. `last_prefill_status` explica o
        False: "no_group" (o tcgcsv RESPONDEU e não tem o set/dados = sem
        cobertura) ou "fetch_failed" (rede/5xx/timeout = falha operacional).
        Roda no máx. 1× por set; /groups com falha não é refeito a cada set
        (cache negativo só dentro do run)."""
        self.last_prefill_status = "ok" if self._set_index.get(ct_set_code) else "no_group"
        if ct_set_code in self._set_index:
            return bool(self._set_index[ct_set_code])
        # Lote 3c: cache negativo de /groups EXPIRA em poucos minutos (um blip no
        # 1º set não condena o run) e cada busca tenta algumas vezes com espera curta.
        if (self._groups_fetched and self._groups is None
                and self._groups_failed_at is not None
                and time.monotonic() - self._groups_failed_at > self.GROUPS_NEGATIVE_TTL_S):
            self._groups_fetched = False
        if not self._groups_fetched:
            self._groups = None
            for attempt in range(self.GROUPS_ATTEMPTS):
                self._groups = tcgcsv_fetch_groups(self.session)  # None = falhou
                if self._groups is not None:
                    break
                if attempt + 1 < self.GROUPS_ATTEMPTS:
                    time.sleep(self.GROUPS_RETRY_WAIT_S)
            self._groups_fetched = True
            self._groups_failed_at = time.monotonic() if self._groups is None else None
        if self._groups is None:
            self.last_prefill_status = "fetch_failed"
            return False
        if not self._groups:  # 200 com lista vazia: a fonte respondeu sem dados
            self._set_index[ct_set_code] = {}
            self.last_prefill_status = "no_group"
            return False
        group_ids = resolve_tcgcsv_group_ids(
            ct_set_code, ptcg_setcodes, set_name, self._groups
        )
        if not group_ids:
            log.warning(
                f"tcgcsv: sem groupId ÚNICO p/ {ct_set_code} "
                f"(ptcg={ptcg_setcodes}, name={set_name!r}) — fallback pulado"
            )
            self._set_index[ct_set_code] = {}
            self.last_prefill_status = "no_group"
            return False

        # v2.28: set pode abranger >1 group (gen = Generations + Radiant
        # Collection). Indexa cada group; se QUALQUER um falhar, aborta o set
        # (índice parcial perderia o guard de colisão abaixo).
        per_group: list[tuple[dict, dict, dict]] = []
        group_meta: list[tuple] = []   # (nome do group, publishedOn) — Shadowless / idade do set
        for group_id in group_ids:
            products, f1 = self._get_json(f"{group_id}/products")
            prices, f2 = self._get_json(f"{group_id}/prices")
            if f1 or f2:
                # falha de rede/5xx: NÃO cacheia o set como vazio (um retry
                # no mesmo run ainda pode funcionar) e sinaliza falha operacional.
                self.last_prefill_status = "fetch_failed"
                return False
            if not isinstance(products, dict) or not isinstance(prices, dict):
                # 404 / corpo vazio: a fonte respondeu e não tem dados do set
                self._set_index[ct_set_code] = {}
                self.last_prefill_status = "no_group"
                return False
            per_group.append(self._index_group(products, prices))
            g = next((x for x in (self._groups or []) if x.get("groupId") == group_id), {})
            group_meta.append((g.get("name") or "", g.get("publishedOn")))

        from collections import Counter
        key_count = Counter(k for idx, _, _r in per_group for k in idx)
        collisions = {k for k, n in key_count.items() if n > 1}
        if collisions:
            log.warning(
                f"  tcgcsv {ct_set_code}: {len(collisions)} número(s) presentes "
                f"em >1 group {group_ids} — descartados (ambíguos, sem preço)"
            )
        index: dict[str, dict] = {}
        pid_map: dict[str, dict] = {}
        gname_map: dict[str, str] = {}
        rar_all: dict[str, str] = {}
        for (idx, pids, rars), (gname, _pub) in zip(per_group, group_meta):
            for key, variants in idx.items():
                if key in collisions:
                    continue
                index[key] = variants
                pid_map[key] = pids[key]
                gname_map[key] = gname
                if key in rars:
                    rar_all[key] = rars[key]
        self.__dict__.setdefault("_rarity_map", {})[ct_set_code] = rar_all
        self.__dict__.setdefault("_group_name", {})[ct_set_code] = gname_map
        dates = sorted(d for d in (ct_variants._iso(p) for _g, p in group_meta) if d)
        self.__dict__.setdefault("_set_released", {})[ct_set_code] = dates[0] if dates else None
        self._set_index[ct_set_code] = index
        self._pid_index[ct_set_code] = pid_map
        self.__dict__.setdefault("_fetched_at", {})[ct_set_code] = now_iso()
        self.last_prefill_status = "ok" if index else "no_group"
        if index:
            # v2.26: a mesma classe atende fallback (v2.23) e primário
            # (--provider tcgcsv) — mensagem neutra quanto ao papel.
            log.info(
                f"  💾 tcgcsv {ct_set_code} (group "
                f"{'+'.join(str(g) for g in group_ids)}): {len(index)} "
                f"cards indexados"
            )
        return bool(index)

    def _dump_at(self) -> Optional[str]:
        """Data do DUMP diário do tcgcsv (`/last-updated.txt`) — a data do DADO. Uma busca por run;
        falha/ausência = None (a linha cai no rótulo "buscado em", nunca inventa data)."""
        d = self.__dict__
        if "_dump_at_val" not in d:
            val = None
            try:
                r = self.session.get(TCGCSV_BASE.rsplit("/tcgplayer", 1)[0] + "/last-updated.txt",
                                     headers={"User-Agent": TCGCSV_USER_AGENT}, timeout=TIMEOUT)
                if r.status_code == 200:
                    txt = r.text if isinstance(getattr(r, "text", None), str) else ""
                    mm = re.match(r"^\s*(\d{4}-\d{2}-\d{2}T[\d:]+)([+-]\d{2}):?(\d{2})?", txt)
                    if mm:
                        val = f"{mm.group(1)}{mm.group(2)}:{mm.group(3) or '00'}"
            except Exception as e:  # noqa: BLE001
                log.debug(f"tcgcsv last-updated indisponível: {e!r}")
            d["_dump_at_val"] = val
        return d["_dump_at_val"]

    @staticmethod
    def _index_group(products: dict, prices: dict) -> tuple[dict, dict, dict]:
        """Índice de UM group tcgcsv: (numerador→variantes, numerador→variante→pid,
        numerador→raridade do PRODUTO no tcgcsv — B1e: 2ª fonte de rótulo p/ detectar holo)."""
        # productId → numerador do collector number (extendedData "Number")
        num_by_pid: dict[int, str] = {}
        rar_by_pid: dict[int, str] = {}
        for p in products.get("results") or []:
            pid = p.get("productId")
            if pid is None:
                continue
            for ed in p.get("extendedData") or []:
                if ed.get("name") == "Number" and ed.get("value"):
                    num_by_pid[pid] = str(ed["value"])
                elif ed.get("name") == "Rarity" and ed.get("value"):
                    rar_by_pid[pid] = str(ed["value"])

        # productId → {variante TCGplayer: {"market","low","mid"}}
        from collections import defaultdict
        variants_by_pid: dict[int, dict] = defaultdict(dict)
        for r in prices.get("results") or []:
            pid = r.get("productId")
            if pid is None:
                continue
            sub = r.get("subTypeName")
            variant = ct_variants.tcgcsv_variant(sub)
            if variant == ct_variants.DESCONHECIDO:
                continue  # subtype desconhecido → ignora (não inventa variante)
            variants_by_pid[pid][variant] = {
                "market": r.get("marketPrice"),
                "low": r.get("lowPrice"),
                "mid": r.get("midPrice"),
            }

        index: dict[str, dict] = {}
        pid_map: dict[str, dict] = {}
        rar_map: dict[str, str] = {}
        for pid, num_raw in num_by_pid.items():
            # v2.26: chave por VARIANTE de numeração (letras preservadas) —
            # o digits-only antigo colidia série H / sufixos a/b do e-Card e
            # precificava uma carta com a referência de outra (ver
            # tcgcsv_collector_key). Guard de dígito mantém o skip de promo
            # não-numérico do comportamento anterior.
            key = tcgcsv_collector_key(str(num_raw))
            if not key or not any(c.isdigit() for c in key):
                continue
            variants = variants_by_pid.get(pid)
            if variants:
                index[key] = variants
                # MESMA escolha last-wins do _set_index → o productId guardado é o
                # do MESMO card cujo preço será usado. Só identidade p/ link.
                pid_map[key] = {v: pid for v in variants}
                if pid in rar_by_pid:
                    rar_map[key] = rar_by_pid[pid]
        return index, pid_map, rar_map

    def market_price_usd(self, card_name: str, set_code: str,
                         collector_number: str,
                         foil: bool = False,
                         rarity: Optional[str] = None,
                         first_edition: bool = False) -> Optional[float]:
        """Preço market USD do tcgcsv p/ a variante EXATA da oferta (B1).

        Chave via ct_variants.match_reference_variant com o NOME DO GROUP (grupo Shadowless
        nunca é referência) e a data de lançamento do set (publishedOn do group) p/ a
        detecção de holo. None se o set não foi prefillado ou a carta não está no índice
        (miss); carta encontrada sem variante compatível → None com last_ref_status."""
        self.last_tcg_url = None
        self.last_variant_used = None
        self.last_ptcg_rarity = None
        self.last_set_release_date = None
        self.last_price_source = None
        self.last_normal_market = None
        self.last_price_fetched_at = None
        self._reset_ref()

        index = self._set_index.get(set_code)
        if not index:
            return None
        key = tcgcsv_collector_key(collector_number)
        if not key:
            return None
        variants = index.get(key)
        if not variants:
            return None
        foil = bool(foil)
        self.last_normal_market = (variants.get("normal") or {}).get("market")
        rel = (self.__dict__.get("_set_released") or {}).get(set_code)
        self.last_set_release_date = rel
        prod_rarity = (self.__dict__.get("_rarity_map") or {}).get(set_code, {}).get(key)
        hd = ct_variants.holo_detection(rarity, prod_rarity, set_released=rel, set_code=set_code)
        offer = ct_variants.offer_variant(first_edition, foil, hd.is_holo)
        gname = (self.__dict__.get("_group_name") or {}).get(set_code, {}).get(key)
        m = ct_variants.match_reference_variant(variants, *offer, group_name=gname,
                                                era_missing=hd.era_missing)
        self._set_ref(m, variants, offer, hd.era_missing, rarity)
        self.last_ref_data_at = self._dump_at()
        self.last_price_source = "tcgcsv"
        self.last_price_fetched_at = getattr(self, "_fetched_at", {}).get(set_code)
        pid_by_variant = self._pid_index.get(set_code, {}).get(key, {}) or {}
        any_pid = next(iter(pid_by_variant.values()), None)
        if m.status != ct_variants.OK:
            # carta encontrada: a página do produto fica p/ o operador conferir
            if any_pid is not None:
                self.last_tcg_url = f"https://www.tcgplayer.com/product/{any_pid}"
            return None
        self.last_variant_used = m.key
        pid = pid_by_variant.get(m.key)
        if pid is not None:
            self.last_tcg_url = f"https://www.tcgplayer.com/product/{pid}"
        market = (variants[m.key].get("market")) or 0.0
        return market if market > 0 else None


class JustTcgProvider(PricingProvider):
    """
    JustTCG — PAGO (~$19-49/mês). Atualiza várias vezes ao dia.
    Stub: habilita quando/se você assinar. Troca no CLI: --provider justtcg
    """
    name = "justtcg"

    def __init__(self, api_key: Optional[str], cache: Cache,
                 delay: float = REQUEST_DELAY_PRICING):
        if not api_key:
            raise ValueError("JUSTTCG_API_KEY não configurado")
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key
        self.cache = cache
        self.delay = delay

    def market_price_usd(self, card_name: str, set_code: str,
                         collector_number: str,
                         foil: bool = False,
                         rarity: Optional[str] = None,
                         first_edition: bool = False) -> Optional[float]:
        # TODO: implementar quando assinar JustTCG.
        # Endpoint: GET /cards?name=X&set=Y → prices.tcgplayer.marketPrice
        raise NotImplementedError("JustTCG provider: implementar ao assinar")


class TcgPlayerOfficialProvider(PricingProvider):
    """
    TCGPlayer API OFICIAL — FECHADA para novos devs em 2026.
    Stub: se você conseguir credenciais no futuro, só implementar aqui.
    """
    name = "tcgplayer"

    def market_price_usd(self, card_name: str, set_code: str,
                         collector_number: str,
                         foil: bool = False,
                         rarity: Optional[str] = None,
                         first_edition: bool = False) -> Optional[float]:
        raise NotImplementedError(
            "TCGPlayer API oficial está fechada para novos devs em 2026. "
            "Quando obter credenciais (OAuth2 com public/private key), "
            "implementar aqui: POST /token → GET /pricing/product/{id}"
        )


PROVIDERS = {
    "pokemontcg": PokemonTcgIoProvider,
    "justtcg": JustTcgProvider,
    "tcgplayer": TcgPlayerOfficialProvider,
    # v2.26: tcgcsv promovido a provider PRIMÁRIO selecionável (--provider
    # tcgcsv) — mesma classe do fallback v2.23, bulk por set, MESMA escada de
    # variante. Precedente da frota: MYP v5.15 usa tcgcsv como fonte do CI
    # (divergência 0–0,3% vs pokemontcg.io — é o MESMO preço TCGplayer).
    # O default segue "pokemontcg"; tcgcsv é opt-in por run (útil quando a
    # pokemontcg.io degrada com 500/502 intermitentes — incidente 2026-08-22).
    "tcgcsv": TcgCsvFallbackProvider,
}


# ══════════════════════════════════════════════════════════════════════
# SCANNER — orquestração do pipeline de arbitragem.
# Fluxo:
#   1. Buscar expansões Pokemon no CT
#   2. Filtrar só as que interessam (via config ou --sets)
#   3. Para cada expansão, puxar TODAS listings EN
#   4. Aplicar filtros (NM, não-graded, preço mín)
#   5. Para cada listing, buscar preço TCG via pricing provider
#   6. Calcular margem bruta e líquida (default frete=0 modelo consolidação Hub)
#   7. Dedup: mantém só melhor oferta por (carta + condição)
# ══════════════════════════════════════════════════════════════════════
# --- v2.4 skip-list helpers (module-level) ---
#
# v2.7 (bug-hunt Codex H1, 2026-05-17): mutações agora são thread+process-safe.
# Antes: load → mutate → write_text() (read-modify-write sem lock). Dois scanners
# paralelos podiam corromper estado (último writer vencia). Pior: load_skip_list
# silenciosamente devolvia {} em qualquer erro de leitura/parse, então quem
# escrevesse depois apagava todo histórico real. Agora:
#   1. portalocker.Lock acquire exclusive antes de qualquer mutação
#   2. read+parse acontece DENTRO do lock (evita TOCTOU)
#   3. write é atomic: escreve em tempfile + os.replace() pra evitar truncate
#      parcial caso processo morra no meio do write
#   4. load_skip_list (read-only) usa shared lock e PROPAGA erro de parse
#      (não engole) — quem chama decide se aborta ou reseta.
# Sentinela `_SKIP_LIST_LOCK_TIMEOUT` evita deadlock se outro processo crashar
# segurando o lock.

_SKIP_LIST_LOCK_TIMEOUT = 30  # seg — operação é trivial, 30s é generoso


# ── Run-guard contra instâncias concorrentes (v2.14 robustez) ──────────────
# Incidente documentado (memória ct_scan_long_run_detached): dois scanners no
# MESMO state-dir disputam o cache.db SQLite + skip-list. A contenção de lock
# derruba o pricing pra ~9s/listing → o per-set-timeout estoura por falsa lentidão
# → a skip-list é ENVENENADA com sets bons. O guard segura um lock EXCLUSIVE
# não-bloqueante num lockfile do state-dir DURANTE TODO o scan. Se outro
# processo já o segura, recusamos iniciar (a menos de --allow-concurrent).
def acquire_run_guard(state_dir: Path):
    """Tenta adquirir o run-guard exclusivo do state-dir. Retorna o handle
    portalocker.Lock JÁ ADQUIRIDO (caller deve mantê-lo vivo até o fim do scan
    e dar .release() no final), ou None se já houver outra instância.

    Não levanta — o caller decide abortar (default) ou seguir (--allow-concurrent).
    """
    guard_path = state_dir / "scanner_run.lock"
    lock = portalocker.Lock(
        str(guard_path),
        mode="a+",
        timeout=0,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    )
    try:
        lock.acquire()
    except portalocker.exceptions.LockException:
        return None
    # Grava PID + timestamp pra diagnóstico de quem segura o lock.
    try:
        fh = lock.fh
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()} since={datetime.now().astimezone().isoformat(timespec='seconds')}\n")
        fh.flush()
    except Exception:
        # Lock é o que importa; o conteúdo informativo é best-effort.
        pass
    return lock

# PR-F (2026-05-28): TTL pra entries TRANSIENTES da skip-list. Sets pulados por
# timeout (per_set_timeout_/ct_*_timeout_) ou mass-pricing-failure costumam ser
# stalls passageiros (rede ruim, 429 burst, cobertura pokemontcg.io temporária).
# Após 7 dias, devem ser re-tentados automaticamente. Já erros estruturais
# (unexpected_error_*) ficam PERMANENTES — provavelmente bug de schema/dados.
_SKIP_LIST_TTL_DAYS = 7
# Prefixos de reason considerados TRANSIENTES (elegíveis a TTL/expiração).
_SKIP_LIST_TRANSIENT_PREFIXES = (
    "per_set_timeout_",
    "mass_pricing_failure_",
    "ct_blueprints_timeout_",
    "ct_listings_timeout_",
    # Lote 1 (2026-11): no_coverage_ e network_error_ também são sintomas de
    # fonte/rede degradada (ex.: 500/502 da pokemontcg.io), não fato do set.
    "no_coverage_",
    "network_error_",
)


def _skip_reason_str(entry) -> str:
    """Normaliza uma entry de reason (str legada OU dict {reason, added_at})
    para a string de motivo. Retrocompat com skip-lists pré-PR-F."""
    if isinstance(entry, dict):
        return str(entry.get("reason", ""))
    return str(entry) if entry is not None else ""


def _skip_entry_is_expired(entry, now: Optional[datetime] = None) -> bool:
    """PR-F: True se a entry é TRANSIENTE (prefixo conhecido) E tem added_at
    mais velho que _SKIP_LIST_TTL_DAYS.

    Regras de retrocompat:
      - entry legada (str pura, sem added_at) → NUNCA expira (permanente).
      - dict sem added_at (ou added_at inválido) → NUNCA expira (conservador).
      - reason não-transiente (ex. unexpected_error_*) → NUNCA expira.
    """
    reason = _skip_reason_str(entry)
    if not reason.startswith(_SKIP_LIST_TRANSIENT_PREFIXES):
        return False
    if not isinstance(entry, dict):
        # Legada (str) → sem timestamp → trata como permanente (não dropa).
        return False
    added_at = entry.get("added_at")
    if not added_at:
        return False
    try:
        # Formato gravado: "%Y-%m-%dT%H:%M:%SZ" (UTC). Parse robusto via fromisoformat.
        ts = datetime.fromisoformat(str(added_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        # added_at corrompido → conservador: não dropar.
        return False
    now = now or datetime.now(timezone.utc)
    return (now - ts) > timedelta(days=_SKIP_LIST_TTL_DAYS)


def _skip_list_lock_path() -> Path:
    """Lock file separado (.lock sidecar) — portalocker em Windows não permite
    bloquear arquivo ainda inexistente; lock dedicado é mais robusto."""
    return SKIP_LIST_FILE.with_suffix(SKIP_LIST_FILE.suffix + ".lock")


def _empty_skip_payload() -> dict:
    return {"skipped": [], "reasons": {}, "updated_at": None}


def _read_skip_file_locked() -> dict:
    """Lê + parseia skip-list assumindo lock já adquirido pelo caller.
    Levanta exception em erro de parse (NÃO engole)."""
    if not SKIP_LIST_FILE.exists():
        return _empty_skip_payload()
    # utf-8-sig: tolera BOM UTF-8 (EF BB BF) que PS 5.1 `Set-Content -Encoding utf8`
    # e vários editores prepend ao reescrever a skip-list. `json.loads` puro rejeita
    # BOM com "Unexpected UTF-8 BOM" → crash pré-set-1 (já quebrou um daily 2026-05-29).
    # Comportamento idêntico ao utf-8 quando não há BOM.
    raw = SKIP_LIST_FILE.read_text(encoding="utf-8-sig")
    if not raw.strip():
        # Arquivo vazio (caso edge: write parcial / disk full). Tratado como vazio,
        # mas loga WARNING — operador deve saber.
        log.warning(f"Skip-list vazia ({SKIP_LIST_FILE}). Tratando como reset.")
        return _empty_skip_payload()
    return json.loads(raw)  # propaga JSONDecodeError


def _atomic_write_skip_file(payload: dict) -> None:
    """Escreve skip-list de forma atomica via tempfile + os.replace.
    Lock deve já estar adquirido pelo caller.

    Em Windows o `os.replace` pode levantar PermissionError[WinError 5] quando
    o destino esta sendo lido por outro processo (file sharing semantics,
    Google Drive watcher, antivirus). Retry curto com backoff cobre isso —
    pq estamos sob lock exclusive do `.lock` sidecar, o conflito eh transient
    (a janela termina assim que o reader concorrente fecha o handle)."""
    tmp_path = SKIP_LIST_FILE.with_suffix(SKIP_LIST_FILE.suffix + ".tmp")
    # Use PID + thread no nome do tmp pra evitar colisao entre workers paralelos
    # que estejam escapando do lock (defense-in-depth — não deveria acontecer)
    unique_tmp = tmp_path.with_suffix(f".tmp.{os.getpid()}")
    unique_tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Retry os.replace pra contornar PermissionError transient no Windows
    last_err: Optional[Exception] = None
    for attempt in range(10):
        try:
            os.replace(unique_tmp, SKIP_LIST_FILE)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.1 * (attempt + 1))  # backoff 0.1, 0.2, 0.3, ... 1.0s
    # Esgotou retries — tenta cleanup do tmp antes de propagar
    try:
        if unique_tmp.exists():
            unique_tmp.unlink()
    except Exception:
        pass
    raise last_err  # type: ignore[misc]


def load_skip_list() -> dict:
    """Lê scanner_skip_list.json (com shared lock pra coerência).
    Em erro de read/parse, levanta exception — caller decide.
    Retorna dict com 'skipped' (list[str]), 'reasons' (dict), 'updated_at'."""
    lock_path = _skip_list_lock_path()
    try:
        # SHARED lock — múltiplos readers OK, conflita com writer exclusive.
        # fail_when_locked=True habilita timeout polling (vs blocking infinito).
        with portalocker.Lock(
            lock_path,
            mode="a+",
            flags=portalocker.LOCK_SH | portalocker.LOCK_NB,
            timeout=_SKIP_LIST_LOCK_TIMEOUT,
            fail_when_locked=False,
            check_interval=0.1,
        ):
            return _read_skip_file_locked()
    except portalocker.exceptions.LockException as e:
        # Não consegue lock em 30s → outro processo travou. Log + propaga.
        log.error(f"Skip-list lock timeout ({lock_path}): {e}")
        raise
    except json.JSONDecodeError as e:
        log.error(f"Skip-list JSON inválido ({SKIP_LIST_FILE}): {e}")
        raise


def add_to_skip_list(exp_code: str, reason: str) -> None:
    """Adiciona um exp_code à skip-list com motivo + timestamp. Idempotente.
    Thread+process-safe (exclusive lock + atomic write)."""
    lock_path = _skip_list_lock_path()
    try:
        with portalocker.Lock(
            lock_path,
            mode="a+",
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,  # EXCLUSIVE não-bloqueante p/ polling
            timeout=_SKIP_LIST_LOCK_TIMEOUT,
            fail_when_locked=False,
            check_interval=0.1,
        ):
            # Read CURRENT state under lock (não confiar em estado pre-lock)
            try:
                data = _read_skip_file_locked()
            except json.JSONDecodeError as e:
                # Corruption detectada. Fail loud — operador investiga.
                # NÃO sobrescreve cegamente, isso apagaria histórico.
                log.error(
                    f"Skip-list corrupted ({SKIP_LIST_FILE}): {e}. "
                    f"Abortando add({exp_code}). Renomeie/delete o arquivo se ok."
                )
                raise
            skipped = set(data.get("skipped", []))
            skipped.add(exp_code)
            reasons = data.get("reasons") or {}
            # PR-F (2026-05-28): reason agora é {reason, added_at} (era str pura)
            # pra suportar TTL na leitura. Entries legadas (str) seguem aceitas
            # no read (tratadas como permanentes).
            reasons[exp_code] = {
                "reason": reason,
                "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            payload = {
                "skipped": sorted(skipped),
                "reasons": reasons,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            _atomic_write_skip_file(payload)
            log.warning(f"  Adicionado à skip-list: {exp_code} (motivo: {reason})")
    except portalocker.exceptions.LockException as e:
        log.error(f"Skip-list lock timeout em add({exp_code}): {e}")
        raise


def clear_skip_list() -> None:
    """Apaga skip-list (no proximo scan todos os sets sao retentados).
    Thread+process-safe."""
    lock_path = _skip_list_lock_path()
    try:
        with portalocker.Lock(
            lock_path,
            mode="a+",
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            timeout=_SKIP_LIST_LOCK_TIMEOUT,
            fail_when_locked=False,
            check_interval=0.1,
        ):
            if SKIP_LIST_FILE.exists():
                SKIP_LIST_FILE.unlink()
                log.info(f"Skip-list apagada: {SKIP_LIST_FILE.name}")
    except portalocker.exceptions.LockException as e:
        log.error(f"Skip-list lock timeout em clear(): {e}")
        raise


# ══════════════════════════════════════════════════════════════════════
# CHECKPOINT WRITER — JSONL append-only crash-safe (v2.6, 2026-05-17)
#
# Por quê?
#   Scanner v2.5 mantinha `opps: list[Opportunity]` em memória até
#   `wb.save()` no fim do `scan()`. Crash mid-run (incidente 2026-05-17
#   17:56→20:21, weekly local) perdia TUDO — 686 sets de dados.
#
# Modelo:
#   - Append-only JSONL ao lado do XLSX final (.checkpoint.jsonl sidecar)
#   - Flush imediato + fsync após cada SET — não bufferizar
#   - Linha de header com args/total_sets, set_complete por set, e
#     opportunity por deal encontrado (preserva ordem temporal real)
#   - Last line parcial é descartável em parse (JSONL semantics)
#
# Recovery via scripts/recover_from_checkpoint.py: parseia JSONL,
# reconstrói lista de Opportunity equivalente, reusa export_xlsx().
# ══════════════════════════════════════════════════════════════════════
class CheckpointWriter:
    """Append-only JSONL writer crash-safe pra estado parcial do scan.

    Uso:
        cw = CheckpointWriter(path, every_n=10)   # every_n=0 desabilita
        cw.write_header(args_dict, total_sets)
        for ...:
            for opp in scan_expansion(exp):
                cw.write_opportunity(opp)
            cw.write_set_complete(set_code, set_name, stats_dict, elapsed_s)
        cw.close()

    Atributo `every_n` é UM NO-OP semântico no v2.6 — todos os writes
    fazem flush+fsync imediato (toda granularidade é per-set, não por
    batch). Mantido pra compatibilidade futura caso adicionemos
    bufferização opcional.
    """

    def __init__(self, path: Path, every_n: int = 10,
                 heartbeat_path: Optional[Path] = None,
                 flush_every_listings: int = 50,
                 resume_validation: bool = False):
        self.path = path
        self.every_n = every_n
        self.enabled = every_n > 0
        # PR-F (2026-05-28): heartbeat + flush per-listing.
        # heartbeat é independente do checkpoint JSONL — útil pra detectar stall
        # mesmo com --checkpoint-every 0. flush_every_listings controla a
        # cadência das linhas set_progress no JSONL (telemetria, não deal).
        self.heartbeat_path = heartbeat_path
        self.flush_every_listings = flush_every_listings
        self._fh = None
        self._opps_written = 0
        self._sets_written = 0
        # Lote 3c: validações do run ANTERIOR, só quando o operador pediu
        # --resume-validation e aquele run não terminou a validação.
        self._prior_validations: dict = {}
        if self.enabled:
            # Garante diretório existente
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Lote 3c: um run novo NUNCA empilha no checkpoint de outro run. O
            # anterior é ARQUIVADO (renomeado, nunca apagado) e este começa limpo.
            if self.path.exists() and self.path.stat().st_size > 0:
                archived = self.path.with_name(
                    f"{self.path.name}.{datetime.now():%Y%m%d-%H%M%S}.prev")
                n = 1
                while archived.exists():
                    archived = self.path.with_name(
                        f"{self.path.name}.{datetime.now():%Y%m%d-%H%M%S}.{n}.prev")
                    n += 1
                os.replace(self.path, archived)
                log.info(f"Checkpoint anterior arquivado em {archived.name} (run novo = checkpoint novo)")
                if resume_validation:
                    self._prior_validations = self._read_validations(archived)
            self._fh = open(self.path, "a", encoding="utf-8")
            log.info(
                f"Checkpoint JSONL ativo: {self.path} (flush per-set, "
                f"every_n={every_n}, flush_every_listings={flush_every_listings})"
            )
        if self.heartbeat_path is not None:
            try:
                self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log.warning(f"Heartbeat dir mkdir falhou ({self.heartbeat_path}): {e}")

    def _write(self, obj: dict) -> None:
        """Append + flush + fsync. Síncrono. Falha silenciosa em log."""
        if not self.enabled or self._fh is None:
            return
        try:
            # default=str: torna Path (e outros não-serializáveis, ex. do args
            # dict no header) seguros. PR-F: --state-dir injeta um Path em args.
            self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())
        except Exception as e:
            # NUNCA mata o scan por falha de checkpoint. Loga + continua.
            log.warning(f"Checkpoint write falhou ({obj.get('_type', '?')}): {e}")

    def touch_heartbeat(self, note: str = "") -> None:
        """PR-F: reescreve heartbeat.txt (modo 'w') com timestamp + nota, com
        flush+fsync. Independente do checkpoint JSONL — funciona mesmo com
        --checkpoint-every 0. Falha silenciosa em log (igual _write): heartbeat
        NUNCA mata o scan."""
        if self.heartbeat_path is None:
            return
        try:
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            with open(self.heartbeat_path, "w", encoding="utf-8") as hb:
                hb.write(f"{ts}\t{note}\n")
                hb.flush()
                os.fsync(hb.fileno())
        except Exception as e:
            log.warning(f"Heartbeat write falhou ({note!r}): {e}")

    def write_progress(self, set_code: str, i: int, total: int) -> None:
        """PR-F: linha de telemetria set_progress (NÃO é deal). Sinaliza ao
        recovery/monitor que o pricing loop está vivo dentro de um set. O
        parser de recovery DEVE ignorar _type=set_progress (não vira
        Opportunity). Append + flush + fsync via _write."""
        if not self.enabled:
            return
        self._write({
            "_type": "set_progress",
            "stamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "set_code": set_code,
            "i": i,
            "total": total,
        })

    def write_header(self, args_dict: dict, total_sets: int,
                     usd_brl: float = 0.0, eur_brl: float = 0.0) -> None:
        if not self.enabled:
            return
        # v2.14 (correção de resultado — candidato 3): grava as taxas de câmbio
        # do scan no header. O recovery (scripts/recover_from_checkpoint.py) lê
        # daqui pra reconstruir a célula Stats `usd_brl_rate` do XLSX. Sem isso,
        # o XLSX recuperado tinha usd_brl_rate=0.0 → a tabela de ENTREGA do
        # postprocess (coluna "CT US$", convertida via FX) ficava vazia. A
        # CLASSIFICAÇÃO (COMPRA/REVISAR) NÃO depende do FX (usa colunas em BRL),
        # mas a entrega ao operador sim.
        self._write({
            "_type": "scan_header",
            "stamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "args": args_dict,
            "total_sets": total_sets,
            "usd_brl": round(usd_brl, 4) if usd_brl else 0.0,
            "eur_brl": round(eur_brl, 4) if eur_brl else 0.0,
        })

    def write_opportunity(self, opp: "Opportunity") -> None:
        if not self.enabled:
            return
        # asdict() converte Opportunity+Listing nested em dict serializável.
        # Adiciona _type + denormaliza campos críticos pro topo (set_code,
        # blueprint_id, name) — facilita parse no recovery script sem precisar
        # entrar no nested listing.
        d = asdict(opp)
        d["_type"] = "opportunity"
        d["set_code"] = opp.listing.set_code
        d["blueprint_id"] = opp.listing.blueprint_id
        d["name"] = opp.listing.card_name
        self._write(d)
        self._opps_written += 1

    def write_set_complete(self, set_code: str, set_name: str,
                            per_set_stats: dict, elapsed_s: float,
                            status: str = "complete",
                            reason: Optional[str] = None,
                            unpriced: int = 0,
                            note: Optional[str] = None,
                            noref: int = 0) -> None:
        if not self.enabled:
            return
        self._write({
            "_type": "set_complete",
            "set_code": set_code,
            "set_name": set_name,
            "blueprints": per_set_stats.get("blueprints", 0),
            "filtered": per_set_stats.get("filtered", 0),
            "priced": per_set_stats.get("priced", 0),
            "opps_found": per_set_stats.get("opps_found", 0),
            "elapsed_s": round(elapsed_s, 2),
            # Lote 3: desfecho do set — "complete" | "no_coverage" (a fonte
            # respondeu e não tem as cartas) | "operational_failure" (rede/5xx/
            # timeout/erro: tentar de novo). `unpriced` = listings do set sem
            # referência. Checkpoints antigos não têm estes campos → complete.
            "status": status,
            "reason": reason,
            "unpriced": unpriced,
            "noref": noref,
            "note": note,
        })
        self._sets_written += 1

    def _ensure_open(self) -> bool:
        """Reabre o arquivo (append) se já foi fechado — validação e sem-preço
        são gravados DEPOIS do scan_complete."""
        if not self.enabled:
            return False
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")
        return True

    def write_unpriced(self, row: dict) -> None:
        """Lote 3b: listing sem referência — vai pro checkpoint p/ o recovery."""
        if self._ensure_open():
            self._write({"_type": "unpriced", **row})

    def write_noref(self, row: dict) -> None:
        """B1: oferta sem referência compatível — vai pro checkpoint p/ o recovery."""
        if self._ensure_open():
            self._write({"_type": "noref", **row})

    def write_validation(self, o: "Opportunity") -> None:
        """Lote 3b/3c: resultado da validação per-blueprint, gravado AO VALIDAR.
        Leva a oferta (preço) e a referência contra as quais foi feita — uma
        retomada só reaproveita se ambas forem idênticas."""
        if not self._ensure_open():
            return
        self._write({
            "_type": "validation",
            "product_id": o.listing.product_id,
            "blueprint_id": o.listing.blueprint_id,
            "seller": o.listing.seller_username,
            "first_edition": o.listing.first_edition,
            "reverse": bool(o.listing.foil),
            "validated_at": o.validated_at or now_iso(),
            "reused": o.validation_reused,
            "offer_price_brl": o.ct_price_brl,
            "ref_brl": o.tcg_market_brl,
            "validation_status": o.validation_status,
            "validation_reason": o.validation_reason,
            "live_price_brl": o.live_price_brl,
            "markup_pct": o.markup_pct,
            "markup_tier": o.markup_tier,
            "real_margin_pct": o.real_margin_pct,
            "real_net_margin_pct": o.real_net_margin_pct,
            "real_lucro_brl": o.real_lucro_brl,
        })

    def write_validation_complete(self) -> None:
        """Marca que a validação deste run terminou — um run assim nunca é fonte
        de reaproveitamento."""
        if self._ensure_open():
            self._write({"_type": "validation_complete", "stamp": now_iso()})

    @staticmethod
    def _read_validations(path: Path) -> dict:
        """Validações de um checkpoint ARQUIVADO — vazio se aquele run concluiu
        a validação (só run que NÃO terminou é fonte de retomada)."""
        out: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    typ = rec.get("_type")
                    if typ == "validation_complete":
                        return {}
                    if typ == "validation":
                        out[validation_key_from_record(rec)] = rec
        except OSError:
            return {}
        return out

    def load_validations(self, max_age_hours: float) -> dict:
        """Validações reaproveitáveis neste run: SÓ as do run anterior
        interrompido e SÓ com --resume-validation (idade <= max_age_hours).
        Sem a flag, sempre vazio."""
        out: dict = {}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        for key, rec in self._prior_validations.items():
            try:
                ts = datetime.fromisoformat(rec["validated_at"])
                if ts.tzinfo is None:
                    ts = ts.astimezone()
            except (KeyError, ValueError, TypeError):
                continue
            if ts >= cutoff:
                out[key] = rec
        return out

    def write_scan_complete(self, total_opps: int, total_elapsed_s: float) -> None:
        if not self.enabled:
            return
        self._write({
            "_type": "scan_complete",
            "stamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "total_opps": total_opps,
            "total_elapsed_s": round(total_elapsed_s, 2),
            "sets_written": self._sets_written,
            "opps_written": self._opps_written,
        })

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None


class SourceBreaker:
    """B1e: disjuntor da fonte principal de preço, medido POR OFERTA dentro do run.

    Janela deslizante das últimas `window` ofertas (ok/falha de infraestrutura + latência).
    Abre quando, com ≥ `min_samples` na janela, a taxa de falha >= `fail_rate` OU a latência
    média > `slow_s`. Aberto: o resto do set e os sets seguintes vão direto ao tcgcsv (mesma
    regra exata de casamento); a cada `probe_every_s` uma sonda barata decide se volta."""

    MIN_SLOW_SAMPLES = 2

    def __init__(self, window: int = 10, min_samples: int = 6, fail_rate: float = 0.5,
                 slow_s: float = 15.0, probe_every_s: float = 120.0, clock=time.monotonic):
        self.window, self.min_samples = window, min_samples
        self.fail_rate, self.slow_s, self.probe_every_s = fail_rate, slow_s, probe_every_s
        self._clock = clock
        self._w: list = []
        self.is_open = False
        self.opened_at: Optional[datetime] = None
        self.open_fail, self.open_n = 0, 0
        self._last_probe: Optional[float] = None
        self.events: list[dict] = []          # aberturas/fechamentos do run (para o resumo)

    @property
    def fail_count(self) -> int:
        return self.open_fail if self.is_open else sum(1 for ok, _ in self._w if not ok)

    @property
    def sample_count(self) -> int:
        return self.open_n if self.is_open else len(self._w)

    def record(self, ok: bool, latency_s: float) -> bool:
        """Registra uma oferta; devolve True se ESTA chamada abriu o disjuntor."""
        if self.is_open:
            return False
        self._w.append((bool(ok), float(latency_s)))
        del self._w[:-self.window]
        n = len(self._w)
        fails = sum(1 for o, _ in self._w if not o)
        # lentidão (retries + Retry-After custam dezenas de s por oferta): bastam 2 amostras;
        # taxa de falha pede o mínimo da janela
        slow = n >= self.MIN_SLOW_SAMPLES and sum(lat for _, lat in self._w) / n > self.slow_s
        if slow or (n >= self.min_samples and fails / n >= self.fail_rate):
            self.is_open, self.opened_at = True, datetime.now()
            self.open_fail, self.open_n = fails, n
            self._last_probe = self._clock()
            self.events.append({"event": "open", "at": self.opened_at, "fails": fails, "n": n,
                                "why": "latência" if slow and fails / n < self.fail_rate else "falhas"})
            return True
        return False

    def probe_due(self) -> bool:
        return self.is_open and (self._last_probe is None
                                 or self._clock() - self._last_probe >= self.probe_every_s)

    def mark_probe(self) -> None:
        self._last_probe = self._clock()

    def close(self) -> None:
        self.is_open = False
        self._w.clear()
        self.events.append({"event": "close", "at": datetime.now()})


class Scanner:
    # v2.29: default de classe = inglês. Explícito (não `getattr` nos call-sites)
    # e ainda tolera stubs `Scanner.__new__` dos testes antigos.
    language: str = LANGUAGE_FILTER

    def __init__(self, ct: CardTraderClient, pricing: PricingProvider, cache: Cache,
                 threshold: float = MARGIN_THRESHOLD,
                 min_price_usd: float = MIN_PRICE_USD,
                 exclude_graded: bool = EXCLUDE_GRADED,
                 shipping_brl_override: float = 0.0,
                 hub_fee_rate: float = 0.06,
                 per_set_timeout_s: float = DEFAULT_PER_SET_TIMEOUT_MIN * 60,
                 ignore_skip_list: bool = False,
                 chase_only: bool = False,
                 max_consecutive_misses: int = 0,
                 keep_all_priced: bool = True,
                 tcgcsv: Optional["TcgCsvFallbackProvider"] = None,
                 tcgcsv_fallback: bool = True,
                 language: str = LANGUAGE_FILTER):
        self.ct = ct
        # v2.29: idioma das OFERTAS CT (`properties_hash.pokemon_language`).
        # Default "en" = comportamento histórico. Normalizado (apelidos →
        # canônico) e enviado à API; no cliente a comparação é lowercased porque
        # `Listing.language` chega .lower(). A REFERÊNCIA de preço continua
        # sendo a carta INGLESA no TCGplayer — com idioma ≠ en o número é razão
        # de preço EN/<idioma>, não margem de revenda (`--ratio-column`).
        self.language = normalize_language(language)
        self.pricing = pricing
        self.cache = cache
        # v2.23: fonte de FALLBACK tcgcsv. Só consultada quando a pokemontcg.io
        # devolve ZERO match de preço pro set inteiro (caso asc/Ascended Heroes,
        # invisível sem isso). `tcgcsv` é o provider (None = não instanciado);
        # `tcgcsv_fallback` é o opt-out (--no-tcgcsv-fallback → False).
        self.tcgcsv = tcgcsv
        self.tcgcsv_fallback = tcgcsv_fallback
        self.threshold = threshold
        self.min_price_usd = min_price_usd
        self.exclude_graded = exclude_graded
        # 2026-05-12: modelo operacional de consolidacao no Hub depot. Frete
        # default = 0 (cartas acumulam no deposito CT ~100 unidades e sao
        # enviadas em consolacao unica → frete dilui pra ~R$0.30/card).
        # Override via CLI --shipping-brl X pra simular envio direto.
        self.shipping_brl_override = shipping_brl_override
        # v2.12 (2026-06-06): hub fee aplicado sobre live_brl no recalc REAL.
        # DEFAULT 0.0 → margem reportada é BRUTA (custo = preço do site, sem
        # taxa). Operador calcula Hub fee/frete/cartão/IOF por fora. Override
        # via --hub-fee 0.06 pra reembutir os 6% históricos, se quiser.
        self.hub_fee_rate = hub_fee_rate
        # v2.4 (2026-05-15): per-set wall-clock timeout (segundos). Default 8min.
        # Quando excedido, scan_expansion aborta + adiciona o set à skip-list.
        self.per_set_timeout_s = per_set_timeout_s
        self.ignore_skip_list = ignore_skip_list
        # v2.13 (frente chase): --chase-only filtra pra raridades TOP/MID
        # (Special/Hyper/Secret/Illustration Rare, alt arts, ultra/rainbow/gold).
        self.chase_only = chase_only
        # v2.13 (frente eficiência): cap de "misses" consecutivos no pricing.
        # Quando N listings seguidos de um set não casam preço na pokemontcg.io
        # (buraco de cobertura — sets 2026 / mega evolução), aborta o set + skip
        # list em vez de moer centenas de listings no rate limit. 0 = desativado
        # (comportamento histórico preservado). Pendência v2.4 conhecida.
        self.max_consecutive_misses = max_consecutive_misses
        # v2.22 (2026-06-22): contrato de ENTREGA scanner→postprocess. Quando
        # True (default), o scanner persiste TODO listing precificado no XLSX,
        # não só os que batem o `threshold`. O threshold vira CLASSIFICAÇÃO
        # downstream (o postprocess separa COMPRA/REVISAR e, se nada bate,
        # mostra os near-miss — fallback do commit #26). Sem isso, um scan que
        # precificou N>0 mas 0 acima do threshold escrevia uma aba
        # "Oportunidades" só com cabeçalho → o postprocess lia df VAZIO →
        # entregava "_(nenhum listing precificado — nada a entregar)_", mesmo
        # com N precificados (run 27925869658: 223 precificados, 0 ≥ threshold,
        # entrega vazia). `--opportunities-only` restaura o filtro duro antigo.
        self.keep_all_priced = keep_all_priced
        # PR-F (2026-05-28): defaults seguros pra heartbeat/checkpoint quando
        # scan_expansion é chamado direto (tests/diagnose) sem passar por scan().
        # scan() reaponta esses dois quando há um CheckpointWriter ativo.
        self.heartbeat = lambda *_: None
        self._checkpoint: Optional["CheckpointWriter"] = None
        self.usd_brl = get_usd_to_brl(cache)
        self.eur_brl = get_eur_to_brl(cache)
        self.stats = {
            # v2.29: auditoria — em que idioma o scan rodou. Registrado AQUI
            # (não só em scan_expansion) pra constar na aba Stats mesmo quando
            # todo set é pulado/estoura antes de listar ofertas.
            "language_filter": self.language,
            "expansions_scanned": 0,
            "listings_fetched": 0,
            "listings_after_filters": 0,
            "tcg_price_found": 0,
            "opportunities_found": 0,
            "skipped_exotic_currency": 0,  # M4 fix: contador de listings em moedas exóticas (GBP/JPY/etc)
            "expansions_skipped_by_list": 0,  # v2.4: sets pulados via skip-list
            "expansions_timed_out": 0,        # v2.4: sets que estouraram per_set_timeout
            "pricing_failures": 0,            # v2.9 (Codex H5): erros desconhecidos no pricing
            "expansions_mass_pricing_abort": 0,  # v2.9: sets abortados por >50% pricing fails
            "skipped_non_chase": 0,           # v2.13: listings cortados por --chase-only
            "expansions_no_coverage_abort": 0,  # v2.13: sets abortados por N misses consecutivos
            "priced_below_threshold": 0,      # v2.22: precificados mas < threshold (near-miss, persistidos)
            "tcgcsv_fallback_sets": 0,        # v2.23: sets resgatados pelo fallback tcgcsv
            "tcgcsv_fallback_priced": 0,      # v2.23: cards precificados via tcgcsv
        }
        # v2.9 (Codex H5): threshold pra abortar set quando pricing está
        # massivamente quebrado (schema drift / SSL / endpoint down). 50% das
        # listings + minimum sample size de 20 evita falsos abort em sets
        # com 1-2 cards.
        self.mass_pricing_failure_threshold = 0.50
        self.mass_pricing_failure_min_sample = 20

    def _parse_listing(self, raw: dict, bp_index: dict) -> Optional[Listing]:
        """Converte o dict da API para dataclass Listing.
        `bp_index`: {blueprint_id: blueprint_dict} pré-carregado.
        """
        bp = bp_index.get(raw.get("blueprint_id"))
        if not bp:
            return None

        # Preço: CT retorna centavos + currency. Em 2026-04-29 descobrimos
        # que contas com país=Brasil recebem listings já convertidos pra BRL
        # pela API CT (independente do país do seller). Antes tudo vinha em EUR.
        # Estratégia: BRL é a moeda interna do scanner, com fallback EUR/USD
        # via Frankfurter pra sellers que ainda enviam moeda original.
        price = raw.get("price", {})
        cents = price.get("cents", 0)
        currency = (price.get("currency") or "BRL").upper()
        if currency == "BRL":
            price_brl_val = cents / 100.0
        elif currency == "EUR":
            price_brl_val = (cents / 100.0) * self.eur_brl
        elif currency == "USD":
            price_brl_val = (cents / 100.0) * self.usd_brl
        else:
            # GBP, JPY etc — raro, ignorado até termos demanda.
            # M4 fix (2026-05-11): log + stat counter pra não perder cobertura
            # silenciosa caso CT habilite GBP/JPY nativo no futuro.
            log.debug(
                f"moeda exótica ignorada: {currency} no listing "
                f"{raw.get('id')} (bp={raw.get('blueprint_id')})"
            )
            self.stats["skipped_exotic_currency"] += 1
            return None

        props = raw.get("properties_hash") or raw.get("properties") or {}
        user = raw.get("user", {})

        # Set code/name: blueprint só traz `expansion_id` numérico (sem dict
        # nested), então a fonte confiável é o próprio listing, que vem com
        # `expansion: {code, name_en, id}`. Descoberto em 2026-04-20 após
        # Mawile falso-positivo com set_code vazio.
        listing_exp = raw.get("expansion") or {}
        resolved_set_code = listing_exp.get("code") or ""
        resolved_set_name = listing_exp.get("name_en") or listing_exp.get("name") or ""

        return Listing(
            product_id=raw["id"],
            blueprint_id=raw["blueprint_id"],
            card_name=bp.get("name", ""),
            set_code=resolved_set_code,
            set_name=resolved_set_name,
            # Fonte preferida: properties_hash do listing, que traz "007" limpo.
            # Blueprint costuma ter collector_number vazio e cair em `version`
            # formatado como "Rarity | N/total" → aplicamos clean só nesse
            # fallback pra extrair o dígito via regex sem mexer nos paths
            # limpos (2026-05-11 fix).
            collector_number=(
                props.get("collector_number")
                or bp.get("collector_number")
                or clean_collector_number(bp.get("version", ""))
                or ""
            ),
            condition=props.get("condition", "Unknown"),
            # Pokemon usa sempre properties_hash.pokemon_language; mtg_language
            # é sempre None pra cartas Pokemon. Sem valor → string vazia (não "en")
            # para não deixar passar carta sem metadados de idioma.
            language=(props.get("pokemon_language") or "").lower(),
            price_cents=cents,
            price_currency=currency,
            price_brl=price_brl_val,
            quantity=raw.get("quantity", 0),
            # v2.18: Pokémon usa `pokemon_reverse` (não `foil`/`mtg_foil`, que
            # só existem em MTG). Antes esse campo era ignorado → TODA carta
            # Pokémon chegava foil=False, e holo rares padrão escorregavam pra
            # reverseHolofoil (inflado). Agora reverse-holo → foil=True.
            foil=(to_bool(props.get("mtg_foil", False)) or to_bool(props.get("foil", False))
                  or to_bool(props.get("pokemon_reverse", False))),
            graded=raw.get("graded", False),
            seller_username=user.get("username", ""),
            seller_can_sell_via_hub=user.get("can_sell_via_hub", False),
            seller_user_type=user.get("user_type", "private"),
            first_edition=to_bool(props.get("first_edition", False)),
            first_edition_known="first_edition" in props,
            cardtrader_url=f"https://www.cardtrader.com/cards/{raw['blueprint_id']}",
            # 2026-05-16: Schema CT blueprint tem rarity em fixed_properties.pokemon_rarity,
            # NÃO no campo `rarity` raiz (verificado via inspect do bp[0] de sfa).
            # Patterns esperados: "Common"/"Uncommon"/"Rare"/"Ultra Rare"/"Secret Rare"/etc.
            # Vazio = sealed product (booster, ETB) — não-card, será filtrado downstream.
            rarity=(
                (bp.get("fixed_properties") or {}).get("pokemon_rarity")
                or bp.get("rarity")
                or props.get("pokemon_rarity")
                or props.get("rarity")
                or ""
            ).strip(),
        )

    def _passes_filters(self, l: Listing) -> bool:
        if l.condition != CONDITION_FILTER:
            return False
        # v2.29: idioma configurável (--language); `Listing.language` vem .lower().
        if self.language and l.language != self.language.lower():
            return False
        if self.exclude_graded and l.graded:
            return False
        # v2.1 — anti-Trainer Gallery: skipa cartas TG## (subset SWSH com
        # pricing corrompido no pokemontcg.io). Ver _TRAINER_GALLERY_RE.
        if l.collector_number and _TRAINER_GALLERY_RE.match(l.collector_number):
            return False
        # Filtro min_price_usd: converte BRL→USD via FX pra manter o threshold
        # em USD (referência TCGPlayer), sem importar a moeda do listing.
        price_usd_equiv = l.price_brl / self.usd_brl
        if price_usd_equiv < self.min_price_usd:
            return False
        return True

    def _costs(self) -> Costs:
        """Custos informativos (ct_economics). `--hub-fee` = taxa do Hub só p/ as colunas
        LÍQUIDAS de preço CRU (o checkout validado já embute o Hub: compra_inclui_hub=True,
        nunca contado duas vezes); `--shipping-brl` > 0 substitui o frete de compra fixo.
        A MARGEM do corte (margem_venda) não depende de nenhum dos dois."""
        kw = {}
        hub = getattr(self, "hub_fee_rate", None)
        if isinstance(hub, (int, float)):
            kw["hub_fee_rate"] = float(hub)
        frete = getattr(self, "shipping_brl_override", 0.0)
        if isinstance(frete, (int, float)) and frete > 0:
            kw["frete_compra_brl"] = float(frete)
        return Costs(**kw)

    @staticmethod
    def _pa(provider, name, typ, default):
        """Atributo `last_*` do provider com tipo garantido (stubs/mocks nunca vazam)."""
        v = getattr(provider, name, default)
        return v if isinstance(v, typ) else default

    @classmethod
    def _ref_is_noref(cls, provider) -> bool:
        """Carta ENCONTRADA na fonte mas sem chave compatível / sem preço utilizável."""
        return cls._pa(provider, "last_ref_status", str, "") in (
            ct_variants.INCOMPATIVEL, ct_variants.SEM_PRECO)

    def _record_noref(self, exp_code: str, l: "Listing", provider, status: Optional[str] = None,
                      reason: Optional[str] = None) -> None:
        """Oferta sem referência COMPATÍVEL: sem margem, sem recomendação; vai p/ a aba
        "Sem Ref Compatível" (e p/ o checkpoint). NÃO é miss de cobertura. Conta na soma."""
        self._commit_noref(l, self._noref_row(exp_code, l, provider, status, reason))

    def _noref_row(self, exp_code: str, l: "Listing", provider, status: Optional[str] = None,
                   reason: Optional[str] = None) -> dict:
        pa = self._pa
        offer = pa(provider, "last_offer_variant", tuple, None) or ct_variants.offer_variant(
            l.first_edition, bool(l.foil), ct_variants.rarity_is_holo(l.rarity, set_code=l.set_code))
        row = {
            "set": exp_code, "set_name": l.set_name, "card": l.card_name,
            "number": l.collector_number, "rarity": l.rarity,
            "edicao": ct_variants.edition_label(offer[0], pa(provider, "last_divided", bool, False)),
            "acabamento": ct_variants.FIN_LABELS.get(offer[1], offer[1]),
            "ct_price_brl": round(l.price_brl, 2), "currency": l.price_currency,
            "qty": l.quantity, "seller": l.seller_username, "link": l.cardtrader_url,
            "tcg_url": pa(provider, "last_tcg_url", str, "") or "",
            "source": pa(provider, "last_price_source", str, "") or pa(provider, "name", str, ""),
            "motivo": reason if reason is not None else pa(provider, "last_ref_reason", str, ""),
            "chaves": ",".join(pa(provider, "last_available_keys", list, [])),
            "status": status or pa(provider, "last_ref_status", str, ""),
        }
        return row

    def _commit_noref(self, l: "Listing", row: dict) -> None:
        self.__dict__.setdefault("noref_rows", []).append(row)
        self.__dict__.setdefault("_set_accounted", set()).add(l.uid)
        self.__dict__.setdefault("_noref_uids", set()).add(l.uid)
        self.stats["listings_sem_ref_compativel"] = self.stats.get("listings_sem_ref_compativel", 0) + 1
        cp = getattr(self, "_checkpoint", None)
        if cp is not None:
            cp.write_noref(row)

    def _estimate_shipping_brl(self, listing: Listing, units: int = 1) -> float:
        """Frete em BRL por listing. Default 0 (modelo de consolidacao no Hub depot).

        Modelo operacional 2026-05-12 (confirmado por Matheus):
        - Compras CT vao pro deposito Hub na Europa
        - Acumulam ~100 cartas
        - Enviadas em consolidacao unica pro Brasil
        - Frete daquele envio (~R$30-50) dilui entre as 100 cartas
        - Resultado per-card: R$0.30-0.50 → desprezivel

        Logo o scanner zera frete por default. Hub fee 6% e o unico custo
        adicional alem do preco CT, e ja vem embutido em `live_price_brl`
        via per-blueprint validation (markup_tier "Hub +6%").

        Override (`--shipping-brl X`): pra simular cenarios sem
        consolidacao (compra urgente, sellers non-Hub que enviam direto).
        Valor passa direto, dividido por `units` se compra multipla do
        mesmo listing.

        Implementacao antiga (estimativa EUR-based por tier) preservada
        como `_legacy_shipping_eur_estimate_unused` para referencia futura.
        """
        return self.shipping_brl_override / max(units, 1)

    def _legacy_shipping_eur_estimate_unused(self, listing: Listing) -> float:
        """[INATIVO desde 2026-05-12] Estimativa de frete baseada em EUR + FX.

        Calculo pre-consolidacao: tier de seller (Hub/Pro/Private) → base em
        EUR (5/10/12) → multiplicado por FX EUR→BRL → frete per-listing
        ~R$28-69.

        Substituido por shipping=0 default quando o modelo operacional de
        consolidacao foi confirmado. Mantido como referencia: se o fluxo de
        consolidacao mudar (ex: virar envio direto), reativar essa logica.
        """
        if listing.seller_user_type == "zero_fee" or listing.seller_can_sell_via_hub:
            base_eur = SHIPPING_EUR_HUB
        elif listing.seller_user_type == "professional":
            base_eur = SHIPPING_EUR_PROFESSIONAL
        else:
            base_eur = SHIPPING_EUR_PRIVATE
        return base_eur * self.eur_brl

    def _check_set_timeout(self, set_start: float, exp_code: str, exp_name: str,
                            stage: str, timeout_s: Optional[float] = None) -> bool:
        """Retorna True se set deve abortar. Timeout é FALHA OPERACIONAL: nunca
        entra na skip-list (Lote 3) — o set aparece como "não concluído, tentar
        de novo".
        v2.8 (Codex H2): chamado antes de cada call externa do set.
        v2.14: aceita timeout_s explícito (o EFETIVO do set, c/ override). Quando
        None, cai no self.per_set_timeout_s (retrocompat p/ chamadas diretas)."""
        effective = self.per_set_timeout_s if timeout_s is None else timeout_s
        if not effective:
            return False
        elapsed = time.monotonic() - set_start
        if elapsed > effective:
            log.error(
                f"  ⏱️  TIMEOUT set {exp_code} ({exp_name}) at stage='{stage}': "
                f"{elapsed/60:.1f}min > {effective/60:.1f}min limite. "
                f"Abortando (falha operacional — NÃO vai pra skip-list)."
            )
            self.stats["expansions_timed_out"] += 1
            self._set_outcome("operational_failure",
                              f"per_set_timeout_{int(effective)}s_at_{stage}")
            return True
        return False

    # ── Lote 3: desfecho por set ───────────────────────────────────────────
    def _set_outcome(self, status: str, reason: Optional[str] = None,
                     note: Optional[str] = None) -> None:
        """status ∈ complete | no_coverage | operational_failure."""
        self._set_status = status
        self._set_reason = reason
        if note is not None:
            self._set_note = note

    def _record_unpriced(self, exp_code: str, listings: list["Listing"],
                         causes: dict, detail: Optional[str],
                         per_uid_detail: Optional[dict] = None) -> None:
        """Guarda cada listing sem referência (nada some em silêncio)."""
        if not hasattr(self, "unpriced_rows"):
            self.unpriced_rows = []
        accounted = self.__dict__.setdefault("_set_accounted", set())
        for l in listings:
            accounted.add(l.uid)
            cause = causes.get(l.uid, "not_reached")
            reason = {"miss": "sem_referencia_na_fonte", "failure": "falha_operacional",
                      "not_reached": "nao_alcancado"}.get(cause, cause)
            ed, fin = ct_variants.offer_variant(
                l.first_edition, bool(l.foil), ct_variants.rarity_is_holo(l.rarity, set_code=l.set_code))
            row = {
                "set": exp_code, "set_name": l.set_name, "card": l.card_name,
                "number": l.collector_number, "ct_price_brl": round(l.price_brl, 2),
                "seller": l.seller_username, "link": l.cardtrader_url,
                "qty": l.quantity, "edicao": ct_variants.edition_label(ed, False),
                "acabamento": ct_variants.FIN_LABELS.get(fin, fin),
                "reason": reason,
                "detail": (per_uid_detail or {}).get(l.uid) or detail or "",
            }
            self.unpriced_rows.append(row)
            cp = getattr(self, "_checkpoint", None)
            if cp is not None:
                cp.write_unpriced(row)

    def _finalize_noref_pair(self, l: "Listing", second_reason: str,
                             second_keys: str = "", second_url: str = "") -> None:
        """Ref incompatível na 1ª fonte e o tcgcsv também não resolveu: UMA linha em "Sem Ref
        Compatível" (substitui a provisória), com os motivos das DUAS fontes."""
        first = self.__dict__.setdefault("_noref_first", {}).pop(l.uid, None)
        if first is None:
            return
        row = dict(first)
        row["motivo"] = f"{first.get('source') or 'pokemontcg'}: {first['motivo']} | tcgcsv: {second_reason}"
        row["chaves"] = f"{first.get('source') or 'pokemontcg'}[{first['chaves']}] tcgcsv[{second_keys}]"
        row["source"] = f"{first.get('source') or 'pokemontcg'}+tcgcsv"
        row["tcg_url"] = first.get("tcg_url") or second_url
        self._commit_noref(l, row)

    def _flush_unaccounted(self, exp_code: str, reason: Optional[str]) -> None:
        """Lote 3c: set interrompido no meio (exceção/Ctrl-C) — toda oferta que
        ainda não virou oportunidade nem linha "Sem preço" vai pra "Sem preço"
        com motivo operacional (e pro checkpoint). A soma precificadas + sem
        preço = total vale também aqui."""
        accounted = self.__dict__.setdefault("_set_accounted", set())
        left = [l for l in getattr(self, "_set_all", []) if l.uid not in accounted]
        if not left:
            return
        self._record_unpriced(exp_code, left, {l.uid: "failure" for l in left}, reason)
        self._set_unpriced = (self._set_unpriced or 0) + len(left)
        log.warning(f"  ⚠️  {exp_code}: {len(left)} listings não alcançados após a "
                    f"interrupção ({reason}) — listados na aba 'Sem preço'")

    def _rescue_via_tcgcsv(self, exp_code: str, exp_name: str,
                           listings: list["Listing"]):
        """Reprecifica `listings` via tcgcsv (referência buscada NESTE run, mesma
        escada de variante). Retorna (opps, uids_precificados, status_do_prefill)
        com status ∈ ok | no_group (a fonte respondeu sem dados) | fetch_failed
        (falha operacional). Os uids contam
        como resolvidos mesmo se `_build_opportunity` descartar a linha por
        filtro explícito (--opportunities-only/--chase-only)."""
        set_name = listings[0].set_name if listings else ""
        ok = self.tcgcsv.prefill_set(exp_code, self._ptcg_setcodes_for(exp_code), set_name)
        if not ok:
            log.warning(
                f"  tcgcsv sem referência p/ {exp_code} "
                f"({getattr(self.tcgcsv, 'last_prefill_status', '?')}) — "
                f"{len(listings)} listings seguem sem preço"
            )
            return [], set(), getattr(self.tcgcsv, "last_prefill_status", None) or "no_group"
        out: list["Opportunity"] = []
        handled: set = set()
        for l in listings:
            try:
                price = self.tcgcsv.market_price_usd(
                    l.card_name, l.set_code, l.collector_number,
                    foil=l.foil, rarity=l.rarity, first_edition=l.first_edition,
                )
            except Exception as e:  # noqa: BLE001
                # B1c: falha de infraestrutura NUNCA vira "sem ref compatível" definitivo
                log.debug(f"  tcgcsv pricing falhou {l.card_name}: {e!r}")
                self.__dict__.setdefault("_infra_failed", {})[l.uid] = f"tcgcsv: erro {type(e).__name__}"
                continue
            if not price or price <= 0:
                if self._ref_is_noref(self.tcgcsv):
                    if l.uid in self.__dict__.get("_noref_first", {}):
                        pa = self._pa
                        self._finalize_noref_pair(
                            l, pa(self.tcgcsv, "last_ref_reason", str, ""),
                            ",".join(pa(self.tcgcsv, "last_available_keys", list, [])),
                            pa(self.tcgcsv, "last_tcg_url", str, "") or "")
                    else:
                        self._record_noref(exp_code, l, self.tcgcsv)
                continue
            self.__dict__.setdefault("_noref_first", {}).pop(l.uid, None)
            handled.add(l.uid)
            opp = self._build_opportunity(l, price, self.tcgcsv)
            if opp is not None:
                out.append(opp)
        if handled:
            self.stats["tcgcsv_fallback_sets"] = self.stats.get("tcgcsv_fallback_sets", 0) + 1
            self.stats["tcgcsv_fallback_priced"] = self.stats.get("tcgcsv_fallback_priced", 0) + len(handled)
            log.info(
                f"  🛟 tcgcsv precificou {len(handled)} de {len(listings)} listings "
                f"sem preço da fonte principal em {exp_code} ({exp_name})"
            )
        return out, handled, "ok"

    def _conclude_set(self, exp_code: str, exp_name: str, pending: list["Listing"],
                      causes: dict, total: int, hits: int,
                      abort_kind: Optional[str] = None,
                      abort_reason: Optional[str] = None):
        """Fecha o set: resgata via tcgcsv o que a fonte principal não precificou
        (misses, falhas e o que não foi alcançado), registra o que ficou sem
        preço e define o desfecho. Generator: yield das Opportunities resgatadas.

        Desfechos: complete (tudo precificado) · complete_with_unpriced (o set foi
        coberto; N ofertas ficaram sem referência e estão na aba "Sem preço") ·
        no_coverage (a fonte respondeu e NADA do set foi precificado) ·
        operational_failure (rede/5xx/timeout/erro — tentar de novo).

        abort_kind: None (fim natural) | "operational" (timeout/mass failure) |
        "coverage" (corte por misses consecutivos). Skip-list SÓ no corte por
        cobertura quando o desfecho é no_coverage de verdade (nada precificado,
        nem pelo resgate) e o resgate NÃO falhou."""
        handled: set = set()
        rescue_status = None
        # B1e: a fonte principal falhou neste set? (só para a nota; o DESFECHO vem da cobertura final)
        primary_failed = abort_kind in ("operational", "breaker") or any(
            causes.get(l.uid) == "failure" for l in pending)
        if pending and self._tcgcsv_can_fallback():
            opps, handled, rescue_status = self._rescue_via_tcgcsv(exp_code, exp_name, pending)
            yield from opps
        self.__dict__.setdefault("_set_accounted", set()).update(handled)
        # B1b: ref incompatível na 1ª fonte que o tcgcsv não resolveu → "Sem Ref Compatível"
        # com os dois motivos (substitui a linha provisória; nunca vira miss nem fica duplicada)
        first_map = self.__dict__.setdefault("_noref_first", {})
        infra = self.__dict__.setdefault("_infra_failed", {})
        if rescue_status == "ok":
            # o tcgcsv RESPONDEU para toda oferta pendente: o que sobrou sem preço é resposta válida
            # ("sem referência na fonte"), não oferta sem resposta (B1e)
            for l in pending:
                if l.uid not in handled and l.uid not in infra and causes.get(l.uid, "not_reached") == "not_reached":
                    causes[l.uid] = "miss"
        if rescue_status == "fetch_failed":
            for l in pending:
                if l.uid not in handled:
                    infra.setdefault(l.uid, "tcgcsv: indisponível (falha de rede/5xx)")
        # B1c: oferta cujo fallback falhou por INFRAESTRUTURA fica pendente (aba "Sem preço",
        # falha operacional, com a 1ª causa registrada), não vira "Sem Ref Compatível" definitivo.
        infra_detail: dict = {}
        for l in pending:
            if l.uid in handled or l.uid not in infra:
                continue
            first = first_map.pop(l.uid, None)
            infra_detail[l.uid] = ((f"{first.get('source') or 'pokemontcg'}: {first['motivo']} | "
                                    if first else "") + infra[l.uid])
            causes[l.uid] = "failure"
        if first_map:
            why = {"no_group": "sem dados do set"}.get(rescue_status or "", "carta não encontrada")
            for l in pending:
                if l.uid in first_map and l.uid not in handled:
                    self._finalize_noref_pair(l, why)
        noref_uids = self.__dict__.setdefault("_noref_uids", set())
        left = [l for l in pending if l.uid not in handled and l.uid not in noref_uids]
        rescued = len(handled)
        prim = self._primary_name()
        self._set_by_source = ({"tcgcsv": hits + rescued} if prim == "tcgcsv"
                               else {prim: hits, "tcgcsv": rescued})
        if rescued:
            self._set_note = f"tcgcsv_rescue_priced_{rescued}_of_{len(pending)}"
        if primary_failed:
            extra = (f"fonte principal falhou, atendido pelo tcgcsv: {prim} {hits} + "
                     f"tcgcsv {rescued} precificadas")
            self._set_note = f"{self._set_note}; {extra}" if self._set_note else extra
        if self.__dict__.get("_set_breaker_note"):
            self._set_note = f"{self._set_note}; {self._set_breaker_note}" if self._set_note else self._set_breaker_note
        fail_left = [l for l in left if causes.get(l.uid) == "failure"]
        nr_left = [l for l in left if causes.get(l.uid, "not_reached") == "not_reached"]
        priced_total = hits + rescued
        # B1e: o desfecho reflete a cobertura FINAL. Falha operacional só quando sobra oferta SEM
        # resposta válida de nenhuma fonte (falha operacional ou não alcançada).
        if abort_kind == "operational" and (fail_left or nr_left):
            status, reason = "operational_failure", abort_reason
        elif left and rescue_status == "fetch_failed":
            # o resgate não pôde rodar: não dá pra afirmar ausência de cobertura
            status, reason = "operational_failure", "tcgcsv_rescue_fetch_failed"
        elif fail_left:
            status, reason = "operational_failure", f"pricing_failures_{len(fail_left)}_unrescued"
        elif not left:
            status, reason = "complete", None
        elif nr_left and (priced_total > 0 or abort_kind in ("operational", "breaker")):
            # B1b: o set NÃO foi avaliado por inteiro — não é "completo": tentar de novo
            status, reason = "operational_failure", f"coverage_interrupted_{len(nr_left)}_not_reached"
        elif priced_total == 0:
            status = "no_coverage"
            reason = abort_reason or f"{len(left)}_of_{total}_without_reference"
        else:
            status, reason = "complete_with_unpriced", f"{len(left)}_of_{total}_without_reference"
        self._set_outcome(status, reason)
        self._set_unpriced = len(left)
        if left:
            self._record_unpriced(exp_code, left, causes, reason, infra_detail)
            log.warning(
                f"  ⚠️  {exp_code}: {len(left)} de {total} listings SEM preço "
                f"({status}{': ' + reason if reason else ''}) — listados na aba 'Sem preço'"
            )
        if status != "operational_failure":
            self.stats["expansions_scanned"] += 1
        if abort_kind == "coverage" and status == "no_coverage":
            self.stats["expansions_no_coverage_abort"] += 1
            try:
                add_to_skip_list(exp_code, abort_reason or "no_coverage")
            except Exception as ee:
                log.warning(f"  Falha ao gravar skip-list ({exp_code}): {ee}")

    def scan_expansion(self, expansion: dict) -> Iterator[Opportunity]:
        exp_id = expansion["id"]
        exp_code = expansion.get("code", "")
        exp_name = expansion.get("name", "")
        self._cur_exp_code = exp_code
        # Lote 3: desfecho do set (lido por scan() p/ o set_complete e o resumo)
        self._set_status: str = "complete"
        self._set_reason: Optional[str] = None
        self._set_unpriced: int = 0
        self._set_total: int = 0
        self._set_note: Optional[str] = None
        self._set_by_source: dict = {}
        self._set_breaker_note: Optional[str] = None
        self._set_all: list = []
        self._set_accounted: set = set()
        log.info(f"→ Scan: {exp_name} ({exp_code}) [id={exp_id}]")
        # v2.4: marca início pra wall-clock timeout no pricing loop
        set_start = time.monotonic()
        # v2.14: timeout EFETIVO do set — aplica override de SET_TIMEOUT_OVERRIDES
        # (sets vintage pesados ganham mais fôlego sem o operador passar flag).
        # Tudo abaixo usa este valor, não self.per_set_timeout_s direto.
        effective_timeout_s = effective_set_timeout_s(exp_code, self.per_set_timeout_s)
        if effective_timeout_s != self.per_set_timeout_s:
            log.info(
                f"  ⏱️  Timeout override p/ {exp_code}: "
                f"{effective_timeout_s/60:.0f}min "
                f"(default {self.per_set_timeout_s/60:.0f}min)"
            )
        # v2.8 (Codex H2): deadline absoluta (monotonic). Passada pra todas
        # chamadas CT do set, então retries/429-sleeps respeitam o cap.
        deadline_ts: Optional[float] = (
            set_start + effective_timeout_s if effective_timeout_s else None
        )

        # v2.8: check ANTES de blueprints (cobre o caso de set já estourado
        # por algum estado externo, embora improvável aqui — set_start é now)
        if self._check_set_timeout(set_start, exp_code, exp_name, "pre_blueprints",
                                    timeout_s=effective_timeout_s):
            return

        # Carrega blueprints da expansão (indexa para O(1) lookup).
        # v2.8: deadline propaga pra _get → retries respeitam cap.
        try:
            blueprints = self.ct.list_blueprints(exp_id, deadline_ts=deadline_ts)
        except TimeoutError as e:
            log.error(f"  ⏱️  CT blueprints timeout para {exp_code}: {e}")
            self.stats["expansions_timed_out"] += 1
            self._set_outcome("operational_failure",
                              f"ct_blueprints_timeout_{int(effective_timeout_s or 0)}s")
            return
        bp_index = {bp["id"]: bp for bp in blueprints}
        log.info(f"  {len(blueprints)} blueprints carregados")

        # v2.8: check entre blueprints e listings — se blueprints foi rápido
        # mas o set já consumiu o orçamento (improvável p/ 1 call), abortar
        if self._check_set_timeout(set_start, exp_code, exp_name, "pre_listings",
                                    timeout_s=effective_timeout_s):
            return

        # Puxa todas listings do idioma configurado (default EN) da expansão de
        # uma vez (muito + eficiente que 1 chamada por blueprint — economiza de
        # 400+ calls para 1). v2.29: idioma vem de --language.
        lang = self.language
        try:
            raw_listings = self.ct.list_listings_by_expansion(
                exp_id, language=lang, deadline_ts=deadline_ts
            )
        except TimeoutError as e:
            log.error(f"  ⏱️  CT listings timeout para {exp_code}: {e}")
            self.stats["expansions_timed_out"] += 1
            self._set_outcome("operational_failure",
                              f"ct_listings_timeout_{int(effective_timeout_s or 0)}s")
            return
        self.stats["listings_fetched"] += len(raw_listings)
        log.info(f"  {len(raw_listings)} listings {lang.upper()} encontrados")

        # Dedup por (blueprint + seller + condição): mantém o menor preço.
        # Comparação é em BRL (não em cents) porque listings podem vir em
        # moedas diferentes — comparar cents direto seria errado (1 cent BRL
        # ≠ 1 cent EUR).
        best_by_uid: dict[str, Listing] = {}
        langs_seen: dict[str, int] = {}
        for raw in raw_listings:
            l = self._parse_listing(raw, bp_index)
            if not l:
                continue
            langs_seen[l.language or "(vazio)"] = langs_seen.get(l.language or "(vazio)", 0) + 1
            if not self._passes_filters(l):
                continue
            existing = best_by_uid.get(l.uid)
            if not existing or l.price_brl < existing.price_brl:
                best_by_uid[l.uid] = l

        # v2.29: diagnóstico do "verde mas vazio" por idioma — o servidor
        # devolveu ofertas mas NENHUMA bateu o idioma configurado (apelido não
        # mapeado, código novo da API...). Avisar com o que foi visto.
        if raw_listings and lang and lang.lower() not in langs_seen and langs_seen:
            log.warning(
                f"  ⚠️  Nenhuma oferta no idioma '{lang}' — idiomas observados nas "
                f"{len(raw_listings)} ofertas devolvidas: {langs_seen}. Confira o "
                f"código em --language (apelidos conhecidos: {sorted(LANGUAGE_ALIASES)})."
            )

        self.stats["listings_after_filters"] += len(best_by_uid)
        log.info(f"  {len(best_by_uid)} listings após filtros (NM, {lang.upper()}, não-graded, ≥${self.min_price_usd})")

        # v2.26: provider PRIMÁRIO tcgcsv é bulk-por-set — sem prefill, todo
        # market_price_usd devolve None. Lote 3: distingue lacuna da FONTE
        # ("no_group": o tcgcsv respondeu e não tem o set → no_coverage, sem
        # skip-list) de FALHA OPERACIONAL ("fetch_failed": rede/5xx → tentar de
        # novo). Em ambos os casos os listings ficam registrados (aba "Sem preço").
        all_listings = list(best_by_uid.values())
        self._set_total = len(all_listings)
        self._set_all = all_listings
        if isinstance(self.pricing, TcgCsvFallbackProvider) and best_by_uid:
            first_listing = all_listings[0]
            if not self.pricing.prefill_set(
                exp_code, self._ptcg_setcodes_for(exp_code),
                first_listing.set_name or exp_name,
            ):
                st = getattr(self.pricing, "last_prefill_status", None)
                if st == "fetch_failed":
                    log.warning(
                        f"  🔌 tcgcsv (primário) FALHOU ao buscar {exp_code} "
                        f"({exp_name}) — falha operacional, tentar de novo."
                    )
                    yield from self._conclude_set(
                        exp_code, exp_name, all_listings, {}, len(all_listings), 0,
                        abort_kind="operational", abort_reason="tcgcsv_fetch_failed")
                else:
                    log.warning(
                        f"  🕳️  tcgcsv (primário) sem groupId único/dados p/ "
                        f"{exp_code} ({exp_name}) — set sem referência de preço "
                        f"neste run (skip-list NÃO gravada: gap é do tcgcsv, "
                        f"não do set)."
                    )
                    self.stats["expansions_no_coverage_abort"] += 1
                    yield from self._conclude_set(
                        exp_code, exp_name, all_listings,
                        {l.uid: "miss" for l in all_listings}, len(all_listings), 0,
                        abort_reason="tcgcsv_primary_no_group_id")
                return

        # B1e: disjuntor aberto → o set começa pelo tcgcsv; sonda barata decide se a fonte voltou.
        brk = self._active_breaker() if all_listings else None
        if brk is not None and brk.is_open:
            if brk.probe_due():
                brk.mark_probe()
                probe = getattr(self.pricing, "probe", None)
                try:
                    healthy = bool(probe()) if callable(probe) else True
                except Exception:  # noqa: BLE001
                    healthy = False
                if healthy:
                    brk.close()
                    log.info(f"  🟢 {self._primary_name()} respondeu à sonda — disjuntor fechado, "
                             f"voltando à fonte principal em {exp_code}")
            if brk.is_open:
                self.__dict__.setdefault("_breaker_sets", set()).add(exp_code)
                self._set_breaker_note = ("disjuntor aberto (fonte principal degradada): set atendido "
                                          "direto pelo tcgcsv")
                log.warning(f"  🔌 {exp_code}: fonte principal degradada (disjuntor aberto) — set vai "
                            f"direto ao tcgcsv (mesma regra exata de edição e acabamento)")
                yield from self._conclude_set(
                    exp_code, exp_name, all_listings, {}, len(all_listings), 0,
                    abort_kind="breaker", abort_reason="source_breaker_open")
                return

        # Para cada listing filtrado, busca preço TCG e calcula margem
        total_listings = len(all_listings)
        # v2.9 (Codex H5): contadores per-set pra detectar mass pricing failure
        set_pricing_attempts = 0
        set_pricing_failures = 0
        # v2.13 (frente eficiência): contador de "misses" consecutivos (preço
        # não encontrado na fonte) pra cortar sets sem cobertura cedo.
        set_consecutive_misses = 0
        streak_cards: set = set()   # B1b: o corte conta CARTAS distintas, não ofertas
        # B1b: provider em LOTE (tcgcsv): o set inteiro já está em memória, continuar custa zero
        # chamada — o corte por misses só existe como proteção de custo por oferta.
        miss_cap = 0 if isinstance(self.pricing, TcgCsvFallbackProvider) else self.max_consecutive_misses
        set_tcg_hits = 0
        # Lote 3: tudo que a fonte principal não precificou — misses (a fonte
        # respondeu sem a carta) e falhas (exceção) — vai pro resgate tcgcsv e,
        # se ainda sobrar, pra aba "Sem preço". Nada some.
        set_misses: list["Listing"] = []
        set_noref_first: list["Listing"] = []   # B1b: 1ª fonte incompatível → resgate tcgcsv
        set_failed: list["Listing"] = []
        causes: dict[str, str] = {}

        def _pending(upto: int) -> list["Listing"]:
            """misses + falhas + listings ainda não alcançados (a partir de `upto`)."""
            return set_misses + set_failed + set_noref_first + all_listings[upto:]

        for i, l in enumerate(all_listings, 1):
            # v2.4: wall-clock timeout check antes de cada call de pricing
            # v2.14: usa o timeout EFETIVO do set (com override vintage).
            if effective_timeout_s and (time.monotonic() - set_start) > effective_timeout_s:
                elapsed = time.monotonic() - set_start
                log.error(
                    f"  ⏱️  TIMEOUT set {exp_code} ({exp_name}): {elapsed/60:.1f}min "
                    f"> {effective_timeout_s/60:.1f}min limite. Abortando após "
                    f"{i-1}/{total_listings} listings priced (falha operacional — "
                    f"NÃO vai pra skip-list)."
                )
                self.stats["expansions_timed_out"] += 1
                yield from self._conclude_set(
                    exp_code, exp_name, _pending(i - 1), causes, total_listings,
                    set_tcg_hits, abort_kind="operational",
                    abort_reason=f"per_set_timeout_{int(effective_timeout_s)}s_at_{i-1}_of_{total_listings}")
                return
            if i % 50 == 0 or i == total_listings:
                log.info(f"  Pricing progress: {i}/{total_listings} listings consultados")
            # PR-F (2026-05-28): heartbeat + set_progress JSONL na cadência
            # configurável (--flush-every-listings, default 50). Distinto do
            # INFO log acima (mantido em i%50 pra não quebrar contrato de log).
            flush_n = getattr(self._checkpoint, "flush_every_listings", 0) if self._checkpoint else 0
            if flush_n and (i % flush_n == 0 or i == total_listings):
                self.heartbeat(f"set={exp_code} i={i}/{total_listings}")
                if self._checkpoint is not None:
                    self._checkpoint.write_progress(exp_code, i, total_listings)
            set_pricing_attempts += 1
            tcg_market = None
            failed = False
            infra_fail = False
            _t0 = time.monotonic()
            _r0 = getattr(self.pricing, "retry_5xx", 0)
            _r0 = _r0 if isinstance(_r0, int) else 0
            try:
                tcg_market = self.pricing.market_price_usd(
                    l.card_name, l.set_code, l.collector_number,
                    foil=l.foil,  # H2 fix: foil/reverse-aware variant selection
                    rarity=l.rarity,  # v2.18: holo rare → holofoil; base → normal
                    first_edition=l.first_edition,  # B1: edição exata
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                # v2.9: erros de rede transientes — já foram retried pelo provider.
                # Log debug (não vira WARNING flood), conta como pricing_failure
                # pra mass-failure detection.
                log.debug(f"  Pricing transient {l.card_name}: {type(e).__name__}: {e}")
                set_pricing_failures += 1
                self.stats["pricing_failures"] += 1
                failed = True
                infra_fail = True
            except Exception as e:
                # v2.9 (Codex H5): erros DESCONHECIDOS = WARNING + counter.
                # Pre-fix: log.debug + swallow → schema drift / SSL / JSON parse
                # silenciosamente removia deals. Agora aparece no INFO log.
                log.warning(
                    f"  Pricing FAILURE {l.card_name} ({l.set_code}/{l.collector_number}) "
                    f"bp={getattr(l, 'blueprint_id', '?')}: {type(e).__name__}: {e}"
                )
                set_pricing_failures += 1
                self.stats["pricing_failures"] += 1
                failed = True
            _r1 = getattr(self.pricing, "retry_5xx", 0)
            degraded = infra_fail or (isinstance(_r1, int) and _r1 > _r0)   # respondeu só depois de 5xx/429
            breaker_opened = (brk.record(not degraded, time.monotonic() - _t0)
                              if brk is not None else False)
            # Lote 3b: a falha em massa é avaliada DEPOIS de contabilizar o listing
            # atual (hit/miss/falha) — antes ela abortava antes de registrar um
            # listing já precificado e a linha sumia.
            mass_failure = (
                set_pricing_attempts >= self.mass_pricing_failure_min_sample
                and (set_pricing_failures / set_pricing_attempts) > self.mass_pricing_failure_threshold
            )
            if failed:
                set_failed.append(l)
                causes[l.uid] = "failure"
            elif (not tcg_market or tcg_market <= 0) and self._ref_is_noref(self.pricing):
                # B1: carta ENCONTRADA sem referência compatível — sem margem, fora da
                # contagem de misses (não alimenta o corte por cobertura nem a skip-list).
                if self._tcgcsv_can_fallback() and self.pricing is not self.tcgcsv:
                    # B1b: tenta o tcgcsv (mesma regra exata) antes de dar como sem ref
                    self.__dict__.setdefault("_noref_first", {})[l.uid] = self._noref_row(
                        exp_code, l, self.pricing)
                    set_noref_first.append(l)
                else:
                    self._record_noref(exp_code, l, self.pricing)
            elif not tcg_market or tcg_market <= 0:
                # v2.13 (frente eficiência): conta miss consecutivo — a fonte
                # RESPONDEU e não tem a carta (≠ falha). Cap atingido = corte do
                # set por falta de cobertura (resgate tcgcsv antes de desistir).
                streak_cards.add(l.blueprint_id)
                set_consecutive_misses = len(streak_cards)
                set_misses.append(l)
                causes[l.uid] = "miss"
                if miss_cap > 0 and set_consecutive_misses >= miss_cap:
                    log.warning(
                        f"  🕳️  SEM COBERTURA em {exp_code} ({exp_name}): "
                        f"{set_consecutive_misses} listings consecutivos sem preço "
                        f"na fonte (cap={self.max_consecutive_misses}). Cortando set "
                        f"após {i}/{total_listings}; resgate tcgcsv p/ o restante."
                    )
                    yield from self._conclude_set(
                        exp_code, exp_name, _pending(i), causes, total_listings,
                        set_tcg_hits, abort_kind="coverage",
                        abort_reason=(f"no_coverage_{set_consecutive_misses}_consecutive_"
                                      f"misses_at_{i}_of_{total_listings}"))
                    return
            else:
                # Hit: zera o contador de misses consecutivos.
                set_consecutive_misses = 0
                streak_cards.clear()
                set_tcg_hits += 1
                opp = self._build_opportunity(l, tcg_market, self.pricing)
                if opp is not None:
                    yield opp
                else:
                    self._set_accounted.add(l.uid)   # descartada por filtro explícito

            if breaker_opened:
                self.__dict__.setdefault("_breaker_sets", set()).add(exp_code)
                self._set_breaker_note = (f"disjuntor aberto às {brk.opened_at:%H:%M} após "
                                          f"{brk.fail_count} falhas em {brk.sample_count} ofertas")
                log.warning(f"  🔌 {self._primary_name()} DEGRADADA em {exp_code} após {i} oferta(s): "
                            f"{brk.fail_count} falhas em {brk.sample_count} — o restante do set vai "
                            f"direto ao tcgcsv (lote, mesma regra exata); sem skip-list")
                yield from self._conclude_set(
                    exp_code, exp_name, _pending(i), causes, total_listings, set_tcg_hits,
                    abort_kind="breaker",
                    abort_reason=f"source_breaker_open_at_{i}_of_{total_listings}")
                return
            # v2.9: mass pricing failure → falha OPERACIONAL do set (nunca skip-list).
            if mass_failure:
                fail_pct = set_pricing_failures / set_pricing_attempts * 100
                log.error(
                    f"  💥 MASS PRICING FAILURE em {exp_code} ({exp_name}): "
                    f"{set_pricing_failures}/{set_pricing_attempts} ({fail_pct:.0f}%) "
                    f"falharam. Abortando set (falha operacional — NÃO vai pra "
                    f"skip-list)."
                )
                self.stats["expansions_mass_pricing_abort"] += 1
                yield from self._conclude_set(
                    exp_code, exp_name, _pending(i), causes, total_listings,
                    set_tcg_hits, abort_kind="operational",
                    abort_reason=f"mass_pricing_failure_{set_pricing_failures}_of_{set_pricing_attempts}")
                return

        # Fim natural do set: o que a fonte principal não precificou (misses do
        # fim do set e falhas) vai pro resgate tcgcsv — também com hits prévios.
        yield from self._conclude_set(
            exp_code, exp_name, set_misses + set_failed + set_noref_first, causes, total_listings,
            set_tcg_hits)

    def _build_opportunity(
        self, l: "Listing", tcg_market: float, source_provider: "PricingProvider"
    ) -> Optional["Opportunity"]:
        """v2.23: constrói uma Opportunity a partir de um listing precificado.

        Extraído do loop de scan_expansion pra ser reusado pelos DOIS caminhos
        de pricing (pokemontcg.io direto e o fallback tcgcsv) — garante que a
        margem/flags/sinais sejam computados IDENTICAMENTE independente da fonte.
        `source_provider` é o provider que produziu o preço (lê last_tcg_url /
        last_variant_used / last_ptcg_rarity / last_set_release_date dele).
        Retorna None quando o listing deve ser descartado (--opportunities-only
        near-miss ou --chase-only)."""
        tcg_brl = tcg_market * self.usd_brl
        ct_brl = l.price_brl
        # D8: a conta de margem mora SÓ em ct_economics. Preço CRU (per-expansion):
        # compra_inclui_hub=False. O corte compara com margem_venda (sobre a VENDA).
        econ = compute_economics(tcg_brl, ct_brl, compra_inclui_hub=False, costs=self._costs())
        if not econ.tem_margem:
            self._record_noref(
                getattr(self, "_cur_exp_code", "") or getattr(l, "set_code", ""), l, source_provider,
                status="MARGEM_NAO_CALCULAVEL",
                reason=f"margem não calculável: {econ.sem_margem_motivo}")
            return None
        margin = econ.margem_venda
        below_threshold = not econ.passa_corte(self.threshold)
        if below_threshold and not self.keep_all_priced:
            # Modo --opportunities-only (legado): descarta o near-miss — e CONTA o descarte.
            self.stats["opportunities_only_descartadas"] = self.stats.get("opportunities_only_descartadas", 0) + 1
            return None

        self.stats["tcg_price_found"] += 1
        shipping_brl = self._costs().frete_compra_brl or 0.0
        net_margin = (econ.margem_liquida_venda if econ.margem_liquida_venda is not None
                      else econ.margem_venda)

        if below_threshold:
            # v2.22: precificado mas abaixo do threshold. Persistido pro XLSX
            # (contrato de entrega → fallback near-miss do postprocess), mas NÃO
            # conta como oportunidade no funil.
            self.stats["priced_below_threshold"] += 1
        else:
            self.stats["opportunities_found"] += 1
        # v2.7.1: tcg_url vem do provider (last call). Pode ser None.
        tcg_url = getattr(source_provider, "last_tcg_url", None)
        # v2.8 Layer 4: variant usada (holofoil/reverseHolofoil/normal/etc).
        variant_used = getattr(source_provider, "last_variant_used", None)
        # v2.13: rarity oficial pokemontcg.io (preferida) → fallback rarity CT.
        ptcg_rarity = getattr(source_provider, "last_ptcg_rarity", None)
        # v2.23: fonte do preço (pokemontcg.io vs tcgcsv) pra rotular proveniência.
        price_source = getattr(source_provider, "last_price_source", None) \
            or getattr(source_provider, "name", None)
        # v2.14 + v2.18: flag de baixa confiança de variante. Listing NÃO-foil
        # que só achou preço numa variante metálica premium (holofoil/
        # unlimitedHolofoil) sendo NÃO-holo (o caso Gengar não-foil → $1600).
        set_release = getattr(source_provider, "last_set_release_date", None) or ""
        if not isinstance(set_release, str):
            set_release = ""
        is_holo_card = ct_variants.rarity_is_holo(l.rarity, ptcg_rarity,
                                                  set_released=set_release or None,
                                                  set_code=l.set_code)
        variant_low_conf = (
            l.foil is False
            and not is_holo_card
            and variant_used in ("holofoil", "unlimitedHolofoil")
        )
        # v2.24: estende o sinal pro caso reverse-outlier — common/uncommon
        # NÃO-holo que casa em `reverseHolofoil` cujo market é um outlier absurdo
        # vs `normal` (>5×). Ex.: Lileep ex12-56 normal $0.55 vs reverse $37.50
        # (68×). Esses são reverse GENUÍNOS (foil=True), então o sinal v2.18 não
        # pegava; aqui a razão reverse/normal denuncia a âncora ilíquida.
        normal_market = getattr(source_provider, "last_normal_market", None)
        variant_low_conf = variant_low_conf or _reverse_nonholo_market_outlier(
            variant_used, is_holo_card, tcg_market, normal_market
        )
        rarity_for_tier = ptcg_rarity or l.rarity
        chase_tier = classify_chase_tier(rarity_for_tier)
        val_score, val_note = compute_valorization(
            rarity_for_tier, set_release, tcg_market
        )
        # Filtro --chase-only: só TOP/MID passam.
        if self.chase_only and chase_tier not in CHASE_ONLY_TIERS:
            self.stats["skipped_non_chase"] += 1
            return None
        ref_data_at = self._pa(source_provider, "last_ref_data_at", str, "") or ""
        fetched = self._pa(source_provider, "last_price_fetched_at", str, "") or ""
        ref_label = "dado de" if ref_data_at else ("buscado em" if fetched else "")
        if not ref_data_at:
            ref_data_at = fetched
        return Opportunity(
            listing=l,
            tcg_market_usd=tcg_market,
            tcg_market_brl=tcg_brl,
            ct_price_brl=ct_brl,
            margin_pct=margin,
            margin_brl=econ.lucro_bruto,
            estimated_shipping_brl=shipping_brl,
            net_margin_pct=net_margin,
            tcg_url=tcg_url,
            price_variant_used=variant_used,
            price_source=price_source,
            chase_tier=chase_tier,
            valorization_score=val_score,
            valorization_note=val_note,
            set_release_date=set_release,
            variant_low_confidence=variant_low_conf,
            below_threshold=below_threshold,
            price_fetched_at=(lambda v: v if isinstance(v, str) else "")(
                getattr(source_provider, "last_price_fetched_at", None)),
            edition=self._opp_edition(l, source_provider),
            finish=self._pa(source_provider, "last_offer_variant", tuple, None)[1]
            if self._pa(source_provider, "last_offer_variant", tuple, None)
            else (ct_variants.FIN_REVERSE if l.foil else
                  ct_variants.FIN_HOLO if is_holo_card else ct_variants.FIN_NORMAL),
            ref_compatible=self._pa(source_provider, "last_ref_exact", bool, False),
            ref_data_at=ref_data_at, ref_data_label=ref_label,
        )

    def _opp_edition(self, l: "Listing", provider) -> str:
        """Edição da linha: 1st (oferta 1st), ED_NONE (carta sem divisão de edição) ou unl."""
        if l.first_edition:
            return ct_variants.ED_1ST
        divided = self._pa(provider, "last_divided", bool, True)
        key = self._pa(provider, "last_ref_key", str, None)
        if key is not None and not divided:
            return ct_variants.ED_NONE
        return ct_variants.ED_UNL

    def _primary_name(self) -> str:
        n = getattr(getattr(self, "pricing", None), "name", None)
        return n if isinstance(n, str) and n else "pokemontcg"

    def _active_breaker(self) -> Optional["SourceBreaker"]:
        """B1e: o disjuntor só existe quando há para onde desviar (tcgcsv de resgate habilitado e
        fonte principal ≠ tcgcsv). `scanner.breaker = None` desliga."""
        if not self._tcgcsv_can_fallback() or self.pricing is self.tcgcsv:
            return None
        if "breaker" not in self.__dict__:
            self.breaker = SourceBreaker()
        return self.breaker

    def _tcgcsv_can_fallback(self) -> bool:
        """v2.23: True se o fallback tcgcsv está habilitado E disponível.

        Habilitado por padrão; desligado por `--no-tcgcsv-fallback`. Disponível
        só quando há um provider tcgcsv instanciado (self.tcgcsv). Mantém o
        default path 100% intacto quando desligado."""
        return self.tcgcsv_fallback and self.tcgcsv is not None

    def _ptcg_setcodes_for(self, ct_set_code: str) -> list[str]:
        """v2.23: CT set code → lista de setcodes pokemontcg.io candidatos.

        Reusa o mapa SET_ALIAS_TO_PTCG do PokemonTcgIoProvider (CT code +
        aliases). É o 1º salto da ponte CT→tcgcsv (o 2º é abbr tcgcsv)."""
        code = (ct_set_code or "").lower()
        # v2.29: código CT de set JP que colide com setcode pokemontcg.io não
        # entra por identidade (ver CT_JP_SETCODE_COLLISIONS).
        out = ([code] if code and code not in CT_JP_SETCODE_COLLISIONS
               and code not in CT_PTCG_ID_COLLISIONS else [])
        for alias in PokemonTcgIoProvider.SET_ALIAS_TO_PTCG.get(code, []):
            if alias.lower() not in out:
                out.append(alias.lower())
        return out

    def scan(self, expansions: list[dict],
             checkpoint: Optional["CheckpointWriter"] = None) -> list[Opportunity]:
        opps: list[Opportunity] = []
        # PR-F (2026-05-28): expõe heartbeat + checkpoint pro scan_expansion
        # (que não recebe checkpoint como arg). Se não há checkpoint, heartbeat
        # vira no-op (lambda) e write_progress é guardado por self._checkpoint=None.
        self._checkpoint = checkpoint
        self.heartbeat = checkpoint.touch_heartbeat if checkpoint else (lambda *_: None)
        # v2.4: carrega skip-list (sets que estouraram timeout em runs anteriores)
        skip_data = load_skip_list() if not self.ignore_skip_list else {"skipped": [], "reasons": {}}
        # PR-F (2026-05-28): TTL. Entries TRANSIENTES (timeout / mass-pricing-fail)
        # com added_at > 7d são re-tentadas (dropadas do skip_set deste run; o
        # arquivo NÃO é reescrito aqui — se o set falhar de novo, add_to_skip_list
        # refresca added_at). Entries permanentes (unexpected_error_*) e legadas
        # (str pura, sem timestamp) seguem pulando.
        reasons_map = skip_data.get("reasons") or {}
        skip_set = set(skip_data.get("skipped", []))
        expired = {
            code for code in skip_set
            if _skip_entry_is_expired(reasons_map.get(code))
        }
        if expired:
            log.info(
                f"Skip-list TTL ({_SKIP_LIST_TTL_DAYS}d): re-tentando {len(expired)} "
                f"set(s) transiente(s) expirado(s): {', '.join(sorted(expired))}"
            )
            skip_set -= expired
        if skip_set:
            log.info(
                f"Skip-list ativa ({SKIP_LIST_FILE.name}): {len(skip_set)} sets serão pulados "
                f"({', '.join(sorted(skip_set))}). Use --ignore-skip-list pra forçar."
            )
        # v2.5.1 (2026-05-16 night): heartbeat por set + total elapsed.
        # Operador pediu detectabilidade de stall: agora cada set loga
        # "ALIVE [HH:MM:SS] set N/TOTAL exp_code elapsed=Xmin" antes de scan_expansion.
        # Também captura Exception genérica (não só HTTPError) pra não matar
        # o loop inteiro se um set lançar algo inesperado.
        run_start = time.monotonic()
        total_sets = len(expansions)
        self.set_outcomes: list[dict] = []   # Lote 3: desfecho de cada set
        self.unpriced_rows: list[dict] = []  # Lote 3: listings sem preço (aba "Sem preço")
        self.interrupted = False             # Lote 3c: Ctrl-C no meio do run
        self.stats["filtros_aplicados"] = (
            f"NM exato (Near Mint); idioma {str(getattr(self, 'language', 'en')).upper()}; "
            f"{'não graduada' if self.exclude_graded else 'graduadas INCLUÍDAS'}; sem Trainer/Galarian Gallery (TG/GG); "
            f"piso de preço US$ {self.min_price_usd:g}; deduplicação por oferta (mesmo produto+vendedor)")
        self.noref_rows: list[dict] = []     # B1: ofertas sem referência compatível
        self.stats.setdefault("listings_sem_ref_compativel", 0)
        for idx, exp in enumerate(expansions, 1):
            exp_code = exp.get("code", "")
            elapsed_min = (time.monotonic() - run_start) / 60.0
            log.info(
                f"ALIVE [{datetime.now().strftime('%H:%M:%S')}] set {idx}/{total_sets} "
                f"({exp_code}) total_elapsed={elapsed_min:.1f}min"
            )
            # PR-F: heartbeat por set (detecta stall externamente via mtime)
            self.heartbeat(f"set {idx}/{total_sets} ({exp_code}) elapsed={elapsed_min:.1f}min")
            if exp_code in skip_set:
                self.stats["expansions_skipped_by_list"] += 1
                # PR-F: reason pode ser dict {reason, added_at} ou str legada.
                reason = _skip_reason_str(reasons_map.get(exp_code)) or "?"
                log.warning(f"⏭️  Pulando {exp.get('name')} ({exp_code}) — skip-list (motivo: {reason})")
                continue
            # v2.6 (2026-05-17): snapshot per-set stats antes do scan_expansion
            # pra calcular DIFFs (self.stats é cumulativo). Permite registrar
            # blueprints/filtered/priced/opps_found per set no checkpoint JSONL.
            stats_pre = dict(self.stats) if checkpoint and checkpoint.enabled else None
            set_start = time.monotonic()
            opps_pre_count = len(opps)
            # Lote 3: desfecho do set (preenchido por scan_expansion/_conclude_set;
            # as exceções abaixo viram "operational_failure" — NUNCA skip-list).
            self._set_status, self._set_reason = "complete", None
            self._set_unpriced, self._set_note, self._set_total = 0, None, 0
            self._set_all, self._set_accounted = [], set()
            self._noref_uids = set()
            self._noref_first = {}
            self._infra_failed = {}
            self._set_by_source, self._set_breaker_note = {}, None
            try:
                # v2.6: itera o generator e escreve cada Opportunity no checkpoint
                # ASSIM QUE for yielded. Antes era `opps.extend(scan_expansion(exp))`
                # — esperar o generator esgotar dava melhor desempenho mas perdia
                # tudo em crash mid-set. Agora: live append-only.
                for opp in self.scan_expansion(exp):
                    opps.append(opp)
                    self._set_accounted.add(opp.listing.uid)
                    if checkpoint:
                        checkpoint.write_opportunity(opp)
            except requests.HTTPError as e:
                code = getattr(getattr(e, "response", None), "status_code", "")
                log.error(f"Falha em {exp.get('name')}: {e} (falha operacional — tentar de novo)")
                self._set_outcome("operational_failure", f"http_error_{code}")
            except requests.RequestException as e:
                # Lote 3: rede/5xx/timeout da CT = FALHA OPERACIONAL do run, não
                # fato do set → nunca vai pra skip-list; aparece no resumo.
                log.error(
                    f"Falha de rede em {exp.get('name')} ({exp_code}): "
                    f"{type(e).__name__}: {e}. Falha operacional — tentar de novo."
                )
                self._set_outcome("operational_failure", f"network_error_{type(e).__name__}")
            except Exception as e:
                # v2.5.1: nunca deixa exceção genérica matar o full scan.
                # Lote 3: também falha operacional (não é ausência de cobertura).
                log.error(
                    f"Erro inesperado em {exp.get('name')} ({exp_code}): "
                    f"{type(e).__name__}: {e}. Falha operacional — tentar de novo."
                )
                self._set_outcome("operational_failure", f"unexpected_error_{type(e).__name__}")
            except KeyboardInterrupt:
                # Lote 3c: Ctrl-C no meio do set — registra, não perde o que já
                # foi coletado; o main escreve o parcial e sai com código != 0.
                log.error(f"Interrompido pelo operador em {exp.get('name')} ({exp_code}) — "
                          f"gravando o que já foi coletado.")
                self._set_outcome("operational_failure", "interrupted_by_user")
                self.interrupted = True
            if self._set_status == "operational_failure":
                # nada some: o que o set ainda não tinha contabilizado vai pra "Sem preço"
                self._flush_unaccounted(exp_code, self._set_reason)
                self.stats["expansions_operational_failure"] = self.stats.get("expansions_operational_failure", 0) + 1
            self.set_outcomes.append({
                "set": exp_code, "name": exp.get("name", ""),
                "status": self._set_status, "reason": self._set_reason,
                "unpriced": self._set_unpriced, "total": self._set_total,
                "note": self._set_note,
                "noref": sum(1 for r in self.noref_rows if r["set"] == exp_code),
                "elapsed_s": round(time.monotonic() - set_start, 1),
                "by_source": dict(self._set_by_source or {}),
            })
            # v2.6: emite set_complete (agora para TODO desfecho) com DIFFs
            if checkpoint and checkpoint.enabled and stats_pre is not None:
                per_set_stats = {
                    "blueprints": 0,  # sem stat agregado de blueprints; deixar 0
                    "filtered": self.stats.get("listings_after_filters", 0) - stats_pre.get("listings_after_filters", 0),
                    "priced": self.stats.get("tcg_price_found", 0) - stats_pre.get("tcg_price_found", 0),
                    "opps_found": len(opps) - opps_pre_count,
                }
                checkpoint.write_set_complete(
                    set_code=exp_code,
                    set_name=exp.get("name", ""),
                    per_set_stats=per_set_stats,
                    elapsed_s=time.monotonic() - set_start,
                    status=self._set_status,
                    reason=self._set_reason,
                    unpriced=self._set_unpriced,
                    note=self._set_note,
                    noref=sum(1 for r in self.noref_rows if r["set"] == exp_code),
                )
            if self.interrupted:
                # sets que nem começaram: operational_failure "não iniciado"
                for rest in expansions[idx:]:
                    rc = rest.get("code", "")
                    self.set_outcomes.append({
                        "set": rc, "name": rest.get("name", ""),
                        "status": "operational_failure", "reason": "interrupted_not_started",
                        "unpriced": 0, "total": 0, "note": None})
                    self.stats["expansions_operational_failure"] = self.stats.get("expansions_operational_failure", 0) + 1
                    if checkpoint and checkpoint.enabled:
                        checkpoint.write_set_complete(
                            set_code=rc, set_name=rest.get("name", ""),
                            per_set_stats={}, elapsed_s=0.0,
                            status="operational_failure", reason="interrupted_not_started")
                break
        # Lote 3: resumo do run — falha operacional NÃO some.
        op = [o for o in self.set_outcomes if o["status"] == "operational_failure"]
        nc = [o for o in self.set_outcomes if o["status"] == "no_coverage"]
        cu = [o for o in self.set_outcomes if o["status"] == "complete_with_unpriced"]
        self.stats["sets_operational_failure"] = (
            "; ".join(f"{o['set']}: {o['reason']}" for o in op) or "(nenhum)")
        self.stats["sets_no_coverage"] = (
            "; ".join(f"{o['set']}: {o['unpriced']}/{o['total']} sem preço" for o in nc)
            or "(nenhum)")
        self.stats["sets_complete_with_unpriced"] = (
            "; ".join(f"{o['set']}: {o['unpriced']}/{o['total']} sem preço" for o in cu)
            or "(nenhum)")
        self.stats["listings_sem_preco"] = len(self.unpriced_rows)
        self.stats["saude_fonte_principal"] = self._source_health_line() or ""
        for line in self.run_summary_lines():
            log.warning(line) if ("tentar de novo" in line) else log.info(line)
        # Ordena por margem bruta desc (maior oportunidade primeiro)
        opps.sort(key=lambda o: o.margin_pct, reverse=True)
        return opps

    def _source_health_line(self) -> Optional[str]:
        """B1e: frase de saúde da fonte principal (None quando não há disjuntor ativo no run)."""
        brk = self.__dict__.get("breaker")
        if brk is None:
            return None
        opens = [e for e in brk.events if e["event"] == "open"]
        if not opens:
            return "pokemontcg.io saudável neste run (disjuntor não abriu)"
        parts = []
        for k, e in enumerate(brk.events):
            if e["event"] == "open":
                parts.append(f"pokemontcg.io degradada às {e['at']:%H:%M} após {e['fails']} falhas "
                             f"em {e['n']}")
            else:
                parts.append(f"voltou às {e['at']:%H:%M}")
        k = len(self.__dict__.get("_breaker_sets", ()))
        tail = (f"{k} set atendido pelo tcgcsv" if k == 1 else f"{k} sets atendidos pelo tcgcsv")
        return "; ".join(parts) + "; " + tail

    def run_summary_lines(self) -> list[str]:
        """Resumo do run pelos QUATRO desfechos (Lote 3b): completo · completo com
        N sem preço (set coberto; ofertas sem referência na aba "Sem preço") ·
        sem cobertura (a fonte respondeu e NADA do set foi precificado) · falha
        operacional ("não concluído, tentar de novo")."""
        outs = getattr(self, "set_outcomes", [])
        op = [o for o in outs if o["status"] == "operational_failure"]
        nc = [o for o in outs if o["status"] == "no_coverage"]
        cu = [o for o in outs if o["status"] == "complete_with_unpriced"]
        ok = [o for o in outs if o["status"] == "complete"]
        lines = [f"Sets: {len(ok)} completos | {len(cu)} completos com sem preço | "
                 f"{len(nc)} sem cobertura | {len(op)} com falha operacional"]
        if op:
            lines.append("⚠️ NÃO CONCLUÍDOS — tentar de novo (falha operacional): " +
                         ", ".join(f"{o['set']} ({o['reason']})" for o in op))
        if nc:
            lines.append("Sem cobertura (a fonte respondeu e não tem as cartas do set): " +
                         ", ".join(f"{o['set']} ({o['unpriced']}/{o['total']})" for o in nc))
        if cu:
            def _frac(o):
                priced = o["total"] - o["unpriced"]
                return f"{o['set']} ({priced}/{o['total']} precificadas, {o['unpriced']} sem preço)"
            lines.append("Completos com listings sem preço (aba 'Sem preço'): " +
                         ", ".join(_frac(o) for o in cu))
            low = [o for o in cu if o["total"] and (o["total"] - o["unpriced"]) * 2 < o["total"]]
            if low:
                lines.append("⚠️ ABAIXO DE METADE precificada (cobertura fraca — conferir antes de confiar): " +
                             ", ".join(f"{o['set']} ({o['total'] - o['unpriced']}/{o['total']})" for o in low))
        by: dict = {}
        for o in outs:
            for k, v in (o.get("by_source") or {}).items():
                by[k] = by.get(k, 0) + v
        if by:
            lines.append("Preços por fonte: " + " | ".join(f"{k} {v}" for k, v in by.items()))
        r5 = getattr(getattr(self, "pricing", None), "retry_5xx", None)
        if isinstance(r5, int):
            lines.append(f"{r5} retries por 5xx/429 da pokemontcg.io neste run")
        resc = [o for o in outs if (o.get("by_source") or {}).get("tcgcsv", 0) > 0
                and o.get("by_source", {}).get(self._primary_name(), 0) >= 0
                and self._primary_name() != "tcgcsv"]
        if resc:
            lines.append("Sets atendidos por resgate (tcgcsv): " +
                         ", ".join(f"{o['set']} ({o['by_source']['tcgcsv']})" for o in resc))
        if outs and any("elapsed_s" in o for o in outs):
            lines.append("Tempo por set: " + " | ".join(
                f"{o['set']} {o.get('elapsed_s', 0) / 60:.1f} min" for o in outs if "elapsed_s" in o))
        health = self._source_health_line()
        if health:
            lines.append(health)
        n = len(getattr(self, "unpriced_rows", []))
        if n:
            lines.append(f"{n} listings sem preço — ver aba 'Sem preço' do XLSX")
        nr = len(getattr(self, "noref_rows", []))
        if nr:
            por_set = {}
            for r in self.noref_rows:
                por_set[r["set"]] = por_set.get(r["set"], 0) + 1
            lines.append(f"{nr} ofertas SEM REFERÊNCIA COMPATÍVEL (edição/acabamento sem preço; sem "
                         f"margem, nada a recomendar) — aba 'Sem Ref Compatível': " +
                         ", ".join(f"{k} ({v})" for k, v in sorted(por_set.items())))
        return lines

    def _enrich_validation(self, o: "Opportunity", listings) -> None:
        """Valida UMA oportunidade contra os listings per-blueprint já buscados."""
        seller = o.listing.seller_username
        o.validated_at, o.validation_reused = now_iso(), False
        if listings is None:
            o.validation_status = "API_ERROR"
            return
        # v2.19 (2026-06-21): casar o listing per-blueprint pela MESMA
        # condição (NM) E mesmo reverse/variante do listing que o scan achou
        # — não só pelo vendedor. Antes pegava o PRIMEIRO listing do vendedor
        # (qualquer condição/variante): um vendedor com uma cópia Poor barata
        # OU a versão não-reverse "contaminava" a validação. Caso real
        # Shiftry hl: scan achou a NM reverse (~R$140), mas a validação casava
        # a Poor não-reverse do mesmo vendedor (R$46,46) → comparava preço de
        # carta Poor contra referência reverse → falso "79%". Agora exige
        # condition == o.listing.condition (Near Mint) e reverse igual; entre
        # os que batem, pega o MAIS BARATO (melhor oferta daquele vendedor
        # naquela exata variante/condição). Se nenhum bate → STALE honesto
        # (a cópia exata que o scan viu sumiu), em vez de casar a errada.
        def _variant_matches(listing_dict) -> bool:
            p = (listing_dict.get("properties_hash")
                 or listing_dict.get("properties") or {})
            cond = p.get("condition", "")
            is_rev = (to_bool(p.get("pokemon_reverse", False))
                      or to_bool(p.get("mtg_foil", False))
                      or to_bool(p.get("foil", False)))
            return cond == o.listing.condition and is_rev == bool(o.listing.foil)

        def _props(listing_dict) -> dict:
            return listing_dict.get("properties_hash") or listing_dict.get("properties") or {}

        # B1: mesma EDIÇÃO além de condição+reverse. Oferta de outra edição NUNCA valida.
        same_variant = [l for l in listings
                        if (l.get("user") or {}).get("username") == seller and _variant_matches(l)]
        # sem a chave `first_edition` no payload per-blueprint não há como confirmar a edição
        # (quando a oferta é 1st, ou quando a chave veio no scan e sumiu aqui)
        needs_key = o.listing.first_edition or o.listing.first_edition_known
        unconfirmable = [l for l in same_variant if "first_edition" not in _props(l)] if needs_key else []
        seller_matches = [l for l in same_variant
                          if ("first_edition" in _props(l)
                              and to_bool(_props(l)["first_edition"]) == bool(o.listing.first_edition))
                          or ("first_edition" not in _props(l) and not needs_key)]
        if not seller_matches and unconfirmable:
            o.validation_status = "NAO_CONFIRMAVEL"
            o.validation_reason = ("endpoint per-blueprint não traz `first_edition`: a edição "
                                   "da oferta não pôde ser confirmada (não validada por oferta de outra edição)")
            return
        match = (min(seller_matches, key=lambda l: l.get("price_cents", float("inf")))
                 if seller_matches else None)
        if not match:
            # STALE: vendedor não tem mais a cópia na MESMA condição+variante
            # que o scan achou (ou só tinha outra condição/variante).
            o.validation_status = "STALE"
            return
        # Live BRL (per-blueprint sempre retorna na moeda da conta = BRL pra Matheus,
        # mas tratamos as 3 moedas pra robustez)
        live_cents = match.get("price_cents", 0)
        live_currency = (match.get("price_currency") or "BRL").upper()
        if live_currency == "BRL":
            live_brl = live_cents / 100.0
        elif live_currency == "EUR":
            live_brl = (live_cents / 100.0) * self.eur_brl
        elif live_currency == "USD":
            live_brl = (live_cents / 100.0) * self.usd_brl
        else:
            o.validation_status = "API_ERROR"
            return

        o.live_price_brl = live_brl
        markup = (live_brl - o.ct_price_brl) / o.ct_price_brl if o.ct_price_brl > 0 else 0.0
        o.markup_pct = markup
        # Classificação tier (com base no padrão observado 2026-04-29 e refinado 2026-05-11)
        if markup < 0.02:
            o.markup_tier = "Real (sem markup)"
            o.validation_status = "VALIDATED_REAL"
        elif markup < 0.12:
            o.markup_tier = "Hub (+6%)"
            o.validation_status = "VALIDATED_MARKUP"
        elif markup < 0.30:
            o.markup_tier = "non-VAT (+20%)"
            o.validation_status = "VALIDATED_MARKUP"
        elif markup < 0.45:
            # 2026-05-11: tiers 30-45% (TheDragonsVault, A2Z TCG, Fun Gs)
            # parecem legítimos — provavelmente non-Hub VAT-exempt ou
            # categoria comissionada alta. Validados, não erro de preço.
            o.markup_tier = f"Alto markup ({markup*100:+.0f}%)"
            o.validation_status = "VALIDATED_MARKUP"
        else:
            # markup ≥45% — provavelmente preço mudou entre scan e validate
            o.markup_tier = f"Anômalo ({markup*100:+.0f}%)"
            o.validation_status = "PRICE_CHANGED"

        # Recalc margens com preço LIVE (per-blueprint, preço de checkout).
        # v2.12 (2026-06-06): custo real = live_brl × (1 + hub_fee_rate). Com
        # hub_fee_rate default 0.0, custo = live_brl → margens REAIS são BRUTAS
        # `(tcg − live)/tcg`. Operador soma Hub fee/frete/cartão/IOF por fora.
        # (--hub-fee 0.06 reembute os 6% históricos.) Alinha com postprocess.
        # D8: preço LIVE do checkout JÁ embute o Hub (compra_inclui_hub=True) — nunca 2×.
        econ = compute_economics(o.tcg_market_brl, live_brl, compra_inclui_hub=True,
                                 costs=self._costs())
        o.real_margin_pct = econ.margem_venda
        o.real_net_margin_pct = econ.margem_liquida_venda
        o.real_lucro_brl = econ.lucro_liquido

    def validate_per_blueprint(self, opps: list[Opportunity],
                               top_n: Optional[int] = None,
                               checkpoint: Optional["CheckpointWriter"] = None) -> None:
        """Fase 3 / v2.0 — Valida candidatos via endpoint per-blueprint.

        Lote 3: `top_n=None` (padrão e canônico) valida TODAS as oportunidades
        elegíveis; um inteiro limita aos N de maior margem bruta (quem quiser).

        A API CT retorna preços diferentes nos endpoints per-expansion (RAW do
        seller, sem markup) e per-blueprint (preço FINAL com markup CT embutido,
        +6% tier Hub ou +20% tier non-VAT). O scanner usa per-expansion por
        eficiência (1 chamada por set vs 1 por carta), mas isso infla margens
        em 5-20% vs o preço que o comprador realmente paga.

        Esta validação faz chamadas per-blueprint pros top N por margem bruta,
        encontra o seller correspondente, e enriquece a Opportunity com:
          - live_price_brl (preço REAL com markup)
          - markup_pct, markup_tier (Hub +6% / non-VAT +20% / anômalo)
          - real_margin_pct, real_net_margin_pct, real_lucro_brl
          - validation_status (VALIDATED_REAL, VALIDATED_MARKUP, STALE,
            PRICE_CHANGED, API_ERROR)

        Mutate in place. Não filtra — caller decide threshold via min_net_margin.
        """
        if not opps:
            return
        # Top N por margem bruta (a mesma ordem do scan default)
        sorted_opps = sorted(opps, key=lambda o: o.margin_pct, reverse=True)
        candidates = sorted_opps if top_n is None else sorted_opps[:top_n]
        unique_bp_ids = {o.listing.blueprint_id for o in candidates}
        log.info(f"v2.0: validando top {len(candidates)} candidatos ({len(unique_bp_ids)} blueprints únicos) per-blueprint...")

        # Lote 3c: retomada SÓ com --resume-validation, de run que não terminou,
        # com a MESMA oferta e a MESMA referência; o resto vai à API.
        cached = checkpoint.load_validations(VALIDATION_RESUME_MAX_AGE_H) if checkpoint else {}
        reused = 0
        by_bp: dict[int, list[Opportunity]] = {}
        for o in candidates:
            rec = cached.get(validation_key(o))
            if rec and validation_record_matches(o, rec):
                apply_validation_record(o, rec, reused=True)
                reused += 1
                if checkpoint is not None:   # o checkpoint NOVO também carrega (retomável de novo)
                    checkpoint.write_validation(o)
            else:
                by_bp.setdefault(o.listing.blueprint_id, []).append(o)
        if reused:
            log.info(f"Validação per-blueprint: {reused} candidatos reaproveitados do "
                     f"checkpoint (≤ {VALIDATION_RESUME_MAX_AGE_H}h); {len(candidates) - reused} a validar")

        total_bp = len(by_bp)
        errors = 0
        done = reused
        rl0 = getattr(self.ct, "rate_limit_hits", 0)
        rl0 = rl0 if isinstance(rl0, (int, float)) else 0
        for n, (bp_id, group) in enumerate(by_bp.items(), 1):
            try:
                listings = self.ct.list_listings_by_blueprint(bp_id, language=self.language)
                if isinstance(listings, dict):
                    listings = [l for sub in listings.values() for l in sub]
            except Exception as e:
                log.warning(f"v2.0: per-blueprint falhou bp={bp_id}: {e}")
                listings = None
                errors += 1
            for o in group:
                self._enrich_validation(o, listings)
                done += 1
                # API_ERROR não é gravado: numa retomada o candidato é refeito.
                if checkpoint is not None and o.validation_status != "API_ERROR":
                    checkpoint.write_validation(o)
            if n % VALIDATION_PROGRESS_EVERY == 0 or n == total_bp:
                rl = getattr(self.ct, "rate_limit_hits", 0)
                rl = (rl if isinstance(rl, (int, float)) else 0) - rl0
                log.info(f"Validação per-blueprint: {n}/{total_bp} blueprints | "
                         f"{done}/{len(candidates)} candidatos | erros {errors} | 429 {int(rl)}")

        if checkpoint is not None:
            checkpoint.write_validation_complete()

        # Stats sumarizadas
        validated_real = sum(1 for o in candidates if o.validation_status == "VALIDATED_REAL")
        validated_markup = sum(1 for o in candidates if o.validation_status == "VALIDATED_MARKUP")
        stale = sum(1 for o in candidates if o.validation_status == "STALE")
        log.info(f"v2.0: {validated_real} REAL, {validated_markup} com markup, {stale} STALE, {len(candidates) - validated_real - validated_markup - stale} outros")
        self.stats["v2_validated"] = validated_real + validated_markup
        self.stats["v2_stale"] = stale


# ══════════════════════════════════════════════════════════════════════
# EXCEL EXPORT — openpyxl para compatibilidade com MYP scanner.
# Layout:
#   - Aba "Oportunidades": uma linha por deal, ordenado por margem desc
#   - Aba "Stats": métricas da execução (funnel de filtragem)
# Formatação condicional: margem >= 40% fica verde forte, <30% vermelho.
# ══════════════════════════════════════════════════════════════════════
VALIDATION_RESUME_MAX_AGE_H = 3   # validação gravada há mais que isso não é reaproveitada
VALIDATION_PROGRESS_EVERY = 25    # blueprints entre linhas de progresso


def validation_key(o: "Opportunity") -> str:
    return validation_key_from(o.listing.product_id, o.listing.seller_username,
                               o.listing.first_edition, o.listing.foil)


def validation_key_from(product_id, seller, first_edition, reverse) -> str:
    """Chave de validação: oferta + edição + reverse (1st/Unlimited e reverse/normal do mesmo
    vendedor nunca compartilham uma validação)."""
    return (f"{product_id}:{seller}:{'1st' if to_bool(first_edition) else 'unl'}:"
            f"{'rev' if to_bool(reverse) else 'std'}")


def validation_key_from_record(rec: dict) -> str:
    return validation_key_from(rec.get("product_id"), rec.get("seller"),
                               rec.get("first_edition"), rec.get("reverse"))


def validation_record_matches(o: "Opportunity", rec: dict) -> bool:
    """Lote 3c: um registro só vale para ESTA oferta se o preço da oferta e a
    referência forem idênticos aos da validação (registro sem eles = não vale)."""
    try:
        return (abs(float(rec["offer_price_brl"]) - o.ct_price_brl) < 0.005
                and abs(float(rec["ref_brl"]) - o.tcg_market_brl) < 0.005)
    except (KeyError, TypeError, ValueError):
        return False


def apply_validation_record(o: "Opportunity", rec: dict,
                            reused: Optional[bool] = None) -> None:
    """Aplica um registro `validation` do checkpoint à Opportunity, com a
    data/hora ORIGINAL da validação. `reused=True` marca a linha como
    REAPROVEITADA de outro run; recovery do próprio checkpoint usa o que o
    registro diz."""
    o.validated_at = rec.get("validated_at") or ""
    o.validation_reused = bool(rec.get("reused", False)) if reused is None else reused
    o.validation_status = rec.get("validation_status", o.validation_status)
    o.validation_reason = rec.get("validation_reason") or ""
    o.live_price_brl = rec.get("live_price_brl")
    o.markup_pct = rec.get("markup_pct")
    o.markup_tier = rec.get("markup_tier")
    o.real_margin_pct = rec.get("real_margin_pct")
    o.real_net_margin_pct = rec.get("real_net_margin_pct")
    o.real_lucro_brl = rec.get("real_lucro_brl")


def apply_validation_filters(opps: list[Opportunity], min_net_margin: float):
    """B1c: o scanner NÃO descarta linha nenhuma por margem depois de validar — toda oferta
    validada vai ao XLSX com o preço real e o status; quem classifica é o postprocess (corte único).
    `--min-net-margin` só MARCA: devolve (todas, marcadas) — marcadas = validadas com líquida real
    abaixo do valor — e loga. Retorna (mantidas = todas, marcadas)."""
    validated = ("VALIDATED_REAL", "VALIDATED_MARKUP")
    marked = [o for o in opps if min_net_margin > 0 and o.validation_status in validated
              and (o.real_net_margin_pct or 0) < min_net_margin]
    by_status: dict[str, int] = {}
    for o in opps:
        by_status[o.validation_status] = by_status.get(o.validation_status, 0) + 1
    log.info(f"Validação: {len(opps)} oportunidades mantidas por status: {by_status}")
    if marked:
        names = "; ".join(
            f"{o.listing.card_name} ({o.listing.set_code} {o.listing.collector_number}) "
            f"net real {(o.real_net_margin_pct or 0):.0%}" for o in marked)
        log.info(
            f"--min-net-margin {min_net_margin:.0%}: {len(marked)} oportunidade(s) validada(s) com "
            f"líquida real abaixo do valor (apenas MARCADAS; seguem no XLSX, o postprocess classifica): {names}")
    return list(opps), marked


def _liquid_label(opp: "Opportunity", hub_fee_rate: float) -> tuple:
    """('PARCIAL'|'DEFINITIVA', custos não informados). Só Hub + frete têm valor; o resto é
    "não informado" -> a líquida é SEMPRE parcial (mesma regra do postprocess)."""
    try:
        econ = compute_economics(1.0, 1.0, compra_inclui_hub=opp.live_price_brl is not None,
                                 costs=Costs(hub_fee_rate=hub_fee_rate))
    except (ValueError, TypeError):
        econ = compute_economics(1.0, 1.0, compra_inclui_hub=opp.live_price_brl is not None)
    return ("DEFINITIVA" if econ.liquida_definitiva else "PARCIAL", ", ".join(econ.custos_nao_informados))


def export_xlsx(opportunities: list[Opportunity], stats: dict,
                out_path: Path, usd_brl: float, eur_brl: float,
                threshold: float, hub_fee_rate: float = 0.06,
                unpriced: Optional[list] = None,
                noref: Optional[list] = None) -> Path:
    wb = Workbook()

    # Aba 1: Oportunidades
    ws = wb.active
    ws.title = "Oportunidades"

    headers = [
        "Card Name", "Set", "Nº", "Rarity", "Condição", "Idioma",
        "Scan R$ (raw)", "Moeda Original CT", "LIVE R$ (real)", "Markup %", "Markup Tier",
        "Validation Status",
        "TCG Market (BRL)", "TCG Market (USD)",
        "Margem % (scan)", "Margem % REAL", "Net Margin % (scan)", "Net Margin % REAL",
        "Lucro R$ REAL", "Frete Est. R$",
        "Qtd", "Foil",
        # v2.8 Layer 4 (2026-05-18): variante TCGPlayer usada no cálculo.
        # Operador valida: foil-listing deve casar com `holofoil`; non-foil
        # com `reverseHolofoil` na maioria dos Holo Rare antigos. Mismatch
        # entre Foil="No" e Variant="holofoil" indica preço inflado.
        "Variant",
        "Seller", "Tipo Seller", "Hub",
        # v2.7.1 (2026-05-18): Link TCG — URL TCGPlayer da carta exata
        # matched no pokemontcg.io. Operador valida variante (ex Lusamine 1st Place
        # vs normal) antes de comprar. Vazio quando provider != pokemontcg ou
        # card sem entry TCGPlayer (Promos antigos comum).
        "Link CardTrader", "Link TCG", "Scanned At",
        # v2.13 — frentes "chase" e "valorização". APPEND no fim (não realocar
        # colunas existentes: os testes de coerência checam índices fixos 6-19,
        # 26, 27). Chase Tier = raridade top (TOP/MID/MODEST/BULK). Desconto %
        # = margem bruta repetida com rótulo do ranking de chase. Valorização =
        # score heurístico 0-100 (rarity + idade do set + preço) + notas.
        "Chase Tier", "Desconto %", "Score heurístico (raridade+idade+preço, 0-100)", "Valorização — Notas",
        # v2.14 (candidato 4): flag de baixa confiança de variante. APPEND no
        # FIM (não realocar — testes de coerência checam índices fixos).
        "Variante Baixa Confiança",
        # v2.23: FONTE do preço de referência (pokemontcg vs tcgcsv). APPEND no
        # FIM. Honestidade real-vs-fonte: "tcgcsv" = preço de fallback (set que a
        # pokemontcg.io não precificava, ex.: asc); "pokemontcg" = caminho padrão.
        "Fonte Preço",
        # Lote 3: data/hora em que a referência foi obtida NESTE run (APPEND).
        "Ref. Data/Hora",
        # Lote 3c: quando a validação per-blueprint foi feita e se foi
        # reaproveitada de um run interrompido (APPEND no fim).
        "Validado em", "Validação",
        # B1: variante da oferta/referência (contrato com o postprocess). `Ref Compatível`
        # = Sim só com Match OK de par IDÊNTICO ao da oferta; a chave usada = coluna `Variant`.
        "Edição", "Acabamento", "Ref Compatível", "Motivo Validação",
        # B1b: data do DADO da referência + rótulo ("dado de" | "buscado em"); a margem líquida
        # usa só Hub + frete -> sempre PARCIAL, com a lista dos custos não informados.
        "Data Ref.", "Rótulo Data Ref.", "Líquida", "Custos Não Informados",
    ]
    ws.append(headers)

    for opp in opportunities:
        l = opp.listing
        ws.append([
            l.card_name,
            f"{l.set_name} ({l.set_code})",
            l.collector_number,
            l.rarity,
            l.condition,
            l.language.upper(),
            round(opp.ct_price_brl, 2),
            l.price_currency,
            round(opp.live_price_brl, 2) if opp.live_price_brl is not None else None,
            round(opp.markup_pct, 4) if opp.markup_pct is not None else None,
            opp.markup_tier or "",
            opp.validation_status,
            round(opp.tcg_market_brl, 2),
            round(opp.tcg_market_usd, 2),
            round(opp.margin_pct, 4),
            round(opp.real_margin_pct, 4) if opp.real_margin_pct is not None else None,
            round(opp.net_margin_pct, 4),
            round(opp.real_net_margin_pct, 4) if opp.real_net_margin_pct is not None else None,
            round(opp.real_lucro_brl, 2) if opp.real_lucro_brl is not None else None,
            round(opp.estimated_shipping_brl, 2),
            l.quantity,
            "Yes" if l.foil else "No",
            opp.price_variant_used or "",
            l.seller_username,
            l.seller_user_type,
            "Yes" if l.seller_can_sell_via_hub else "No",
            l.cardtrader_url,
            opp.tcg_url or "",
            opp.scanned_at,
            # v2.13 — chase + valorização (colunas append, índices 29-32 0-based)
            opp.chase_tier or "",
            round(opp.margin_pct, 4),  # Desconto % (= margem bruta, rótulo chase)
            opp.valorization_score,
            opp.valorization_note or "",
            # v2.14 (candidato 4): "Sim" só quando non-foil casou variante holo.
            "Sim" if opp.variant_low_confidence else "",
            # v2.23: fonte do preço (proveniência). Default "pokemontcg".
            opp.price_source or "",
            opp.price_fetched_at or "",
            opp.validated_at or "",
            ("reaproveitada" if opp.validation_reused
             else "nova" if opp.validated_at else ""),
            {ct_variants.ED_1ST: "1st Edition", ct_variants.ED_UNL: "Unlimited",
             ct_variants.ED_NONE: ct_variants.ED_NONE_LABEL}.get(opp.edition, ""),
            ct_variants.FIN_LABELS.get(opp.finish, ""),
            ("" if opp.edition is None else ("Sim" if opp.ref_compatible else "Não")),
            opp.validation_reason or "",
            opp.ref_data_at or "", opp.ref_data_label or "",
            *_liquid_label(opp, hub_fee_rate),
        ])

    # ─── Formatação ───
    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    border = Border(*(Side(border_style="thin", color="D1D5DB"),) * 4)

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Larguras de coluna ajustadas à leitura
    # v2.8 Layer 4: nova coluna Variant inserida entre Foil e Seller
    widths = [
        28, 28, 8, 12, 8,         # A-E: card/set/num/cond/idioma
        12, 10, 12, 9, 18,        # F-J: scan/moeda/live/markup%/markup_tier
        18,                       # K: validation_status
        14, 14,                   # L-M: TCG BRL/USD
        12, 12, 12, 16,           # N-Q: margem scan/real/net scan/net REAL
        12, 10,                   # R-S: lucro REAL / frete
        6, 6,                     # T-U: qtd/foil
        18,                       # V: variant (holofoil/reverseHolofoil/normal)
        20, 14, 6,                # W-Y: seller/tipo/hub
        40, 40, 18,               # Z-AB: link CT / link TCG / scanned_at
        # v2.13 — AC-AF: chase tier / desconto% / valorização / notas
        12, 11, 16, 60,
    ]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Formato número/percentual/moeda
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = border
        # Colunas monetárias (índices 0-based)
        # v2.8 Layer 4: índices corrigidos após inserção da coluna "Idioma"
        # (idx 5). O bloco anterior estava todo -1 (escrito pré-Idioma).
        row[6].number_format = '"R$"#,##0.00'   # G: Scan R$ (raw)
        row[8].number_format = '"R$"#,##0.00'   # I: LIVE R$ (real)
        row[9].number_format = "0.00%"          # J: Markup %
        row[12].number_format = '"R$"#,##0.00'  # M: TCG Market BRL
        row[13].number_format = "$#,##0.00"     # N: TCG Market USD
        row[14].number_format = "0.00%"         # O: Margem % (scan)
        row[15].number_format = "0.00%"         # P: Margem % REAL
        row[16].number_format = "0.00%"         # Q: Net Margin % (scan)
        row[17].number_format = "0.00%"         # R: Net Margin % REAL
        row[18].number_format = '"R$"#,##0.00'  # S: Lucro R$ REAL
        row[19].number_format = '"R$"#,##0.00'  # T: Frete Est. R$
        # v2.13: Desconto % (idx30 0-based) — formato percentual. Demais novas
        # colunas (Chase Tier idx29, Valorização idx31 int, Notas idx32 texto)
        # ficam no formato geral.
        if len(row) > 30:
            row[30].number_format = "0.00%"
        # v2.8 Layer 4: nova coluna Variant inserida entre Foil e Seller.
        # Headers atuais (29 cols): ... "Foil"(22), "Variant"(23), "Seller"(24),
        # "Tipo Seller"(25), "Hub"(26), "Link CardTrader"(27), "Link TCG"(28),
        # "Scanned At"(29). 0-based: 26=Link CT, 27=Link TCG.
        # Apenas quando célula tem URL não-vazia.
        link_font = Font(color="0563C1", underline="single")
        for col_0 in (26, 27):  # 0-based: Link CardTrader, Link TCG
            if col_0 < len(row):
                cell = row[col_0]
                v = cell.value
                if isinstance(v, str) and v.startswith("http"):
                    cell.hyperlink = v
                    cell.font = link_font

    # Freeze header + filtro
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # Formatação condicional na coluna Net Margin REAL (R, idx17): verde forte
    # = oportunidade real. Antes apontava p/ Q (Net Margin % scan, otimista
    # pré-validação) — bug de off-by-one igual ao bloco de number_format.
    if ws.max_row > 1:
        ws.conditional_formatting.add(
            f"R2:R{ws.max_row}",
            ColorScaleRule(
                start_type="num", start_value=0, start_color="FEE2E2",
                mid_type="num", mid_value=0.15, mid_color="FEF3C7",
                end_type="num", end_value=0.30, end_color="86EFAC",
            ),
        )

    # Lote 3: listings SEM preço (sem cobertura / falha operacional / não
    # alcançados) — nada some em silêncio; aba só existe quando há linhas.
    if noref:
        wsn = wb.create_sheet("Sem Ref Compatível")
        wsn.append(["Card Name", "Set", "Nº", "Rarity", "Edição", "Acabamento",
                    "Scan R$ (raw)", "Moeda", "Qtd", "Seller", "Link CardTrader", "Link TCG",
                    "Fonte Preço", "Motivo", "Chaves disponíveis", "Status Ref"])
        for r in noref:
            wsn.append([r.get("card"), f"{r.get('set_name')} ({r.get('set')})", r.get("number"),
                        r.get("rarity"), r.get("edicao"), r.get("acabamento"),
                        r.get("ct_price_brl"), r.get("currency"), r.get("qty"), r.get("seller"),
                        r.get("link"), r.get("tcg_url"), r.get("source"), r.get("motivo"),
                        r.get("chaves"), r.get("status")])
        for cell in wsn[1]:
            cell.fill = header_fill
            cell.font = header_font
    if unpriced:
        ws3 = wb.create_sheet("Sem preço")
        ws3.append(["Set", "Nome do set", "Carta", "Nº", "CT R$", "Seller",
                    "Link CardTrader", "Motivo", "Detalhe", "Qtd", "Edição", "Acabamento"])
        for r in unpriced:
            ws3.append([r.get("set"), r.get("set_name"), r.get("card"), r.get("number"),
                        r.get("ct_price_brl"), r.get("seller"), r.get("link"),
                        r.get("reason"), r.get("detail"), r.get("qty"), r.get("edicao"),
                        r.get("acabamento")])
        for cell in ws3[1]:
            cell.fill = header_fill
            cell.font = header_font

    # Aba 2: Stats (auditoria do funnel)
    ws2 = wb.create_sheet("Stats")
    ws2.append(["Métrica", "Valor"])
    for k, v in stats.items():
        ws2.append([k, v])
    ws2.append(["usd_brl_rate", round(usd_brl, 4)])
    ws2.append(["eur_brl_rate", round(eur_brl, 4)])
    ws2.append(["threshold_margin", f"{threshold:.0%}"])
    ws2.append(["hub_fee_rate", f"{hub_fee_rate:.0%}"])
    ws2.append(["margin_basis", "margem sobre a VENDA (ct_economics); Hub só nas colunas líquidas"])
    ws2.append(["scanned_at", now_iso()])
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 20
    for cell in ws2[1]:
        cell.fill = header_fill
        cell.font = header_font

    # Garante o diretório-alvo antes de salvar: outputs/ é gitignored e NÃO vem
    # num clone limpo (sessão Claude Code na nuvem) — sem isto o wb.save() quebra
    # com FileNotFoundError DEPOIS de um rastreio inteiro (horas), perdendo tudo.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    log.info(f"✓ Planilha salva: {out_path}")
    return out_path


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser(
        description="CardTrader Arbitrage Scanner — Pokémon TCG Singles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sets", nargs="*", help="Códigos de expansão CT (ex: sv1 sv3pt5). Default: todas do config.yaml")
    p.add_argument("--all-sets", action="store_true",
                   help=("Escaneia TODAS as expansões Pokemon do CardTrader (~832), "
                         "ignorando tanto --sets quanto a lista 'sets' do config.yaml. "
                         "Use para o scan COMPLETO (weekly). Sem esta flag e sem --sets, "
                         "o escopo cai na lista do config.yaml."))
    p.add_argument("--skip-backcatalog", action="store_true",
                   help=("Escaneia só as coleções modernas/curadas (PRIORITY_SET_CODES), "
                         "pulando o back-catalog (mercado eficiente, ~0 deal acionável). "
                         "Mais útil com --all-sets: corta ~832 → ~30 sets. Combinado com "
                         "--sets, intersecta com a lista do usuário."))
    p.add_argument("--vintage", action="store_true",
                   help=("Escaneia a lista CURADA vintage core (VINTAGE_SET_CODES): "
                         "WOTC + e-Card + EX Series completa (~34 sets). Onde mora o "
                         "gap de arbitragem vintage (holo rares era EX/Neo). Restringe "
                         "o escopo a essas coleções, na ordem curada. Mutuamente "
                         "exclusivo com --skip-backcatalog."))
    p.add_argument("--threshold", type=float, default=MARGIN_THRESHOLD,
                   help=f"Margem mínima bruta (default: {MARGIN_THRESHOLD})")
    p.add_argument("--min-price-usd", type=float, default=MIN_PRICE_USD,
                   help=f"Preço mínimo por carta em USD (default: {MIN_PRICE_USD})")
    p.add_argument("--language", type=str, default=LANGUAGE_FILTER,
                   help=("v2.29: idioma das OFERTAS no CT (properties_hash."
                         "pokemon_language). Default 'en' (comportamento "
                         "histórico). Valores reais vistos na API: en, it, de, "
                         "fr, es, pt, zh-CN. ⚠️ A referência TCGplayer continua "
                         "sendo a carta INGLESA: com idioma ≠ en a 'margem' é "
                         "razão de preço EN/<idioma>, não margem de revenda — "
                         "entregue com `cardtrader_postprocess.py --ratio-column`."))
    p.add_argument("--include-graded", action="store_true",
                   help="Incluir cartas graded (PSA/BGS/CGC). Default: excluir")
    p.add_argument("--provider", choices=list(PROVIDERS.keys()), default="pokemontcg",
                   help=("Fonte de preços TCG (default: pokemontcg). v2.26: "
                         "'tcgcsv' usa o tcgcsv.com como fonte PRIMÁRIA (bulk "
                         "por set, mesma escada de variante, sem key) — útil "
                         "quando a pokemontcg.io degrada com 500/502. Set que "
                         "não resolver no tcgcsv sai sem referência de preço "
                         "(sem skip-list), nunca com preço inventado."))
    p.add_argument("--no-tcgcsv-fallback", action="store_true",
                   help=("v2.23: DESLIGA o fallback tcgcsv.com. Por padrão "
                         "(omitido), quando a pokemontcg.io não precifica um SET "
                         "inteiro (ex.: asc/Ascended Heroes — set fica INVISÍVEL "
                         "sem isso), o scanner consulta o tcgcsv pra preencher SÓ "
                         "esse buraco (com a MESMA seleção de variante e validação "
                         "per-blueprint). Sets que a pokemontcg.io já precifica "
                         "NÃO mudam. Use esta flag pra desabilitar o fallback."))
    p.add_argument("--output", "-o", type=str, default=None,
                   help="Arquivo de saída .xlsx (default: cardtrader_scan_<timestamp>.xlsx)")
    p.add_argument("--dry-run", action="store_true",
                   help="Usa só cache, não chama APIs (debug)")
    p.add_argument("--no-cache", action="store_true",
                   help="Limpa caches voláteis (preços TCG + FX) antes de rodar — força refresh em janelas de arbitragem urgente")
    p.add_argument("--max-expansions", type=int, default=None,
                   help="Limita o número de expansões (teste rápido)")
    p.add_argument("--validate-top", type=int, default=None,
                   help=("v2.0 / Lote 3: valida via per-blueprint (preço REAL com markup CT). "
                         "PADRÃO (omitido) = TODAS as oportunidades elegíveis. "
                         "N = só as N de maior margem bruta; 0 = desativa a validação."))
    p.add_argument("--resume-validation", action="store_true",
                   help=("Lote 3c: retoma a validação per-blueprint de um run INTERROMPIDO "
                         "(mesmo --output/--state-dir): reaproveita só o que foi validado "
                         f"há ≤ {VALIDATION_RESUME_MAX_AGE_H}h com a MESMA oferta e a MESMA referência; linha "
                         "reaproveitada sai marcada. Sem a flag, todo run valida do zero."))
    p.add_argument("--min-net-margin", type=float, default=0.0,
                   help="B1c: SÓ MARCA (log + contador) as validadas com margem liq REAL < X; NÃO remove nenhuma "
                        "linha — o corte é único e fica no postprocess. Ex: 0.20")
    p.add_argument("--shipping-brl", type=float, default=0.0,
                   help="Frete fixo per-listing em BRL (default 0 — modelo de "
                        "consolidacao no Hub depot, frete dilui per-card). "
                        "Override pra simular envio direto: ex --shipping-brl 28.84")
    p.add_argument("--hub-fee", type=float, default=0.06,
                   help=("B1/D8: taxa do Hub (default 0.06) usada SÓ nas colunas LÍQUIDAS "
                         "informativas de preço CRU (ct_economics). A margem do corte "
                         "(--threshold) é margem sobre a VENDA e NÃO depende desta flag; o preço "
                         "validado no checkout já embute o Hub (nunca contado duas vezes)."))
    # v2.4: per-set timeout + skip-list controls
    p.add_argument("--per-set-timeout", type=float, default=DEFAULT_PER_SET_TIMEOUT_MIN,
                   help=(f"v2.4: wall-clock timeout per set (minutos). Default "
                         f"{DEFAULT_PER_SET_TIMEOUT_MIN}. Quando excedido durante pricing loop, "
                         f"set é abortado e adicionado à skip-list. 0 = desativado."))
    p.add_argument("--no-source-breaker", action="store_true",
                   help="B1e: desliga o disjuntor da fonte principal (pokemontcg.io → tcgcsv em lote).")
    p.add_argument("--source-fail-rate", type=float, default=0.5,
                   help="B1e: taxa de falha de infra (FRAÇÃO, janela recente) que abre o disjuntor. Default 0.5.")
    p.add_argument("--source-slow-s", type=float, default=15.0,
                   help="B1e: latência média (s, janela recente) que abre o disjuntor. Default 15.")
    p.add_argument("--source-window", type=int, default=10,
                   help="B1e: tamanho da janela (ofertas). Mínimo de amostras = 60%% da janela. Default 10.")
    p.add_argument("--source-probe-s", type=float, default=120.0,
                   help="B1e: de quantos em quantos segundos testar se a fonte voltou. Default 120.")
    p.add_argument("--ignore-skip-list", action="store_true",
                   help="v2.4: ignora scanner_skip_list.json (retenta sets que travaram em runs anteriores).")
    # v2.13 (frente chase cards): filtra pra raridades top.
    p.add_argument("--chase-only", action="store_true",
                   help=("v2.13: só inclui chase cards — raridades TOP/MID "
                         "(Special/Hyper/Secret/Illustration Rare, alt/full art, "
                         "ultra/rainbow/gold rare). Corta common/uncommon/holo "
                         "comum. Mantém piso $10 e validação per-blueprint. "
                         "Output já vem ranqueado por desconto (margem desc)."))
    # v2.13 (frente eficiência): cap de misses consecutivos sem cobertura.
    p.add_argument("--max-consecutive-misses", type=int, default=0,
                   help=("v2.13: aborta um set após N listings consecutivos sem "
                         "preço na fonte (buraco de cobertura — sets 2026/mega "
                         "evolução) e o joga na skip-list. Evita moer centenas de "
                         "chamadas que sempre falham. 0 = desativado (default, "
                         "comportamento histórico). Sugestão p/ --all-sets: 40."))
    p.add_argument("--clear-skip-list", action="store_true",
                   help="v2.4: apaga scanner_skip_list.json antes de rodar (reset total).")
    # v2.22 (2026-06-22): contrato de entrega scanner→postprocess.
    p.add_argument("--opportunities-only", action="store_true",
                   help=("v2.22: comportamento LEGADO — escreve no XLSX só os "
                         "listings que batem o --threshold. Por padrão (omitido) "
                         "o scanner persiste TODO listing precificado, mesmo "
                         "abaixo do threshold, pra alimentar o fallback near-miss "
                         "do postprocess (a entrega nunca fica vazia quando há "
                         "≥1 precificado). Use só se quiser o XLSX enxuto."))
    # v2.6 (2026-05-17): partial JSONL checkpoint crash-recovery
    p.add_argument("--checkpoint-every", type=int, default=10,
                   help=("v2.6: emite checkpoint JSONL append-only a cada N sets "
                         "(default 10). 0 = desativado. Path: "
                         "<state-dir>/<output-name>.checkpoint.jsonl sidecar. "
                         "Crash mid-run não "
                         "perde mais dados — `scripts/recover_from_checkpoint.py "
                         "--checkpoint <path>` regenera XLSX equivalente."))
    # PR-F (2026-05-28): state dir + flush per-listing.
    p.add_argument("--state-dir", type=Path, default=None,
                   help=("v2.11 (PR-F): diretório de estado mutável (cache.db, "
                         "scanner_skip_list.json, heartbeat.txt, *.checkpoint.jsonl). "
                         "Default: %%LOCALAPPDATA%%/CardTraderScanner. Tira estado "
                         "volátil do Google Drive (evita conflitos de sync + lock). "
                         "O XLSX final continua indo pra --output."))
    p.add_argument("--flush-every-listings", type=int, default=50,
                   help=("v2.11 (PR-F): emite linha de telemetria set_progress + "
                         "heartbeat a cada N listings precificados (default 50). "
                         "Distinto de --checkpoint-every (que é por SET). Permite "
                         "detectar stall mid-set. 0 = desativado."))
    p.add_argument("--allow-concurrent", action="store_true",
                   help=("v2.14 (robustez): por padrão o scanner RECUSA iniciar se "
                         "já houver outra instância usando o MESMO state-dir "
                         "(lockfile scanner_run.lock). Dois scanners no mesmo "
                         "cache.db/skip-list disputam lock SQLite (throughput cai a "
                         "~9s/listing) e podem ENVENENAR a skip-list por timeout "
                         "falso. Passe esta flag pra rodar mesmo assim (ex.: "
                         "state-dirs diferentes que o guard não distingue, ou "
                         "diagnóstico). Use com cautela."))
    return p.parse_args()


# Sets de MAIOR PRIORIDADE (era Scarlet & Violet + curados do daily). No modo
# --all-sets, estes são escaneados PRIMEIRO — o catálogo CT vem em ordem
# old→new, e sem reordenar os sets modernos (foco da operação) ficariam no fim
# da fila, sob risco de serem cortados pelo timeout. Códigos que não existirem
# no catálogo simplesmente não casam (inócuo). Ordem aqui = ordem de scan.
PRIORITY_SET_CODES = [
    # Curados (daily) — códigos CardTrader
    "sfa", "scr", "par", "paf", "tef", "twm", "ssp", "dri", "blk", "jtg", "asc",
    # Scarlet & Violet (config.yaml) — sv1..sv10 + meio-sets
    "sv1", "sv2", "sv3", "sv3pt5", "sv4", "sv4pt5", "sv5", "sv6", "sv6pt5",
    "sv7", "sv8", "sv8pt5", "sv9", "sv10", "zsv10pt5", "me2pt5",
]


def filter_modern_sets(
    expansions: list[dict], priority_codes: list[str] = PRIORITY_SET_CODES
) -> list[dict]:
    """Mantém só as expansões cujo `code` está em `priority_codes` (modernas/
    curadas), descartando o back-catalog. É o suporte de `--skip-backcatalog`.

    Lição operacional (auditoria 2026-06-08): back-catalog = mercado eficiente
    = ~0 deal acionável; o gap de arbitragem mora em lançamentos novos. Função
    pura (sem rede) → testável offline. Preserva a ordem de entrada;
    case-insensitive; tolera `code` ausente/None.
    """
    prio = {c.lower() for c in priority_codes}
    return [e for e in expansions if (e.get("code") or "").lower() in prio]


# v2.21 (2026-06-21): lista CURADA "vintage core" — códigos CardTrader REAIS
# (verificados contra a API de expansões do CT em 2026-06-21, não os chutes do
# briefing: Base Set = `bs` (não `b1`); Southern Islands = `si` (não `si1`);
# Best of Game = `bog` (não `bp`); WOTC promos = `wiz` (não `basep`)). Cobre as
# 3 eras "vintage clássico": WOTC/Wizards, e-Card e EX Series completa (16 sets).
# Todos com alias pra pokemontcg.io em SET_ALIAS_TO_PTCG (ou code idêntico).
# Suporte da flag `--vintage`. NÃO inclui POP/DP/Platinum/HGSS (bucket separado,
# "early modern" — o briefing pediu pra não misturar no mesmo threshold).
VINTAGE_SET_CODES = [
    # WOTC / Wizards era
    "bs", "ju", "fo", "b2", "tr", "g1", "g2",
    "n1", "n2", "n3", "n4", "si", "lc", "wiz", "bog",
    # e-Card era
    "ex", "aq", "skg",
    # EX Series (16 main expansions: rs..pk, incluindo dr e df)
    "rs", "ss", "dr", "exma", "hl", "rg", "trr", "dx",
    "em", "uf", "ds", "lm", "hp", "cg", "df", "pk",
]


def filter_vintage_sets(
    expansions: list[dict], vintage_codes: list[str] = VINTAGE_SET_CODES
) -> list[dict]:
    """Mantém só as expansões cujo `code` está em `vintage_codes` (vintage core:
    WOTC + e-Card + EX Series). Suporte da flag `--vintage`.

    Espelha `filter_modern_sets` mas para o lado oposto do catálogo: o gap de
    arbitragem vintage mora na era EX + alguns Neo/WOTC holo rares (validado nos
    scans 2026-06-21). Função pura (sem rede) → testável offline. Preserva a
    ordem de `vintage_codes` (não a do catálogo), pra escanear na ordem curada.
    Case-insensitive; tolera `code` ausente/None.
    """
    order = {c.lower(): i for i, c in enumerate(vintage_codes)}
    matched = [e for e in expansions if (e.get("code") or "").lower() in order]
    matched.sort(key=lambda e: order[(e.get("code") or "").lower()])
    return matched


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def resolve_state_dir(state_dir_arg: Optional[Path]) -> Path:
    """PR-F (2026-05-28): resolve o diretório de estado MUTÁVEL.

    Precedência:
      1. --state-dir explícito (se passado).
      2. %LOCALAPPDATA%/CardTraderScanner (default em Windows).
      3. SCRIPT_DIR (fallback legado quando LOCALAPPDATA ausente — nunca
         quebra a inicialização em CI/não-Windows).

    NÃO cria o diretório (caller faz mkdir) — fica testável puro.
    """
    if state_dir_arg is not None:
        return Path(state_dir_arg)
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "CardTraderScanner"
    return SCRIPT_DIR


def main():
    args = parse_args()

    # Sanity check: --threshold e --min-net-margin são frações (0.30 = 30%).
    # Trap recorrente: usuário passa "25" achando que é percent → 2500%, scan
    # zera silenciosamente. Auto-converte com warning (2026-05-11 fix).
    if args.threshold > 1.0:
        log.warning(
            f"--threshold {args.threshold} > 1.0 parece percentual, "
            f"convertendo para fração: {args.threshold/100}"
        )
        args.threshold = args.threshold / 100.0
    if args.min_net_margin > 1.0:
        log.warning(
            f"--min-net-margin {args.min_net_margin} > 1.0 parece percentual, "
            f"convertendo para fração: {args.min_net_margin/100}"
        )
        args.min_net_margin = args.min_net_margin / 100.0
    # v2.3: mesma proteção para --hub-fee. Operador pode passar `6` ou `0.06`.
    if args.hub_fee > 1.0:
        log.warning(
            f"--hub-fee {args.hub_fee} > 1.0 parece percentual, "
            f"convertendo para fração: {args.hub_fee/100}"
        )
        args.hub_fee = args.hub_fee / 100.0

    load_dotenv(ENV_FILE)
    cfg = load_config()

    # PR-F (2026-05-28): resolve state dir. Tudo que é estado MUTÁVEL
    # (cache.db, skip-list, heartbeat, checkpoint JSONL) vive aqui — fora do
    # Google Drive, que causa lock-conflict + sync-conflict (.tmp/desktop.ini).
    # O XLSX final (out_path) continua indo pra --output (default SCRIPT_DIR).
    # Reaponta os globais CACHE_DB + SKIP_LIST_FILE pra que as 6 funções de
    # skip-list (que referenciam o nome do módulo em call-time) sigam o novo
    # path. ARMADILHA: Cache.__init__ tem db_path=CACHE_DB como DEFAULT-ARG
    # (bindado no import) — mudar o global não basta; passamos explícito abaixo.
    global CACHE_DB, SKIP_LIST_FILE
    state_dir = resolve_state_dir(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    CACHE_DB = state_dir / "cache.db"
    SKIP_LIST_FILE = skip_list_path(state_dir, args.language)
    log.info(f"State dir: {state_dir} | skip-list: {SKIP_LIST_FILE.name}")

    # v2.14 (robustez): run-guard contra instâncias concorrentes no mesmo
    # state-dir. Dois scanners no mesmo cache.db/skip-list disputam lock e
    # envenenam a skip-list por timeout falso (ver acquire_run_guard).
    run_guard = acquire_run_guard(state_dir)
    if run_guard is None:
        if args.allow_concurrent:
            log.warning(
                "⚠️  Outra instância parece estar usando este state-dir "
                f"({state_dir}). --allow-concurrent passado → seguindo mesmo "
                "assim. Risco: contenção de lock SQLite + skip-list envenenada."
            )
        else:
            log.error(
                f"💥 Já há um scanner rodando neste state-dir ({state_dir}). "
                "Dois scanners no mesmo cache.db/skip-list disputam lock "
                "(pricing despenca pra ~9s/listing) e podem ENVENENAR a "
                "skip-list por timeout falso. Aborte a outra instância, OU use "
                "--state-dir diferente, OU passe --allow-concurrent (com cautela)."
            )
            sys.exit(2)

    ct_jwt = _clean_secret(os.getenv("CT_JWT"))
    if not ct_jwt:
        log.error("CT_JWT não definido. Configure no arquivo .env")
        log.error("Como obter: CardTrader → Settings → API Access → Create New Token")
        sys.exit(1)

    # PR-F: db_path EXPLÍCITO (não confiar no default-arg bindado no import).
    cache = Cache(db_path=state_dir / "cache.db")
    if not args.dry_run:
        log.info("Nova coleta: renovando price_cache e fx_cache...")
        cache.begin_run()
    ct = CardTraderClient(ct_jwt)

    # Pricing provider
    provider_cls = PROVIDERS[args.provider]
    if args.provider == "pokemontcg":
        pricing = provider_cls(_clean_secret(os.getenv("POKEMONTCG_API_KEY")), cache)
    elif args.provider == "justtcg":
        pricing = provider_cls(_clean_secret(os.getenv("JUSTTCG_API_KEY")), cache)
    elif args.provider == "tcgcsv":
        # v2.26: tcgcsv como PRIMÁRIO. Sem key (fonte gratuita); o prefill
        # bulk por set acontece no scan_expansion (o provider sozinho não
        # sabe o mapa CT→ptcg codes do set).
        pricing = provider_cls(cache)
    else:
        pricing = provider_cls()
    log.info(f"Pricing provider: {pricing.name}")

    # v2.23: fonte de FALLBACK tcgcsv. Instanciada só quando o provider primário
    # é pokemontcg.io (a única fonte que sofre o buraco de cobertura por-set) E o
    # fallback não foi desligado. Compartilha o mesmo Cache. NUNCA roda pros sets
    # que a pokemontcg.io já precifica — só onde o set inteiro vem sem preço.
    tcgcsv_provider: Optional[TcgCsvFallbackProvider] = None
    tcgcsv_fallback_on = (args.provider == "pokemontcg" and not args.no_tcgcsv_fallback)
    if tcgcsv_fallback_on:
        tcgcsv_provider = TcgCsvFallbackProvider(cache)
        log.info("Fallback tcgcsv.com: HABILITADO (sets sem preço na "
                 "pokemontcg.io serão preenchidos via tcgcsv — ex.: asc)")
    elif args.no_tcgcsv_fallback:
        log.info("Fallback tcgcsv.com: DESLIGADO (--no-tcgcsv-fallback)")

    # Seleção de expansões
    log.info("Listando expansões Pokemon no CardTrader...")
    all_expansions = ct.list_expansions(CT_POKEMON_GAME_ID)
    log.info(f"Total: {len(all_expansions)} expansões")

    # --all-sets força o escopo COMPLETO: ignora --sets E a lista do config.yaml,
    # caindo no branch `else` abaixo (expansions = all_expansions ~832).
    # v2.21: --vintage e --skip-backcatalog são mutuamente exclusivos — as listas
    # VINTAGE_SET_CODES e PRIORITY_SET_CODES são DISJUNTAS, então combiná-las
    # produziria um scan vazio silencioso (footgun). Falha explícita.
    if getattr(args, "vintage", False) and args.skip_backcatalog:
        log.error(
            "--vintage e --skip-backcatalog são mutuamente exclusivos "
            "(vintage core e coleções modernas/curadas são conjuntos disjuntos → "
            "resultado vazio). Use um OU o outro."
        )
        sys.exit(2)

    sets_cfg = None if args.all_sets else (args.sets or cfg.get("sets"))
    if sets_cfg:
        wanted = {s.lower() for s in sets_cfg}
        expansions = [e for e in all_expansions if e.get("code", "").lower() in wanted]
        missing = wanted - {e.get("code", "").lower() for e in expansions}
        if missing:
            log.warning(f"Sets não encontrados: {missing}")
    else:
        expansions = all_expansions

    # v2.17: --skip-backcatalog restringe às coleções modernas/curadas
    # (PRIORITY_SET_CODES), pulando o back-catalog (mercado eficiente, ~0 deal).
    if args.skip_backcatalog:
        before = len(expansions)
        expansions = filter_modern_sets(expansions)
        log.info(
            f"--skip-backcatalog: {len(expansions)}/{before} expansões modernas "
            f"(puladas {before - len(expansions)} de back-catalog)"
        )

    # v2.21: --vintage restringe ao vintage core (VINTAGE_SET_CODES) na ordem
    # curada. Onde mora o gap vintage (holo rares era EX/Neo, validado 2026-06-21).
    # Escopo: sozinho filtra TODAS as expansões (não a lista modern do config);
    # com --sets explícito, intersecta com a lista do usuário.
    if getattr(args, "vintage", False):
        base = expansions if args.sets else all_expansions
        before = len(base)
        expansions = filter_vintage_sets(base)
        found = [e.get("code") for e in expansions]
        present = {(e.get("code") or "").lower() for e in expansions}
        missing = [c for c in VINTAGE_SET_CODES if c not in present]
        log.info(
            f"--vintage: {len(expansions)}/{before} expansões vintage core "
            f"(ordem curada). Sets: {', '.join(found)}"
            + (f" | NÃO encontrados no CT: {', '.join(missing)}" if missing else "")
        )

    # Reordena no escopo COMPLETO: sets de maior valor (SV/curados) PRIMEIRO.
    # O catálogo CT vem old→new; sem isso, os sets modernos (foco) ficariam no
    # fim e poderiam ser cortados pelo timeout. sort é estável → o resto mantém
    # a ordem do catálogo. Só afeta --all-sets (em --sets a ordem é do usuário).
    if args.all_sets and not getattr(args, "vintage", False):
        prio = {c.lower(): i for i, c in enumerate(PRIORITY_SET_CODES)}
        expansions.sort(key=lambda e: prio.get((e.get("code") or "").lower(), 10_000))
        matched = [e.get("code") for e in expansions if (e.get("code") or "").lower() in prio]
        log.info(
            f"Prioridade --all-sets: {len(matched)} sets curados/SV primeiro"
            + (f" ({', '.join(matched[:25])})" if matched else "")
        )

    if args.max_expansions:
        expansions = expansions[: args.max_expansions]
    log.info(f"Scan em {len(expansions)} expansões")

    # v2.4: gerencia skip-list antes de criar o Scanner
    if args.clear_skip_list:
        clear_skip_list()
    per_set_timeout_s = args.per_set_timeout * 60 if args.per_set_timeout and args.per_set_timeout > 0 else 0

    # Scanner
    scanner = Scanner(
        ct=ct,
        pricing=pricing,
        cache=cache,
        threshold=args.threshold,
        min_price_usd=args.min_price_usd,
        exclude_graded=not args.include_graded,
        shipping_brl_override=args.shipping_brl,
        hub_fee_rate=args.hub_fee,
        per_set_timeout_s=per_set_timeout_s,
        ignore_skip_list=args.ignore_skip_list,
        chase_only=args.chase_only,
        max_consecutive_misses=args.max_consecutive_misses,
        keep_all_priced=not args.opportunities_only,
        tcgcsv=tcgcsv_provider,
        tcgcsv_fallback=tcgcsv_fallback_on,
        language=args.language,
    )
    scanner.breaker = None if args.no_source_breaker else SourceBreaker(
        window=max(2, args.source_window), min_samples=max(2, round(0.6 * max(2, args.source_window))),
        fail_rate=args.source_fail_rate, slow_s=args.source_slow_s, probe_every_s=args.source_probe_s)
    if args.language.lower() != LANGUAGE_FILTER:
        log.warning(
            f"🌐 --language {args.language}: ofertas CT em '{args.language}', "
            f"referência TCGplayer da carta INGLESA → o número é RAZÃO de preço "
            f"EN/{args.language.upper()}, não margem de revenda."
        )

    # v2.6: resolve output_path ANTES de scan() pra calcular checkpoint sidecar.
    # XLSX final continua no --output (default SCRIPT_DIR / Drive). Só o JSONL
    # de checkpoint + heartbeat migram pro state_dir (PR-F).
    out_path = Path(args.output) if args.output else (
        SCRIPT_DIR / f"cardtrader_scan_{datetime.now():%Y%m%d_%H%M}.xlsx"
    )
    # PR-F: checkpoint sidecar vive no state_dir (fora do Drive), nomeado a
    # partir do XLSX final pra rastreabilidade (<output-name>.checkpoint.jsonl).
    checkpoint_path = state_dir / (out_path.name + ".checkpoint.jsonl")
    heartbeat_path = state_dir / "heartbeat.txt"
    checkpoint = CheckpointWriter(
        checkpoint_path,
        every_n=args.checkpoint_every,
        heartbeat_path=heartbeat_path,
        flush_every_listings=args.flush_every_listings,
        resume_validation=args.resume_validation,
    )
    if checkpoint.enabled:
        # Header com args dict pra reprodutibilidade no recovery.
        # v2.14: inclui FX do scan (usd_brl/eur_brl) pra o recovery reconstruir
        # a célula Stats usd_brl_rate (candidato 3).
        checkpoint.write_header(
            vars(args), total_sets=len(expansions),
            usd_brl=scanner.usd_brl, eur_brl=scanner.eur_brl,
        )

    t0 = time.time()
    try:
        opps = scanner.scan(expansions, checkpoint=checkpoint)
    finally:
        # Flush + close mesmo em exception. fsync já roda per-write.
        pass
    dt = time.time() - t0
    interrupted = bool(getattr(scanner, "interrupted", False))
    if checkpoint.enabled:
        if not interrupted:   # run interrompido NÃO é um run completo
            checkpoint.write_scan_complete(total_opps=len(opps), total_elapsed_s=dt)
        checkpoint.close()
    # v2.29 (revisão): `opps` aqui ainda inclui os near-miss persistidos (v2.22,
    # keep_all_priced) — contar só o que está ≥ threshold, senão o log diz
    # "11 oportunidades ≥ 75%" e logo abaixo "0 oportunidades ≥ 75%".
    n_real_opps = sum(1 for o in opps if not getattr(o, "below_threshold", False))
    log.info(f"Scan completo em {dt:.1f}s — {n_real_opps} oportunidades ≥ {args.threshold:.0%} "
             f"({len(opps) - n_real_opps} precificadas abaixo do threshold, persistidas como near-miss)")
    log.info(f"Margem do corte = margem sobre a VENDA (ct_economics): (ref − compra)/ref, sem taxa. "
             f"Hub {args.hub_fee:.0%} só nas colunas líquidas de preço cru (checkout validado já embute o Hub).")

    # v2.22 (2026-06-22): sob o contrato de entrega (keep_all_priced), os
    # near-misses (below_threshold=True) NÃO podem ser descartados pelos
    # filtros pós-validação, senão um scan sem deal acima do threshold volta a
    # esvaziar o XLSX → "nenhum listing precificado". Solução: a validação opera só no
    # SUBCONJUNTO de OPORTUNIDADES; os near-miss precificados ficam preservados como referência
    # pro fallback near-miss do postprocess. Em --opportunities-only (legado),
    # não há near-miss na lista, então o comportamento é idêntico ao antigo.
    near_misses = [o for o in opps if o.below_threshold] if scanner.keep_all_priced else []
    opps = [o for o in opps if not o.below_threshold] if scanner.keep_all_priced else opps

    # v2.0 — validação per-blueprint (Lote 3: de TODAS as oportunidades por
    # padrão; --validate-top N limita; 0 desliga). Só sobre as OPORTUNIDADES.
    if args.validate_top != 0 and opps and not interrupted:
        t1 = time.time()
        try:
            scanner.validate_per_blueprint(opps, top_n=args.validate_top, checkpoint=checkpoint)
            log.info(f"Validação per-blueprint completa em {time.time()-t1:.1f}s")
        except KeyboardInterrupt:
            interrupted = True
            log.error("Interrompido durante a validação — linhas ainda não validadas "
                      "ficam NOT_VALIDATED; XLSX parcial será escrito.")

        # Nenhuma linha sai aqui: --min-net-margin só MARCA (log + contador); o corte único
        # é do postprocess. Linhas não validadas ficam com o status real.
        opps, cut = apply_validation_filters(opps, args.min_net_margin)
        scanner.stats["opps_marcadas_min_net"] = len(cut)

        # M2 fix (2026-05-11): sempre re-ordena por margem líq REAL desc
        # quando houve validação, não só quando min_net_margin > 0.
        opps.sort(key=lambda o: o.real_net_margin_pct or -999, reverse=True)

    checkpoint.close()  # reaberto por write_validation/write_unpriced após o scan

    # v2.22: re-anexa os near-misses precificados (ordenados por margem bruta
    # desc) DEPOIS das oportunidades. Assim o XLSX nunca volta vazio quando há
    # ≥1 listing precificado, e o postprocess sempre tem dados pro near-miss.
    if near_misses:
        near_misses.sort(key=lambda o: o.margin_pct, reverse=True)
        if not opps:
            log.info(
                f"0 oportunidades ≥ {args.threshold:.0%}, mas {len(near_misses)} "
                f"listing(s) precificado(s) abaixo do threshold — persistidos no "
                f"XLSX como near-miss (entrega não fica vazia)."
            )
        opps = opps + near_misses

    # Export — out_path já resolvido acima (v2.6 fix: precisa antes do scan
    # pra calcular .checkpoint.jsonl sidecar)
    export_xlsx(opps, scanner.stats, out_path,
                usd_brl=scanner.usd_brl, eur_brl=scanner.eur_brl,
                threshold=args.threshold, hub_fee_rate=args.hub_fee,
                unpriced=getattr(scanner, "unpriced_rows", None),
                noref=getattr(scanner, "noref_rows", None))

    # Top 5 por margem líquida REAL se validado, senão líquida estimada
    def net_key(o: Opportunity) -> float:
        return o.real_net_margin_pct if o.real_net_margin_pct is not None else o.net_margin_pct
    opps_by_net = sorted(opps, key=net_key, reverse=True)

    # Resumo no terminal
    print("\n" + "═" * 60)
    print(f"  RESUMO — {datetime.now():%Y-%m-%d %H:%M}")
    print("═" * 60)
    print(f"  Expansões escaneadas   : {scanner.stats['expansions_scanned']}")
    print(f"  Listings baixados       : {scanner.stats['listings_fetched']}")
    print(f"  Após filtros           : {scanner.stats['listings_after_filters']}")
    print(f"  Com preço TCG          : {scanner.stats['tcg_price_found']}")
    print(f"  Oportunidades ≥ {args.threshold:.0%}   : {scanner.stats['opportunities_found']}")
    # v2.22: near-misses precificados (abaixo do threshold). Distinção honesta
    # "0 acima do threshold" vs "0 precificado" — os near-miss vão no XLSX e
    # alimentam o fallback de entrega do postprocess.
    if scanner.keep_all_priced and scanner.stats.get("priced_below_threshold", 0) > 0:
        print(f"  Near-miss (< {args.threshold:.0%}, no XLSX): {scanner.stats['priced_below_threshold']}")
    print(f"  Câmbio USD→BRL          : {scanner.usd_brl:.4f}")
    print(f"  Câmbio EUR→BRL          : {scanner.eur_brl:.4f}")
    # v2.9 (Codex H5): expor pricing failures pra operador detectar drift cedo
    pricing_failures = scanner.stats.get("pricing_failures", 0)
    if pricing_failures > 0:
        attempts = scanner.stats.get("listings_after_filters", 0)
        pct = (pricing_failures / attempts * 100) if attempts > 0 else 0
        marker = "  ⚠️  " if pricing_failures >= 5 else "  "
        print(f"{marker}Pricing failures        : {pricing_failures} ({pct:.1f}% das tentativas)")
        if pricing_failures >= 5:
            print("      → revisar log WARNING acima (schema drift / SSL / endpoint down?)")
    if scanner.stats.get("expansions_mass_pricing_abort", 0) > 0:
        print(f"  💥 Sets abortados (mass pricing fail): {scanner.stats['expansions_mass_pricing_abort']}")
    for _line in scanner.run_summary_lines():
        print(f"  {_line}")
    print(f"  Planilha                : {out_path}")
    print("═" * 60)

    if opps_by_net:
        validated_label = " (validadas v2.0)" if args.validate_top != 0 else ""
        print(f"\n  TOP 5 OPORTUNIDADES{validated_label}:\n")
        for i, o in enumerate(opps_by_net[:5], 1):
            l = o.listing
            # Frete: por default = 0 (modelo consolidação Hub depot). Mostra
            # parêntese só quando há override via --shipping-brl > 0.
            freight_suffix = (
                f" c/ frete (R${o.estimated_shipping_brl:.2f})"
                if o.estimated_shipping_brl > 0 else ""
            )
            print(f"  {i}. {l.card_name} ({l.set_code} {l.collector_number})")
            if o.live_price_brl is not None:
                print(f"     Scan R${o.ct_price_brl:.2f} → LIVE R${o.live_price_brl:.2f}  [{o.markup_tier}]")
                print(f"     TCG: R${o.tcg_market_brl:.2f} (${o.tcg_market_usd:.2f})  | Lucro REAL: R${o.real_lucro_brl:.2f}")
                print(f"     Margem REAL: {o.real_margin_pct:.1%} bruta | {o.real_net_margin_pct:.1%} líquida{freight_suffix}")
            else:
                print(f"     CT: R${o.ct_price_brl:.2f} ({l.price_currency})  →  TCG: R${o.tcg_market_brl:.2f} (${o.tcg_market_usd:.2f})")
                print(f"     Margem: {o.margin_pct:.1%} bruta | {o.net_margin_pct:.1%} líquida{freight_suffix}  [não validado]")
            print(f"     Seller: {l.seller_username} ({l.seller_user_type})")
            print(f"     Link: {l.cardtrader_url}\n")

    if interrupted:
        log.error("⛔ Run INTERROMPIDO (Ctrl-C): planilha e resumo são PARCIAIS — "
                  "sets não concluídos estão listados acima ('tentar de novo').")
        sys.exit(130)


if __name__ == "__main__":
    main()
