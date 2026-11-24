# Entrega dos scanners — regra vigente do operador (2026-09-06)

Esta regra substitui instruções anteriores de entrega, publicação de resultados
e reutilização de preços. Vale para todos os jogos e perfis deste scanner.

- Rodar uma coleta nova quando o operador solicitar um scan. Não criar execução
  recorrente. Uma análise de código ou formatação não autoriza uma coleta de mercado.
- Entregar a tabela Markdown do gerador canônico diretamente no painel de conversa,
  no padrão MYP Cards: carta com número (ou produto/SKU), compra, referência assumida,
  diferença, métricas econômicas e flags pertinentes, com links da oferta e referência.
- O próprio preço de referência deve ser clicável e apontar à fonte que sustenta
  aquele valor. Mediana e projeção devem ser identificadas, com suas evidências.
  Não substituir fonte ausente por uma busca genérica ou por outra carta.
- Preservar todas as linhas disponíveis e os avisos de revisão/rejeição. Não
  remontar tabelas à mão nem transformar uma ausência de referência em preço zero.
- Não publicar resultados, preços, relatórios ou logs de coleta no GitHub, inclusive
  commits, Pages, releases, issues, comentários, Actions artifacts ou job summaries.
  GitHub pode guardar código e documentação; a entrega dos resultados é só no chat.
- Arquivos locais temporários são apoio de processamento, não a entrega padrão.
  Só anexar arquivos se solicitado. Não usar resultados antigos como preços atuais.
- Em cada nova solicitação, renovar ofertas, referências de preço e câmbio.
  Cache apenas da coleta em andamento ou de metadados estáveis; nunca reutilizar
  preços de outro scan, mesmo no mesmo dia. Um dump atualizado do provedor deve
  ter sua data informada; não prometer cotação em tempo real se a fonte é diária.
- Falha da coleta atual: declarar indisponibilidade/resultado parcial. Nunca
  apresentar um snapshot anterior como se tivesse sido coletado agora.
- Não mudar regras de margem, taxas, moedas ou equivalências para padronizar a tabela.

## Procedimento antes de entregar

1. Fazer a nova coleta solicitada, com saída e caches voláteis próprios desta execução.
2. Gerar a tabela com a ferramenta do repositório, a partir somente dessa execução.
3. Conferir identificação, horário da coleta, preço clicável, fonte e flags.
4. Colar a tabela no chat; se longa, dividir em mensagens preservando todas as linhas.

Para CardTrader usar coleta sem cache de preços; para Liga desativar cache de preços
entre execuções; para MYP não retomar checkpoints de solicitações anteriores.
COMC/eBay devem usar diretório de cache novo por coleta. Selados devem reconstruir
as referências de classificação e coletar novamente as ofertas antes do relatório.
O integrado deve chamar as fontes nesta execução, sem carregar arquivos antigos.

## Regras de decisão e colunas do CardTrader (P1, 2026-11-24, decisões do dono)

- Margem do corte = sobre a VENDA `(ref − compra)/ref` (padrão 30%, impresso no cabeçalho);
  ROI sobre aquisição só informativo. Hub 6% + frete R$ 0,50/carta só na líquida (XLSX),
  sempre rotulada PARCIAL enquanto houver custo não informado; nada de líquida no chat.
- Chase é informativo, nunca decide. COMPRA exige liquidez verificada no PriceCharting
  (≥5 vendas/90d e ≥1/30d, configuráveis); sem dado → REVISAR com o motivo.
- A tabela ganha `Vendas 30d` e `Vendas 90d` (com `≥` quando é piso) antes de `Flag`; todas as
  colunas anteriores seguem. Toda linha tem o link de oferta; o de referência vai junto sempre que a
  referência existe — quando não existe (bloco `Sem preço`), a célula diz `TCG: sem link`, nunca um link inventado.
- Margem negativa fica fora da tabela (aba Auditoria do XLSX); o rodapé diz quantas, e fecha a
  conta: entrada = COMPRA + REVISAR + abaixo do corte + margem negativa + blocos extras.
- Linhas das abas `Sem preço` / `Sem Ref Compatível` saem num bloco à parte, sem margem.
- Consultas ao PriceCharting: cache só do run, créditos Firecrawl informados no rodapé
  (teto 100 por scan; padrão 0).

## B1b — edição, fonte e data da referência; entrega completa

- A tabela ganha `Edição` e `Acabamento` (depois de `Carta`) e `Fonte ref.` e `Data ref.` (antes de
  `Flag`). `—` = scanner antigo, não informado. Os dois links por linha seguem intactos nas linhas com referência.
- `Data ref.` = data do DADO (`dado de …`: dump diário do tcgcsv, `updatedAt` do TCGplayer);
  `buscado em …` só quando a fonte não expõe a data.
- Canônico sem `--top-md`: entrega TODAS as linhas. Com limite, o cabeçalho diz "mostrando N de M" e
  o rodapé diz quantas ficaram fora e em qual aba (`Deals`) estão.
- Rodapé "Origem dos números": ofertas buscadas → após filtros, texto dos filtros e descartes de
  `--chase-only` / `--opportunities-only`.
- `Sem Ref Compatível` com tcgcsv como fallback: uma linha só, com os dois motivos (um por fonte).

## B1c — correções da revisão

- `Data ref.` mostra o fuso (`dado de 2026-11-23 17:05 (UTC-03:00)`, convertido ao horário local); XLSX antigo com só
  `Ref. Data/Hora` mostra `buscado em …`. O rodapé `Fontes das referências` diz a fonte de cada linha, que o tcgcsv
  é um lote diário e a idade do lote no momento do scan.
- Bloco `Sem preço`: ganha Vendedor, Qtd, CT R$ e Edição/Acab. (44 linhas do mesmo produto deixam de ser idênticas).
- O scanner não remove linha por margem depois de validar; `--min-net-margin` só marca. O corte único é do postprocess.
- Falha de infraestrutura no fallback tcgcsv = `Sem preço` (falha operacional) e set `operational_failure`
  ("tentar de novo"), nunca `Sem Ref Compatível` definitivo.

## B1g–B1k — como ler a decisão (resumo)

- Fonte principal do preço = tcgcsv (padrão do `--provider`); pokemontcg.io só quando o tcgcsv tem a carta
  sem preço. `Fonte ref.` diz quem precificou; resposta incompatível/ambígua nunca é trocada por outra fonte.
- `Ref Compatível = Inferido` (raridade CT não informa o acabamento): margem estimada, sempre REVISAR.
- Referência ambígua = linha sem referência e sem preço (bloco `Sem Ref Compatível`, com o motivo).
- Referência com idade desconhecida/futura ou acima de `--max-ref-age-days` (7) = REVISAR.
- PriceCharting compatível divergindo mais que `--max-ref-divergence` (0,30), ou margem pela MENOR referência
  abaixo do corte = REVISAR.
- Liquidez: ≥5 vendas/90d e ≥1/30d. Firecrawl: teto 100 créditos por scan; sem consulta por orçamento =
  `NAO_CONSULTADO_ORCAMENTO`; a coluna `PC Motivo` traz a causa linha a linha.
