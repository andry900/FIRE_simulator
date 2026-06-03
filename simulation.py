"""
Simulazione deterministica FIRE in euro reali (inflazione rimossa).

Funzioni esportate:
- simulate()      → proiezione mese per mese del patrimonio
- find_fire_age() → binary search sull'età FIRE minima sostenibile
"""

import pandas as pd

from constants import CAPITAL_GAINS_TAX
from pension_fonte import FonteState, step_fonte, fonte_real_monthly, fonte_tax_rate_by_enrollment
from pension_inps import InpsState, annual_net_pension_from_gross, step_inps
from portfolio import gross_withdrawal_for_net_expense


def simulate(
    portfolio_start: float,
    monthly_salary: float,
    monthly_non_housing_expenses: float,
    salary_growth_rate: float,
    post_fire_expense_multiplier: float,
    rent_monthly_now: float,
    rent_real_growth: float,
    owner_monthly_cost: float,
    owner_cost_real_growth: float,
    nominal_return: float,
    inflation: float,
    threshold_swr: float,
    pension_value: float,
    pension_access_age: int,
    planned_retirement_age: float,
    housing_mode: str,
    inheritance_age: int,
    inheritance_cash_amount: float,
    full_house_value_today: float,
    real_estate_appreciation: float,
    start_age: float,
    end_age: int,
    annual_pension_contribution: float = 8211.0,
    fonte_access_age: int = 50,
    fonte_enrollment_date: str = "2021-04-01",
    fonte_equity_return: float = 0.075,
    fonte_bond_return: float = 0.035,
    fonte_equity_weight: float = 0.60,
    fonte_bond_weight: float = 0.40,
    inps_montante_current: float = 102456.0,
    inps_annual_contribution: float = 18023.0,
    inps_contribution_growth_rate: float = 0.03,
    inps_montante_revaluation_rate: float = 0.015,
    initial_gain_pct: float = 0.30,
) -> tuple[pd.DataFrame, bool]:
    """
    Proietta il patrimonio in euro reali (inflazione rimossa).
    Dopo planned_retirement_age lo stipendio viene azzerato e restano solo le spese.
    Tassazione sui prelievi: 26% solo sulla quota plusvalenza (gain_ratio dinamico).
    Restituisce (DataFrame mensile, successo_a_fine_periodo).
    """
    real_annual = (1 + nominal_return) / (1 + inflation) - 1
    real_monthly = (1 + real_annual) ** (1 / 12) - 1
    f_monthly = fonte_real_monthly(
        inflation,
        fonte_equity_return=fonte_equity_return,
        fonte_bond_return=fonte_bond_return,
        fonte_equity_weight=fonte_equity_weight,
        fonte_bond_weight=fonte_bond_weight,
    )

    salary_growth_monthly = (1 + salary_growth_rate) ** (1 / 12) - 1
    rent_growth_monthly = (1 + rent_real_growth) ** (1 / 12) - 1
    owner_growth_monthly = (1 + owner_cost_real_growth) ** (1 / 12) - 1
    inflation_monthly = (1 + inflation) ** (1 / 12) - 1
    real_estate_real_annual = (1 + real_estate_appreciation) / (1 + inflation) - 1
    real_estate_growth_monthly = (1 + real_estate_real_annual) ** (1 / 12) - 1
    inps_contrib_growth_monthly = (1 + inps_contribution_growth_rate) ** (1 / 12) - 1
    inps_reval_monthly = (1 + inps_montante_revaluation_rate) ** (1 / 12) - 1
    fonte_tax_rate = fonte_tax_rate_by_enrollment(
        fonte_enrollment_date, float(fonte_access_age), start_age
    )

    months = int((end_age - start_age) * 12)
    ages, values, fire_nums = [], [], []
    portfolio = portfolio_start
    cost_basis = portfolio_start * (1 - initial_gain_pct)

    fonte = FonteState(pot=pension_value)
    inps = InpsState(montante=inps_montante_current)
    inheritance_event_done = False
    success = True

    for m in range(months + 1):
        age = start_age + m / 12

        # ── Fon.te ──────────────────────────────────────────────────────────
        fonte, delta_p, delta_cb = step_fonte(
            fonte,
            m=m, age=age,
            monthly_rate=f_monthly,
            salary_growth_monthly=salary_growth_monthly,
            annual_pension_contribution=annual_pension_contribution,
            planned_retirement_age=planned_retirement_age,
            fonte_access_age=fonte_access_age,
            fonte_tax_rate=fonte_tax_rate,
        )
        portfolio += delta_p
        cost_basis += delta_cb

        # ── INPS ─────────────────────────────────────────────────────────────
        inps = step_inps(
            inps,
            m=m, age=age,
            revaluation_monthly=inps_reval_monthly,
            contribution_growth_monthly=inps_contrib_growth_monthly,
            inps_annual_contribution=inps_annual_contribution,
            planned_retirement_age=planned_retirement_age,
            pension_access_age=pension_access_age,
        )

        # ── Eredità ──────────────────────────────────────────────────────────
        if not inheritance_event_done and age >= inheritance_age:
            months_to_inh = max(int(round((inheritance_age - start_age) * 12)), 0)
            inheritance_cash_real = inheritance_cash_amount / ((1 + inflation_monthly) ** months_to_inh)
            full_house_value = full_house_value_today * (
                (1 + real_estate_growth_monthly) ** months_to_inh
            )
            portfolio += inheritance_cash_real
            cost_basis += inheritance_cash_real
            if housing_mode == "rent_life_with_sale":
                portfolio += full_house_value
                cost_basis += full_house_value
            inheritance_event_done = True

        # ── Costo abitativo ──────────────────────────────────────────────────
        if housing_mode == "owner_after_inheritance" and age >= inheritance_age:
            months_to_inh = max(int(round((inheritance_age - start_age) * 12)), 0)
            months_since_inh = max(m - months_to_inh, 0)
            housing_monthly = owner_monthly_cost * ((1 + owner_growth_monthly) ** months_since_inh)
        else:
            housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)

        monthly_expenses_t = monthly_non_housing_expenses + housing_monthly
        annual_expenses_post = monthly_expenses_t * 12 * post_fire_expense_multiplier

        # ── FIRE number (per visualizzazione) ────────────────────────────────
        if inps.pension_started:
            annual_inps_net = annual_net_pension_from_gross(inps.annual_pension)
            net_for_fire = max(annual_expenses_post - annual_inps_net, 0)
        else:
            net_for_fire = annual_expenses_post
        fire_number_t = net_for_fire / threshold_swr

        ages.append(round(age, 4))
        values.append(round(portfolio, 2))
        fire_nums.append(round(fire_number_t, 2))

        # ── Cash flow mensile ────────────────────────────────────────────────
        retired = age >= planned_retirement_age
        salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)

        if retired:
            monthly_post = monthly_expenses_t * post_fire_expense_multiplier
            monthly_inps = (
                annual_net_pension_from_gross(inps.annual_pension) / 12
                if inps.pension_started else 0.0
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

        portfolio = portfolio * (1 + real_monthly) + cashflow_t
        if retired and portfolio <= 0:
            portfolio = 0
            success = False

    return (
        pd.DataFrame({"age": ages, "portfolio": values, "fire_number": fire_nums}),
        success,
    )


def find_fire_age(precision: float = 0.1, **simulate_kwargs) -> float | None:
    """
    Trova l'età FIRE minima sostenibile tramite binary search.
    Logica: qual è la prima età in cui, smettendo di lavorare, il portafoglio
    non si esaurisce mai fino a end_age?
    """
    start_age = float(simulate_kwargs["start_age"])
    end_age = int(simulate_kwargs["end_age"])

    _, success_now = simulate(**{**simulate_kwargs, "planned_retirement_age": start_age})
    if success_now:
        return start_age

    _, success_max = simulate(**{**simulate_kwargs, "planned_retirement_age": float(end_age)})
    if not success_max:
        return None

    lo, hi = start_age, float(end_age)
    while hi - lo > precision:
        mid = (lo + hi) / 2
        _, ok = simulate(**{**simulate_kwargs, "planned_retirement_age": mid})
        if ok:
            hi = mid
        else:
            lo = mid

    return round(hi, 1)
