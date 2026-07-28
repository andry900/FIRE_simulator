"""Costanti globali e utility di base per il FIRE Simulator."""

from datetime import date
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "fire.db")
BIRTH_DATE = date(1990, 1, 1)
DETERMINISTIC_SWR = 0.025

# ── Tassazione italiana sui prelievi dal portafoglio ──────────────────────────
# Plusvalenze su strumenti finanziari "ordinari" (ETF azionari, azioni, ecc.)
CAPITAL_GAINS_TAX = 0.26
# Plusvalenze su titoli di Stato italiani / white list / sovranazionali
CAPITAL_GAINS_TAX_STATE_BONDS = 0.125

# ── Costi ricorrenti del portafoglio ──────────────────────────────────────────
# Imposta di bollo titoli (D.L. 201/2011): 0,2% annuo sul valore del dossier.
DEFAULT_STAMP_DUTY_RATE = 0.002
# TER medio ETF + costi broker / spread: stima conservativa.
DEFAULT_PORTFOLIO_TER = 0.003

# ── Addizionali IRPEF (default tipici, modificabili da UI) ────────────────────
# Aliquota addizionale regionale media (range nazionale 1,23%–3,33%).
DEFAULT_REGIONAL_SURTAX = 0.0173
# Aliquota addizionale comunale tipica (range 0%–0,9%).
DEFAULT_MUNICIPAL_SURTAX = 0.008

# ── Tassazione del fondo pensione complementare ──────────────────────────────
# Imposta sostitutiva sui rendimenti maturati DENTRO al fondo pensione.
# 20% standard; 12,5% sulla quota investita in titoli di Stato/white list.
FONTE_INTERNAL_TAX_BONDS = 0.125
FONTE_INTERNAL_TAX_EQUITY = 0.20

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

# Categorie del portafoglio considerate "obbligazionarie sovrane / titoli di
# Stato": le plusvalenze su queste sono tassate al 12,5% invece che al 26%.
# Per default consideriamo l'intera categoria "Obbligazionario" come 50% titoli
# di Stato (mix tipico portafoglio retail italiano). L'utente può raffinarla in
# futuro tramite tag, qui usiamo la mappa peso → aliquota effettiva.
CATEGORY_STATE_BOND_SHARE: dict[str, float] = {
    "Obbligazionario": 0.50,
}


def effective_capital_gains_tax(state_bond_share: float = 0.0) -> float:
    """Aliquota effettiva sui prelievi dato il peso di titoli di Stato.

    state_bond_share è la frazione del portafoglio investita in titoli di Stato
    italiani / white list (0 → tutto al 26%, 1 → tutto al 12,5%).
    """
    s = max(0.0, min(1.0, float(state_bond_share)))
    return s * CAPITAL_GAINS_TAX_STATE_BONDS + (1 - s) * CAPITAL_GAINS_TAX


def current_age() -> float:
    """Età attuale in anni con decimali (mesi/12)."""
    today = date.today()
    d = BIRTH_DATE
    years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    months = (today.month - d.month) % 12
    return years + months / 12