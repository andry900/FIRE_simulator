"""
Simulazioni Monte Carlo per analisi di sostenibilita FIRE.

Funzioni esportate:
- monte_carlo_survival_given_initial()    -> probabilita di non esaurire il capitale
- required_capital_for_target_survival()  -> capitale minimo per target di sopravvivenza

Note: la binary search di required_capital_for_target_survival usa lo stesso
random_seed per tutte le iterazioni, applicando di fatto Common Random Numbers
(variance reduction). I percorsi sono quindi confrontabili tra capitali diversi
ma il survival rate finale resta sempre stimato MC.
"""

import numpy as np

from constants import DEFAULT_MUNICIPAL_SURTAX, DEFAULT_REGIONAL_SURTAX
from pension_fonte import FonteState, step_fonte, fonte_real_monthly, fonte_tax_rate_by_enrollment
from pension_inps import InpsState, annual_net_pension_from_gross, step_inps
from portfolio import (
    effective_capital_gains_tax,
    gross_withdrawal_for_net_expense,
    portfolio_annual_drag,
)


def _monthly_rates(
    nominal_return: float,
    inflation: float,
    annual_volatility: float,
    crash_prob_annual: float,
    salary_growth_rate: float,
    rent_real_growth: float,
    owner_cost_real_growth: float,
    real_estate_appreciation: float,
    inps_contribution_growth_rate: float,
    portfolio_drag: float,
) -> dict:
    """Calcola tutti i tassi mensili necessari alle simulazioni."""
    nominal_after_drag = max(nominal_return - portfolio_drag, 0.0)
    real_annual = (1 + nominal_after_drag) / (1 + inflation) - 1
    real_estate_real_annual = (1 + real_estate_appreciation) / (1 + inflation) - 1
    return dict(
        real_monthly_mean=(1 + real_annual) ** (1 / 12) - 1,
        monthly_std=annual_volatility / np.sqrt(12),
        monthly_crash_prob=crash_prob_annual / 12,
        inflation_monthly=(1 + inflation) ** (1 / 12) - 1,
        salary_growth_monthly=(1 + salary_growth_rate) ** (1 / 12) - 1,
        rent_growth_monthly=(1 + rent_real_growth) ** (1 / 12) - 1,
        owner_growth_monthly=(1 + owner_cost_real_growth) ** (1 / 12) - 1,
        real_estate_growth_monthly=(1 + real_estate_real_annual) ** (1 / 12) - 1,
        inps_contrib_growth_monthly=(1 + inps_contribution_growth_rate) ** (1 / 12) - 1,
    )


def _run_one_mc(
    *,
    portfolio: float,
    cost_basis: float,
    monthly_salary: float,
    monthly_non_housing_expenses: float,
    salary_growth_monthly: float,
    post_fire_expense_multiplier: float,
    rent_monthly_now: float,
    rent_growth_monthly: float,
    owner_monthly_cost: float,
    owner_growth_monthly: float,
    pension_value: float,
    fonte_contributions_paid: float,
    fonte_monthly: float,
    annual_pension_contribution: float,
    planned_retirement_age: float,
    fonte_access_age: float,
    fonte_unlock_years_after_fire: float | None,
    fonte_enrollment_date: str,
    inps_montante_current: float,
    inps_montante_revaluation_rate: float,
    inps_contrib_growth_monthly: float,
    inps_annual_contribution: float,
    inps_years_contributed_current: float,
    inps_fill_missing_years: bool,
    inps_gross_factor: float,
    pension_access_age: int,
    inps_coefficient_haircut: float,
    housing_mode: str,
    inheritance_age: int,
    inheritance_cash_amount: float,
    full_house_value_today: float,
    inflation_monthly: float,
    real_estate_growth_monthly: float,
    real_monthly_mean: float,
    monthly_std: float,
    monthly_crash_prob: float,
    crash_impact: float,
    capital_gains_rate: float,
    regional_surtax: float,
    municipal_surtax: float,
    start_age: float,
    months: int,
    rng: np.random.Generator,
) -> bool:
    """Esegue una singola simulazione Monte Carlo."""
    fonte_post_fire_real_monthly = (1 / (1 + inflation_monthly)) - 1
    effective_fonte_access_age = (
        float(planned_retirement_age) + max(float(fonte_unlock_years_after_fire), 0.0)
        if fonte_unlock_years_after_fire is not None
        else float(fonte_access_age)
    )
    fonte_tax_rate = fonte_tax_rate_by_enrollment(
        fonte_enrollment_date, float(planned_retirement_age), start_age
    )

    fonte = FonteState(pot=pension_value, contributions_paid=fonte_contributions_paid)
    inps = InpsState(
        montante=inps_montante_current,
        contributed_years=max(float(inps_years_contributed_current), 0.0),
    )
    inheritance_event_done = False

    for m in range(months + 1):
        age = start_age + m / 12

        fonte, delta_p, delta_cb = step_fonte(
            fonte,
            m=m,
            age=age,
            monthly_rate=fonte_monthly,
            monthly_rate_post_fire=fonte_post_fire_real_monthly,
            salary_growth_monthly=salary_growth_monthly,
            annual_pension_contribution=annual_pension_contribution,
            planned_retirement_age=planned_retirement_age,
            fonte_access_age=effective_fonte_access_age,
            fonte_tax_rate=fonte_tax_rate,
        )
        portfolio += delta_p
        cost_basis += delta_cb

        inps, inps_contrib_paid = step_inps(
            inps,
            m=m,
            age=age,
            revaluation_annual=inps_montante_revaluation_rate,
            contribution_growth_monthly=inps_contrib_growth_monthly,
            inps_annual_contribution=inps_annual_contribution,
            planned_retirement_age=planned_retirement_age,
            pension_access_age=pension_access_age,
            years_contributed_required=20.0,
            fill_missing_years_after_fire=inps_fill_missing_years,
            coefficient_haircut=inps_coefficient_haircut,
            gross_pension_factor=inps_gross_factor,
        )

        if not inheritance_event_done and age >= inheritance_age:
            months_to_inh = max(int(round((inheritance_age - start_age) * 12)), 0)
            inheritance_cash_real = inheritance_cash_amount / ((1 + inflation_monthly) ** months_to_inh)
            full_house = full_house_value_today * ((1 + real_estate_growth_monthly) ** months_to_inh)
            portfolio += inheritance_cash_real
            cost_basis += inheritance_cash_real
            if housing_mode == "rent_life_with_sale":
                portfolio += full_house
                cost_basis += full_house
            inheritance_event_done = True

        if housing_mode == "owner_after_inheritance" and age >= inheritance_age:
            months_to_inh = max(int(round((inheritance_age - start_age) * 12)), 0)
            months_since_inh = max(m - months_to_inh, 0)
            housing_monthly = owner_monthly_cost * ((1 + owner_growth_monthly) ** months_since_inh)
        else:
            housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)

        monthly_expenses_t = monthly_non_housing_expenses + housing_monthly
        retired = age >= planned_retirement_age
        salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)

        if retired:
            monthly_post = monthly_expenses_t * post_fire_expense_multiplier
            monthly_inps = (
                annual_net_pension_from_gross(
                    inps.annual_pension,
                    regional_surtax=regional_surtax,
                    municipal_surtax=municipal_surtax,
                ) / 12 if inps.pension_started else 0.0
            )
            extra_inps_contrib = inps_contrib_paid if inps_contrib_paid > 0 else 0.0
            net_expense = max(monthly_post - monthly_inps, 0.0) + extra_inps_contrib
            if net_expense > 0 and portfolio > 0:
                gain_ratio = max(0.0, (portfolio - cost_basis) / portfolio)
                effective_tax = capital_gains_rate * gain_ratio
                gross = gross_withdrawal_for_net_expense(net_expense, effective_tax)
                gross = min(gross, portfolio)
                cost_basis *= max(0.0, (portfolio - gross) / portfolio) if portfolio > 0 else 0.0
                cashflow_t = -gross
            else:
                cashflow_t = 0.0
        else:
            cashflow_t = salary_t - monthly_expenses_t
            if cashflow_t > 0:
                cost_basis += cashflow_t

        random_r = rng.normal(real_monthly_mean, monthly_std)
        if rng.random() < monthly_crash_prob:
            random_r += crash_impact

        if cashflow_t < 0:
            mid_month_factor = (1 + random_r) ** 0.5 if random_r > -1 else 0.0
            portfolio = portfolio * (1 + random_r) + cashflow_t * mid_month_factor
        else:
            portfolio = portfolio * (1 + random_r) + cashflow_t

        if retired and portfolio <= 0:
            return False

    return True


def _build_common_kwargs(
    simulate_kwargs: dict,
    inflation: float,
    crash_impact: float,
    capital_gains_rate: float,
    start_age: float,
    months: int,
    rates: dict,
) -> dict:
    """Costruisce il dizionario di argomenti comuni per _run_one_mc."""
    return dict(
        monthly_salary=float(simulate_kwargs["monthly_salary"]),
        monthly_non_housing_expenses=float(simulate_kwargs["monthly_non_housing_expenses"]),
        post_fire_expense_multiplier=float(simulate_kwargs["post_fire_expense_multiplier"]),
        rent_monthly_now=float(simulate_kwargs["rent_monthly_now"]),
        owner_monthly_cost=float(simulate_kwargs["owner_monthly_cost"]),
        pension_value=float(simulate_kwargs["pension_value"]),
        fonte_contributions_paid=float(simulate_kwargs.get("fonte_contributions_paid", 0.0)),
        fonte_monthly=fonte_real_monthly(
            inflation,
            fonte_equity_return=float(simulate_kwargs.get("fonte_equity_return", 0.075)),
            fonte_bond_return=float(simulate_kwargs.get("fonte_bond_return", 0.035)),
            fonte_equity_weight=float(simulate_kwargs.get("fonte_equity_weight", 0.60)),
            fonte_bond_weight=float(simulate_kwargs.get("fonte_bond_weight", 0.40)),
        ),
        annual_pension_contribution=float(simulate_kwargs.get("annual_pension_contribution", 8211.0)),
        planned_retirement_age=float(simulate_kwargs["planned_retirement_age"]),
        fonte_access_age=float(simulate_kwargs.get("fonte_access_age", 50.0)),
        fonte_unlock_years_after_fire=(
            None
            if simulate_kwargs.get("fonte_unlock_years_after_fire") is None
            else float(simulate_kwargs.get("fonte_unlock_years_after_fire"))
        ),
        fonte_enrollment_date=str(simulate_kwargs.get("fonte_enrollment_date", "2021-04-01")),
        inps_montante_current=float(simulate_kwargs.get("inps_montante_current", 102456.0)),
        inps_montante_revaluation_rate=float(
            simulate_kwargs.get("inps_montante_revaluation_rate", 0.015)
        ),
        inps_annual_contribution=float(simulate_kwargs.get("inps_annual_contribution", 18023.0)),
        inps_years_contributed_current=float(simulate_kwargs.get("inps_years_contributed_current", 10.0)),
        inps_fill_missing_years=bool(simulate_kwargs.get("inps_fill_missing_years", False)),
        inps_gross_factor=float(simulate_kwargs.get("inps_gross_factor", 1.0)),
        pension_access_age=int(simulate_kwargs["pension_access_age"]),
        inps_coefficient_haircut=float(simulate_kwargs.get("inps_coefficient_haircut", 0.0)),
        housing_mode=str(simulate_kwargs["housing_mode"]),
        inheritance_age=int(simulate_kwargs["inheritance_age"]),
        inheritance_cash_amount=float(simulate_kwargs["inheritance_cash_amount"]),
        full_house_value_today=float(simulate_kwargs["full_house_value_today"]),
        crash_impact=crash_impact,
        capital_gains_rate=capital_gains_rate,
        regional_surtax=float(simulate_kwargs.get("regional_surtax", DEFAULT_REGIONAL_SURTAX)),
        municipal_surtax=float(simulate_kwargs.get("municipal_surtax", DEFAULT_MUNICIPAL_SURTAX)),
        start_age=start_age,
        months=months,
        **rates,
    )


def monte_carlo_survival_given_initial(
    initial_portfolio: float,
    n_sims: int,
    annual_volatility: float,
    crash_prob_annual: float,
    crash_impact: float,
    random_seed: int | None = None,
    **simulate_kwargs,
) -> float:
    """Probabilita di non esaurire il capitale fino a end_age con pensionamento pianificato."""
    nominal_return = float(simulate_kwargs["nominal_return"])
    inflation = float(simulate_kwargs["inflation"])
    start_age = float(simulate_kwargs["start_age"])
    end_age = int(simulate_kwargs["end_age"])
    initial_gain_pct = float(simulate_kwargs.get("initial_gain_pct", 0.30))
    state_bond_share = float(simulate_kwargs.get("state_bond_share", 0.0))
    portfolio_ter = float(simulate_kwargs.get("portfolio_ter", 0.003))
    stamp_duty_rate = float(simulate_kwargs.get("stamp_duty_rate", 0.002))
    drag_annual = portfolio_annual_drag(ter=portfolio_ter, stamp_duty=stamp_duty_rate)
    capital_gains_rate = effective_capital_gains_tax(state_bond_share)

    rates = _monthly_rates(
        nominal_return,
        inflation,
        annual_volatility,
        crash_prob_annual,
        float(simulate_kwargs["salary_growth_rate"]),
        float(simulate_kwargs["rent_real_growth"]),
        float(simulate_kwargs["owner_cost_real_growth"]),
        float(simulate_kwargs["real_estate_appreciation"]),
        float(simulate_kwargs.get("inps_contribution_growth_rate", 0.03)),
        drag_annual,
    )
    months = int((end_age - start_age) * 12)
    common = _build_common_kwargs(
        simulate_kwargs, inflation, crash_impact, capital_gains_rate, start_age, months, rates
    )
    rng = np.random.default_rng(random_seed)

    success_count = sum(
        1
        for _ in range(n_sims)
        if _run_one_mc(
            portfolio=initial_portfolio,
            cost_basis=initial_portfolio * (1 - initial_gain_pct),
            rng=rng,
            **common,
        )
    )
    return success_count / n_sims if n_sims > 0 else 0.0


def required_capital_for_target_survival(
    target_survival: float,
    n_sims: int,
    annual_volatility: float,
    crash_prob_annual: float,
    crash_impact: float,
    random_seed: int | None = None,
    **simulate_kwargs,
) -> tuple[float, float]:
    """Capitale iniziale minimo per probabilità target di sopravvivenza."""
    low = 0.0
    high = max(float(simulate_kwargs["portfolio_start"]), 100_000.0)

    mc_kwargs = dict(
        n_sims=n_sims,
        annual_volatility=annual_volatility,
        crash_prob_annual=crash_prob_annual,
        crash_impact=crash_impact,
        random_seed=random_seed,
        **simulate_kwargs,
    )

    for _ in range(12):
        if monte_carlo_survival_given_initial(initial_portfolio=high, **mc_kwargs) >= target_survival:
            break
        high *= 1.5

    for _ in range(16):
        mid = (low + high) / 2
        if monte_carlo_survival_given_initial(initial_portfolio=mid, **mc_kwargs) >= target_survival:
            high = mid
        else:
            low = mid

    final_prob = monte_carlo_survival_given_initial(initial_portfolio=high, **mc_kwargs)
    return high, final_prob