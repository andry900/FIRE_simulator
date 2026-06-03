"""
Tab Patrimonio: asset allocation, tabella asset, eredità attesa.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from constants import CATEGORY_COLORS


def render(df: pd.DataFrame, monthly_expenses: float, monthly_salary: float, savings_rate: float) -> None:
    df_current = df[df["category"] != "Immobiliare"].copy()
    df_inheritance = df[df["category"] == "Immobiliare"].copy()

    total_nw = df_current["current_value"].sum()
    inheritance_nw = df_inheritance["current_value"].sum()
    investable_nw = df_current[df_current["is_investable"] == 1]["current_value"].sum()
    annual_expenses_now = monthly_expenses * 12

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💎 Patrimonio attuale",     f"€{total_nw:,.0f}")
    c2.metric("🚀 Patrimonio investibile", f"€{investable_nw:,.0f}")
    c3.metric("💸 Spese annue attuali",    f"€{annual_expenses_now:,.0f}")
    c4.metric("📈 Savings rate",           f"{savings_rate:.1f}%")
    st.caption(f"Eredità attesa (non inclusa nel patrimonio attuale): €{inheritance_nw:,.0f}")

    st.divider()

    alloc = (
        df_current.groupby("category")["current_value"]
        .sum()
        .reset_index()
        .rename(columns={"category": "Categoria", "current_value": "Valore"})
        .query("Valore > 0")
        .sort_values("Valore", ascending=False)
    )
    alloc["% Totale"] = (alloc["Valore"] / total_nw * 100).round(1)

    col_pie, col_tbl = st.columns([1, 1])

    with col_pie:
        colors = [CATEGORY_COLORS.get(c, "#888888") for c in alloc["Categoria"]]
        fig_pie = go.Figure(go.Pie(
            labels=alloc["Categoria"],
            values=alloc["Valore"],
            marker_colors=colors,
            textinfo="label+percent",
            hole=0.42,
            direction="clockwise",
            sort=False,
        ))
        fig_pie.update_traces(textfont_size=12)
        fig_pie.update_layout(
            title_text="Asset Allocation",
            showlegend=False,
            margin=dict(t=40, b=10, l=10, r=10),
            height=400,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_tbl:
        st.markdown("#### Dettaglio per categoria")
        tbl = alloc.copy()
        tbl["Valore"] = tbl["Valore"].map(lambda x: f"€{x:,.0f}")
        tbl["% Totale"] = tbl["% Totale"].astype(str) + "%"
        st.dataframe(tbl, use_container_width=True, hide_index=True)
        st.divider()
        st.markdown(f"**Totale patrimonio:** €{total_nw:,.0f}")
        st.markdown(f"**Investibile (liquido):** €{investable_nw:,.0f}")

    st.divider()
    st.markdown("#### Tutti gli asset")
    show_df = df_current[
        ["name", "ticker", "quantity", "current_value", "category", "subcategory", "broker"]
    ].copy()
    show_df = show_df[show_df["current_value"] > 0].sort_values("current_value", ascending=False)
    show_df["current_value"] = show_df["current_value"].map(lambda x: f"€{x:,.2f}")
    show_df.columns = ["Nome", "Ticker", "Qtà", "Valore", "Categoria", "Sottocategoria", "Broker"]
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    if inheritance_nw > 0:
        st.divider()
        st.markdown("#### Eredità attesa (fuori dal patrimonio attuale)")
        inh_df = df_inheritance[["name", "current_value", "subcategory", "broker"]].copy()
        inh_df = inh_df[inh_df["current_value"] > 0].sort_values("current_value", ascending=False)
        inh_df["current_value"] = inh_df["current_value"].map(lambda x: f"€{x:,.2f}")
        inh_df.columns = ["Nome", "Valore", "Tipo", "Fonte"]
        st.dataframe(inh_df, use_container_width=True, hide_index=True)
