# MLB Bot — API & Data Source Research

**Date:** 2026-03-30
**Purpose:** Exact URL patterns, response structures, and field names for every data source used by the MLB prediction bot.

---

## 1. MLB Stats API (statsapi.mlb.com)

Base URL: `https://statsapi.mlb.com/api/v1`
No authentication required. JSON responses throughout. Rate limits are generous for personal projects.

---

### 1.1 Daily Schedule

**URL pattern:**
```
GET https://statsapi.mlb.com/api/v1/schedule
  ?sportId=1
  &date=YYYY-MM-DD
  &hydrate=probablePitcher,lineups,venue,team,broadcasts
```

The `hydrate` parameter is the key lever — it stuffs additional nested objects into each game record. You can add multiple values comma-separated. Without `hydrate`, you get bare game IDs and team stubs only.

**Top-level response structure:**
```json
{
  "copyright": "...",
  "totalItems": 15,
  "totalEvents": 0,
  "totalGames": 15,
  "totalGamesInProgress": 0,
  "dates": [
    {
      "date": "2025-04-01",
      "totalItems": 15,
      "totalGames": 15,
      "games": [ ... ]
    }
  ]
}
```

**Per-game object (inside `dates[0].games[]`):**
```json
{
  "gamePk": 748532,
  "gameGuid": "...",
  "link": "/api/v1.1/game/748532/feed/live",
  "gameType": "R",
  "season": "2025",
  "gameDate": "2025-04-01T23:10:00Z",
  "officialDate": "2025-04-01",
  "status": {
    "abstractGameState": "Preview",
    "codedGameState": "S",
    "detailedState": "Scheduled",
    "statusCode": "S",
    "abstractGameCode": "P"
  },
  "teams": {
    "away": {
      "leagueRecord": { "wins": 0, "losses": 0, "pct": ".000" },
      "score": 0,
      "team": {
        "id": 147,
        "name": "New York Yankees",
        "link": "/api/v1/teams/147"
      },
      "probablePitcher": {
        "id": 543037,
        "fullName": "Gerrit Cole",
        "link": "/api/v1/people/543037"
      },
      "splitSquad": false,
      "seriesNumber": 1
    },
    "home": {
      "team": {
        "id": 111,
        "name": "Boston Red Sox"
      },
      "probablePitcher": {
        "id": 656302,
        "fullName": "Brayan Bello"
      }
    }
  },
  "venue": {
    "id": 3,
    "name": "Fenway Park",
    "link": "/api/v1/venues/3"
  },
  "content": { "link": "/api/v1/game/748532/content" },
  "isTie": false,
  "gameNumber": 1,
  "doubleHeader": "N",
  "dayNight": "night",
  "description": "",
  "scheduledInnings": 9,
  "reverseHomeAwayStatus": false,
  "inningBreakLength": 120,
  "gamesInSeries": 3,
  "seriesGameNumber": 1,
  "seriesDescription": "Regular Season",
  "recordSource": "S",
  "ifNecessary": "N",
  "ifNecessaryDescription": "Normal Game"
}
```

**Key fields to extract:**
- `gamePk` — the universal game ID used in all subsequent calls
- `gameDate` — UTC timestamp; convert to ET for display
- `officialDate` — the calendar date
- `dayNight` — "day" | "night"
- `teams.away.team.id` and `teams.home.team.id` — team IDs for roster/stats calls
- `teams.away.probablePitcher.id` and same for home — pitcher IDs
- `venue.id` — for park factor lookup
- `status.abstractGameState` — "Preview" | "Live" | "Final"

**Lineups via schedule hydrate:**

When you add `lineups` to the hydrate parameter, each game object gains:
```json
{
  "lineups": {
    "awayPlayers": [
      { "id": 123456, "fullName": "...", "battingOrder": 100 }
    ],
    "homePlayers": [ ... ]
  }
}
```
`battingOrder` is encoded as multiples of 100 (100 = leadoff, 200 = second, etc.). Lineups only appear here once officially submitted — typically 60-90 minutes before first pitch. Before that, this key is absent or empty.

---

### 1.2 Lineup Data

**Primary method — schedule hydrate (see above).** This is the simplest approach.

**Secondary method — live feed:**
```
GET https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live
```

Note the `v1.1` — not `v1`. This endpoint returns the full live game state including confirmed lineups, current inning, pitch-by-pitch data, and box score.

The lineups live at:
```json
{
  "liveData": {
    "boxscore": {
      "teams": {
        "away": {
          "battingOrder": [592518, 665742, 543760, ...],
          "players": {
            "ID592518": {
              "person": { "id": 592518, "fullName": "..." },
              "jerseyNumber": "99",
              "position": { "code": "1", "name": "Pitcher", "type": "Pitcher", "abbreviation": "P" },
              "stats": { "batting": { ... }, "pitching": { ... } },
              "seasonStats": { "batting": { ... }, "pitching": { ... } },
              "gameStatus": { "isCurrentBatter": false, "isCurrentPitcher": false, "isOnBench": false }
            }
          }
        }
      }
    }
  }
}
```

**Boxscore endpoint (simpler, post-game):**
```
GET https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore
```

Returns finalized lineups and per-player game stats without the full live feed overhead.

**Linescore endpoint:**
```
GET https://statsapi.mlb.com/api/v1/game/{gamePk}/linescore
```

Returns inning-by-inning scoring, current inning, outs, runners on base.

---

### 1.3 Player Stats — Season Stats

**Individual player stats:**
```
GET https://statsapi.mlb.com/api/v1/people/{personId}/stats
  ?stats=season
  &season=2025
  &group=pitching
```

For batting:
```
GET https://statsapi.mlb.com/api/v1/people/{personId}/stats
  ?stats=season
  &season=2025
  &group=hitting
```

**Response structure:**
```json
{
  "stats": [
    {
      "type": { "displayName": "season" },
      "group": { "displayName": "pitching" },
      "splits": [
        {
          "season": "2025",
          "stat": {
            "gamesPlayed": 5,
            "gamesStarted": 5,
            "inningsPitched": "32.1",
            "wins": 3,
            "losses": 1,
            "era": "2.51",
            "whip": "0.99",
            "strikeOuts": 42,
            "baseOnBalls": 6,
            "hits": 24,
            "homeRuns": 3,
            "strikeoutsPer9Inn": "11.70",
            "walksPer9Inn": "1.67",
            "hitsPer9Inn": "6.68",
            "strikeoutWalkRatio": "7.00",
            "groundOutsToAirouts": "0.71",
            "pitchesPerInning": "15.2",
            "runsScoredPer9": "2.51",
            "battersFaced": 128,
            "outs": 97
          }
        }
      ]
    }
  ]
}
```

**Key pitching fields from MLB API:**
- `era` — Earned Run Average
- `strikeOuts` — total Ks
- `strikeoutsPer9Inn` — K/9
- `walksPer9Inn` — BB/9
- `whip` — WHIP
- `inningsPitched` — IP (string like "32.1")
- `gamesStarted` — starter confirmation

**Note:** The MLB API does not return FIP, xFIP, SIERA, or SwStr%. Those require FanGraphs or Baseball Savant.

**Key hitting fields from MLB API:**
- `avg` — batting average
- `obp` — on-base percentage
- `slg` — slugging percentage
- `ops` — OPS
- `strikeOuts` — total strikeouts
- `baseOnBalls` — walks
- `atBats`, `plateAppearances`
- `homeRuns`, `rbi`, `hits`
- `strikeoutsPer9Inn` is on the pitching side only — for batter K%, compute from `strikeOuts / plateAppearances`

**Season stats with splits (vs LHP/RHP):**
```
GET https://statsapi.mlb.com/api/v1/people/{personId}/stats
  ?stats=statSplits
  &season=2025
  &group=hitting
  &sitCodes=vl,vr
```

`sitCodes` values: `vl` = vs left-handed pitcher, `vr` = vs right-handed pitcher, `h` = home, `a` = away, `d` = day, `n` = night.

**Recent form (last N games):**
```
GET https://statsapi.mlb.com/api/v1/people/{personId}/stats
  ?stats=gameLog
  &season=2025
  &group=pitching
```

Returns a split per game started. Filter to last 3-5 for recent form.

---

### 1.4 Team Stats (for lineup strength, bullpen)

```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/stats
  ?stats=season
  &season=2025
  &group=hitting
```

Also useful for bullpen aggregate:
```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/stats
  ?stats=season
  &season=2025
  &group=pitching
```

**Roster endpoint (to enumerate all pitchers):**
```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/roster
  ?rosterType=active
  &season=2025
```

Returns `roster[]` array with `person.id`, `person.fullName`, `position.abbreviation` (P, C, 1B, etc.), `status.code`.

**40-man roster:**
```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/roster
  ?rosterType=40Man
```

---

### 1.5 Game Results / Box Scores (for grading picks)

**Box score (final stats, lineups, per-player):**
```
GET https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore
```

Top-level structure:
```json
{
  "teams": {
    "away": {
      "team": { "id": 147, "name": "New York Yankees" },
      "teamStats": {
        "batting": { "runs": 4, "hits": 9, "strikeOuts": 11, ... },
        "pitching": { "runs": 2, "hits": 6, "strikeOuts": 8, ... }
      },
      "players": {
        "ID543037": {
          "stats": {
            "pitching": {
              "inningsPitched": "6.0",
              "strikeOuts": 9,
              "earnedRuns": 2,
              "hits": 5,
              "baseOnBalls": 1
            }
          }
        }
      },
      "battingOrder": [...]
    },
    "home": { ... }
  },
  "info": [...],
  "officials": [
    {
      "official": { "id": 427, "fullName": "Angel Hernandez" },
      "officialType": "Home Plate"
    }
  ]
}
```

**Fields for grading:**
- `teams.away.teamStats.batting.runs` and `teams.home.teamStats.batting.runs` — final score for moneyline/run line grading
- Starting pitcher's `stats.pitching.strikeOuts` — for K prop grading
- First-inning runs (use linescore) — for NRFI grading
- `officials` array — home plate umpire ID for future lookup

**Linescore (inning-by-inning, first-inning runs):**
```
GET https://statsapi.mlb.com/api/v1/game/{gamePk}/linescore
```

```json
{
  "currentInning": 9,
  "currentInningOrdinal": "9th",
  "innings": [
    {
      "num": 1,
      "ordinalNum": "1st",
      "away": { "runs": 0, "hits": 1, "errors": 0 },
      "home": { "runs": 1, "hits": 2, "errors": 0 }
    },
    ...
  ],
  "teams": {
    "away": { "runs": 3, "hits": 8, "errors": 0 },
    "home": { "runs": 5, "hits": 10, "errors": 1 }
  }
}
```

For NRFI grading: `innings[0].away.runs + innings[0].home.runs == 0` = NRFI wins.

---

### 1.6 Roster / Injury (IL) Data

**Active roster with injury status:**
```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/roster
  ?rosterType=active
  &season=2025
```

Each roster entry includes:
```json
{
  "person": { "id": 123, "fullName": "..." },
  "jerseyNumber": "45",
  "position": { "code": "1", "abbreviation": "P" },
  "status": {
    "code": "A",
    "description": "Active"
  }
}
```

Status codes: `A` = Active, `D10` = 10-Day IL, `D15` = 15-Day IL, `D60` = 60-Day IL, `NRI` = Non-Roster Invitee, `RST` = Restricted.

**Injured list (transactions endpoint):**
```
GET https://statsapi.mlb.com/api/v1/transactions
  ?teamId={teamId}
  &startDate=YYYY-MM-DD
  &endDate=YYYY-MM-DD
```

Returns all roster transactions including IL placements and activations:
```json
{
  "transactions": [
    {
      "id": 12345,
      "person": { "id": 543037, "fullName": "Gerrit Cole" },
      "toTeam": { "id": 147 },
      "date": "2025-04-01",
      "effectiveDate": "2025-04-01",
      "resolutionDate": "...",
      "typeCode": "DL",
      "typeDesc": "Placed on 15-Day Injured List",
      "description": "Right elbow inflammation"
    }
  ]
}
```

**Practical IL check approach:** Pull the active roster and filter for `status.code` != `A`. Cross-check against the 40-man roster to identify anyone who has moved to IL.

---

### 1.7 Venue / Park Information

```
GET https://statsapi.mlb.com/api/v1/venues/{venueId}
  ?hydrate=location,fieldInfo
```

Returns:
```json
{
  "venues": [
    {
      "id": 3,
      "name": "Fenway Park",
      "link": "/api/v1/venues/3",
      "location": {
        "city": "Boston",
        "state": "Massachusetts",
        "stateAbbrev": "MA",
        "defaultCoordinates": {
          "latitude": 42.3467,
          "longitude": -71.0972
        },
        "elevation": 20
      },
      "fieldInfo": {
        "capacity": 37755,
        "turfType": "Grass",
        "roofType": "Open",
        "leftLine": 310,
        "leftCenter": 379,
        "center": 390,
        "rightCenter": 380,
        "rightLine": 302
      }
    }
  ]
}
```

`defaultCoordinates` feeds directly into the OpenWeatherMap API call for weather data.

---

### 1.8 Umpire Data (from box score)

The MLB API surfaces the home plate umpire in the box score `officials` array once the game has started or finished (see section 1.4). There is no pre-game umpire assignment endpoint in the public API — that data comes from Baseball Reference (see section 4).

---

## 2. FanGraphs

Base URL: `https://www.fangraphs.com`
No authentication required. Scraping-based. FanGraphs has both HTML leaderboard pages and CSV export endpoints.

---

### 2.1 Pitcher Leaderboard — CSV Export

**Season pitching leaderboard:**
```
https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=y&type=8&season=2025&season1=2025&ind=0&team=0&rost=0&age=0&filter=&players=0&export=y
```

The `export=y` parameter returns raw CSV. `type=8` is the "dashboard" column set. Change `type` to access different column groups:
- `type=8` — Dashboard (ERA, FIP, xFIP, K%, BB%, BABIP, LOB%, HR/FB)
- `type=36` — Advanced (SIERA, kwERA, FIP-, xFIP-)
- `type=24` — Plate Discipline (O-Swing%, Z-Swing%, SwStr%, F-Strike%)
- `type=4` — Standard (W, L, ERA, G, GS, IP, H, R, ER, HR, BB, SO)

**Key CSV columns returned (type=8):**
```
Name, Team, W, L, ERA, G, GS, IP, K/9, BB/9, HR/9, BABIP, LOB%, GB%, HR/FB, FIP, xFIP, WAR
```

**Key CSV columns (type=36 advanced):**
```
Name, Team, SIERA, kwERA, FIP-, xFIP-, ERA-
```

**Key CSV columns (type=24 plate discipline):**
```
Name, Team, O-Swing%, Z-Swing%, Swing%, O-Contact%, Z-Contact%, Contact%, Zone%, F-Strike%, SwStr%
```

**Qualifying pitchers only:** `qual=y` filters to pitchers meeting the innings threshold. Use `qual=0` for all pitchers (includes openers and spot starters, but adds noise).

**Specific pitcher by ID:**
```
https://www.fangraphs.com/statss.aspx?playerid={fangraphsId}&position=P
```

FanGraphs player IDs do not match MLB API player IDs. You need a cross-reference. The most reliable approach is to match by `Name` + `Team` from the leaderboard CSV.

**Batter leaderboard — plate discipline:**
```
https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=y&type=23&season=2025&season1=2025&ind=0&export=y
```

`type=23` returns: `K%, BB%, LD%, GB%, FB%, IFFB%, HR/FB, Pull%, Cent%, Oppo%`

**Park Factors:**
```
https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season=2025
```

This is an HTML page, not a CSV. The table has columns:
```
Team, Basic 1yr, Basic 3yr, 1B, 2B, 3B, HR, BB, K, UIBB
```

All values are indexed to 100. Values above 100 favor that event at that park.

**Alternative park factors CSV (simpler):**
```
https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=0&type=8&season=2025&season1=2025&ind=0&team=0&rost=0&age=0&filter=&players=0&page=1_200
```

FanGraphs park factors by team can also be embedded in the team stats pages at:
```
https://www.fangraphs.com/depthcharts.aspx?position=Standings
```

**Practical scraping note:** FanGraphs uses ASP.NET and returns gzip content. Use `requests` with `headers={"Accept-Encoding": "gzip"}` and `response.content` decoded with `pandas.read_csv(io.StringIO(text))`. The CSV endpoint often works directly without JavaScript rendering.

---

### 2.2 FanGraphs Player Search (for ID cross-reference)

```
https://www.fangraphs.com/players.aspx?lastname={lastName}
```

Or use the search API:
```
https://www.fangraphs.com/api/search/players?q={name}&sport=0
```

Returns JSON with `playerid` (FanGraphs ID), `name`, `team`, `pos`.

---

## 3. Baseball Savant (Statcast)

Base URL: `https://baseballsavant.mlb.com`
No authentication required. Mix of CSV download endpoints and JSON APIs.

---

### 3.1 Statcast Leaderboard — Expected Stats (xERA, xBA, xSLG)

**Pitcher expected stats leaderboard:**
```
https://baseballsavant.mlb.com/leaderboard/expected_statistics
  ?type=pitcher
  &year=2025
  &position=
  &team=
  &min=q
  &csv=true
```

`csv=true` returns raw CSV. This is the most important endpoint for the bot.

**Key columns:**
```
last_name, first_name, player_id, year, pa, bip, ba, xba, slg, xslg, woba, xwoba, xwobacon, wobacon, era, xera, exit_velocity_avg, launch_angle_avg, barrel_batted_rate, k_percent, bb_percent
```

- `player_id` here is the MLB player ID (matches `statsapi.mlb.com`)
- `xera` — expected ERA based on contact quality
- `xba` / `xslg` / `xwoba` — expected stats
- `barrel_batted_rate` — barrel rate allowed
- `k_percent` / `bb_percent` — K% and BB% (0-100 scale, not decimal)

**Batter expected stats:**
```
https://baseballsavant.mlb.com/leaderboard/expected_statistics
  ?type=batter
  &year=2025
  &position=
  &team=
  &min=q
  &csv=true
```

---

### 3.2 Statcast Pitch-Level Data

**Pitcher pitch arsenal (average velo, spin rate by pitch type):**
```
https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats
  ?type=pitcher
  &pitchType=
  &year=2025
  &team=
  &min=10
  &csv=true
```

**Pitcher whiff rate leaderboard:**
```
https://baseballsavant.mlb.com/leaderboard/spin-direction-comparison
  ?year=2025&csv=true
```

**Custom Statcast query (the most flexible endpoint):**
```
https://baseballsavant.mlb.com/statcast_search/csv
  ?all=true
  &hfPT=
  &hfAB=
  &hfBBT=
  &hfPR=
  &hfZ=
  &stadium=
  &hfBBL=
  &hfNewZones=
  &hfGT=R%7C
  &hfC=
  &hfSea=2025%7C
  &hfSit=
  &player_type=pitcher
  &hfOuts=
  &opponent=
  &pitcher_throws=
  &batter_stands=
  &hfSA=
  &game_date_gt=
  &game_date_lt=
  &hfInfield=
  &team=
  &position=
  &hfRO=
  &home_road=
  &hfFlag=
  &hfPull=
  &metric_1=
  &hfInn=
  &min_pitches=0
  &min_results=0
  &group_by=name
  &sort_col=pitches
  &player_event_sort=api_p_release_speed
  &sort_order=desc
  &min_pas=0
  &type=details
  &player_id={mlbPlayerId}
```

This returns every pitch thrown by a specific pitcher in the filtered range, with columns including:
```
pitch_type, release_speed, release_spin_rate, pfx_x, pfx_z, plate_x, plate_z,
description, zone, type (B/S/X), events, estimated_ba_using_speedangle,
estimated_woba_using_speedangle, launch_speed, launch_angle, hit_distance_sc,
woba_value, babip_value
```

**For the bot's use case, the leaderboard CSV endpoints (section 3.1) are preferable** — they return season aggregates rather than pitch-level rows, which is all you need for the prediction models.

---

### 3.3 Sprint Speed / Outs Above Average (less relevant, noted for completeness)

```
https://baseballsavant.mlb.com/leaderboard/sprint_speed?year=2025&position=&team=&min=10&csv=true
```

---

### 3.4 Baseball Savant Player Page (for spot checks)

```
https://baseballsavant.mlb.com/savant-player/{firstName}-{lastName}-{mlbPlayerId}
```

Example: `https://baseballsavant.mlb.com/savant-player/gerrit-cole-543037`

The page contains embedded JSON in a `<script>` tag with the player's full Statcast profile if scraping HTML is needed as a fallback.

---

## 4. Baseball Reference — Umpire Data

Base URL: `https://www.baseball-reference.com`
No authentication. HTML scraping required. Baseball Reference blocks aggressive scrapers — add delays and a realistic User-Agent header.

---

### 4.1 Umpire Index

```
https://www.baseball-reference.com/umpires/
```

Lists all umpires with links to individual pages.

**Individual umpire page:**
```
https://www.baseball-reference.com/umpires/{umpireCode}.shtml
```

Example: `https://www.baseball-reference.com/umpires/hernana001.shtml`

Contains tables for: Year-by-year games behind the plate, K rate, BB rate, runs per game, and other tendencies.

---

### 4.2 Umpire Scorecards (Third-Party — Umpire Scorecards Site)

Baseball Reference itself has limited umpire tendency data. The community standard for umpire strike zone analysis is the **Umpire Scorecards** project:

```
https://umpscorecards.com/umpires/
```

Individual umpire profile:
```
https://umpscorecards.com/umpires/{name}/
```

Example: `https://umpscorecards.com/umpires/angel-hernandez/`

Metrics available:
- Accuracy % (calls made correctly)
- Consistency %
- Favor (run impact per game — positive favors home team)
- K+ (extra strikeouts generated vs expected)
- K- (strikeouts taken away)
- Pitches called above/below strike zone (bias direction)

**Game-level scorecard:**
```
https://umpscorecards.com/games/{gameDate}/{awayTeam}-vs-{homeTeam}/
```

There is no public CSV export from Umpire Scorecards, but individual umpire pages have embedded JSON data in `<script type="application/json">` tags that can be parsed without a full HTML scrape.

---

### 4.3 Pre-Game Umpire Assignment

Umpire assignments are published by MLB and aggregated on:
```
https://www.rotowire.com/baseball/daily-lineups.php
```

Rotowire's lineup page lists the home plate umpire alongside the confirmed lineups. This is typically the most reliable pre-game source for umpire assignment, available by approximately 5-6 hours before first pitch.

**Alternative:** The MLB Stats API sometimes includes umpire assignment in the live feed (`/api/v1.1/game/{gamePk}/feed/live`) under `liveData.boxscore.officials` once the umpire has checked in, but this is typically only available day-of.

---

## 5. The Odds API

Base URL: `https://api.the-odds-api.com/v4`
Requires API key. Free tier: 500 requests/month. Paid tiers available.
Documentation: `https://the-odds-api.com/liveapi/guides/v4/`

---

### 5.1 Available Sports / Markets

**List all available sports:**
```
GET https://api.the-odds-api.com/v4/sports
  ?apiKey={YOUR_KEY}
```

MLB sport key: `baseball_mlb`

---

### 5.2 Moneylines, Run Lines, and Totals

```
GET https://api.the-odds-api.com/v4/sports/baseball_mlb/odds
  ?apiKey={YOUR_KEY}
  &regions=us
  &markets=h2h,spreads,totals
  &oddsFormat=american
  &dateFormat=iso
```

**Parameters:**
- `regions` — `us` (DraftKings, FanDuel, BetMGM, etc.), `us2`, `uk`, `eu`, `au`
- `markets` — `h2h` = moneyline, `spreads` = run line (-1.5/+1.5), `totals` = over/under runs
- `oddsFormat` — `american` | `decimal` | `fractional`

**Response structure:**
```json
[
  {
    "id": "a1b2c3d4e5f6...",
    "sport_key": "baseball_mlb",
    "sport_title": "MLB",
    "commence_time": "2025-04-01T23:10:00Z",
    "home_team": "Boston Red Sox",
    "away_team": "New York Yankees",
    "bookmakers": [
      {
        "key": "draftkings",
        "title": "DraftKings",
        "last_update": "2025-04-01T20:15:00Z",
        "markets": [
          {
            "key": "h2h",
            "last_update": "...",
            "outcomes": [
              { "name": "New York Yankees", "price": -128 },
              { "name": "Boston Red Sox", "price": +108 }
            ]
          },
          {
            "key": "spreads",
            "outcomes": [
              { "name": "New York Yankees", "price": +145, "point": -1.5 },
              { "name": "Boston Red Sox", "price": -165, "point": 1.5 }
            ]
          },
          {
            "key": "totals",
            "outcomes": [
              { "name": "Over", "price": -110, "point": 8.5 },
              { "name": "Under", "price": -110, "point": 8.5 }
            ]
          }
        ]
      }
    ]
  }
]
```

**Note on team name matching:** The Odds API uses full team names ("New York Yankees") while the MLB Stats API uses the same. Matching is straightforward, but watch for edge cases like "Athletics" (no city prefix in some books after the Oakland relocation).

---

### 5.3 Pitcher Strikeout Props

Player props are in a separate endpoint:
```
GET https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eventId}/odds
  ?apiKey={YOUR_KEY}
  &regions=us
  &markets=pitcher_strikeouts
  &oddsFormat=american
```

You need the `eventId` — this is the Odds API's own game ID, returned in the game list response (the `id` field in section 5.2 response).

**Response structure for player props:**
```json
{
  "id": "a1b2c3...",
  "sport_key": "baseball_mlb",
  "home_team": "Boston Red Sox",
  "away_team": "New York Yankees",
  "bookmakers": [
    {
      "key": "draftkings",
      "markets": [
        {
          "key": "pitcher_strikeouts",
          "outcomes": [
            {
              "name": "Over",
              "description": "Gerrit Cole",
              "price": -115,
              "point": 7.5
            },
            {
              "name": "Under",
              "description": "Gerrit Cole",
              "price": -105,
              "point": 7.5
            }
          ]
        }
      ]
    }
  ]
}
```

**Available MLB player prop market keys** (availability varies by bookmaker):
- `pitcher_strikeouts` — starting pitcher K over/under
- `batter_home_runs` — HR yes/no
- `batter_hits` — hits over/under
- `batter_rbis` — RBI over/under
- `batter_runs_scored`
- `batter_total_bases`

---

### 5.4 NRFI / YRFI Odds

NRFI is an alternate market, not a standard market key. Availability depends on bookmaker and fluctuates:

```
GET https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eventId}/odds
  ?apiKey={YOUR_KEY}
  &regions=us
  &markets=team_totals,1st_1_innings
  &oddsFormat=american
```

Market keys to try:
- `1st_1_innings` — NRFI/YRFI (first inning runs scored, yes/no)
- `team_totals` — first-5-innings team totals (related but not identical)

**Important caveat:** NRFI market availability is inconsistent. Not all bookmakers offer it, and The Odds API only returns markets that at least one bookmaker in the selected region has posted. The `pitcher_strikeouts` and `1st_1_innings` markets may require a paid tier plan — verify against your subscription level.

**Request usage tracking:** The Odds API returns headers on every response:
```
x-requests-remaining: 487
x-requests-used: 13
x-requests-last: 1
```

Budget your 500 free monthly requests carefully. A single `/odds` call with multiple markets counts as one request per market per event in some configurations — check the docs for your plan's counting rules.

---

## 6. ID Cross-Reference Strategy

The MLB API uses its own integer player IDs. FanGraphs uses different integer IDs. Baseball Savant uses MLB API IDs (which simplifies things). The Odds API uses team/player names (strings).

**Recommended approach:**

1. Treat the MLB Stats API player ID as the canonical ID throughout the system.
2. Baseball Savant CSV exports include `player_id` that matches MLB API — no cross-reference needed.
3. FanGraphs leaderboard CSVs include `Name` and `Team` — match on normalized name + team abbreviation.
4. Build a local cache table `player_id_map (mlb_id, fangraphs_id, name, team)` populated on first run each season.

**FanGraphs ID lookup via their search API:**
```
https://www.fangraphs.com/api/search/players?q={lastName}&sport=0
```

Returns `playerid` (FanGraphs) alongside `name`. Match to MLB API's `fullName` with fuzzy matching for accented characters and name variations.

---

## 7. Key Hydrate Values for MLB Stats API

The `hydrate` parameter accepts these values (comma-separated, mix and match):

| Hydrate Value | What It Adds |
|---|---|
| `probablePitcher` | Probable pitcher object on each team in schedule |
| `lineups` | Confirmed batting order arrays |
| `team` | Full team object (name, abbreviation, venue) |
| `venue` | Full venue object with coordinates |
| `broadcasts` | TV/radio broadcast details |
| `weather` | Weather conditions at game time (sometimes populated) |
| `linescore` | Live score by inning |
| `decisions` | Win/loss/save pitcher decisions |
| `person` | Full person details on roster entries |
| `stats` | Season stats embedded in roster entries |

---

## 8. Rate Limits and Caching Strategy

| Source | Rate Limit | Recommended Cache TTL |
|---|---|---|
| MLB Stats API | ~500 req/min (unofficial) | Schedule: 15 min; Stats: 4 hrs; Boxscore: permanent once Final |
| FanGraphs CSV | No official limit — be polite | Season leaderboards: 24 hrs |
| Baseball Savant CSV | No official limit — be polite | Season leaderboards: 24 hrs |
| The Odds API | 500 req/month (free tier) | Lines: 30 min; Props: 30 min |
| Umpire Scorecards | No official limit | Season data: 24 hrs |
| Baseball Reference | Aggressive blocking at ~10 req/min | Umpire data: 24 hrs |

**Practical tip:** Fetch FanGraphs and Savant leaderboards once per day at pipeline start and store in-memory (or SQLite). All pitcher/batter lookups within the session read from the local cache, not the network.

---

## 9. Summary — Primary Endpoints Per Module

| Module | Primary Endpoint |
|---|---|
| `schedule.py` | `GET /api/v1/schedule?sportId=1&date={date}&hydrate=probablePitcher,lineups,venue,team` |
| `lineups.py` | Schedule hydrate (pre-game) + `/api/v1.1/game/{gamePk}/feed/live` (confirmed) |
| `pitcher_stats.py` | `/api/v1/people/{id}/stats?stats=season&group=pitching` + FanGraphs type=8,36,24 + Savant expected_statistics |
| `batter_stats.py` | `/api/v1/people/{id}/stats?stats=season&group=hitting` + FanGraphs type=23 + Savant expected_statistics |
| `bullpen.py` | `/api/v1/teams/{teamId}/roster?rosterType=active` + per-pitcher season stats |
| `park_factors.py` | FanGraphs `/guts.aspx?type=pf` + `/api/v1/venues/{venueId}?hydrate=location,fieldInfo` |
| `umpires.py` | Box score officials + Umpire Scorecards individual pages |
| `injuries.py` | `/api/v1/teams/{teamId}/roster?rosterType=active` (status.code filter) + transactions |
| `odds.py` | `/v4/sports/baseball_mlb/odds?markets=h2h,spreads,totals` + per-event props |
| `results_tracker.py` | `/api/v1/game/{gamePk}/boxscore` + `/api/v1/game/{gamePk}/linescore` |

---

## Citations

[1] MLB Stats API. "Unofficial MLB Stats API Documentation." GitHub/ZhangJiupeng, multiple community forks. `https://statsapi.mlb.com/api/v1/`

[2] FanGraphs. "Leaderboards — Pitching." FanGraphs, 2025. `https://www.fangraphs.com/leaders.aspx`

[3] Baseball Savant. "Expected Statistics Leaderboard." MLB/Statcast, 2025. `https://baseballsavant.mlb.com/leaderboard/expected_statistics`

[4] The Odds API. "V4 API Documentation." The Odds API, 2025. `https://the-odds-api.com/liveapi/guides/v4/`

[5] Umpire Scorecards. "Umpire Profiles and Scorecards." Community project. `https://umpscorecards.com`

[6] Baseball Reference. "Umpire Register." Sports Reference LLC, 2025. `https://www.baseball-reference.com/umpires/`
