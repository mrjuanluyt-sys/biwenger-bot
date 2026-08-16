from biwenger.edge import captain_score, hole
from biwenger.intel import parse_preview
from biwenger.models import Player, Position
from biwenger.predictor import predict


def test_parse_preview_extracts_starters_and_doubts() -> None:
    html = """
    <h3>Posible Alineación del Deportivo</h3>
    <img src="https://cdn.biwenger.com/i/p/111.png">
    <img src="https://cdn.biwenger.com/i/p/222.png">
    <h4>No disponibles</h4>
    <img src="https://cdn.biwenger.com/i/p/333.png" alt="X">
    <span class="player-status" title="Golpe en el tobillo.">Duda</span>
    <small>Golpe en el tobillo.</small>
    <img src="https://cdn.biwenger.com/i/p/444.png">
    <span class="player-status">Lesionado</span>
    <small>Rotura de fibras.</small>
    """
    starters, unav = parse_preview(html)
    assert 111 in starters and 222 in starters
    assert 333 not in starters
    assert unav[333][0] == "doubt"
    assert "tobillo" in unav[333][1]
    assert unav[444][0] == "injured"


def test_injured_and_out_score_zero() -> None:
    injured = Player(1, "A", Position.FORWARD, 1, status="injured", fitness=[8, 8])
    out = Player(2, "B", Position.FORWARD, 1, status="ok", starter_role="out", fitness=[8, 8])
    assert predict(injured) == 0
    assert predict(out) == 0


def test_no_keeper_is_the_hole() -> None:
    squad = [
        Player(1, "DEF", Position.DEFENDER, 1),
        Player(2, "MED", Position.MIDFIELDER, 1),
        Player(3, "DEL", Position.FORWARD, 1),
    ]
    assert hole(squad) == Position.GOALKEEPER


def test_unique_captain_beats_owned_same_xp() -> None:
    unique = Player(1, "A", Position.FORWARD, 1, ownership=0)
    popular = Player(2, "B", Position.FORWARD, 1, ownership=10)
    assert captain_score(unique, 6.0, 13) > captain_score(popular, 6.0, 13)


def test_probable_starter_beats_bench() -> None:
    starter = Player(1, "Titular", Position.FORWARD, 1, fitness=[6, 6, 6], starter_role="starter")
    bench = Player(2, "Suplente", Position.FORWARD, 1, fitness=[6, 6, 6], starter_role="bench")
    assert predict(starter) > predict(bench)
