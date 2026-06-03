"""
Simulazioni Monte Carlo per analisi di sostenibilita FIRE.

Funzioni esportate:
- monte_carlo_survival_given_initial()    -> probabilita di non esaurire il capitale
- required_capital_for_target_survival()  -> capitale minimo per target di sopravvivenza
"""

import numpy as np

from constants import CAPITAL_GAINS_TAX
from pension_fonte import FonteState, step_fonte, fonte_real_monthly, fonte_tax_rate_by_enrollment
from pension_inps import InpsState, annual_net_pension_from_gross, step_inps
from portfolio import gross_withdrawal_for_net_expense


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
    inps_montante_revaluation_rate: float,
) -> dict:
    """Calcola tutti i tassi mensili necessari alle simulazioni."""
    real_annual = (1 + nominal_return) / (1 + inflation) - 1
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
        inps_reval_monthly=(1 + inps_montante_revaluation_rate) ** (1 / 12) - 1,
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
    fonte_monthly: float,
    annual_pension_contribution: float,
    planned_retirement_age: float,
    fonte_access_age: int,
    fonte_enrollment_date: str,
    inps_montante_current: float,
    inps_reval_monthly: float,
    inps_contrib_growth_monthly: float,
    inps_annual_contribution: float,
    pension_access_age: int,
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
    start_age: float,
    months: int,
    rng: np.random.Generator,
) -> bool:
    """Esegue una singola simulazione Monte Carlo e restituisce se sopravvive fino a fine periodo."""
    fonte_tax_rate = fonte_tax_rate_by_enrollment(
        fonte_enrollment_date, float(fonte_access_age), start_age
    )

    fonte = FonteState(pot=pension_value)
    inps = InpsState(montante=inps_montante_current)
    inheritance_event_done = False
    ages = []
    portfolios = []

    for m in range(months + 1):
        age = start_age + m / 12
        ages.append(age)

        fonte, delta_p, delta_cb = step_fonte(
            fonte,
            m=m,
            age=age,
            monthly_rate=fonte_monthly,
            salary_growth_monthly=salary_growth_monthly,
            annual_pension_contribution=annual_pension_contribution,
            planned_retirement_age=planned_retirement_age,
            fonte_access_age=fonte_access_age,
            fonte_tax_rate=fonte_tax_rate,
        )
        portfolio += delta_p
        cost_basis += delta_cb

        inps = step_inps(
            inps,
            m=m,
            age=age,
            revaluation_monthly=inps_reval_monthly,
            contribution_growth_monthly=inps_contrib_growth_monthly,
            inps_annual_contribution=inps_annual_contribution,
            planned_retirement_age=planned_retirement_age,
            pension_access_age=pension_access_age,
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
                annual_net_pension_from_gross(inps.annual_pension) / 12 if inps.pension_started else 0.0
            )
            net_expense = max(monthly_post - monthly_inps, 0.0)
            if net_expense > 0 and portfolio > 0:
                gain_ratio = max(0.0, (portfolio - cost_basis) / portfolio)
                effective_tax = CAPITAL_GAINS_TAX * gain_ratio
                gross = gross_withdrawal_for_net_expense(net_expense, effective_tax)
                cost_basis *= max(0.0, (portfolio - gross) / portfolio)
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

        portfolio = portfolio * (1 + random_r) + cashflow_t
        portfolios.append(max(0.0, portfolio))

        if retired and portfolio <= 0:
            return False

    return True


def _build_common_kwargs(
    simulate_kwargs: dict,
    inflation: float,
    crash_impact: float,
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
        fonte_monthly=fonte_real_monthly(
            inflation,
            fonte_equity_return=float(simulate_kwargs.get("fonte_equity_return", 0.075)),
            fonte_bond_return=float(simulate_kwargs.get("fonte_bond_return", 0.035)),
            fonte_equity_weight=float(simulate_kwargs.get("fonte_equity_weight", 0.60)),
            fonte_bond_weight=float(simulate_kwargs.get("fonte_bond_weight", 0.40)),
        ),
        annual_pension_contribution=float(simulate_kwargs.get("annual_pension_contribution", 8211.0)),
        planned_retirement_age=float(simulate_kwargs["planned_retirement_age"]),
        fonte_access_age=int(simulate_kwargs.get("fonte_access_age", 50)),
        fonte_enrollment_date=str(simulate_kwargs.get("fonte_enrollment_date", "2021-04-01")),
        inps_montante_current=float(simulate_kwargs.get("inps_montante_current", 102456.0)),
        inps_annual_contribution=float(simulate_kwargs.get("inps_annual_contribution", 18023.0)),
        pension_access_age=int(simulate_kwargs["pension_access_age"]),
        housing_mode=str(simulate_kwargs["housing_mode"]),
        inheritance_age=int(simulate_kwargs["inheritance_age"]),
        inheritance_cash_amount=float(simulate_kwargs["inheritance_cash_amount"]),
        full_house_value_today=float(simulate_kwargs["full_house_value_today"]),
        crash_impact=crash_impact,
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
        float(simulate_kwargs.get("inps_montante_revaluation_rate", 0.015)),
    )
    months = int((end_age - start_age) * 12)
    common = _build_common_kwargs(simulate_kwargs, inflation, crash_impact, start_age, months, rates)
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
    """
    Cerca il capitale iniziale minimo per avere probabilita target di sopravvivenza.
    Restituisce (capitale_minimo, probabilita_effettiva).
    """
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
