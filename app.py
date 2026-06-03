"""
FIRE Simulator — entry point principale.

La logica è distribuita in moduli separati:
  constants.py        — costanti e current_age()
  db.py               — database, CRUD, query
  portfolio.py        — stima rendimenti portafoglio
  pension_fonte.py    — logica fondo Fon.te
  pension_inps.py     — logica INPS contributivo
  simulation.py       — simulate() e find_fire_age()
  monte_carlo.py      — simulazioni Monte Carlo
  views/sidebar.py    — sidebar parametri
  views/patrimonio.py — tab Patrimonio
  views/fire_tab.py   — tab Simulazione FIRE
  views/edit_tab.py   — tab Aggiorna Dati
"""

import streamlit as st
from datetime import date

from db import init_db, load_assets
from views import sidebar as sidebar_view
from views import patrimonio as patrimonio_view
from views import fire_tab as fire_tab_view
from views import edit_tab as edit_tab_view

# ── Page config ───────────────────────────────────────────────────────────────
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

# ── DB init (una sola volta per sessione) ─────────────────────────────────────
if "db_ready" not in st.session_state:
    init_db()
    st.session_state["db_ready"] = True

# ── Sidebar ───────────────────────────────────────────────────────────────────
cfg = sidebar_view.render()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔥 FIRE Simulator")
st.caption(
    f"Valori in € reali (potere d'acquisto {date.today().strftime('%d/%m/%Y')}) "
    f"· Età attuale: {cfg['age_now']:.1f} anni"
)
st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_patrimonio, tab_fire, tab_edit = st.tabs(
    ["📊 Patrimonio", "🔥 Simulazione FIRE", "✏️ Aggiorna Dati"]
)

with tab_patrimonio:
    df = load_assets()
    patrimonio_view.render(df, cfg["monthly_expenses"], cfg["monthly_salary"], cfg["savings_rate"])

with tab_fire:
    df = load_assets()
    fire_tab_view.render(df, cfg)

with tab_edit:
    edit_tab_view.render()
