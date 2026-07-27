"""
Logica INPS — sistema contributivo (metodo contributivo puro).

- Il montante cresce per rivalutazione e nuovi versamenti fino all'età FIRE
  (planned_retirement_age), poi solo per rivalutazione.
- All'età di accesso viene convertito in rendita annua lorda tramite
  coefficiente di trasformazione INPS deterministico per età.
- Il netto è calcolato con IRPEF progressiva a scaglioni + detrazione pensione
  + addizionali regionale e comunale.

Note sulla rivalutazione:
- La rivalutazione del montante INPS è ANNUALE (al 31 dicembre, in base alla
  media quinquennale del PIL nominale). Modellarla mensile con tasso
  annualizzato sopravaluta il montante. Qui usiamo capitalizzazione annua a
  fine anno, mentre i contributi entrano mensilmente non rivalutati durante
  l'anno (semplificazione tipica).
"""

from dataclasses import dataclass

from constants import DEFAULT_MUNICIPAL_SURTAX, DEFAULT_REGIONAL_SURTAX


# Coefficienti di trasformazione 2025 (decreto MEF 1/1/2025).
# Valori in frazione (es. 5,608% -> 0.05608).
# Fonte: Decreto Ministero del Lavoro 22/05/2024 — coefficienti revisione
# triennale, in vigore dal 1° gennaio 2025.
# Nota: per le età 72-75 usiamo una estensione stimata e monotona della
# progressione 67-71, utile per analisi what-if oltre il range ufficiale.
INPS_TRANSFORMATION_COEFFICIENTS: dict[int, float] = {
    57: 0.04186,
    58: 0.04289,
    59: 0.04399,
    60: 0.04515,
    61: 0.04639,
    62: 0.04770,
    63: 0.04910,
    64: 0.05060,
    65: 0.05220,
    66: 0.05391,
    67: 0.05608,
    68: 0.05814,
    69: 0.06034,
    70: 0.06273,
    71: 0.06530,
    72: 0.06805,
    73: 0.07098,
    74: 0.07409,
    75: 0.07738,
}


@dataclass
class InpsState:
    montante: float                # montante contributivo accumulato (EUR)
    contributed_years: float = 0.0 # anni contributivi maturati
    pension_started: bool = False  # True dopo avvio erogazione
    annual_pension: float = 0.0    # rendita annua lorda (EUR)


def inps_transformation_coefficient(age: float, future_haircut: float = 0.0) -> float:
    """Coefficiente INPS deterministico per età (anni interi).

    future_haircut applica una riduzione percentuale (0..1) ai coefficienti
    ufficiali per simulare ulteriori revisioni triennali sfavorevoli (la
    longevità tende ad aumentare → coefficienti destinati a scendere). Default 0
    per usare i coefficienti vigenti.
    """
    age_int = int(age)
    min_age = min(INPS_TRANSFORMATION_COEFFICIENTS)
    max_age = max(INPS_TRANSFORMATION_COEFFICIENTS)
    age_int = max(min_age, min(age_int, max_age))
    base = INPS_TRANSFORMATION_COEFFICIENTS[age_int]
    haircut = max(0.0, min(0.5, float(future_haircut)))
    return base * (1.0 - haircut)


def irpef_gross_tax_annual(taxable_income: float) -> float:
    """Calcola l'imposta lorda IRPEF erariale annua (scaglioni 2024+)."""
    x = max(taxable_income, 0.0)
    if x <= 28_000:
        return 0.23 * x
    if x <= 50_000:
        return 0.23 * 28_000 + 0.35 * (x - 28_000)
    return 0.23 * 28_000 + 0.35 * (50_000 - 28_000) + 0.43 * (x - 50_000)


def pension_tax_credit_annual(gross_pension_annual: float) -> float:
    """Detrazione da pensione (art. 13 c.3 TUIR vigente).

    - <= 8.500: 1.955 (con minimo 713)
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


def annual_net_pension_from_gross(
    gross_pension_annual: float,
    regional_surtax: float = DEFAULT_REGIONAL_SURTAX,
    municipal_surtax: float = DEFAULT_MUNICIPAL_SURTAX,
) -> float:
    """Pensione annua netta da lordo: IRPEF erariale - detrazione + addizionali.

    Le addizionali regionale e comunale si applicano sul reddito complessivo
    (qui assunto = pensione lorda) SENZA detrazione, sopra la no-tax-area
    pensione (8.500 €). Modello semplificato: applichiamo le addizionali piene
    sull'eccedenza oltre 8.500 €.
    """
    gross = max(gross_pension_annual, 0.0)
    imposta_lorda = irpef_gross_tax_annual(gross)
    detrazione = pension_tax_credit_annual(gross)
    irpef_netta = max(imposta_lorda - detrazione, 0.0)

    # Addizionali: si applicano se l'IRPEF lorda supera la detrazione (cioè
    # sopra la no-tax-area). Approssimazione: base = pensione lorda oltre 8.500.
    taxable_for_surtax = max(gross - 8_500.0, 0.0) if irpef_netta > 0 else 0.0
    addizionali = taxable_for_surtax * (regional_surtax + municipal_surtax)

    totale_imposte = irpef_netta + addizionali
    return max(gross - totale_imposte, 0.0)


def step_inps(
    state: InpsState,
    *,
    m: int,
    age: float,
    revaluation_annual: float,
    contribution_growth_monthly: float,
    inps_annual_contribution: float,
    planned_retirement_age: float,
    pension_access_age: int,
    years_contributed_required: float = 20.0,
    fill_missing_years_after_fire: bool = False,
    coefficient_haircut: float = 0.0,
    gross_pension_factor: float = 1.0,
) -> InpsState:
    """Avanza lo stato INPS di un mese.

    - I contributi entrano mensilmente (1/12 del valore annuo cresciuto).
    - La rivalutazione del montante è applicata ANNUALMENTE (a fine dell'anno
      di simulazione, cioè ogni 12 mesi: m % 12 == 11) per riflettere le regole
      INPS reali (non capitalizzazione mensile).
    """
    if state.pension_started:
        return state

    montante = state.montante
    contributed_years = state.contributed_years
    required_years = max(0.0, float(years_contributed_required))

    should_contribute = age < planned_retirement_age
    if (not should_contribute) and fill_missing_years_after_fire and contributed_years < required_years:
        should_contribute = True

    if should_contribute:
        monthly_contrib = (
            inps_annual_contribution
            * ((1 + contribution_growth_monthly) ** m)
            / 12
        )
        montante = montante + monthly_contrib
        contributed_years += (1 / 12)

    # Rivalutazione annuale al termine di ogni anno di simulazione.
    if m > 0 and m % 12 == 0:
        montante = montante * (1 + revaluation_annual)

    if age >= pension_access_age and contributed_years >= required_years:
        coeff = inps_transformation_coefficient(
            float(pension_access_age), future_haircut=coefficient_haircut
        )
        factor = max(0.3, min(1.0, float(gross_pension_factor)))
        annual_pension = montante * coeff * factor
        return InpsState(
            montante=montante,
            contributed_years=contributed_years,
            pension_started=True,
            annual_pension=annual_pension,
        )

    return InpsState(
        montante=montante,
        contributed_years=contributed_years,
        pension_started=False,
        annual_pension=0.0,
    )


def project_inps_pension(
    montante_current: float,
    revaluation_rate: float,
    years_to_pension: float,
    pension_access_age: int,
    coefficient_haircut: float = 0.0,
    gross_pension_factor: float = 1.0,
) -> float:
    """Stima pensione annua lorda al momento dell'accesso (solo rivalutazione)."""
    projected_montante = montante_current * ((1 + revaluation_rate) ** years_to_pension)
    coeff = inps_transformation_coefficient(
        float(pension_access_age), future_haircut=coefficient_haircut
    )
    factor = max(0.3, min(1.0, float(gross_pension_factor)))
    return projected_montante * coeff * factor