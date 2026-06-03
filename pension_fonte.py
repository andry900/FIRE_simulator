"""
Logica del fondo pensione complementare Fon.te.

Composizione del fondo:
- 60% azionario ETF  → rendimento stimato 7,5% nominale
- 40% obbligazionario → rendimento stimato 3,5% nominale
→ rendimento nominale complessivo: 5,9%

Il montante cresce con i versamenti (proporzionali allo stipendio) fino
all'età FIRE (planned_retirement_age), poi solo per rivalutazione.
Al raggiungimento dell'età
di sblocco viene liquidato al netto della tassazione agevolata sulle
prestazioni (default 9%).
"""

from dataclasses import dataclass
from datetime import datetime

DEFAULT_FONTE_EQUITY_RETURN: float = 0.075
DEFAULT_FONTE_BOND_RETURN: float = 0.035
DEFAULT_FONTE_EQUITY_WEIGHT: float = 0.60
DEFAULT_FONTE_BOND_WEIGHT: float = 0.40


def fonte_tax_rate_by_enrollment(enrollment_date: str, unlock_age: float, current_age: float) -> float:
    """
    Calcola l'aliquota di tassazione Fon.te in base agli anni di iscrizione (interi).
    Regole:
    - Dal 1° al 15° anno: 15%
    - Dal 16° anno in poi: riduzione dello 0,30% per ogni anno aggiuntivo
    - Dal 35° anno in poi: limite minimo 9%
    
    Parametri:
    - enrollment_date: data iscrizione (YYYY-MM-DD)
    - unlock_age: età dello sblocco (pianificata)
    - current_age: età attuale
    
    Restituisce: aliquota di tassazione (es. 0.15, 0.12, 0.09)
    
    Nota: Si conteggia solo per anni interi completati, non per frazioni di anno.
    """
    try:
        enrollment_dt = datetime.strptime(enrollment_date, "%Y-%m-%d")
        current_dt = datetime.now()
        # Calcola solo anni interi completati (non frazionari)
        years_of_enrollment = int((current_dt - enrollment_dt).days / 365.25)
        # Aggiungi gli anni interi dal presente all'unlock
        years_of_enrollment += int(max(unlock_age - current_age, 0))
    except (ValueError, TypeError):
        years_of_enrollment = 0
    
    if years_of_enrollment <= 15:
        return 0.15
    elif years_of_enrollment >= 35:
        return 0.09
    else:
        # Dal 16° al 34° anno: riduzione dello 0,30% per ogni anno oltre il 15°
        years_beyond_15 = years_of_enrollment - 15
        return max(0.15 - (years_beyond_15 * 0.003), 0.09)


@dataclass
class FonteState:
    pot: float          # montante accumulato (€ reali)
    added: bool = False # True dopo lo sblocco e il versamento nel portafoglio


def fonte_nominal_annual(
    fonte_equity_return: float,
    fonte_bond_return: float,
    fonte_equity_weight: float,
    fonte_bond_weight: float,
) -> float:
    """Rendimento nominale annuo del fondo Fon.te con pesi normalizzati."""
    total_weight = fonte_equity_weight + fonte_bond_weight
    if total_weight <= 0:
        return (
            DEFAULT_FONTE_EQUITY_WEIGHT * DEFAULT_FONTE_EQUITY_RETURN
            + DEFAULT_FONTE_BOND_WEIGHT * DEFAULT_FONTE_BOND_RETURN
        )

    ew = fonte_equity_weight / total_weight
    bw = fonte_bond_weight / total_weight
    return ew * fonte_equity_return + bw * fonte_bond_return


def fonte_real_monthly(
    inflation: float,
    fonte_equity_return: float = DEFAULT_FONTE_EQUITY_RETURN,
    fonte_bond_return: float = DEFAULT_FONTE_BOND_RETURN,
    fonte_equity_weight: float = DEFAULT_FONTE_EQUITY_WEIGHT,
    fonte_bond_weight: float = DEFAULT_FONTE_BOND_WEIGHT,
) -> float:
    """Tasso reale mensile del fondo Fon.te dato inflazione, rendimenti e pesi."""
    fonte_nominal = fonte_nominal_annual(
        fonte_equity_return,
        fonte_bond_return,
        fonte_equity_weight,
        fonte_bond_weight,
    )
    real_annual = (1 + fonte_nominal) / (1 + inflation) - 1
    return (1 + real_annual) ** (1 / 12) - 1


def step_fonte(
    state: FonteState,
    *,
    m: int,
    age: float,
    monthly_rate: float,
    salary_growth_monthly: float,
    annual_pension_contribution: float,
    planned_retirement_age: float,
    fonte_access_age: int,
    fonte_tax_rate: float,
) -> tuple[FonteState, float, float]:
    """
    Avanza lo stato Fon.te di un mese.

    I versamenti annui cessano all'età FIRE (planned_retirement_age),
    non all'età di accesso pensione pubblica.

    Restituisce (nuovo_stato, delta_portafoglio, delta_cost_basis).
    Il delta è positivo solo nell'anno di sblocco (versamento nel portafoglio).
    """
    if state.added:
        return state, 0.0, 0.0

    pot = state.pot
    if age < planned_retirement_age:
        pot = (
            pot * (1 + monthly_rate)
            + annual_pension_contribution * ((1 + salary_growth_monthly) ** m) / 12
        )
    else:
        pot = pot * (1 + monthly_rate)

    if age >= fonte_access_age:
        net = pot * (1 - fonte_tax_rate)
        return FonteState(pot=0.0, added=True), net, net

    return FonteState(pot=pot, added=False), 0.0, 0.0
