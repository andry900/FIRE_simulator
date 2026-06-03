"""
Tab Aggiorna Dati: modifica valori asset esistenti e aggiunta nuovi asset.
"""

import streamlit as st
import pandas as pd

from db import load_assets, update_asset, add_asset
from constants import CATEGORY_COLORS


def _asset_expanders(subset: pd.DataFrame) -> None:
    for _, row in subset.iterrows():
        label = f"**{row['name']}**"
        ticker = str(row["ticker"]).strip() if pd.notna(row["ticker"]) else ""
        if ticker and ticker.lower() != "nan":
            label += f" `{ticker}`"
        label += f" — {row['category']}"
        broker = str(row["broker"]).strip() if pd.notna(row["broker"]) else ""
        if broker and broker.lower() != "nan":
            label += f" — {broker}"
        subcategory = str(row["subcategory"]).strip() if pd.notna(row["subcategory"]) else ""
        if subcategory and subcategory.lower() != "nan":
            label += f" · {subcategory}"
        label += f" — €{row['current_value']:,.2f}"

        with st.expander(label):
            col1, col2, col3 = st.columns([3, 2, 1])
            new_val = col1.number_input(
                "Valore (€)", value=float(row["current_value"]),
                key=f"v_{row['id']}", format="%.2f", min_value=0.0, step=10.0,
            )
            qty_val = float(row["quantity"]) if row["quantity"] is not None else 0.0
            new_qty = col2.number_input(
                "Quantità", value=qty_val,
                key=f"q_{row['id']}", format="%.4f", min_value=0.0,
            )
            if col3.button("💾 Salva", key=f"s_{row['id']}"):
                update_asset(int(row["id"]), new_val, new_qty)
                st.success("Aggiornato!")
                st.cache_data.clear()
                st.rerun()


def render() -> None:
    st.markdown("#### ✏️ Aggiorna valori degli asset")
    st.caption("Aggiorna i prezzi/valori correnti del tuo patrimonio.")

    df_edit = load_assets()

    current_assets = (
        df_edit[df_edit["category"] != "Immobiliare"]
        .query("current_value > 0")
        .sort_values("current_value", ascending=False)
    )
    future_assets = (
        df_edit[df_edit["category"] == "Immobiliare"]
        .query("current_value > 0")
        .sort_values("current_value", ascending=False)
    )

    st.markdown("##### Asset attuali")
    _asset_expanders(current_assets)

    st.divider()
    st.markdown("##### Asset futuri (eredità)")
    _asset_expanders(future_assets)

    st.divider()
    st.markdown("#### ➕ Aggiungi nuovo asset")
    with st.form("add_asset"):
        fc1, fc2 = st.columns(2)
        a_name   = fc1.text_input("Nome")
        a_ticker = fc2.text_input("Ticker (opzionale)")
        fc3, fc4, fc5 = st.columns(3)
        a_value  = fc3.number_input("Valore (€)", min_value=0.0, format="%.2f")
        a_qty    = fc4.number_input("Quantità",   min_value=0.0, format="%.4f")
        a_cat    = fc5.selectbox("Categoria", sorted(CATEGORY_COLORS.keys()))
        fc6, fc7, fc8 = st.columns(3)
        a_sub    = fc6.text_input("Sottocategoria")
        a_broker = fc7.text_input("Broker / custode")
        a_invest = fc8.selectbox("Investibile?", ["Sì", "No"])

        submitted = st.form_submit_button("➕ Aggiungi")
        if submitted and a_name:
            add_asset(
                name=a_name,
                ticker=a_ticker or None,
                quantity=a_qty,
                value=a_value,
                category=a_cat,
                subcategory=a_sub or None,
                broker=a_broker or None,
                is_investable=1 if a_invest == "Sì" else 0,
            )
            st.success(f"Asset «{a_name}» aggiunto!")
            st.rerun()
