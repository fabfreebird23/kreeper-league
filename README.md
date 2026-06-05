# The Kreeper League — Keeper Hub

A dashboard for our fantasy league to set keepers, with live keeper-cost math and
daily multi-source ADP. Built on Streamlit, fed by the public Sleeper API.

## What it does

- **Pick-your-name keeper entry.** Each manager loads their real Sleeper roster,
  sees every player's keeper year / eligibility / cost, and marks up to
  3 regular + 2 rookie keepers.
- **Keeper-cost engine** (house rules, all in `config.yaml`):
  - 3-year max per regular keeper.
  - **Year 1** — keep at the round you drafted them.
  - **Year 2** — bump up 3 rounds *or* keep at ADP (your choice).
  - **Year 3** — must keep at ADP.
  - **Rookie keepers** — kept for their whole career; exempt from the clock.
    Move one into a regular slot and the 3-year clock starts.
- **Everything from real data.** Draft rounds and keeper streaks are reconstructed
  from your actual Sleeper drafts (2023→present) — not transcribed.
- **Daily ADP** averaged across **ESPN, FantasyPros, FootballGuys** and the
  per-platform columns they expose (Underdog, NFFC, MFL, DraftKings, Drafters…).
  ADP overall rank → draft round via your league size.

## Layout

```
app.py                  Streamlit app (My Keepers / League Board / ADP tabs)
config.yaml             League + rules + manager map (pulled from Sleeper)
kreeper/
  config.py             config loader
  sleeper.py            Sleeper API client (league chain, drafts, players)
  history.py            keeper streaks + original draft rounds
  engine.py             eligibility + cost rules  (unit-tested)
  storage.py            keeper-selection persistence (JSON; swappable)
  names.py              cross-source player-name matching
  adp/                  espn / fantasypros / footballguys + consensus
scripts/
  refresh_adp.py        rebuild the ADP consensus CSV (run daily)
  build_history.py      dump a keeper-history snapshot CSV
.github/workflows/adp.yml   daily ADP refresh + commit
tests/test_engine.py    keeper-rule unit tests
data/                   generated CSV/JSON (ADP + selections)
```

## Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/refresh_adp.py     # pull today's ADP
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this folder to a GitHub repo.
2. On https://share.streamlit.io, point a new app at `app.py`.
3. The included GitHub Action refreshes ADP daily and commits it, so the live
   app always shows current numbers.

### Durable submissions via Google Sheets

On Streamlit Cloud the container filesystem resets on restart, so live keeper
submissions are stored in a **Google Sheet** when credentials are present
(otherwise it falls back to local `data/keepers_<season>.json`). One-time setup:

1. **Create a Google Cloud service account** (console.cloud.google.com → a project
   → APIs & Services → enable **Google Sheets API** → Credentials → Create
   service account → Keys → Add key → JSON). Download the JSON.
2. **Create a Google Sheet** and **Share** it (Editor) with the service account's
   `client_email`. Copy the sheet ID from its URL
   (`docs.google.com/spreadsheets/d/<ID>/edit`).
3. **Add secrets** in Streamlit Cloud → your app → Settings → **Secrets**, in the
   format shown in `.streamlit/secrets.toml.example` (`sheet_id` + the
   `[gcp_service_account]` JSON fields).

The app creates a `keepers_<season>` worksheet automatically and writes each
manager's picks there — durable, and you can view/edit it like any sheet.
Historical keeper years (2023–2025) stay in the committed local ledger.

## Config

All league specifics live in `config.yaml` — pulled from the Sleeper API
(8 teams, 14 rounds, PPR, 3+2 keepers) but editable. Rookie-keeper cost basis
defaults to "original rookie draft round"; flip `rules.rookie_keeper_cost` to
`fixed_round` or `free` if the house rule differs.
