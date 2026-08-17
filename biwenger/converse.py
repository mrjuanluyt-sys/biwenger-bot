"""Análisis conversacional: preguntas en español, no solo comandos."""
from __future__ import annotations

import logging
import re
import unicodedata

from . import alerts, state
from .client import BiwengerClient
from .explain import POS_PLURAL, POS_WORD, _intel_phrase, explain_target
from .market import filter_position, money, pick_board, sell_candidates
from .models import ManagerBudget, Player, Position
from .predictor import predict
from .services import _target_button, parse_position
from .settings import settings
from .snap import Snap, gather

logger = logging.getLogger(__name__)

Button = tuple[str, str]
STOP = {
    "el", "la", "los", "las", "un", "una", "de", "del", "al", "a", "y", "o",
    "que", "es", "en", "mi", "mis", "tu", "me", "te", "se", "lo", "le", "por",
    "con", "para", "como", "mas", "qué", "cómo", "cuanto", "cuánto",
}


def fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfkd.lower() if unicodedata.category(c) != "Mn")


def detect_position(text: str) -> Position | None:
    folded = fold(text)
    for token in ("porteros", "portero", "defensas", "defensa", "centrocampistas",
                  "centrocampista", "medios", "medio", "delanteros", "delantero"):
        if re.search(rf"\b{token}\b", folded):
            pos = parse_position(token)
            if pos:
                return pos
    return None


def _player_hits(text_folded: str, player: Player) -> int:
    name = fold(player.name)
    if len(name) < 4:
        return 0
    if name in text_folded:
        return len(name) + 5
    parts = [p for p in name.split() if len(p) >= 4]
    hits = [p for p in parts if p in text_folded]
    if hits and (len(hits) == len(parts) or any(len(p) >= 5 for p in hits)):
        return sum(len(p) for p in hits)
    return 0


def match_player(text: str, catalog: dict[int, Player]) -> Player | None:
    folded = fold(text)
    best: tuple[int, Player] | None = None
    for player in catalog.values():
        score = _player_hits(folded, player)
        if score and (best is None or score > best[0]):
            best = (score, player)
    return best[1] if best else None


def match_players(text: str, catalog: dict[int, Player], limit: int = 3) -> list[Player]:
    folded = fold(text)
    ranked: list[tuple[int, Player]] = []
    for player in catalog.values():
        score = _player_hits(folded, player)
        if score:
            ranked.append((score, player))
    ranked.sort(key=lambda x: x[0], reverse=True)
    out: list[Player] = []
    seen: set[int] = set()
    for _score, player in ranked:
        if player.id in seen:
            continue
        seen.add(player.id)
        out.append(player)
        if len(out) >= limit:
            break
    return out


def match_manager(text: str, budgets: list[ManagerBudget]) -> ManagerBudget | None:
    folded = fold(text)
    best: tuple[int, ManagerBudget] | None = None
    for row in budgets:
        name = fold(row.name)
        tokens = [t for t in re.findall(r"[a-z0-9]+", name) if len(t) >= 4 and t not in STOP]
        if not tokens:
            compact = re.sub(r"[^a-z0-9]+", "", name)
            if len(compact) >= 4 and compact in folded:
                score = len(compact)
                if best is None or score > best[0]:
                    best = (score, row)
            continue
        if all(t in folded for t in tokens):
            score = sum(len(t) for t in tokens)
            if best is None or score > best[0]:
                best = (score, row)
    return best[1] if best else None


def detect_intent(text: str) -> str:
    q = fold(text)
    if re.search(r"\b(hola|buenas|hey|que tal|buenos dias|buenas tardes)\b", q):
        return "greet"
    if re.search(r"\b(compar|versus|\bvs\b|mejor que|o a )\b", q) or re.search(r"\b\w+\s+o\s+\w+", q):
        return "compare"
    if re.search(r"(quien me (puede )?clavar|me (pueden )?clavar|proteger|escudo|me clavan)", q):
        return "threat"
    if re.search(r"\b(vigila|avisame|avisame de|alerta de|watch)\b", q):
        return "watch"
    if re.search(r"\b(alertas|avisos)\b", q):
        return "alerts"
    if re.search(r"\b(alineacion|alineación|once|titulares|capitan|capitán)\b", q):
        return "lineup"
    if re.search(r"\b(calendario|proximo rival|próximo rival|partidos)\b", q):
        return "calendar"
    if re.search(r"\b(clasificacion|clasificación|tabla|ranking)\b", q):
        return "table"
    if re.search(r"\b(presupuesto|saldo|dinero|caja|liquidez|millon|rico|pobre|gast)\b", q):
        return "budget"
    if re.search(r"\b(vendo|vendes|vender|vendemos|soltar|soltarlo|en venta)\b", q):
        return "sell"
    if re.search(r"\b(clausula|clausulazo|clavar|clavo|clavamos)\b", q):
        return "clause"
    if re.search(r"\b(al cierre|pujame|pújame|auto.?puja|si nadie puja)\b", q):
        return "snipe"
    if re.search(r"\b(mercado|ganga|chollo|fichar|fichaje|comprar|pujar)\b", q):
        return "market"
    if re.search(r"\b(equipo|plantilla|mis jugadores)\b", q):
        return "squad"
    if re.search(r"\b(ventaja|ganar|diferencial|capitan|capitán|hueco|plan)\b", q):
        return "edge"
    if re.search(r"\b(lesion|lesionado|sancion|sancionado|titular|once probable|previa|noticia|sofascore|picas)\b", q):
        return "intel"
    if re.search(r"\b(resumen|que hago|qué hago|consejo)\b", q):
        return "briefing"
    if re.search(r"\b(ese|esa|este|esta|lo ficho|lo clavo|y ese|y este)\b", q):
        return "followup"
    return "chat"


def _remember(player_id: int | None = None, manager_id: int | None = None) -> None:
    if player_id is not None:
        state.set_value("last_player_id", player_id)
    if manager_id is not None:
        state.set_value("last_manager_id", manager_id)


def _advice_player(player: Player, snap: Snap) -> tuple[str, list[Button] | None]:
    _remember(player_id=player.id)
    buttons: list[Button] = []
    mine = next((p for p in snap.squad if p.id == player.id), None)
    target = next((t for t in snap.targets if t.player.id == player.id), None)
    xp = predict(player)
    pos = POS_WORD.get(player.position, player.position.label.lower())
    lines = [f"{player.status_emoji} {player.name}, {pos} del {player.team_name or 'sin club'}."]
    if mine:
        lines.append(f"Ya es tuyo. Lo pagaste por {money(mine.buy_price or player.price)} y ahora vale {money(player.price)}.")
        lines.append(f"Esta jornada esperamos {xp:.1f} puntos.")
        intel_line = _intel_phrase(player)
        if intel_line:
            lines.append(intel_line)
        tips = [t for t in sell_candidates(snap.squad, limit=20) if t.player.id == player.id]
        if tips:
            lines.append(f"Yo lo pondría en venta: {tips[0].reason}.")
            buttons.append((f"Vender {player.name} {money(tips[0].suggested_price)}", f"sell:{player.id}:{tips[0].suggested_price}"))
        else:
            lines.append("No urge venderlo.")
        return "\n".join(lines), buttons or None
    if target:
        lines.extend(explain_target(target, snap.balance))
        btn = _target_button(target)
        if btn:
            buttons.append(btn)
        return "\n".join(lines).strip(), buttons or None
    if player.owner_name and player.clause:
        lack = player.clause - snap.balance
        lines.append(f"Es de {player.owner_name}. La cláusula está en {money(player.clause)} (vale {money(player.price)}).")
        lines.append(f"Esperamos {xp:.1f} puntos.")
        if lack > 0:
            lines.append(f"Ahora mismo te faltan {money(lack)} para clavarlo.")
            for tip in sell_candidates(snap.squad, limit=8):
                if tip.player.id == player.id:
                    continue
                if tip.suggested_price >= lack:
                    lines.append(
                        f"Si vendes a {tip.player.name} (~{money(tip.suggested_price)}) te llega. "
                        f"{tip.reason}."
                    )
                    buttons.append(
                        (f"Vender {tip.player.name} {money(tip.suggested_price)}", f"sell:{tip.player.id}:{tip.suggested_price}")
                    )
                    break
        else:
            lines.append("Sí podrías pagar la cláusula.")
            buttons.append((f"Cláusula {player.name} {money(player.clause)}", f"askclause:{player.id}:{player.clause}"))
        return "\n".join(lines), buttons or None
    lines.append(f"Vale {money(player.price)}. Esperamos {xp:.1f} puntos. No está a la venta ni tiene cláusula a tiro.")
    return "\n".join(lines), None


def _compare(a: Player, b: Player, snap: Snap) -> tuple[str, list[Button] | None]:
    _remember(player_id=a.id)
    xa, xb = predict(a), predict(b)
    lines = [
        f"⚖️ <b>{a.name} vs {b.name}</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"{a.status_emoji} {a.name}: {xa:.1f} pts · {money(a.price)}"
        + (f" · cláusula {money(a.clause)}" if a.clause else "")
        + (f" · de {a.owner_name}" if a.owner_name and not a.is_owned_by_me else "")
        + (" · TÚ" if a.is_owned_by_me or any(p.id == a.id for p in snap.squad) else ""),
        f"{b.status_emoji} {b.name}: {xb:.1f} pts · {money(b.price)}"
        + (f" · cláusula {money(b.clause)}" if b.clause else "")
        + (f" · de {b.owner_name}" if b.owner_name and not b.is_owned_by_me else "")
        + (" · TÚ" if b.is_owned_by_me or any(p.id == b.id for p in snap.squad) else ""),
        "",
    ]
    winner = a if xa > xb else b
    gap = abs(xa - xb)
    if gap < 0.25:
        lines.append("Están muy parejos. Quédate con el más barato o el que menos gente tenga.")
    else:
        lines.append(f"Para el once, yo me quedo con {winner.name} ({gap:.1f} pts más).")
    if a.position == b.position:
        best = max(
            (predict(p) for p in snap.squad if p.position == a.position and not p.is_injured_or_suspended),
            default=0.0,
        )
        for p, xp in ((a, xa), (b, xb)):
            if xp > best + 0.4 and not any(s.id == p.id for s in snap.squad):
                lines.append(f"{p.name} mejoraría tu {a.position.label} actual ({best:.1f} pts).")
    buttons: list[Button] = []
    for p in (a, b):
        t = next((x for x in snap.targets if x.player.id == p.id), None)
        if t:
            btn = _target_button(t)
            if btn:
                buttons.append(btn)
    return "\n".join(lines), buttons or None


def _threats(snap: Snap) -> tuple[str, list[Button] | None]:
    lines = [
        "🛡️ <b>Quién te puede clavar</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
    ]
    buttons: list[Button] = []
    hits = 0
    for p in sorted(snap.squad, key=lambda x: predict(x), reverse=True):
        if not p.clause:
            continue
        hunters = alerts.clause_hunters(snap, int(p.clause))
        if not hunters:
            continue
        hits += 1
        lines.append(f"{p.status_emoji} {p.name} · cláusula {money(p.clause)}")
        lines.append("   lo pagan: " + ", ".join(hunters[:5]))
        if predict(p) >= 3.5:
            price = max(int(round(p.price * 0.98 / 1000) * 1000), 1)
            buttons.append((f"Vender {p.name} {money(price)}", f"sell:{p.id}:{price}"))
    if not hits:
        lines.append("Nadie de la liga te llega a las cláusulas de tus jugadores útiles.")
    return "\n".join(lines), buttons or None


def _watch_answer(player: Player | None, snap: Snap) -> tuple[str, list[Button] | None]:
    if player:
        added = alerts.watch_add(player.id)
        _remember(player_id=player.id)
        verb = "Empiezo a vigilar" if added else "Ya lo vigilaba"
        return (
            f"👀 {verb} a {player.name}.\n"
            "Te aviso si sale al mercado o si te llega la cláusula.",
            [("📋 Vigilados", "cmd:alertas")],
        )
    ids = alerts.watchlist()
    if not ids:
        return "No vigilo a nadie. Dime «vigila a Pedri».", None
    lines = ["👀 <b>Vigilados</b>", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    for pid in ids:
        p = snap.catalog.get(pid)
        lines.append(f"  • {p.name if p else pid}")
    return "\n".join(lines), None


def _advice_manager(row: ManagerBudget) -> tuple[str, list[Button] | None]:
    _remember(manager_id=row.team_id)
    src = "caja real" if not row.cash_is_estimate else "caja estimada"
    lines = [
        f"{row.position}º {row.name}.",
        f"{src}: {money(row.cash)}." if not row.overdraft else f"Caja: 0€. Fichó {money(row.overdraft)} por encima del inicial + ventas.",
        f"Plantilla {money(row.team_value)} · patrimonio {money(row.wealth)} · techo de puja {money(row.max_bid)}.",
    ]
    if row.cash >= 10_000_000:
        lines.append("Puede pagar cláusulas gordas (10M+).")
    elif row.cash >= 1_000_000:
        lines.append("Puede clavar alguna cláusula mediana.")
    else:
        lines.append("Casi no puede pagar cláusulas: solo pujar con el 25% del equipo.")
    return "\n".join(lines), [("💶 Presupuesto de todos", "cmd:presupuesto")]


def _clause_answer(snap: Snap, pos: Position | None) -> tuple[str, list[Button] | None]:
    pool = [t for t in snap.targets if t.source == "clause"]
    pool = filter_position(pool, pos)
    board, watch = pick_board(pool, affordable_n=3, watch_n=1)
    word = POS_PLURAL[pos] if pos else "la liga"
    lines = [f"Los clausulazos de {word} que más te mejoran el once:", ""]
    buttons: list[Button] = []
    if not board:
        lines.append("No veo ninguno asequible que mejore de verdad.")
    for t in board:
        lines.extend(explain_target(t, snap.balance))
        btn = _target_button(t)
        if btn:
            buttons.append(btn)
        _remember(player_id=t.player.id)
    if watch:
        lines.append("Cuando ahorres:")
        lines.extend(explain_target(watch[0], snap.balance))
    buttons.extend([("🧤 POR", "clpos:1"), ("🛡️ DEF", "clpos:2"), ("⚙️ MED", "clpos:3"), ("🎯 DEL", "clpos:4")])
    return "\n".join(lines).strip(), buttons


def _market_answer(snap: Snap, pos: Position | None) -> tuple[str, list[Button] | None]:
    pool = filter_position(snap.targets, pos)
    board, _ = pick_board(pool, affordable_n=3, watch_n=1)
    lines = ["Esto es lo que más te mejora el once ahora mismo:", ""]
    buttons: list[Button] = []
    for t in board:
        lines.extend(explain_target(t, snap.balance))
        btn = _target_button(t)
        if btn:
            buttons.append(btn)
        _remember(player_id=t.player.id)
    if not board:
        lines.append("No hay nada claro a este precio.")
    return "\n".join(lines).strip(), buttons or None


def _lineup_answer(snap: Snap) -> tuple[str, list[Button] | None]:
    r = snap.lineup
    lines = [
        f"Yo pondría un {r.formation} (unos {r.total_expected:.1f} puntos esperados).",
        f"Tienes {money(snap.balance)} en el banco.",
        "",
    ]
    for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
        group = [p for p in r.starters if p.position == pos]
        if not group:
            lines.append(f"{pos.emoji} {pos.label}: no tienes a nadie. Es un hueco.")
            continue
        names = []
        for p in group:
            cap = " (capitán)" if r.captain and p.id == r.captain.id else ""
            names.append(f"{p.name}{cap} {r.expected.get(p.id, 0):.1f}")
        lines.append(f"{pos.emoji} {pos.label}: " + ", ".join(names))
    if r.formation.startswith("incompleto"):
        lines.append("")
        lines.append("No llegas a 11. Prioriza un portero y rellenar la línea más floja.")
    buttons = [] if r.formation.startswith("incompleto") else [("✅ Aplicar esta alineación", "apply:lineup")]
    return "\n".join(lines), buttons or None


def _facts(snap: Snap) -> str:
    lines = [
        f"Equipo {snap.team.name}. Saldo {money(snap.balance)}. Techo puja {money(snap.max_bid)}.",
        f"Jugadores: {len(snap.squad)}. Once sugerido {snap.lineup.formation} ({snap.lineup.total_expected:.1f} pts).",
        "Plantilla: " + ", ".join(f"{p.name} ({p.position.label}, xp {predict(p):.1f})" for p in snap.squad),
        "Cajas: " + "; ".join(
            f"{b.name} {money(b.cash)}{'*' if b.cash_is_estimate else ''}" for b in snap.budgets
        ),
        "Mejores fichajes: " + " | ".join(
            f"{t.player.name} {t.via} {money(t.cost)} xp {t.expected:.1f} ΔXI {t.extra_xp:+.1f}"
            for t in snap.targets[:8]
        ),
    ]
    return "\n".join(lines)


def _grok(question: str, facts: str) -> str | None:
    if not settings.xai_api_key:
        return None
    try:
        import requests

        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.xai_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.xai_model or "grok-4.5",
                "temperature": 0.3,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Eres el mánager asistente de una liga Biwenger. Hablas en español claro, "
                            "de tú, sin jerga innecesaria. SOLO usas los DATOS que te paso: no inventes "
                            "precios, cláusulas ni saldos. Si falta un dato, dilo. Máximo 18 líneas. "
                            "No ejecutes fichajes: recomienda y listo."
                        ),
                    },
                    {"role": "user", "content": f"DATOS DEL ANALIZADOR:\n{facts}\n\nPREGUNTA:\n{question}"},
                ],
            },
            timeout=40,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("Grok conversacional no disponible")
        return None


def handle_chat(text: str, client: BiwengerClient) -> tuple[str, list[Button] | None]:
    raw = (text or "").strip()
    if not raw:
        return "Dime qué quieres mirar: once, mercado, cláusulas, dinero de la liga o un jugador.", None

    snap = gather(client)
    intent = detect_intent(raw)
    pos = detect_position(raw)
    mentioned = match_players(raw, snap.catalog)
    player = mentioned[0] if mentioned else None
    manager = match_manager(raw, snap.budgets)
    if intent == "compare" and len(mentioned) < 2:
        intent = "chat"

    if intent == "followup" and not player:
        last = state.get("last_player_id")
        if last and int(last) in snap.catalog:
            player = snap.catalog[int(last)]
            intent = "player"
    if intent == "followup" and not manager:
        last_m = state.get("last_manager_id")
        if last_m:
            manager = next((b for b in snap.budgets if b.team_id == int(last_m)), None)
            intent = "manager"

    structured: tuple[str, list[Button] | None]
    if intent == "compare" and len(mentioned) >= 2:
        structured = _compare(mentioned[0], mentioned[1], snap)
    elif player and intent in {"chat", "followup", "market", "clause", "player", "sell"}:
        structured = _advice_player(player, snap)
    elif manager and intent in {"chat", "followup", "budget", "manager"}:
        structured = _advice_manager(manager)
    elif intent == "threat":
        structured = _threats(snap)
    elif intent == "watch":
        structured = _watch_answer(player, snap)
    elif intent == "alerts":
        structured = _watch_answer(None, snap)
    elif intent == "greet":
        structured = (
            "👋 <b>Dime qué quieres y lo miro</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "💬 «qué once pongo»\n"
            "🔓 «un clausulazo de defensa»\n"
            "💶 «cuánto tiene Moradona»\n"
            "🎯 «pújame al cierre por Mariano»\n"
            "⚡ «cómo gano hoy»",
            [
                ("⚡ Ventaja", "cmd:ventaja"),
                ("⚽ Once", "cmd:alineacion"),
                ("🔓 Cláusulas", "cmd:clausulas"),
                ("💶 Dinero", "cmd:presupuesto"),
            ],
        )
    elif intent == "lineup":
        structured = _lineup_answer(snap)
    elif intent == "squad":
        from .services import squad_text

        structured = (squad_text(client, snap), None)
    elif intent == "clause":
        structured = _clause_answer(snap, pos)
    elif intent == "market":
        structured = _market_answer(snap, pos)
    elif intent == "budget":
        from .services import budget_report

        structured = budget_report(client, snap)
    elif intent == "sell":
        from .services import sell_report

        structured = sell_report(client, snap)
    elif intent == "calendar":
        from .services import calendar_text

        structured = (calendar_text(client, snap), None)
    elif intent == "table":
        from .services import standings_text

        structured = (standings_text(client, snap), None)
    elif intent == "snipe":
        from .services import schedule_close_bid, snipe_list_text

        if player or (state.get("last_player_id") and "cierre" in fold(raw)):
            pid = player.id if player else int(state.get("last_player_id"))
            p = snap.catalog.get(pid)
            listing = next((t.listing for t in snap.targets if t.player.id == pid and t.listing), None)
            if listing is None:
                structured = (snipe_list_text() if not p else f"{p.name} no está en el mercado ahora.", None)
            else:
                amount = listing.price
                structured = (schedule_close_bid(client, pid, amount), None)
        else:
            structured = (snipe_list_text(), None)
    elif intent == "edge":
        from .services import edge_report

        structured = edge_report(client, snap)
    elif intent == "intel":
        from .services import intel_report

        structured = intel_report(client, snap)
    elif intent == "briefing":
        from .services import daily_briefing

        structured = daily_briefing(client, snap)
    else:
        structured = (
            "No te he pillado del todo. Prueba con un nombre (Pedri, Tenaglia), "
            "una posición (defensa, delantero) o pregunta por el dinero de un rival.",
            [
                ("⚽ Once", "cmd:alineacion"),
                ("💰 Mercado", "cmd:mercado"),
                ("🔓 Cláusulas", "cmd:clausulas"),
            ],
        )

    grok = _grok(raw, _facts(snap) + "\n\nRESPUESTA DEL ANALIZADOR:\n" + structured[0])
    if grok:
        return grok, structured[1]
    return structured
