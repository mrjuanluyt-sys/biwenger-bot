"""La ventaja: ownership, diferenciales, capitán, subidas y rivales rotos."""
from __future__ import annotations

from dataclasses import dataclass

from .lineup import LineupResult, best_lineup
from .market import Target, money
from .models import ManagerBudget, Player, Position, UpcomingFixture
from .predictor import predict


def apply_ownership(catalog: dict[int, Player], n_managers: int) -> None:
    counts: dict[int, int] = {}
    for player in catalog.values():
        if player.owner_id:
            counts[player.id] = counts.get(player.id, 0) + 1
    for player in catalog.values():
        player.ownership = counts.get(player.id, 0)


def apply_next_home(catalog: dict[int, Player], fixtures: dict[int, list[UpcomingFixture]]) -> None:
    for player in catalog.values():
        runs = fixtures.get(player.team_id or -1) or []
        if runs:
            player.next_is_home = bool(runs[0].is_home)


def ownership_label(player: Player, n_managers: int) -> str:
    n = player.ownership
    if n <= 0:
        return "nadie lo tiene"
    if n == 1:
        return "solo 1 rival"
    pct = round(100 * n / max(n_managers, 1))
    return f"en {n}/{n_managers} equipos ({pct}%)"


def captain_score(player: Player, expected: float, n_managers: int) -> float:
    # El capitán dobla. Si casi nadie lo tiene, ganas hueco en la tabla.
    unique = 1.0 - min(player.ownership, n_managers) / max(n_managers, 1)
    return expected * (1.0 + 0.35 * unique)


def pick_captain(lineup: LineupResult, n_managers: int) -> Player | None:
    if not lineup.starters:
        return None
    return max(
        lineup.starters,
        key=lambda p: captain_score(p, lineup.expected.get(p.id, 0.0), n_managers),
    )


@dataclass
class EdgePick:
    player: Player
    why: str
    score: float
    target: Target | None = None


def hole(squad: list[Player]) -> Position | None:
    counts = {pos: 0 for pos in Position}
    for p in squad:
        if p.position != Position.COACH and not p.is_injured_or_suspended:
            counts[p.position] += 1
    if counts[Position.GOALKEEPER] < 1:
        return Position.GOALKEEPER
    if counts[Position.FORWARD] < 2:
        return Position.FORWARD
    if counts[Position.DEFENDER] < 3:
        return Position.DEFENDER
    if counts[Position.MIDFIELDER] < 3:
        return Position.MIDFIELDER
    return None


def differentials(catalog: dict[int, Player], limit: int = 5) -> list[Player]:
    pool = [
        p
        for p in catalog.values()
        if not p.is_owned_by_me
        and not p.is_injured_or_suspended
        and p.ownership <= 1
        and predict(p) >= 3.5
        and p.starter_role in {"starter", "unknown"}
    ]
    pool.sort(key=lambda p: (p.ownership, -predict(p), p.price))
    return pool[:limit]


def price_risers(catalog: dict[int, Player], limit: int = 4) -> list[Player]:
    pool = [
        p
        for p in catalog.values()
        if not p.is_injured_or_suspended
        and p.starter_role != "out"
        and (p.price_increment > 0 or predict(p) >= 5)
    ]
    pool.sort(key=lambda p: (p.price_increment, predict(p)), reverse=True)
    return pool[:limit]


def price_falls(squad: list[Player], limit: int = 3) -> list[Player]:
    pool = [p for p in squad if p.price_increment < 0 or p.starter_role in {"bench", "out"} or p.is_injured_or_suspended]
    pool.sort(key=lambda p: (p.is_injured_or_suspended, p.price_increment, predict(p)))
    return pool[:limit]


def shield(squad: list[Player], limit: int = 3) -> list[Player]:
    stars = [p for p in squad if p.clause and p.price and p.clause < p.price * 1.35 and predict(p) >= 3]
    stars.sort(key=lambda p: (p.clause or 0) / max(p.price, 1))
    return stars[:limit]


def weak_rivals(catalog: dict[int, Player], budgets: list[ManagerBudget]) -> list[str]:
    by_owner: dict[int, list[Player]] = {}
    for p in catalog.values():
        if p.owner_id:
            by_owner.setdefault(p.owner_id, []).append(p)
    notes: list[str] = []
    for b in budgets:
        if b.is_me:
            continue
        roster = by_owner.get(b.team_id) or []
        gks = [p for p in roster if p.position == Position.GOALKEEPER and not p.is_injured_or_suspended]
        bits = []
        if b.cash == 0:
            bits.append("sin caja")
        if not gks:
            bits.append("sin portero")
        injured = [p for p in roster if p.is_injured_or_suspended]
        if len(injured) >= 2:
            bits.append(f"{len(injured)} bajas")
        if bits:
            notes.append(f"{b.name}: " + ", ".join(bits) + f" (techo {money(b.max_bid)})")
    return notes[:5]


def best_targets_for_hole(targets: list[Target], pos: Position | None) -> list[Target]:
    pool = [t for t in targets if t.expected > 0]
    if pos:
        pool = [t for t in pool if t.player.position == pos]
    pool.sort(key=lambda t: (t.affordable, t.score), reverse=True)
    return pool[:3]


def calendar_edge(squad: list[Player], fixtures: dict[int, list[UpcomingFixture]]) -> list[str]:
    lines: list[str] = []
    seen: set[int] = set()
    for p in squad:
        tid = p.team_id
        if not tid or tid in seen:
            continue
        seen.add(tid)
        runs = fixtures.get(tid) or []
        if not runs:
            continue
        easy = sum(1 for fx in runs[:4] if fx.difficulty is not None and fx.difficulty <= 40)
        hard = sum(1 for fx in runs[:4] if fx.difficulty is not None and fx.difficulty >= 65)
        if easy >= 2:
            names = ", ".join(x.name for x in squad if x.team_id == tid)[:40]
            lines.append(f"{p.team_name}: {easy} rivales asequibles en 4 jornadas ({names})")
        elif hard >= 3:
            lines.append(f"{p.team_name}: calendario duro — plantéate vender antes de que baje el precio")
    return lines[:4]
