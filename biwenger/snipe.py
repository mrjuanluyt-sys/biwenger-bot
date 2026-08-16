"""Pujas al cierre, solo si tú las pides y el jugador no tiene puja."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import state

WINDOW_BEFORE = 180  # dispara 3 min antes del until
WINDOW_AFTER = 45


def _all() -> list[dict[str, Any]]:
    raw = state.get("snipe_targets") or []
    return list(raw) if isinstance(raw, list) else []


def _save(items: list[dict[str, Any]]) -> None:
    state.set_value("snipe_targets", items)


def pending() -> list[dict[str, Any]]:
    return [t for t in _all() if t.get("status") == "pending"]


def add(player_id: int, name: str, amount: int, until_ts: int, seller_id: int | None) -> dict[str, Any]:
    items = [t for t in _all() if not (t.get("player_id") == player_id and t.get("status") == "pending")]
    target = {
        "player_id": int(player_id),
        "name": name,
        "amount": int(amount),
        "until": int(until_ts),
        "seller_id": seller_id,
        "status": "pending",
        "created": int(datetime.now(timezone.utc).timestamp()),
    }
    items.append(target)
    _save(items)
    return target


def cancel(player_id: int) -> bool:
    items = _all()
    found = False
    for t in items:
        if t.get("player_id") == player_id and t.get("status") == "pending":
            t["status"] = "cancelled"
            found = True
    if found:
        _save(items)
    return found


def _set_status(player_id: int, status: str) -> None:
    items = _all()
    for t in items:
        if t.get("player_id") == player_id and t.get("status") == "pending":
            t["status"] = status
    _save(items)


def due(now_ts: int | None = None) -> list[dict[str, Any]]:
    now = now_ts or int(datetime.now(timezone.utc).timestamp())
    ready = []
    for t in pending():
        left = int(t.get("until") or 0) - now
        if -WINDOW_AFTER <= left <= WINDOW_BEFORE:
            ready.append(t)
        elif left < -WINDOW_AFTER:
            _set_status(int(t["player_id"]), "missed")
    return ready


def fire(client) -> list[str]:
    """Ejecuta pujas debidas. No pujas si ya hay puja (nuestra o visible)."""
    from .market import money

    notes: list[str] = []
    ready = due()
    if not ready:
        return notes
    listings, balance, max_bid = client.get_market()
    listed = {item.player_id: item for item in listings}
    already = client.get_my_purchase_ids()
    for t in ready:
        pid = int(t["player_id"])
        name = t.get("name") or str(pid)
        amount = int(t["amount"])
        listing = listed.get(pid)
        if listing is None:
            _set_status(pid, "gone")
            notes.append(f"{name}: ya no está en el mercado. No pujé.")
            continue
        if pid in already:
            _set_status(pid, "skipped")
            notes.append(f"{name}: ya tenías puja. No repetí.")
            continue
        if listing.has_visible_bids:
            _set_status(pid, "skipped")
            notes.append(f"{name}: ya tiene {listing.bid_count} puja(s) visible(s). No entré.")
            continue
        cap = min(balance, max_bid) if max_bid else balance
        if amount > cap:
            _set_status(pid, "skipped")
            notes.append(f"{name}: {money(amount)} supera tu techo ({money(cap)}). No pujé.")
            continue
        client.place_bid(pid, amount, listing.seller_id)
        _set_status(pid, "done")
        verb = "Simulada" if client.cfg.dry_run else "Enviada"
        notes.append(f"{verb} puja al cierre por {name}: {money(amount)}.")
    return notes
