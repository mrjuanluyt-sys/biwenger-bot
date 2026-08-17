from biwenger.lineup import LineupResult
from biwenger.models import ManagerBudget, Player, Position, TeamState
from biwenger.snap import Snap
from biwenger.unfair import gap_to_beat, project_league, week_points


def _p(pid: int, name: str, pos: Position, owner: int, xp_fit: int) -> Player:
    return Player(
        id=pid,
        name=name,
        position=pos,
        price=1_000_000,
        fitness=[xp_fit, xp_fit, xp_fit],
        owner_id=owner,
        is_owned_by_me=owner == 1,
        starter_role="starter",
        starter_rate=1.0,
        fixture_difficulty=40,
    )


def _budget(tid: int, name: str, pos: int, me: bool = False) -> ManagerBudget:
    return ManagerBudget(
        team_id=tid,
        name=name,
        position=pos,
        points=10,
        team_value=1,
        team_value_inc=0,
        team_size=11,
        cash=0,
        cash_raw=0,
        cash_is_estimate=not me,
        max_bid=1,
        spent=0,
        income=0,
        is_me=me,
    )


def test_week_points_doubles_captain() -> None:
    a = _p(1, "A", Position.FORWARD, 1, 8)
    result = LineupResult("4-3-3", [a], {1: 5.0}, 5.0, a)
    assert week_points(result) == 10.0


def test_project_ranks_me_behind_stronger_rival() -> None:
    mine = [_p(1, "GK", Position.GOALKEEPER, 1, 2)]
    mine += [_p(10 + i, f"D{i}", Position.DEFENDER, 1, 2) for i in range(4)]
    mine += [_p(20 + i, f"M{i}", Position.MIDFIELDER, 1, 2) for i in range(3)]
    mine += [_p(30 + i, f"F{i}", Position.FORWARD, 1, 2) for i in range(3)]
    rival = [_p(100, "GK2", Position.GOALKEEPER, 2, 8)]
    rival += [_p(110 + i, f"RD{i}", Position.DEFENDER, 2, 8) for i in range(4)]
    rival += [_p(120 + i, f"RM{i}", Position.MIDFIELDER, 2, 8) for i in range(3)]
    rival += [_p(130 + i, f"RF{i}", Position.FORWARD, 2, 8) for i in range(3)]
    catalog = {p.id: p for p in mine + rival}
    snap = Snap(
        team=TeamState(1, "Yo", 1, [p.id for p in mine]),
        squad=mine,
        catalog=catalog,
        balance=1,
        max_bid=1,
        targets=[],
        budgets=[_budget(1, "Yo", 2, True), _budget(2, "Líder", 1)],
        lineup=LineupResult("4-3-3", mine, {p.id: 1.0 for p in mine}, 11.0, mine[-1]),
        n_managers=2,
    )
    weeks = project_league(snap)
    assert weeks[0].name == "Líder"
    gap = gap_to_beat(weeks)
    assert gap is not None
    assert gap[0].name == "Líder"
    assert gap[1] > 0
