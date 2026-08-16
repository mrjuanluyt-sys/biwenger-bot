from biwenger.lineup import best_lineup
from biwenger.models import Player, Position
from biwenger.predictor import predict


def _p(pid: int, name: str, pos: Position, fitness: list[int], status: str = "ok") -> Player:
    return Player(
        id=pid,
        name=name,
        position=pos,
        price=1_000_000,
        fitness=fitness,
        status=status,
        is_owned_by_me=True,
        points_last_season=100,
        starter_rate=1.0,
        fixture_difficulty=50,
    )


def _squad() -> list[Player]:
    players = []
    players.append(_p(1, "Oblak", Position.GOALKEEPER, [6, 6, 7]))
    players.append(_p(2, "Suplente", Position.GOALKEEPER, [2, 1, 2]))
    for i in range(5):
        players.append(_p(10 + i, f"DEF{i}", Position.DEFENDER, [4 + i, 5, 4]))
    for i in range(5):
        players.append(_p(20 + i, f"MED{i}", Position.MIDFIELDER, [5 + i, 6, 5]))
    for i in range(3):
        players.append(_p(30 + i, f"DEL{i}", Position.FORWARD, [7 + i, 6, 8]))
    players.append(_p(99, "Lesionado", Position.FORWARD, [10, 10, 10], status="injured"))
    return players


def test_injured_has_zero_points() -> None:
    injured = _p(1, "X", Position.FORWARD, [10, 10, 10], status="injured")
    assert predict(injured) == 0.0


def test_best_lineup_has_eleven_and_one_keeper() -> None:
    result = best_lineup(_squad())
    assert len(result.starters) == 11
    keepers = [p for p in result.starters if p.position == Position.GOALKEEPER]
    assert len(keepers) == 1
    assert keepers[0].name == "Oblak"
    assert result.captain is not None
    assert all(p.status != "injured" for p in result.starters)
    assert result.formation in {"4-3-3", "4-4-2", "3-5-2", "3-4-3", "5-3-2", "5-4-1"}


def test_incomplete_squad_returns_partial() -> None:
    small = [
        _p(1, "Oblak", Position.GOALKEEPER, [6, 6, 7]),
        _p(10, "DEF0", Position.DEFENDER, [4, 5, 4]),
        _p(20, "MED0", Position.MIDFIELDER, [5, 6, 5]),
        _p(30, "DEL0", Position.FORWARD, [7, 6, 8]),
    ]
    result = best_lineup(small)
    assert len(result.starters) == 4
    assert result.formation.startswith("incompleto")
    assert result.captain is not None


def test_easy_fixture_beats_hard_fixture() -> None:
    easy = _p(1, "Easy", Position.FORWARD, [6, 6, 6])
    hard = _p(2, "Hard", Position.FORWARD, [6, 6, 6])
    easy.fixture_difficulty = 20
    hard.fixture_difficulty = 80
    assert predict(easy) > predict(hard)
