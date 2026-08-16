from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from biwenger.client import BiwengerClient
from biwenger.services import (
    apply_bid,
    apply_clause,
    apply_lineup,
    apply_offer,
    apply_sale,
    budget_report,
    build_lineup,
    calendar_text,
    clause_menu,
    clause_report,
    confirm_clause,
    daily_briefing,
    edge_report,
    intel_report,
    market_report,
    maybe_auto_lineup,
    parse_position,
    schedule_close_bid,
    sell_report,
    snipe_list_text,
    squad_text,
    standings_text,
)
from biwenger.settings import set_telegram_chat_id, settings
from biwenger import state
from bot.visual import auto_html, chunk, mode_html

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TZ = ZoneInfo("Europe/Madrid")

HELP = (
    "🤖 <b>Van Nistelrooy · Gestor Biwenger</b>\n"
    "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
    "💬 Escríbeme en normal:\n"
    "«qué once pongo» · «un clausulazo de defensa»\n"
    "«cuánto tiene Moradona» · «pújame al cierre por Mariano»\n"
    "\n"
    f"{mode_html(settings.dry_run)}\n"
    "Yo recomiendo. Tú confirmas con un botón.\n"
    "\n"
    "⚡ /ventaja — plan para ganar hoy\n"
    "⚽ /alineacion — XI + capitán\n"
    "💰 /mercado — gangas y cláusulas\n"
    "🔓 /clausulas — buscar por posición\n"
    "💶 /presupuesto — caja de toda la liga\n"
    "📰 /previa — AS, SofaScore, lesiones\n"
    "🎯 /pujas — auto-pujas al cierre\n"
    "👥 /equipo  ·  ⏱️ /vender  ·  📅 /calendario\n"
    "🏆 /clasificacion  ·  📋 /resumen"
)

MENU = [
    ("ventaja", "Plan para ganar hoy"),
    ("alineacion", "Once óptimo de la jornada"),
    ("mercado", "Fichajes explicados"),
    ("clausulas", "Clausulazos por posición"),
    ("presupuesto", "Dinero de toda la liga"),
    ("vender", "Candidatos a vender"),
    ("equipo", "Plantilla y saldo"),
    ("calendario", "Próximos rivales"),
    ("clasificacion", "Tabla de la liga"),
    ("previa", "Lesiones, onces AS y SofaScore"),
    ("resumen", "Briefing de ahora"),
    ("auto", "Auto-alineación"),
    ("pujas", "Pujas al cierre programadas"),
    ("help", "Ayuda"),
]


def _base() -> str:
    return f"{API}/bot{settings.telegram_bot_token}"


def _keyboard(buttons: list[tuple[str, str]] | None) -> dict | None:
    if not buttons:
        return None
    rows: list[list[dict]] = []
    row: list[dict] = []
    for text, data in buttons:
        row.append({"text": text, "callback_data": data})
        wide = len(text) > 22
        if wide or len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def send_message(text: str, buttons: list[tuple[str, str]] | None = None, chat_id: str | None = None) -> None:
    if not settings.telegram_bot_token:
        logger.info("Telegram no configurado:\n%s", text)
        return
    target = chat_id or settings.telegram_chat_id
    if not target:
        logger.warning("Sin TELEGRAM_CHAT_ID. Mensaje no enviado.")
        return
    pieces = chunk(auto_html(text))
    for i, piece in enumerate(pieces):
        payload: dict = {
            "chat_id": target,
            "text": piece,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if i == len(pieces) - 1:
            kb = _keyboard(buttons)
            if kb:
                payload["reply_markup"] = kb
        resp = requests.post(f"{_base()}/sendMessage", json=payload, timeout=15)
        if resp.status_code != 200:
            logger.error("Telegram sendMessage: %s", resp.text[:240])


def answer_callback(callback_id: str, text: str | None = None) -> None:
    payload: dict = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text[:180]
    try:
        requests.post(f"{_base()}/answerCallbackQuery", json=payload, timeout=10)
    except requests.RequestException as exc:
        logger.warning("answerCallbackQuery: %s", exc)


def set_commands() -> None:
    try:
        requests.post(
            f"{_base()}/setMyCommands",
            json={"commands": [{"command": c, "description": d} for c, d in MENU]},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("setMyCommands: %s", exc)


def allowed(chat_id: int | str) -> bool:
    if not settings.telegram_chat_id:
        return True
    return str(chat_id) == str(settings.telegram_chat_id)


def handle_command(text: str, client: BiwengerClient) -> tuple[str, list[tuple[str, str]] | None]:
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/token":
        if len(parts) < 2:
            return "Uso: /token <satellizer_token>", None
        client.update_token(parts[1])
        return "✅ Token actualizado. Borra este mensaje del chat.", None

    if cmd in {"/start", "/help"}:
        buttons = [
            ("⚡ Ventaja", "cmd:ventaja"),
            ("⚽ Once", "cmd:alineacion"),
            ("💰 Mercado", "cmd:mercado"),
            ("🔓 Cláusulas", "cmd:clausulas"),
            ("💶 Dinero", "cmd:presupuesto"),
            ("📰 Previa", "cmd:previa"),
            ("👥 Equipo", "cmd:equipo"),
            ("🎯 Pujas", "cmd:pujas"),
        ]
        return HELP, buttons

    if cmd in {"/ask", "/pregunta"}:
        from biwenger.converse import handle_chat

        rest = text.strip().split(maxsplit=1)
        if len(rest) < 2:
            return "Pregúntame algo. Ejemplo: /ask puedo clavar a Tenaglia", None
        return handle_chat(rest[1], client)

    if cmd in {"/ventaja", "/edge", "/plan"}:
        return edge_report(client)
    if cmd == "/alineacion":
        msg, buttons, _ = build_lineup(client)
        return msg, buttons
    if cmd in {"/mercado", "/gangas"}:
        return market_report(client)
    if cmd == "/clausulas":
        pos = parse_position(parts[1]) if len(parts) > 1 else None
        if pos is None and len(parts) == 1:
            return clause_menu()
        if pos is None and len(parts) > 1:
            return "Posición no reconocida. Prueba: por, def, med, del.", None
        return clause_report(client, pos)
    if cmd in {"/presupuesto", "/finanzas", "/dinero"}:
        return budget_report(client)
    if cmd == "/vender":
        return sell_report(client)
    if cmd == "/equipo":
        return squad_text(client), None
    if cmd == "/calendario":
        return calendar_text(client), None
    if cmd == "/clasificacion":
        return standings_text(client), None
    if cmd in {"/previa", "/intel", "/lesiones", "/noticias"}:
        return intel_report(client)
    if cmd == "/resumen":
        return daily_briefing(client)
    if cmd in {"/pujas", "/cierre"}:
        return snipe_list_text(), None
    if cmd == "/auto":
        on = bool(state.get("auto_lineup"))
        text_msg = (
            "⚙️ Auto-alineación: "
            + ("ON (pone el XI ~4h antes del primer partido)" if on else "OFF")
            + "\nSigue respetando DRY_RUN. Si DRY_RUN=true solo simula."
        )
        label = "Desactivar auto-alineación" if on else "Activar auto-alineación"
        value = "off" if on else "on"
        return text_msg, [(label, f"toggle:auto_lineup:{value}")]

    return "No conozco ese comando. /help", None


def handle_callback(data: str, client: BiwengerClient) -> tuple[str, list[tuple[str, str]] | None]:
    if data.startswith("cmd:"):
        mapping = {
            "ventaja": "/ventaja",
            "alineacion": "/alineacion",
            "mercado": "/mercado",
            "clausulas": "/clausulas",
            "presupuesto": "/presupuesto",
            "equipo": "/equipo",
            "vender": "/vender",
            "calendario": "/calendario",
            "previa": "/previa",
            "resumen": "/resumen",
            "pujas": "/pujas",
        }
        key = data.split(":", 1)[1]
        return handle_command(mapping.get(key, "/help"), client)

    if data.startswith("clpos:"):
        raw = data.split(":", 1)[1]
        if raw == "0":
            return clause_report(client, None)
        try:
            from biwenger.models import Position

            return clause_report(client, Position(int(raw)))
        except ValueError:
            return clause_menu()

    if data == "apply:lineup":
        return apply_lineup(client), None

    if data.startswith("askclause:"):
        _, pid, amount = data.split(":")
        return confirm_clause(client, int(pid), int(amount))

    if data.startswith("clause:"):
        _, pid, amount = data.split(":")
        return apply_clause(client, int(pid), int(amount)), None

    if data.startswith("snipe:"):
        _, pid, amount = data.split(":")
        return schedule_close_bid(client, int(pid), int(amount)), None

    if data.startswith("unsnipe:"):
        from biwenger import snipe

        pid = int(data.split(":")[1])
        ok = snipe.cancel(pid)
        return ("Cancelada." if ok else "No había ninguna pendiente."), None

    if data.startswith("bid:"):
        _, pid, amount = data.split(":")
        return apply_bid(client, int(pid), int(amount)), None

    if data.startswith("sell:"):
        _, pid, price = data.split(":")
        return apply_sale(client, int(pid), int(price)), None

    if data.startswith("accept:"):
        return apply_offer(client, int(data.split(":")[1]), True), None

    if data.startswith("reject:"):
        return apply_offer(client, int(data.split(":")[1]), False), None

    if data.startswith("toggle:auto_lineup:"):
        value = data.split(":")[-1] == "on"
        state.set_value("auto_lineup", value)
        return handle_command("/auto", client)

    return "Acción desconocida.", None


def get_updates(offset: int | None, timeout: int = 25) -> list[dict]:
    resp = requests.get(
        f"{_base()}/getUpdates",
        params={"offset": offset, "timeout": timeout},
        timeout=timeout + 10,
    )
    resp.raise_for_status()
    return resp.json().get("result") or []


def run_once_jobs(client: BiwengerClient, last_briefing_date: str | None) -> str | None:
    """Devuelve la nueva fecha de briefing si se envió, o la misma."""
    now = datetime.now(TZ)
    today = now.date().isoformat()
    if now.hour == settings.daily_briefing_hour and last_briefing_date != today:
        text, buttons = daily_briefing(client)
        send_message(text, buttons)
        last_briefing_date = today
        logger.info("Briefing diario enviado")
    try:
        notice = maybe_auto_lineup(client)
    except Exception:
        logger.exception("auto-lineup")
        notice = None
    if notice:
        send_message(notice)
    try:
        from biwenger.snipe import fire

        for note in fire(client):
            send_message("🎯 " + note)
    except Exception:
        logger.exception("snipe")
    return last_briefing_date


def run_bot(client: BiwengerClient | None = None) -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")
    client = client or BiwengerClient()
    client.login()
    set_commands()
    send_message(
        "🟢 <b>Bot en marcha</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"{mode_html(settings.dry_run)}\n"
        "Dime «ventaja» o pulsa un botón."
    )
    logger.info("Bot Telegram escuchando")

    offset: int | None = None
    last_briefing: str | None = None
    last_job_check = 0.0

    while True:
        try:
            updates = get_updates(offset)
        except requests.RequestException as exc:
            logger.warning("getUpdates: %s", exc)
            time.sleep(3)
            continue

        now = time.time()
        if now - last_job_check > 60:
            try:
                last_briefing = run_once_jobs(client, last_briefing)
            except Exception:
                logger.exception("jobs")
            last_job_check = now

        for upd in updates:
            offset = int(upd["update_id"]) + 1
            try:
                _dispatch(upd, client)
            except Exception:
                logger.exception("update %s", upd.get("update_id"))


def _dispatch(upd: dict, client: BiwengerClient) -> None:
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        if not settings.telegram_chat_id:
            set_telegram_chat_id(str(chat_id))
            logger.info("Chat autorizado automáticamente: %s", chat_id)
        if not allowed(chat_id):
            return
        text = msg.get("text") or ""
        if not text.startswith("/"):
            from biwenger.converse import handle_chat

            reply, buttons = handle_chat(text, client)
            send_message(reply, buttons)
            return
        reply, buttons = handle_command(text, client)
        send_message(reply, buttons)
        return

    if "callback_query" in upd:
        cb = upd["callback_query"]
        chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
        if chat_id and not allowed(chat_id):
            answer_callback(cb["id"], "No autorizado")
            return
        data = cb.get("data") or ""
        answer_callback(cb["id"])
        reply, buttons = handle_callback(data, client)
        send_message(reply, buttons)
