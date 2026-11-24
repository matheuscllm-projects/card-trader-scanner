# Decisao dos launchers apos o scanner: roda o postprocess ou aborta?
# Codigos de saida: ver "TABELA DE CODIGOS DE SAIDA" em cardtrader_scanner.py (unica fonte).
#   0            -> roda o postprocess
#   20 / 21 / 22 -> validacao parcial / sem preco live valido / API falhou: o XLSX bruto foi escrito COMPLETO, MAS so serve se
#                   foi escrito DURANTE este run (LastWriteTime >= inicio do run) - um XLSX de run ANTERIOR (o nome do
#                   arquivo depende so do carimbo) nunca e reaproveitado
#   qualquer outro (1, 2 = args/run-guard sem nada escrito, 130, ...) -> aborta
function Get-PostprocessDecision {
    param(
        [int]$ExitCode,
        [string]$RawOut,
        [datetime]$RunStart
    )
    if ($ExitCode -eq 0) { return 'run' }
    if (($ExitCode -in 20, 21, 22) -and (Test-Path -LiteralPath $RawOut)) {
        if ((Get-Item -LiteralPath $RawOut).LastWriteTime -ge $RunStart) { return 'run' }
    }
    return 'abort'
}
