from modules.models.strikeout_predictor import (
    predict_strikeouts, _csw_to_expected_ks, _swstr_to_expected_ks,
    _estimate_batters_faced, _opposing_k_adjustment,
)


def test_csw_to_expected_ks_elite():
    ks = _csw_to_expected_ks(32.0)
    assert 7 < ks < 10


def test_swstr_to_expected_ks():
    ks = _swstr_to_expected_ks(13.0)
    assert 6 < ks < 9


def test_estimate_batters_faced():
    pitcher = {"innings_pitched": 30.0, "games_started": 5}
    batters = _estimate_batters_faced(pitcher)
    assert 24 < batters < 30


def test_opposing_k_adjustment_high():
    adj = _opposing_k_adjustment(27)
    assert adj > 0


def test_opposing_k_adjustment_low():
    adj = _opposing_k_adjustment(18)
    assert adj < 0


def test_predict_strikeouts_returns_fields():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees"}
    pitcher = {"player_id": 543037, "player_name": "Gerrit Cole", "csw": 32.1,
               "swstr": 13.8, "k_rate": 30.2, "k_per_9": 11.4,
               "innings_pitched": 32.0, "games_started": 5, "recent_k_per_9": 12.0}
    opp_batting = {"k_rate": 26.8}
    park = {"k_factor": 98}
    umpire = {"k_plus": 0.4}
    weather = None
    k_odds = {"line": 7.5, "over_price": -115, "under_price": -105}

    result = predict_strikeouts(game, pitcher, opp_batting, park, umpire, weather, k_odds)
    assert result["pick"] in ("OVER", "UNDER", "PASS")
    assert result["model_ks"] is not None
    assert result["model_ks"] > 5
    assert result["grade"] in ("BET", "LEAN", "PASS")
