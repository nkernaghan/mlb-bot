---
name: K props switched to DraftKings via BettingPros
description: Replaced PrizePicks/Underdog with real DraftKings strikeout lines scraped from BettingPros API — includes juice for alt line logic
type: project
---

On 2026-04-07, replaced PrizePicks and Underdog Fantasy as K prop sources with DraftKings lines via BettingPros free API.

**Why:** PrizePicks had generic lines (often 4.5 for everyone) producing fake edges — went 0-5 on K props over the weekend. Underdog Fantasy is also a DFS platform, not a real sportsbook. User bets on DraftKings so needs DK-specific lines.

**How to apply:** 
- `fetch_draftkings_k_props()` in odds.py calls `api.bettingpros.com/v3/props` with `market_id=285` (pitcher Ks) and `book_id=12` (DraftKings)
- Only real sportsbooks (draftkings, fanduel, betmgm, caesars, pointsbet, betrivers) qualify for market blending in strikeout_predictor.py
- Alt line logic: when over juice is worse than -110, recommends flat lower number (e.g., "OVER 6 Ks" instead of "OVER 6.5 at -124")
- No auth needed, plain requests.get()
