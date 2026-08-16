"""Reconstruye el dinero de cada manager.

Todos salen con 50 millones. El saldo de los rivales está oculto: se
rehace con el tablón (mercado, ventas, cláusulas, cesiones). En ti se
usa el saldo real, que sirve de control: si el recuento cuadra, el
método es bueno.

El saldo en Biwenger no baja de 0. Si alguien fichó por encima del
inicial + ventas, su caja se muestra a 0 y el exceso como 'invertido
de más'. El techo de puja sigue siendo caja + 25% del valor de plantilla.
Las cláusulas se pagan solo de la caja.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from .models import LeagueStanding, ManagerBudget, MarketListing, MoneyMove, Player
from .settings import settings

SEASON_START = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
START_MONEY = 50_000_000


def last_reset_epoch(news: list[dict]) -> int | None:
    dates = [int(n.get("date") or 0) for n in news if n.get("type") == "leagueReset"]
    return max(dates) if dates else None


def parse_moves(news: list[dict], since: int | None = None) -> list[MoneyMove]:
    moves: list[MoneyMove] = []
    for item in news:
        date = int(item.get("date") or 0)
        if since is not None and date < since:
            continue
        kind = item.get("type")
        content = item.get("content") or []
        if not isinstance(content, list):
            continue
        if kind == "market":
            for row in content:
                if not isinstance(row, dict):
                    continue
                to = (row.get("to") or {}).get("id")
                amount = int(row.get("amount") or 0)
                if to and amount:
                    moves.append(MoneyMove(date, amount, int(to), None, "market", row.get("player")))
        elif kind == "transfer":
            for row in content:
                if not isinstance(row, dict):
                    continue
                amount = int(row.get("amount") or 0)
                if not amount:
                    continue
                frm = (row.get("from") or {}).get("id")
                to = (row.get("to") or {}).get("id")
                frm_id = int(frm) if frm else None
                to_id = int(to) if to else None
                label = row.get("type") or ("clause" if to_id else "sale")
                moves.append(MoneyMove(date, amount, to_id, frm_id, label, row.get("player")))
        elif kind == "clauseIncrement":
            for row in content:
                if not isinstance(row, dict):
                    continue
                uid = (row.get("user") or {}).get("id")
                amount = int(row.get("amount") or 0)
                if uid and amount:
                    moves.append(MoneyMove(date, amount, int(uid), None, "raise", row.get("player")))
        elif kind == "loan":
            for row in content:
                if not isinstance(row, dict):
                    continue
                amount = int(row.get("amount") or 0)
                if not amount:
                    continue
                frm = (row.get("from") or {}).get("id")
                to = (row.get("to") or {}).get("id")
                frm_id = int(frm) if frm else None
                to_id = int(to) if to else None
                # Cesión: el dueño cobra, el que lo pide paga.
                moves.append(MoneyMove(date, amount, to_id, frm_id, "loan", row.get("player")))
    return moves


def net_flow(moves: list[MoneyMove], team_id: int) -> tuple[int, int, int]:
    income = spent = 0
    for move in moves:
        if move.receiver_id == team_id:
            income += move.amount
        if move.payer_id == team_id:
            spent += move.amount
    return income - spent, income, spent


def infer_start_money(my_balance: int, my_points: int, my_net: int, bonus_per_point: int) -> int:
    raw = my_balance - my_net - my_points * bonus_per_point
    if raw < 0:
        return 0
    snapped = int(round(raw / 1_000_000) * 1_000_000)
    if abs(snapped - raw) <= 750_000:
        return max(snapped, 0)
    return raw


def estimate_max_bid(cash: int, team_value: int, rule: str) -> int:
    liquid = max(cash, 0)
    if rule == "quarterTeam":
        return int(liquid + team_value // 4)
    if rule == "halfTeam":
        return int(liquid + team_value // 2)
    return liquid + team_value


def _book_values(players: list[Player] | None) -> dict[int, int]:
    out: dict[int, int] = {}
    for player in players or []:
        if not player.owner_id:
            continue
        out[player.owner_id] = out.get(player.owner_id, 0) + int(player.buy_price or 0)
    return out


def _listed_values(listings: list[MarketListing] | None) -> tuple[dict[int, int], dict[int, int]]:
    euros: dict[int, int] = {}
    counts: dict[int, int] = {}
    for item in listings or []:
        if not item.seller_id:
            continue
        euros[item.seller_id] = euros.get(item.seller_id, 0) + int(item.price or 0)
        counts[item.seller_id] = counts.get(item.seller_id, 0) + 1
    return euros, counts


def _sold_cost(moves: list[MoneyMove], team_id: int, owned_ids: set[int]) -> int:
    cost = 0
    for move in moves:
        if move.payer_id != team_id or not move.player_id:
            continue
        if move.player_id not in owned_ids:
            cost += move.amount
    return cost


def _confidence(cash_raw: int, is_me: bool, recon_error: int) -> str:
    if is_me and abs(recon_error) <= 1:
        return "alta"
    if cash_raw >= 0:
        return "alta"
    if cash_raw > -2_000_000:
        return "media"
    return "media"


def build_budgets(
    standings: list[LeagueStanding],
    moves: list[MoneyMove],
    my_id: int | None,
    my_balance: int,
    bonus_per_point: int = 25_000,
    max_bid_rule: str = "quarterTeam",
    start_money: int = START_MONEY,
    players: list[Player] | None = None,
    listings: list[MarketListing] | None = None,
) -> tuple[list[ManagerBudget], int]:
    start = start_money
    books = _book_values(players)
    listed, listed_n = _listed_values(listings)
    owned_by: dict[int, set[int]] = {}
    for player in players or []:
        if player.owner_id:
            owned_by.setdefault(player.owner_id, set()).add(player.id)

    my_net, _, _ = net_flow(moves, int(my_id or 0))
    my_row = next((s for s in standings if my_id and s.team_id == my_id), None)
    my_points = my_row.points if my_row else 0
    recon_me = start + my_net + my_points * bonus_per_point
    recon_error = recon_me - my_balance

    out: list[ManagerBudget] = []
    for row in standings:
        net, income, spent = net_flow(moves, row.team_id)
        is_me = my_id is not None and row.team_id == my_id
        raw = my_balance if is_me else start + net + row.points * bonus_per_point
        cash = raw if is_me else max(int(raw), 0)
        overdraft = 0 if raw >= 0 else int(-raw)
        book = books.get(row.team_id, 0)
        sold_cost = _sold_cost(moves, row.team_id, owned_by.get(row.team_id, set()))
        sale_in = 0
        for move in moves:
            if move.receiver_id == row.team_id and move.kind in {"sale", "clause", "immediateSale"}:
                sale_in += move.amount
        realized = sale_in - sold_cost
        out.append(
            ManagerBudget(
                team_id=row.team_id,
                name=row.name,
                position=row.position,
                points=row.points,
                team_value=row.team_value,
                team_value_inc=row.team_value_inc,
                team_size=row.team_size,
                cash=int(cash),
                cash_raw=int(raw),
                cash_is_estimate=not is_me,
                max_bid=estimate_max_bid(int(cash), row.team_value, max_bid_rule),
                spent=spent,
                income=income,
                book_value=book,
                unrealized=row.team_value - book,
                realized=realized,
                overdraft=overdraft,
                listed=listed.get(row.team_id, 0),
                listed_count=listed_n.get(row.team_id, 0),
                confidence=_confidence(int(raw), is_me, recon_error),
                is_me=is_me,
            )
        )
    out.sort(key=lambda b: b.wealth, reverse=True)
    return out, start


def snapshot_path():
    return settings.data_dir / "budget.json"


def save_snapshot(budgets: list[ManagerBudget], start: int) -> None:
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "start_money": start,
        "managers": [asdict(b) for b in budgets],
    }
    path = snapshot_path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_previous_cash() -> dict[int, int]:
    path = snapshot_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, int] = {}
    for row in data.get("managers") or []:
        try:
            out[int(row["team_id"])] = int(row.get("cash_raw", row["cash"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out
