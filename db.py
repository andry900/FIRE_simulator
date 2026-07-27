"""
Livello dati: inizializzazione DB, migrazioni schema, seed, CRUD e query.
"""

import sqlite3
import pandas as pd
from constants import DB_PATH


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
            planned_retirement_age REAL DEFAULT 44.17,
            annual_volatility      REAL    DEFAULT 0.14,
            crash_prob_annual      REAL    DEFAULT 0.10,
            crash_impact           REAL    DEFAULT -0.20,
            monte_carlo_runs       INTEGER DEFAULT 800,
            annual_pension_contribution      REAL    DEFAULT 8211,
            fonte_enrollment_date            TEXT    DEFAULT '2021-04-01',
            fonte_access_age                 INTEGER DEFAULT 50,
            fonte_equity_weight              REAL    DEFAULT 0.60,
            fonte_bond_weight                REAL    DEFAULT 0.40,
            inps_montante_current            REAL    DEFAULT 102456.35,
            inps_annual_contribution         REAL    DEFAULT 18023,
            inps_contribution_growth_rate    REAL    DEFAULT 0.025,
            inps_montante_revaluation_rate   REAL    DEFAULT 0.015,
            inps_years_contributed_current   REAL    DEFAULT 10.0,
            inps_fill_missing_years          INTEGER DEFAULT 0,
            inps_pension_coefficient         REAL    DEFAULT 0.065,
            inps_irpef_rate                  REAL    DEFAULT 0.20,
            inps_gross_factor                REAL    DEFAULT 1.0,
            inps_coefficient_haircut         REAL    DEFAULT 0.0,
            initial_gain_pct                 REAL    DEFAULT 0.30,
            fonte_contributions_paid         REAL    DEFAULT 0.0,
            state_bond_share                 REAL    DEFAULT 0.0,
            portfolio_ter                    REAL    DEFAULT 0.003,
            stamp_duty_rate                  REAL    DEFAULT 0.002,
            regional_surtax                  REAL    DEFAULT 0.0173,
            municipal_surtax                 REAL    DEFAULT 0.008
        );

        CREATE TABLE IF NOT EXISTS category_return_assumptions (
            category      TEXT PRIMARY KEY,
            nominal_return REAL NOT NULL
        );

        INSERT OR IGNORE INTO simulation_params (id) VALUES (1);
    """)

    cur = conn.execute("SELECT COUNT(*) FROM assets")
    if cur.fetchone()[0] == 0:
        _seed_assets(conn)

    _ensure_schema_updates(conn)
    _drop_legacy_fonte_return_columns(conn)
    _ensure_real_estate_assets(conn)
    _ensure_category_return_assumptions(conn)

    conn.commit()
    conn.close()


def _seed_assets(conn: sqlite3.Connection) -> None:
    """
    Dati iniziali dal file NetWorth.csv.
    Pensione Fon.te (€23 500,04) splittata: 62,7% equity → Azionario ETF,
    37,3% bond → Obbligazionario.
    is_investable=0 per asset bloccati/illiquidi o riservati a emergenza.
    """
    assets = [
        # ── Azionario ETF ────────────────────────────────────────────────────
        ("iShares Core MSCI World",  "BIT:SWDA",    501,   61_818.39, "Azionario ETF", "Developed Markets", "Directa",      1, None),
        ("Invesco NASDAQ-100",       "BIT:XNAS",    254,   15_257.78, "Azionario ETF", "Nasdaq",            "Directa",      1, None),
        ("iShares MSCI EM IMI",      "BIT:EIMI",    357,   17_175.27, "Azionario ETF", "Emerging Markets",  "Directa",      1, None),
        ("iShares MSCI Small Cap",   "BIT:SMEA",    127,   12_920.98, "Azionario ETF", "Small Cap",         "Directa",      1, None),
        ("VanEck Defense",           "BIT:DFNS",      0,        0.00, "Azionario ETF", "Thematic",          "Directa",      1, None),
        ("Fon.te — Quota Azionaria", None,         None,   14_739.58, "Azionario ETF", "Pensione",          "Fon.te",       0, "60% equity del fondo pensione"),
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
        ("Fon.te — Quota Obbligazionaria", None, None, 8_760.46, "Obbligazionario", "Pensione", "Fon.te", 0, "40% bond del fondo pensione"),
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
        ("BBVA",    None, None,    477.34, "Liquidità Spese", "Conto Corrente", "BBVA",        1, None),
        ("ING",     None, None, 20_436.68, "Liquidità Spese", "Conto Corrente", "ING",         1, None),
        ("Cash",    None, None,    787.64, "Liquidità Spese", "Contante",       "Portafoglio", 1, None),
        ("Revolut", None, None,      0.00, "Liquidità Spese", "Conto Corrente", "Revolut",     1, None),
        # ── Liquidità Bloccata ───────────────────────────────────────────────
        ("Caparra Affitto", None, None, 900.00, "Liquidità Bloccata", "Deposito Cauzionale", "Privato", 0, "Cauzione affitto bloccata"),
        # ── Immobiliare ──────────────────────────────────────────────────────
        ("Cash Eredità",       None, None, 250_000.00, "Immobiliare", "Cash",         "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Roma",          None,  1.0, 300_000.00, "Immobiliare", "Abitazione",   "Eredità", 0, "Valore attuale stimato"),
        ("Casa al Mare (50%)", None,  0.5, 100_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €200.000"),
    ]
    conn.executemany(
        """INSERT INTO assets
           (name, ticker, quantity, current_value, category, subcategory, broker, is_investable, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        assets,
    )


def _ensure_schema_updates(conn: sqlite3.Connection) -> None:
    """Aggiunge colonne mancanti e migra valori default obsoleti."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(simulation_params)").fetchall()}
    extra_columns = [
        ("salary_growth_rate",           "REAL DEFAULT 0.03"),
        ("rent_monthly_now",             "REAL DEFAULT 450"),
        ("rent_real_growth",             "REAL DEFAULT 0.01"),
        ("owner_monthly_cost",           "REAL DEFAULT 250"),
        ("owner_cost_real_growth",       "REAL DEFAULT 0.0"),
        ("inheritance_age",              "INTEGER DEFAULT 60"),
        ("inheritance_cash_amount",      "REAL DEFAULT 250000"),
        ("real_estate_appreciation",     "REAL DEFAULT 0.015"),
        ("post_fire_expense_multiplier", "REAL DEFAULT 1.5"),
        ("planned_retirement_age",       "REAL DEFAULT 44"),
        ("annual_volatility",            "REAL DEFAULT 0.14"),
        ("crash_prob_annual",            "REAL DEFAULT 0.10"),
        ("crash_impact",                 "REAL DEFAULT -0.20"),
        ("monte_carlo_runs",             "INTEGER DEFAULT 800"),
        ("annual_pension_contribution",  "REAL DEFAULT 8211"),
        ("fonte_enrollment_date",        "TEXT DEFAULT '2005-01-01'"),
        ("fonte_access_age",             "INTEGER DEFAULT 50"),
        ("fonte_equity_weight",          "REAL DEFAULT 0.60"),
        ("fonte_bond_weight",            "REAL DEFAULT 0.40"),
        ("inps_montante_current",        "REAL DEFAULT 102456.35"),
        ("inps_annual_contribution",     "REAL DEFAULT 18023"),
        ("inps_contribution_growth_rate","REAL DEFAULT 0.025"),
        ("inps_montante_revaluation_rate","REAL DEFAULT 0.015"),
        ("inps_years_contributed_current","REAL DEFAULT 10.0"),
        ("inps_fill_missing_years",      "INTEGER DEFAULT 0"),
        ("inps_pension_coefficient",     "REAL DEFAULT 0.065"),
        ("inps_irpef_rate",              "REAL DEFAULT 0.20"),
        ("inps_gross_factor",            "REAL DEFAULT 1.0"),
        ("initial_gain_pct",             "REAL DEFAULT 0.30"),
        ("inps_coefficient_haircut",     "REAL DEFAULT 0.0"),
        ("fonte_contributions_paid",     "REAL DEFAULT 0.0"),
        ("state_bond_share",             "REAL DEFAULT 0.0"),
        ("portfolio_ter",                "REAL DEFAULT 0.003"),
        ("stamp_duty_rate",              "REAL DEFAULT 0.002"),
        ("regional_surtax",              "REAL DEFAULT 0.0173"),
        ("municipal_surtax",             "REAL DEFAULT 0.008"),
    ]
    for col_name, col_def in extra_columns:
        if col_name not in cols:
            conn.execute(f"ALTER TABLE simulation_params ADD COLUMN {col_name} {col_def}")

    # Migrazione legacy: pension_access_age 67 → 73
    conn.execute(
        "UPDATE simulation_params SET pension_access_age = 73 WHERE id = 1 AND pension_access_age = 67"
    )
    # Migrazione default pensionamento: 45 → 44 → 44.17
    conn.execute(
        "UPDATE simulation_params SET planned_retirement_age = 44 WHERE id = 1 AND planned_retirement_age = 45"
    )
    conn.execute(
        "UPDATE simulation_params SET planned_retirement_age = 44.17 WHERE id = 1 AND planned_retirement_age = 44"
    )


def _drop_legacy_fonte_return_columns(conn: sqlite3.Connection) -> None:
    """Rimuove colonne legacy non più usate, se SQLite supporta DROP COLUMN.

    Colonne droppate:
    - fonte_equity_return / fonte_bond_return: sostituite dai valori in
      category_return_assumptions (Azionario ETF / Obbligazionario).
    - inheritance_cash_amount: ora calcolato dagli asset categoria
      "Immobiliare", subcategory "Cash" (vedi views/fire_tab.py).
    - inps_pension_coefficient: sostituito dalla tabella deterministica
      INPS_TRANSFORMATION_COEFFICIENTS (pension_inps.py).
    - inps_irpef_rate: sostituito da IRPEF a scaglioni + addizionali
      (pension_inps.py::annual_net_pension_from_gross).
    """
    legacy_columns = (
        "fonte_equity_return",
        "fonte_bond_return",
        "inheritance_cash_amount",
        "inps_pension_coefficient",
        "inps_irpef_rate",
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(simulation_params)").fetchall()}
    for col_name in legacy_columns:
        if col_name in cols:
            try:
                conn.execute(f"ALTER TABLE simulation_params DROP COLUMN {col_name}")
            except sqlite3.OperationalError:
                # SQLite < 3.35 non supporta DROP COLUMN: la colonna sopravvive
                # ma non viene letta dal codice. Logghiamo per visibilità.
                import warnings
                warnings.warn(
                    f"Impossibile droppare la colonna legacy '{col_name}' "
                    "(SQLite troppo vecchio per ALTER TABLE DROP COLUMN). "
                    "La colonna resta nello schema ma è ignorata dal codice.",
                    stacklevel=2,
                )


def _ensure_real_estate_assets(conn: sqlite3.Connection) -> None:
    """Aggiunge gli asset immobiliari se non presenti (migrazione non distruttiva)."""
    real_estate_assets = [
        ("Cash Eredità",       None, None, 250_000.00, "Immobiliare", "Cash",         "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Roma",          None,  1.0, 300_000.00, "Immobiliare", "Abitazione",   "Eredità", 0, "Valore attuale stimato"),
        ("Casa al Mare (50%)", None,  0.5, 100_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €200.000"),
    ]
    for asset in real_estate_assets:
        name = asset[0]
        if conn.execute("SELECT 1 FROM assets WHERE name = ? LIMIT 1", (name,)).fetchone() is None:
            conn.execute(
                """INSERT INTO assets
                   (name, ticker, quantity, current_value, category, subcategory, broker, is_investable, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                asset,
            )


def _ensure_category_return_assumptions(conn: sqlite3.Connection) -> None:
    """Seed non distruttivo dei rendimenti nominali annui stimati per categoria."""
    defaults = [
        ("Liquidità Spese", 0.015),
        ("Fondo Emergenza", 0.03),
        ("Liquidità Investimenti", 0.0),
        ("Liquidità Bloccata", 0.0),
        ("Azionario ETF", 0.075),
        ("Azionario Stocks", 0.10),
        ("Obbligazionario", 0.035),
        ("Crypto", 0.20),
        ("Oro", 0.03),
        ("Collezionismo", 0.10),
        ("Immobiliare", 0.04),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO category_return_assumptions (category, nominal_return) VALUES (?,?)",
        defaults,
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


def load_category_return_map() -> dict[str, float]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT category, nominal_return FROM category_return_assumptions"
        ).fetchall()
    return {str(category): float(nominal_return) for category, nominal_return in rows}


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
                   planned_retirement_age=:planned_retirement_age,
                   annual_volatility=:annual_volatility,
                   crash_prob_annual=:crash_prob_annual,
                   crash_impact=:crash_impact,
                   monte_carlo_runs=:monte_carlo_runs,
                   annual_pension_contribution=:annual_pension_contribution,
                   fonte_enrollment_date=:fonte_enrollment_date,
                   fonte_access_age=:fonte_access_age,
                   fonte_equity_weight=:fonte_equity_weight,
                   fonte_bond_weight=:fonte_bond_weight,
                   inps_montante_current=:inps_montante_current,
                   inps_annual_contribution=:inps_annual_contribution,
                   inps_contribution_growth_rate=:inps_contribution_growth_rate,
                   inps_montante_revaluation_rate=:inps_montante_revaluation_rate,
                   inps_years_contributed_current=:inps_years_contributed_current,
                   inps_fill_missing_years=:inps_fill_missing_years,
                   inps_gross_factor=:inps_gross_factor,
                   inps_coefficient_haircut=:inps_coefficient_haircut,
                   initial_gain_pct=:initial_gain_pct,
                   fonte_contributions_paid=:fonte_contributions_paid,
                   state_bond_share=:state_bond_share,
                   portfolio_ter=:portfolio_ter,
                   stamp_duty_rate=:stamp_duty_rate,
                   regional_surtax=:regional_surtax,
                   municipal_surtax=:municipal_surtax
               WHERE id=1""",
            params,
        )


def update_asset(asset_id: int, new_value: float, new_quantity: float) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE assets SET current_value=?, quantity=?, updated_at=datetime('now') WHERE id=?",
            (new_value, new_quantity, asset_id),
        )


def add_asset(
    name: str,
    ticker: str | None,
    quantity: float,
    value: float,
    category: str,
    subcategory: str | None,
    broker: str | None,
    is_investable: int,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO assets
               (name, ticker, quantity, current_value, category, subcategory, broker, is_investable)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, ticker, quantity, value, category, subcategory, broker, is_investable),
        )
