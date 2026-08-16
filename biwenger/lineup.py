"""Elige el XI que maximiza puntos esperados.

Si las únicas restricciones son los cupos por posición, elegir a los
mejores de cada línea es óptimo: no hace falta un solver ILP.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Player, Position
from .predictor import predict_all

FORMATIONS: dict[str, dict[Position, int]] = {
    "4-3-3": {Position.DEFENDER: 4, Position.MIDFIELDER: 3, Position.FORWARD: 3},
    "4-4-2": {Position.DEFENDER: 4, Position.MIDFIELDER: 4, Position.FORWARD: 2},
    "3-5-2": {Position.DEFENDER: 3, Position.MIDFIELDER: 5, Position.FORWARD: 2},
    "3-4-3": {Position.DEFENDER: 3, Position.MIDFIELDER: 4, Position.FORWARD: 3},
    "5-3-2": {Position.DEFENDER: 5, Position.MIDFIELDER: 3, Position.FORWARD: 2},
    "5-4-1": {Position.DEFENDER: 5, Position.MIDFIELDER: 4, Position.FORWARD: 1},
}


@dataclass
class LineupResult:
    formation: str
    starters: list[Player]
    expected: dict[int, float]
    total_expected: float
    captain: Player | None

    @property
    def player_ids(self) -> list[int]:
        ordered: list[Player] = []
        for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
            ordered.extend([p for p in self.starters if p.position == pos])
        return [p.id for p in ordered]


def _pick(players: list[Player], expected: dict[int, float], n: int) -> list[Player] | None:
    eligible = [
        p
        for p in players
        if not p.is_injured_or_suspended
        and p.starter_role != "out"
        and not (p.is_doubt and p.starter_role != "starter")
    ]
    if len(eligible) < n:
        return None
    ranked = sorted(eligible, key=lambda p: expected.get(p.id, 0.0), reverse=True)
    return ranked[:n]


def solve_formation(
    squad: list[Player],
    expected: dict[int, float],
    formation: str,
) -> LineupResult | None:
    req = FORMATIONS[formation]
    keepers = _pick([p for p in squad if p.position == Position.GOALKEEPER], expected, 1)
    if keepers is None:
        return None
    starters = list(keepers)
    for pos, count in req.items():
        picked = _pick([p for p in squad if p.position == pos], expected, count)
        if picked is None:
            return None
        starters.extend(picked)
    total = sum(expected.get(p.id, 0.0) for p in starters)
    captain = max(starters, key=lambda p: expected.get(p.id, 0.0))
    return LineupResult(
        formation=formation,
        starters=starters,
        expected=expected,
        total_expected=round(total, 2),
        captain=captain,
    )


def _partial_lineup(squad: list[Player], expected: dict[int, float]) -> LineupResult:
    """Mejor XI incompleto cuando aún no hay 11 disponibles."""
    eligible = [p for p in squad if not p.is_injured_or_suspended and p.position != Position.COACH]
    keepers = [p for p in eligible if p.position == Position.GOALKEEPER]
    rest = [p for p in eligible if p.position != Position.GOALKEEPER]
    rest.sort(key=lambda p: expected.get(p.id, 0.0), reverse=True)
    starters = keepers[:1] + rest[: 10 if keepers else 11]
    total = sum(expected.get(p.id, 0.0) for p in starters)
    captain = max(starters, key=lambda p: expected.get(p.id, 0.0)) if starters else None
    return LineupResult(
        formation=f"incompleto ({len(starters)}/11)",
        starters=starters,
        expected=expected,
        total_expected=round(total, 2),
        captain=captain,
    )


def best_lineup(squad: list[Player]) -> LineupResult:
    field = [p for p in squad if p.position != Position.COACH]
    expected = predict_all(field)
    candidates = [
        result
        for formation in FORMATIONS
        if (result := solve_formation(field, expected, formation)) is not None
    ]
    if candidates:
        return max(candidates, key=lambda r: r.total_expected)
    return _partial_lineup(field, expected)
