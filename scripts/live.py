"""Escucha Telegram en un runner de Actions (~5 h 40 min) y se reencadena."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from biwenger import state
from biwenger.client import BiwengerClient
from biwenger.snipe import fire
from biwenger.services import daily_briefing, maybe_auto_lineup
from biwenger.settings import settings
from bot import telegram_app as tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("live")
TZ = ZoneInfo("Europe/Madrid")

# Dejar margen para persistir y lanzar el siguiente job (límite Actions = 6 h).
RUN_SECONDS = 5 * 3600 + 40 * 60
JOBS_EVERY = 45
PERSIST_EVERY = 180
RELOGIN_EVERY = 30 * 60


def persist_remote() -> None:
    token = os.environ.get("GITHUB_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    src = settings.data_dir / "state.json"
    if not token or not repo or not src.exists():
        return
    work = Path(tempfile.mkdtemp())
    (work / "state.json").write_bytes(src.read_bytes())
    env = os.environ.copy()
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, check=True, env=env, capture_output=True)
    try:
        git("init", "-q")
        git("checkout", "-q", "-b", "bot-state")
        git("add", "state.json")
        git("-c", "user.name=biwenger-bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-qm", "state")
        git("remote", "add", "origin", f"https://x-access-token:{token}@github.com/{repo}.git")
        git("push", "-fq", "origin", "bot-state:bot-state")
    except subprocess.CalledProcessError as exc:
        log.warning("persist: %s", exc.stderr.decode("utf-8", "replace")[:300] if exc.stderr else exc)


def run_jobs(client: BiwengerClient) -> None:
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


def main() -> int:
    if not settings.telegram_bot_token:
        log.error("Falta TELEGRAM_BOT_TOKEN")
        return 1
    client = BiwengerClient()
    client.login()
    if not state.get("live_hello_v2"):
        mode = "simulación" if settings.dry_run else "LIVE"
        tg.send_message(
            "⚡ <b>En directo ahora</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "Escríbeme y te contesto al momento.\n"
            f"Modo: <b>{mode}</b>\n"
            "Prueba: «ventaja» o /equipo"
        )
        state.set_value("live_hello_v2", True)
        persist_remote()

    deadline = time.time() + RUN_SECONDS
    offset: int | None = None
    stop = threading.Event()

    def background() -> None:
        jobs = BiwengerClient()
        try:
            jobs.login()
        except Exception:
            log.exception("jobs login")
            jobs = client
        last_login = time.time()
        while not stop.is_set() and time.time() < deadline:
            if time.time() - last_login > RELOGIN_EVERY:
                try:
                    jobs.login()
                except Exception:
                    log.exception("relogin")
                last_login = time.time()
            try:
                from biwenger.converse import gather

                gather(jobs, force=True)
            except Exception:
                log.exception("warm cache")
            try:
                run_jobs(jobs)
            except Exception:
                log.exception("jobs")
            persist_remote()
            stop.wait(JOBS_EVERY)

    threading.Thread(target=background, name="jobs", daemon=True).start()
    log.info("escuchando hasta %s", datetime.fromtimestamp(deadline, TZ).isoformat())

    while time.time() < deadline:
        try:
            updates = tg.get_updates(offset, timeout=25)
        except requests.RequestException as exc:
            log.warning("getUpdates: %s", exc)
            time.sleep(2)
            continue
        for upd in updates:
            offset = int(upd["update_id"]) + 1
            try:
                tg._dispatch(upd, client)
            except Exception:
                log.exception("update")

    stop.set()
    persist_remote()
    log.info("fin de turno")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
