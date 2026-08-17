"""Alertas que el bot manda solo: te clavan, gangas nuevas, bajas, vigilancia."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import state
from .market import money
from .predictor import predict
from .snap import Snap

COOLDOWN = 4 * 3600
MARKET_SOON = 90 * 60


def _sent() -> dict:
    raw = state.get("alert_sent") or {}
    return raw if isinstance(raw, dict) else {}


def _mark(key: str) -> None:
    data = _sent()
    data[key] = int(time.time())
    # no crecer sin límite
    if len(data) > 80:
        keep = sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:50]
        data = dict(keep)
    state.set_value("alert_sent", data)


def _fresh(key: str) -> bool:
    ts = _sent().get(key)
    if not ts:
        return True
    return time.time() - float(ts) > COOLDOWN


def watchlist() -> list[int]:
    raw = state.get("watchlist") or []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def watch_add(player_id: int) -> bool:
    ids = watchlist()
    if player_id in ids:
        return False
    ids.append(player_id)
    state.set_value("watchlist", ids)
    return True


def watch_remove(player_id: int) -> bool:
    ids = [i for i in watchlist() if i != player_id]
    changed = ids != watchlist()
    state.set_value("watchlist", ids)
    return changed


def clause_hunters(snap: Snap, clause: int) -> list[str]:
    return [b.name for b in snap.budgets if not b.is_me and b.cash >= clause]


def scan(snap: Snap) -> list[tuple[str, list[tuple[str, str]] | None]]:
    """Nuevos avisos desde el último ciclo. Cada clave tiene cooldown."""
    out: list[tuple[str, list[tuple[str, str]] | None]] = []
    prev = state.get("alert_prev") or {}
    if not isinstance(prev, dict):
        prev = {}
    first = not prev
    old_listings = set(prev.get("listings") or [])
    old_injured = set(prev.get("injured") or [])
    old_afford = set(prev.get("afford") or [])
    old_threats = prev.get("threats") or {}

    listed = {item.player_id: item for item in snap.listings}

    def _snapshot() -> dict:
        return {
            "listings": [item.player_id for item in snap.listings],
            "injured": [
                p.id
                for p in snap.squad
                if p.is_injured_or_suspended or p.is_doubt or p.starter_role == "out"
            ],
            "afford": [t.player.id for t in snap.targets if t.source == "clause" and t.affordable],
            "threats": {
                str(p.id): len(clause_hunters(snap, int(p.clause)))
                for p in snap.squad
                if p.clause
            },
        }

    if first:
        state.set_value("alert_prev", _snapshot())
        return []

    # 1) Cláusula asequible que mejora el XI y antes no podías
    for t in snap.targets:
        if t.source != "clause" or not t.affordable or t.extra_xp < 0.6:
            continue
        key = f"afford:{t.player.id}"
        if t.player.id in old_afford or not _fresh(key):
            continue
        _mark(key)
        out.append(
            (
                "🚨 <b>Ya te llega la cláusula</b>\n"
                f"{t.player.name} te suma {t.extra_xp:+.1f} pts al XI "
                f"por {money(t.cost)}.",
                [(f"Cláusula {t.player.name} {money(t.cost)}", f"askclause:{t.player.id}:{t.cost}")],
            )
        )

    # 2) Un rival acaba de poder pagarte un crack
    for p in snap.squad:
        if not p.clause or predict(p) < 3.5:
            continue
        hunters = clause_hunters(snap, int(p.clause))
        if not hunters:
            continue
        prev_n = int(old_threats.get(str(p.id), 0) or 0)
        if len(hunters) <= prev_n:
            continue
        key = f"threat:{p.id}:{len(hunters)}"
        if not _fresh(key):
            continue
        _mark(key)
        out.append(
            (
                "🛡️ <b>Te pueden clavar</b>\n"
                f"{p.name} (cláusula {money(p.clause)}) lo pagan: "
                + ", ".join(hunters[:4])
                + ".",
                [(f"Vender {p.name}", f"sell:{p.id}:{max(int(p.price * 0.98 / 1000) * 1000, 1)}")],
            )
        )

    # 3) Baja nueva en tu plantilla
    for p in snap.squad:
        if not (p.is_injured_or_suspended or p.is_doubt or p.starter_role == "out"):
            continue
        if p.id in old_injured:
            continue
        key = f"down:{p.id}:{p.status}:{p.starter_role}"
        if not _fresh(key):
            continue
        _mark(key)
        note = p.status_info or p.status or p.starter_role
        out.append(
            (
                f"{p.status_emoji} <b>{p.name} en duda / fuera</b>\n{note}\n"
                "Recalculo el once.",
                [("⚽ Once", "cmd:alineacion")],
            )
        )

    # 4) Mercado que cierra pronto y te interesa
    now = datetime.now(timezone.utc)
    for t in snap.targets[:12]:
        listing = t.listing
        if listing is None or not t.affordable or t.expected < 3.2:
            continue
        left = (listing.until - now).total_seconds()
        if left > MARKET_SOON or left < 0:
            continue
        key = f"close:{listing.player_id}"
        if not _fresh(key):
            continue
        _mark(key)
        mins = max(int(left // 60), 1)
        out.append(
            (
                f"⏰ <b>{t.player.name} cierra en {mins} min</b>\n"
                f"{t.via} {money(t.cost)} · {t.expected:.1f} pts.",
                [
                    (f"Pujar {t.player.name}", f"bid:{t.player.id}:{(t.bids or {}).get('minima') or t.cost}"),
                    (f"Al cierre si vacío", f"snipe:{t.player.id}:{(t.bids or {}).get('minima') or t.cost}"),
                ],
            )
        )

    # 5) Vigilados: aparecen en mercado o ya pagas cláusula
    for pid in watchlist():
        p = snap.catalog.get(pid)
        if not p:
            continue
        listing = listed.get(pid)
        target = next((t for t in snap.targets if t.player.id == pid), None)
        if listing and pid not in old_listings:
            key = f"watch-mkt:{pid}"
            if _fresh(key):
                _mark(key)
                out.append(
                    (
                        f"👀 <b>{p.name} está en el mercado</b>\n"
                        f"{money(listing.price)}.",
                        [(f"Pujar {p.name}", f"bid:{pid}:{listing.price}")],
                    )
                )
        if target and target.source == "clause" and target.affordable:
            key = f"watch-cl:{pid}"
            if _fresh(key):
                _mark(key)
                out.append(
                    (
                        f"👀 <b>Ya puedes clavar a {p.name}</b>\n{money(target.cost)}.",
                        [(f"Cláusula {p.name} {money(target.cost)}", f"askclause:{pid}:{target.cost}")],
                    )
                )

    # 6) Oferta nueva
    for off in snap.offers:
        key = f"offer:{off.id}"
        if not _fresh(key):
            continue
        _mark(key)
        names = ", ".join(snap.catalog[i].name for i in off.player_ids if i in snap.catalog) or str(off.player_ids)
        out.append(
            (
                f"📥 <b>Oferta de {off.from_name}</b>\n{money(off.amount)} por {names}.",
                [
                    (f"Aceptar {money(off.amount)}", f"accept:{off.id}"),
                    ("Rechazar", f"reject:{off.id}"),
                ],
            )
        )

    state.set_value("alert_prev", _snapshot())
    return out[:6]
