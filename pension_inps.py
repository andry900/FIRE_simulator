"""
Logica INPS — sistema contributivo (metodo contributivo puro).

- Il montante cresce per rivalutazione e nuovi versamenti fino all'età FIRE
  (planned_retirement_age), poi solo per rivalutazione.
- All'età di accesso viene convertito in rendita annua lorda tramite
  coefficiente di trasformazione INPS deterministico per età.
- Il netto è calcolato con IRPEF progressiva a scaglioni + detrazione pensione.
"""

from dataclasses import dataclass


# Coefficienti di trasformazione (quota contributiva) per età, valori in frazione.
# Fonte normativa INPS (tabella coefficienti vigenti): es. 5.723% -> 0.05723.
INPS_TRANSFORMATION_COEFFICIENTS: dict[int, float] = {
    57: 0.04270,
    58: 0.04378,
    59: 0.04493,
    60: 0.04615,
    61: 0.04744,
    62: 0.04882,
    63: 0.05028,
    64: 0.05184,
    65: 0.05352,
    66: 0.05531,
    67: 0.05723,
    68: 0.05931,
    69: 0.06154,
    70: 0.06395,
    71: 0.06655,
}


@dataclass
class InpsState:
    montante: float                # montante contributivo accumulato (EUR)
    pension_started: bool = False  # True dopo avvio erogazione
    annual_pension: float = 0.0    # rendita annua lorda (EUR)


def inps_transformation_coefficient(age: float) -> float:
    """Restituisce il coefficiente INPS deterministico per età (anni interi)."""
    age_int = int(age)
    min_age = min(INPS_TRANSFORMATION_COEFFICIENTS)
    max_age = max(INPS_TRANSFORMATION_COEFFICIENTS)
    age_int = max(min_age, min(age_int, max_age))
    return INPS_TRANSFORMATION_COEFFICIENTS[age_int]


def irpef_gross_tax_annual(taxable_income: float) -> float:
    """Calcola l'imposta lorda IRPEF annua con scaglioni nazionali vigenti."""
    x = max(taxable_income, 0.0)
    if x <= 28_000:
        return 0.23 * x
    if x <= 50_000:
        return 0.23 * 28_000 + 0.35 * (x - 28_000)
    return 0.23 * 28_000 + 0.35 * (50_000 - 28_000) + 0.43 * (x - 50_000)


def pension_tax_credit_annual(gross_pension_annual: float) -> float:
    """
    Detrazione da pensione (stima normativa nazionale).
    Formula standard per redditi di pensione:
    - <= 8.500: 1.955 (minimo 713)
    - 8.500..28.000: 700 + 1.255 * (28.000 - reddito) / 19.500
    - 28.000..50.000: 700 * (50.000 - reddito) / 22.000
    - > 50.000: 0
    """
    r = max(gross_pension_annual, 0.0)
    if r <= 8_500:
        return max(1_955.0, 713.0)
    if r <= 28_000:
        return 700.0 + 1_255.0 * (28_000.0 - r) / 19_500.0
    if r <= 50_000:
        return 700.0 * (50_000.0 - r) / 22_000.0
    return 0.0


def annual_net_pension_from_gross(gross_pension_annual: float) -> float:
    """Pensione annua netta da lordo con IRPEF progressiva + detrazione pensione."""
    gross = max(gross_pension_annual, 0.0)
    imposta_lorda = irpef_gross_tax_annual(gross)
    detrazione = pension_tax_credit_annual(gross)
    imposta_netta = max(imposta_lorda - detrazione, 0.0)
    return max(gross - imposta_netta, 0.0)


def step_inps(
    state: InpsState,
    *,
    m: int,
    age: float,
    revaluation_monthly: float,
    contribution_growth_monthly: float,
    inps_annual_contribution: float,
    planned_retirement_age: float,
    pension_access_age: int,
) -> InpsState:
    """Avanza lo stato INPS di un mese."""
    if state.pension_started:
        return state

    montante = state.montante
    if age < planned_retirement_age:
        monthly_contrib = (
            inps_annual_contribution
            * ((1 + contribution_growth_monthly) ** m)
            / 12
        )
        montante = montante * (1 + revaluation_monthly) + monthly_contrib
    else:
        montante = montante * (1 + revaluation_monthly)

    if age >= pension_access_age:
        coeff = inps_transformation_coefficient(float(pension_access_age))
        annual_pension = montante * coeff
        return InpsState(montante=montante, pension_started=True, annual_pension=annual_pension)

    return InpsState(montante=montante, pension_started=False, annual_pension=0.0)


def project_inps_pension(
    montante_current: float,
    revaluation_rate: float,
    years_to_pension: float,
    pension_access_age: int,
) -> float:
    """Stima pensione annua lorda al momento dell'accesso (solo rivalutazione montante)."""
    projected_montante = montante_current * ((1 + revaluation_rate) ** years_to_pension)
    coeff = inps_transformation_coefficient(float(pension_access_age))
    return projected_montante * coeff
