from biwenger.budget import build_budgets, infer_start_money, net_flow, parse_moves
from biwenger.models import LeagueStanding, MoneyMove


def test_parse_market_and_clause() -> None:
    news = [
        {
            "type": "market",
            "date": 10,
            "content": [{"player": 1, "to": {"id": 5}, "amount": 2_000_000}],
        },
        {
            "type": "transfer",
            "date": 11,
            "content": [
                {
                    "player": 2,
                    "from": {"id": 5},
                    "to": {"id": 8},
                    "amount": 3_000_000,
                    "type": "clause",
                }
            ],
        },
        {
            "type": "transfer",
            "date": 12,
            "content": [{"player": 3, "from": {"id": 8}, "amount": 500_000}],
        },
    ]
    moves = parse_moves(news)
    assert len(moves) == 3
    net5, inc5, sp5 = net_flow(moves, 5)
    assert sp5 == 2_000_000
    assert inc5 == 3_000_000
    assert net5 == 1_000_000
    net8, inc8, sp8 = net_flow(moves, 8)
    assert sp8 == 3_000_000
    assert inc8 == 500_000
    assert net8 == -2_500_000


def test_infer_start_snaps_to_million() -> None:
    start = infer_start_money(5_600_000, 0, -34_400_000, 25_000)
    assert start == 40_000_000


def test_build_budgets_uses_50m_start_and_real_cash_for_me() -> None:
    standings = [
        LeagueStanding(1, "Yo", 0, 1, team_value=30_000_000, team_value_inc=100_000, team_size=10),
        LeagueStanding(2, "Rival", 0, 2, team_value=40_000_000, team_value_inc=-50_000, team_size=12),
    ]
    moves = [
        MoneyMove(1, 10_000_000, payer_id=1, receiver_id=None, kind="market"),
        MoneyMove(2, 4_000_000, payer_id=2, receiver_id=None, kind="market"),
        MoneyMove(3, 2_000_000, payer_id=None, receiver_id=2, kind="sale"),
    ]
    budgets, start = build_budgets(standings, moves, my_id=1, my_balance=6_000_000)
    mine = next(b for b in budgets if b.is_me)
    rival = next(b for b in budgets if b.team_id == 2)
    assert mine.cash == 6_000_000
    assert mine.cash_is_estimate is False
    assert start == 50_000_000
    assert rival.cash == 50_000_000 - 4_000_000 + 2_000_000
    assert rival.cash_raw == rival.cash
    assert rival.cash_is_estimate is True
    assert rival.max_bid == rival.cash + rival.team_value // 4
    assert mine.overdraft == 0


def test_parse_loan_fee() -> None:
    news = [
        {
            "type": "loan",
            "date": 20,
            "content": [
                {
                    "player": 9,
                    "from": {"id": 1},
                    "to": {"id": 2},
                    "amount": 150_000,
                    "refund": -100_000,
                }
            ],
        }
    ]
    moves = parse_moves(news)
    assert len(moves) == 1
    net1, inc1, _ = net_flow(moves, 1)
    net2, _, sp2 = net_flow(moves, 2)
    assert inc1 == 150_000
    assert sp2 == 150_000
    assert net1 == 150_000
    assert net2 == -150_000


def test_overdraft_floors_cash_and_keeps_raw() -> None:
    standings = [
        LeagueStanding(2, "Gastón", 0, 1, team_value=40_000_000, team_value_inc=0, team_size=11),
    ]
    moves = [MoneyMove(1, 60_000_000, payer_id=2, receiver_id=None, kind="market")]
    budgets, _ = build_budgets(standings, moves, my_id=99, my_balance=1)
    gaston = budgets[0]
    assert gaston.cash_raw == 50_000_000 - 60_000_000
    assert gaston.cash == 0
    assert gaston.overdraft == 10_000_000
    assert gaston.max_bid == 40_000_000 // 4
