"""
FIRE Simulator — Simulazione FIRE personale
Tutti i valori sono in euro reali (potere d'acquisto di oggi).
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import date
import os

# ── Costanti ─────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "fire.db")
BIRTH_DATE = date(1994, 8, 26)
DETERMINISTIC_SWR = 0.025
POST_FIRE_CAPITAL_GAINS_TAX = 0.26

CATEGORY_COLORS = {
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

# ── Database ──────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            ticker        TEXT,
            quantity      REAL,
            current_value REAL    NOT NULL DEFAULT 0,
            category      TEXT    NOT NULL,
            subcategory   TEXT,
            broker        TEXT,
            is_investable INTEGER DEFAULT 1,
            notes         TEXT,
            updated_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS simulation_params (
            id                    INTEGER PRIMARY KEY DEFAULT 1,
            monthly_salary        REAL    DEFAULT 3300,
            monthly_expenses      REAL    DEFAULT 1550,
            salary_growth_rate    REAL    DEFAULT 0.03,
            nominal_annual_return REAL    DEFAULT 0.07,
            inflation_rate        REAL    DEFAULT 0.025,
            swr                   REAL    DEFAULT 0.04,
            pension_access_age    INTEGER DEFAULT 73,
            rent_monthly_now      REAL    DEFAULT 450,
            rent_real_growth      REAL    DEFAULT 0.01,
            owner_monthly_cost    REAL    DEFAULT 250,
            owner_cost_real_growth REAL   DEFAULT 0.0,
            inheritance_age       INTEGER DEFAULT 60,
            inheritance_cash_amount REAL DEFAULT 250000,
            real_estate_appreciation REAL DEFAULT 0.015,
            post_fire_expense_multiplier REAL DEFAULT 1.5,
            post_fire_expense_growth REAL DEFAULT 0.025,
            planned_retirement_age REAL DEFAULT 44,
            annual_volatility      REAL    DEFAULT 0.14,
            crash_prob_annual      REAL    DEFAULT 0.10,
            crash_impact           REAL    DEFAULT -0.20,
            monte_carlo_runs       INTEGER DEFAULT 800
        );

        INSERT OR IGNORE INTO simulation_params (id) VALUES (1);
    """)

    cur = conn.execute("SELECT COUNT(*) FROM assets")
    if cur.fetchone()[0] == 0:
        _seed_assets(conn)

    _ensure_schema_updates(conn)
    _ensure_real_estate_assets(conn)

    conn.commit()
    conn.close()


def _seed_assets(conn: sqlite3.Connection) -> None:
    """
    Dati iniziali dal file NetWorth.csv.
    Pensione Fon.te (€23 500,04) splittata: 62,7% equity → Azionario ETF,
    37,3% bond → Obbligazionario (per far tornare i totali dell'allocazione).
    is_investable=0 per asset bloccati/illiquidi o riservati a emergenza.
    """
    assets = [
        # ── Azionario ETF ────────────────────────────────────────────────────
        ("iShares Core MSCI World",  "BIT:SWDA",    501,   61_818.39, "Azionario ETF", "Developed Markets", "Directa",      1, None),
        ("Invesco NASDAQ-100",       "BIT:XNAS",    254,   15_257.78, "Azionario ETF", "Nasdaq",            "Directa",      1, None),
        ("iShares MSCI EM IMI",      "BIT:EIMI",    357,   17_175.27, "Azionario ETF", "Emerging Markets",  "Directa",      1, None),
        ("iShares MSCI Small Cap",   "BIT:SMEA",    127,   12_920.98, "Azionario ETF", "Small Cap",         "Directa",      1, None),
        ("VanEck Defense",           "BIT:DFNS",      0,        0.00, "Azionario ETF", "Thematic",          "Directa",      1, None),
        # Fon.te — quota azionaria (≈62.7% di 23 500,04 = 14 739,58)
        ("Fon.te — Quota Azionaria", None,         None,   14_739.58, "Azionario ETF", "Pensione",          "Fon.te",       0, "60% equity del fondo pensione, accessibile a 67 anni"),

        # ── Azionario Stocks ─────────────────────────────────────────────────
        ("SAP SE",    "ETR:SAP",    40.00,  6_008.80, "Azionario Stocks", "SAP",  "Fineco",      1, None),
        ("SAP SE",    "ETR:SAP",    14.57,  2_188.09, "Azionario Stocks", "SAP",  "Equate Plus", 1, "Piano azionario dipendente"),
        ("SAP SE",    "ETR:SAP",     1.00,    150.22, "Azionario Stocks", "SAP",  "Directa",     1, None),
        ("Duolingo",  "NASDAQ:DUOL", 9.00,    823.35, "Azionario Stocks", "Tech", "Directa",     1, None),
        ("NVIDIA",    "BIT:1NVDA",   0.00,      0.00, "Azionario Stocks", "Tech", "Directa",     1, None),
        ("Ferrari",   "BIT:RACE",    0.00,      0.00, "Azionario Stocks", "Auto", "Directa",     1, None),
        ("Meta",      "BIT:1FB",     0.00,      0.00, "Azionario Stocks", "Tech", "Directa",     1, None),
        ("Netflix",   "BIT:1NFLX",   0.00,      0.00, "Azionario Stocks", "Tech", "Directa",     1, None),

        # ── Crypto ───────────────────────────────────────────────────────────
        ("Bitcoin ETP", "ETF:WBITG", 120.0, 1_867.20, "Crypto", "Bitcoin", "Directa", 1, None),

        # ── Obbligazionario ──────────────────────────────────────────────────
        # Fon.te — quota obbligazionaria (≈37.3% di 23 500,04 = 8 760,46)
        ("Fon.te — Quota Obbligazionaria", None, None, 8_760.46, "Obbligazionario", "Pensione", "Fon.te", 0, "40% bond del fondo pensione, accessibile a 67 anni"),

        # ── Oro ──────────────────────────────────────────────────────────────
        ("Gold Physical",          "GOLD",     74.0, 6_875.94, "Oro", "Fisico",  "Just Sentimental", 1, "Oro fisico"),
        ("Xtrackers Physical Gold", "BIT:GBSE",  0.0,     0.00, "Oro", "ETC",     "Directa",          1, None),

        # ── Collezionismo ────────────────────────────────────────────────────
        ("Pokemon Cards", None, 23.0, 5_228.73, "Collezionismo", "Cards",   "Privato", 0, "Valore di mercato stimato"),
        ("Funko Pop",     None, 77.0, 2_630.32, "Collezionismo", "Funko",   "Privato", 0, None),
        ("Orologi",       None,  2.0,   884.00, "Collezionismo", "Orologi", "Privato", 0, None),

        # ── Fondo Emergenza ──────────────────────────────────────────────────
        ("CA Auto Bank", None, None, 25_000.00, "Fondo Emergenza", "Conto Deposito", "CA Auto Bank", 0, "Fondo emergenza / conto deposito"),

        # ── Liquidità Investimenti ───────────────────────────────────────────
        ("Directa — Cash", None, None, 14_202.01, "Liquidità Investimenti", "Conto Trading", "Directa", 1, None),
        ("Fineco — Cash",  None, None,  5_261.87, "Liquidità Investimenti", "Conto Trading", "Fineco",  1, None),

        # ── Liquidità Spese ──────────────────────────────────────────────────
        ("BBVA",    None, None,    477.34, "Liquidità Spese", "Conto Corrente", "BBVA",       1, None),
        ("ING",     None, None, 20_436.68, "Liquidità Spese", "Conto Corrente", "ING",        1, None),
        ("Cash",    None, None,    787.64, "Liquidità Spese", "Contante",       "Portafoglio",1, None),
        ("Revolut", None, None,      0.00, "Liquidità Spese", "Conto Corrente", "Revolut",    1, None),

        # ── Liquidità Bloccata ───────────────────────────────────────────────
        ("Caparra Affitto", None, None, 900.00, "Liquidità Bloccata", "Deposito Cauzionale", "Privato", 0, "Cauzione affitto bloccata"),

        # ── Immobiliare (eredità stimata in euro di oggi) ───────────────────
        ("Cash Eredità",         None, None, 250_000.00, "Immobiliare", "Cash",         "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Roma",        None, 1.0, 300_000.00, "Immobiliare", "Abitazione", "Eredità", 0, "Valore attuale stimato"),
        ("Casa al Mare (50%)", None, 0.5, 100_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €200.000"),
    ]

    conn.executemany(
        """INSERT INTO assets
           (name, ticker, quantity, current_value, category, subcategory, broker, is_investable, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        assets,
    )


def _ensure_schema_updates(conn: sqlite3.Connection) -> None:
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(simulation_params)").fetchall()
    }
    extra_columns = [
        ("salary_growth_rate", "REAL DEFAULT 0.03"),
        ("rent_monthly_now", "REAL DEFAULT 450"),
        ("rent_real_growth", "REAL DEFAULT 0.01"),
        ("owner_monthly_cost", "REAL DEFAULT 250"),
        ("owner_cost_real_growth", "REAL DEFAULT 0.0"),
        ("inheritance_age", "INTEGER DEFAULT 60"),
        ("inheritance_cash_amount", "REAL DEFAULT 250000"),
        ("real_estate_appreciation", "REAL DEFAULT 0.015"),
        ("post_fire_expense_multiplier", "REAL DEFAULT 1.5"),
        ("post_fire_expense_growth", "REAL DEFAULT 0.025"),
        ("planned_retirement_age", "REAL DEFAULT 44"),
        ("annual_volatility", "REAL DEFAULT 0.14"),
        ("crash_prob_annual", "REAL DEFAULT 0.10"),
        ("crash_impact", "REAL DEFAULT -0.20"),
        ("monte_carlo_runs", "INTEGER DEFAULT 800"),
    ]
    for col_name, col_def in extra_columns:
        if col_name not in cols:
            conn.execute(f"ALTER TABLE simulation_params ADD COLUMN {col_name} {col_def}")

    # Migrazione legacy: se ancora al vecchio default 67, passa a 73.
    conn.execute(
        "UPDATE simulation_params SET pension_access_age = 73 WHERE id = 1 AND pension_access_age = 67"
    )

    # Migrazione default pensionamento: da 45 a 44 anni.
    conn.execute(
        "UPDATE simulation_params SET planned_retirement_age = 44 WHERE id = 1 AND planned_retirement_age = 45"
    )


def _ensure_real_estate_assets(conn: sqlite3.Connection) -> None:
    """Aggiunge gli asset immobiliari se non presenti (migrazione non distruttiva)."""
    real_estate_assets = [
        ("Cash Eredità", None, None, 250_000.00, "Immobiliare", "Cash", "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Roma", None, 1.0, 300_000.00, "Immobiliare", "Abitazione", "Eredità", 0, "Valore attuale stimato"),
        ("Casa al Mare (50%)", None, 0.5, 100_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €200.000"),
    ]
    for asset in real_estate_assets:
        name = asset[0]
        cur = conn.execute("SELECT 1 FROM assets WHERE name = ? LIMIT 1", (name,))
        if cur.fetchone() is None:
            conn.execute(
                """INSERT INTO assets
                   (name, ticker, quantity, current_value, category, subcategory, broker, is_investable, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                asset,
            )


# ── Query helpers ─────────────────────────────────────────────────────────────

def load_assets() -> pd.DataFrame:
    with _get_conn() as conn:
        return pd.read_sql("SELECT * FROM assets ORDER BY category, name", conn)


def load_params() -> dict:
    with _get_conn() as conn:
        cur = conn.execute("SELECT * FROM simulation_params WHERE id=1")
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def save_params(params: dict) -> None:
    with _get_conn() as conn:
        conn.execute(
            """UPDATE simulation_params
               SET monthly_salary=:monthly_salary,
                   monthly_expenses=:monthly_expenses,
                   salary_growth_rate=:salary_growth_rate,
                   nominal_annual_return=:nominal_annual_return,
                   inflation_rate=:inflation_rate,
                   pension_access_age=:pension_access_age,
                   rent_monthly_now=:rent_monthly_now,
                   rent_real_growth=:rent_real_growth,
                   owner_monthly_cost=:owner_monthly_cost,
                   owner_cost_real_growth=:owner_cost_real_growth,
                   inheritance_age=:inheritance_age,
                   real_estate_appreciation=:real_estate_appreciation,
                   post_fire_expense_multiplier=:post_fire_expense_multiplier,
                   post_fire_expense_growth=:post_fire_expense_growth,
                   planned_retirement_age=:planned_retirement_age,
                   annual_volatility=:annual_volatility,
                   crash_prob_annual=:crash_prob_annual,
                   crash_impact=:crash_impact,
                   monte_carlo_runs=:monte_carlo_runs
               WHERE id=1""",
            params,
        )


def update_asset(asset_id: int, new_value: float, new_quantity: float) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE assets SET current_value=?, quantity=?, updated_at=datetime('now') WHERE id=?",
            (new_value, new_quantity, asset_id),
        )


def infer_asset_nominal_return(row: pd.Series) -> float:
    """Ritorna un rendimento nominale annuo stimato per singolo asset."""
    category = str(row.get("category") or "").strip()
    subcategory = str(row.get("subcategory") or "").strip().lower()

    if category == "Liquidità Spese":
        return 0.015
    if category == "Fondo Emergenza" or "deposito" in subcategory:
        return 0.03
    if category == "Liquidità Investimenti":
        return 0.0
    if category == "Liquidità Bloccata":
        return 0.0
    if category == "Azionario ETF":
        return 0.075
    if category == "Azionario Stocks":
        return 0.10
    if category == "Obbligazionario":
        return 0.035
    if category == "Crypto":
        return 0.20
    if category == "Oro":
        return 0.03
    if category == "Collezionismo":
        return 0.10
    return 0.04


def estimate_portfolio_nominal_return(df_assets: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    """
    Stima rendimento nominale pesato sul patrimonio attuale (esclusa eredità immobiliare).
    Restituisce (rendimento_annuo, breakdown_per_categoria).
    """
    df = df_assets.copy()
    df = df[(df["category"] != "Immobiliare") & (df["current_value"] > 0)]
    if df.empty:
        return 0.05, pd.DataFrame(columns=["Categoria", "Valore", "Peso", "Rendimento Stimato"])

    df["assumed_return"] = df.apply(infer_asset_nominal_return, axis=1)
    total_value = df["current_value"].sum()
    df["weight"] = df["current_value"] / total_value

    estimated = float((df["weight"] * df["assumed_return"]).sum())

    by_cat = (
        df.groupby("category")
        .apply(
            lambda g: pd.Series(
                {
                    "Valore": g["current_value"].sum(),
                    "Peso": g["current_value"].sum() / total_value,
                    "Rendimento Stimato": (
                        (g["current_value"] * g["assumed_return"]).sum() / g["current_value"].sum()
                    ),
                }
            )
        )
        .reset_index()
        .rename(columns={"category": "Categoria"})
        .sort_values("Valore", ascending=False)
    )

    return estimated, by_cat


def gross_withdrawal_for_net_expense(net_expense: float, tax_rate: float) -> float:
    """Importo lordo da prelevare per coprire una spesa netta, includendo tassazione."""
    if net_expense <= 0:
        return 0.0
    if tax_rate >= 1:
        return net_expense
    return net_expense / (1 - tax_rate)


# ── FIRE math ─────────────────────────────────────────────────────────────────

def current_age() -> float:
    today = date.today()
    d = BIRTH_DATE
    years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    months = (today.month - d.month) % 12
    return years + months / 12


def simulate(
    portfolio_start: float,
    monthly_salary: float,
    monthly_non_housing_expenses: float,
    salary_growth_rate: float,
    post_fire_expense_multiplier: float,
    post_fire_expense_growth: float,
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
) -> tuple[pd.DataFrame, float | None, bool]:
    """
    Proietta il patrimonio in euro reali (inflazione rimossa).
    Dopo il FIRE lo stipendio viene azzerato e restano solo le spese.
    Restituisce (DataFrame mensile, età FIRE o None, successo_a_fine_periodo).
    """
    real_annual = (1 + nominal_return) / (1 + inflation) - 1
    real_monthly = (1 + real_annual) ** (1 / 12) - 1
    salary_growth_monthly = (1 + salary_growth_rate) ** (1 / 12) - 1
    post_fire_expense_growth_monthly = (1 + post_fire_expense_growth) ** (1 / 12) - 1
    rent_growth_monthly = (1 + rent_real_growth) ** (1 / 12) - 1
    owner_growth_monthly = (1 + owner_cost_real_growth) ** (1 / 12) - 1
    real_estate_growth_monthly = (1 + real_estate_appreciation) ** (1 / 12) - 1

    months = int((end_age - start_age) * 12)
    ages, values, fire_nums = [], [], []
    portfolio = portfolio_start
    fire_age = None
    pension_added = False
    inheritance_event_done = False
    success = True

    for m in range(months + 1):
        age = start_age + m / 12

        # Aggiungi pensione all'età di accesso (una volta sola)
        if not pension_added and age >= pension_access_age:
            portfolio += pension_value
            pension_added = True

        if not inheritance_event_done and age >= inheritance_age:
            months_to_inheritance = int(round((inheritance_age - start_age) * 12))
            months_to_inheritance = max(months_to_inheritance, 0)
            full_house_value = full_house_value_today * ((1 + real_estate_growth_monthly) ** months_to_inheritance)

            # Cash eredità entra in entrambi gli scenari all'età di eredità.
            portfolio += inheritance_cash_amount

            # Solo nello scenario affitto a vita la casa al 100% viene venduta e investita.
            if housing_mode == "rent_life_with_sale":
                portfolio += full_house_value
            inheritance_event_done = True

        if housing_mode == "owner_after_inheritance" and age >= inheritance_age:
            months_to_inheritance = int(round((inheritance_age - start_age) * 12))
            months_since_inheritance = max(m - max(months_to_inheritance, 0), 0)
            housing_monthly = owner_monthly_cost * ((1 + owner_growth_monthly) ** months_since_inheritance)
        else:
            housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)

        monthly_expenses_t = monthly_non_housing_expenses + housing_monthly
        annual_expenses_t = monthly_expenses_t * 12
        fire_number_t = (annual_expenses_t * post_fire_expense_multiplier) / threshold_swr

        ages.append(round(age, 4))
        values.append(round(portfolio, 2))
        fire_nums.append(round(fire_number_t, 2))

        if fire_age is None and portfolio >= fire_number_t:
            fire_age = age

        retired = age >= planned_retirement_age
        months_to_retirement = int(round((planned_retirement_age - start_age) * 12))
        months_since_retirement = max(m - max(months_to_retirement, 0), 0)
        salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)

        if retired:
            monthly_expenses_post_fire = (
                monthly_expenses_t
                * post_fire_expense_multiplier
                * ((1 + post_fire_expense_growth_monthly) ** months_since_retirement)
            )
            gross_withdrawal = gross_withdrawal_for_net_expense(
                monthly_expenses_post_fire,
                POST_FIRE_CAPITAL_GAINS_TAX,
            )
            cashflow_t = -gross_withdrawal
        else:
            cashflow_t = salary_t - monthly_expenses_t

        portfolio = portfolio * (1 + real_monthly) + cashflow_t
        if retired and portfolio <= 0:
            portfolio = 0
            success = False
            # Continua a generare la serie per il grafico, ma senza valori negativi.

    return (
        pd.DataFrame({"age": ages, "portfolio": values, "fire_number": fire_nums}),
        fire_age,
        success,
    )


def monte_carlo_success_probability(
    n_sims: int,
    annual_volatility: float,
    crash_prob_annual: float,
    crash_impact: float,
    **simulate_kwargs,
) -> tuple[float, float, float | None]:
    """
    Monte Carlo in euro reali:
    - pre-FIRE: accumulo (stipendio - spese)
    - post-FIRE: solo spese (stipendio azzerato)
    Restituisce:
    - probabilità di raggiungere FIRE entro il periodo
    - probabilità di non esaurire il capitale a fine periodo
    - età FIRE mediana (se raggiunta in almeno una simulazione)
    """
    nominal_return = float(simulate_kwargs["nominal_return"])
    inflation = float(simulate_kwargs["inflation"])
    start_age = float(simulate_kwargs["start_age"])
    end_age = int(simulate_kwargs["end_age"])

    real_annual = (1 + nominal_return) / (1 + inflation) - 1
    real_monthly_mean = (1 + real_annual) ** (1 / 12) - 1
    monthly_std = annual_volatility / np.sqrt(12)
    monthly_crash_prob = crash_prob_annual / 12

    months = int((end_age - start_age) * 12)
    fire_ages = []
    reached_fire_count = 0
    success_count = 0

    for _ in range(n_sims):
        kwargs = dict(simulate_kwargs)
        portfolio = float(kwargs["portfolio_start"])
        monthly_salary = float(kwargs["monthly_salary"])
        monthly_non_housing_expenses = float(kwargs["monthly_non_housing_expenses"])
        salary_growth_rate = float(kwargs["salary_growth_rate"])
        post_fire_expense_multiplier = float(kwargs["post_fire_expense_multiplier"])
        post_fire_expense_growth = float(kwargs["post_fire_expense_growth"])
        rent_monthly_now = float(kwargs["rent_monthly_now"])
        rent_real_growth = float(kwargs["rent_real_growth"])
        owner_monthly_cost = float(kwargs["owner_monthly_cost"])
        owner_cost_real_growth = float(kwargs["owner_cost_real_growth"])
        threshold_swr = float(kwargs["threshold_swr"])
        pension_value = float(kwargs["pension_value"])
        pension_access_age = int(kwargs["pension_access_age"])
        housing_mode = str(kwargs["housing_mode"])
        planned_retirement_age = float(kwargs["planned_retirement_age"])
        inheritance_age = int(kwargs["inheritance_age"])
        inheritance_cash_amount = float(kwargs["inheritance_cash_amount"])
        full_house_value_today = float(kwargs["full_house_value_today"])
        real_estate_appreciation = float(kwargs["real_estate_appreciation"])

        salary_growth_monthly = (1 + salary_growth_rate) ** (1 / 12) - 1
        post_fire_expense_growth_monthly = (1 + post_fire_expense_growth) ** (1 / 12) - 1
        rent_growth_monthly = (1 + rent_real_growth) ** (1 / 12) - 1
        owner_growth_monthly = (1 + owner_cost_real_growth) ** (1 / 12) - 1
        real_estate_growth_monthly = (1 + real_estate_appreciation) ** (1 / 12) - 1

        pension_added = False
        inheritance_event_done = False
        fire_age = None
        success = True

        for m in range(months + 1):
            age = start_age + m / 12

            if not pension_added and age >= pension_access_age:
                portfolio += pension_value
                pension_added = True

            if not inheritance_event_done and age >= inheritance_age:
                months_to_inheritance = int(round((inheritance_age - start_age) * 12))
                months_to_inheritance = max(months_to_inheritance, 0)
                full_house_value = full_house_value_today * ((1 + real_estate_growth_monthly) ** months_to_inheritance)
                portfolio += inheritance_cash_amount
                if housing_mode == "rent_life_with_sale":
                    portfolio += full_house_value
                inheritance_event_done = True

            if housing_mode == "owner_after_inheritance" and age >= inheritance_age:
                months_to_inheritance = int(round((inheritance_age - start_age) * 12))
                months_since_inheritance = max(m - max(months_to_inheritance, 0), 0)
                housing_monthly = owner_monthly_cost * ((1 + owner_growth_monthly) ** months_since_inheritance)
            else:
                housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)

            monthly_expenses_t = monthly_non_housing_expenses + housing_monthly
            fire_number_t = (monthly_expenses_t * 12 * post_fire_expense_multiplier) / threshold_swr

            if fire_age is None and portfolio >= fire_number_t:
                fire_age = age

            retired = age >= planned_retirement_age
            months_to_retirement = int(round((planned_retirement_age - start_age) * 12))
            months_since_retirement = max(m - max(months_to_retirement, 0), 0)
            salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)

            if retired:
                monthly_expenses_post_fire = (
                    monthly_expenses_t
                    * post_fire_expense_multiplier
                    * ((1 + post_fire_expense_growth_monthly) ** months_since_retirement)
                )
                gross_withdrawal = gross_withdrawal_for_net_expense(
                    monthly_expenses_post_fire,
                    POST_FIRE_CAPITAL_GAINS_TAX,
                )
                cashflow_t = -gross_withdrawal
            else:
                cashflow_t = salary_t - monthly_expenses_t

            random_r = np.random.normal(real_monthly_mean, monthly_std)
            if np.random.random() < monthly_crash_prob:
                random_r += crash_impact

            portfolio = portfolio * (1 + random_r) + cashflow_t

            if retired and portfolio <= 0:
                success = False
                break

        if fire_age is not None and fire_age <= planned_retirement_age:
            reached_fire_count += 1
            fire_ages.append(fire_age)
        if success:
            success_count += 1

    p_reach_fire = reached_fire_count / n_sims if n_sims > 0 else 0.0
    p_success = success_count / n_sims if n_sims > 0 else 0.0
    fire_age_median = float(np.median(fire_ages)) if fire_ages else None
    return p_reach_fire, p_success, fire_age_median


def monte_carlo_survival_given_initial(
    initial_portfolio: float,
    n_sims: int,
    annual_volatility: float,
    crash_prob_annual: float,
    crash_impact: float,
    **simulate_kwargs,
) -> float:
    """Probabilità di non esaurire il capitale fino a end_age con pensionamento all'età pianificata."""
    kwargs = dict(simulate_kwargs)
    kwargs["portfolio_start"] = initial_portfolio

    nominal_return = float(kwargs["nominal_return"])
    inflation = float(kwargs["inflation"])
    start_age = float(kwargs["start_age"])
    end_age = int(kwargs["end_age"])

    real_annual = (1 + nominal_return) / (1 + inflation) - 1
    real_monthly_mean = (1 + real_annual) ** (1 / 12) - 1
    monthly_std = annual_volatility / np.sqrt(12)
    monthly_crash_prob = crash_prob_annual / 12
    months = int((end_age - start_age) * 12)

    success_count = 0

    for _ in range(n_sims):
        portfolio = float(kwargs["portfolio_start"])
        monthly_salary = float(kwargs["monthly_salary"])
        monthly_non_housing_expenses = float(kwargs["monthly_non_housing_expenses"])
        salary_growth_rate = float(kwargs["salary_growth_rate"])
        post_fire_expense_multiplier = float(kwargs["post_fire_expense_multiplier"])
        post_fire_expense_growth = float(kwargs["post_fire_expense_growth"])
        rent_monthly_now = float(kwargs["rent_monthly_now"])
        rent_real_growth = float(kwargs["rent_real_growth"])
        owner_monthly_cost = float(kwargs["owner_monthly_cost"])
        owner_cost_real_growth = float(kwargs["owner_cost_real_growth"])
        pension_value = float(kwargs["pension_value"])
        pension_access_age = int(kwargs["pension_access_age"])
        housing_mode = str(kwargs["housing_mode"])
        planned_retirement_age = float(kwargs["planned_retirement_age"])
        inheritance_age = int(kwargs["inheritance_age"])
        inheritance_cash_amount = float(kwargs["inheritance_cash_amount"])
        full_house_value_today = float(kwargs["full_house_value_today"])
        real_estate_appreciation = float(kwargs["real_estate_appreciation"])

        salary_growth_monthly = (1 + salary_growth_rate) ** (1 / 12) - 1
        post_fire_expense_growth_monthly = (1 + post_fire_expense_growth) ** (1 / 12) - 1
        rent_growth_monthly = (1 + rent_real_growth) ** (1 / 12) - 1
        owner_growth_monthly = (1 + owner_cost_real_growth) ** (1 / 12) - 1
        real_estate_growth_monthly = (1 + real_estate_appreciation) ** (1 / 12) - 1

        pension_added = False
        inheritance_event_done = False
        success = True

        for m in range(months + 1):
            age = start_age + m / 12

            if not pension_added and age >= pension_access_age:
                portfolio += pension_value
                pension_added = True

            if not inheritance_event_done and age >= inheritance_age:
                months_to_inheritance = int(round((inheritance_age - start_age) * 12))
                months_to_inheritance = max(months_to_inheritance, 0)
                full_house_value = full_house_value_today * ((1 + real_estate_growth_monthly) ** months_to_inheritance)
                portfolio += inheritance_cash_amount
                if housing_mode == "rent_life_with_sale":
                    portfolio += full_house_value
                inheritance_event_done = True

            if housing_mode == "owner_after_inheritance" and age >= inheritance_age:
                months_to_inheritance = int(round((inheritance_age - start_age) * 12))
                months_since_inheritance = max(m - max(months_to_inheritance, 0), 0)
                housing_monthly = owner_monthly_cost * ((1 + owner_growth_monthly) ** months_since_inheritance)
            else:
                housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)

            monthly_expenses_t = monthly_non_housing_expenses + housing_monthly
            random_r = np.random.normal(real_monthly_mean, monthly_std)
            if np.random.random() < monthly_crash_prob:
                random_r += crash_impact

            retired = age >= planned_retirement_age
            months_to_retirement = int(round((planned_retirement_age - start_age) * 12))
            months_since_retirement = max(m - max(months_to_retirement, 0), 0)
            salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)

            if retired:
                monthly_expenses_post_fire = (
                    monthly_expenses_t
                    * post_fire_expense_multiplier
                    * ((1 + post_fire_expense_growth_monthly) ** months_since_retirement)
                )
                gross_withdrawal = gross_withdrawal_for_net_expense(
                    monthly_expenses_post_fire,
                    POST_FIRE_CAPITAL_GAINS_TAX,
                )
                cashflow_t = -gross_withdrawal
            else:
                cashflow_t = salary_t - monthly_expenses_t

            portfolio = portfolio * (1 + random_r) + cashflow_t
            if retired and portfolio <= 0:
                success = False
                break

        if success:
            success_count += 1

    return success_count / n_sims if n_sims > 0 else 0.0


def required_capital_for_target_survival(
    target_survival: float,
    n_sims: int,
    annual_volatility: float,
    crash_prob_annual: float,
    crash_impact: float,
    **simulate_kwargs,
) -> tuple[float, float]:
    """Cerca il capitale iniziale minimo per avere probabilità target di sopravvivenza."""
    low = 0.0
    high = max(float(simulate_kwargs["portfolio_start"]), 100_000.0)

    # Espansione upper bound finché non raggiunge target.
    for _ in range(12):
        p = monte_carlo_survival_given_initial(
            initial_portfolio=high,
            n_sims=n_sims,
            annual_volatility=annual_volatility,
            crash_prob_annual=crash_prob_annual,
            crash_impact=crash_impact,
            **simulate_kwargs,
        )
        if p >= target_survival:
            break
        high *= 1.5

    # Ricerca binaria.
    for _ in range(16):
        mid = (low + high) / 2
        p = monte_carlo_survival_given_initial(
            initial_portfolio=mid,
            n_sims=n_sims,
            annual_volatility=annual_volatility,
            crash_prob_annual=crash_prob_annual,
            crash_impact=crash_impact,
            **simulate_kwargs,
        )
        if p >= target_survival:
            high = mid
        else:
            low = mid

    final_prob = monte_carlo_survival_given_initial(
        initial_portfolio=high,
        n_sims=n_sims,
        annual_volatility=annual_volatility,
        crash_prob_annual=crash_prob_annual,
        crash_impact=crash_impact,
        **simulate_kwargs,
    )
    return high, final_prob


# ── App ───────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🔥 FIRE Simulator",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 700; }
.block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# Inizializza DB una sola volta per sessione
if "db_ready" not in st.session_state:
    init_db()
    st.session_state["db_ready"] = True

# ── Sidebar — parametri ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Parametri")

    p = load_params()
    assets_for_estimation = load_assets()
    estimated_nominal_return, returns_by_category = estimate_portfolio_nominal_return(assets_for_estimation)

    st.markdown("### 💰 Cash flow mensile")
    monthly_salary   = st.number_input("Stipendio netto (€/mese)",  value=float(p["monthly_salary"]),   step=50.0, format="%.0f")
    monthly_expenses = st.number_input("Spese totali (€/mese)",      value=float(p["monthly_expenses"]), step=50.0, format="%.0f")
    salary_growth_rate = st.slider(
        "Aumento stipendio (%/anno)",
        0.0,
        10.0,
        float(p.get("salary_growth_rate", 0.03) * 100),
        0.1,
    ) / 100
    monthly_savings  = monthly_salary - monthly_expenses
    savings_rate     = monthly_savings / monthly_salary * 100 if monthly_salary > 0 else 0
    st.markdown(f"**Risparmio:** €{monthly_savings:,.0f}/mese — savings rate **{savings_rate:.1f}%**")
    st.caption(f"Aumento stipendio impostato: {salary_growth_rate * 100:.1f}% annuo")

    st.divider()
    st.markdown("### 📈 Rendimento & inflazione")
    default_adjust = 0.0
    st.markdown(f"**Stima automatica portafoglio:** {estimated_nominal_return * 100:.2f}% nominale")
    nominal_adjustment = st.slider(
        "Aggiustamento personale della stima (%/anno)",
        -3.0,
        3.0,
        float(default_adjust),
        0.1,
    )
    nominal_return = max(0.0, estimated_nominal_return + nominal_adjustment / 100)
    st.caption(
        f"Rendimento usato in simulazione: **{nominal_return * 100:.2f}%** · "
        "Ipotesi liquidità: 1,5% conti correnti / 3% conto deposito"
    )

    with st.expander("Dettaglio stima rendimento per categoria"):
        rb = returns_by_category.copy()
        if not rb.empty:
            rb["Valore"] = rb["Valore"].map(lambda x: f"€{x:,.0f}")
            rb["Peso"] = (rb["Peso"] * 100).map(lambda x: f"{x:.1f}%")
            rb["Rendimento Stimato"] = (rb["Rendimento Stimato"] * 100).map(lambda x: f"{x:.2f}%")
            st.dataframe(rb, use_container_width=True, hide_index=True)
        else:
            st.caption("Nessun asset con valore positivo disponibile per la stima.")

    inflation      = st.slider("Inflazione (%/anno)",           1.0,  5.0, float(p["inflation_rate"] * 100),       0.25) / 100
    real_return    = (1 + nominal_return) / (1 + inflation) - 1
    st.caption(f"Rendimento reale: **{real_return * 100:.2f}%**")

    st.divider()
    st.markdown("### 🧾 Spese post-FIRE")
    post_fire_expense_multiplier = st.slider(
        "Moltiplicatore spese post-FIRE (vs pre-FIRE)",
        1.0,
        2.5,
        float(p.get("post_fire_expense_multiplier", 1.5)),
        0.05,
    )
    post_fire_expense_growth = st.slider(
        "Crescita spese post-FIRE (%/anno)",
        0.0,
        8.0,
        float(p.get("post_fire_expense_growth", float(p.get("inflation_rate", 0.025))) * 100),
        0.1,
    ) / 100
    st.caption(
        f"Dopo il pensionamento: spese x{post_fire_expense_multiplier:.2f} e crescita annua {post_fire_expense_growth * 100:.1f}%"
    )

    st.divider()
    st.markdown("### 🏖️ Simulazione")
    age_now = current_age()
    sim_end = st.slider("Età fine simulazione", min_value=50, max_value=120, value=95, step=1)
    planned_retirement_default = float(p.get("planned_retirement_age", 44))
    planned_retirement_default = min(max(planned_retirement_default, age_now), 60.0)
    planned_retirement_age = st.slider(
        "Età in cui vuoi smettere di lavorare",
        min_value=float(round(age_now, 1)),
        max_value=60.0,
        value=float(round(planned_retirement_default, 1)),
        step=0.1,
    )

    pension_access_age = st.number_input(
        "Età accesso pensione", value=int(p["pension_access_age"]), step=1, min_value=55, max_value=75
    )

    st.divider()
    st.markdown("### 🏠 Casa vs Affitto")
    rent_monthly_now = st.number_input(
        "Affitto attuale (€/mese)", value=float(p.get("rent_monthly_now", 450)), step=25.0, min_value=0.0, format="%.0f"
    )
    rent_real_growth = st.slider(
        "Aumento reale affitto (%/anno)", 0.0, 3.0, float(p.get("rent_real_growth", 0.01) * 100), 0.1
    ) / 100
    owner_monthly_cost = st.number_input(
        "Costo casa di proprietà (€/mese)", value=float(p.get("owner_monthly_cost", 250)), step=25.0, min_value=0.0, format="%.0f"
    )
    owner_cost_real_growth = st.slider(
        "Aumento reale costi proprietà (%/anno)", 0.0, 2.0, float(p.get("owner_cost_real_growth", 0.0) * 100), 0.1
    ) / 100
    inheritance_age = st.number_input(
        "Età eredità stimata", value=int(p.get("inheritance_age", 60)), step=1, min_value=35, max_value=100
    )
    real_estate_appreciation = st.slider(
        "Rivalutazione reale immobili (%/anno)",
        0.0,
        4.0,
        float(p.get("real_estate_appreciation", 0.015) * 100),
        0.1,
    ) / 100

    st.divider()
    st.markdown("### 🌪️ Rischio di mercato")
    annual_volatility = st.slider(
        "Volatilità annua portafoglio (%)",
        5.0,
        35.0,
        float(p.get("annual_volatility", 0.14) * 100),
        0.5,
    ) / 100
    crash_prob_annual = st.slider(
        "Probabilità annua di anno negativo forte (%)",
        0.0,
        30.0,
        float(p.get("crash_prob_annual", 0.10) * 100),
        1.0,
    ) / 100
    crash_impact = st.slider(
        "Impatto shock (% sul mese dello shock)",
        -40.0,
        -5.0,
        float(p.get("crash_impact", -0.20) * 100),
        1.0,
    ) / 100
    monte_carlo_runs = int(
        st.slider(
            "Numero simulazioni Monte Carlo",
            min_value=300,
            max_value=3000,
            value=int(p.get("monte_carlo_runs", 800)),
            step=100,
        )
    )

    st.divider()
    if st.button("💾 Salva parametri", use_container_width=True):
        save_params({
            "monthly_salary":        monthly_salary,
            "monthly_expenses":      monthly_expenses,
            "salary_growth_rate":    salary_growth_rate,
            "nominal_annual_return": nominal_return,
            "inflation_rate":        inflation,
            "pension_access_age":    int(pension_access_age),
            "rent_monthly_now":      rent_monthly_now,
            "rent_real_growth":      rent_real_growth,
            "owner_monthly_cost":    owner_monthly_cost,
            "owner_cost_real_growth": owner_cost_real_growth,
            "inheritance_age":       int(inheritance_age),
            "real_estate_appreciation": real_estate_appreciation,
            "post_fire_expense_multiplier": post_fire_expense_multiplier,
            "post_fire_expense_growth": post_fire_expense_growth,
            "planned_retirement_age": planned_retirement_age,
            "annual_volatility":     annual_volatility,
            "crash_prob_annual":     crash_prob_annual,
            "crash_impact":          crash_impact,
            "monte_carlo_runs":      monte_carlo_runs,
        })
        st.success("Salvato!")

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔥 FIRE Simulator")
st.caption(f"Valori in € reali (potere d'acquisto {date.today().strftime('%d/%m/%Y')}) · Età attuale: {age_now:.1f} anni")
st.divider()

tab_patrimonio, tab_fire, tab_edit = st.tabs(["📊 Patrimonio", "🔥 Simulazione FIRE", "✏️ Aggiorna Dati"])

# ══ TAB 1 — Patrimonio ════════════════════════════════════════════════════════
with tab_patrimonio:
    df = load_assets()
    df_current = df[df["category"] != "Immobiliare"].copy()
    df_inheritance = df[df["category"] == "Immobiliare"].copy()

    total_nw = df_current["current_value"].sum()
    inheritance_nw = df_inheritance["current_value"].sum()
    investable_nw = df_current[df_current["is_investable"] == 1]["current_value"].sum()
    annual_expenses_now = monthly_expenses * 12

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💎 Patrimonio attuale",      f"€{total_nw:,.0f}")
    c2.metric("🚀 Patrimonio investibile",  f"€{investable_nw:,.0f}")
    c3.metric("💸 Spese annue attuali",     f"€{annual_expenses_now:,.0f}")
    c4.metric("📈 Savings rate",            f"{savings_rate:.1f}%")
    st.caption(f"Eredità attesa (non inclusa nel patrimonio attuale): €{inheritance_nw:,.0f}")

    st.divider()

    # Allocation
    alloc = (
        df_current.groupby("category")["current_value"]
        .sum()
        .reset_index()
        .rename(columns={"category": "Categoria", "current_value": "Valore"})
        .query("Valore > 0")
        .sort_values("Valore", ascending=False)
    )
    alloc["% Totale"] = (alloc["Valore"] / total_nw * 100).round(1)

    col_pie, col_tbl = st.columns([1, 1])

    with col_pie:
        colors = [CATEGORY_COLORS.get(c, "#888888") for c in alloc["Categoria"]]
        fig_pie = go.Figure(go.Pie(
            labels=alloc["Categoria"],
            values=alloc["Valore"],
            marker_colors=colors,
            textinfo="label+percent",
            hole=0.42,
            direction="clockwise",
            sort=False,
        ))
        fig_pie.update_traces(textfont_size=12)
        fig_pie.update_layout(
            title_text="Asset Allocation",
            showlegend=False,
            margin=dict(t=40, b=10, l=10, r=10),
            height=400,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_tbl:
        st.markdown("#### Dettaglio per categoria")
        tbl = alloc.copy()
        tbl["Valore"] = tbl["Valore"].map(lambda x: f"€{x:,.0f}")
        tbl["% Totale"] = tbl["% Totale"].astype(str) + "%"
        st.dataframe(tbl, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown(f"**Totale patrimonio:** €{total_nw:,.0f}")
        st.markdown(f"**Investibile (liquido):** €{investable_nw:,.0f}")

    st.divider()
    st.markdown("#### Tutti gli asset")
    show_df = df_current[["name", "ticker", "quantity", "current_value", "category", "subcategory", "broker"]].copy()
    show_df = show_df[show_df["current_value"] > 0].sort_values("current_value", ascending=False)
    show_df["current_value"] = show_df["current_value"].map(lambda x: f"€{x:,.2f}")
    show_df.columns = ["Nome", "Ticker", "Qtà", "Valore", "Categoria", "Sottocategoria", "Broker"]
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    if inheritance_nw > 0:
        st.divider()
        st.markdown("#### Eredità attesa (fuori dal patrimonio attuale)")
        inh_df = df_inheritance[["name", "current_value", "subcategory", "broker"]].copy()
        inh_df = inh_df[inh_df["current_value"] > 0].sort_values("current_value", ascending=False)
        inh_df["current_value"] = inh_df["current_value"].map(lambda x: f"€{x:,.2f}")
        inh_df.columns = ["Nome", "Valore", "Tipo", "Fonte"]
        st.dataframe(inh_df, use_container_width=True, hide_index=True)

# ══ TAB 2 — Simulazione FIRE ══════════════════════════════════════════════════
with tab_fire:
    df = load_assets()
    df_current = df[df["category"] != "Immobiliare"].copy()
    inheritance_age = int(p.get("inheritance_age", 60))
    real_estate_appreciation = float(p.get("real_estate_appreciation", 0.015))

    # Portafoglio di partenza: investible esclusa pensione e illiquidi
    portfolio_liquid = df_current[
        (df_current["is_investable"] == 1)
    ]["current_value"].sum()

    # Solo le quote Fon.te — sblocco a pension_access_age
    pension_total = df_current[df_current["broker"] == "Fon.te"]["current_value"].sum()

    # Patrimonio immobiliare eredità (non investibile)
    inheritance_df = df[df["category"] == "Immobiliare"].copy()
    inheritance_cash_amount = inheritance_df[inheritance_df["subcategory"] == "Cash"]["current_value"].sum()
    inheritance_re_df = inheritance_df[inheritance_df["subcategory"] != "Cash"]
    full_house_value_today = inheritance_re_df[inheritance_re_df["quantity"].fillna(0) >= 1]["current_value"].sum()
    partial_house_value_today = inheritance_re_df[inheritance_re_df["quantity"].fillna(0) < 1]["current_value"].sum()
    inherited_real_estate = full_house_value_today + partial_house_value_today
    years_to_inheritance = max(inheritance_age - age_now, 0)
    full_house_at_inheritance = full_house_value_today * ((1 + real_estate_appreciation) ** years_to_inheritance)
    partial_house_at_inheritance = partial_house_value_today * ((1 + real_estate_appreciation) ** years_to_inheritance)

    monthly_non_housing_expenses = max(monthly_expenses - rent_monthly_now, 0.0)

    st.markdown(
        f"**Portafoglio investibile attuale:** €{portfolio_liquid:,.0f} "
        f"· **Pensione (a {pension_access_age:.0f} anni):** €{pension_total:,.0f} "
        f"· **Immobiliare eredità:** €{inherited_real_estate:,.0f}"
    )
    st.caption(
        f"A {inheritance_age} anni entrano €{inheritance_cash_amount:,.0f} cash in entrambi gli scenari. "
        f"In affitto a vita vendi anche la casa al 100% e investi il ricavato (stimato: €{full_house_at_inheritance:,.0f})."
    )
    st.caption(
        f"Casa al mare 50% resta non liquidata (valore stimato a {inheritance_age} anni: €{partial_house_at_inheritance:,.0f}). "
        f"Scenario proprietà: resti in affitto fino all'eredità, poi vivi in casa con costi da proprietario."
    )
    st.caption("Nota: nel grafico la curva mostra il patrimonio investibile. In 'Proprietà dopo eredità' la casa non viene venduta, quindi non appare un salto del portafoglio investibile.")
    st.caption(f"Età pensionamento impostata: {planned_retirement_age:.1f} anni.")
    st.divider()

    st.markdown("#### 🎯 Quando superi la soglia SWR (stima deterministica)")
    threshold_swr = st.slider(
        "SWR (%)",
        min_value=2.0,
        max_value=5.0,
        value=float(DETERMINISTIC_SWR * 100),
        step=0.1,
    ) / 100
    st.caption(f"La sezione deterministica usa SWR {threshold_swr * 100:.1f}%. Il pensionamento effettivo avviene all'età impostata dallo slider pensionamento.")
    st.divider()

    # ── Scenari ──────────────────────────────────────────────────────────────
    scenarios = {
        f"Affitto · Pessimista (5%)": (0.05, "#EF5350", "dash", "rent_life_with_sale", "legendonly"),
        f"Affitto · Base ({nominal_return*100:.1f}%)": (nominal_return, "#42A5F5", "solid", "rent_life_with_sale", True),
        f"Affitto · Ottimista (9%)": (0.09, "#66BB6A", "dot", "rent_life_with_sale", "legendonly"),
        f"Proprietà dopo eredità · Base ({nominal_return*100:.1f}%)": (nominal_return, "#8D6E63", "solid", "owner_after_inheritance", True),
    }

    fig = go.Figure()

    fire_ages: dict[str, float | None] = {}
    deterministic_success: dict[str, bool] = {}
    scenario_inputs: dict[str, dict] = {}

    for label, (ret, color, dash, housing_mode, default_visible) in scenarios.items():
        sim_kwargs = {
            "portfolio_start": portfolio_liquid,
            "monthly_salary": monthly_salary,
            "monthly_non_housing_expenses": monthly_non_housing_expenses,
            "salary_growth_rate": salary_growth_rate,
            "post_fire_expense_multiplier": post_fire_expense_multiplier,
            "post_fire_expense_growth": post_fire_expense_growth,
            "rent_monthly_now": rent_monthly_now,
            "rent_real_growth": rent_real_growth,
            "owner_monthly_cost": owner_monthly_cost,
            "owner_cost_real_growth": owner_cost_real_growth,
            "nominal_return": ret,
            "inflation": inflation,
            "threshold_swr": threshold_swr,
            "pension_value": pension_total,
            "pension_access_age": int(pension_access_age),
            "planned_retirement_age": planned_retirement_age,
            "housing_mode": housing_mode,
            "inheritance_age": inheritance_age,
            "inheritance_cash_amount": inheritance_cash_amount,
            "full_house_value_today": full_house_value_today,
            "real_estate_appreciation": real_estate_appreciation,
            "start_age": age_now,
            "end_age": sim_end,
        }
        df_sim, f_age, ok_end = simulate(**sim_kwargs)
        fire_ages[label] = f_age
        deterministic_success[label] = ok_end
        scenario_inputs[label] = sim_kwargs

        fig.add_trace(go.Scatter(
            x=df_sim["age"],
            y=df_sim["portfolio"],
            name=label,
            mode="lines",
            line=dict(color=color, dash=dash, width=2.5),
            visible=default_visible,
            hovertemplate="Età %{x:.1f} → €%{y:,.0f}<extra>" + label + "</extra>",
        ))

    # Linea pensione
    fig.add_vline(
        x=pension_access_age,
        line_dash="dot",
        line_color="#CE93D8",
        line_width=1.5,
        annotation_text=f" Pensione {pension_access_age:.0f}a",
        annotation_position="top right",
        annotation_font=dict(color="#CE93D8", size=11),
    )

    fig.add_vline(
        x=inheritance_age,
        line_dash="dot",
        line_color="#8D6E63",
        line_width=1.5,
        annotation_text=f" Eredità {inheritance_age:.0f}a",
        annotation_position="top left",
        annotation_font=dict(color="#8D6E63", size=11),
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

    # ── Metriche FIRE ────────────────────────────────────────────────────────
    st.markdown("##### Risultati soglia SWR")
    cols = st.columns(len(scenarios))
    for i, (label, _) in enumerate(scenarios.items()):
        fa = fire_ages[label]
        if fa is not None:
            birth_year = BIRTH_DATE.year
            fire_year  = birth_year + int(fa)
            years_left = fa - age_now
            deterministic_status = "nel percorso medio il capitale resta > 0 a fine periodo" if deterministic_success.get(label, False) else "nel percorso medio il capitale si esaurisce"
            cols[i].metric(label, f"Età {fa:.1f} ({fire_year})", f"tra {years_left:.1f} anni")
            cols[i].caption(deterministic_status)
        else:
            cols[i].metric(label, "Non raggiunto", f"nel range (max {sim_end}a)")

    st.divider()

    st.markdown("#### 🎲 Stress test Monte Carlo (mercato variabile)")
    st.caption("Qui c'è la metrica robusta: probabilità di sostenibilità fino a età target con mercati variabili e shock.")
    base_rent_label = f"Affitto · Base ({nominal_return*100:.1f}%)"
    base_owner_label = f"Proprietà dopo eredità · Base ({nominal_return*100:.1f}%)"
    target_survival = 0.95

    mc1, mc2 = st.columns(2)
    for col, label in [(mc1, base_rent_label), (mc2, base_owner_label)]:
        if label in scenario_inputs:
            p_fire, p_survival, fire_med = monte_carlo_success_probability(
                n_sims=monte_carlo_runs,
                annual_volatility=annual_volatility,
                crash_prob_annual=crash_prob_annual,
                crash_impact=crash_impact,
                **scenario_inputs[label],
            )

            target_capital, target_prob = required_capital_for_target_survival(
                target_survival=target_survival,
                n_sims=max(300, monte_carlo_runs // 2),
                annual_volatility=annual_volatility,
                crash_prob_annual=crash_prob_annual,
                crash_impact=crash_impact,
                **scenario_inputs[label],
            )
            if fire_med is not None:
                fire_year = BIRTH_DATE.year + int(fire_med)
                fire_txt = f"Età mediana FIRE {fire_med:.1f} ({fire_year})"
            else:
                fire_txt = "FIRE non raggiunta nella maggior parte delle simulazioni"

            gap_to_target = max(target_capital - portfolio_liquid, 0)
            col.metric(f"{label} · Capitale target oggi (95% fino a {sim_end}a)", f"€{target_capital:,.0f}")
            col.metric(f"{label} · Gap vs patrimonio investibile oggi", f"€{gap_to_target:,.0f}")
            col.metric(f"{label} · Prob. raggiungere SWR entro età pensionamento", f"{p_fire * 100:.1f}%")
            col.metric(f"{label} · Prob. sostenibilità con età pensionamento impostata", f"{p_survival * 100:.1f}%")
            col.caption(f"Il capitale target è calibrato per circa {target_prob * 100:.1f}% di probabilità di arrivare a {sim_end} anni.")
            col.caption(f"{fire_txt} · Soglia SWR, non garanzia di riuscita.")
        else:
            col.caption(f"Scenario {label} non disponibile")

    st.caption(
        "Interpretazione: il Target FIRE Monte Carlo è il capitale iniziale minimo oggi per avere circa 95% "
        "di probabilità di non esaurire il capitale fino all'età target, considerando stipendio fino all'età pensionamento impostata e poi solo spese."
    )
    st.caption("Nei prelievi post-FIRE è applicata una tassazione del 26% in modo prudenziale (gross-up del prelievo necessario).")

    st.divider()

    # ── Breakdown risparmio ──────────────────────────────────────────────────
    ca, cb, cc, cd = st.columns(4)
    ca.metric("📊 Savings rate",        f"{savings_rate:.1f}%")
    cb.metric("💸 Risparmio mensile",   f"€{monthly_savings:,.0f}")
    cc.metric("📅 Risparmio annuale",   f"€{monthly_savings * 12:,.0f}")
    cd.metric("🧮 Simulazioni MC",      f"{monte_carlo_runs}")

# ══ TAB 3 — Aggiorna Dati ════════════════════════════════════════════════════
with tab_edit:
    st.markdown("#### ✏️ Aggiorna valori degli asset")
    st.caption("Aggiorna i prezzi/valori correnti del tuo patrimonio.")

    df_edit = load_assets()

    def _asset_expanders(subset: pd.DataFrame) -> None:
        for _, row in subset.iterrows():
            label = f"**{row['name']}**"
            ticker = str(row["ticker"]).strip() if pd.notna(row["ticker"]) else ""
            if ticker and ticker.lower() != "nan":
                label += f" `{ticker}`"
            label += f" — {row['category']}"
            broker = str(row["broker"]).strip() if pd.notna(row["broker"]) else ""
            if broker and broker.lower() != "nan":
                label += f" — {broker}"
            subcategory = str(row["subcategory"]).strip() if pd.notna(row["subcategory"]) else ""
            if subcategory and subcategory.lower() != "nan":
                label += f" · {subcategory}"
            label += f" — €{row['current_value']:,.2f}"

            with st.expander(label):
                col1, col2, col3 = st.columns([3, 2, 1])
                new_val = col1.number_input(
                    "Valore (€)", value=float(row["current_value"]),
                    key=f"v_{row['id']}", format="%.2f", min_value=0.0, step=10.0,
                )
                qty_val = float(row["quantity"]) if row["quantity"] is not None else 0.0
                new_qty = col2.number_input(
                    "Quantità", value=qty_val,
                    key=f"q_{row['id']}", format="%.4f", min_value=0.0,
                )
                if col3.button("💾 Salva", key=f"s_{row['id']}"):
                    update_asset(int(row["id"]), new_val, new_qty)
                    st.success("Aggiornato!")
                    st.cache_data.clear()
                    st.rerun()

    current_assets = (
        df_edit[df_edit["category"] != "Immobiliare"]
        .query("current_value > 0")
        .sort_values("current_value", ascending=False)
    )
    future_assets = (
        df_edit[df_edit["category"] == "Immobiliare"]
        .query("current_value > 0")
        .sort_values("current_value", ascending=False)
    )

    st.markdown("##### Asset attuali")
    _asset_expanders(current_assets)

    st.divider()
    st.markdown("##### Asset futuri (eredità)")
    _asset_expanders(future_assets)

    st.divider()
    st.markdown("#### ➕ Aggiungi nuovo asset")
    with st.form("add_asset"):
        fc1, fc2 = st.columns(2)
        a_name   = fc1.text_input("Nome")
        a_ticker = fc2.text_input("Ticker (opzionale)")
        fc3, fc4, fc5 = st.columns(3)
        a_value  = fc3.number_input("Valore (€)", min_value=0.0, format="%.2f")
        a_qty    = fc4.number_input("Quantità",   min_value=0.0, format="%.4f")
        a_cat    = fc5.selectbox("Categoria", sorted(CATEGORY_COLORS.keys()))
        fc6, fc7, fc8 = st.columns(3)
        a_sub    = fc6.text_input("Sottocategoria")
        a_broker = fc7.text_input("Broker / custode")
        a_invest = fc8.selectbox("Investibile?", ["Sì", "No"])

        submitted = st.form_submit_button("➕ Aggiungi")
        if submitted and a_name:
            with _get_conn() as conn:
                conn.execute(
                    """INSERT INTO assets (name, ticker, quantity, current_value, category, subcategory, broker, is_investable)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (a_name, a_ticker or None, a_qty, a_value, a_cat, a_sub or None, a_broker or None, 1 if a_invest == "Sì" else 0),
                )
            st.success(f"Asset «{a_name}» aggiunto!")
            st.rerun()
