# Review tecnica FIRE Simulator (Italia) — stato attuale

Questa è una review aggiornata del codice **dopo** le correzioni già implementate
rispetto alla prima review storica (bollo, TER, addizionali, doppia tassazione
Fon.te corretta, fix anni di iscrizione, coefficienti INPS 2025, ecc.).
Obiettivo: rendere lo strumento il più accurato possibile per la pianificazione
FIRE in **Italia**.

Le voci sono ordinate per **gravità**: BUG CONFERMATI → BUG MINORI / EDGE CASE
→ INCONSISTENZE FISCALI ITALIANE → MIGLIORAMENTI ACCURATEZZA → CODE QUALITY.

---

## 🔴 BUG CONFERMATI (effetti numerici sul risultato)

### B1. `monte_carlo.py` / `simulation.py` — fase "Capitale richiesto a FIRE": le spese partono dal valore di OGGI invece che da quello già rivalutato a FIRE
File coinvolti:
- `views/fire_tab.py` righe 461-470 (build di `fire_phase_kwargs`).
- `simulation.py` riga 162-163 e `monte_carlo.py` riga 151:
  ```python
  housing_monthly = rent_monthly_now * ((1 + rent_growth_monthly) ** m)
  ```

Quando `fire_tab.py` calcola il "Capitale richiesto a FIRE", invoca il Monte
Carlo con `start_age = planned_retirement_age`. Però passa **invariati**:
- `rent_monthly_now`
- `monthly_non_housing_expenses`
- `owner_monthly_cost`

Nel ciclo MC, `m` riparte da 0 → l'affitto a FIRE viene calcolato come
`rent_monthly_now * (1 + rent_growth_monthly)^0 = rent_monthly_now`.

**Effetto:** se la simulazione "fase FIRE" parte a 44 anni e l'affitto cresce
1%/anno reale, l'affitto a 44 anni dovrebbe essere `rent_monthly_now * 1.01^14
≈ 1,15×`. Il bug **sotto-stima le spese** del 10-20% per tutta la fase di
decumulo, e quindi **sotto-stima il capitale richiesto** per ottenere il target
di sopravvivenza (95%).

**Fix consigliato:** in `views/fire_tab.py` quando si costruisce
`fire_phase_kwargs`, riscalare le spese al valore proiettato a FIRE:
```python
years_to_fire = cfg["planned_retirement_age"] - age_now
rent_at_fire = cfg["rent_monthly_now"] * (1 + cfg["rent_real_growth"]) ** years_to_fire
non_housing_at_fire = monthly_non_housing_expenses * 1.0  # già reale, salary growth non si applica alle spese
owner_at_fire = cfg["owner_monthly_cost"] * (1 + cfg["owner_cost_real_growth"]) ** years_to_fire
fire_phase_kwargs.update({
    "rent_monthly_now": rent_at_fire,
    "owner_monthly_cost": owner_at_fire,
    "monthly_non_housing_expenses": non_housing_at_fire,
})
```
(Le spese non-housing in euro reali in teoria sono costanti, ma se l'utente
modella un drift reale in futuro andrebbe coerentemente scalato.)

Stesso problema potenziale in `inheritance_age` quando l'eredità si sarebbe già
verificata prima dell'inizio della fase FIRE: in quel caso il triggering
dell'eredità avverrebbe a età `inheritance_age >= start_age` ma `months_to_inh`
sarebbe `(inheritance_age - planned_retirement_age) * 12` → eredità solo
**futura**. Se invece l'eredità è già passata (`inheritance_age <
planned_retirement_age`), il flag `inheritance_event_done` parte False ma
`age >= inheritance_age` è subito True → entra nel branch e **aggiunge di nuovo
l'eredità**, raddoppiandola.

**Fix:** se `inheritance_age <= start_age`, il portafoglio iniziale a FIRE
dovrebbe già contenere l'eredità (non riaggiungerla), oppure mettere
`inheritance_event_done = True` all'inizio.

---

### B2. `pension_inps.py::step_inps` — il coefficiente di trasformazione viene clampato a 71 anche se l'utente sceglie pensione a 73
La tabella `INPS_TRANSFORMATION_COEFFICIENTS` arriva a 71 (limite tabella MEF
2025). In `inps_transformation_coefficient` il clamp è:
```python
age_int = max(min_age, min(age_int, max_age))
```
Quindi `pension_access_age = 73` (default DB) → coefficiente di **71**
(0,06530). In realtà al posticipare il pensionamento INPS oltre 71 il
coefficiente reale **continua a crescere** (non è solo un limite tabella, è un
limite legale: il sistema contributivo accetta posticipi e ricalcola).

**Effetto:** chi pianifica pensione a 73 vede una pensione INPS più bassa di
quella reale. **Sotto-stima** il netto pensione di ~5-7% (la differenza
attuariale tra 71 e 73).

**Fix consigliato:**
- Ammettere lo slider INPS solo nel range 57-71 (cap della tabella ufficiale),
  oppure
- Estendere la tabella con valori estrapolati linearmente fino a 75-80, con
  caption "valori oltre 71 sono estrapolazioni".

Lo slider in sidebar ha già `max_value=71` (riga 131), ma la migrazione DB
imposta `pension_access_age = 73` (riga 199 di `db.py`):
```python
"UPDATE simulation_params SET pension_access_age = 73 WHERE id = 1 AND pension_access_age = 67"
```
→ se l'utente non riapre la sidebar, il valore 73 finisce nel calcolo,
clampato a 71. **Inconsistenza tra DB default e UI cap**.

**Fix:** rimuovere la migrazione 67→73 oppure estendere la tabella fino a 73-75.

---

### B3. `simulation.py` / `monte_carlo.py` — il `salary_t` non viene azzerato esplicitamente ma il branch `retired` lo ignora
Riga 185 di `simulation.py`:
```python
salary_t = monthly_salary * ((1 + salary_growth_monthly) ** m)
```
calcolato **anche se retired**. Poi:
```python
if retired:
    ...  # salary_t non usato
else:
    cashflow_t = salary_t - monthly_expenses_t
```
OK funzionale, ma **fuorviante**: se in futuro qualcuno aggiunge un branch
"Coast FIRE" con stipendio parziale, il `salary_t` potrebbe essere ri-usato per
errore.

**Effetto:** nessuno oggi, ma debito tecnico.

---

### B4. `simulation.py::simulate` — `cost_basis += cashflow_t` quando `cashflow_t > 0` non considera il drag
Riga 209-210:
```python
cashflow_t = salary_t - monthly_expenses_t
if cashflow_t > 0:
    cost_basis += cashflow_t
```
Il risparmio mensile (cashflow positivo) entra come "cost basis" 1:1, ok. Ma
**ogni mese il portafoglio cresce** (con `real_monthly`). Il `cost_basis` non
viene rivalutato, quindi col tempo `gain_ratio = (portfolio - cost_basis) /
portfolio` cresce monotonicamente verso 1. Questo è **coerente con la realtà
fiscale italiana** (le plusvalenze sono solo l'incremento, non il capitale
nominale), ma:

- All'eredità (`portfolio += inheritance_cash_real; cost_basis +=
  inheritance_cash_real`) si **resetta parzialmente** il rapporto, OK.
- Su orizzonti di 50+ anni, il `gain_ratio` tende a >0,9 → l'aliquota effettiva
  ≈ 23-24% (vs 26% nominale). Modello corretto.

**Non è un bug**, ma vale la pena verificare che il caption nella sidebar
("aliquota effettiva sulle plusvalenze ... col tempo la % di gain cresce con
l'interesse composto → aliquota effettiva sale") corrisponda a ciò che vede
l'utente in fase FIRE estrema (40+ anni).

---

### B5. `views/edit_tab.py` riga 33 — gestione errata di `quantity` NaN
```python
qty_val = float(row["quantity"]) if row["quantity"] is not None else 0.0
```
Pandas restituisce `np.nan` (non `None`). `np.nan is not None` → True →
`float(np.nan) = nan`. L'input si popola con `nan` → l'utente lo vede vuoto e
salvando può scrivere NaN nel DB.

**Fix:**
```python
qty_val = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
```

---

### B6. `db.py::save_params` — non salva `inheritance_cash_amount`, `inps_pension_coefficient`, `inps_irpef_rate`
Confrontando la `UPDATE` con lo schema:
- `inheritance_cash_amount` (nello schema) → non salvato (perché viene calcolato
  dagli asset Immobiliare via `fire_tab.py`). **Dead column** nel DB.
- `inps_pension_coefficient` → idem, non più usato (sostituito da tabella
  coefficienti).
- `inps_irpef_rate` → idem (sostituito da IRPEF a scaglioni).

**Fix:** rimuovere queste tre colonne (con migrazione DROP COLUMN se SQLite ≥
3.35) oppure documentarle come deprecate.

---

## 🟠 BUG MINORI / EDGE CASE

### B7. `db.py::_seed_assets` e `_ensure_real_estate_assets` — dati personali hardcoded
Il seed contiene importi specifici (€61.818 SWDA, €23.500 Fon.te, €25.000 CA
Auto Bank, €250.000 cash eredità, ecc.). Per chi clona la repo, il primo avvio
restituisce **dati di un altro utente**. Stesso vale per:
- `constants.py::BIRTH_DATE = date(1994, 8, 26)`
- migrazione `planned_retirement_age = 44.17` in `db.py`.

**Fix consigliato:**
- Seed con valori a zero / esempio palesemente didattico.
- `BIRTH_DATE` come parametro `simulation_params.birth_date` salvato dall'utente
  al primo avvio (con default plausibile e prompt UI).
- Rimuovere la migrazione `planned_retirement_age = 44 → 44.17` (puramente
  personale, irrilevante per altri utenti).

### B8. `simulation.py::simulate` riga 113 — il loop scrive l'ultimo `age` *prima* del cashflow finale
```python
for m in range(months + 1):
    ...
    ages.append(...); values.append(...)
    ...
    portfolio = portfolio * (1 + real_monthly) + cashflow_t
```
L'ultimo append (m = months) registra il portafoglio **prima** del cashflow di
quel mese. È un off-by-one cosmetico (1 mese di rendimento + 1 prelievo
mancanti). Per simulazioni di 60+ anni è invisibile sul grafico ma
matematicamente l'ultimo punto della curva non è "alla fine del mese ultimo".

**Fix:** dopo il loop, fare un append finale del portafoglio aggiornato.

### B9. `simulation.py::simulate` — `if retired and portfolio <= 0` non blocca il loop
```python
if retired and portfolio <= 0:
    portfolio = 0
    success = False
```
Il flag `success = False` è settato ma il loop **continua**, registrando
portfolio=0 per i mesi successivi. Nessun bug funzionale, ma sprecata
computazione e curva piatta a zero che confonde la UI.

**Fix:** `break` dopo aver registrato la riga finale.

### B10. `monte_carlo.py::_run_one_mc` — stessa logica, ma con `return False` immediato (riga 192). Asimmetria con `simulate`.
`simulate` continua, MC esce subito. Comportamento **incoerente**. Dato che il
DataFrame di `simulate` viene ridipinto sul grafico, la coda piatta a zero
non è un problema, ma è meglio uniformare.

### B11. `pension_fonte.py::step_fonte` — la moltiplicazione del rendimento al pot avviene anche durante il mese di sblocco
Riga 171: `pot = pot * (1 + monthly_rate) + monthly_contrib` (se pre-FIRE).
Riga 174: `pot = pot * (1 + monthly_rate)` (se post-FIRE pre-sblocco).
Riga 176: `if age >= fonte_access_age:` → liquida.

Se sblocco accade nello stesso mese del pre/post-FIRE, il pot ha già un mese di
rendimento. Coerente con convenzione end-of-month. OK.

### B12. `pension_inps.py::step_inps` — la rivalutazione `m % 12 == 0` cattura anche m=12, 24, ... ma il **primo** anno (m=1..11) non rivaluta
Il modello applica la rivalutazione solo a m=12, 24, .... Questo significa che
i contributi del 1° anno non sono rivalutati (eccetto `inps_montante_current`
che subisce la rivalutazione a m=12). Approssimazione plausibile (la
rivalutazione INPS è applicata al 31/12, quindi i contributi del 2025 vengono
rivalutati per la prima volta al 31/12/2026).

**OK**, ma il caption non lo spiega.

### B13. `pension_inps.py::annual_net_pension_from_gross` — addizionali con franchigia €8.500 fisso
La franchigia per addizionali in realtà varia per comune (es. Roma €11.000,
Milano €15.000, alcuni comuni 0). L'approssimazione è conservativa (sotto-stima
il netto). OK come default semplificato.

### B14. `pension_inps.py` — non distingue tra pensionati < 75 e ≥ 75 anni
La detrazione pensione e la no-tax-area sono **diverse** sopra i 75 anni:
- < 75: no-tax-area € 8.500.
- ≥ 75: no-tax-area € 8.700, detrazione max €1.880.

Approssimazione di 1-2% sul netto post-75. Marginale.

### B15. `monte_carlo.py::_run_one_mc` riga 186 — `mid_month_factor = (1 + random_r) ** 0.5 if random_r > -1 else 0.0`
Se `random_r = -0.5` (-50% in un mese, possibile con crash), `(1-0.5)**0.5 ≈
0.707`. Quindi un prelievo €1000 in un mese di crash perde solo il 30% di
"rendimento mancato negativo" → **portafoglio penalizzato meno** del dovuto.

In realtà con `(1+r)^0.5` per `r<0` il prelievo a metà mese è prelevato in un
saldo già "mezzo crashato" (ovvio: se il portafoglio sta crashando, prelevare
prima ti salva una mezza parte del crash). Matematicamente coerente.

OK, ma andrebbe documentato che la convenzione half-month non è simmetrica per
crash forti.

### B16. `db.py::_drop_legacy_fonte_return_columns` — silenzioso fallimento
Se SQLite < 3.35 (rare ma possibili in container vecchi), il `DROP COLUMN`
lancia `OperationalError` catchata silenziosamente → le colonne legacy
sopravvivono. Non è un bug funzionale (le colonne non vengono lette), ma
inquina lo schema.

**Fix:** loggare un warning quando si entra nel `except`.

### B17. `views/sidebar.py` riga 153 — `pd.to_datetime(fonte_enrollment_date_str).date()`
Se l'utente nel DB ha data malformata (es. "2021-13-45"), `pd.to_datetime`
lancia eccezione **non gestita** → la pagina crasha. Stesso vale per
`fonte_tax_rate_by_enrollment` che ha try/except ma su sidebar la conversione
date_input avviene prima.

**Fix:** wrappare in try/except con fallback "2021-04-01".

### B18. `fonte_tax_rate_by_enrollment` — fallback `years_of_enrollment = 0` su data invalida
Nessun warning all'utente: l'aliquota torna 15% (meno favorevole). Se la data
era in realtà di 30 anni fa, l'utente paga "in simulazione" 6% in più di tasse
Fon.te. Aggiungere log/warning.

### B19. `fire_tab.py::_project_fonte_pot` e `_project_inps_montante` — duplicano logica già presente in `step_fonte` / `step_inps`
Tre implementazioni diverse della stessa cosa (sidebar, fire_tab, simulation).
Rischio di drift tra implementazioni se una viene aggiornata e le altre no.

**Fix:** usare le funzioni `step_*` già esistenti via un wrapper.

---

## 🟠 INCONSISTENZE FISCALI ITALIANE (semplificazioni del modello)

### F1. Imposte di successione e ipo-catastali sull'eredità non modellate
Eredità in Italia (D.Lgs. 346/1990 e succ.):
- **Coniuge / figli / genitori**: franchigia €1M, oltre 4%.
- **Fratelli/sorelle**: franchigia €100k, oltre 6%.
- **Altri parenti entro 4° grado**: 6% senza franchigia.
- **Estranei**: 8% senza franchigia.

Inoltre **imposta ipotecaria 2% + catastale 1%** sul valore catastale (no
franchigia) per immobili. Su una casa da €300k catastali (≈ 1/3 del valore
mercato) → ~€3-9k di imposte ipo-catastali, *non modellate*.

**Effetto:** sovrastima dell'eredità netta del 1-3%.

### F2. IMU/TARI sulla seconda casa ereditata (50%) non modellate
Il modello usa solo `owner_monthly_cost` come parametro libero, ma:
- IMU seconda casa: ~1% del valore catastale → su casa €100k catastali = €1.000/anno.
- TARI: ~€300-500/anno.
- Manutenzione straordinaria 0,5-1% del valore = €1-2k/anno.

Anche nello scenario "rent_life_with_sale" la casa al 50% **resta** (perché
non liquidabile facilmente al 50%) e genera spese. Il modello la **ignora**.

**Fix:** aggiungere `partial_house_annual_cost` (default €1500) tra le spese
post-eredità.

### F3. Plusvalenza su casa ereditata in caso di vendita
Se housing_mode = "rent_life_with_sale" e l'utente vende la casa ereditata:
- **Prima casa** ereditata (o detenuta >5 anni): **esente da plusvalenza**.
- **Seconda casa** entro 5 anni dall'eredità: plusvalenza tassata 26% (cedolare)
  oppure IRPEF a scaglioni.

Il modello aggiunge il `full_house_value` al portafoglio + cost_basis ⇒ zero
plusvalenza implicita. **Coerente con caso "prima casa"** ma non corretto se la
casa fosse seconda casa venduta entro 5 anni.

### F4. PIR / PIR Alternativi non modellati
Strumenti italiani con esenzione totale plusvalenze se detenuti ≥ 5 anni.
L'utente che intendesse usarli vede aliquota 26% piena → simulazione
**conservativa** (più tasse delle reali). Marginale.

### F5. Cedolare secca affitti (post-FIRE)
Se l'utente affitta la casa ereditata invece di viverci → reddito 21%/10%
flat. Non modellato come scenario alternativo.

### F6. Nessuna pensione anticipata da contributi
In Italia con 41a 10m (donne) / 42a 10m (uomini) di contributi si va in
pensione *indipendentemente dall'età*. Lo slider `pension_access_age` parte da
57 (Quota 103/personaggio anticipata), ma **non c'è automatismo** che dica
"hai 42 anni di contributi → pensione subito".

**Fix:** aggiungere parametro `inps_anni_contribuzione_attuali` e calcolare
`pension_access_age_effettivo = max(età_minima, età_quando_anni_contribuzione
≥ 42.83)`.

### F7. INPS — la rivalutazione del montante è "reale" nel modello
Lo slider dice "rivalutazione montante INPS (%/anno, reale)" → 1,5% default. Ma
la rivalutazione INPS reale è la **media quinquennale del PIL nominale**
deflazionato. Negli ultimi 20 anni in Italia: PIL nominale ~2%, inflazione
~1,5% → reale ~0,5%. Il default **1,5% reale è ottimistico** (è coerente con
la media di lungo periodo solo se si crede a una ripresa strutturale).

**Suggerimento:** lasciare il default 1,5% ma aggiungere un'annotazione storica.

### F8. Stipendio a crescita reale 3% — non realistico per Italia
In Italia gli aumenti reali medi (al netto inflazione) sono storicamente
0,5-1%/anno (con periodi di crescita zero o negativa). Il default **3% reale è
molto ottimistico** e gonfia il montante INPS, le contribuzioni Fon.te e il
risparmio post-stipendio.

**Effetto:** sotto-stima del capitale richiesto FIRE del 5-15% (perché modello
suppone più cashflow disponibile in fase di accumulo).

**Suggerimento:** default 1% reale, oppure rinominare lo slider in "crescita
nominale" e ricalcolare reale internamente.

### F9. Inflazione costante deterministica
Già segnalato in review storica, ancora aperto. Per FIRE 50+ anni il rischio
inflazione è **uno dei tre rischi principali** (insieme a sequence-of-returns
e longevità). Modellarla stocastica nel MC sarebbe un upgrade rilevante.

### F10. Volatilità portafoglio fissa (slider unico)
`annual_volatility = 14%` di default è fissa indipendentemente dall'asset
allocation. Un portafoglio 100% azionario ha vol ~16-18%, un 60/40 ~10%, un
40/60 ~7%. Il modello usa lo stesso valore qualunque sia l'allocazione →
**MC scollegato dalla realtà del portafoglio**.

**Fix:** derivare la volatilità da una mappa `category → volatilità_attesa`
analoga a `category → rendimento_atteso`, pesare e (opzionalmente) applicare un
fattore di diversificazione (es. 0,9 per ridurre la vol di portafoglio diverso).

### F11. Crash come jump indipendente
`monthly_crash_prob = crash_prob_annual / 12` è iid mese su mese. Manca
**autocorrelazione negativa** (mean reversion) e **clustering volatilità**
(GARCH). Il modello attuale **sotto-stima drawdown prolungati** (il risk per
sequence-of-returns).

**Fix migliore:** bootstrap dalle serie storiche MSCI World 1970-2024 invece
di gaussiana + jump. Cattura naturalmente fat tails e clustering.

### F12. Profilo spese age-based (U-shape)
`post_fire_expense_multiplier` costante per sempre. La realtà:
- 60-75 anni: alta (viaggi, hobby, salute discreta).
- 75-85 anni: in calo (meno mobilità).
- 85+ anni: spese sanitarie esplosive (RSA: €2-4k/mese, assistenza
  domiciliare: €1.500-3.000/mese).

**Suggerimento:** profilo spese per età:
```python
def expense_multiplier(age):
    if age < 70: return 1.5
    if age < 80: return 1.3
    return 1.8  # assistenza
```

### F13. Glide path / lifecycle allocation non modellato
Allocazione fissa per tutta la simulazione. Bengen/Pfau-Kitces dimostrano che
una "rising equity glide path" (azionario che cresce in pensione) riduce il
sequence-of-returns risk. Il modello attuale ignora questa best practice.

### F14. INPS revaluation deterministica nel MC
Anche nel Monte Carlo `inps_montante_revaluation_rate` è scalare. La
rivalutazione INPS è correlata con il PIL nominale → nel MC andrebbe
correlata negativamente con shock azionari (recessione → PIL giù → INPS giù E
mercati giù → doppia botta).

### F15. Fon.te deterministico nel Monte Carlo
Anche `fonte_real_monthly` è scalare. Il fondo Fon.te è esposto a equity
(60%) → andrebbe stocastico e correlato con i rendimenti del portafoglio.

---

## 🟢 MIGLIORAMENTI ACCURATEZZA Italia-specifici

1. **Imposte successione + ipo-catastali** sull'eredità (vedi F1).
2. **IMU/TARI/manutenzione** sulla casa al 50% non liquidata (vedi F2).
3. **No tax area pensione** differenziata per età ≥ 75 (vedi B14).
4. **Pensione anticipata da contributi** (vedi F6).
5. **PIR / cedolare secca affitti** (vedi F4, F5).
6. **TFR vs Fon.te**: il simulatore assume tutto in Fon.te. Il TFR in azienda
   ha tassazione separata su media IRPEF ultimi 5 anni → diversa.
7. **Riscatto laurea agevolato** (legge Fornero) come "what if".
8. **Sanità privata post-FIRE** (€1-3k/anno/persona dopo 60 per polizze
   integrative). Aggiungibile come voce nel post-FIRE multiplier.

---

## 🛠️ CODE QUALITY

### CQ1. Test mancanti
Nessuna directory `tests/`, nessun pytest. Per un tool finanziario è grave.

**Suggeriti:**
- `test_pension_inps.py`: IRPEF su redditi noti (€8500, €15000, €30000,
  €50000), detrazione ai limiti.
- `test_pension_fonte.py`: aliquota dopo 5/15/20/35 anni di iscrizione.
- `test_simulation.py`: smoke test, deterministico con seed fissato.
- `test_monte_carlo.py`: con seed fissato output identico.
- `test_portfolio.py`: `effective_capital_gains_tax(0)`, `(0.5)`, `(1)`.

### CQ2. Linter / type checker non configurati
Aggiungere `ruff.toml` (formatter + linter veloce) e `mypy.ini` (type checker).
Il codice ha già parziali type hints, basta poco per renderlo strict.

### CQ3. `simulation.py` e `monte_carlo.py::_run_one_mc` molto ridondanti
Il loop mensile è scritto due volte con micro-differenze (rendimento det vs
stocastico, mid_month_factor con check su random_r > -1 nel MC).

**Refactor:**
```python
def simulate_path(rng_or_none, portfolio, ..., return_generator):
    for m in range(months + 1):
        ...
        r = return_generator(m)  # deterministico o stocastico
        ...
```
Riduce ~50% del codice e elimina rischio di drift.

### CQ4. Costanti magiche sparpagliate
- `0.075`, `0.035`, `0.60`, `0.40` (rendimenti/pesi Fon.te di default) duplicati
  in `pension_fonte.py`, `simulation.py`, `monte_carlo.py`.
- `0.30` (initial_gain_pct default) sparso.
- Soglie IRPEF (28000, 50000) hardcoded in `pension_inps.py` (potrebbero
  essere costanti aggiornabili).

**Fix:** centralizzare in `constants.py` con commento sulla normativa di
riferimento.

### CQ5. `views/fire_tab.py` 552 righe — troppo monolitico
La funzione `render` fa: derivazioni portafoglio + grafico scenari + tabella
asset futuri + metriche + Monte Carlo button + risultati. Suddividerla:
- `_compute_scenarios(...)`
- `_render_chart(...)`
- `_render_future_assets_table(...)`
- `_render_mc_results(...)`

### CQ6. `db.py::_seed_assets` e `_ensure_real_estate_assets` hardcoded
Vedi B7. Spostare i dati personali in un fixture `examples/seed_personal.py`
caricabile via flag CLI o pulsante "carica esempio".

### CQ7. `views/sidebar.py` non separa input da side-effect (DB save)
Il bottone "Salva parametri" è dentro `render()`. Va bene per Streamlit, ma
rende la sidebar non testabile. Non urgente.

### CQ8. `portfolio.py::estimate_portfolio_nominal_return` — `groupby().apply()` deprecato
Pandas 2.2+ avvisa con `DeprecationWarning`. Sostituire:
```python
# Da:
df.groupby("category").apply(lambda g: pd.Series({
    "Valore": g["current_value"].sum(),
    ...
}))
# A:
df.groupby("category").agg(
    Valore=("current_value", "sum"),
    Peso=...,
)
```

### CQ9. `requirements.txt` senza upper bound / lock file
`streamlit>=1.35.0` etc. Per riproducibilità: `requirements-lock.txt` con
versioni esatte da `pip freeze`, oppure usare `pyproject.toml` + `uv lock`.

### CQ10. Caching mancante
`load_assets()`, `load_params()`, `estimate_portfolio_nominal_return()`
vengono chiamate **due volte** per ogni rerun di Streamlit (sidebar +
fire_tab). Aggiungere `@st.cache_data` con TTL breve.

### CQ11. `monte_carlo.py::required_capital_for_target_survival` — Common Random Numbers non documentato
La binary search riusa lo stesso seed per tutte le iterazioni → CRN. È una
scelta corretta (riduce varianza) ma andrebbe esplicitata nel docstring + UI
(es. "i risultati sono deterministici per fissato seed").

### CQ12. Slider `planned_retirement_age` cap a 60 in sidebar
`min_value=age_now, max_value=60.0` (sidebar.py riga 122-126). Chi vuole
pianificare un FIRE oltre 60 anni (es. "regular retirement") non può.
Estendere a 75.

### CQ13. Colonne DB morte: `inheritance_cash_amount`, `inps_pension_coefficient`, `inps_irpef_rate`
Vedi B6. Da pulire.

### CQ14. Asimmetria scenari grafico
`fire_tab.py` mostra "Affitto pessimista/base/ottimista + Proprietà solo base".
Aggiungere "Proprietà pessimista/ottimista" per simmetria UX.

### CQ15. Nessuna gestione errori centralizzata
Eccezioni in `db.py`, `pension_fonte.py`, `views/sidebar.py` con
`try/except` muti. Considerare un decorator `@safe_run` con logging strutturato
(es. `logging.warning`).

---

## 📋 PRIORITIZZAZIONE INTERVENTI (aggiornata)

### 🔴 ALTA — impatto numerico significativo, fix rapidi
1. **Fix B1**: spese e housing rivalutati a FIRE quando si chiama il MC "fase
   FIRE". Stimato impatto: 10-20% di variazione sul capitale richiesto.
2. **Fix B2**: estendere tabella coefficienti INPS oltre 71 o restringere il
   default DB a 67 invece di 73. Stimato impatto: 5-7% sulla pensione netta.
3. **Fix B5**: gestione `pd.notna` su `quantity` in edit_tab.
4. **Fix B6**: rimuovere colonne morte dallo schema DB.
5. **Fix F8**: rivedere default `salary_growth_rate` (3% reale → 1% reale)
   con annotazione storica.
6. **Fix F2**: aggiungere costo annuo casa al 50% nello scenario eredità.
7. **Fix F1**: stimare imposte successione come % singola sull'eredità totale.

### 🟠 MEDIA — raffinamenti modello
8. Volatilità derivata da asset allocation (F10).
9. Glide path / rising equity allocation (F13).
10. Inflazione stocastica nel MC (F9).
11. Profilo spese U-shape post-FIRE (F12).
12. Pensione anticipata da contributi (F6).
13. Bootstrap storico per i rendimenti MC (F11).

### 🟢 BASSA — qualità codice
14. Test suite con pytest (CQ1).
15. Refactor `simulate` + `_run_one_mc` (CQ3).
16. Rimuovere dati personali dal seed (B7).
17. Centralizzare costanti (CQ4).
18. Aggiornare API pandas (CQ8).
19. Lock file dipendenze (CQ9).
20. Caching `@st.cache_data` (CQ10).

---

## ✅ Cosa è stato fatto bene (rispetto alla prima review)
- ✅ Bollo titoli 0,2% + TER ETF 0,3% → `portfolio_annual_drag` integrato.
- ✅ Aliquota 12,5% titoli di Stato distinta dal 26% →
  `effective_capital_gains_tax(state_bond_share)`.
- ✅ Addizionali regionali e comunali → `annual_net_pension_from_gross`.
- ✅ Coefficienti INPS 2025 + slider haircut futuro.
- ✅ Doppia tassazione Fon.te corretta: rendimenti netti durante l'accumulo,
  contributi tassati 9-15% in uscita.
- ✅ Anni di iscrizione Fon.te calcolati con un solo `int()` sulla somma.
- ✅ Convenzione half-month per prelievi (più conservativa).
- ✅ Rivalutazione INPS annuale (a m % 12 == 0).
- ✅ Architettura modulare chiara (constants/db/portfolio/pensioni/simulation/views).
- ✅ Migrazioni DB non distruttive con `ALTER TABLE ADD COLUMN`.
- ✅ Calcolo plusvalenza dinamico con cost basis tracking.
- ✅ Modello tutto in euro reali.
- ✅ IRPEF a scaglioni vera (non aliquota piatta).
- ✅ UI organizzata in tab + caption esplicativi.

---

## 📌 Riepilogo finale
Il tool ha **buone fondamenta fiscali** per l'Italia (post correzioni). I bug
residui più impattanti sono:
1. Le spese **non vengono rivalutate** quando si calcola il "capitale richiesto
   a FIRE" (sotto-stima 10-20%).
2. Il **default DB** per `pension_access_age = 73` cozza con il **cap della
   tabella coefficienti** a 71, sotto-stimando la pensione INPS.
3. **Default troppo ottimistici** per crescita stipendio reale (3%) e
   rivalutazione INPS (1,5%): andrebbero abbassati o convertiti a nominali.
4. **Eredità senza imposte** (successione, ipo-catastali, IMU/TARI casa al
   50%): sovra-stima dell'eredità netta del 2-5%.
5. **Volatilità unica scollegata dall'asset allocation**: il MC è
   matematicamente coerente ma non rispecchia la composizione reale.

I primi due fix sono **quick wins** (mezza giornata di lavoro) e cambiano il
risultato finale del 5-20%. Gli altri sono raffinamenti di medio termine.