---
description: Roda o scan canônico do CardTrader por GRUPOS de sets (6 grupos por recência, poucos minutos cada (medido) — formato padrão da frota, igual ao scan-myp) e entrega via cardtrader_postprocess.py verbatim. SEMPRE pergunta ao operador quais grupos rodar antes de começar. Argumento = números de grupo (ex. "1 3") OU códigos de set CT; "total" = catálogo inteiro via workflow semanal.
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

REGRA VIGENTE DO OPERADOR: ler DELIVERY_CHAT.md na raiz do repositório. Entrega somente no chat, preço de referência clicável, coleta nova sob demanda; não executar scans no GitHub Actions nem publicar resultados. Esta regra substitui instruções antigas conflitantes abaixo.



Você foi acionado pelo comando **`/scan`** do operador. Sua missão é **uma só**:
rodar o scanner do CardTrader **por grupos canônicos** — nunca improvisando
flags — e entregar cada grupo no formato obrigatório do postprocess. **Nenhum
scan do CardTrader roda fora deste runbook.** Runs longos morriam sem entregar;
cada grupo é curto (tempos medidos abaixo) e entrega **sozinho** (se o seguinte morrer, o
anterior já foi entregue). Se algo aqui divergir do `CLAUDE.md`, ele vence.

**Argumento recebido (grupos, códigos ou "total"):** `$ARGUMENTS`

---

## 1. Pré-voo (obrigatório)

1. **Python do ambiente**: Windows local `.venv\Scripts\python.exe`; nuvem/CI
   `python` (instale `requirements.txt` em clone limpo).
2. **Chaves**: `CT_JWT` (obrigatória) e `POKEMONTCG_API_KEY` (opcional: só a 2ª fonte de preço) no ambiente ou `.env`. Cuidado
   com BOM/zero-width (`.strip()` NÃO tira BOM — chave suja crasha o header
   latin-1 e o scan sai "verde mas vazio"). Chave ausente/suja → reporte e
   pare. Nunca invente preço.
3. **Escopo**: números 1–6 em `$ARGUMENTS` → esses grupos, sem perguntar.
   Códigos de set CT → scan custom (§3, flags canônicas). `total` → §5.
   **Vazio ou genérico → SEMPRE pergunte** (AskUserQuestion, multiSelect; como
   o limite é 4 opções por pergunta, divida em duas: grupos 1–4 e 5–6; seleção
   vazia/"Other: nenhum" = não rodar aquela faixa), mostrando a tabela abaixo.
   Nunca escolha grupos sozinho.

## 2. Os 6 grupos (códigos CT VERBATIM — nunca invente/deduza outros)

Universo = os **132 sets com referência de preço real e sem armadilha**,
derivado de `SET_ALIAS_TO_PTCG` + `VINTAGE_SET_CODES` do scanner (excluídos:
`wcd*` — decks de mundial precificados contra o set original = preço-armadilha;
`mc*` McDonald's; variantes `p`-duplicadas). A partição é **travada por teste**
(`tests/test_scan_skill_profiles.py`) — nunca edite um código de cabeça.

| Grupo | Era | Sets | Medido 2026-11-24 |
|---|---|---|---|
| **G1** | Mega Evolution (**inclui Chaos Rising**) + era SV | 21 | 3,5 min |
| **G2** | era Sword & Shield + Pokémon GO + Detective Pikachu + SM final | 21 | 2,4 min |
| **G3** | Sun & Moon restante + XY final | 21 | 1,2 min |
| **G4** | XY inicial + era Black & White + HGSS | 21 | 1,0 min |
| **G5** | Call of Legends + DP + Platinum + EX tardio (tem sets lentos) | 26 | 0,7 min (26 sets, com md/la/dp/ar/dpbsp) |
| **G6** | EX inicial + e-Card + WotC (Base…Neo, Gym, promos) | 22 | 0,9 min |

_Ressalva: medido com tcgcsv como fonte principal, validando todas as candidatas (sem top-N); com `--provider pokemontcg` não foi medido. `--vintage` (34 sets): 1,2 min. DP Black Star Promos = `dpbsp` (id 1517 na API de expansões da CardTrader; o antigo `pdp` não existia)._

**G1 — Mega Evolution + era SV:**
```bash
python cardtrader_scanner.py \
  --sets meg pfl asc por cri blk wht dri pre jtg ssp scr sfa twm tef paf par mew obf pal svi \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g1_<AAAAMMDD_HHMM>.xlsx
```

**G2 — SWSH + PGO + DET + SM final:**
```bash
python cardtrader_scanner.py \
  --sets crz sit lorg astr brs fst evs cre bst shf viv cpa daa rcl ssh pkmgo det cec unm hif teu \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g2_<AAAAMMDD_HHMM>.xlsx
```

**G3 — SM restante + XY final:**
```bash
python cardtrader_scanner.py \
  --sets unb lot drm ces fli upr cinv bus slg gri sum evo sts fco bkp bkt aor gen ros prc dcr \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g3_<AAAAMMDD_HHMM>.xlsx
```

**G4 — XY inicial + BW + HGSS:**
```bash
python cardtrader_scanner.py \
  --sets phf ffi flf kss xybsp ltr plb plf pls bcr drx dex nxd nvi epo blw drv tri und ul hgs \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g4_<AAAAMMDD_HHMM>.xlsx
```

**G5 — COL + DP + Platinum + EX tardio:**
```bash
python cardtrader_scanner.py \
  --sets clo ar sv rr pl sft la md ge sw mt dp dpbsp nbsp pk df cg hp lm ds uf em dx trr rg hl \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g5_<AAAAMMDD_HHMM>.xlsx
```

**G6 — EX inicial + e-Card + WotC:**
```bash
python cardtrader_scanner.py \
  --sets exma dr ss rs skg aq ex lc si n4 n3 n2 n1 g2 g1 tr b2 fo ju bs wiz bog \
  --threshold 0.30 --max-consecutive-misses 40 \
  --output outputs/scan_g6_<AAAAMMDD_HHMM>.xlsx
```

## 3. Rodar (um run por grupo, SEQUENCIAL)

- Valores canônicos em TODO run: `--threshold 0.30` (**FRAÇÃO** — inteiro `30`
  = 3000% = zero deals sem erro); **sem `--min-net-margin`** (o scanner não corta por margem; o corte único é do postprocess),
  **sem `--validate-top`** (decisão do operador, Lote 3: a validação per-blueprint
  cobre TODAS as oportunidades; `--validate-top N` só limita, `0` desliga),
  `--max-consecutive-misses 40` (valor travado em teste; inofensivo: o tcgcsv, fonte principal, já vem
  em lote por set e não corta por misses).
- **Fonte de preço:** NÃO passe `--provider`: o padrão já é `tcgcsv`. A pokemontcg.io só entra como 2ª fonte,
  quando o tcgcsv acha a carta sem preço. Não use `--provider tcgcsv --ignore-skip-list` como contorno: não é mais
  necessário (set sem referência sai com motivo, sem skip-list). Resposta incompatível/ambígua do tcgcsv nunca é
  trocada por preço da outra fonte.
- Scan custom (`/scan pre ssp`): mesmo comando trocando só a lista de `--sets`.
- **Nunca dois runs ao mesmo tempo** (mesma pasta de estado — o scanner
  recusa). Grupos escolhidos rodam **em sequência**, cada um em background,
  monitorado. Sets vintage lentos já têm timeout interno maior (df 20min,
  ds/n1/n4 18min) — não mexa em `--per-set-timeout`.
- ⏱️ **Tempos medidos em 2026-11-24** (tcgcsv, validando todas, sem top-N): ver a tabela do §2.
  Anote a duração real de cada grupo no resumo.
- Grupo que estourar bem acima do medido (>~15 min): anote a duração real no resumo e
  proponha re-dividir. Grupo que falhar não cancela os demais — registre com a
  saída real e siga.
- **Rota via GitHub (opcional)**: dispatch do workflow `daily-scan.yml` com o
  input `sets` = os códigos do grupo (o timeout do workflow comporta um grupo).
  Baixe o artifact e entregue o `.md` do postprocess que vem nele.

## 4. Postprocess + entrega (por grupo, formato OBRIGATÓRIO)

Assim que **cada grupo** terminar (não espere os outros). Para a liquidez (que libera COMPRA) adicione
`--pc-refs N` (consultas únicas ao PriceCharting) e, se ele bloquear (403), `--pc-firecrawl N` (pago, 1 crédito por
página, **teto 100 por scan**; padrão 0 = não gasta):

```bash
python cardtrader_postprocess.py \
  --input outputs/scan_g<N>_<stamp>.xlsx \
  --output outputs/relatorio_g<N>_<stamp>.xlsx
```

Como ler a decisão (regras do código, nada além disso): **Inferido** (raridade da CardTrader não informa o
acabamento; margem estimada) = sempre REVISAR, nunca COMPRA. Referência **ambígua** = sem referência e sem preço.
Referência **mais velha que 7 dias** (`--max-ref-age-days`), de idade desconhecida ou futura = REVISAR. Preço
PriceCharting compatível que **diverge** mais que `--max-ref-divergence` (0,30), ou margem pela MENOR referência
abaixo de 30% = REVISAR. COMPRA exige **liquidez** (≥5 vendas/90d e ≥1/30d). Linha que ficou sem consulta por
orçamento Firecrawl esgotado aparece como `NAO_CONSULTADO_ORCAMENTO`; a coluna **PC Motivo** explica por quê.

Se o scanner sair com código **20, 21, 22 ou 23** (validação parcial / sem preço live válido / validação falhou /
set em falha operacional), o XLSX foi gravado e o relatório É gerado mesmo assim: rode o postprocess e **leia o aviso
do cabeçalho** ("⚠ set(s) NÃO avaliados…") antes de colar; sets avaliados com falha precisam rodar de novo. Tabela completa dos códigos no CLAUDE.md.

(**sem `--top-md`**: a entrega mostra TODAS as linhas de COMPRA e REVISAR. Se alguém limitar com
`--top-md N`, o cabeçalho diz "mostrando N de M" e o rodapé diz quantas ficaram de fora e que
elas estão na aba `Deals` do XLSX.)

- **Cole no chat, VERBATIM, o `.md`** que ele gravou/imprimiu
  (`build_delivery_markdown` — única fonte de verdade do formato).
- **PROIBIDO**: tabela à mão; renomear/reordenar colunas; remover link;
  XLSX/CSV por anexo (só a pedido explícito); amostra curada.
- **Todas as linhas** (COMPRA + REVISAR); sem deal acima do limiar, a
  ferramenta emite os near-miss "abaixo do limiar" — não existe "veio vazio,
  então reformato".
- **Não recomende compra** — capital é do operador.

## 5. `/scan total` — catálogo inteiro (~832 sets, incl. sem referência)

Nunca local numa tacada: dispatch do **`weekly-scan.yml`** (checkpoint
recuperável + artifacts), aguardar, baixar o artifact e colar o `.md` do
postprocess. Local só em blocos explícitos a pedido do operador.

## 6. Fechamento e higiene

- Outputs de scan (`outputs/*`) são gitignored — NUNCA commite dados de scan.
- Fonte falhou → linha rotulada fallback/erro; jamais fabrique número.
- Resumo final: grupos rodados, duração REAL de cada um (pra calibrar as
  estimativas), deals por classificação, sets pulados/falhos, caminhos dos
  XLSX/`.md` de apoio.
