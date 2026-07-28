"""
Tab Simulazione FIRE: proiezione deterministica SWR + stress test Monte Carlo.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from constants import BIRTH_DATE, DETERMINISTIC_SWR
from pension_fonte import fonte_real_monthly, fonte_tax_rate_by_enrollment
from pension_inps import annual_net_pension_from_gross, inps_transformation_coefficient
from simulation import simulate, find_fire_age
from monte_carlo import required_capital_for_target_survival


def _project_fonte_pot(
    start_pot: float,
    start_contributions: float,
    age_now: float,
    target_age: float,
    planned_retirement_age: float,
    cfg: dict,
    fonte_monthly: float,
    fonte_post_fire_monthly: float,
    salary_growth_monthly: float,
) -> tuple[float, float]:
    """Proietta pot Fon.te e contributi cumulati da age_now a target_age."""
    pot = start_pot
    contributions = start_contributions
    months_to_target = max(int(round((target_age - age_now) * 12)), 0)
    for m in range(months_to_target + 1):
        age_t = age_now + m / 12
        if age_t < planned_retirement_age:
            monthly_contrib = (
                cfg["annual_pension_contribution"] * ((1 + salary_growth_monthly) ** m) / 12
            )
            pot = pot * (1 + fonte_monthly) + monthly_contrib
            contributions += monthly_contrib
        else:
            pot = pot * (1 + fonte_post_fire_monthly)
    return pot, contributions


def _project_inps_montante(
    start_montante: float,
    start_contributed_years: float,
    age_now: float,
    target_age: float,
    planned_retirement_age: float,
    pension_access_age: int,
    fill_missing_years_after_fire: bool,
    cfg: dict,
    inps_contrib_growth_monthly: float,
) -> tuple[float, float]:
    """Proietta montante e anni contributivi INPS fino a target_age."""
    montante = start_montante
    contributed_years = max(float(start_contributed_years), 0.0)
    months_to_target = max(int(round((target_age - age_now) * 12)), 0)
    for m in range(months_to_target):
        age_t = age_now + m / 12
        should_contribute = age_t < planned_retirement_age
        if (
            not should_contribute
            and fill_missing_years_after_fire
            and age_t < float(pension_access_age)
            and contributed_years < 20.0
        ):
            should_contribute = True

        if should_contribute:
            monthly_inps = cfg["inps_annual_contribution"] * ((1 + inps_contrib_growth_monthly) ** m) / 12
            montante += monthly_inps
            contributed_years += (1 / 12)
        if m > 0 and m % 12 == 0:
            montante *= (1 + cfg["inps_montante_revaluation_rate"])
    return montante, contributed_years


def render(df: pd.DataFrame, cfg: dict) -> None:
    """
    Renderizza il tab FIRE completo.

    Parameters
    ----------
    df  : DataFrame degli asset (tutti, inclusi Immobiliare)
    cfg : dict con tutti i parametri dalla sidebar
    """
    age_now = cfg["age_now"]

    # ── Derivazioni dal portafoglio ──────────────────────────────────────────
    df_current = df[df["category"] != "Immobiliare"].copy()
    portfolio_liquid = df_current[df_current["is_investable"] == 1]["current_value"].sum()
    pension_total = df_current[df_current["broker"] == "Fon.te"]["current_value"].sum()

    inheritance_df = df[df["category"] == "Immobiliare"].copy()
    inheritance_cash_amount = (
        inheritance_df[inheritance_df["subcategory"] == "Cash"]["current_value"].sum()
    )
    inheritance_re_df = inheritance_df[inheritance_df["subcategory"] != "Cash"]
    full_house_value_today = (
        inheritance_re_df[inheritance_re_df["quantity"].fillna(0) >= 1]["current_value"].sum()
    )
    partial_house_value_today = (
        inheritance_re_df[inheritance_re_df["quantity"].fillna(0) < 1]["current_value"].sum()
    )

    inheritance_age = cfg["inheritance_age"]
    real_estate_appreciation = cfg["real_estate_appreciation"]
    years_to_inheritance = max(inheritance_age - age_now, 0)
    inflation_factor = (1 + cfg["inflation"]) ** years_to_inheritance
    inheritance_cash_real_at_inh = (
        inheritance_cash_amount / inflation_factor if inflation_factor > 0 else inheritance_cash_amount
    )
    real_estate_real_growth = ((1 + real_estate_appreciation) / (1 + cfg["inflation"])) - 1
    full_house_at_inh = full_house_value_today * ((1 + real_estate_real_growth) ** years_to_inheritance)
    partial_house_at_inh = partial_house_value_today * ((1 + real_estate_real_growth) ** years_to_inheritance)

    monthly_non_housing_expenses = max(cfg["monthly_expenses"] - cfg["rent_monthly_now"], 0.0)

    # ── Info summary ─────────────────────────────────────────────────────────
    st.markdown(
        f"**Portafoglio investibile attuale:** €{portfolio_liquid:,.0f} "
        f"· **Fon.te attuale:** €{pension_total:,.0f} (sblocco a {cfg['fonte_access_age']} anni) "
        f"· **INPS montante:** €{cfg['inps_montante_current']:,.0f} "
        f"(pensione a {cfg['pension_access_age']} anni) "
        f"· **Eredità:** €{full_house_value_today + partial_house_value_today:,.0f}"
    )
    st.caption(
        f"A {inheritance_age} anni entrano €{inheritance_cash_real_at_inh:,.0f} cash reali in entrambi gli scenari. "
        f"In affitto a vita vendi anche la casa al 100% e investi il ricavato "
        f"(stimato: €{full_house_at_inh:,.0f})."
    )
    st.caption(
        f"Casa al mare 50% resta non liquidata "
        f"(valore stimato a {inheritance_age} anni: €{partial_house_at_inh:,.0f}). "
        "Scenario proprietà: resti in affitto fino all'eredità, poi vivi in casa con costi da proprietario."
    )
    st.caption(
        "Nota: nel grafico la curva mostra il patrimonio investibile. "
        "In 'Proprietà dopo eredità' la casa non viene venduta, quindi non appare un salto del portafoglio."
    )
    st.caption(f"Età pensionamento impostata: {cfg['planned_retirement_age']:.1f} anni.")
    st.divider()

    threshold_swr = DETERMINISTIC_SWR
    minimum_portfolio_reserve = float(cfg.get("minimum_portfolio_reserve", 100000.0))

    # ── Costruzione kwargs comuni ────────────────────────────────────────────
    base_sim_kwargs = dict(
        portfolio_start=portfolio_liquid,
        monthly_salary=cfg["monthly_salary"],
        monthly_non_housing_expenses=monthly_non_housing_expenses,
        salary_growth_rate=cfg["salary_growth_rate"],
        post_fire_expense_multiplier=cfg["post_fire_expense_multiplier"],
        rent_monthly_now=cfg["rent_monthly_now"],
        rent_real_growth=cfg["rent_real_growth"],
        owner_monthly_cost=cfg["owner_monthly_cost"],
        owner_cost_real_growth=cfg["owner_cost_real_growth"],
        inflation=cfg["inflation"],
        threshold_swr=threshold_swr,
        minimum_portfolio_reserve=minimum_portfolio_reserve,
        pension_value=pension_total,
        pension_access_age=cfg["pension_access_age"],
        annual_pension_contribution=cfg["annual_pension_contribution"],
        fonte_access_age=cfg["fonte_access_age"],
        fonte_unlock_years_after_fire=max(cfg["fonte_access_age"] - cfg["planned_retirement_age"], 0.0),
        fonte_enrollment_date=cfg["fonte_enrollment_date"],
        fonte_equity_return=cfg["fonte_equity_return"],
        fonte_bond_return=cfg["fonte_bond_return"],
        fonte_equity_weight=cfg["fonte_equity_weight"],
        fonte_bond_weight=cfg["fonte_bond_weight"],
        fonte_contributions_paid=cfg["fonte_contributions_paid"],
        inps_montante_current=cfg["inps_montante_current"],
        inps_annual_contribution=cfg["inps_annual_contribution"],
        inps_contribution_growth_rate=cfg["inps_contribution_growth_rate"],
        inps_montante_revaluation_rate=cfg["inps_montante_revaluation_rate"],
        inps_years_contributed_current=cfg["inps_years_contributed_current"],
        inps_fill_missing_years=cfg["inps_fill_missing_years"],
        inps_gross_factor=cfg["inps_gross_factor"],
        inps_coefficient_haircut=cfg["inps_coefficient_haircut"],
        initial_gain_pct=cfg["initial_gain_pct"],
        state_bond_share=cfg["state_bond_share"],
        portfolio_ter=cfg["portfolio_ter"],
        stamp_duty_rate=cfg["stamp_duty_rate"],
        regional_surtax=cfg["regional_surtax"],
        municipal_surtax=cfg["municipal_surtax"],
        planned_retirement_age=cfg["planned_retirement_age"],
        inheritance_age=inheritance_age,
        inheritance_cash_amount=inheritance_cash_amount,
        full_house_value_today=full_house_value_today,
        real_estate_appreciation=real_estate_appreciation,
        start_age=age_now,
        end_age=cfg["sim_end"],
    )

    # ── Scenari ──────────────────────────────────────────────────────────────
    nominal_return = cfg["nominal_return"]
    pessimistic_return = max(0.0, nominal_return - 0.03)
    optimistic_return = nominal_return + 0.03
    scenarios = {
        f"Affitto · Pessimista ({pessimistic_return*100:.1f}%)": (
            pessimistic_return, "#EF5350", "dash", "rent_life_with_sale", "legendonly"
        ),
        f"Proprietà dopo eredità · Base ({nominal_return*100:.1f}%)": (
            nominal_return, "#8D6E63", "solid", "owner_after_inheritance", True
        ),
        f"Affitto · Base ({nominal_return*100:.1f}%)": (
            nominal_return, "#42A5F5", "solid", "rent_life_with_sale", True
        ),
        f"Affitto · Ottimista ({optimistic_return*100:.1f}%)": (
            optimistic_return, "#66BB6A", "dot", "rent_life_with_sale", "legendonly"
        ),
    }

    fig = go.Figure()
    min_sustainable_fire_ages: dict[str, float | None] = {}
    deterministic_success: dict[str, bool] = {}
    scenario_inputs: dict[str, dict] = {}
    scenario_paths: dict[str, pd.DataFrame] = {}

    for label, (ret, color, dash, housing_mode, default_visible) in scenarios.items():
        sim_kwargs = {**base_sim_kwargs, "nominal_return": ret, "housing_mode": housing_mode}
        df_sim, ok_end = simulate(**sim_kwargs)
        min_sustainable_fire_ages[label] = find_fire_age(precision=0.1, **sim_kwargs)
        deterministic_success[label] = ok_end
        scenario_inputs[label] = sim_kwargs
        scenario_paths[label] = df_sim

        fig.add_trace(go.Scatter(
            x=df_sim["age"],
            y=df_sim["portfolio"],
            name=label,
            mode="lines",
            line=dict(color=color, dash=dash, width=2.5),
            visible=default_visible,
            hovertemplate="Età %{x:.1f} → €%{y:,.0f}<extra>" + label + "</extra>",
        ))

    # Linee verticali eventi
    fig.add_vline(
        x=cfg["planned_retirement_age"],
        line_dash="dash",
        line_color="#EF5350",
        line_width=2,
        annotation_text=f" FIRE {cfg['planned_retirement_age']:.1f}a",
        annotation_position="top left",
        annotation_font=dict(color="#EF5350", size=11),
    )

    for x_val, color, label_txt in [
        (cfg["fonte_access_age"], "#FFB74D", f" Fon.te {cfg['fonte_access_age']:.0f}a"),
        (cfg["pension_access_age"], "#CE93D8", f" INPS {cfg['pension_access_age']:.0f}a"),
        (inheritance_age, "#8D6E63", f" Eredità {inheritance_age:.0f}a"),
    ]:
        fig.add_vline(
            x=x_val, line_dash="dot", line_color=color, line_width=1.5,
            annotation_text=label_txt, annotation_position="top right",
            annotation_font=dict(color=color, size=11),
        )

    fig.update_layout(
        title="Proiezione patrimonio — confronto Affitto vs Proprietà (euro reali)",
        xaxis_title="Età",
        yaxis_title="Patrimonio (€)",
        yaxis=dict(tickprefix="€", tickformat=",.0f"),
        xaxis=dict(dtick=5),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=520,
        margin=dict(r=160),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Asset futuri a sblocco (valori reali, euro di oggi) ────────────────
    salary_growth_monthly = (1 + cfg["salary_growth_rate"]) ** (1 / 12) - 1
    inflation_monthly = (1 + cfg["inflation"]) ** (1 / 12) - 1
    fonte_post_fire_monthly = (1 / (1 + inflation_monthly)) - 1
    fonte_monthly = fonte_real_monthly(
        cfg["inflation"],
        fonte_equity_return=cfg["fonte_equity_return"],
        fonte_bond_return=cfg["fonte_bond_return"],
        fonte_equity_weight=cfg["fonte_equity_weight"],
        fonte_bond_weight=cfg["fonte_bond_weight"],
    )
    inps_contrib_growth_monthly = (1 + cfg["inps_contribution_growth_rate"]) ** (1 / 12) - 1

    # Calcolo aliquota Fon.te dinamica basata su anni di iscrizione
    fonte_tax_rate_calculated = fonte_tax_rate_by_enrollment(
        cfg["fonte_enrollment_date"],
        float(cfg["planned_retirement_age"]),
        age_now,
    )

    # Proiezione Fon.te fino a età di sblocco
    fonte_pot_at_unlock, fonte_contribs_at_unlock = _project_fonte_pot(
        start_pot=pension_total,
        start_contributions=cfg["fonte_contributions_paid"],
        age_now=age_now,
        target_age=cfg["fonte_access_age"],
        planned_retirement_age=cfg["planned_retirement_age"],
        cfg=cfg,
        fonte_monthly=fonte_monthly,
        fonte_post_fire_monthly=fonte_post_fire_monthly,
        salary_growth_monthly=salary_growth_monthly,
    )
    # Tassazione corretta: contributi tassati 9-15%, rendimenti già netti.
    taxable_contribs = min(fonte_contribs_at_unlock, fonte_pot_at_unlock)
    fonte_net_at_unlock = (
        taxable_contribs * (1 - fonte_tax_rate_calculated)
        + max(fonte_pot_at_unlock - taxable_contribs, 0.0)
    )
    fonte_future_contribs = max(fonte_contribs_at_unlock - cfg["fonte_contributions_paid"], 0.0)

    # Proiezione INPS fino ad accesso pensione
    inps_montante, inps_years_at_access = _project_inps_montante(
        start_montante=cfg["inps_montante_current"],
        start_contributed_years=cfg["inps_years_contributed_current"],
        age_now=age_now,
        target_age=cfg["pension_access_age"],
        planned_retirement_age=cfg["planned_retirement_age"],
        pension_access_age=int(cfg["pension_access_age"]),
        fill_missing_years_after_fire=bool(cfg.get("inps_fill_missing_years", False)),
        cfg=cfg,
        inps_contrib_growth_monthly=inps_contrib_growth_monthly,
    )
    inps_coeff = inps_transformation_coefficient(
        float(cfg["pension_access_age"]),
        future_haircut=cfg["inps_coefficient_haircut"],
    )
    inps_annual_lorda = 0.0
    inps_monthly_netta = 0.0
    inps_eligible = inps_years_at_access >= 20.0
    if inps_eligible:
        inps_annual_lorda = inps_montante * inps_coeff
        inps_annual_lorda *= cfg.get("inps_gross_factor", 1.0)
        inps_monthly_netta = annual_net_pension_from_gross(
            inps_annual_lorda,
            regional_surtax=cfg["regional_surtax"],
            municipal_surtax=cfg["municipal_surtax"],
        ) / 12

    inheritance_cash_real_at_unlock = inheritance_cash_real_at_inh

    # Immobiliare: crescita nominale stimata meno inflazione -> valore reale a età eredità
    full_house_real_at_inh = full_house_value_today * ((1 + real_estate_real_growth) ** years_to_inheritance)
    partial_house_real_at_inh = partial_house_value_today * ((1 + real_estate_real_growth) ** years_to_inheritance)

    st.markdown("##### Asset futuri al momento dello sblocco (valori reali in € di oggi)")
    future_assets_df = pd.DataFrame([
        {
            "Voce": "Fon.te (netto al primo sblocco)",
            "Età sblocco": f"{cfg['fonte_access_age']:.0f}",
            "Valore stimato": fonte_net_at_unlock,
            "Note": (
                f"Pot lordo €{fonte_pot_at_unlock:,.0f}, contributi cumulati "
                f"€{fonte_contribs_at_unlock:,.0f} tassati al {fonte_tax_rate_calculated*100:.2f}%; "
                f"contributi aggiuntivi futuri €{fonte_future_contribs:,.0f} fino a FIRE "
                f"({cfg['planned_retirement_age']:.2f} anni), poi sola rivalutazione fino allo sblocco; "
                "rendimenti già netti (sostitutiva 20%/12,5%)."
            ),
        },
        {
            "Voce": "Eredità cash",
            "Età sblocco": f"{inheritance_age:.0f}",
            "Valore stimato": inheritance_cash_real_at_unlock,
            "Note": "Deflazionato per inflazione fino all'età di eredità",
        },
        {
            "Voce": "Eredità immobiliare (totale stima)",
            "Età sblocco": f"{inheritance_age:.0f}",
            "Valore stimato": full_house_real_at_inh + partial_house_real_at_inh,
            "Note": "Rivalutazione immobili al netto dell'inflazione (quota 100% + 50%)",
        },
        {
            "Voce": "Pensione INPS netta mensile",
            "Età sblocco": f"{cfg['pension_access_age']:.0f}",
            "Valore stimato": inps_monthly_netta,
            "Note": (
                (
                    f"Anni contributivi stimati: {inps_years_at_access:.1f} (>=20, requisito soddisfatto). "
                    f"Coeff. INPS {inps_coeff * 100:.3f}% (haircut {cfg['inps_coefficient_haircut']*100:.0f}%) + "
                    "IRPEF a scaglioni + detrazione pensione + addizionali."
                )
                if inps_eligible
                else (
                    f"Anni contributivi stimati: {inps_years_at_access:.1f} (<20). "
                    "Pensione INPS non erogabile nel modello con questi parametri."
                )
            ),
        },
    ])
    future_assets_df["Valore stimato"] = future_assets_df["Valore stimato"].map(lambda x: f"€{x:,.0f}")
    st.dataframe(future_assets_df, use_container_width=True, hide_index=True)

    # ── Metriche FIRE deterministiche ────────────────────────────────────────
    st.markdown("##### Età FIRE minima sostenibile per scenario")
    st.caption(
        "Definizione: prima età in cui puoi smettere di lavorare e il capitale non va mai a zero "
        f"fino a {cfg['sim_end']} anni. Confronto rispetto alla tua FIRE impostata ({cfg['planned_retirement_age']:.1f} anni)."
    )
    ordered_labels = sorted(
        scenarios.keys(),
        key=lambda label: (
            min_sustainable_fire_ages[label] is None,
            float("inf") if min_sustainable_fire_ages[label] is None else (
                min_sustainable_fire_ages[label] - float(cfg["planned_retirement_age"])
            ),
        ),
    )
    cols = st.columns(len(ordered_labels))
    for i, label in enumerate(ordered_labels):
        fa = min_sustainable_fire_ages[label]
        if fa is not None:
            fire_year = BIRTH_DATE.year + int(fa)
            delta_vs_manual = fa - float(cfg["planned_retirement_age"])
            cols[i].metric(
                label,
                f"Età {fa:.1f} ({fire_year})",
                f"{delta_vs_manual:+.1f} anni vs FIRE impostata",
                delta_color="inverse",
            )
            if delta_vs_manual > 0:
                cols[i].caption("In questo scenario devi posticipare il FIRE rispetto alla data impostata.")
            else:
                cols[i].caption("In questo scenario la data FIRE impostata è sostenibile (o prudente).")
        else:
            cols[i].metric(label, "Non sostenibile", f"entro {cfg['sim_end']} anni")

    st.markdown("##### Proiezione patrimonio con FIRE minima sostenibile per scenario")
    st.caption(
        "Ogni curva sotto usa, per il relativo scenario, la prima età FIRE sostenibile calcolata sopra. "
        "Serve per confrontare visivamente le traiettorie dopo il pensionamento scenario per scenario."
    )

    fig_min_fire = go.Figure()
    fonte_unlock_lag = max(float(cfg["fonte_access_age"]) - float(cfg["planned_retirement_age"]), 0.0)
    for label in ordered_labels:
        ret, color, dash, housing_mode, default_visible = scenarios[label]
        scenario_fire_age = min_sustainable_fire_ages[label]
        if scenario_fire_age is None:
            continue
        scenario_fonte_age = scenario_fire_age + fonte_unlock_lag

        sim_kwargs = {
            **base_sim_kwargs,
            "nominal_return": ret,
            "housing_mode": housing_mode,
            "planned_retirement_age": scenario_fire_age,
            "fonte_unlock_years_after_fire": fonte_unlock_lag,
        }
        df_min_fire, _ = simulate(**sim_kwargs)

        fig_min_fire.add_trace(go.Scatter(
            x=df_min_fire["age"],
            y=df_min_fire["portfolio"],
            name=label,
            mode="lines",
            legendgroup=label,
            line=dict(color=color, dash=dash, width=2.5),
            visible=default_visible,
            hovertemplate="Età %{x:.1f} → €%{y:,.0f}<extra>" + label + "</extra>",
        ))
        y_max = float(df_min_fire["portfolio"].max()) if not df_min_fire.empty else 0.0
        fig_min_fire.add_trace(go.Scatter(
            x=[scenario_fire_age, scenario_fire_age],
            y=[0.0, y_max],
            mode="lines",
            line=dict(color=color, dash="dash", width=1.5),
            legendgroup=label,
            showlegend=False,
            visible=default_visible,
            hovertemplate=f"FIRE {scenario_fire_age:.1f}a<extra>{label}</extra>",
        ))
        fig_min_fire.add_trace(go.Scatter(
            x=[scenario_fire_age],
            y=[y_max],
            mode="text",
            text=[f"FIRE {scenario_fire_age:.1f}a"],
            textposition="top left",
            textfont=dict(color=color, size=10),
            legendgroup=label,
            showlegend=False,
            visible=default_visible,
            hoverinfo="skip",
        ))
        fig_min_fire.add_trace(go.Scatter(
            x=[scenario_fonte_age, scenario_fonte_age],
            y=[0.0, y_max],
            mode="lines",
            line=dict(color="#FFB74D", dash="dot", width=1.3),
            legendgroup=label,
            showlegend=False,
            visible=default_visible,
            hovertemplate=f"Fon.te {scenario_fonte_age:.1f}a<extra>{label}</extra>",
        ))
        fig_min_fire.add_trace(go.Scatter(
            x=[scenario_fonte_age],
            y=[y_max * 0.94 if y_max > 0 else 0.0],
            mode="text",
            text=[f"Fon.te {scenario_fonte_age:.1f}a"],
            textposition="top right",
            textfont=dict(color="#FFB74D", size=10),
            legendgroup=label,
            showlegend=False,
            visible=default_visible,
            hoverinfo="skip",
        ))

    for x_val, color, label_txt in [
        (cfg["pension_access_age"], "#CE93D8", f" INPS {cfg['pension_access_age']:.0f}a"),
        (inheritance_age, "#8D6E63", f" Eredità {inheritance_age:.0f}a"),
    ]:
        fig_min_fire.add_vline(
            x=x_val,
            line_dash="dot",
            line_color=color,
            line_width=1.2,
            annotation_text=label_txt,
            annotation_position="top right",
            annotation_font=dict(color=color, size=10),
        )

    fig_min_fire.update_layout(
        title="Proiezione patrimonio alle età FIRE minime sostenibili",
        xaxis_title="Età",
        yaxis_title="Patrimonio (€)",
        yaxis=dict(tickprefix="€", tickformat=",.0f"),
        xaxis=dict(dtick=5),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=520,
        margin=dict(r=160),
    )
    st.plotly_chart(fig_min_fire, use_container_width=True)

    st.divider()

    # ── Monte Carlo ──────────────────────────────────────────────────────────
    st.markdown("#### 🎯 Target FIRE Monte Carlo")

    mc_signature = (
        round(threshold_swr, 6),
        float(cfg.get("minimum_portfolio_reserve", 100000.0)),
        int(cfg["monte_carlo_runs"]),
        float(cfg["annual_volatility"]),
        float(cfg["crash_prob_annual"]),
        float(cfg["crash_impact"]),
        float(cfg["planned_retirement_age"]),
        float(cfg["nominal_return"]),
        float(cfg["portfolio_ter"]),
        float(cfg["stamp_duty_rate"]),
        float(cfg["state_bond_share"]),
        float(cfg["regional_surtax"]),
        float(cfg["municipal_surtax"]),
        float(cfg["inps_coefficient_haircut"]),
    )
    if st.session_state.get("mc_target_signature") != mc_signature:
        st.session_state["mc_target_signature"] = mc_signature
        st.session_state.pop("mc_target_results", None)

    run_mc = st.button("Esegui simulazione Target FIRE Monte Carlo", type="primary")

    # Valori previdenziali stimati all'età FIRE (per il calcolo del target a FIRE)
    fonte_pot_at_fire, fonte_contribs_at_fire = _project_fonte_pot(
        start_pot=pension_total,
        start_contributions=cfg["fonte_contributions_paid"],
        age_now=age_now,
        target_age=cfg["planned_retirement_age"],
        planned_retirement_age=cfg["planned_retirement_age"],
        cfg=cfg,
        fonte_monthly=fonte_monthly,
        fonte_post_fire_monthly=fonte_post_fire_monthly,
        salary_growth_monthly=salary_growth_monthly,
    )
    inps_montante_at_fire, inps_years_at_fire = _project_inps_montante(
        start_montante=cfg["inps_montante_current"],
        start_contributed_years=cfg["inps_years_contributed_current"],
        age_now=age_now,
        target_age=cfg["planned_retirement_age"],
        planned_retirement_age=cfg["planned_retirement_age"],
        pension_access_age=int(cfg["pension_access_age"]),
        fill_missing_years_after_fire=bool(cfg.get("inps_fill_missing_years", False)),
        cfg=cfg,
        inps_contrib_growth_monthly=inps_contrib_growth_monthly,
    )

    base_rent_label = f"Affitto · Base ({nominal_return*100:.1f}%)"
    base_owner_label = f"Proprietà dopo eredità · Base ({nominal_return*100:.1f}%)"
    target_survival = 0.95
    scenario_labels = [base_rent_label, base_owner_label]

    def euro_it(v: float) -> str:
        return f"€{v:,.0f}".replace(",", ".")

    if run_mc:
        results = []
        for label in scenario_labels:
            if label not in scenario_inputs:
                continue

            seed_base = sum((i + 1) * ord(ch) for i, ch in enumerate(label)) % 1_000_000
            mc_target_runs = max(1, int(cfg["monte_carlo_runs"]))
            target_capital, target_prob = required_capital_for_target_survival(
                target_survival=target_survival,
                n_sims=mc_target_runs,
                annual_volatility=cfg["annual_volatility"],
                crash_prob_annual=cfg["crash_prob_annual"],
                crash_impact=cfg["crash_impact"],
                random_seed=seed_base,
                **scenario_inputs[label],
            )

            df_path = scenario_paths[label]
            idx_fire = (df_path["age"] - cfg["planned_retirement_age"]).abs().idxmin()
            portfolio_at_fire_est = float(df_path.loc[idx_fire, "portfolio"])

            fire_phase_kwargs = {
                **scenario_inputs[label],
                "start_age": float(cfg["planned_retirement_age"]),
                "planned_retirement_age": float(cfg["planned_retirement_age"]),
                "portfolio_start": max(portfolio_at_fire_est, 100_000.0),
                "pension_value": fonte_pot_at_fire,
                "fonte_contributions_paid": fonte_contribs_at_fire,
                "inps_montante_current": inps_montante_at_fire,
                "inps_years_contributed_current": inps_years_at_fire,
            }
            target_capital_fire, target_prob_fire = required_capital_for_target_survival(
                target_survival=target_survival,
                n_sims=mc_target_runs,
                annual_volatility=cfg["annual_volatility"],
                crash_prob_annual=cfg["crash_prob_annual"],
                crash_impact=cfg["crash_impact"],
                random_seed=seed_base + 1,
                **fire_phase_kwargs,
            )

            gap_today = portfolio_liquid - target_capital
            gap_fire = portfolio_liquid - target_capital_fire
            success_today = int(round(target_prob * mc_target_runs))
            fail_today = mc_target_runs - success_today
            success_fire = int(round(target_prob_fire * mc_target_runs))
            fail_fire = mc_target_runs - success_fire

            results.append(
                {
                    "label": label,
                    "mc_target_runs": mc_target_runs,
                    "target_capital": target_capital,
                    "success_today": success_today,
                    "fail_today": fail_today,
                    "gap_today": gap_today,
                    "target_capital_fire": target_capital_fire,
                    "success_fire": success_fire,
                    "fail_fire": fail_fire,
                    "gap_fire": gap_fire,
                    "portfolio_at_fire_est": portfolio_at_fire_est,
                }
            )
        st.session_state["mc_target_results"] = results

    mc_results = st.session_state.get("mc_target_results")
    if not mc_results:
        st.caption("Premi il pulsante per eseguire la simulazione Monte Carlo.")
    else:
        mc1, mc2 = st.columns(2)
        for col, row in zip((mc1, mc2), mc_results):
            col.markdown(f"**{row['label']}**")
            col.caption(f"Run Monte Carlo: {row['mc_target_runs']}")

            col.markdown("**Oggi**")
            t1, t2 = col.columns(2)
            t1.metric("Capitale richiesto", euro_it(row["target_capital"]))
            t2.markdown(
                (
                    "<div><strong>Esito</strong><br>"
                    f"<span style='color:#2e7d32;font-weight:700'>OK {row['success_today']}</span> · "
                    f"<span style='color:#c62828;font-weight:700'>KO {row['fail_today']}</span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            col.metric("Gap vs patrimonio attuale", euro_it(row["gap_today"]))

            col.markdown(f"**A FIRE ({cfg['planned_retirement_age']:.1f}a)**")
            f1, f2 = col.columns(2)
            f1.metric("Capitale richiesto", euro_it(row["target_capital_fire"]))
            f2.markdown(
                (
                    "<div><strong>Esito</strong><br>"
                    f"<span style='color:#2e7d32;font-weight:700'>OK {row['success_fire']}</span> · "
                    f"<span style='color:#c62828;font-weight:700'>KO {row['fail_fire']}</span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            col.metric("Gap vs patrimonio attuale", euro_it(row["gap_fire"]))
            col.caption(f"Patrimonio stimato a FIRE: {euro_it(row['portfolio_at_fire_est'])}")

        st.caption(f"Esiti simulazioni su {max(1, int(cfg['monte_carlo_runs']))} run per scenario.")

    st.divider()

    # ── Breakdown risparmio ──────────────────────────────────────────────────
    ca, cb, cc, cd = st.columns(4)
    ca.metric("📊 Savings rate",      f"{cfg['savings_rate']:.1f}%")
    cb.metric("💸 Risparmio mensile", f"€{cfg['monthly_savings']:,.0f}")
    cc.metric("📅 Risparmio annuale", f"€{cfg['monthly_savings'] * 12:,.0f}")
    cd.metric("🧮 Simulazioni MC",    f"{cfg['monte_carlo_runs']}")