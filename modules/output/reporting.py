import os
from datetime import datetime
from config import REPORTS_DIR
from colorama import Fore, Style, init

init()


def generate_report(games, predictions, target_date):
    """Generate the full daily report."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    lines = []
    lines.append(f"MLB Prediction Bot — {target_date}")
    lines.append("=" * 60)

    game_preds = [p for p in predictions if p["bet_type"] == "game"]
    k_preds = [p for p in predictions if p["bet_type"] == "strikeout"]
    nrfi_preds = [p for p in predictions if p["bet_type"] == "nrfi"]

    # Game Predictions
    if game_preds:
        lines.append("\nGAME PREDICTIONS")
        lines.append("-" * 40)
        for pred in game_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_game_prediction(game, pred))

    # Strikeout Props
    if k_preds:
        lines.append("\nPITCHER STRIKEOUT PROPS")
        lines.append("-" * 40)
        for pred in k_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_k_prediction(game, pred))

    # NRFI Picks
    if nrfi_preds:
        lines.append("\nNRFI PICKS")
        lines.append("-" * 40)
        for pred in nrfi_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_nrfi_prediction(game, pred))

    # Best Picks Summary
    lines.extend(_format_best_picks(predictions))

    report_text = "\n".join(lines)

    # Save to file
    filepath = os.path.join(REPORTS_DIR, f"{target_date}.txt")
    with open(filepath, "w") as f:
        f.write(report_text)

    # Print to console with color
    _print_colored(report_text)

    return report_text


def _find_game(games, game_pk):
    for g in games:
        if g["game_pk"] == game_pk:
            return g
    return None


def _format_game_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{game['away_team_name']} @ {game['home_team_name']} | {game.get('venue_name', '')}")
    lines.append(f"  Starter: {game.get('away_pitcher_name', 'TBD')} vs {game.get('home_pitcher_name', 'TBD')}")

    # Lines: ML, Spread, Total
    ml_str = ""
    if pred.get("home_ml") is not None and pred.get("away_ml") is not None:
        ml_str = f"  Lines: {game['away_team_name']} {_fmt_odds(pred['away_ml'])} | {game['home_team_name']} {_fmt_odds(pred['home_ml'])}"
        if pred.get("spread") is not None:
            ml_str += f" | Spread: {_fmt_spread(pred['spread'])} ({_fmt_odds(pred.get('spread_price'))})"
        if pred.get("total") is not None:
            ml_str += f" | O/U: {pred['total']}"
        lines.append(ml_str)

    lines.append(f"  Model: {pred.get('model_value', '?')}% | Market: {pred.get('market_value', '?')}%")
    lines.append(f"  Pick: {pred['pick_detail']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:.1f}% | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Top Factors: {', '.join(pred['reasons'][:3])}")
    if pred.get("risks"):
        lines.append(f"  Risks: {', '.join(pred['risks'][:2])}")
    lines.append("")
    return lines


def _fmt_odds(odds):
    """Format American odds with +/- sign."""
    if odds is None:
        return "?"
    return f"+{odds}" if odds > 0 else str(odds)


def _fmt_spread(spread):
    """Format spread with +/- sign."""
    if spread is None:
        return "?"
    return f"+{spread}" if spread > 0 else str(spread)


def _format_k_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{pred.get('pitcher_name', '?')} ({game['away_team_name']} @ {game['home_team_name']})")
    lines.append(f"  Model: {pred.get('model_ks', '?')} Ks | Line: O/U {pred.get('line', '?')}")
    lines.append(f"  Pick: {pred['pick']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:+.1f} Ks | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Why: {', '.join(pred['reasons'][:3])}")
    lines.append("")
    return lines


def _format_nrfi_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{game['away_team_name']} @ {game['home_team_name']}")
    nrfi_pct = pred.get('nrfi_probability', 0) * 100
    implied_pct = (pred.get('implied_probability') or 0) * 100
    lines.append(f"  NRFI Probability: {nrfi_pct:.1f}% | Implied: {implied_pct:.1f}%")
    lines.append(f"  Pick: {pred['pick']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:.1f}% | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Why: {', '.join(pred['reasons'][:3])}")
    if pred.get("risks"):
        lines.append(f"  Risks: {', '.join(pred['risks'][:2])}")
    lines.append("")
    return lines


def _format_best_picks(predictions):
    lines = ["\nTODAY'S BEST PICKS", "=" * 40]

    bets = [p for p in predictions if p["grade"] == "BET"]
    leans = [p for p in predictions if p["grade"] == "LEAN"]

    if bets:
        lines.append(f"{Fore.GREEN}BET:{Style.RESET_ALL}")
        for p in sorted(bets, key=lambda x: x["confidence"], reverse=True):
            detail = p.get("pick_detail") or p["pick"]
            lines.append(f"  - {p['bet_type'].upper()}: {detail} ({p['confidence']}/100, {p['edge']:.1f}% edge)")

    if leans:
        lines.append(f"{Fore.YELLOW}LEAN:{Style.RESET_ALL}")
        for p in sorted(leans, key=lambda x: x["confidence"], reverse=True):
            detail = p.get("pick_detail") or p["pick"]
            lines.append(f"  - {p['bet_type'].upper()}: {detail} ({p['confidence']}/100)")

    if not bets and not leans:
        lines.append("  No actionable picks today.")

    return lines


def _grade_color(grade):
    if grade == "BET":
        return Fore.GREEN
    elif grade == "LEAN":
        return Fore.YELLOW
    return Fore.RED


def _print_colored(text):
    print(text)
