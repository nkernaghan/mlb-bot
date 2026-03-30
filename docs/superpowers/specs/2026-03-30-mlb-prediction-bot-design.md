# MLB Prediction Bot — Design Spec

## Overview

A Python-based MLB prediction bot that runs daily (cron) or on-demand (CLI), fetching data from free sources, running three independent prediction engines, and producing a graded daily report. Modeled after an existing NCAAB prediction bot with adaptations for baseball-specific analysis.

Incorporates findings from research into what sharp bettors and successful models are using in 2025-2026.

## Bet Types

### 1. Game Predictions (Moneyline / Run Line)

Predicts game outcomes with confidence scoring and edge calculation against market lines.

**Prediction Factors (13 signals):**

- Starting pitcher quality — weight xERA over ERA (strips out luck/defense noise). Use FIP, xFIP, SIERA as supporting signals. Recent form (last 3-5 starts) weighted separately.
- Opposing lineup strength vs handedness — L/R splits, K%, OPS, wRC+ vs pitcher handedness
- Barrel rate matchup — combined barrel rate of both lineups is one of the strongest predictors of run scoring. A lineup with >10% barrel rate against a pitcher allowing >8% barrel rate = elevated run expectancy.
- Bullpen strength and availability — recent usage (pitches thrown in last 3 days), aggregate ERA/FIP, leverage index, days rest per reliever
- Park factors — run factor, HR factor, K factor (indexed to 100 from FanGraphs). Include altitude adjustment (Coors).
- Weather — wind speed/direction (out to CF = +runs, in from CF = -runs), temperature (every 10°F above 70 adds ~0.5 runs), humidity, roof status
- Home/away splits — team and pitcher-level
- Team recent form — last 10-14 games, run differential, pythagorean record
- Head-to-head history — pitcher vs specific batters in opposing lineup (Statcast matchup data)
- Umpire tendencies — zone size (wide zone = fewer runs), K+ impact, run scoring impact from Umpire Scorecards
- Travel/rest — cross-country trips, day games after night games, series openers vs closers
- xBA/xSLG/xwOBA matchup — expected contact quality stats for lineup vs pitcher (from Baseball Savant)
- Vegas line blending — 60% market / 40% model consensus

### 2. Pitcher Strikeout Props (Starting Pitcher Over/Under)

Predicts starting pitcher strikeout totals and compares to posted over/under lines. Starting pitchers only.

Uses a **7-factor weighted scoring model** (validated approach from sharp K prop bettors):

**Primary Factors (highest weight):**
- CSW% (Called Strikes + Whiffs) — more comprehensive than SwStr% alone. Elite K pitchers are above 30%. This is the single best predictor of strikeout upside.
- SwStr% (Swinging Strike Rate) — above 12% = strong K potential. Measures pure whiff ability.
- Season K% — elite strikeout pitchers carry 28-30%+

**Secondary Factors:**
- Opposing lineup K% vs pitcher handedness — a 30% K-rate pitcher facing a 27% K-rate lineup = strong over signal
- Pitch count / innings expectation — estimate how many batters faced based on team's typical starter usage, recent workload, pitch count trends. This caps the K ceiling.
- Pitcher recent form — last 3 starts K rate, trending up or down

**Tertiary Factors:**
- Park K factor — Tropicana Field suppresses offense (more Ks), Coors altitude = fewer Ks
- Umpire strike zone tendencies — wide zone umpires generate more Ks
- Day/night splits
- Weather (wind, temperature affect swing decisions)
- Vegas K prop line for edge calculation

### 3. NRFI (No Runs First Inning)

Estimates NRFI probability and compares to implied odds probability. Outputs both a binary pick and the underlying probability/edge.

Research finding: XGBoost models show **FIP for both pitchers is the most significant predictor** — more predictive than raw first-inning ERA. Ensemble learning approaches outperform single models.

**Primary Factors (highest weight per XGBoost research):**
- Home pitcher FIP and away pitcher FIP — the #1 signal
- Starting pitcher first-inning ERA — historical 1st-inning run prevention
- Pitcher first-pitch strike rate — high F-Strike% = gets ahead early, controls the inning
- Historical NRFI rate for each pitcher

**Secondary Factors:**
- Opposing lineup first-inning performance — how lineups 1-3 perform in the first AB
- Leadoff hitter quality — OBP, speed (SB threat creates pressure)
- Pitcher vs batter matchup data for top-of-order hitters (Statcast)
- How quickly pitcher settles in (1st inning splits vs rest of game)

**Tertiary Factors:**
- Park factors — first-inning run frequency by venue
- Umpire tendencies — wide zone in 1st inning = pitcher advantage
- Weather conditions — cold/wind = suppressed offense
- Vegas NRFI odds for implied probability comparison

**NRFI market edge opportunity:** Research shows NRFI markets lag in pricing adjustments, particularly around late weather changes and lineup card submissions. Running the model after lineups are posted (60-90 min before first pitch) captures stale lines.

## Data Sources

| Source | Cost | Auth | How Accessed | Usage |
|--------|------|------|-------------|-------|
| MLB Stats API | Free | No key | `MLB-StatsAPI` Python package | Schedules, rosters, lineups, live data, pitcher/batter season stats, box scores, linescore, venue info, IL status |
| The Odds API | Free (500 req/mo) | API key | `requests` | Moneylines, run lines, totals, `pitcher_strikeouts` props, `1st_1_innings` NRFI odds |
| Baseball Savant | Free | No key | `pybaseball` | xERA, xBA, xSLG, xwOBA, barrel rate, CSW%, SwStr%, K%, spin rates, exit velocity |
| FanGraphs | Free | No key | `pybaseball` | FIP, xFIP, SIERA, park factors, plate discipline (O-Swing%, Z-Contact%), wRC+ |
| Baseball Reference | Free | No key | `pybaseball` | Historical splits, game logs, umpire data |
| Umpire Scorecards | Free | Scraping | `requests` + HTML parse | K+ impact, accuracy %, favor metric, zone consistency per umpire |
| OpenWeatherMap | Free tier | API key | `requests` | Wind speed/direction, temperature, humidity for outdoor parks |
| MLB Stats API (IL) | Free | No key | `MLB-StatsAPI` | Roster status codes (A/D10/D15/D60), transaction history for IL tracking |

**Key insight from research:** `pybaseball` wraps Baseball Savant, FanGraphs, and Baseball Reference in clean Python functions — eliminates the need for custom scraper code. Baseball Savant uses the same player IDs as the MLB Stats API, so no cross-referencing needed for Statcast data.

## Tech Stack

- **Language:** Python 3.11+
- **Database:** SQLite with WAL mode
- **MLB data backbone:** `MLB-StatsAPI` (official API wrapper) + `pybaseball` (Savant/FanGraphs/BRef)
- **HTTP:** `requests` (for Odds API, Umpire Scorecards, OpenWeatherMap)
- **Scraping:** `beautifulsoup4` (Umpire Scorecards HTML parsing)
- **Data:** `pandas` (data manipulation, CSV handling)
- **Config:** `python-dotenv`
- **AI narratives:** `anthropic` (optional)
- **Scheduling:** cron (daily morning run)

## Architecture

### Pipeline Flow

```
[1] Schedule + Lineups  -> MLB Stats API (single hydrated call)
    |
[2] Odds               -> The Odds API (moneylines, run lines, totals)
    |                      + per-event calls for K props and NRFI odds
    |
[3] Stats Fetch (parallel, cached daily):
    |   +-- pybaseball  -> FanGraphs leaderboard CSVs (FIP, xFIP, SIERA, park factors)
    |   +-- pybaseball  -> Savant expected stats (xERA, barrel rate, CSW%, SwStr%)
    |   +-- pybaseball  -> Batter plate discipline + splits
    |   +-- MLB API     -> Pitcher/batter season stats, game logs, roster/IL
    |   +-- Umpire Scorecards -> Plate umpire tendency data
    |   +-- OpenWeatherMap    -> Weather for outdoor venues
    |
[4] Per-Game Analysis (parallelized, 4 threads):
    |   +-- Game Predictor      -> 13-factor model -> moneyline / run line pick
    |   +-- Strikeout Predictor -> 7-factor weighted model -> K over/under
    |   +-- NRFI Predictor      -> FIP-primary ensemble -> NRFI probability + pick
    |
[5] Reporting       -> Generate daily report (per-game + summary)
    |
[6] Database        -> Save predictions, track results
```

### Caching Strategy

FanGraphs and Savant leaderboards are fetched once per day at pipeline start and stored in-memory (pandas DataFrames) + SQLite. All pitcher/batter lookups within the session read from the local cache. This avoids rate-limiting and speeds up the pipeline.

| Source | Cache TTL |
|--------|-----------|
| FanGraphs leaderboards | 24 hours |
| Savant expected stats | 24 hours |
| MLB API schedule | 15 minutes |
| MLB API player stats | 4 hours |
| Odds API lines | 30 minutes |
| Umpire Scorecards | 24 hours |
| Weather | 2 hours |
| Box scores (Final games) | Permanent |

### Project Structure

```
mlb-bot/
├── main.py                         # Entry point, CLI, pipeline orchestration
├── config.py                       # Central config (API keys, constants, thresholds)
├── requirements.txt
├── .env / .env.example
├── modules/
│   ├── data/
│   │   ├── schedule.py             # MLB Stats API — daily schedule + lineups
│   │   ├── odds.py                 # The Odds API — all bet types
│   │   ├── pitcher_stats.py        # Pitcher data aggregation (MLB API + pybaseball)
│   │   ├── batter_stats.py         # Batter data aggregation (MLB API + pybaseball)
│   │   ├── bullpen.py              # Bullpen usage and availability
│   │   ├── park_factors.py         # FanGraphs park factors
│   │   ├── umpires.py              # Umpire Scorecards data
│   │   ├── weather.py              # OpenWeatherMap integration
│   │   ├── injuries.py             # IL tracking from MLB API roster status
│   │   └── cache.py               # Daily leaderboard caching layer
│   ├── models/
│   │   ├── game_predictor.py       # 13-factor game outcome model
│   │   ├── strikeout_predictor.py  # 7-factor weighted K prop model
│   │   ├── nrfi_predictor.py       # FIP-primary NRFI ensemble model
│   │   └── confidence.py           # Shared confidence scoring + grading
│   ├── output/
│   │   ├── reporting.py            # Report generation (per-game + daily summary)
│   │   ├── results_tracker.py      # Result grading and record keeping
│   │   └── ai_summary.py          # Claude AI narratives (optional)
│   └── database.py                 # SQLite schema, queries, migrations
├── data/
│   ├── mlb.db                      # SQLite database
│   └── odds_history/               # Historical odds snapshots
├── reports/                        # Daily report output
├── logs/                           # Cron job logs
├── tests/                          # Test suite
│   ├── test_schedule.py
│   ├── test_pitcher_stats.py
│   ├── test_game_predictor.py
│   ├── test_strikeout_predictor.py
│   ├── test_nrfi_predictor.py
│   └── test_results_tracker.py
└── docs/
```

### Database Schema

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| games | Game metadata | game_pk, game_date, home_team_id, away_team_id, home_team_name, away_team_name, venue_id, venue_name, game_time_utc, day_night, status, home_score, away_score, home_pitcher_id, away_pitcher_id |
| odds | Line history snapshots | game_pk, fetched_at, home_ml, away_ml, run_line_spread, run_line_home_price, run_line_away_price, total, over_price, under_price |
| k_prop_odds | K prop line history | game_pk, pitcher_id, pitcher_name, fetched_at, line, over_price, under_price, bookmaker |
| nrfi_odds | NRFI line history | game_pk, fetched_at, nrfi_price, yrfi_price, bookmaker |
| pitcher_stats_cache | Daily pitcher metrics | player_id, player_name, team, date_cached, era, fip, xfip, siera, xera, k_rate, bb_rate, csw, swstr, barrel_rate_against, first_inning_era, f_strike_pct, innings_pitched, games_started, k_per_9 |
| batter_stats_cache | Daily batter metrics | player_id, player_name, team, date_cached, ops, k_rate, bb_rate, barrel_rate, xba, xslg, xwoba, wrc_plus, vs_lhp_ops, vs_rhp_ops |
| park_factors | Park adjustments | venue_id, venue_name, season, run_factor, hr_factor, k_factor, bb_factor |
| umpire_stats | Umpire tendencies | umpire_id, umpire_name, season, accuracy_pct, consistency_pct, k_plus, favor, games_behind_plate |
| bullpen_usage | Bullpen tracking | team_id, date, pitcher_id, pitcher_name, pitches_thrown, innings_pitched, days_rest, era, fip |
| predictions | All model outputs | game_pk, bet_type (game/strikeout/nrfi), pick, pick_detail, confidence, edge, model_value, market_value, grade, reasons, risks, created_at |
| results | Graded picks | game_pk, bet_type, pick, result (WIN/LOSS/PUSH), actual_outcome, edge_at_pick, confidence_at_pick, graded_at |

## CLI Interface

```bash
python main.py                    # Today's full analysis (all three bet types)
python main.py --date 2026-04-15  # Specific date
python main.py --game-only        # Just game predictions
python main.py --strikeouts       # Just K props
python main.py --nrfi             # Just NRFI picks
python main.py --grade-results    # Grade yesterday's picks
python main.py --record           # Season record tracker
python main.py --record --days 30 # Rolling 30-day record
python main.py --refresh          # Force re-fetch cached data (ignore TTL)
```

## Scheduling

- **Daily cron:** Morning run (configurable, e.g., 10 AM ET) for the full day's slate
- **On-demand:** Run manually anytime via CLI for fresh data
- **Optimal timing:** Run after lineups are posted (60-90 min before first pitch) to capture NRFI edge from stale lines

## Confidence Scoring & Grading

Adapted from the NCAAB bot, tuned per bet type.

**Grades:**
- **BET** — High confidence, clear edge over market, 3+ signals aligned
- **LEAN** — Moderate confidence, edge exists but data gaps or mixed signals
- **PASS** — Low confidence, no edge, or contradictions

### Game Predictor Confidence

**Base (data availability):** +20 (pitcher stats) +15 (lineup confirmed) +10 (bullpen data) +10 (umpire known) +10 (weather data) +10 (odds available)
**Bonuses:** +15 (xERA and FIP agree with model direction) +12 (3+ signals aligned) +10 (market agrees)
**Penalties:** -15 (lineup not confirmed) -12 (signals contradicting) -10 (park factor extreme) -5 (missing umpire data)

### Strikeout Predictor Confidence

**Base:** +25 (CSW% data) +20 (opposing lineup K% known) +15 (recent form data) +10 (umpire zone data)
**Bonuses:** +15 (CSW% and SwStr% both elite) +10 (opposing K% above 25%) +10 (K-friendly park)
**Penalties:** -15 (pitch count concern / short leash) -10 (K% trending down last 3 starts) -10 (missing opposing lineup data)

### NRFI Predictor Confidence

**Base:** +25 (both pitcher FIPs known) +20 (first-inning ERA data) +15 (leadoff hitter data) +10 (umpire known)
**Bonuses:** +15 (both pitchers FIP < 3.50) +12 (both pitchers NRFI rate > 65%) +10 (K-friendly park + umpire combo)
**Penalties:** -15 (pitcher with 1st-inning ERA > 4.50) -10 (elite leadoff hitter in lineup) -10 (hitter-friendly park + warm weather)

## Report Format

```
MLB Prediction Bot — 2026-03-30
============================================================

GAME PREDICTIONS
────────────────
NYY @ BOS | 7:10 PM ET | Fenway Park
  Starter: Cole (NYY) vs Bello (BOS)
  Cole: 2.51 ERA / 2.89 xERA / 3.01 FIP | Bello: 3.80 ERA / 3.45 xERA / 3.62 FIP
  Model Line: NYY -145 | Market: NYY -128
  Run Line: NYY -1.5 (+140) — LEAN
  Edge: 3.2% | Confidence: 68/100
  Top Factors: Cole xERA edge, BOS 28% K rate vs RHP, bullpen taxed (3-day load)
  Risks: Fenway HR factor 112, wind blowing out 15mph, Bello xERA better than ERA

PITCHER STRIKEOUT PROPS
───────────────────────
Gerrit Cole (NYY) vs BOS
  CSW: 32.1% | SwStr: 13.8% | K%: 30.2% | vs BOS K%: 26.8% (vs RHP)
  Pitch count est: 95-100 (~6.0 IP, ~24 batters faced)
  Model: 7.8 Ks | Line: O/U 7.5 Ks
  Pick: OVER 7.5 | Edge: +0.3 Ks
  Grade: LEAN | Confidence: 62/100
  Why: Elite CSW/SwStr combo + BOS high-K lineup, umpire Angel Hernandez K+ = +0.4

NRFI PICKS
──────────
NYY @ BOS
  Cole 1st-Inn ERA: 2.10 | FIP: 2.89 | NRFI Rate: 71%
  Bello 1st-Inn ERA: 3.40 | FIP: 3.62 | NRFI Rate: 58%
  Combined NRFI Prob: 61.3% | Implied from odds: 54.5%
  Pick: NRFI | Edge: 6.8%
  Grade: BET | Confidence: 70/100
  Why: Cole elite 1st-inning pitcher, both FIPs solid, Hernandez wide zone

TODAY'S BEST PICKS
==================
BET:
  - NRFI: NYY @ BOS (70/100, 6.8% edge)
LEAN:
  - Game: NYY ML -145 (68/100, 3.2% edge)
  - K Prop: Cole OVER 7.5 Ks (62/100, +0.3 Ks edge)

Season Record: 12-8-1 (60.0%) | +4.2 units
  Games: 8-5 (61.5%) | K Props: 6-4 (60.0%) | NRFI: 9-3 (75.0%)
```

## What Carries Over from NCAAB Bot

- Pipeline architecture (fetch -> analyze -> predict -> report)
- SQLite database for storage and result tracking
- The Odds API integration patterns
- Confidence scoring / grading system (BET / LEAN / PASS)
- Vegas blending approach (60% market / 40% model)
- Cron scheduling + CLI flags
- Report formatting patterns
- Result grading and record tracking
- Optional Claude AI narratives

## What's New vs NCAAB Bot

- MLB Stats API as the primary data backbone (official free API)
- `pybaseball` library for FanGraphs + Savant + BRef (no custom scrapers)
- Three separate prediction models instead of one
- Statcast advanced metrics (xERA, barrel rate, CSW%, SwStr%, xBA, xSLG, xwOBA)
- FIP-primary NRFI model (based on XGBoost research findings)
- 7-factor weighted K prop model with pitch count estimation
- Umpire Scorecards integration (K+ impact, zone accuracy)
- MLB-specific park factor system
- Bullpen usage/availability tracking with days-rest calculation
- Lineup-dependent predictions (baseball lineups change daily)
- Daily leaderboard caching layer (fetch once, lookup many)

## Research-Backed Design Decisions

1. **xERA over ERA** — Research shows xERA strips out luck and defense. A pitcher with 4.55 ERA but 3.46 xERA is being unlucky, not bad. Model weights xERA as primary, ERA as supporting context.

2. **Barrel rate as game total predictor** — Combined barrel rate of both lineups is one of the strongest signals for over/under and overall run scoring. Incorporated as a first-class game predictor signal.

3. **CSW% for K props** — More comprehensive than SwStr% alone because it captures called strikes (umpire influence) + whiffs. Elite K pitchers are above 30% CSW.

4. **FIP as primary NRFI signal** — XGBoost modeling research found FIP for both pitchers is the single most significant contributor to NRFI outcomes, outperforming raw first-inning ERA.

5. **NRFI market inefficiency** — Research confirms these markets lag in pricing adjustments around weather/lineup changes. Running after lineup submissions captures stale odds.

6. **Pitch count estimation for K ceiling** — Sharp K prop bettors cap projections based on expected innings/batters faced, not just rate stats. A high-K pitcher on a short leash still has a low K ceiling.

7. **pybaseball over custom scrapers** — Well-maintained open-source package that wraps Savant, FanGraphs, and BRef. Eliminates scraper maintenance burden and handles rate limiting.
