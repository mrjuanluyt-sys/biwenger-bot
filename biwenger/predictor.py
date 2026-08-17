from __future__ import annotations

from .models import Player

DEFAULT_WEIGHTS = [0.35, 0.25, 0.18, 0.12, 0.10]
SEASON_GAMES = 38
FIXTURE_SENSITIVITY = 0.6


def base_per_game(player: Player, weights: list[float] | None = None) -> float:
    weights = weights or DEFAULT_WEIGHTS
    recent = [float(x) for x in (player.fitness[-len(weights) :] if player.fitness else [])]
    season = (player.points_last_season / SEASON_GAMES) if player.points_last_season else None
    if recent:
        used = weights[-len(recent) :]
        norm = sum(used) or 1.0
        form = sum(pts * w for pts, w in zip(reversed(recent), used)) / norm
        # 1-2 partidos no mandan: si no, un 17 de jornada 1 parece 17 eternos.
        if season is not None and len(recent) < 5:
            w_form = len(recent) / (len(recent) + 5)
            return w_form * form + (1.0 - w_form) * season
        return form
    if season is not None:
        return season
    if player.points:
        return player.points / max(len(player.fitness) or 1, 1)
    return 0.0


def fixture_factor(player: Player, sensitivity: float = FIXTURE_SENSITIVITY) -> float:
    if player.fixture_difficulty is None:
        return 1.0
    return 1.0 + (50.0 - player.fixture_difficulty) / 100.0 * sensitivity


def home_away_factor(player: Player) -> float:
    if player.next_is_home is None:
        return 1.0
    home_n = max(player.played_home, 0)
    away_n = max(player.played_away, 0)
    if home_n + away_n >= 4:
        home_ppg = player.points_home / max(home_n, 1)
        away_ppg = player.points_away / max(away_n, 1)
        avg = (home_ppg + away_ppg) / 2 or 1.0
        use = home_ppg if player.next_is_home else away_ppg
        return max(0.82, min(1.22, use / avg))
    return 1.06 if player.next_is_home else 0.96


def starter_factor(player: Player) -> float:
    if player.starter_role == "starter":
        return 1.08
    if player.starter_role == "bench":
        return 0.28
    if player.starter_role == "out":
        return 0.0
    return 0.6 + 0.4 * max(0.0, min(1.0, player.starter_rate))


def predict(player: Player) -> float:
    if player.is_injured_or_suspended or player.starter_role == "out":
        return 0.0
    expected = (
        base_per_game(player)
        * fixture_factor(player)
        * starter_factor(player)
        * home_away_factor(player)
    )
    if player.is_doubt and player.starter_role != "starter":
        expected *= 0.4
    elif player.is_doubt:
        expected *= 0.7
    if player.sofascore is not None:
        if player.sofascore >= 7.3:
            expected *= 1.05
        elif player.sofascore <= 6.1:
            expected *= 0.95
    return round(max(expected, 0.0), 2)


def predict_all(players: list[Player]) -> dict[int, float]:
    return {p.id: predict(p) for p in players}
