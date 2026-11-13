# AI-Based Vendor Quotation Comparison System

Reads a buyer's comparative-statement workbook (like `data/Vendor_Quotation_Comparison.xlsx`) and automatically produces:

* item-wise L1/L2 ranking, price spread, and a heat-map of every vendor vs. the lowest rate
* like-for-like totals (quoted, **landed cost**, or landed + financing cost of advance)
* a weighted vendor scorecard (price, delivery, payment terms, warranty, technical)
* award scenarios (single vendor vs. item-wise split, Indian-only vs. foreign-only)
* negotiation tracking across rounds
* red flags (partial quotes, price outliers, unsecured advances, missing commissioning cost, errors in the manual L1 column)
* a written conclusion, an Excel report, and an optional **Claude** executive summary + Q&A

## 1. Setup in VS Code (once)

Requires Python 3.10 or newer.

1. Unzip the folder, then in VS Code: **File → Open Folder** and choose `vendor_quotation_ai`.
2. Open a terminal (**Terminal → New Terminal**) and run:

   **Windows**
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   **macOS / Linux**
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the `.venv` one.

## 2. Run locally

```
uvicorn app:app --reload
```
Open the displayed local URL. Load the sample workbook from the sidebar or upload your own.
The original Streamlit interface remains available with `streamlit run streamlit_app.py`.

No browser? `python cli.py data/Vendor_Quotation_Comparison.xlsx` prints the conclusion and writes an Excel report.

Self-check: `python tests/test_engine.py`

## 3. Deploy on Vercel

Import this project into Vercel and set the project root to the directory containing `app.py` and `requirements.txt`. Vercel serves the FastAPI application exported as `app` from `app.py`. The optional Claude integration can use an API key entered in the dashboard or `ANTHROPIC_API_KEY` from the deployment environment.

The workbook upload limit is 3 MB. Uploaded files and AI keys are not written to persistent storage by this app.

## 4. Turn on Claude (optional)

1. Create an API key at https://console.anthropic.com
2. Copy `.env.example` to `.env` and paste the key (or paste it in the sidebar → *Claude (AI)*).
3. Open the **Ask Claude** tab → *Generate executive summary*, or ask questions such as
   "Why not award everything to Beijing?" / "What should we negotiate with ABB on item 10?"

Design rule: Python computes every number; Claude only explains them from a compact JSON of results,
and is told not to invent figures. Without a key, every other feature still works.

## 5. How the comparison works

| Step | What happens |
|---|---|
| Load (`vqc/loader.py`) | Detects vendor blocks, negotiation rounds (`_R1`, `_R2`…), currency rows, ignores derived "Price in INR" columns, reads the terms rows. Latest round per item = final price. USD → INR with one FX rate. |
| Terms (`vqc/terms.py`) | Text → numbers: advance %, whether an ABG/LC/PBG protects payments, delivery months (weeks/days converted), warranty months, price basis (FOB / FOR / DAP / Ex-works), supervision cover. |
| Landed cost (`vqc/analysis.py`) | FOB quotes get freight+insurance, customs duty and clearance added; Ex-works gets inland freight; FOR/DAP unchanged. |
| Scoring | Price = item-wise L1 total ÷ vendor total on the same items. Delivery = fastest ÷ vendor. Payment = 100 − advance % (halved if ABG-backed, −20 if no bank protection). Warranty = months ÷ longest. Weights are sidebar sliders. |
| Partial quotes | Scored on the items they quoted, but never ranked as full-scope winners (e.g. BHEL, 4 of 10 items). |

## 6. Things you must review (assumptions)

* **Landed-cost percentages are placeholders** (`vqc/config.py`, or the sidebar). Replace with your logistics/customs numbers before relying on the Landed or TCO basis.
* Domestic prices are assumed GST-exclusive and GST is treated as recoverable.
* Technical rating rows in your sheet are empty, so technical score is excluded until you fill them (sidebar).
* "Warranty" uses the longest clock in "18/24 months" (assumed dispatch-based).
* Supervision/commissioning charges are flagged, not priced, because mandays are not specified.

## 7. Using your own workbooks

Keep the same layout as the sample: items down the rows; vendor name in a header row with one column per round; a currency row under the header; terms rows below the `Total` row. Different layout? Only `vqc/loader.py` needs adapting.

## 8. Project map

```
app.py            FastAPI web dashboard for Vercel
streamlit_app.py  Original Streamlit dashboard
cli.py            Command-line report
vqc/loader.py     Excel -> tidy tables
vqc/terms.py      Free-text terms -> numbers
vqc/analysis.py   L1, landed cost, scoring, scenarios, flags, conclusion
vqc/charts.py     Plotly charts
vqc/ai_assistant.py  Claude summary + chat
vqc/export.py     Excel report
vqc/config.py     Assumptions and weights
tests/            Sanity tests
```
