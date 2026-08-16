"""Un ciclo: Telegram + pujas al cierre. Para GitHub Actions (gratis, 24/7)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from zoneinfo import ZoneInfo

from biwenger import state
from biwenger.client import BiwengerClient
from biwenger.snipe import fire
from biwenger.services import daily_briefing, maybe_auto_lineup
from biwenger.settings import settings
from bot import telegram_app as tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tick")
TZ = ZoneInfo("Europe/Madrid")


def drain_telegram(client: BiwengerClient) -> int:
    n = 0
    offset = None
    # Pasadas cortas: Actions no puede hacer long-poll de 30s.
    for _ in range(3):
        updates = tg.get_updates(offset, timeout=2)
        if not updates:
            break
        for upd in updates:
            offset = int(upd["update_id"]) + 1
            try:
                tg._dispatch(upd, client)
                n += 1
            except Exception:
                log.exception("update")
    if offset is not None:
        try:
            tg.get_updates(offset, timeout=0)
        except Exception:
            log.exception("ack offset")
    return n


def main() -> int:
    if not settings.telegram_bot_token:
        log.error("Falta TELEGRAM_BOT_TOKEN")
        return 1
    client = BiwengerClient()
    client.login()
    if not state.get("cloud_hello"):
        mode = "simulación" if settings.dry_run else "LIVE"
        tg.send_message(
            "☁️ <b>Bot 24/7 en marcha</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "Corro en GitHub Actions cada 5 min, aunque apagues el PC.\n"
            f"Modo: <b>{mode}</b>\n"
            "Respondo al escribirte (delay ≤ 5 min).\n"
            "Dime «ventaja» o pulsa un botón."
        )
        state.set_value("cloud_hello", True)
    n = drain_telegram(client)
    log.info("Telegram: %s updates", n)
    for note in fire(client):
        tg.send_message("🎯 " + note)
        log.info("%s", note)
    try:
        notice = maybe_auto_lineup(client)
        if notice:
            tg.send_message(notice)
    except Exception:
        log.exception("auto-lineup")
    now = datetime.now(TZ)
    today = now.date().isoformat()
    if now.hour == settings.daily_briefing_hour and state.get("last_briefing_date") != today:
        text, buttons = daily_briefing(client)
        tg.send_message(text, buttons)
        state.set_value("last_briefing_date", today)
        log.info("briefing enviado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
