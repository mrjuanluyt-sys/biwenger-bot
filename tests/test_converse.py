from biwenger.converse import (
    detect_intent,
    detect_position,
    fold,
    match_manager,
    match_player,
    match_players,
)
from biwenger.models import ManagerBudget, Player, Position


def test_fold_strips_accents() -> None:
    assert fold("Cláusulazo") == "clausulazo"


def test_detect_intent_spanish() -> None:
    assert detect_intent("qué once pongo mañana") == "lineup"
    assert detect_intent("un clausulazo de defensa") == "clause"
    assert detect_intent("cuánto dinero tiene la decaneta") == "budget"
    assert detect_intent("a quién vendo") == "sell"
    assert detect_intent("hola tío") == "greet"
    assert detect_intent("quién está lesionado") == "intel"
    assert detect_intent("pújame al cierre por Mariano") == "snipe"
    assert detect_intent("Pedri o Nico") == "compare"
    assert detect_intent("quién me puede clavar") == "threat"
    assert detect_intent("vigila a Pedri") == "watch"


def test_detect_position_from_sentence() -> None:
    assert detect_position("quiero un delantero barato") == Position.FORWARD
    assert detect_position("mejor defensa") == Position.DEFENDER
    assert detect_position("pagar por el mercado") is None


def test_match_player_by_surname() -> None:
    catalog = {
        1: Player(1, "Pablo Barrios", Position.MIDFIELDER, 1),
        2: Player(2, "Tenaglia", Position.DEFENDER, 1),
    }
    assert match_player("puedo clavar a Tenaglia?", catalog).id == 2
    assert match_player("qué te parece Barrios", catalog).id == 1
    both = match_players("Barrios o Tenaglia", catalog)
    assert {p.id for p in both} == {1, 2}


def test_match_manager_ignores_short_tokens() -> None:
    budgets = [
        ManagerBudget(
            team_id=1,
            name="La Decaneta 🥇",
            position=4,
            points=0,
            team_value=1,
            team_value_inc=0,
            team_size=11,
            cash=0,
            cash_raw=0,
            cash_is_estimate=True,
            max_bid=1,
            spent=0,
            income=0,
        )
    ]
    assert match_manager("cuánto tiene la decaneta", budgets).team_id == 1
    assert match_manager("qué once pongo", budgets) is None
