"""
Calcoli sul portafoglio: stima rendimenti attesi per categoria,
rendimento pesato complessivo e calcolo prelievi netti/lordi.
"""

import pandas as pd


DEFAULT_CATEGORY_RETURNS: dict[str, float] = {
    "Liquidità Spese": 0.015,
    "Fondo Emergenza": 0.03,
    "Liquidità Investimenti": 0.0,
    "Liquidità Bloccata": 0.0,
    "Azionario ETF": 0.075,
    "Azionario Stocks": 0.10,
    "Obbligazionario": 0.035,
    "Crypto": 0.20,
    "Oro": 0.03,
    "Collezionismo": 0.10,
    "Immobiliare": 0.04,
}


def infer_asset_nominal_return(row: pd.Series, return_map: dict[str, float] | None = None) -> float:
    """Ritorna un rendimento nominale annuo stimato per singolo asset."""
    category = str(row.get("category") or "").strip()
    subcategory = str(row.get("subcategory") or "").strip().lower()
    source = return_map or DEFAULT_CATEGORY_RETURNS

    if category in source:
        return float(source[category])
    if "deposito" in subcategory and "Fondo Emergenza" in source:
        return float(source["Fondo Emergenza"])
    return float(source.get("Immobiliare", 0.04))


def estimate_portfolio_nominal_return(
    df_assets: pd.DataFrame,
    return_map: dict[str, float] | None = None,
) -> tuple[float, pd.DataFrame]:
    """
    Stima rendimento nominale pesato sul patrimonio attuale (esclusa eredità immobiliare).
    Restituisce (rendimento_annuo, breakdown_per_categoria).
    """
    df = df_assets.copy()
    df = df[(df["category"] != "Immobiliare") & (df["current_value"] > 0)]
    if df.empty:
        return 0.05, pd.DataFrame(columns=["Categoria", "Valore", "Peso", "Rendimento Stimato"])

    df["assumed_return"] = df.apply(lambda r: infer_asset_nominal_return(r, return_map), axis=1)
    total_value = df["current_value"].sum()
    df["weight"] = df["current_value"] / total_value
    estimated = float((df["weight"] * df["assumed_return"]).sum())

    by_cat = (
        df.groupby("category")
        .apply(
            lambda g: pd.Series({
                "Valore": g["current_value"].sum(),
                "Peso": g["current_value"].sum() / total_value,
                "Rendimento Stimato": (
                    (g["current_value"] * g["assumed_return"]).sum()
                    / g["current_value"].sum()
                ),
            })
        )
        .reset_index()
        .rename(columns={"category": "Categoria"})
        .sort_values("Valore", ascending=False)
    )

    return estimated, by_cat


def gross_withdrawal_for_net_expense(net_expense: float, tax_rate: float) -> float:
    """Importo lordo da prelevare per coprire una spesa netta, includendo tassazione."""
    if net_expense <= 0:
        return 0.0
    if tax_rate >= 1:
        return net_expense
    return net_expense / (1 - tax_rate)
