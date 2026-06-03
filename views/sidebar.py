"""
Sidebar: input dei parametri di simulazione.
Restituisce un dict con tutti i valori selezionati dall'utente.
"""

import streamlit as st

import pandas as pd

from db import load_params, load_assets, save_params, load_category_return_map
from portfolio import estimate_portfolio_nominal_return
from pension_inps import annual_net_pension_from_gross, inps_transformation_coefficient
from pension_fonte import fonte_nominal_annual, fonte_tax_rate_by_enrollment
from constants import current_age


def render() -> dict:
    """Renderizza la sidebar e restituisce il dizionario di configurazione."""
    with st.sidebar:
        st.markdown("## ⚙️ Parametri")

        p = load_params()
        assets_df = load_assets()
        category_return_map = load_category_return_map()
        estimated_nominal_return, returns_by_category = estimate_portfolio_nominal_return(
            assets_df,
            return_map=category_return_map,
        )
        age_now = current_age()

        # ── Cash flow ────────────────────────────────────────────────────────
        st.markdown("### 💰 Cash flow mensile")
        monthly_salary = st.number_input(
            "Stipendio netto (€/mese)", value=float(p["monthly_salary"]), step=50.0, format="%.0f"
        )
        monthly_expenses = st.number_input(
            "Spese totali (€/mese)", value=float(p["monthly_expenses"]), step=50.0, format="%.0f"
        )
        salary_growth_rate = st.slider(
            "Aumento stipendio (%/anno)", 0.0, 10.0,
            float(p.get("salary_growth_rate", 0.03) * 100), 0.1,
        ) / 100
        monthly_savings = monthly_salary - monthly_expenses
        savings_rate = monthly_savings / monthly_salary * 100 if monthly_salary > 0 else 0
        st.markdown(
            f"**Risparmio:** €{monthly_savings:,.0f}/mese — savings rate **{savings_rate:.1f}%**"
        )
        st.caption(f"Aumento stipendio impostato: {salary_growth_rate * 100:.1f}% annuo")

        st.divider()

        # ── Rendimento & inflazione ──────────────────────────────────────────
        st.markdown("### 📈 Rendimento & inflazione")
        st.markdown(f"**Stima automatica portafoglio:** {estimated_nominal_return * 100:.2f}% nominale")
        nominal_adjustment = st.slider(
            "Aggiustamento personale della stima (%/anno)", -3.0, 3.0, 0.0, 0.1,
        )
        nominal_return = max(0.0, estimated_nominal_return + nominal_adjustment / 100)
        st.caption(
            f"Rendimento usato in simulazione: **{nominal_return * 100:.2f}%** · "
            "Ipotesi liquidità: 1,5% conti correnti / 3% conto deposito"
        )

        with st.expander("Dettaglio stima rendimento per categoria"):
            rb = returns_by_category.copy()
            if not rb.empty:
                rb["Valore"] = rb["Valore"].map(lambda x: f"€{x:,.0f}")
                rb["Peso"] = (rb["Peso"] * 100).map(lambda x: f"{x:.1f}%")
                rb["Rendimento Stimato"] = (rb["Rendimento Stimato"] * 100).map(lambda x: f"{x:.2f}%")
                st.dataframe(rb, use_container_width=True, hide_index=True)
            else:
                st.caption("Nessun asset con valore positivo disponibile per la stima.")

        inflation = st.slider(
            "Inflazione (%/anno)", 1.0, 5.0, float(p["inflation_rate"] * 100), 0.25
        ) / 100
        real_return = (1 + nominal_return) / (1 + inflation) - 1
        st.caption(f"Rendimento reale: **{real_return * 100:.2f}%**")

        st.divider()

        # ── Spese post-FIRE ──────────────────────────────────────────────────
        st.markdown("### 🧾 Spese post-FIRE")
        post_fire_expense_multiplier = st.slider(
            "Moltiplicatore spese post-FIRE (vs pre-FIRE)", 1.0, 2.5,
            float(p.get("post_fire_expense_multiplier", 1.5)), 0.05,
        )
        st.caption(
            f"Dopo il pensionamento: spese x{post_fire_expense_multiplier:.2f} (fisso in termini reali)."
        )

        st.divider()

        # ── Simulazione ──────────────────────────────────────────────────────
        st.markdown("### 🏖️ Simulazione")
        sim_end = st.slider("Età fine simulazione", min_value=50, max_value=120, value=95, step=1)
        planned_retirement_default = float(p.get("planned_retirement_age", 44))
        planned_retirement_default = min(max(planned_retirement_default, age_now), 60.0)
        planned_retirement_age = st.slider(
            "Età in cui vuoi smettere di lavorare",
            min_value=float(round(age_now, 1)),
            max_value=60.0,
            value=float(round(planned_retirement_default, 1)),
            step=0.1,
        )
        pension_access_default = int(p.get("pension_access_age", 67))
        pension_access_default = max(57, min(pension_access_default, 71))
        pension_access_age = st.number_input(
            "Età pensione INPS", value=pension_access_default,
            step=1, min_value=57, max_value=71,
        )
        st.caption("Coefficiente INPS applicato in modo deterministico in base all'età di accesso (57-71 anni).")

        # ── Fon.te ───────────────────────────────────────────────────────────
        st.markdown("#### Fon.te")
        annual_pension_contribution = st.number_input(
            "Versamento annuo Fon.te (€/anno)",
            value=float(p.get("annual_pension_contribution", 8211.0)),
            step=100.0, min_value=0.0, format="%.0f",
        )
        fonte_access_age = st.number_input(
            "Età sblocco Fon.te", value=int(p.get("fonte_access_age", 50)),
            step=1, min_value=44, max_value=75,
        )
        fonte_enrollment_date_str = p.get("fonte_enrollment_date", "2021-04-01")
        fonte_enrollment_date = st.date_input(
            "Data inizio iscrizione Fon.te",
            value=pd.to_datetime(fonte_enrollment_date_str).date(),
        )
        fonte_tax_rate = fonte_tax_rate_by_enrollment(
            fonte_enrollment_date.strftime("%Y-%m-%d"),
            float(fonte_access_age),
            age_now,
        )
        fonte_equity_return = float(category_return_map.get("Azionario ETF", 0.075))
        fonte_bond_return = float(category_return_map.get("Obbligazionario", 0.035))
        fonte_equity_weight = st.slider(
            "Peso azionario Fon.te (%)", 0.0, 100.0,
            float(p.get("fonte_equity_weight", 0.60) * 100), 0.5,
        ) / 100
        fonte_bond_weight = st.slider(
            "Peso obbligazionario Fon.te (%)", 0.0, 100.0,
            float(p.get("fonte_bond_weight", 0.40) * 100), 0.5,
        ) / 100
        fonte_nominal = fonte_nominal_annual(
            fonte_equity_return,
            fonte_bond_return,
            fonte_equity_weight,
            fonte_bond_weight,
        )
        st.caption(
            f"Fon.te: €{annual_pension_contribution:,.0f}/anno (cresce con lo stipendio reale). "
            f"Rendimento {fonte_nominal * 100:.2f}% nominale "
            f"({fonte_equity_weight * 100:.1f}% Az.×{fonte_equity_return * 100:.1f}% + "
            f"{fonte_bond_weight * 100:.1f}% Obbl.×{fonte_bond_return * 100:.1f}%, pesi normalizzati). "
            f"Sblocco a {fonte_access_age} anni con {fonte_tax_rate * 100:.1f}% su intero valore."
        )
        years_from_enrollment = (
            (pd.Timestamp.now() - pd.Timestamp(fonte_enrollment_date_str)).days / 365.25
            + max(float(fonte_access_age) - age_now, 0)
        )
        st.caption(
            f"Aliquota calcolata: {fonte_tax_rate * 100:.1f}% (anni di iscrizione: {years_from_enrollment:.1f}). "
            f"I rendimenti Fon.te sono presi dai rendimenti categoria: Azionario ETF e Obbligazionario."
        )

        # ── INPS ─────────────────────────────────────────────────────────────
        st.markdown("#### INPS")
        inps_montante_current = st.number_input(
            "Montante contributivo INPS attuale (€)",
            value=float(p.get("inps_montante_current", 102456.0)),
            step=1000.0, min_value=0.0, format="%.2f",
        )
        inps_annual_contribution = st.number_input(
            "Contributo annuo INPS (€/anno, ≤33% RAL)",
            value=float(p.get("inps_annual_contribution", 18023.0)),
            step=500.0, min_value=0.0, format="%.0f",
        )
        inps_contribution_growth_rate = st.slider(
            "Crescita annua contributo INPS (%/anno, reale)", 0.0, 8.0,
            float(p.get("inps_contribution_growth_rate", 0.03) * 100), 0.1,
        ) / 100
        inps_montante_revaluation_rate = st.slider(
            "Rivalutazione montante INPS post-FIRE (%/anno, reale)", 0.0, 4.0,
            float(p.get("inps_montante_revaluation_rate", 0.015) * 100), 0.1,
        ) / 100
        years_to_inps = max(pension_access_age - age_now, 0)
        # Proiezione deterministica: include versamenti futuri fino a FIRE e rivalutazione.
        inps_montante_proj = inps_montante_current
        inps_contrib_growth_monthly = (1 + inps_contribution_growth_rate) ** (1 / 12) - 1
        inps_reval_monthly = (1 + inps_montante_revaluation_rate) ** (1 / 12) - 1
        months_to_inps = max(int(round(years_to_inps * 12)), 0)
        for m in range(months_to_inps + 1):
            age_t = age_now + m / 12
            if age_t < planned_retirement_age:
                monthly_inps = inps_annual_contribution * ((1 + inps_contrib_growth_monthly) ** m) / 12
                inps_montante_proj = inps_montante_proj * (1 + inps_reval_monthly) + monthly_inps
            else:
                inps_montante_proj = inps_montante_proj * (1 + inps_reval_monthly)

        inps_coeff = inps_transformation_coefficient(float(pension_access_age))
        inps_proj_pension = inps_montante_proj * inps_coeff
        inps_proj_net_annual = annual_net_pension_from_gross(inps_proj_pension)

        st.caption(
            f"INPS: montante attuale €{inps_montante_current:,.0f}, montante stimato a {pension_access_age} anni "
            f"€{inps_montante_proj:,.0f}. Coefficiente deterministico {inps_coeff * 100:.3f}%."
        )
        st.caption(
            f"Pensione INPS stimata a {pension_access_age} anni: lorda €{inps_proj_pension:,.0f}/anno, "
            f"netta €{inps_proj_net_annual:,.0f}/anno (~€{inps_proj_net_annual / 12:,.0f}/mese) "
            f"con IRPEF a scaglioni e detrazione pensione."
        )

        st.divider()

        # ── Tassazione prelievi ──────────────────────────────────────────────
        st.markdown("### 🧾 Tassazione prelievi")
        initial_gain_pct = st.slider(
            "Plusvalenza attuale sul portafoglio (%)", 0.0, 80.0,
            float(p.get("initial_gain_pct", 0.30) * 100), 5.0,
        ) / 100
        st.caption(
            f"Oggi il {initial_gain_pct * 100:.0f}% del portafoglio è plusvalenza. "
            "Tassazione fissa al 26% solo sulle plusvalenze (non sull'intero prelievo). "
            "Col tempo la % di gain cresce con l'interesse composto → aliquota effettiva sale."
        )

        st.divider()

        # ── Casa vs Affitto ──────────────────────────────────────────────────
        st.markdown("### 🏠 Casa vs Affitto")
        rent_monthly_now = st.number_input(
            "Affitto attuale (€/mese)", value=float(p.get("rent_monthly_now", 450)),
            step=25.0, min_value=0.0, format="%.0f",
        )
        rent_real_growth = st.slider(
            "Aumento reale affitto (%/anno)", 0.0, 3.0,
            float(p.get("rent_real_growth", 0.01) * 100), 0.1,
        ) / 100
        owner_monthly_cost = st.number_input(
            "Costo casa di proprietà (€/mese)", value=float(p.get("owner_monthly_cost", 250)),
            step=25.0, min_value=0.0, format="%.0f",
        )
        owner_cost_real_growth = st.slider(
            "Aumento reale costi proprietà (%/anno)", 0.0, 2.0,
            float(p.get("owner_cost_real_growth", 0.0) * 100), 0.1,
        ) / 100
        inheritance_age = st.number_input(
            "Età eredità stimata", value=int(p.get("inheritance_age", 60)),
            step=1, min_value=35, max_value=100,
        )
        real_estate_appreciation = st.slider(
            "Rivalutazione immobili (%/anno, nominale)", 0.0, 4.0,
            float(p.get("real_estate_appreciation", 0.015) * 100), 0.1,
        ) / 100

        st.divider()

        # ── Rischio di mercato ───────────────────────────────────────────────
        st.markdown("### 🌪️ Rischio di mercato")
        annual_volatility = st.slider(
            "Volatilità annua portafoglio (%)", 5.0, 35.0,
            float(p.get("annual_volatility", 0.14) * 100), 0.5,
        ) / 100
        crash_prob_annual = st.slider(
            "Probabilità annua di anno negativo forte (%)", 0.0, 30.0,
            float(p.get("crash_prob_annual", 0.10) * 100), 1.0,
        ) / 100
        crash_impact = st.slider(
            "Impatto shock (% sul mese dello shock)", -40.0, -5.0,
            float(p.get("crash_impact", -0.20) * 100), 1.0,
        ) / 100
        monte_carlo_runs = int(
            st.slider(
                "Numero simulazioni Monte Carlo", min_value=300, max_value=3000,
                value=int(p.get("monte_carlo_runs", 800)), step=100,
            )
        )

        st.divider()
        if st.button("💾 Salva parametri", use_container_width=True):
            save_params({
                "monthly_salary":                monthly_salary,
                "monthly_expenses":              monthly_expenses,
                "salary_growth_rate":            salary_growth_rate,
                "nominal_annual_return":         nominal_return,
                "inflation_rate":                inflation,
                "pension_access_age":            int(pension_access_age),
                "rent_monthly_now":              rent_monthly_now,
                "rent_real_growth":              rent_real_growth,
                "owner_monthly_cost":            owner_monthly_cost,
                "owner_cost_real_growth":        owner_cost_real_growth,
                "inheritance_age":               int(inheritance_age),
                "real_estate_appreciation":      real_estate_appreciation,
                "post_fire_expense_multiplier":  post_fire_expense_multiplier,
                "planned_retirement_age":        planned_retirement_age,
                "annual_volatility":             annual_volatility,
                "crash_prob_annual":             crash_prob_annual,
                "crash_impact":                  crash_impact,
                "monte_carlo_runs":              monte_carlo_runs,
                "annual_pension_contribution":   annual_pension_contribution,
                "fonte_access_age":              int(fonte_access_age),
                "fonte_enrollment_date":         fonte_enrollment_date.strftime("%Y-%m-%d"),
                "fonte_equity_weight":           fonte_equity_weight,
                "fonte_bond_weight":             fonte_bond_weight,
                "inps_montante_current":         inps_montante_current,
                "inps_annual_contribution":      inps_annual_contribution,
                "inps_contribution_growth_rate": inps_contribution_growth_rate,
                "inps_montante_revaluation_rate":inps_montante_revaluation_rate,
                "initial_gain_pct":              initial_gain_pct,
            })
            st.success("Salvato!")

    return dict(
        monthly_salary=monthly_salary,
        monthly_expenses=monthly_expenses,
        monthly_savings=monthly_savings,
        savings_rate=savings_rate,
        salary_growth_rate=salary_growth_rate,
        nominal_return=nominal_return,
        inflation=inflation,
        post_fire_expense_multiplier=post_fire_expense_multiplier,
        sim_end=sim_end,
        planned_retirement_age=planned_retirement_age,
        pension_access_age=int(pension_access_age),
        annual_pension_contribution=annual_pension_contribution,
        fonte_access_age=int(fonte_access_age),
        fonte_enrollment_date=fonte_enrollment_date.strftime("%Y-%m-%d"),
        fonte_equity_return=fonte_equity_return,
        fonte_bond_return=fonte_bond_return,
        fonte_equity_weight=fonte_equity_weight,
        fonte_bond_weight=fonte_bond_weight,
        inps_montante_current=inps_montante_current,
        inps_annual_contribution=inps_annual_contribution,
        inps_contribution_growth_rate=inps_contribution_growth_rate,
        inps_montante_revaluation_rate=inps_montante_revaluation_rate,
        initial_gain_pct=initial_gain_pct,
        rent_monthly_now=rent_monthly_now,
        rent_real_growth=rent_real_growth,
        owner_monthly_cost=owner_monthly_cost,
        owner_cost_real_growth=owner_cost_real_growth,
        inheritance_age=int(inheritance_age),
        real_estate_appreciation=real_estate_appreciation,
        annual_volatility=annual_volatility,
        crash_prob_annual=crash_prob_annual,
        crash_impact=crash_impact,
        monte_carlo_runs=monte_carlo_runs,
        age_now=age_now,
    )
