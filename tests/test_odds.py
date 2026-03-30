from modules.data.odds import parse_game_odds, parse_k_props, parse_nrfi_odds, american_to_implied


def test_american_to_implied_favorite():
    assert abs(american_to_implied(-150) - 0.6) < 0.01


def test_american_to_implied_underdog():
    assert abs(american_to_implied(150) - 0.4) < 0.01


def test_parse_game_odds():
    raw_bookmaker = {
        "key": "draftkings",
        "title": "DraftKings",
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "New York Yankees", "price": -128},
                    {"name": "Boston Red Sox", "price": 108},
                ],
            },
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "New York Yankees", "price": 145, "point": -1.5},
                    {"name": "Boston Red Sox", "price": -165, "point": 1.5},
                ],
            },
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": -110, "point": 8.5},
                    {"name": "Under", "price": -110, "point": 8.5},
                ],
            },
        ],
    }
    odds = parse_game_odds(raw_bookmaker, "New York Yankees", "Boston Red Sox")
    assert odds["away_ml"] == -128
    assert odds["home_ml"] == 108
    assert odds["run_line_spread"] == -1.5
    assert odds["total"] == 8.5


def test_parse_k_props():
    raw_bookmaker = {
        "key": "draftkings",
        "markets": [
            {
                "key": "pitcher_strikeouts",
                "outcomes": [
                    {"name": "Over", "description": "Gerrit Cole", "price": -115, "point": 7.5},
                    {"name": "Under", "description": "Gerrit Cole", "price": -105, "point": 7.5},
                ],
            },
        ],
    }
    props = parse_k_props(raw_bookmaker)
    assert len(props) == 1
    assert props[0]["pitcher_name"] == "Gerrit Cole"
    assert props[0]["line"] == 7.5
    assert props[0]["over_price"] == -115


def test_parse_nrfi_odds():
    raw_bookmaker = {
        "key": "draftkings",
        "markets": [
            {
                "key": "1st_1_innings",
                "outcomes": [
                    {"name": "Under", "price": -130, "point": 0.5},
                    {"name": "Over", "price": 110, "point": 0.5},
                ],
            },
        ],
    }
    nrfi = parse_nrfi_odds(raw_bookmaker)
    assert nrfi["nrfi_price"] == -130
    assert nrfi["yrfi_price"] == 110
