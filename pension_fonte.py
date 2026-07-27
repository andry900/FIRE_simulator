"""
Logica del fondo pensione complementare Fon.te.

Modello fiscale (D.Lgs. 252/2005):

1) DURANTE LA FASE DI ACCUMULO i rendimenti maturati DENTRO al fondo sono
   tassati al 20% (12,5% per la quota in titoli di Stato/white list) in
   sostitutiva. Per modellarlo, applichiamo direttamente il rendimento NETTO
   (post imposta sostitutiva) al pot del fondo. Il pot rappresenta quindi un
   valore "già tassato" sui rendimenti.

2) IN USCITA (al raggiungimento dell'età di sblocco) si applica un'aliquota
   agevolata SOLO sui contributi dedotti versati al fondo:
     - dal 1° al 15° anno di iscrizione: 15%
     - dal 16° al 34° anno: 15% - 0,30% per ogni anno oltre il 15°
     - dal 35° anno in poi: 9% (limite minimo)
   I rendimenti già tassati al 20%/12,5% durante l'accumulo NON sono
   ulteriormente tassati. Ai fini del calcolo separiamo il pot in:
     - quota_contributi (capitale versato cumulato): tassata 9-15%
     - quota_rendimenti (pot - quota_contributi): non tassata in uscita

NB: il modello assume che TUTTI i contributi siano stati dedotti (entro il
tetto annuo di 5.164,57 €). Se l'utente versa più del tetto, l'eccedenza
sarebbe esente in uscita: semplificazione conservativa (tendiamo a tassare un
po' più del dovuto su quella quota residuale).
"""

from dataclasses import dataclass
from datetime import datetime

from constants import FONTE_INTERNAL_TAX_BONDS, FONTE_INTERNAL_TAX_EQUITY

DEFAULT_FONTE_EQUITY_RETURN: float = 0.075
DEFAULT_FONTE_BOND_RETURN: float = 0.035
DEFAULT_FONTE_EQUITY_WEIGHT: float = 0.60
DEFAULT_FONTE_BOND_WEIGHT: float = 0.40


def fonte_tax_rate_by_enrollment(enrollment_date: str, unlock_age: float, current_age: float) -> float:
    """Aliquota Fon.te in uscita in base agli anni di iscrizione (interi).

    Regole D.Lgs. 252/2005:
    - Dal 1° al 15° anno: 15%
    - Dal 16° anno in poi: riduzione dello 0,30% per ogni anno aggiuntivo
    - Dal 35° anno in poi: limite minimo 9%

    Calcolo anni: somma frazionaria tra (oggi - data_iscrizione) e (unlock_age
    - current_age), poi un solo `int()` sul totale per evitare il bug del
    doppio troncamento.
    """
    try:
        enrollment_dt = datetime.strptime(enrollment_date, "%Y-%m-%d")
        current_dt = datetime.now()
        years_passed = (current_dt - enrollment_dt).days / 365.25
        years_future = max(unlock_age - current_age, 0)
        total_years = years_passed + years_future
        years_of_enrollment = int(total_years)
    except (ValueError, TypeError):
        years_of_enrollment = 0

    if years_of_enrollment <= 15:
        return 0.15
    if years_of_enrollment >= 35:
        return 0.09
    years_beyond_15 = years_of_enrollment - 15
    return max(0.15 - (years_beyond_15 * 0.003), 0.09)


@dataclass
class FonteState:
    pot: float                 # montante netto da rendimenti già tassati (€ reali)
    contributions_paid: float  # capitale lordo versato cumulato (per tassazione uscita)
    added: bool = False        # True dopo lo sblocco e il versamento nel portafoglio


def fonte_nominal_annual(
    fonte_equity_return: float,
    fonte_bond_return: float,
    fonte_equity_weight: float,
    fonte_bond_weight: float,
) -> float:
    """Rendimento nominale annuo LORDO del fondo Fon.te con pesi normalizzati."""
    total_weight = fonte_equity_weight + fonte_bond_weight
    if total_weight <= 0:
        return (
            DEFAULT_FONTE_EQUITY_WEIGHT * DEFAULT_FONTE_EQUITY_RETURN
            + DEFAULT_FONTE_BOND_WEIGHT * DEFAULT_FONTE_BOND_RETURN
        )

    ew = fonte_equity_weight / total_weight
    bw = fonte_bond_weight / total_weight
    return ew * fonte_equity_return + bw * fonte_bond_return


def fonte_internal_tax_rate(
    fonte_equity_weight: float,
    fonte_bond_weight: float,
) -> float:
    """Aliquota sostitutiva sui rendimenti del fondo (pesata per asset class).

    20% sulla quota azionaria, 12,5% sulla quota obbligazionaria (assunta
    interamente in titoli di Stato/white list).
    """
    total = fonte_equity_weight + fonte_bond_weight
    if total <= 0:
        return FONTE_INTERNAL_TAX_EQUITY * DEFAULT_FONTE_EQUITY_WEIGHT + FONTE_INTERNAL_TAX_BONDS * DEFAULT_FONTE_BOND_WEIGHT
    ew = fonte_equity_weight / total
    bw = fonte_bond_weight / total
    return ew * FONTE_INTERNAL_TAX_EQUITY + bw * FONTE_INTERNAL_TAX_BONDS


def fonte_real_monthly(
    inflation: float,
    fonte_equity_return: float = DEFAULT_FONTE_EQUITY_RETURN,
    fonte_bond_return: float = DEFAULT_FONTE_BOND_RETURN,
    fonte_equity_weight: float = DEFAULT_FONTE_EQUITY_WEIGHT,
    fonte_bond_weight: float = DEFAULT_FONTE_BOND_WEIGHT,
) -> float:
    """Tasso reale mensile NETTO del fondo Fon.te.

    Applica l'imposta sostitutiva sui rendimenti (20% / 12,5%) prima di
    detrarre l'inflazione. In questo modo il pot del fondo è già al netto
    dell'imposta sui rendimenti maturati.
    """
    fonte_nominal_gross = fonte_nominal_annual(
        fonte_equity_return,
        fonte_bond_return,
        fonte_equity_weight,
        fonte_bond_weight,
    )
    internal_tax = fonte_internal_tax_rate(fonte_equity_weight, fonte_bond_weight)
    fonte_nominal_net = fonte_nominal_gross * (1 - internal_tax)
    real_annual = (1 + fonte_nominal_net) / (1 + inflation) - 1
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
    """Avanza lo stato Fon.te di un mese.

    monthly_rate è il tasso reale NETTO (post imposta sostitutiva 20%/12,5%).

    I versamenti annui cessano all'età FIRE (planned_retirement_age), non
    all'età di accesso pensione pubblica.

    In uscita applica l'aliquota agevolata SOLO sui contributi (dedotti). I
    rendimenti, già tassati al 20%/12,5% durante l'accumulo, NON sono
    ulteriormente tassati.

    Restituisce (nuovo_stato, delta_portafoglio, delta_cost_basis).
    Il delta è positivo solo nell'anno di sblocco (versamento nel portafoglio).
    """
    if state.added:
        return state, 0.0, 0.0

    pot = state.pot
    contributions_paid = state.contributions_paid

    if age < planned_retirement_age:
        monthly_contrib = annual_pension_contribution * ((1 + salary_growth_monthly) ** m) / 12
        pot = pot * (1 + monthly_rate) + monthly_contrib
        contributions_paid += monthly_contrib
    else:
        pot = pot * (1 + monthly_rate)

    if age >= fonte_access_age:
        # In uscita: tassa solo i contributi dedotti, i rendimenti sono già
        # netti. Se per qualche motivo contributions_paid > pot (improbabile
        # con rendimenti positivi), tassa solo il pot.
        taxable_contributions = min(contributions_paid, pot)
        non_taxable_gains = max(pot - taxable_contributions, 0.0)
        net = taxable_contributions * (1 - fonte_tax_rate) + non_taxable_gains
        return (
            FonteState(pot=0.0, contributions_paid=0.0, added=True),
            net,
            net,
        )

    return FonteState(pot=pot, contributions_paid=contributions_paid, added=False), 0.0, 0.0