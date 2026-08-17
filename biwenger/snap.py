"""Un snapshot de la liga. Todos los informes y el chat lo reutilizan."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .budget import SEASON_START, START_MONEY, build_budgets, last_reset_epoch, parse_moves
from .client import BiwengerClient
from .edge import apply_next_home, apply_ownership
from .intel import enrich_catalog
from .lineup import LineupResult, best_lineup
from .market import Target, find_targets
from .models import ManagerBudget, MarketListing, Offer, Player, TeamState, UpcomingFixture

_CACHE: tuple[float, "Snap"] | None = None
CACHE_TTL = 8 * 60.0


def fill_buy_prices(players: list[Player], moves) -> None:
    last_pay: dict[tuple[int, int], int] = {}
    for move in sorted(moves, key=lambda m: m.date):
        if move.payer_id and move.player_id:
            last_pay[(int(move.payer_id), int(move.player_id))] = move.amount
    for player in players:
        if player.owner_id and not player.buy_price:
            player.buy_price = last_pay.get((int(player.owner_id), int(player.id)))


@dataclass
class Snap:
    team: TeamState
    squad: list[Player]
    catalog: dict[int, Player]
    balance: int
    max_bid: int
    targets: list[Target]
    budgets: list[ManagerBudget]
    lineup: LineupResult
    listings: list[MarketListing] = field(default_factory=list)
    fixtures: dict[int, list[UpcomingFixture]] = field(default_factory=dict)
    offers: list[Offer] = field(default_factory=list)
    n_managers: int = 1
    ts: float = field(default_factory=time.time)


def gather(client: BiwengerClient, force: bool = False) -> Snap:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE[0] < CACHE_TTL:
        return _CACHE[1]
    try:
        return _gather_fresh(client)
    except Exception as exc:
        from .client import BiwengerRateLimit

        if _CACHE and isinstance(exc, BiwengerRateLimit):
            return _CACHE[1]
        raise


def _gather_fresh(client: BiwengerClient) -> Snap:
    team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    enrich_catalog(client, catalog)
    n_mgr = max(len({p.owner_id for p in catalog.values() if p.owner_id}), 1)
    apply_ownership(catalog, n_mgr)
    fixtures: dict[int, list[UpcomingFixture]] = {}
    try:
        fixtures = client.get_team_fixtures(5)
        apply_next_home(catalog, fixtures)
    except Exception:
        pass
    listings, balance, max_bid = client.get_market()
    market_cap = max(max_bid, 0) if max_bid else max(balance, 0)
    clause_cash = max(balance, 0)
    targets = find_targets(listings, catalog, squad, market_cap, clause_cash=clause_cash)
    standings = client.get_standings()
    news = client.get_season_news(SEASON_START, max_pages=4)
    moves = parse_moves(news, since=last_reset_epoch(news) or SEASON_START)
    fill_buy_prices(list(catalog.values()), moves)
    league_settings = client.get_league_settings()
    budgets, _ = build_budgets(
        standings,
        moves,
        my_id=client.team_id,
        my_balance=team.balance,
        bonus_per_point=int(league_settings.get("bonusPoint") or 25_000),
        max_bid_rule=str(league_settings.get("maximumBid") or "quarterTeam"),
        start_money=START_MONEY,
        players=list(catalog.values()),
        listings=listings,
    )
    try:
        offers = client.get_offers()
    except Exception:
        offers = []
    snap = Snap(
        team=team,
        squad=squad,
        catalog=catalog,
        balance=balance,
        max_bid=max_bid,
        targets=targets,
        budgets=budgets,
        lineup=best_lineup(squad),
        listings=listings,
        fixtures=fixtures,
        offers=offers,
        n_managers=n_mgr,
    )
    _CACHE = (time.time(), snap)
    return snap


def clear() -> None:
    global _CACHE
    _CACHE = None
