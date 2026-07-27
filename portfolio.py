"""
Calcoli sul portafoglio: stima rendimenti attesi per categoria,
rendimento pesato complessivo, prelievi netti/lordi e aliquota effettiva
sulle plusvalenze (mix 26% / 12,5% per titoli di Stato).
"""

import pandas as pd

from constants import (
    CAPITAL_GAINS_TAX,
    CAPITAL_GAINS_TAX_STATE_BONDS,
    CATEGORY_STATE_BOND_SHARE,
    DEFAULT_PORTFOLIO_TER,
    DEFAULT_STAMP_DUTY_RATE,
)


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


def estimate_state_bond_share(
    df_assets: pd.DataFrame,
    state_bond_map: dict[str, float] | None = None,
) -> float:
    """Stima la frazione del portafoglio investibile in titoli di Stato/white list.

    Per ogni categoria del portafoglio (escluso Immobiliare e asset
    non-investabili), si moltiplica il valore per la quota tipica di titoli di
    Stato (vedi CATEGORY_STATE_BOND_SHARE). Restituisce un valore in [0,1].
    """
    df = df_assets.copy()
    df = df[(df["category"] != "Immobiliare") & (df["current_value"] > 0)]
    if "is_investable" in df.columns:
        df = df[df["is_investable"] == 1]
    if df.empty:
        return 0.0

    source = state_bond_map or CATEGORY_STATE_BOND_SHARE
    df["sb_share"] = df["category"].map(lambda c: source.get(str(c), 0.0))
    total = df["current_value"].sum()
    if total <= 0:
        return 0.0
    return float((df["current_value"] * df["sb_share"]).sum() / total)


def effective_capital_gains_tax(state_bond_share: float = 0.0) -> float:
    """Aliquota effettiva sulle plusvalenze data la share di titoli di Stato."""
    s = max(0.0, min(1.0, float(state_bond_share)))
    return s * CAPITAL_GAINS_TAX_STATE_BONDS + (1 - s) * CAPITAL_GAINS_TAX


def gross_withdrawal_for_net_expense(net_expense: float, tax_rate: float) -> float:
    """Importo lordo da prelevare per coprire una spesa netta, includendo tassazione."""
    if net_expense <= 0:
        return 0.0
    if tax_rate >= 1:
        return net_expense
    return net_expense / (1 - tax_rate)


def portfolio_annual_drag(
    ter: float = DEFAULT_PORTFOLIO_TER,
    stamp_duty: float = DEFAULT_STAMP_DUTY_RATE,
) -> float:
    """Drag annuo complessivo da applicare al rendimento nominale.

    Somma TER medio (costi prodotto) e bollo titoli (D.L. 201/2011, 0,2% annuo
    sul valore del dossier). Approssimazione conservativa: trattiamo il bollo
    come riduzione del rendimento (matematicamente equivalente al primo
    ordine).
    """
    return max(0.0, float(ter)) + max(0.0, float(stamp_duty))