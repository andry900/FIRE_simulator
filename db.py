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
            monthly_salary        REAL    DEFAULT 3000,
            monthly_expenses      REAL    DEFAULT 1500,
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
            minimum_portfolio_reserve REAL DEFAULT 100000,
            planned_retirement_age REAL DEFAULT 45.0,
            annual_volatility      REAL    DEFAULT 0.14,
            crash_prob_annual      REAL    DEFAULT 0.10,
            crash_impact           REAL    DEFAULT -0.20,
            monte_carlo_runs       INTEGER DEFAULT 800,
            annual_pension_contribution      REAL    DEFAULT 3000,
            fonte_enrollment_date            TEXT    DEFAULT '2020-01-01',
            fonte_access_age                 INTEGER DEFAULT 50,
            fonte_equity_weight              REAL    DEFAULT 0.60,
            fonte_bond_weight                REAL    DEFAULT 0.40,
            inps_montante_current            REAL    DEFAULT 50000,
            inps_annual_contribution         REAL    DEFAULT 10000,
            inps_contribution_growth_rate    REAL    DEFAULT 0.025,
            inps_montante_revaluation_rate   REAL    DEFAULT 0.015,
            inps_contribution_start_date     TEXT    DEFAULT '2015-01-01',
            use_auto_inps_years              INTEGER DEFAULT 1,
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
    Dati di esempio per un nuovo utente.
    Fondo Pensione (~€23 500) splittato: 60% equity → Azionario ETF,
    40% bond → Obbligazionario.
    is_investable=0 per asset bloccati/illiquidi o riservati a emergenza.
    """
    assets = [
        # ── Azionario ETF ────────────────────────────────────────────────────
        ("iShares Core MSCI World",  "BIT:SWDA",   500,  60_000.00, "Azionario ETF", "Developed Markets", "Broker A",       1, None),
        ("Invesco NASDAQ-100",       "BIT:XNAS",   250,  15_000.00, "Azionario ETF", "Nasdaq",            "Broker A",       1, None),
        ("iShares MSCI EM IMI",      "BIT:EIMI",   350,  17_000.00, "Azionario ETF", "Emerging Markets",  "Broker A",       1, None),
        ("iShares MSCI Small Cap",   "BIT:SMEA",   125,  12_500.00, "Azionario ETF", "Small Cap",         "Broker A",       1, None),
        ("Fondo Pensione — Quota Azionaria", None, None, 14_000.00, "Azionario ETF", "Pensione",          "Fondo Pensione", 0, "60% equity del fondo pensione"),
        # ── Azionario Stocks ─────────────────────────────────────────────────
        ("Azione Esempio",  "BIT:EXMPL",  40.00, 6_000.00, "Azionario Stocks", "Large Cap", "Broker B", 1, None),
        ("NVIDIA",          "BIT:1NVDA",   0.00,     0.00, "Azionario Stocks", "Tech",      "Broker A", 1, None),
        ("Meta",            "BIT:1FB",     0.00,     0.00, "Azionario Stocks", "Tech",      "Broker A", 1, None),
        # ── Crypto ───────────────────────────────────────────────────────────
        ("Bitcoin ETP", "ETF:WBITG", 100.0, 1_500.00, "Crypto", "Bitcoin", "Broker A", 1, None),
        # ── Obbligazionario ──────────────────────────────────────────────────
        ("Fondo Pensione — Quota Obbligazionaria", None, None, 8_500.00, "Obbligazionario", "Pensione", "Fondo Pensione", 0, "40% bond del fondo pensione"),
        # ── Oro ──────────────────────────────────────────────────────────────
        ("Xtrackers Physical Gold", "BIT:GBSE", 0.0, 0.00, "Oro", "ETC", "Broker A", 1, None),
        # ── Fondo Emergenza ──────────────────────────────────────────────────
        ("Conto Deposito", None, None, 15_000.00, "Fondo Emergenza", "Conto Deposito", "Banca A", 0, "Fondo emergenza"),
        # ── Liquidità Investimenti ───────────────────────────────────────────
        ("Broker A — Cash", None, None, 5_000.00, "Liquidità Investimenti", "Conto Trading", "Broker A", 1, None),
        # ── Liquidità Spese ──────────────────────────────────────────────────
        ("Conto Corrente", None, None, 5_000.00, "Liquidità Spese", "Conto Corrente", "Banca A",     1, None),
        ("Cash",           None, None,   500.00, "Liquidità Spese", "Contante",       "Portafoglio", 1, None),
        # ── Liquidità Bloccata ───────────────────────────────────────────────
        ("Caparra Affitto", None, None, 900.00, "Liquidità Bloccata", "Deposito Cauzionale", "Privato", 0, "Cauzione affitto bloccata"),
        # ── Immobiliare ──────────────────────────────────────────────────────
        ("Cash Eredità",       None, None, 100_000.00, "Immobiliare", "Cash",         "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Principale",    None,  1.0, 250_000.00, "Immobiliare", "Abitazione",   "Eredità", 0, "Valore attuale stimato"),
        ("Seconda Casa (50%)", None,  0.5,  75_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €150.000"),
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
        ("minimum_portfolio_reserve",   "REAL DEFAULT 100000"),
        ("planned_retirement_age",       "REAL DEFAULT 45"),
        ("annual_volatility",            "REAL DEFAULT 0.14"),
        ("crash_prob_annual",            "REAL DEFAULT 0.10"),
        ("crash_impact",                 "REAL DEFAULT -0.20"),
        ("monte_carlo_runs",             "INTEGER DEFAULT 800"),
        ("annual_pension_contribution",  "REAL DEFAULT 3000"),
        ("fonte_enrollment_date",        "TEXT DEFAULT '2020-01-01'"),
        ("fonte_access_age",             "INTEGER DEFAULT 50"),
        ("fonte_equity_weight",          "REAL DEFAULT 0.60"),
        ("fonte_bond_weight",            "REAL DEFAULT 0.40"),
        ("inps_montante_current",        "REAL DEFAULT 50000"),
        ("inps_annual_contribution",     "REAL DEFAULT 10000"),
        ("inps_contribution_growth_rate","REAL DEFAULT 0.025"),
        ("inps_montante_revaluation_rate","REAL DEFAULT 0.015"),
        ("inps_contribution_start_date", "TEXT DEFAULT '2015-01-01'"),
        ("use_auto_inps_years",          "INTEGER DEFAULT 1"),
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

    conn.execute(
        "UPDATE simulation_params SET minimum_portfolio_reserve = 100000 WHERE minimum_portfolio_reserve IS NULL"
    )
    # Enforce minimum buffer of 10k (no one should arrive at 0)
    conn.execute(
        "UPDATE simulation_params SET minimum_portfolio_reserve = 10000 WHERE minimum_portfolio_reserve < 10000"
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
        ("Cash Eredità",       None, None, 100_000.00, "Immobiliare", "Cash",         "Eredità", 0, "Cash eredità stimata, valore reale di oggi"),
        ("Casa Principale",    None,  1.0, 250_000.00, "Immobiliare", "Abitazione",   "Eredità", 0, "Valore attuale stimato"),
        ("Seconda Casa (50%)", None,  0.5,  75_000.00, "Immobiliare", "Seconda Casa", "Eredità", 0, "50% di immobile da €150.000"),
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
                   minimum_portfolio_reserve=:minimum_portfolio_reserve,
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
                   inps_contribution_start_date=:inps_contribution_start_date,
                   use_auto_inps_years=:use_auto_inps_years,
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
