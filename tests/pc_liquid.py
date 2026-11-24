"""Helper de teste: marca as linhas de um df enriquecido como 'liquidez verificada' e
'referencia compativel' (o que attach_pc_refs / o scanner novo fornecem em producao).
B1l: pc_status OK tambem traz a mediana PC (coerente com a TCG da linha, salvo override)."""


def with_liquidity(df, **over):
    df = df.copy()
    for k, v in dict(pc_status="OK", pc_vendas_30d=2, pc_vendas_90d=7, pc_truncado=False,
                     ref_compativel="Sim", **over).items():
        df[k] = v
    if "pc_median_usd" not in over and "reference_price_usd" in df.columns:
        df["pc_median_usd"] = df["reference_price_usd"]
    return df
