<!-- FLEET:ESTILO-RESPOSTA v2 (2026-11-27) — cópia-mestra: scanners-commons/08-ESTILO-RESPOSTA.md. Editar LÁ e replicar; não divergir nesta cópia. -->
> **Estilo de resposta obrigatório (operador, 2026-09-14): CONCISO — teto de 200 palavras.**
> Toda resposta no chat, nesta ordem: **1) Objetivo** — 1 linha do que foi pedido · **2) O que foi feito** — bullets curtos, cada um com o *porquê* da decisão · **3) Dependências/pendências** — o que falta, o que bloqueia, de quem depende (`nenhuma` quando não houver).
> O teto conta **só prosa**. **Fora do teto** (nunca resumir, cortar nem "amostrar" pra caber): a tabela de entrega gerada pela ferramenta do repo (colada VERBATIM), blocos de comando/código, saída de teste colada como prova e artefato canônico do repo (brief, relatório, análise).
> Sem preâmbulo, sem repetir o pedido, sem recapitular o que já foi dito. Não cabe em 200 palavras? Entregue o essencial dentro do teto e ofereça o detalhe ("quer o detalhe de X?") — nunca estoure em silêncio.
> **Entendi antes de executar (v2):** pedido longo (mais de 3 frases), brain dump ou várias tarefas misturadas → antes de executar, devolva em até 3 linhas `Entendi: …` e espere o ok. Pedido curto e claro vai direto. Sem o operador presente (rotina, thread autônoma): escreva o `Entendi` no topo e siga na leitura mais provável.

> **Regra vigente de entrega:** [DELIVERY_CHAT.md](DELIVERY_CHAT.md). Resultados somente no chat, referência clicável e coleta nova por solicitação; substitui orientações antigas de entrega via GitHub ou preços reutilizados.

# CLAUDE.md — card-trader-scanner

> **Este arquivo tem dois leitores:**
> 1. **Você, Matheus** — pra entender o que o scanner faz e como rodá-lo.
> 2. **Qualquer sessão Claude Code (local ou na nuvem)** — que lê este arquivo
>    no começo de cada sessão pra saber como trabalhar neste projeto sem
>    re-descobrir tudo.
>
> Por isso ele mistura linguagem simples com alguns termos técnicos. **Toda
> palavra técnica é explicada entre parênteses na primeira vez que aparece**, e
> há um **glossário no fim**. Vá no seu ritmo — com o tempo os termos ficam
> familiares. *(Guia reescrito em linguagem acessível em 2026-06-05, decisão do
> operador.)*

**Em uma frase:** este programa compara o **preço de cartas Pokémon** (avulsas,
em inglês, estado Near Mint / "quase perfeita") no site europeu
**cardtrader.com** contra o preço de referência dos EUA (**TCG Player**), e
aponta onde dá pra comprar barato na Europa e revender caro. É o caminho
**inverso** do scanner MYP (que garimpa barato no Brasil).

---

## 🛰️ Convenções da frota (cross-scanner)

> **Manual completo** (repo público): https://github.com/matheuscllm-lgtm/scanners-commons — erros comuns, referências de preço, chaves, GitHub Actions e modelo de entrega de TODOS os scanners. Cópia-mestra local (PC do operador): `C:\Users\mathe\scanners-commons\`.

Invariantes que valem para TODOS os scanners:

- **Margem sobre a VENDA, mínimo 30%** — `(ref − compra)/ref` decide o corte; o ROI `(ref − compra)/compra` é só informativo (não filtra, não classifica, não ordena). Sem nenhuma taxa embutida (frete, cartão, IOF — o operador calcula por fora). Vale igual para Pokémon (CardTrader), One Piece e Dragon Ball: a base é a venda, nunca a compra.
- **Piso de relevância R$50 (~US$10) — SÓ para cartas avulsas (singles).** Produtos SELADOS não têm piso (decisão do operador, 2026-06-27); lá o único critério é a margem ≥30%.
- **Só Near Mint** — condição por match EXATO `== "NM"`, nunca substring (já vazou SP).
- **Nunca inventar preço** — fonte falhou → marca fallback/erro e segue; jamais fabrica número.
- **Nunca recomendar compra** — o scanner reporta margem, flags e fontes; a decisão de capital é do operador.
- **Entrega = tabela markdown no chat** (nunca XLSX/CSV por padrão), gerada pela ferramenta do repo — nunca montada à mão —, mostrando TODAS as linhas (aprovadas + rejeitadas). Coluna `Carta` = nome + número; coluna `Links` combinada = `[oferta](url) · [TCG/referência](url)`.
- ⚠️ **Convenção de threshold:** percentual inteiro (`30`) = MYP, Liga, eBay; fração (`0.30`) = CardTrader, COMC, Selados.
- **Sem check-ins automáticos de PR** (operador, 2026-09-12): depois de abrir um PR, a sessão reporta o link no chat e **para** — sem `subscribe_pr_activity`, sem check-in agendado (`send_later`/Routine/cron), sem poll de CI/review. Assinatura de PR criada pelo harness deve ser cancelada. Exceção única: pedido explícito do operador ("acompanha esse PR").

Erros recorrentes (3 famílias — detalhe no manual):

1. **Segredo/ambiente:** BOM/zero-width numa chave → crash latin-1 no header → scan "verde mas vazio". Setar sem BOM (`printf '%s' 'KEY' | gh secret set`) **e** sanitizar ao ler no código (`.strip()` NÃO tira BOM).
2. **Git:** branch ou `main` local defasado por squash-merge PARECE pendência. O teste real de "já mergeado" é `git diff --stat origin/main <branch>` estar vazio (não `git merge-base`).
3. **Honestidade de preço:** inflação de referência, fallback tratado como real, NM frouxo → sempre validar versão/condição e rotular fallback.

**Este scanner:** fonte principal do preço de referência = **`tcgcsv.com`** (padrão do `--provider` desde a B1j, decisão do dono 2026-11-24), com validação per-blueprint (casa NM + variante exata). A **pokemontcg.io é só a 2ª fonte**: entra apenas quando o tcgcsv tem a carta mas SEM preço na chave certa; resposta incompatível ou ambígua do tcgcsv **nunca** é trocada por preço da outra fonte (correspondência EXATA de edição e acabamento, nunca o mais barato). Chaves = `CT_JWT` (obrigatória), `POKEMONTCG_API_KEY` (opcional, só p/ a 2ª fonte).

---

## Onde mora o programa (importante)

- **Pasta oficial (PC do operador):** `C:\Users\mathe\card-trader-scanner` —
  no **disco do computador** (HD local), fora do Google Drive.
- Existe uma **cópia na nuvem** no GitHub (um site que guarda código), no
  endereço `github.com/matheuscllm-lgtm/card-trader-scanner`. As duas se
  espelham. Sessões Claude Code na nuvem trabalham num **clone** (cópia
  baixada) desse repo.

> **Por que saiu do Google Drive (junho/2026):** o Drive ficava mexendo nos
> arquivos internos de controle do programa e corrompia coisas. Mudamos pro HD
> local e **apagamos a pasta antiga do Drive**. Se você vir uma pasta
> "CardTrader Scanner" no Drive, ela é lixo antigo — não use.

---

## ⚠️ A pegadinha nº 1 — a "margem mínima" é em FRAÇÃO

Quando você manda o programa procurar deals, define uma **margem mínima de
lucro** (`--threshold`, lê-se "thréshould" = limiar). Aqui ela é escrita como
**fração**:

- `--threshold 0.25` quer dizer **25%**.
- Se você escrever `--threshold 25`, o programa entende **2.500%** → não acha
  nada, sem dar erro nenhum.

> O scanner irmão (MYP, repo `myp-arbitrage-scanner`) faz o **oposto** (lá
> `25` = 25%). São dois projetos separados, com regras diferentes — não
> confunda os dois. (Ver a tabela de convenções da frota, acima.)

---

## A conta do lucro e a decisão (P1, 2026-11-24 — decisões do dono)

**Uma só conta**, em `ct_economics.compute` (o postprocess não tem mais fórmula própria):

```
margem sobre a VENDA = (referência − compra) ÷ referência   ← é o CORTE (30%) e a coluna "Margem %"
ROI sobre aquisição  = (referência − compra) ÷ compra       ← só informativo (XLSX); nunca vira o corte
```

Exemplo: compra 75, referência 100 → margem 25% (**não** passa em 30%), ROI 33,3%.

- **Custos:** Hub 6% e frete de R$ 0,50 **por carta** (sem desconto por quantidade do
  mesmo vendedor). IOF, spread cambial, taxa do cartão, imposto de importação e taxa de
  venda são **configuráveis por flag** (`--iof`, `--spread-cambio`, `--card-fee`,
  `--import-tax`, `--sell-fee`, `--sell-shipping-brl`; cada taxa exige a sua base de incidência, `--iof-base` etc., sem base presumida: compra_sem_hub|compra_com_hub|compra_com_hub_frete; venda|venda_menos_frete) e valem "não informado" até alguém
  informar. Enquanto houver custo não informado, a margem líquida do XLSX sai marcada
  **PARCIAL** (com a lista do que falta) — nunca como definitiva. No chat não aparece
  margem líquida.
- **Hub nunca em dobro:** o preço de checkout (`LIVE R$ (real)`) já embute o Hub; o preço
  cru do scan (`Scan R$ (raw)`) não. Cada linha carrega `compra_inclui_hub` (decidido pela
  coluna que a linha usa) e só o preço cru recebe os 6%.
- **Chase é só informativo** (vintage e moderno): coluna do XLSX, nunca em ramo de decisão.
  Vem da coluna `Chase Tier` do scanner; sem ela, `ct_chase.classify_chase_tier`.
- **COMPRA exige, junto:** margem sobre a venda ≥ corte (`--min-net-margin`, **padrão 0.30**;
  o cabeçalho da entrega imprime o corte em uso) · lucro ≥ R$ 50 · preço validado no
  checkout · referência de variante/edição compatível (coluna `Ref Compatível` = Sim; sem
  ela → REVISAR) · **liquidez verificada** no PriceCharting: ≥ `--min-sales-90d` (padrão 5)
  vendas em 90 dias **e** ≥ `--min-sales-30d` (padrão 1) em 30 dias, só cartas não
  graduadas e unitárias, da página da **mesma edição**. Contagem truncada vale "pelo menos
  N". Sem dado de liquidez (sem consulta, 403, sem página, edição não informada, oferta
  reverse — o acabamento da página PC não é confirmável pelo módulo) → **REVISAR** com o
  motivo "liquidez não verificada: <status>". Margem alta nunca dispensa a liquidez.
- **Margem negativa** nunca entra na tabela do chat: vai para a aba **Auditoria** do XLSX e a
  entrega diz em uma linha quantas foram. (Antes entravam por causa das regras de REVISAR
  — sufixo alfa/set sem cobertura — que rodavam antes do teste de margem.)
- **PriceCharting:** `--pc-refs N` = no máximo N consultas **únicas** (carta+set+edição+
  acabamento; linhas repetidas = 1 consulta), das linhas de maior lucro primeiro. Edição vem
  da coluna `Edição`; ausente (XLSX antigo) → não consulta, "edição não informada".
  `--pc-firecrawl N` (padrão 0 = nunca gasta; máximo 100 por scan) paga o Firecrawl só
  quando o PriceCharting bloqueia. A entrega informa consultas únicas × linhas atendidas ×
  créditos. Cache só do run (pasta `pc_cache_<timestamp>` ao lado do XLSX).
- **Abas opcionais do scanner** `Sem preço` / `Sem Ref Compatível`: viram bloco à parte na
  entrega (sem margem, com motivo e os dois links; "TCG: sem link" quando faltar).
- **COMPRA só é alcançável com XLSX de scanner novo (importante).** A decisão COMPRA exige as
  colunas `Edição`, `Acabamento` e `Ref Compatível` (= Sim) emitidas pelo scanner. Com um XLSX
  **antigo** (sem essas colunas) **tudo sai REVISAR** — nunca COMPRA —, cada linha com o motivo:
  "referência de variante/edição não certificada pelo scanner" (sem `Ref Compatível`) e/ou
  "edição não informada" (sem `Edição`: o postprocess não presume Unlimited e não consulta o
  PriceCharting). Isso é proposital: quem certifica edição/variante é o scanner, o postprocess
  só confere. COMPRA também exige preço de checkout (`LIVE R$ (real)`) na linha: validação
  `VALIDATED_*` sem LIVE vira REVISAR.
- **Edição:** o vocabulário vem só de `ct_variants` (`1st`/`unl` e os rótulos `1st Edition`/
  `Unlimited`). Célula vazia, NaN ou valor fora do vocabulário (ex.: `Shadowless`) = edição **não
  informada** (REVISAR, valor original no motivo). O `ct_variants` ainda não define um valor
  explícito para "carta sem divisão de edição"; enquanto o scanner não emitir um, essas linhas
  ficam REVISAR por esse motivo (pendência do scanner, não do postprocess).
- **Destinos que não são COMPRA/REVISAR (cada causa separada, todas contadas no rodapé):** NÃO
  (abaixo do corte), AUDITORIA (margem negativa, só na aba), **SEM REFERÊNCIA** (compra ou
  referência inválida/ausente: o `ct_economics` não dá margem, então a linha não tem margem nem
  lucro, nunca herda número do XLSX; bloco à parte "Sem referência" com o motivo e os links),
  blocos `Sem preço`/`Sem Ref Compatível` (abas do scanner). Falhas operacionais do PriceCharting
  têm status próprios (`INDISPONIVEL_403/REDE/FIRECRAWL/ORCAMENTO`) e o limite `--pc-refs`
  esgotado é `LIMITE_CONSULTAS` (rodapé: quantas referências e linhas ficaram sem consulta).

> Os números de `margem` da planilha mudaram de nome: `Margem venda %` (era `Net %`) e
> `Lucro bruto (R$)` (era `Lucro Líq`) — o conteúdo é o mesmo cálculo do scanner na base
> venda, só que agora vem de um único módulo.
>
> ℹ️ **Base do denominador:** a margem deste scanner também é sobre a VENDA (`margin = (tcg_brl - custo_brl) / tcg_brl`, `cardtrader_scanner.py`), igual à regra da frota acima.

> **Detalhe técnico (pode pular):** o primeiro rastreio usa um preço "cru"
> (*per-expansion*, agregado por coleção); a conferência (`--validate-top`, que existe e vale)
> refaz com o preço **real de checkout** (*per-blueprint*, por carta exata).
> **Sempre conferir** — sem isso, no passado **~76% dos "achados" eram falsos**.
> Desde o Lote 3 (2026-11) o padrão de `--validate-top` é **validar TODAS** as
> oportunidades elegíveis (omitir a flag = todas); `--validate-top N` limita às N
> de maior margem e `--validate-top 0` desliga a validação. Linha que não pôde
> ser validada (erro de API, STALE) **continua na saída com o status real**.
>
> A opção `--hub-fee` existe nos dois scripts com **padrão 0,06** e só alimenta as colunas
> **líquidas** (informativas) de preço cru; o corte de 30% é a margem sobre a venda e não
> depende dela, e o preço validado do checkout já embute o Hub (nunca contado duas vezes).

---

## Como rodar

### Preparar o ambiente (só na primeira vez)

São três passos, feitos uma vez por máquina. *"venv" = ambiente virtual: uma
caixinha isolada onde o programa instala as ferramentas que precisa, sem
bagunçar o resto do sistema.*

```bash
# Windows (PC do operador):
python -m venv .venv                 # cria a caixinha
.venv\Scripts\activate               # entra na caixinha
pip install -r requirements.txt      # instala as ferramentas listadas

# Nuvem/Linux (clone limpo): mesmos comandos, com "source .venv/bin/activate"
# no lugar do activate do Windows (ou use o python do ambiente direto).
```

Depois, crie um arquivo chamado `.env` (texto simples) na pasta, com a sua
**senha de acesso ao CardTrader** (chamada de "token" — uma senha longa que o
site gera pra você). Ele fica assim:

```
CT_JWT=<seu token do CardTrader: no site, Settings → API Access → Create New Token>
POKEMONTCG_API_KEY=<opcional (2ª fonte de preço), grátis em pokemontcg.io/dev>
```

> ⚠️ O `.env` **nunca** vai pra nuvem (tem sua senha dentro). O programa já está
> configurado pra ignorá-lo. Cuidado com BOM/zero-width ao setar chaves (erro
> recorrente nº 1 da frota, acima).

### 🎯 O caminho canônico de scan é o skill `/scan` — nenhum scan roda fora dele

**Skill `/scan`** (`.claude/commands/scan.md`, jul/2026): o jeito canônico de
pedir um scan ao assistente — formato padrão da frota, igual ao `scan-myp`.
Os **132 sets com preço de referência real** (derivados de
`SET_ALIAS_TO_PTCG` + `VINTAGE_SET_CODES`, sem os `wcd*`/McDonald's/duplicatas)
estão divididos em **6 grupos por recência** (G1 = Mega Evolution até Chaos
Rising + era SV … G6 = EX inicial + e-Card + WotC), cada um de poucos minutos (medido 2026-11-24: G1 3,5 · G2 2,4 · G3 1,2 · G4 1,0 · G5 0,7 · G6 0,9 min; `--vintage` 1,2 min) —
runs mais longos morriam sem entregar. O skill **sempre pergunta quais grupos
rodar**, roda um por vez (nunca em paralelo) com os valores canônicos
(threshold 0.30, max-consecutive-misses 40; **sem** `--validate-top`
(valida todas) e **sem** `--min-net-margin` no scanner: o corte é único, no postprocess) e entrega **cada grupo**
pela tabela do postprocess assim que termina. `/scan pre ssp` = sets custom;
`/scan total` = catálogo inteiro via workflow semanal. A partição é travada por
teste (`tests/test_scan_skill_profiles.py`) contra o mapa do scanner. **Nenhum
scan do CardTrader roda fora do skill.**

Existe também o skill **`/auto`** (`.claude/commands/auto.md`): modo autônomo
de trabalho no repo (tarefas de código/manutenção ponta a ponta, com os freios
duros descritos nele). Ele **não** substitui o `/scan` para scans.

### Os comandos que o skill executa (referência — pra manutenção e debug)

Um comando tem três partes: **o programa** · **as opções** (começam com `--`,
chamadas "flags") · **os valores**. Se algum dia precisar rodar à mão (debug),
use exatamente os valores canônicos:

```bash
# 1) Rastrear alguns sets e já conferir os melhores candidatos:
.venv\Scripts\python.exe cardtrader_scanner.py \
  --sets sfa scr par paf tef twm ssp dri blk jtg \   # quais coleções (códigos CardTrader)
  --threshold 0.30 \                                  # margem mínima 30% (FRAÇÃO!)
                                                      # (sem --validate-top = confere TODAS)
  --output outputs/scan_da_vez.xlsx                   # onde salvar a planilha

# 2) Gerar o relatório organizado (decisão COMPRA/REVISAR/NÃO):
#    Aqui --input e --output são OBRIGATÓRIOS (não dá pra omitir).
.venv\Scripts\python.exe cardtrader_postprocess.py \
  --input outputs/scan_da_vez.xlsx \
  --output outputs/relatorio_da_vez.xlsx
```

(Na nuvem/Linux, troque `.venv\Scripts\python.exe` por `python`.)

**Defaults que enganam (documentados de propósito):**

- `--validate-top`: omitido = valida **todas** (Lote 3). `N` limita, `0` desliga
  (sem validação ~76% dos achados são falsos). Os comandos canônicos do skill
  `/scan` **não passam** a flag (validam todas).
- `--min-net-margin`: no **scanner** (default 0.0) só MARCA (log + contador `opps_marcadas_min_net`),
  NUNCA remove linha — toda oferta validada vai ao XLSX e quem classifica é o postprocess; no
  **postprocess** (padrão 0.30) é o corte único do dono, margem sobre a venda. O comando canônico
  não passa a flag no scanner.

Opções úteis:

- `--all-sets` = **rastreio COMPLETO** (todas as ~832 coleções de uma vez),
  começando pelas mais valiosas — é o modo do rastreio **semanal**. Esse modo é
  demorado (horas).
- `--skip-backcatalog` = **só as coleções modernas/curadas** (~30, em vez de
  ~832). Pula o **back-catalog** (sets antigos, era Sword & Shield e anteriores),
  que é mercado eficiente e quase nunca rende deal (a auditoria de 2026-06-08 deu
  **0 deal** em 17 sets SWSH). Use junto com `--all-sets` pra um scan completo
  **muito mais rápido**, focado em lançamentos novos — que é onde o gap aparece.
  Se combinar com `--sets`, ele cruza a sua lista com as modernas (fica só a
  interseção).
- `--vintage` (v2.21) = a lista curada "vintage core" de sets antigos.
- `--threshold 0.20` acha ~5× mais deals que `0.30`, mas com mais ruído (mais
  falso positivo pra você filtrar).
- Rastreios longos: rode **em segundo plano** (sem travar o terminal). Nunca
  deixe rodando "preso" numa janela que você pode fechar sem querer.
- `--language zh-CN` (v2.29) = varre ofertas em **outro idioma** (default `en`
  intacto; valores reais na API: en/it/de/fr/es/pt/zh-CN). ⚠️ A referência
  TCGplayer continua sendo a carta **inglesa**, então o número vira **razão de
  preço** EN/<idioma>, não margem de revenda — entregue com
  `cardtrader_postprocess.py --ratio-column [--min-ratio 4]` (coluna "Razão
  EN/ZH-CN" + corte explícito; 0 linha → mensagem honesta, nunca near-miss).
  **Referência principal nesse modo = eBay** (`--ref-source ebay`: mediana das
  vendas eBay concluídas da carta inglesa raw, via tabela pública do
  PriceCharting; TCG vira fallback rotulado). O PriceCharting dá 403 a cliente
  HTTP comum em alguns IPs — passe `--pc-firecrawl N` (pago, 1 crédito/página,
  ~2 páginas por linha) ou a coluna sai "eBay indisponível". Comando canônico:
  `cardtrader_postprocess.py -i <raw> -o <rel> --ref-source ebay --min-ratio 4
  --pc-firecrawl <2×linhas>`. **Piso US$10 fica na referência inglesa**
  (`--min-ref-usd`, default 10, decisão do operador 2026-10-03): colete o scan
  de idioma com `--min-price-usd 0`, senão o piso cai na oferta chinesa e
  esconde as baratas. ⚠️ No CT, `sv3/sv6/sv7/sv8/sv9/sv10` são sets
  **japoneses** (não Obsidian Flames…Destined Rivals): ficam sem referência de
  propósito (`CT_JP_SETCODE_COLLISIONS`).
  Limite conhecido: o grosso do chinês no CT vive em expansões PRÓPRIAS
  (`cs35`, `svp-c`, `z-chp`, `s-p`, `sl`…) cuja numeração não casa com os sets
  ingleses — fora do escopo deste scanner.
- Outras flags existem (`--provider`, `--include-graded`, `--dry-run`,
  `--no-cache`, `--max-expansions`, `--shipping-brl`, `--ignore-skip-list`,
  `--clear-skip-list`, `--chase-only`, `--opportunities-only`,
  `--checkpoint-every`, `--flush-every-listings`, `--max-consecutive-misses`,
  `--per-set-timeout`, `--state-dir`, `--allow-concurrent`,
  `--no-tcgcsv-fallback`; no postprocess: `--revisar-min-net`,
  `--min-lucro`, `--min-sales-90d`, `--min-sales-30d`, `--iof`, `--shipping-brl`, `--top-md`, `--doubleholo`,
  `--no-pid-resolve`, `--pc-refs N` (P1: liquidez `Vendas 30d/90d` + `Ref PC US$`
  (mediana ungraded, sem lotes) + link `[PC]` + flag `PC diverge`, por consulta única, linhas
  de maior lucro primeiro; é o que libera COMPRA)) — `--help` de cada script lista
  tudo.

> ℹ️ **Histórico (vale só com `--provider pokemontcg`):** desde a B1j o padrão é o
> tcgcsv como fonte principal; nele o set inteiro vem em lote e **não há corte por misses**,
> então `--ignore-skip-list` e `--provider tcgcsv` deixaram de ser contorno. O gotcha abaixo
> descreve o caminho antigo (pokemontcg.io primeiro). Os comandos do skill ainda passam
> `--max-consecutive-misses 40` (travado em teste; inofensivo com o tcgcsv).
>
> ⚠️ **Gotcha do fallback tcgcsv (registrado 2026-07-06; skill alinhada em
> 2026-07-20):** o fallback `tcgcsv.com` (v2.23) tem **dois gatilhos**: o cap
> de misses consecutivos (`--max-consecutive-misses > 0`) e um **resgate de
> fim de set** (set que completa o loop de pricing com 0 hit na pokemontcg.io
> e listings pendentes tenta o tcgcsv para todos os misses — mesmo com o cap
> em 0). Na prática o resgate só vale se o set completar o loop dentro do
> per-set-timeout — e num set como `asc` (Ascended Heroes, que só o tcgcsv
> precifica) o per-listing lento da pokemontcg.io historicamente estourava o
> timeout antes do resgate. Por isso os 6 comandos canônicos do skill `/scan`
> passam `--max-consecutive-misses 40` (alinhado em 2026-07-20 com o que o
> comentário do código em `SET_TIMEOUT_OVERRIDES` sempre assumiu; travado em
> `tests/test_scan_skill_profiles.py`). Se for rodar um set como `asc` à mão,
> fora do skill, passe `--max-consecutive-misses 40` você também.

> ✅ **Mapa explícito de sets no tcgcsv (v2.28, 2026-09-12):** cada código CT
> do universo dos grupos aponta pro(s) *groupId* (número do set no tcgcsv)
> certo(s) em `CT_SET_TO_TCGCSV_GROUP_IDS`. Antes, só ~21 sets tinham esse
> atalho e o resto era casado pelo **nome**, que falhava em nomes parecidos —
> por isso `svi`, `kss`, `gen` e `evo` saíam "sem referência de preço" no
> tcgcsv (agora o padrão). Único set sem referência de propósito: `c25`
> (Celebrations — a numeração da Classic Collection colide com a do set
> principal). **Set novo no universo?** O teste `tests/test_tcgcsv_group_map.py`
> quebra até você mapear o groupId (conferido no `/groups` do tcgcsv) ou
> documentar a exclusão.

### Workflows do GitHub Actions (nuvem)

Três workflows em `.github/workflows/`:

- **`tests.yml`** ("tests"): roda a suíte de testes em todo push na `main`,
  em todo PR e por dispatch manual.
- **`daily-scan.yml`** ("Daily CT Scan"): apesar do nome, **só roda por
  dispatch manual** (`workflow_dispatch` — decisão do operador 2026-05-16: sem
  agendamento; runs autônomos rodam LOCAL via venv + `.env`). Aceita inputs
  `sets`, `threshold` (fração), `min_net_margin` e `validate_top`.
- **`weekly-scan.yml`** ("Weekly Scan (full scope)"): rastreio completo, **só
  dispatch manual**. Desde 2026-06-18 (higiene de repo público) os resultados
  saem **apenas como artifacts** do workflow (ficam atrás da aba Actions e
  expiram sozinhos) — o antigo mecanismo de "live partials" numa branch pública
  foi aposentado porque publicaria a lista de deals. Resultado totalmente
  privado = rodar local. É este workflow que o `/scan total` usa.

Os secrets `CT_JWT` e `POKEMONTCG_API_KEY` moram nos Secrets do repo (Actions);
nunca em arquivo versionado.

---

## 📤 Como o resultado é ENTREGUE (tabela no chat, com links pra clicar) — REGRA OBRIGATÓRIA

> **Regra do operador (jun/2026):** a entrega do resultado é uma **tabela no
> chat** — **não** uma planilha. A planilha (`.xlsx`) continua sendo gerada e
> guardada na pasta `outputs/`, mas é arquivo de apoio, não a entrega.

> **⚠️ Instrução MANDATÓRIA pro assistente — não opcional:**
> Sempre que for entregar resultados deste scanner ao operador, você **DEVE**:
> 1. **Gerar a tabela pela ferramenta do repo** (`cardtrader_postprocess.py`,
>    que chama `build_delivery_markdown`). **NUNCA monte a tabela à mão** nem
>    reformate números/links você mesmo — a ferramenta garante o formato, os
>    links clicáveis e a classificação coerente com a planilha.
> 2. **Colar a tabela markdown no chat** (terminal ou app). **NUNCA** entregar
>    XLSX/CSV por anexo como padrão. Só mande arquivo se o operador **pedir
>    explicitamente**.
> 3. **Mostrar TODOS os deals** (COMPRA + REVISAR) — não uma amostra curada.
>    O comando canônico NÃO usa `--top-md` (mostra tudo). Se alguém limitar com
>    `--top-md N`, o cabeçalho diz "mostrando N de M" e o rodapé diz quantas ficaram
>    de fora e em qual aba do XLSX (`Deals`) estão.
> 4. **Não rankear "comprar/não comprar".** Você reporta margem, flags e fontes;
>    quem decide capital é o operador.
> 5. **NUNCA monte tabela à mão, nem mesmo quando "não há deal".** A ferramenta
>    **sempre** entrega uma tabela no formato canônico: se nenhum item passa o
>    limiar, ela mostra os **candidatos mais próximos por margem** marcados
>    *"abaixo do limiar"* (fallback near-miss). Logo **não existe** o caso "veio
>    vazio, então eu reformato" — esse era o erro recorrente. Se a entrega que
>    você vai colar **não saiu do `.md` da ferramenta**, pare e gere por ela.
>    **Única exceção (v2.29, `--min-ratio X`):** o operador pediu um screen de
>    *razão de preço* com corte explícito; aí a ferramenta corre o corte sobre
>    TODAS as linhas precificadas (inclusive as que a regra mecânica marcaria
>    NÃO — a Flag diz o motivo) e, se **nenhuma** bate o corte, imprime a
>    mensagem de 0 linha com as contagens (abaixo do corte / sem CT US$) em vez
>    da tabela near-miss. Linhas abaixo do corte **não** aparecem como resultado
>    — mostrar "quase 4×" como se fosse 4× seria mentir. Cole a mensagem
>    verbatim também.

**Para explorar abaixo do threshold padrão** (ver o que está "perto"), rebaixe os
limiares **na própria ferramenta** — nunca leia o XLSX e monte à mão:

```bash
.venv\Scripts\python.exe cardtrader_postprocess.py \
  --input outputs/scan_da_vez.xlsx --output outputs/relatorio.xlsx \
  --min-net-margin 0.20 --revisar-min-net 0.10 --min-lucro 0
```

O comando literal de entrega (passo 2 do "Como rodar") **já produz a tabela** —
ele imprime no terminal E grava um arquivo `.md` ao lado da planilha:

```bash
.venv\Scripts\python.exe cardtrader_postprocess.py \
  --input outputs/scan_da_vez.xlsx \
  --output outputs/relatorio_da_vez.xlsx      # sem --top-md: a tabela traz TODAS as linhas
```

A tabela tem as colunas:

```
| # | Margem % | CT US$ | TCG US$ | Dif | Carta | Edição | Acabamento | Set | Raridade | Cond | Qtd | Vendas 30d | Vendas 90d | Fonte ref. | Data ref. | Flag | Links |
```

O que cada coluna quer dizer:

| Coluna | O que é |
|---|---|
| **#** | posição no ranking (1 = maior margem) |
| **Margem %** | margem sobre a VENDA: (referência − compra) ÷ referência (`ct_economics`); o corte é 30% |
| **Vendas 30d / 90d** | vendas ungraded da página PriceCharting da mesma edição; `≥N` = piso (página truncada); `—` = não verificada |
| **CT US$** | preço no CardTrader, **em dólar** (convertido do real pela cotação do dia, que o programa lê da planilha) |
| **TCG US$** | preço de referência dos EUA (TCG Player), em dólar |
| **Dif** | a diferença em dólar (TCG US$ − CT US$) — quanto "sobra" antes das taxas |
| **Carta** | nome **+ número** numa célula só (ex.: `Hitmonlee (013/110)`). Se o nome já tem o número, não duplica |
| **Edição / Acabamento** | edição da oferta (`1st Edition`, `Unlimited` ou `Sem divisão de edição`) e acabamento (`Normal`/`Holo`/`Reverse`) — a referência TCG é DESTA variante; `—` = scanner antigo, não informada |
| **Fonte ref. / Data ref.** | fonte do preço de referência (`pokemontcg`/`tcgcsv`) e a data: `dado de …` = data do DADO (dump diário do tcgcsv, `updatedAt` do TCGplayer); `buscado em …` = só a hora da busca, quando a fonte não expõe a data |
| **Set** | a coleção (código do CardTrader) |
| **Raridade** / **Cond** | raridade oficial e condição (sempre Near Mint) |
| **Qtd** | quantas unidades o vendedor tem (você importa em lote) |
| **Flag** | **"validar manual: <motivo>"** quando a linha é REVISAR (margem borderline, suspeita de inflada — `TG`, sufixo de promo/league, set sem cobertura, markup anômalo —, ref não certificada ou **liquidez não verificada/baixa**). Vazio = COMPRA. Margem negativa nunca aparece (aba Auditoria) |
| **Links** | **dois links pra clicar:** `[oferta]` abre a página da carta no CardTrader · `[TCG]` abre a página do TCG Player **pra você conferir o preço à mão** |

> **Por que a coluna Flag:** ela traz pro chat a mesma classificação que a
> planilha faz (`COMPRA` / `REVISAR`). Assim, sem abrir o Excel, você já vê
> quais achados são "limpos" e quais pedem **conferência manual** antes — os
> suspeitos de margem inflada (lembre dos ~76% de falsos sem validação
> per-blueprint, na seção "A conta do lucro").

> **Por que dois links:** o `[TCG]` é o seu jeito padrão de **conferir** o preço
> antes de comprar. O `[oferta]` te leva direto à carta no CardTrader.

A tabela aparece **na tela** quando o postprocess roda, e também é salva num
arquivo de texto `.md` ao lado da planilha (mesmo nome, terminação `.md`) — é só
copiar e colar no chat.

> **Detalhe técnico (pode pular):** a tabela do chat **junta** colunas (Carta =
> nome+número; Links = oferta+TCG) só pra ficar legível. A planilha (`.xlsx`) e
> os arquivos `.csv`/`.json` continuam com **colunas separadas e os endereços
> (URLs) crus**, do jeito que ferramentas de importação esperam. Margem, filtros
> e classificação (COMPRA/REVISAR/NÃO) **não mudaram** — só a apresentação.

---

## Coluna DH — 2ª opinião do Double Holo (opcional)

O postprocess aceita `--doubleholo <arquivo.json>`: adiciona uma coluna **DH**
(nota 0-100; 50 = neutro; >50 = Double Holo otimista) que resume a leitura de
mercado do Double Holo pra carta (previsão de preço, sinal de IA, ROI de
gradação, momentum). Regras duras:

- **NÃO entra na margem nem na decisão COMPRA/REVISAR** — o preço de referência
  continua sendo o TCGplayer (pokemontcg.io/tcgcsv). É coluna **extra**, uma
  segunda opinião.
- O JSON canônico vem de `scanners-commons/tooling/doubleholo_signals.py ingest
  --json` (a nota `dh_score` é calculada UMA vez lá; `doubleholo_join.py` daqui
  só a **lê**, nunca recalcula — pra não haver fórmulas divergindo entre repos).
- **Join determinístico por productId do TCGplayer** — nunca por nome. Linha
  sem productId resolvido mostra "—" (honesto; não inventa).
- Pras linhas precificadas via pokemontcg.io (cujo Link TCG é um redirect por
  cardId, sem productId), o resolver offline `tcgcsv_productid.py` resolve o
  productId via tcgcsv (bulk por set, sem seguir redirect HTTP), com
  desambiguação por variante; se não resolver pra exatamente 1 productId →
  `None` → "—". Honestidade > cobertura: nunca chuta. `--no-pid-resolve`
  desliga esse resolver (só tem efeito junto com `--doubleholo`).
- Se o JSON falhar ao carregar, o postprocess avisa ("--doubleholo ignorado") e
  a entrega segue **sem** a coluna DH, idêntica ao comportamento sem a flag.

---

## Cuidados — "achados" que costumam ser falsos

- **Cartas "Trainer Gallery" (código começa com `TG`)**: o preço de referência
  vem inflado (5 a 10×). O relatório já manda essas pra conferência manual, mas
  desconfie. (Desde o pós-v2.22/#36, `TG##` **e** `GG##` são pulados já em scan
  time — regex `^(?:TG|GG)\d+`.)
- **Coleções muito novas**: a base de preços de referência ainda é fraca nelas →
  pode faltar preço ou casar com a coleção errada.
- **Sets antigos (back-catalog)**: mercado já "eficiente" — o preço na Europa
  costuma bater com o dos EUA, então quase nunca sobra deal. Auditoria de
  2026-06-08: toda a era Sword & Shield (17 sets, ~1.000 cartas) deu **0 deal**.
  Gaste energia em **lançamentos novos** — é onde o gap aparece.
- **Use o piso de preço padrão (≈US$10)**: subir o piso (ex.: `--min-price-usd
  25`) esconde a faixa barata (US$10–25), que é justamente onde **a maioria dos
  deals mora**. No teste de 06-08, subir pra $25 derrubou os achados de 12 → 2.
- **A cópia barata pode já ter sumido ("staleness")**: o número que o scanner
  mostra é o preço de *quando ele rastreou*. Cópias baratas vendem rápido —
  quando você for comprar, pode só restar a cara. **Confira o preço ao vivo
  antes de comprar.** (Ex. 06-08: Arceus VSTAR scan R$54 → real R$75 → virou
  prejuízo.)
- **Coluna "Variante Baixa Confiança" (jun/2026; reforçada em v2.24)**: quando
  aparece "Sim", a carta foi anunciada como **não-brilhante** mas o único preço
  de referência encontrado era de uma versão **brilhante cara** — OU (novo em
  v2.24) é uma comum/incomum **reverse** cujo preço de referência reverse é um
  número **fino e fora da curva** vs a versão normal (mais de 5× o normal; ex.:
  Lileep ex12-56 normal US$0,55 vs reverse US$37,50 = 68×). Em ambos os casos o
  preço pode ser da versão errada / de pouca liquidez → a margem pode estar
  inflada. **Confira a versão no Link TCG antes de comprar.** A margem e o preço
  **não mudam** — mas a partir de **v2.24** essa linha é **rebaixada de COMPRA
  para REVISAR** ("validar manual"): nunca mais aparece como COMPRA limpa. (Não
  rebaixa o que já era NÃO: margem baixa, TG##, STALE seguem NÃO.)

> **Não rode dois scanners na mesma pasta de estado ao mesmo tempo.** A partir de
> jun/2026 (v2.14) o programa **recusa** iniciar um segundo scanner que use a
> mesma pasta de estado (ele avisa com uma mensagem clara), porque dois ao mesmo
> tempo brigavam pelo mesmo arquivo de cache e ficavam lentíssimos. Se algum dia
> você precisar mesmo rodar dois, use pastas de estado diferentes (`--state-dir`)
> ou a opção `--allow-concurrent`.

---

## Coleções vintage (e ME) demoram mais — e o programa já sabe disso

O programa tem um **limite de tempo por coleção** (chamado *per-set-timeout*):
se uma coleção demora demais pra ser rastreada, ele desiste dela pra não travar
o rastreio inteiro, e a coloca numa **lista de pulos** (*skip-list*) pra não
tentar de novo logo em seguida. O padrão é **8 minutos por coleção**.

O problema (descoberto em jun/2026): algumas coleções **vintage** (antigas, com
muitas cartas) precisam de bem mais que 8 minutos. Elas estouravam o tempo
**toda vez**, entravam na lista de pulos e **nunca eram rastreadas por completo**
— um ciclo sem fim. Era preciso lembrar de mandar um tempo maior à mão toda vez.

**O conserto (v2.15):** o programa guarda, no próprio código
(`SET_TIMEOUT_OVERRIDES`), um **tempo maior só pra essas coleções específicas**
— você não precisa lembrar de nada. Lista atual (verificada no código):

- `df` (EX Dragon Frontiers) — **20 min**;
- `ds` / `n1` / `n4` — **18 min**;
- `cg` / `g1` / `g2` / `tr` / `hp` / `aq` — **18 min** (adicionados no Lote 1 de resiliência,
  2026-11: estouravam os 8 min no run de 2026-06-27);
- `cri` (Chaos Rising, era Mega Evolution / me4 — adicionado no #47) —
  **20 min**: a pokemontcg.io não precifica o set, então (no caminho antigo
  `--provider pokemontcg`) ele caía no fallback tcgcsv per-listing, que é lento.

Se um dia você quiser dar ainda mais tempo a todas, o `--per-set-timeout 25`
(em minutos) ainda vale e vence o ajuste interno. Notas:

- `n2` (Neo Discovery) **NÃO** recebe override de propósito: a base de preços
  quase não tem essa coleção — o problema dela não é tempo, é falta de
  referência (tratado pelo cap de `--max-consecutive-misses`, não por timeout).
- `asc` (Ascended Heroes) também **NÃO** precisa de override: o resgate tcgcsv
  dele é um bulk único, não per-listing — mas exige o gotcha do
  `--max-consecutive-misses > 0` (ver "Como rodar").

---

## Desfecho de cada set, skip-list e resgate tcgcsv (Lote 3, 2026-11)

- **Quatro desfechos por set** (gravados no `set_complete` do checkpoint e no
  resumo do run): `complete` (tudo precificado) · `complete_with_unpriced` (o set
  foi coberto; N ofertas ficaram sem referência e estão na aba "Sem preço") ·
  `no_coverage` (a fonte respondeu e **nada** do set foi precificado) ·
  `operational_failure` (timeout, 5xx, erro de rede, erro inesperado, falha em
  massa de preço, tcgcsv fora do ar no resgate — **tentar de novo**; aparece no
  resumo como "NÃO CONCLUÍDOS — tentar de novo").
- **Skip-list só para `no_coverage` de verdade:** corte por misses consecutivos
  **e** nada do set precificado (nem pelo resgate) **e** o resgate não falhou.
  Falha operacional **nunca** entra na skip-list.
- **Validação: run novo NUNCA reaproveita validação** (regra do operador: nada
  de cache de scans anteriores para fundamentar recomendação de compra). Todo run
  valida do zero; cada linha validada carrega `Validado em` (data/hora com fuso)
  e `Validação` (`nova` | `reaproveitada`). Única exceção, com opt-in explícito:
  `--resume-validation` retoma a validação de um run **interrompido** (sem o
  marcador `validation_complete`) validada há ≤ 3 h, e só para a oferta com o
  **mesmo preço de oferta e a mesma referência**; a linha reaproveitada sai
  marcada. Rodar de novo com o mesmo `--output` **arquiva** o checkpoint anterior
  (`*.prev`, nunca apaga) e começa um checkpoint limpo — oportunidades de dois
  runs não se misturam no recovery. Referência/câmbio buscados antes do início do
  run nunca são lidos (`Cache.begin_run`). Ctrl-C no meio: o set em curso vira
  `operational_failure` (`interrupted_by_user`), o que faltava vai para "Sem
  preço", sets não iniciados ficam como `interrupted_not_started`, o XLSX parcial
  e o resumo são escritos e o processo sai com código 130. Exceção inesperada no
  meio do set: o que faltava vai para "Sem preço" (falha operacional) — a soma
  precificadas + sem preço = total vale sempre. `/groups` do tcgcsv: 3 tentativas
  com espera curta e cache negativo de ~3 min dentro do run.
- ⏱️ **Tempos dos grupos medidos em 2026-11-24** (tcgcsv como fonte principal, valida todas as candidatas, sem top-N): G1 3,5 · G2 2,4 · G3 1,2 · G4 1,0 · G5 0,7 (26 sets, com md/la/dp/ar/dpbsp) · G6 0,9 min; `--vintage` (34 sets) 1,2 min. **Não medido** com `--provider pokemontcg`.
- **Resgate tcgcsv** (caminho `--provider pokemontcg`): tudo que a pokemontcg.io não precificou (misses do fim do
  set, falhas, listings não alcançados) é oferecido ao tcgcsv (referência buscada
  **neste run**, correspondência exata de edição e acabamento). Cada linha leva `Fonte Preço` e
  `Ref. Data/Hora`. Resgate parcial **nunca** é "completo".
- **Nada some:** listings sem preço vão para a aba **"Sem preço"** do XLSX
  (motivo: `sem_referencia_na_fonte`, `falha_operacional` ou `nao_alcancado`) e contam em
  `Stats` (`sets_operational_failure`, `sets_no_coverage`, `listings_sem_preco`).

---

## Edição, acabamento e referência compatível (B1, 2026-11)

- **Correspondência EXATA** (decisão do dono): a oferta tem edição (`first_edition` do
  `properties_hash`: 1st Edition / Unlimited) e acabamento (Normal / Holo / Reverse). A
  referência só vale se a chave de preço tiver o **mesmo par**; não existe mais escada de
  fallback (reverse→holofoil→normal), nem exclusão de 1st Edition, e Shadowless nunca é
  referência. A lógica mora em `ct_variants.py` (única); os providers pokemontcg e tcgcsv
  (primário e resgate) só chamam `match_reference_variant`.
- **Sem referência compatível = sem margem e sem recomendação.** A oferta vai para a aba
  **"Sem Ref Compatível"** (carta, set, nº, edição, acabamento, preço CT, link, motivo, chaves
  que a fonte tinha) e para o checkpoint. **Não** conta como miss de cobertura (não entra na
  skip-list). A soma fecha em todo caminho: precificadas + sem preço + sem ref compatível =
  total de ofertas (inclusive após exceção ou Ctrl-C).
- **Colunas do XLSX:** `Edição` (`1st Edition` | `Unlimited` | `Sem divisão de edição` para
  carta sem divisão, ex. moderno; célula vazia = não informada), `Acabamento`, `Ref Compatível`
  (`Sim` só com par idêntico) e `Variant` (a chave de referência usada). Dedup: `uid` inclui
  edição e reverse (1st/Unlimited do mesmo vendedor viram linhas separadas).
- **Per-blueprint** só considera ofertas da MESMA edição; sem `first_edition` no payload (quando
  a oferta é 1st, ou a chave existia no scan) o status é `NAO_CONFIRMAVEL` com o motivo.
- **Margem:** só `ct_economics.compute`. O corte (`--threshold`) é `margem_venda` (sobre a
  venda; ROI é outra métrica). `--hub-fee` (default 0,06) agora só alimenta as colunas
  **líquidas** de preço cru; o preço validado do checkout já embute o Hub
  (`compra_inclui_hub=True`) — nunca contado duas vezes. Frete de compra fixo R$ 0,50
  (`--shipping-brl` > 0 substitui). **Chase:** regra única em `ct_chase.py`, só informativa.
- Raridades vistas na CardTrader (leitura real, par/twm/sfa/obf/pal): Common, Uncommon, Rare,
  Holo Rare, Ultra Rare, Secret Rare, Illustration Rare, Special Illustration Rare, Rare ACE,
  Promo. A CardTrader **não** envia "Double Rare" (usa "Ultra Rare"); todas as grafias de holo
  são reconhecidas por `ct_variants.holo_detection` com a data de lançamento do set
  (`releaseDate` da pokemontcg.io; `publishedOn` do group no tcgcsv).

### B1b — fallback tcgcsv, entrega completa, cobertura

- **Fallback tcgcsv para ref incompatível** (só no caminho `--provider pokemontcg`; no padrão o tcgcsv é a fonte principal e a resposta incompatível dele NÃO vai à pokemontcg.io): se a pokemontcg.io acha a carta mas sem a variante
  exata, a oferta vai ao tcgcsv (mesma regra exata; grupo Shadowless nunca). Se o tcgcsv
  também não resolve, UMA linha em "Sem Ref Compatível" com os dois motivos (um por fonte).
  `Fonte Preço` diz quem precificou.
- **Fonte e data na entrega:** colunas `Edição`, `Acabamento`, `Fonte ref.`, `Data ref.`. A data é a
  do DADO quando a fonte expõe (tcgcsv: `last-updated.txt` do dump diário; pokemontcg.io:
  `tcgplayer.updatedAt`) com o rótulo "dado de"; senão "buscado em" (hora da busca).
- **Entrega completa:** o canônico não usa `--top-md`; com limite o cabeçalho diz "mostrando N de M" e
  o rodapé diz quantas ficaram fora (aba `Deals`). O rodapé e a aba Summary mostram ofertas buscadas →
  após filtros (texto dos filtros e o piso) e quantas `--chase-only`/`--opportunities-only` descartaram.
- **Líquidas do XLSX do scanner** (`Net Margin %…`, `Lucro R$ REAL`) usam só Hub + frete: colunas
  `Líquida` = PARCIAL e `Custos Não Informados`.
- **Cobertura:** com provider em lote (tcgcsv) NÃO há corte por misses (o set já está em memória);
  no caminho por oferta o corte conta CARTAS distintas, não ofertas. Set cortado com ofertas "não
  alcançadas" NÃO é completo: desfecho `operational_failure` (`coverage_interrupted_N_not_reached`,
  "tentar de novo").
- **Chase** não entra em nenhum score/ordenação (só a coluna `Chase Tier`). Raridade da CT
  inconclusiva (Promo, vazia) + referência com UM só acabamento: a regra exata NÃO muda; o motivo
  só registra o acabamento que a referência tem.

### B1e/B1f — disjuntor da fonte, idade da referência, conflito de rótulo

- **Disjuntor da fonte principal (caminho `--provider pokemontcg`: pokemontcg.io → tcgcsv em lote; com o padrão tcgcsv a fonte já é em lote):** o scanner mede a saúde da fonte
  POR OFERTA (janela das últimas N: falha de infra — 5xx, timeout, 4xx≠429 — ou oferta que só respondeu
  depois de retry 5xx — e latência). Passou do limite = fonte degradada: o resto do set e os sets
  seguintes vão direto ao tcgcsv (mesma regra exata); uma sonda barata (consulta de carta real) decide
  quando voltar. Nunca grava skip-list. Flags: `--source-fail-rate` (FRAÇÃO 0-1, padrão 0.5),
  `--source-slow-s` (latência média, padrão 15 s), `--source-window` (padrão 10),
  `--source-probe-s` (padrão 120 s), `--no-source-breaker`. Registro: log, nota do `set_complete` e resumo
  ("pokemontcg.io degradada às HH:MM …; K sets atendidos pelo tcgcsv").
- **Desfecho = cobertura FINAL:** falha operacional só quando sobra oferta sem resposta válida de qualquer
  fonte; set atendido pelo resgate sai completo, com a contagem por fonte na nota.
- **Idade da referência:** `--max-ref-age-days` (padrão 7; **o valor definitivo é do dono** — o 7 é
  provisório) no scanner (troca a referência velha da fonte principal pela do tcgcsv quando há
  compatível mais nova, registrada na coluna `Troca de Referência`) e no postprocess (linha mais velha
  leva "referência desatualizada (N dias)" e nunca sai COMPRA; margem continua exibida). O rodapé mostra,
  por fonte, o dado mais antigo, o mais novo e a idade.
- **Conflito de rótulo de acabamento:** raridade CardTrader conclusiva p/ não-holo + produto holo COM
  impressão normal = `VARIANTE_INCOMPATIVEL` ("raridades em conflito"); sem impressão normal (carta só
  existe em holo) vale holo. `publishedOn` do tcgcsv com o carimbo do lote não é data de lançamento.
- **Acabamento declarado × inferido (B1g/B1h):** `Ref Compatível` = `Sim` só quando o acabamento sai do rótulo da
  própria CardTrader; `Inferido` (coluna "Acabamento Inferido (motivo)") quando foi deduzido da referência
  (carta só existe em holo; set holo-only `det`; rótulo CT desconhecido; **promo vazia/"Promo" com UMA única
  impressão normal**). Inferido tem margem exibida, nunca COMPRA, e é contado por set no resumo. Ponto único
  da decisão do dono: `ct_variants.INCONCLUSIVE_SINGLE_PRINT_POLICY` (hoje `{"normal": "inferir", "holo": "inferir"}`,
  decisão do dono 2026-11-24: raridade vazia/"Promo"/"Fixed" com UMA única impressão, normal ou holo, vira
  Inferido; o valor `"sem_referencia"` desliga a inferência daquele acabamento) e `NO_INFERENCE_CT_RARITIES`.
  Mais de uma impressão não-reverse = sem referência compatível.
- **Referência ambígua (B1i/B1j):** dois produtos DIFERENTES da referência na mesma chave (ex.: wiz Mew "08/53" × "Mew - 8 (Glossy Finish)"),
  duas linhas do mesmo subtipo no mesmo produto com preços diferentes, ou vários resultados da pokemontcg.io para a mesma carta = AMBÍGUA:
  nunca "um dos dois" (nada de last-wins, `results[0]`, ordem ou preço). Só casa se dado declarado da oferta desempata (número completo com
  denominador ou nome exato do produto); senão sem referência compatível, motivo "referência ambígua: N produtos com a mesma chave".
  Rótulo CT inconclusivo QUALQUER (vazio/Promo/"Fixed"/desconhecido) segue a política de única impressão — nunca "Sim". Idade da
  referência ausente, negativa ou futura = desconhecida = REVISAR.
- **Motivo com fontes:** "Sem Ref Compatível"/"Sem preço" listam as fontes consultadas e as NÃO
  consultadas com a causa; o fallback vale nos dois sentidos (`--provider tcgcsv` consulta a
  pokemontcg.io quando saudável). Set com menos da metade precificada (todos os motivos) é destacado no
  resumo e no rodapé.

### B1g–B1k — como o código decide hoje (resumo em linguagem simples)

- **De onde vem o preço:** o `--provider` padrão é `tcgcsv` (o dump diário do TCGplayer, em lote por set).
  A pokemontcg.io só é consultada quando o tcgcsv ACHOU a carta mas ela está SEM preço na chave certa
  (`CARTA_SEM_PRECO`). Se o tcgcsv respondeu "variante incompatível" ou "referência ambígua", essa resposta
  vale: o scanner **nunca** a troca por um preço da outra fonte para "salvar" a linha.
- **Inferido:** quando a raridade da CardTrader não diz o acabamento (vazia, "Promo", "Fixed"/BREAK, rótulo
  desconhecido) e a referência tem UMA só impressão não-reverse (normal ou holo — política
  `INCONCLUSIVE_SINGLE_PRINT_POLICY`, hoje `inferir` nos dois), o acabamento é deduzido da referência. A margem
  aparece (estimada), a linha leva `Ref Compatível = Inferido` e a coluna "Acabamento Inferido (motivo)", e a
  decisão é **sempre REVISAR, nunca COMPRA**. Com mais de uma impressão não-reverse não se adivinha: sem referência.
- **Ambiguidade = sem referência, sem preço:** vários produtos com a mesma chave (número), o mesmo subtipo duas
  vezes no mesmo produto com preços diferentes, ou mais de uma impressão possível. Só desempata dado
  declarado da oferta (número completo com denominador, ou nome exato do produto). Senão a linha vai para
  "Sem Ref Compatível" com o motivo — nunca "um dos dois", nunca ordem de chegada ou preço.
- **Idade da referência:** `--max-ref-age-days` (padrão 7, no scanner e no postprocess). Idade desconhecida
  (fonte sem data do dado, "buscado em", data inválida ou **futura**) ou acima do limite impede COMPRA; a
  linha vai a REVISAR e a margem continua visível. No scanner, referência velha da fonte principal é trocada
  pela do tcgcsv só se houver uma compatível mais nova (coluna `Troca de Referência`).
- **Divergência entre referências (postprocess):** `--max-ref-divergence` (padrão 0,30, fração da MAIOR das
  duas). Com preço PriceCharting compatível (mesma edição/acabamento, ungraded) que diverge acima disso, a linha
  vai a REVISAR ("referências divergem"). Se o PC é MENOR que a TCG, a margem recalculada pela menor referência
  também precisa passar o corte de 30%; senão REVISAR. Sem PC compatível vale só a regra de liquidez.
- **Liquidez e PriceCharting:** COMPRA exige ≥5 vendas em 90 dias (`--min-sales-90d`) e ≥1 em 30
  (`--min-sales-30d`) na página da MESMA edição; sem dado → REVISAR. `--pc-refs N` limita consultas únicas;
  `--pc-firecrawl N` paga Firecrawl só quando o PC bloqueia, com **teto de 100 créditos por scan** (acima disso
  o comando recusa). Linha que sobrou sem consulta porque o orçamento acabou fica com o status
  `NAO_CONSULTADO_ORCAMENTO` (não é falha da fonte). A coluna **"PC Motivo"** diz, linha a linha, por que o PC
  não foi consultado ou não serviu (edição não informada, bloqueio, orçamento…). O rodapé conta consultas
  únicas, duplicadas evitadas, por status, e os créditos usados.
- **B1l (versão de preço "4", `PRICE_LOGIC_VERSION`):** preço em cache de versão antiga não é reaproveitado.
  COMPRA com PriceCharting `OK` exige as DUAS referências válidas: PC compatível mas sem mediana (ou TCG
  ausente/não positivo) vai a REVISAR ("PC compatível sem mediana (motivo)"). A flag "PC diverge" da tabela
  usa o mesmo `--max-ref-divergence` da decisão (antes era um limite próprio). A skip-list grava o
  `provider` de quem a escreveu e só vale para ele: entrada sem provider (antiga) ou de outro provider é
  reavaliada (um `no_coverage` da pokemontcg.io não diz nada sobre o tcgcsv); o log avisa quais sets
  foram reavaliados por isso. `--no-tcgcsv-fallback` só tem efeito com `--provider pokemontcg` (com o padrão
  tcgcsv não há fallback tcgcsv a desligar).
- **B1m (validação per-blueprint):** a API real devolve o preço como `price: {cents, currency}`; a validação lê
  esse formato (o antigo `price_cents`/`price_currency` solto só como fallback). Preço live ausente, zero ou
  não finito = status `PRECO_INVALIDO`: a linha segue no XLSX, nunca vira `VALIDATED_REAL`/markup, e o postprocess
  a manda a REVISAR com "preço não validado" (nunca "sem referência"). O processo sai com **código 3** quando há
  candidatos validados e NENHUM tem preço live válido (aviso de que a validação não funcionou). Set cujas ofertas
  ficaram sem referência compatível/ambígua (a fonte TEM a carta) é `complete_with_unpriced`, não `no_coverage`:
  não vai para a skip-list.
- **Contadores:** o resumo e o rodapé contam por fonte (derivados das linhas, não de variáveis soltas),
  incluindo quantas linhas saíram Inferido por set.

### B1n–B1q — códigos de saída, canário de formato e a nota do câmbio

- **Tabela única de códigos de saída** (a fonte é o comentário "TABELA DE CÓDIGOS DE SAÍDA" em
  `cardtrader_scanner.py`; os `.ps1` só referenciam). Precedência com várias condições: 22 > 21 > 23 > 20; 130 vence tudo.

| Código | Quem | O que significa | O que o launcher `.ps1` faz |
|---|---|---|---|
| 0 | scanner | ok | roda o postprocess |
| 1 | scanner | erro fatal (`CT_JWT` ausente/ilegível, exceção) | aborta (sai com 1) |
| 2 | scanner | argumentos inválidos ou run-guard (outro scan no mesmo `--state-dir`); nada foi escrito | aborta (sai com 2) |
| 20 | scanner | validação per-blueprint PARCIAL (erro de API e/ou moeda não suportada em alguns candidatos); XLSX completo | roda o postprocess se o XLSX bruto foi escrito NESTE run; termina com 20 |
| 21 | scanner | NENHUM preço live válido (0/ausente/não finito); XLSX completo, linhas REVISAR | idem 20; termina com 21 |
| 22 | scanner | validação falhou por completo (erro de API em TODOS os candidatos) | idem 20; termina com 22 |
| 23 | scanner | scan concluído, mas há set(s) em falha operacional (canário de formato, 5xx, rede, disjuntor, timeout); vale também com `--validate-top 0` | idem 20; termina com 23 |
| 96 | launcher | o postprocess falhou: nenhuma entrega gerada (vence o código do scanner) | sai com 96 |
| 97 / 98 / 99 | launcher | venv do Python / arquivo de códigos de set / pasta do repo ausentes | sai com o código, sem rodar nada |
| 130 | scanner | interrompido (Ctrl-C); XLSX parcial | aborta (sai com 130) |

  Nos códigos 20-23 o XLSX bruto só é aproveitado se foi gravado durante o run atual (um arquivo de run anterior
  nunca é reaproveitado). Sem saída 0 silenciosa: o launcher termina com o código do scanner quando ele não é 0.
- **Cabeçalho da entrega:** o postprocess imprime, a partir das abas de desfecho do scanner, uma linha por tipo:
  "⚠ N set(s) NÃO avaliados por falha operacional: … — tentar de novo" (a ausência de deals neles não significa
  nada), "N set(s) sem cobertura: …" e "N set(s) pulados pela skip-list (decisão registrada, não avaliados neste
  run)". Sem essas abas (XLSX antigo) o cabeçalho diz que não dá para afirmar que todos os sets foram avaliados.
- **Canário de formato da API:** chaves obrigatórias do listing: `graded`, `condition`, `pokemon_language` e
  `user.username`. Listing sem alguma delas é descartado e contado. Se, num set, uma chave falta em pelo menos 2
  listings E em ≥10% deles (ou em todos), ou se TODAS as ofertas foram descartadas, o formato da API mudou: o set sai
  `operational_failure` com motivo `api_format_changed_<chave>` (nunca complete nem sem cobertura; não vai para a
  skip-list) e o run termina com código 23. As ofertas válidas desse set NÃO seguem para precificação.
- **`pokemon_reverse` ausente:** a oferta segue, mas o acabamento não foi declarado pela CardTrader: vira Inferido
  (REVISAR), com o motivo "campo pokemon_reverse ausente no payload". `user_type` e `can_sell_via_hub` ausentes têm
  default seguro e só são contados.
- **Funil de ofertas:** o resumo diz "baixadas N = após filtros + duplicadas + reprovadas nos filtros + sem
  blueprint + sem preço CT válido + payload inesperado + moeda não suportada + descartadas pelo canário"; a soma fecha.
- **Colunas de preço:** `Preço CT validado (R$)` é SÓ o preço de checkout (LIVE) validado, vazio se não validou;
  `Preço usado na conta (R$)` é o que entrou na margem (o validado, ou o preço cru do scan quando não houve validação).
  Em linha não validada `Preço CT validado (R$)` fica VAZIO, inclusive no XLSX (o hyperlink de preço não escreve em célula vazia).
- **Nota honesta sobre o câmbio (informada pelo dono, medida no checkout):** o preço do scan por expansão vem em USD
  e é convertido pelo câmbio oficial (~5,87), mas o checkout em BRL da CardTrader sai cerca de 17,6% acima (cotação
  efetiva ~6,90; ~7,80 em alguns vendedores). Por isso a margem de linha NÃO validada está inflada: só a margem com
  preço validado (LIVE) vale para decisão.

## Scanner paralelo: Dragon Ball Super (`dbs_scanner.py`)

> **Decisão do operador (2026-07-17):** a frota era Pokémon-only e deixava passar
> deals de Dragon Ball no CardTrader (ex.: energy markers **Gold** e promos
> **Release Event/Tournament Winner** do set Fusion World Promos — caso real que
> motivou a ferramenta). O `dbs_scanner.py` cobre esse buraco SEM tocar o fluxo
> Pokémon: é um script separado, que **não** passa pelo skill `/scan` (que segue
> Pokémon-only) e não usa pokemontcg.io.

- **O que faz:** varre expansões de **Dragon Ball Super** no CardTrader
  (game_id 9 — Fusion World `fb*`/`fs*`/`fuspromo` + Masters `bt*`) com ofertas
  **AO VIVO** do marketplace (menor NM inglês não-graded) e compara com o
  **market price do TCGplayer** via tcgcsv.com (categorias 80 + 27).
- **Join oferta↔referência DETERMINÍSTICO:** `blueprint.tcg_player_id` ==
  `productId` do tcgcsv (mesma filosofia do join DH por productId). Blueprint sem
  `tcg_player_id` (comum nos sets Masters antigos) passa por um **join
  SECUNDÁRIO** também determinístico: nome EXATO normalizado + cauda do número,
  **match único obrigatório e só blueprint SEM versão** (variante Gold/Alt Art
  nunca entra) — rotulado por linha na coluna `join` do CSV. O que sobrar fica
  **FORA com contagem explícita** — nunca fuzzy por nome, nunca preço inventado.
- **Convenções:** a **margem sobre a VENDA** `(TCG_BRL − CT_BRL)/TCG_BRL` decide
  o corte (`--threshold` 0.30); o **ROI** `(TCG_BRL − CT_BRL)/CT_BRL` é só
  informativo (coluna "ROI aquisição %", não filtra nem ordena). Ct ou tcg ≤ 0
  → linha fora, contada em "sem preço válido" e avisada no stderr.
  `--threshold` em **FRAÇÃO** (0.30; passar `30` aborta com erro); piso de
  relevância na referência (`--min-price-usd 10`); NM por match **EXATO**
  `== "Near Mint"`; graded/assinada nunca entram; oferta <50% da referência vai
  pro bucket 🚨 REVISAR (possível lixo/scam), nunca vira COMPRA limpa.
- **Filtro de SINGLES (v1.1, 2026-07-18):** os blueprints de uma expansão vêm
  com **selados misturados** (packs, booster box, premium box) — e selado com
  `tcg_player_id` casava na referência e saía na entrega como carta (vazamento
  real do catálogo 2026-07-17: a linha "Collector's Selection Vol.2"). Agora só
  blueprint **com `collector_number`** entra; os demais são pulados com
  contagem própria na cobertura ("selados/acessórios pulados"). Regra provada
  na API em 2026-07-18 (games 9 e 15: todo blueprint sem número era selado).
- **Câmbio:** `--fx` manual OU automático (open.er-api.com) — sem fonte real o
  run **falha alto** (nunca chuta). Ofertas em moeda sem taxa conhecida são
  puladas e contadas.
- **Entrega:** tabela markdown canônica da frota gerada pelo próprio script
  (buckets 🟢 COMPRA / 🚨 REVISAR / 🔎 Quase + contagens honestas de cobertura;
  `Links` = `[oferta](cardtrader) · [TCG](tcgplayer)` em toda linha) + CSV com
  TODAS as linhas avaliadas em `outputs/` (gitignored). Cache tcgcsv em
  `outputs/dbs_cache/` (TTL 20h).
- **Run longo nunca fica mudo:** o `.md`/`.csv` são regravados CUMULATIVAMENTE a
  cada expansão concluída, com marcador `⏳ PARCIAL — N/M expansões` no cabeçalho
  até o fim (dá pra entregar parcial no chat a qualquer momento). No `--all` a
  varredura vai das expansões mais novas pras antigas. Sidecar
  `<out>_semref.csv` lista todo blueprint COM oferta NM viva que ficou sem
  referência TCG, com o motivo — nada some em silêncio.
- **Como rodar:**

  ```bash
  python dbs_scanner.py --list-expansions              # códigos disponíveis
  python dbs_scanner.py --expansions fuspromo --threshold 0.30
  python dbs_scanner.py --all --threshold 0.30         # catálogo DBS inteiro (lento)
  ```

- **Contratos travados em teste:** `tests/test_dbs_scanner.py` (35 testes
  offline — filtros NM/EN/graded, conversão de moeda, joins por tcg_player_id e
  secundário nome+número, piso, guardas anti-lixo e de referência volátil,
  filtro de singles/selados, fração no threshold, marcador PARCIAL, motivos do
  semref, 2 links por linha).
- Primeira prova real (2026-07-17, `fuspromo`): 545 blueprints → 163 avaliadas →
  21 COMPRA ≥30%, incluindo os casos que motivaram a ferramenta.
- **Irmão da família:** scanner de ONE PIECE (`op_scanner.py`, mesmo molde) —
  ver a seção própria logo abaixo.

## Scanner paralelo: One Piece (`op_scanner.py`)

> **Origem (2026-07-18):** pedido do operador em 2026-07-17, executado a partir
> do handoff `scanners-commons/HANDOFF-ONEPIECE-SCANNER.md` (handoffs são
> gitignored AQUI de propósito; o lar deles é o scanners-commons). É o irmão do
> `dbs_scanner.py` — mesmo molde, mesmos invariantes, mesma entrega — para o
> **One Piece Card Game**.

- **O que faz:** varre expansões de One Piece no CardTrader (**game_id 15**,
  93 expansões: `op01`…, starters `st*`, promos) com ofertas **AO VIVO** do
  marketplace (menor NM inglês não-graded) e compara com o **market price do
  TCGplayer** via tcgcsv.com (**categoria 68** = catálogo INGLÊS; cache próprio
  em `outputs/op_cache/`, TTL 20h — nunca compartilhado com o `dbs_cache/`).
- **⚠️ Idioma é o risco nº 1 deste jogo — e está travado em teste:** o CT vende
  MUITO One Piece JP (no OP-01, **18% das 15.986 ofertas** eram jp/zh-CN/kr).
  A chave real na oferta é `onepiece_language` (provada com oferta JP real em
  2026-07-18); qualquer valor ≠ EN é rejeitado. Na validação manual do primeiro
  scan, as ofertas mais baratas das DUAS linhas entregues eram JP/asiáticas —
  sem esse filtro a margem sairia de produto errado (lição do guard JP do
  ebay-arbitrage-scanner).
- **Filtro de SINGLES:** igual ao v1.1 do dbs — selados vêm misturados nos
  blueprints (no OP-01: booster box com 13 ofertas vivas e `tcg_player_id`);
  só blueprint com `collector_number` entra, o resto é contado como
  "selados/acessórios pulados". Alt arts são blueprints próprios com sufixo no
  número (`OP01-001a`/`OP01-064b`) e `tcg_player_id` próprio (97% de cobertura
  no OP-01 → join primário domina); o sufixo é PRESERVADO no join secundário
  (alt art nunca colapsa na carta base). DON!! são singles legítimos (o piso
  US$10 os corta). Raridade em `fixed_properties["onepiece_rarity"]`.
- **Todo o resto é idêntico ao dbs_scanner** (joins primário/secundário,
  guardas anti-lixo e de referência volátil, câmbio com falha-alta, parciais
  cumulativos `⏳ PARCIAL — N/M`, sidecar `_semref.csv`, entrega canônica
  🟢/🚨/🔎 com 2 links por linha, threshold em FRAÇÃO com trava, CSV completo
  em `outputs/` gitignored). Backlog registrado: extrair um núcleo comum
  (`ct_tcg_core.py`) pros dois scanners — o handoff mandou não bloquear a v1
  por isso.
- **Como rodar:**

  ```bash
  python op_scanner.py --list-expansions              # códigos disponíveis
  python op_scanner.py --expansions op01 --threshold 0.30
  python op_scanner.py --all --threshold 0.30         # catálogo OP inteiro (lento)
  ```

- **Contratos travados em teste:** `tests/test_op_scanner.py` (37 testes
  offline, espelho do test_dbs_scanner + os específicos: chave real
  `onepiece_language` com os 4 valores observados, booster box nunca vira
  linha, sufixo de alt art preservado no `_num_tail`, raridade onepiece).
- **Primeira prova real (2026-07-18, `op01`):** 165 blueprints = 156 singles +
  9 selados pulados → 29 avaliadas → 1 COMPRA ≥30% (Monkey.D.Luffy Leader
  OP01-003, 49,2%) + 1 quase (Perona Box Topper). Contagens batem 1:1 com a
  sonda da API; menor oferta EN NM e referência tcgcsv das 2 linhas
  reconferidas ao vivo. Set de 2022 = back-catalog eficiente (coerente com a
  auditoria Pokémon da frota) — deal mora nos lançamentos; catálogo completo =
  `--all`.

## Testes

```bash
python -m pytest              # Windows: .venv\Scripts\python.exe -m pytest
```

- **281 testes** coletados (verificado com `python -m pytest -q` em
  2026-07-18, após `pip install -r requirements.txt`: 281 passed).
- O `pytest.ini` escopa a coleta a `testpaths=tests` **de propósito**: os
  `scripts/test_*.py` são run-scripts standalone (testes operacionais rodados à
  mão), deliberadamente fora da suíte do pytest.
- Testes que travam contratos importantes: `tests/test_scan_skill_profiles.py`
  (partição dos 6 grupos do `/scan`) e `tests/test_doubleholo_join.py`
  (join da coluna DH).

---

## Arquitetura (o que é cada arquivo)

```
cardtrader_scanner.py       o scanner: varre o CardTrader, precifica (tcgcsv principal; pokemontcg.io só 2ª fonte) e grava o XLSX cru
cardtrader_postprocess.py   o relatório: classifica COMPRA/REVISAR/NÃO e gera a tabela de ENTREGA (build_delivery_markdown)
dbs_scanner.py              scanner PARALELO de DRAGON BALL (Fusion World/Masters): CT ao vivo vs TCGplayer — ver seção própria
op_scanner.py               scanner PARALELO de ONE PIECE (game 15 / tcgcsv cat 68): mesmo molde do dbs — ver seção própria
doubleholo_join.py          coluna DH (2ª opinião Double Holo) — só lê a nota do JSON canônico, join por productId
tcgcsv_productid.py         resolver offline de productId TCGplayer (pro join DH; identidade, nunca toca preço)
config.yaml                 configuração
CHANGELOG.md                histórico narrativo completo (desde 2026-04-29)
pytest.ini                  escopo da suíte (testpaths=tests)
tests/                      a suíte do pytest (281 testes)
scripts/                    utilitários operacionais: recover_from_checkpoint.py, checkpoint_to_partial.py,
                            peek_deals.py, launchers .ps1 do PC do operador, e run-scripts test_*.py (fora do pytest)
diagnose_*.py (raiz)        scripts de diagnóstico pontual (jtg, no_deals, pricing)
.claude/commands/           skills /scan (canônico de scan) e /auto (modo autônomo)
.github/workflows/          tests.yml, daily-scan.yml, weekly-scan.yml (ver "Workflows")
outputs/                    planilhas/relatórios locais (gitignored — dados, não programa)
cardtrader_postprocess_legacy_v1.5.py   versão antiga preservada por referência
```

---

## Fluxo de desenvolvimento e segurança

- Os resultados (planilhas `.xlsx`, registros de execução) **não** vão pra nuvem
  — são dados, não programa. O repo é **público**: lista de deals nunca entra
  nele (nem em branch — por isso o weekly entrega por artifacts, 2026-06-18).
- Toda mudança no programa segue um ritual de segurança: cria-se uma **cópia de
  trabalho** ("branch"), faz-se a alteração lá, abre-se um **pedido de revisão**
  ("PR" = pull request) e só então junta-se ao oficial ("main"). O assistente
  nunca altera o oficial direto. *(Você não precisa fazer isso à mão — é como o
  trabalho técnico é organizado.)*
- Chaves (`CT_JWT`, `POKEMONTCG_API_KEY`) moram no `.env` local (gitignored) ou
  nos Secrets do GitHub Actions — **nunca** em arquivo versionado.

---

## Glossário (as palavras técnicas que aparecem aqui)

| Palavra | O que é, em simples |
|---|---|
| **scanner** | o programa que "varre" os preços procurando oportunidades |
| **repositório / repo** | a pasta do projeto, com todo o código e histórico |
| **GitHub** | site que guarda o código na nuvem e seu histórico de versões |
| **clone** | uma cópia do projeto baixada do GitHub pro seu computador |
| **branch** | uma "cópia de trabalho" paralela, pra mexer sem afetar o oficial |
| **main** | a versão **oficial** do código |
| **commit** | um "salvar com etiqueta" — registra uma mudança no histórico |
| **push** | enviar suas mudanças pro GitHub (nuvem) |
| **PR (pull request)** | pedido pra juntar uma branch ao oficial, depois de revisar |
| **venv** | a "caixinha" isolada com as ferramentas do programa |
| **flag / opção** | um ajuste no comando, começa com `--` (ex.: `--threshold`) |
| **token** | uma senha longa que um site gera pra programas acessarem sua conta |
| **threshold** | a margem mínima de lucro pra um deal aparecer (aqui em **fração** — ver "A pegadinha nº 1") |
| **postprocess** | a etapa que pega o rastreio cru e gera o relatório organizado |
| **skill** | um runbook pronto que o assistente segue (ex.: `/scan`) |
| **workflow (Actions)** | um "robô" do GitHub que roda comandos na nuvem quando disparado |
| **artifact** | o arquivo de resultado que um workflow guarda (expira sozinho) |
| **outputs/** | a pasta onde as planilhas de resultado são salvas |

---

## Estado, pendências e histórico de versões

**Versão declarada no cabeçalho do `cardtrader_scanner.py`: v2.29**
(bookkeeping fechado em 2026-10-03). Uma linha por versão (o detalhe narrativo
completo vive no `CHANGELOG.md`):

- **v2.29** (2026-10-03): `--language <código>` no scanner (idioma das ofertas
  CT; default `en` intacto; aplicado no filtro, na listagem por expansão e na
  validação per-blueprint; registrado em Stats) + `--ratio-column`/`--min-ratio`
  no postprocess (coluna "Razão EN/<IDIOMA>" = TCG US$ ÷ CT US$, corte
  declarado, 0 linha → mensagem honesta). Motivação: scan de cartas em chinês
  ≥ 4× mais baratas que a inglesa. 13 testes novos (348).
- **v2.28** (2026-09-12, #68): mapa explícito CT → groupId tcgcsv
  (`CT_SET_TO_TCGCSV_GROUP_IDS`, 132 códigos) — fim dos sets "sem referência"
  no `--provider tcgcsv`.
- **v2.27** (2026-08-28, #63): `--pc-refs N` no postprocess — colunas
  `Ref PC US$`/`Margem PC %` (mediana das vendas REAIS do PriceCharting) +
  link `[PC]` + flag `PC diverge` nas N linhas de maior margem da entrega;
  módulo novo `pricecharting_ref.py` (guardas de slug carta+set, nunca inventa
  preço); sinal-only — margem canônica e decisão intactas. O scanner em si não
  mudou.

- **v2.26** (2026-08-22, #62): `--provider tcgcsv` — tcgcsv.com promovido a
  fonte primária SELECIONÁVEL (na época opt-in por run, com o default ainda na pokemontcg; desde a B1j o default é tcgcsv)
  após o incidente 500/502 da pokemontcg.io de 2026-08-22; prefill bulk por
  set no `scan_expansion`; set sem groupId único aborta SEM gravar skip-list;
  mapa de abbr vintage G6 (base1/base5/ecard1/ex1/ex3; `wiz`/`bog` fora —
  abbr "PR" ambígua); **fix crítico** `tcgcsv_collector_key` variant-aware
  (série H / sufixos a/b do e-Card colidiam no join digits-only e
  precificavam carta errada — latente desde v2.23, exposto pelo papel
  primário em aq/skg).
- **Pós-v2.25 mergeados** (scripts paralelos, fora do versionamento do scanner
  Pokémon): `dbs_scanner.py` v1.0/v1.1 + `op_scanner.py` (#57/#58, mergeados
  2026-07-20) — ver seções próprias; PR #56 (modo `--game dragonball` embutido
  no scanner Pokémon) fechado como **superado** pelo #57 em 2026-07-20; skill
  `/scan` alinhado com `--max-consecutive-misses 40` (antiga pendência (b),
  2026-07-20).
- **v2.25** (2026-07-03, #52): linhas near-miss chegam do scanner **sem
  `lucro_liq`** e caíam
  todas em "Dados insuficientes" no `classify_decision`, mesmo com
  `--revisar-min-net` rebaixado; agora `net_margin`/`lucro_liq` são recomputados
  **só onde faltam** (linhas validadas, que já têm valor real, não mudam).
- **Pós-v2.24 mergeados** (sem bump de versão): coluna **DH** / integração
  Double Holo (`--doubleholo`, `doubleholo_join.py`, `tcgcsv_productid.py`);
  alias `cri`→me4 + timeout override do `cri` (#47); skill `/scan` v1–v3
  (#48–#50).
- **v2.24** (2026-06-26): guard reverse-outlier — common/uncommon NÃO-holo que
  casa no `reverseHolofoil` da pokemontcg.io com razão reverse/normal absurda
  (>5×, ex. Lileep ex12-56 = 68×) dispara "Variante Baixa Confiança" e é
  rebaixada COMPRA→REVISAR no postprocess; sinal-only, margem/preço/bucket
  inalterados; constante `REVERSE_NONHOLO_OUTLIER_RATIO=5.0`.
- **v2.23** (2026-06-23): fonte de FALLBACK `tcgcsv.com` — preenche SÓ os sets
  que a pokemontcg.io não precifica (ex.: `asc`, que sem isso ficava invisível);
  resolução de set unique-match-only; MESMA seleção de variante da pokemontcg.io
  (sem colapsar pro subtype mais barato); validação per-blueprint como guard
  final; fonte rotulada via `price_source`/coluna `Fonte Preço`; opt-out
  `--no-tcgcsv-fallback`.
- **Pós-v2.22** (#36, #37): `GG##` pulado em scan time igual `TG##` (regex
  `^(?:TG|GG)\d+`); `write_xlsx` garante o diretório-alvo antes de salvar (fim
  do FileNotFoundError em clone limpo sem `outputs/`).
- **v2.22** (2026-06-22): contrato de entrega scanner→postprocess — fim da
  "entrega vazia": o scanner persiste todo listing precificado no XLSX e o
  threshold vira classificação downstream, com fallback near-miss.
- **v2.21** (2026-06-21): lista curada "vintage core" + flag `--vintage`.
- **v2.18–v2.20** (2026-06-20/21): fim da inflação de holo rare vintage;
  validação per-blueprint casa NM + reverse/variante; cache-bust do pricing.
- **v2.17** (2026-06-20): flag `--skip-backcatalog` (só as ~30 coleções
  modernas/curadas).
- **v2.16** (2026-06-17): entrega = tabela no chat OBRIGATÓRIA via a ferramenta
  do repo, nunca à mão / nunca XLSX por padrão; coluna Flag "validar manual" nas
  linhas REVISAR; fix do `--help` do postprocess.
- **v2.15** (2026-06-15): overrides de timeout por coleção pra sets vintage
  pesados.
- **v2.14** (2026-06-15): correção + robustez — timeout que escapava corrigido,
  falha de preço silenciosa corrigida, bloqueio de scanners concorrentes,
  câmbio preservado na recuperação, coluna "Variante Baixa Confiança".
- **v2.12** (2026-06-06): margem BRUTA — sem taxa embutida.
- **2026-06-05**: este guia reescrito em linguagem acessível pro operador.

**Pendências vivas:** nenhuma de bookkeeping — as antigas (a) v2.25 no
CHANGELOG/cabeçalho e (b) discrepância skill↔código do
`--max-consecutive-misses` foram fechadas em 2026-07-20. Backlog registrado:
extrair o núcleo comum `ct_tcg_core.py` pros scanners paralelos dbs/op (ver
seção do `op_scanner.py`).
