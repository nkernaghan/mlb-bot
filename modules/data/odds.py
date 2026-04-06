import re
import requests
from datetime import datetime, timezone
from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY, ODDS_REGIONS, ODDS_FORMAT
from modules.database import get_connection

# ---------------------------------------------------------------------------
# ESPN Core API — used as a free fallback when the-odds-api quota is exhausted
# ---------------------------------------------------------------------------
_ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
)
_ESPN_ODDS_TPL = (
    "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
    "/events/{event_id}/competitions/{event_id}/odds"
)
_ESPN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Map ESPN displayName → MLB Stats API name for the handful of mismatches.
# Every other team name is identical across both APIs.
_ESPN_NAME_MAP: dict[str, str] = {
    "Oakland Athletics": "Athletics",
    "Las Vegas Athletics": "Athletics",
}


def _normalise_espn_name(espn_name: str) -> str:
    """Return the MLB Stats API team name for a given ESPN displayName."""
    return _ESPN_NAME_MAP.get(espn_name, espn_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def american_to_implied(american_odds: float) -> float:
    """Convert American odds to implied probability (0-1)."""
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        return 100 / (american_odds + 100)


def _parse_american(value: object) -> float | None:
    """Parse an American-odds value that may arrive as int, float, or string.

    ESPN returns run-line prices as strings like ``'+123'`` or ``'-149'``.
    Moneylines arrive as plain integers.  Returns ``None`` when the value is
    missing or cannot be converted.
    """
    if value is None:
        return None
    try:
        return float(str(value).replace("+", ""))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Fallback scraper — ESPN Core API
# ---------------------------------------------------------------------------


def fetch_fallback_odds() -> list[dict]:
    """Scrape MLB moneylines, run lines, and totals from ESPN's public API.

    This is a free fallback used when the-odds-api quota is exhausted.  The
    function returns a list of event dicts in the **exact same schema** as
    ``fetch_game_odds()`` so the rest of the pipeline needs no changes::

        [
            {
                "id": "<espn_event_id>",
                "home_team": "Kansas City Royals",
                "away_team": "Minnesota Twins",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {"key": "h2h",      "outcomes": [...]},
                            {"key": "spreads",  "outcomes": [...]},
                            {"key": "totals",   "outcomes": [...]},
                        ],
                    }
                ],
            },
            ...
        ]

    Returns an empty list if any network or parsing error occurs — callers
    should treat an empty return as "no odds available" and continue.
    """
    try:
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        sb_resp = requests.get(
            _ESPN_SCOREBOARD,
            params={"dates": today, "limit": 30},
            headers=_ESPN_HEADERS,
            timeout=15,
        )
        sb_resp.raise_for_status()
        scoreboard = sb_resp.json()
    except Exception as exc:
        print(f"  Fallback scraper: ESPN scoreboard request failed — {exc}")
        return []

    events_out: list[dict] = []

    for event in scoreboard.get("events", []):
        event_id = event.get("id", "")
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])

        home_team = ""
        away_team = ""
        for c in competitors:
            team_name = _normalise_espn_name(
                c.get("team", {}).get("displayName", "")
            )
            if c.get("homeAway") == "home":
                home_team = team_name
            else:
                away_team = team_name

        if not home_team or not away_team:
            continue

        bookmakers = _fetch_espn_event_odds(event_id, home_team, away_team)

        events_out.append(
            {
                "id": event_id,
                "home_team": home_team,
                "away_team": away_team,
                "bookmakers": bookmakers,
            }
        )

    return events_out


def _fetch_espn_event_odds(
    event_id: str, home_team: str, away_team: str
) -> list[dict]:
    """Fetch and reshape odds for one ESPN event into the-odds-api bookmaker format."""
    try:
        url = _ESPN_ODDS_TPL.format(event_id=event_id)
        resp = requests.get(url, headers=_ESPN_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"  Fallback scraper: odds request failed for event {event_id} — {exc}")
        return []

    bookmakers: list[dict] = []

    for item in data.get("items", []):
        provider = item.get("provider", {})
        provider_name: str = provider.get("name", "unknown")
        book_key = provider_name.lower().replace(" ", "").replace(".", "")

        home_ml = _parse_american(item.get("homeTeamOdds", {}).get("moneyLine"))
        away_ml = _parse_american(item.get("awayTeamOdds", {}).get("moneyLine"))

        # Run line — ESPN `spread` is signed from the home-team perspective
        # (negative when home is favoured).  We expose the away-team point
        # in ``spreads`` outcomes to match the-odds-api convention.
        raw_spread = item.get("spread")  # home-team RL, e.g. -1.5
        home_rl_point: float | None = None
        away_rl_point: float | None = None
        if raw_spread is not None:
            try:
                home_rl_point = float(raw_spread)
                away_rl_point = -home_rl_point
            except (ValueError, TypeError):
                pass

        # Run-line prices come from current pointSpread odds
        home_odds_block = item.get("homeTeamOdds", {})
        away_odds_block = item.get("awayTeamOdds", {})
        home_rl_price = _parse_american(
            home_odds_block.get("current", {}).get("spread", {}).get("american")
        )
        away_rl_price = _parse_american(
            away_odds_block.get("current", {}).get("spread", {}).get("american")
        )

        # Totals
        total = item.get("overUnder")
        over_price = _parse_american(item.get("overOdds"))
        under_price = _parse_american(item.get("underOdds"))

        markets: list[dict] = []

        # h2h market
        if home_ml is not None and away_ml is not None:
            markets.append(
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": home_team, "price": home_ml},
                        {"name": away_team, "price": away_ml},
                    ],
                }
            )

        # spreads market
        if home_rl_point is not None and away_rl_point is not None:
            markets.append(
                {
                    "key": "spreads",
                    "outcomes": [
                        {
                            "name": home_team,
                            "price": home_rl_price,
                            "point": home_rl_point,
                        },
                        {
                            "name": away_team,
                            "price": away_rl_price,
                            "point": away_rl_point,
                        },
                    ],
                }
            )

        # totals market
        if total is not None:
            markets.append(
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over",  "price": over_price,  "point": total},
                        {"name": "Under", "price": under_price, "point": total},
                    ],
                }
            )

        if markets:
            bookmakers.append(
                {
                    "key": book_key,
                    "title": provider_name,
                    "markets": markets,
                }
            )

    return bookmakers


# ---------------------------------------------------------------------------
# Fallback props — returns empty; K props / NRFI not available for free
# ---------------------------------------------------------------------------


def fetch_fallback_props(home_team: str, away_team: str) -> dict:
    """Attempt to fetch K-prop and NRFI odds from a free source.

    Currently returns an empty dict because no reliable free JSON endpoint
    exposes pitcher strikeout or first-inning totals.  Game odds (moneyline,
    run line, totals) are available via ``fetch_fallback_odds()``.

    The signature matches the shape that ``fetch_event_props()`` returns so
    callers can use it as a drop-in fallback without code changes.
    """
    return {}


# ---------------------------------------------------------------------------
# Primary API functions (with fallback wired in)
# ---------------------------------------------------------------------------


def fetch_game_odds() -> list[dict]:
    """Fetch moneylines, run lines, and totals for all MLB games.

    Tries the-odds-api first.  On a 401 (quota exhausted) or any other
    request error, falls back to the ESPN public odds scraper.
    """
    if not ODDS_API_KEY:
        print("  No ODDS_API_KEY set — using fallback scraper...")
        return fetch_fallback_odds()

    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": "h2h,spreads,totals",
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()

        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  Odds API requests remaining: {remaining}")

        return resp.json()

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(
            f"  Odds API returned HTTP {status} — "
            "using fallback scraper..."
        )
        return fetch_fallback_odds()

    except Exception as exc:
        print(f"  Odds API unavailable ({exc}) — using fallback scraper...")
        return fetch_fallback_odds()


def fetch_event_props(
    event_id: str,
    markets: str = "pitcher_strikeouts,totals_1st_1_innings",
) -> dict:
    """Fetch player props and NRFI odds for a specific event.

    Falls back to ``fetch_fallback_props()`` (returns empty dict) when the
    API key is missing or the request fails.
    """
    if not ODDS_API_KEY:
        return fetch_fallback_props("", "")

    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(
            f"    Props API returned HTTP {status} for event {event_id} — "
            "skipping props"
        )
        return fetch_fallback_props("", "")

    except Exception as exc:
        print(f"    Props API unavailable ({exc}) — skipping props")
        return fetch_fallback_props("", "")


# ---------------------------------------------------------------------------
# Parsing helpers (unchanged)
# ---------------------------------------------------------------------------


def parse_game_odds(bookmaker: dict, away_team: str, home_team: str) -> dict:
    """Parse a single bookmaker's odds for a game."""
    result = {
        "bookmaker": bookmaker["key"],
        "home_ml": None, "away_ml": None,
        "run_line_spread": None, "run_line_home_price": None,
        "run_line_away_price": None,
        "total": None, "over_price": None, "under_price": None,
    }

    for market in bookmaker.get("markets", []):
        if market["key"] == "h2h":
            for outcome in market["outcomes"]:
                if outcome["name"] == away_team:
                    result["away_ml"] = outcome["price"]
                elif outcome["name"] == home_team:
                    result["home_ml"] = outcome["price"]

        elif market["key"] == "spreads":
            for outcome in market["outcomes"]:
                if outcome["name"] == away_team:
                    result["run_line_spread"] = outcome.get("point")
                    result["run_line_away_price"] = outcome["price"]
                elif outcome["name"] == home_team:
                    result["run_line_home_price"] = outcome["price"]

        elif market["key"] == "totals":
            for outcome in market["outcomes"]:
                if outcome["name"] == "Over":
                    result["total"] = outcome.get("point")
                    result["over_price"] = outcome["price"]
                elif outcome["name"] == "Under":
                    result["under_price"] = outcome["price"]

    return result


def parse_k_props(bookmaker: dict) -> list[dict]:
    """Parse pitcher strikeout props from a bookmaker."""
    props: list[dict] = []
    for market in bookmaker.get("markets", []):
        if market["key"] != "pitcher_strikeouts":
            continue
        pitchers: dict[str, dict] = {}
        for outcome in market["outcomes"]:
            name = outcome.get("description", "")
            if name not in pitchers:
                pitchers[name] = {
                    "pitcher_name": name,
                    "line": outcome.get("point"),
                    "over_price": None,
                    "under_price": None,
                    "bookmaker": bookmaker["key"],
                }
            if outcome["name"] == "Over":
                pitchers[name]["over_price"] = outcome["price"]
                pitchers[name]["line"] = outcome.get("point")
            elif outcome["name"] == "Under":
                pitchers[name]["under_price"] = outcome["price"]
        props.extend(pitchers.values())
    return props


def parse_nrfi_odds(bookmaker: dict) -> dict | None:
    """Parse NRFI/YRFI odds from a bookmaker."""
    for market in bookmaker.get("markets", []):
        if market["key"] in ("1st_1_innings", "totals_1st_1_innings"):
            result: dict = {
                "nrfi_price": None,
                "yrfi_price": None,
                "bookmaker": bookmaker["key"],
            }
            for outcome in market["outcomes"]:
                if outcome["name"] == "Under":
                    result["nrfi_price"] = outcome["price"]
                elif outcome["name"] == "Over":
                    result["yrfi_price"] = outcome["price"]
            return result
    return None


def get_consensus_odds(all_bookmaker_odds: list[dict]) -> dict | None:
    """Average odds across bookmakers for consensus line."""
    if not all_bookmaker_odds:
        return None

    fields = ["home_ml", "away_ml", "total"]
    consensus: dict = {}
    for field in fields:
        values = [o[field] for o in all_bookmaker_odds if o.get(field) is not None]
        consensus[field] = round(sum(values) / len(values)) if values else None

    spread_values = [
        o["run_line_spread"]
        for o in all_bookmaker_odds
        if o.get("run_line_spread") is not None
    ]
    consensus["run_line_spread"] = spread_values[0] if spread_values else None

    for field in ["run_line_home_price", "run_line_away_price"]:
        values = [o[field] for o in all_bookmaker_odds if o.get(field) is not None]
        consensus[field] = round(sum(values) / len(values)) if values else None

    rlm = detect_line_divergence(all_bookmaker_odds)
    if rlm:
        consensus["rlm_signal"] = rlm

    return consensus


def detect_line_divergence(all_bookmaker_odds: list[dict]) -> dict | None:
    """Detect reverse line movement by comparing sharp vs casual book implied probabilities.

    Sharp books (DraftKings, FanDuel, BetOnline) have tighter lines.
    If sharp books favour one side more than casual books, that's a signal.
    """
    from config import SHARP_BOOKS, CASUAL_BOOKS

    sharp_home: list[float] = []
    casual_home: list[float] = []

    for odds in all_bookmaker_odds:
        bk = odds.get("bookmaker", "").lower()
        home_ml = odds.get("home_ml")
        if home_ml is None:
            continue

        implied = american_to_implied(home_ml)
        if bk in SHARP_BOOKS:
            sharp_home.append(implied)
        elif bk in CASUAL_BOOKS:
            casual_home.append(implied)

    if not sharp_home or not casual_home:
        return None

    sharp_avg = sum(sharp_home) / len(sharp_home)
    casual_avg = sum(casual_home) / len(casual_home)
    divergence = round((sharp_avg - casual_avg) * 100, 1)

    if abs(divergence) > 2.0:
        return {
            "sharp_home_implied": round(sharp_avg, 3),
            "casual_home_implied": round(casual_avg, 3),
            "divergence": divergence,
            "direction": "home" if divergence > 0 else "away",
        }
    return None


def save_odds(game_pk: int, odds_list: list[dict]) -> None:
    """Save odds snapshots to database."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    for odds in odds_list:
        conn.execute(
            """
            INSERT INTO odds (game_pk, fetched_at, home_ml, away_ml, run_line_spread,
                run_line_home_price, run_line_away_price, total, over_price, under_price, bookmaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_pk, now,
                odds["home_ml"], odds["away_ml"],
                odds["run_line_spread"], odds["run_line_home_price"],
                odds["run_line_away_price"], odds["total"],
                odds["over_price"], odds["under_price"],
                odds["bookmaker"],
            ),
        )
    conn.commit()
    conn.close()
