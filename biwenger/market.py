from __future__ import annotations

from dataclasses import dataclass

from .models import MarketListing, Player, Position
from .predictor import predict
from .settings import Settings, settings as default_settings

BID_LEVELS = {"minima": 1.00, "competitiva": 1.15, "fuerte": 1.35}
NEED_MULTIPLIER = {"urgent": 1.25, "upgrade": 1.12, "depth": 1.03}
NEED_LABEL = {"urgent": "hueco", "upgrade": "mejora XI", "depth": "fondo"}
SOURCE_LABEL = {"market": "mercado", "sale": "venta rival", "clause": "cláusula", "free": "libre"}


def money(n: int | float) -> str:
    return f"{int(n):,}".replace(",", ".") + "€"


def bid_levels(market_price: int, available: int, margin: int) -> dict[str, int]:
    cap = max(available - margin, 0)
    out: dict[str, int] = {}
    for name, mult in BID_LEVELS.items():
        amount = int(round(market_price * mult / 1000) * 1000)
        out[name] = min(amount, cap) if cap else amount
    return out


def need_level(player: Player, squad: list[Player]) -> str:
    same = [p for p in squad if p.position == player.position and not p.is_injured_or_suspended]
    if player.position == Position.GOALKEEPER:
        return "urgent" if len(same) < 2 else "depth"
    if len(same) < 3:
        return "urgent"
    best = max((predict(p) for p in same), default=0.0)
    if predict(player) > best + 0.6:
        return "upgrade"
    return "depth"


def best_in_position(squad: list[Player], position: Position) -> float:
    same = [p for p in squad if p.position == position and not p.is_injured_or_suspended]
    return max((predict(p) for p in same), default=0.0)


@dataclass
class Bargain:
    """Compat: ganga de mercado clásica."""

    listing: MarketListing
    player: Player
    discount_pct: float
    expected: float
    need: str
    bids: dict[str, int]
    score: float


@dataclass
class Target:
    """Cualquier vía de fichar: mercado, venta o clausulazo."""

    player: Player
    source: str
    cost: int
    expected: float
    need: str
    xp_per_million: float
    extra_xp: float
    cost_per_extra: float | None
    premium_pct: float
    trend_pct: float
    affordable: bool
    score: float
    listing: MarketListing | None = None
    bids: dict[str, int] | None = None

    @property
    def via(self) -> str:
        return SOURCE_LABEL.get(self.source, self.source)


def _score_target(
    *,
    expected: float,
    extra_xp: float,
    xp_per_million: float,
    premium_pct: float,
    trend_pct: float,
    need: str,
    affordable: bool,
    injured: bool,
    cost: int,
    ownership: int = 0,
) -> float:
    # Ranking: ¿mejora el XI? ¿cuánto cuesta cada punto extra?
    # La prima valor/cláusula solo afina. pts/M€ bruto no manda: si no,
    # un jugador de 150k con 0.2 pts gana a un crack.
    need_bonus = {"urgent": 3.5, "upgrade": 2.0, "depth": 0.0}[need]
    premium_adj = max(-1.5, min(0.8, (15.0 - premium_pct) / 40.0))
    trend_adj = max(-1.2, min(1.2, trend_pct / 4.0))
    extra = max(extra_xp, 0.0)
    upgrade_per_m = extra / max(cost / 1_000_000, 1.0)
    score = (
        4.0 * extra
        + 2.6 * upgrade_per_m
        + 0.7 * expected
        + need_bonus
        + premium_adj
        + trend_adj
        + 0.15 * xp_per_million
    )
    if extra_xp <= 0:
        score -= 2.2
    if not affordable:
        score -= 8.0
    if injured:
        score -= 6.0
    # Nadie lo tiene: ventaja de clasificación, no solo de puntos.
    if ownership <= 0:
        score += 2.4
    elif ownership == 1:
        score += 1.1
    return round(score, 3)


def _make_target(
    player: Player,
    cost: int,
    source: str,
    squad: list[Player],
    available: int,
    listing: MarketListing | None = None,
    bids: dict[str, int] | None = None,
) -> Target | None:
    if cost <= 0:
        return None
    expected = predict(player)
    if expected <= 0 and player.is_injured_or_suspended:
        return None
    extra = expected - best_in_position(squad, player.position)
    xp_per_m = expected / max(cost / 1_000_000, 0.05)
    premium = ((cost - player.price) / player.price * 100) if player.price else 0.0
    need = need_level(player, squad)
    if extra > 0.6 and need == "depth":
        need = "upgrade"
    affordable = cost <= available
    cost_per_extra = (cost / extra) if extra > 0.05 else None
    score = _score_target(
        expected=expected,
        extra_xp=extra,
        xp_per_million=xp_per_m,
        premium_pct=premium,
        trend_pct=player.price_trend_pct,
        need=need,
        affordable=affordable,
        injured=player.is_injured_or_suspended,
        cost=cost,
        ownership=int(player.ownership or 0),
    )
    return Target(
        player=player,
        source=source,
        cost=cost,
        expected=expected,
        need=need,
        xp_per_million=round(xp_per_m, 2),
        extra_xp=round(extra, 2),
        cost_per_extra=round(cost_per_extra) if cost_per_extra else None,
        premium_pct=round(premium, 1),
        trend_pct=player.price_trend_pct,
        affordable=affordable,
        score=score,
        listing=listing,
        bids=bids,
    )


def find_targets(
    listings: list[MarketListing],
    catalog: dict[int, Player],
    squad: list[Player],
    available: int,
    cfg: Settings | None = None,
) -> list[Target]:
    """Analiza TODO: mercado + ventas + cláusulas de rivales."""
    cfg = cfg or default_settings
    owned = {p.id for p in squad}
    listed = {item.player_id: item for item in listings}
    out: list[Target] = []

    # 1) Mercado / ventas (si un rival lo pone, suele ser más barato que la cláusula)
    for listing in listings:
        if listing.player_id in owned:
            continue
        player = catalog.get(listing.player_id)
        if not player:
            continue
        source = "free" if listing.is_free_market else "sale"
        bids = bid_levels(listing.price or player.price, available, cfg.budget_safety_margin)
        target = _make_target(player, listing.price, source, squad, available, listing, bids)
        if target:
            out.append(target)

    # 2) Clausulazos: todo el que tenga dueño rival y cláusula, y no esté ya
    #    cubierto por una venta más barata.
    for player in catalog.values():
        if player.id in owned or player.on_loan or player.is_owned_by_me:
            continue
        if not player.owner_id or not player.clause:
            continue
        listing = listed.get(player.id)
        if listing and listing.price and listing.price <= player.clause:
            continue
        target = _make_target(player, int(player.clause), "clause", squad, available)
        if target:
            out.append(target)

    out.sort(key=lambda t: t.score, reverse=True)
    return out


def find_bargains(
    listings: list[MarketListing],
    catalog: dict[int, Player],
    squad: list[Player],
    available: int,
    cfg: Settings | None = None,
    limit: int = 8,
) -> list[Bargain]:
    """Compat para tests / briefing: top del mercado convertido a Bargain."""
    cfg = cfg or default_settings
    targets = [
        t
        for t in find_targets(listings, catalog, squad, available, cfg)
        if t.source in {"free", "sale", "market"} and t.listing
    ]
    bargains: list[Bargain] = []
    for t in targets[:limit]:
        listing = t.listing
        assert listing is not None
        discount = (t.player.price - listing.price) / t.player.price * 100 if t.player.price else 0.0
        bargains.append(
            Bargain(
                listing=listing,
                player=t.player,
                discount_pct=round(discount, 1),
                expected=t.expected,
                need=t.need,
                bids=t.bids or {},
                score=t.score,
            )
        )
    return bargains


def filter_position(targets: list[Target], position: Position | None) -> list[Target]:
    if position is None:
        return targets
    return [t for t in targets if t.player.position == position]


def pick_board(targets: list[Target], affordable_n: int = 8, watch_n: int = 3) -> tuple[list[Target], list[Target]]:
    affordable = [t for t in targets if t.affordable]
    watch = [t for t in targets if not t.affordable]
    return affordable[:affordable_n], watch[:watch_n]


@dataclass
class SellTip:
    player: Player
    reason: str
    suggested_price: int
    expected: float


def sell_candidates(squad: list[Player], limit: int = 6) -> list[SellTip]:
    tips: list[SellTip] = []
    for player in squad:
        expected = predict(player)
        reasons: list[str] = []
        if player.is_injured_or_suspended:
            reasons.append(f"fuera ({player.status})")
        if player.price_increment < 0 and player.price_trend_pct <= -1.5:
            reasons.append(f"precio {player.price_trend_pct:+.1f}%")
        if player.fitness and len(player.fitness) >= 3 and sum(player.fitness[-3:]) <= 0:
            reasons.append("3 jornadas flojas")
        if player.fixture_difficulty is not None and player.fixture_difficulty >= 70:
            reasons.append(f"calendario duro ({player.fixture_difficulty:.0f})")
        if not reasons:
            continue
        suggested = max(int(round(player.price * 0.98 / 1000) * 1000), 1)
        tips.append(
            SellTip(
                player=player,
                reason=", ".join(reasons),
                suggested_price=suggested,
                expected=expected,
            )
        )
    tips.sort(key=lambda t: (t.player.is_injured_or_suspended, -t.player.price_increment), reverse=True)
    return tips[:limit]
