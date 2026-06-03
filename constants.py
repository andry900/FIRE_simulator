"""Costanti globali e utility di base per il FIRE Simulator."""

from datetime import date
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "fire.db")
BIRTH_DATE = date(1994, 8, 26)
DETERMINISTIC_SWR = 0.025
CAPITAL_GAINS_TAX = 0.26  # Tassazione italiana su plusvalenze (esclusi titoli di stato)

CATEGORY_COLORS: dict[str, str] = {
    "Azionario ETF":          "#4CAF50",
    "Azionario Stocks":       "#2196F3",
    "Crypto":                 "#FF9800",
    "Obbligazionario":        "#9C27B0",
    "Oro":                    "#FFD700",
    "Collezionismo":          "#A1887F",
    "Fondo Emergenza":        "#00BCD4",
    "Liquidità Investimenti": "#29B6F6",
    "Liquidità Spese":        "#80DEEA",
    "Liquidità Bloccata":     "#78909C",
    "Immobiliare":            "#8D6E63",
}


def current_age() -> float:
    """Età attuale in anni con decimali (mesi/12)."""
    today = date.today()
    d = BIRTH_DATE
    years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    months = (today.month - d.month) % 12
    return years + months / 12
