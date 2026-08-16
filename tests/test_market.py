from datetime import datetime, timezone

from biwenger.market import filter_position, find_bargains, find_targets, money, pick_board, sell_candidates
from biwenger.models import MarketListing, Player, Position


def test_money_format() -> None:
    assert money(1_250_000) == "1.250.000€"


def _fwd(pid: int, name: str, price: int, fitness: list[int], **kw) -> Player:
    return Player(
        id=pid,
        name=name,
        position=Position.FORWARD,
        price=price,
        fitness=fitness,
        status="ok",
        starter_rate=1.0,
        fixture_difficulty=40,
        **kw,
    )


def test_bargain_prefers_discounted_fit_player() -> None:
    cheap = _fwd(1, "Cholillo", 10_000_000, [8, 8, 7])
    listing = MarketListing(player_id=1, price=7_000_000, until=datetime.now(timezone.utc))
    squad = [_fwd(9, "Mio", 4_000_000, [3], is_owned_by_me=True)]
    found = find_bargains([listing], {1: cheap}, squad, available=20_000_000)
    assert found
    assert found[0].player.name == "Cholillo"
    assert found[0].discount_pct > 0
    assert found[0].bids["competitiva"] > 0


def test_clause_targets_include_rival_players() -> None:
    mine = _fwd(1, "Mio", 3_000_000, [3, 3, 3], is_owned_by_me=True)
    star = _fwd(
        2,
        "Crack",
        12_000_000,
        [9, 8, 8],
        owner_id=99,
        owner_name="Rival",
        clause=14_000_000,
    )
    junk = _fwd(
        3,
        "Barato",
        200_000,
        [1, 1, 1],
        owner_id=99,
        owner_name="Rival",
        clause=200_000,
    )
    targets = find_targets([], {2: star, 3: junk}, [mine], available=20_000_000)
    names = [t.player.name for t in targets]
    assert "Crack" in names
    assert "Barato" in names
    # Un crack que mejora el XI gana a un clause=valor irrelevante.
    assert targets[0].player.name == "Crack"
    assert targets[0].source == "clause"
    assert targets[0].xp_per_million > 0
    assert targets[0].extra_xp > 0
    assert targets[0].cost_per_extra is not None


def test_sale_cheaper_than_clause_hides_clause_path() -> None:
    player = _fwd(5, "EnVenta", 5_000_000, [6, 6, 6], owner_id=7, owner_name="X", clause=8_000_000)
    listing = MarketListing(
        player_id=5,
        price=5_200_000,
        until=datetime.now(timezone.utc),
        seller_id=7,
        seller_name="X",
    )
    squad = [_fwd(1, "Mio", 2_000_000, [2], is_owned_by_me=True)]
    targets = find_targets([listing], {5: player}, squad, available=20_000_000)
    assert len(targets) == 1
    assert targets[0].source == "sale"
    assert targets[0].cost == 5_200_000


def test_unaffordable_ranked_below_but_listed() -> None:
    mine = _fwd(1, "Mio", 3_000_000, [3], is_owned_by_me=True)
    mega = _fwd(2, "Mega", 40_000_000, [10, 10, 10], owner_id=3, owner_name="R", clause=50_000_000)
    ok = _fwd(4, "Ok", 4_000_000, [6, 6, 6], owner_id=3, owner_name="R", clause=4_500_000)
    targets = find_targets([], {2: mega, 4: ok}, [mine], available=6_000_000)
    board, watch = pick_board(targets, affordable_n=5, watch_n=2)
    assert any(t.player.name == "Ok" for t in board)
    assert any(t.player.name == "Mega" for t in watch)
    assert all(t.affordable for t in board)


def test_filter_position_keeps_only_that_line() -> None:
    mine = _fwd(1, "Mio", 3_000_000, [3], is_owned_by_me=True)
    fw = _fwd(2, "Nueve", 8_000_000, [7, 7], owner_id=9, owner_name="R", clause=9_000_000)
    mf = Player(
        id=3,
        name="Interior",
        position=Position.MIDFIELDER,
        price=6_000_000,
        fitness=[6, 6],
        owner_id=9,
        owner_name="R",
        clause=7_000_000,
        starter_rate=1.0,
        fixture_difficulty=40,
    )
    targets = find_targets([], {2: fw, 3: mf}, [mine], available=20_000_000)
    only_fw = filter_position(targets, Position.FORWARD)
    assert only_fw
    assert all(t.player.position == Position.FORWARD for t in only_fw)


def test_injured_is_sell_candidate() -> None:
    injured = Player(
        id=2,
        name="Roto",
        position=Position.MIDFIELDER,
        price=8_000_000,
        status="injured",
        is_owned_by_me=True,
    )
    tips = sell_candidates([injured])
    assert tips
    assert "fuera" in tips[0].reason
