"""Ventaja de liga privada clásica (un jugador = un dueño).

No existe el ownership tipo Premier. Ganas proyectando el XI de cada rival
(con AS/lesiones), su caja oculta y el precio de mañana.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from .lineup import LineupResult, best_lineup
from .market import Target, money
from .models import ManagerBudget, Player, Position
from .predictor import predict
from .snap import Snap


@dataclass
class WeekTeam:
    name: str
    team_id: int
    is_me: bool
    table_pos: int
    table_pts: int
    lineup: LineupResult
    week_pts: float
    hole: Position | None
    dead: list[Player]
    cash: int


def week_points(result: LineupResult) -> float:
    total = float(result.total_expected)
    if result.captain:
        total += float(result.expected.get(result.captain.id, 0.0))
    return round(total, 2)


def rosters(snap: Snap) -> dict[int, list[Player]]:
    by: dict[int, list[Player]] = defaultdict(list)
    for player in snap.catalog.values():
        if player.owner_id:
            by[int(player.owner_id)].append(player)
    return by


def dead_assets(squad: list[Player]) -> list[Player]:
    out = []
    for p in squad:
        if p.position == Position.COACH:
            continue
        if p.is_injured_or_suspended or p.starter_role == "out" or predict(p) <= 0.4:
            out.append(p)
    out.sort(key=lambda p: p.price, reverse=True)
    return out


def project_league(snap: Snap) -> list[WeekTeam]:
    by_owner = rosters(snap)
    weeks: list[WeekTeam] = []
    for b in snap.budgets:
        squad = by_owner.get(b.team_id) or []
        if b.is_me:
            lineup = snap.lineup
        else:
            lineup = best_lineup(squad) if squad else snap.lineup
        from .edge import hole

        weeks.append(
            WeekTeam(
                name=b.name,
                team_id=b.team_id,
                is_me=b.is_me,
                table_pos=b.position,
                table_pts=b.points,
                lineup=lineup,
                week_pts=week_points(lineup) if squad or b.is_me else 0.0,
                hole=hole(squad),
                dead=dead_assets(squad)[:3],
                cash=b.cash,
            )
        )
    weeks.sort(key=lambda w: (-w.week_pts, w.table_pos))
    return weeks


def my_week(weeks: list[WeekTeam]) -> WeekTeam | None:
    return next((w for w in weeks if w.is_me), None)


def gap_to_beat(weeks: list[WeekTeam]) -> tuple[WeekTeam, float] | None:
    mine = my_week(weeks)
    if not mine:
        return None
    better = [w for w in weeks if not w.is_me and w.week_pts > mine.week_pts]
    if not better:
        return None
    leader = better[0]
    return leader, round(leader.week_pts - mine.week_pts, 2)


def best_anti_captain(snap: Snap) -> Player | None:
    """Capitán: titular AS, casa, rival flojo. No 'diferencial FPL'."""
    from .edge import pick_captain

    return pick_captain(snap.lineup, snap.n_managers)


def steal_from(snap: Snap, team_id: int) -> list[Target]:
    hits = [
        t
        for t in snap.targets
        if t.source == "clause"
        and t.player.owner_id == team_id
        and t.expected >= 3.2
        and t.extra_xp > 0.3
    ]
    hits.sort(key=lambda t: (t.affordable, t.extra_xp, t.score), reverse=True)
    return hits[:3]


def empty_market(snap: Snap) -> list[Target]:
    now = datetime.now(timezone.utc)
    out = []
    for t in snap.targets:
        listing = t.listing
        if listing is None or not t.affordable or t.expected < 3.0:
            continue
        if listing.has_visible_bids:
            continue
        left = (listing.until - now).total_seconds()
        if left < 0:
            continue
        out.append(t)
    out.sort(key=lambda t: t.score, reverse=True)
    return out[:3]


def price_front_run(snap: Snap) -> tuple[list[Player], list[Player]]:
    mine = {p.id for p in snap.squad}
    buy: list[Player] = []
    sell: list[Player] = []
    for p in snap.catalog.values():
        if p.id in mine or p.is_injured_or_suspended:
            continue
        if p.starter_role == "starter" and p.price_increment > 0 and predict(p) >= 3.5:
            buy.append(p)
    buy.sort(key=lambda p: (p.price_increment, predict(p)), reverse=True)
    for p in snap.squad:
        if p.starter_role in {"bench", "out"} or p.is_injured_or_suspended:
            if p.price >= 1_000_000:
                sell.append(p)
    sell.sort(key=lambda p: (p.is_injured_or_suspended, p.price_increment, -p.price))
    return buy[:4], sell[:4]


def broken_rivals(weeks: list[WeekTeam]) -> list[WeekTeam]:
    return [w for w in weeks if not w.is_me and (w.hole or len(w.dead) >= 2 or w.week_pts < 20)]
