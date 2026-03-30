from modules.models.game_predictor import predict_game, _pitcher_quality_score, _runs_edge_to_probability
from modules.models.confidence import grade_pick


def test_pitcher_quality_prefers_xera():
    pitcher = {"xera": 3.00, "fip": 3.50, "era": 4.00}
    score = _pitcher_quality_score(pitcher)
    # Ensemble: xERA (30%), FIP (25%), ERA (10%) — all present, xFIP/SIERA missing
    expected = (3.00 * 0.30 + 3.50 * 0.25 + 4.00 * 0.10) / (0.30 + 0.25 + 0.10)
    assert abs(score - expected) < 0.001


def test_pitcher_quality_fallback_to_era():
    pitcher = {"era": 3.50}
    assert _pitcher_quality_score(pitcher) == 3.50


def test_runs_edge_to_probability_positive():
    prob = _runs_edge_to_probability(1.0)
    assert prob > 0.5


def test_runs_edge_to_probability_zero():
    prob = _runs_edge_to_probability(0.0)
    assert abs(prob - 0.5) < 0.01


def test_grade_pick_bet():
    assert grade_pick(70, 3.0, "game") == "BET"


def test_grade_pick_lean():
    assert grade_pick(50, 1.0, "game") == "LEAN"


def test_grade_pick_pass():
    assert grade_pick(20, 0.1, "game") == "PASS"


def test_predict_game_returns_required_fields():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees",
            "home_pitcher_name": "Bello", "away_pitcher_name": "Cole"}
    home_p = {"era": 3.80, "xera": 3.45, "fip": 3.62, "barrel_rate_against": 7.0}
    away_p = {"era": 2.51, "xera": 2.89, "fip": 3.01, "barrel_rate_against": 5.0}
    home_bat = {"ops": 0.730, "k_rate": 22, "wrc_plus": 102, "barrel_rate": 8.5}
    away_bat = {"ops": 0.750, "k_rate": 24, "wrc_plus": 108, "barrel_rate": 9.0}
    bp_home = {"bullpen_era": 3.90}
    bp_away = {"bullpen_era": 3.50}
    park = {"run_factor": 105}
    umpire = None
    weather = {"dome": False, "temp_f": 72, "wind_speed": 8, "wind_dir": 180}
    odds = {"home_ml": 108, "away_ml": -128}

    result = predict_game(game, home_p, away_p, home_bat, away_bat,
                          bp_home, bp_away, park, umpire, weather, odds)

    assert "pick" in result
    assert "confidence" in result
    assert "edge" in result
    assert "grade" in result
    assert result["grade"] in ("BET", "LEAN", "PASS")
    assert 0 <= result["confidence"] <= 100
