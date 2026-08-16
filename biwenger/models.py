from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class Position(IntEnum):
    GOALKEEPER = 1
    DEFENDER = 2
    MIDFIELDER = 3
    FORWARD = 4
    COACH = 5

    @property
    def label(self) -> str:
        return {1: "POR", 2: "DEF", 3: "MED", 4: "DEL", 5: "ENT"}[int(self)]

    @property
    def emoji(self) -> str:
        return {1: "🧤", 2: "🛡️", 3: "⚙️", 4: "🎯", 5: "👔"}[int(self)]


STATUS_EMOJI = {
    "ok": "✅",
    "injured": "🚑",
    "injured_out": "🚑",
    "sanctioned": "🟥",
    "suspended": "🟥",
    "doubt": "⚠️",
    "doubtful": "⚠️",
}


@dataclass
class Player:
    id: int
    name: str
    position: Position
    price: int
    price_increment: int = 0
    status: str = "ok"
    fitness: list[int] = field(default_factory=list)
    slug: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    is_owned_by_me: bool = False
    owner_id: int | None = None
    owner_name: str | None = None
    clause: int | None = None
    buy_price: int | None = None
    on_loan: bool = False
    points: int = 0
    points_last_season: int = 0
    fixture_difficulty: float | None = None
    starter_rate: float = 1.0
    price_history: list[tuple[int, int]] = field(default_factory=list)
    status_info: str = ""
    starter_role: str = "unknown"  # starter | bench | out | unknown
    sofascore: float | None = None
    as_points: int | None = None
    headlines: list[str] = field(default_factory=list)
    ownership: int = 0
    next_is_home: bool | None = None
    points_home: int = 0
    points_away: int = 0
    played_home: int = 0
    played_away: int = 0

    @property
    def price_trend_pct(self) -> float:
        if not self.price:
            return 0.0
        return round(self.price_increment / self.price * 100, 2)

    @property
    def is_injured_or_suspended(self) -> bool:
        status = (self.status or "ok").lower()
        if status in {"injured", "injured_out", "sanctioned", "suspended", "discarded"}:
            return True
        return self.starter_role == "out"

    @property
    def is_doubt(self) -> bool:
        return (self.status or "").lower() in {"doubt", "doubtful"}

    @property
    def status_emoji(self) -> str:
        if self.starter_role == "starter":
            return "🟢"
        if self.starter_role == "bench":
            return "🟡"
        if self.starter_role == "out" or self.is_injured_or_suspended:
            return STATUS_EMOJI.get((self.status or "ok").lower(), "🚫")
        return STATUS_EMOJI.get((self.status or "ok").lower(), "✅")


@dataclass
class MarketListing:
    player_id: int
    price: int
    until: datetime
    seller_id: int | None = None
    seller_name: str | None = None
    bid_count: int = 0

    @property
    def is_free_market(self) -> bool:
        return self.seller_id is None

    @property
    def has_visible_bids(self) -> bool:
        return self.bid_count > 0


@dataclass
class Offer:
    id: int
    amount: int
    player_ids: list[int]
    from_id: int | None
    from_name: str
    status: str
    until: int | None = None


@dataclass
class Lineup:
    formation: str
    player_ids: list[int]
    captain_id: int | None = None


@dataclass
class TeamState:
    team_id: int
    name: str
    balance: int
    player_ids: list[int]
    lineup: Lineup | None = None
    owned: dict[int, dict] = field(default_factory=dict)
    points: int = 0


@dataclass
class Fixture:
    home: str
    away: str
    home_difficulty: float | None = None
    away_difficulty: float | None = None
    status: str = ""
    date: int = 0


@dataclass
class UpcomingFixture:
    opponent: str
    is_home: bool
    difficulty: float | None = None
    date: int = 0


@dataclass
class LeagueStanding:
    team_id: int
    name: str
    points: int
    position: int
    team_value: int = 0
    team_value_inc: int = 0
    team_size: int = 0


@dataclass
class MoneyMove:
    date: int
    amount: int
    payer_id: int | None
    receiver_id: int | None
    kind: str
    player_id: int | None = None


@dataclass
class ManagerBudget:
    team_id: int
    name: str
    position: int
    points: int
    team_value: int
    team_value_inc: int
    team_size: int
    cash: int
    cash_raw: int
    cash_is_estimate: bool
    max_bid: int
    spent: int
    income: int
    book_value: int = 0
    unrealized: int = 0
    realized: int = 0
    overdraft: int = 0
    listed: int = 0
    listed_count: int = 0
    confidence: str = "alta"
    is_me: bool = False

    @property
    def wealth(self) -> int:
        return self.cash + self.team_value

    @property
    def can_pay_clauses(self) -> bool:
        return self.cash > 0
