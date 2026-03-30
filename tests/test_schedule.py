import json
from unittest.mock import patch, MagicMock
from modules.data.schedule import fetch_games, parse_game


def make_mock_game(game_pk=748532, home="Boston Red Sox", away="New York Yankees",
                   home_id=111, away_id=147, venue="Fenway Park", venue_id=3,
                   home_pitcher_id=656302, home_pitcher="Brayan Bello",
                   away_pitcher_id=543037, away_pitcher="Gerrit Cole",
                   day_night="night", status="Preview"):
    return {
        "gamePk": game_pk,
        "gameDate": "2026-04-01T23:10:00Z",
        "officialDate": "2026-04-01",
        "dayNight": day_night,
        "status": {"abstractGameState": status},
        "teams": {
            "home": {
                "team": {"id": home_id, "name": home},
                "probablePitcher": {"id": home_pitcher_id, "fullName": home_pitcher},
            },
            "away": {
                "team": {"id": away_id, "name": away},
                "probablePitcher": {"id": away_pitcher_id, "fullName": away_pitcher},
            },
        },
        "venue": {"id": venue_id, "name": venue},
    }


def test_parse_game_extracts_fields():
    raw = make_mock_game()
    game = parse_game(raw)
    assert game["game_pk"] == 748532
    assert game["home_team_name"] == "Boston Red Sox"
    assert game["away_team_name"] == "New York Yankees"
    assert game["home_pitcher_id"] == 656302
    assert game["away_pitcher_id"] == 543037
    assert game["venue_name"] == "Fenway Park"
    assert game["day_night"] == "night"


def test_parse_game_missing_pitcher():
    raw = make_mock_game()
    del raw["teams"]["home"]["probablePitcher"]
    game = parse_game(raw)
    assert game["home_pitcher_id"] is None
    assert game["home_pitcher_name"] is None


@patch("modules.data.schedule.statsapi")
def test_fetch_games_returns_parsed_list(mock_api):
    mock_api.schedule.return_value = {
        "dates": [{"games": [make_mock_game(), make_mock_game(game_pk=748533)]}]
    }
    games = fetch_games("2026-04-01")
    assert len(games) == 2
    assert games[0]["game_pk"] == 748532
