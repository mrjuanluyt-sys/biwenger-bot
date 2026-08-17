from biwenger import alerts, state
from biwenger.lineup import LineupResult
from biwenger.models import ManagerBudget, Player, Position, TeamState
from biwenger.snap import Snap


def _budget(team_id: int, name: str, cash: int, me: bool = False) -> ManagerBudget:
    return ManagerBudget(
        team_id=team_id,
        name=name,
        position=1,
        points=0,
        team_value=10_000_000,
        team_value_inc=0,
        team_size=11,
        cash=cash,
        cash_raw=cash,
        cash_is_estimate=not me,
        max_bid=cash,
        spent=0,
        income=0,
        is_me=me,
    )


def _snap(squad: list[Player], budgets: list[ManagerBudget]) -> Snap:
    team = TeamState(team_id=1, name="Yo", balance=5_000_000, player_ids=[p.id for p in squad])
    return Snap(
        team=team,
        squad=squad,
        catalog={p.id: p for p in squad},
        balance=5_000_000,
        max_bid=10_000_000,
        targets=[],
        budgets=budgets,
        lineup=LineupResult("4-3-3", squad, {}, 0.0, None),
        n_managers=2,
    )


def test_first_scan_is_silent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    star = Player(1, "Crack", Position.FORWARD, 20_000_000, clause=8_000_000)
    star.fitness = [8, 7, 6, 7, 8]
    snap = _snap(
        [star],
        [_budget(1, "Yo", 5_000_000, True), _budget(2, "Rival", 0)],
    )
    assert alerts.scan(snap) == []
    assert alerts.scan(snap) == []


def test_new_injury_alerts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    ok = Player(1, "Sano", Position.FORWARD, 5_000_000)
    snap = _snap([ok], [_budget(1, "Yo", 1, True)])
    assert alerts.scan(snap) == []
    hurt = Player(1, "Sano", Position.FORWARD, 5_000_000, status="injured")
    notes = alerts.scan(_snap([hurt], [_budget(1, "Yo", 1, True)]))
    assert notes
    assert "Sano" in notes[0][0]


def test_watch_add(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    assert alerts.watch_add(9) is True
    assert alerts.watch_add(9) is False
    assert alerts.watchlist() == [9]
