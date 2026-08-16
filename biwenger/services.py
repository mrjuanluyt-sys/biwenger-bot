from __future__ import annotations

from datetime import datetime, timezone

from .budget import (
    SEASON_START,
    START_MONEY,
    build_budgets,
    last_reset_epoch,
    load_previous_cash,
    parse_moves,
    save_snapshot,
)
from .client import BiwengerClient
from .edge import (
    apply_next_home,
    apply_ownership,
    best_targets_for_hole,
    calendar_edge,
    differentials,
    hole,
    ownership_label,
    pick_captain,
    price_falls,
    price_risers,
    shield,
    weak_rivals,
)
from .intel import enrich_catalog
from .explain import POS_PLURAL, POS_WORD, explain_target, intro_clauses, intro_gangas
from .lineup import LineupResult, best_lineup
from .market import Target, filter_position, find_targets, money, pick_board, sell_candidates
from .models import Player, Position, TeamState
from .predictor import predict
from .settings import settings

Button = tuple[str, str]


def _mode_tag() -> str:
    return "🧪 SIMULACIÓN" if settings.dry_run else "⚡ EN VIVO"


def _fitness(player: Player) -> str:
    if not player.fitness:
        return "—"
    return " ".join(str(x) for x in player.fitness[-5:])


def lineup_text(result: LineupResult, team: TeamState) -> str:
    lines = [
        f"⚽ Alineación  ·  {result.formation}  ·  {_mode_tag()}",
        f"Esperado: {result.total_expected:.1f} pts   saldo: {money(team.balance)}",
        "",
    ]
    for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
        group = [p for p in result.starters if p.position == pos]
        if not group:
            continue
        lines.append(f"{pos.emoji} {pos.label}")
        for p in group:
            cap = " Ⓒ" if result.captain and p.id == result.captain.id else ""
            xp = result.expected.get(p.id, 0.0)
            lines.append(f"  {p.name}{cap}  {xp:.1f} pts  {_fitness(p)}")
        lines.append("")
    if result.captain:
        own = ownership_label(result.captain, 13)
        lines.append(f"Capitán: {result.captain.name} (dobla puntos, {own})")
    current = team.lineup.formation if team.lineup else "sin alinear"
    lines.append(f"Ahora mismo: {current}")
    return "\n".join(lines).strip()


def lineup_buttons() -> list[Button]:
    return [("✅ Aplicar esta alineación", "apply:lineup")]


def build_lineup(client: BiwengerClient) -> tuple[str, list[Button], LineupResult]:
    team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    enrich_catalog(client, catalog)
    n_mgr = max(len({p.owner_id for p in catalog.values() if p.owner_id}), 1)
    apply_ownership(catalog, n_mgr)
    try:
        apply_next_home(catalog, client.get_team_fixtures(5))
    except Exception:
        pass
    result = best_lineup(squad)
    cap = pick_captain(result, n_mgr)
    if cap:
        result.captain = cap
    buttons = [] if result.formation.startswith("incompleto") else lineup_buttons()
    return lineup_text(result, team), buttons, result


def squad_text(client: BiwengerClient) -> str:
    team, squad, catalog = client.enrich_my_squad()
    enrich_catalog(client, catalog)
    lines = [
        f"👥 {team.name}  ·  {money(team.balance)}  ·  {team.points} pts  ·  {_mode_tag()}",
        f"{len(squad)} jugadores",
        "",
    ]
    for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
        group = [p for p in squad if p.position == pos]
        if not group:
            continue
        lines.append(f"{pos.emoji} {pos.label}")
        for p in sorted(group, key=lambda x: predict(x), reverse=True):
            xp = predict(p)
            trend = f"{p.price_trend_pct:+.1f}%"
            lines.append(
                f"  {p.status_emoji} {p.name}  {xp:.1f}  {money(p.price)}  {trend}"
            )
        lines.append("")
    return "\n".join(lines).strip()


POS_ALIASES = {
    "por": Position.GOALKEEPER,
    "portero": Position.GOALKEEPER,
    "porteros": Position.GOALKEEPER,
    "gk": Position.GOALKEEPER,
    "1": Position.GOALKEEPER,
    "def": Position.DEFENDER,
    "defensa": Position.DEFENDER,
    "defensas": Position.DEFENDER,
    "2": Position.DEFENDER,
    "med": Position.MIDFIELDER,
    "medio": Position.MIDFIELDER,
    "medios": Position.MIDFIELDER,
    "centrocampista": Position.MIDFIELDER,
    "centrocampistas": Position.MIDFIELDER,
    "3": Position.MIDFIELDER,
    "del": Position.FORWARD,
    "delantero": Position.FORWARD,
    "delanteros": Position.FORWARD,
    "4": Position.FORWARD,
}


def parse_position(raw: str | None) -> Position | None:
    if not raw:
        return None
    return POS_ALIASES.get(raw.strip().lower().lstrip("/"))


def _target_button(t: Target) -> Button | None:
    p = t.player
    if t.source == "clause" and t.affordable:
        return (f"Cláusula {p.name} {money(t.cost)}", f"askclause:{p.id}:{t.cost}")
    if t.bids:
        bid = t.bids.get("minima") or t.bids.get("competitiva") or 0
        if bid > 0:
            return (f"Pujar ahora {p.name}", f"bid:{p.id}:{bid}")
    return None


def _close_bid_button(t: Target) -> Button | None:
    if t.source == "clause" or not t.listing:
        return None
    amount = (t.bids or {}).get("minima") or t.listing.price
    if amount <= 0:
        return None
    return (f"Al cierre si vacío {t.player.name}", f"snipe:{t.player.id}:{amount}")


def _collect_targets(client: BiwengerClient, clause_only: bool = False) -> tuple[list[Target], int, int, dict[int, Player]]:
    _team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    enrich_catalog(client, catalog)
    apply_ownership(catalog, max(len({p.owner_id for p in catalog.values() if p.owner_id}), 1))
    try:
        apply_next_home(catalog, client.get_team_fixtures(5))
    except Exception:
        pass
    listings, balance, max_bid = client.get_market()
    if clause_only:
        spendable = max(balance - settings.budget_safety_margin, 0)
    else:
        spendable = min(balance, max_bid) if max_bid else balance
    targets = find_targets(listings, catalog, squad, spendable)
    if clause_only:
        targets = [t for t in targets if t.source == "clause"]
    return targets, balance, max_bid, catalog


def market_report(client: BiwengerClient, clause_only: bool = False) -> tuple[str, list[Button]]:
    targets, balance, max_bid, catalog = _collect_targets(client, clause_only=clause_only)
    board, watch = pick_board(targets, affordable_n=4, watch_n=2)
    n_clause = sum(1 for t in targets if t.source == "clause")
    n_mkt = sum(1 for t in targets if t.source != "clause")
    lines = [f"💰 Análisis de fichajes  ·  {_mode_tag()}", ""]
    lines.extend(intro_gangas(len(targets), n_mkt, n_clause, balance, max_bid))
    lines.append("🎯 Los que más te mejoran y puedes pagar")
    lines.append("")
    buttons: list[Button] = []
    if not board:
        lines.append("Ahora mismo no hay nadie asequible que mejore de verdad el once.")
        lines.append("")
    for t in board:
        lines.extend(explain_target(t, balance))
        btn = _target_button(t)
        if btn:
            buttons.append(btn)
        close = _close_bid_button(t)
        if close:
            buttons.append(close)
    if watch:
        lines.append("💎 Buenas ideas cuando ahorres")
        lines.append("")
        for t in watch:
            lines.extend(explain_target(t, balance))
    offers = client.get_offers()
    if offers and not clause_only:
        lines.append("📥 Ofertas que te han hecho")
        for off in offers:
            names = ", ".join(catalog[i].name for i in off.player_ids if i in catalog) or str(off.player_ids)
            lines.append(f"  {off.from_name} te ofrece {money(off.amount)} por {names}.")
            if off.id:
                buttons.append((f"Aceptar {money(off.amount)}", f"accept:{off.id}"))
                buttons.append((f"Rechazar oferta {off.id}", f"reject:{off.id}"))
        lines.append("")
    buttons.append(("🔓 Buscar cláusulas", "cmd:clausulas"))
    buttons.append(("💶 Presupuesto de la liga", "cmd:presupuesto"))
    return "\n".join(lines).strip(), buttons


def clause_menu() -> tuple[str, list[Button]]:
    text = (
        "🔓 <b>Buscador de clausulazos</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "Elige línea. Solo jugadores de rivales, ordenados por si te mejoran el once.\n"
        "\n"
        "💬 También: /clausulas def · med · del · por"
    )
    buttons = [
        ("🧤 Porteros", "clpos:1"),
        ("🛡️ Defensas", "clpos:2"),
        ("⚙️ Centrocampistas", "clpos:3"),
        ("🎯 Delanteros", "clpos:4"),
        ("📋 Todas las posiciones", "clpos:0"),
    ]
    return text, buttons


def clause_report(client: BiwengerClient, position: Position | None = None) -> tuple[str, list[Button]]:
    targets, balance, _max_bid, _catalog = _collect_targets(client, clause_only=True)
    targets = filter_position(targets, position)
    board, watch = pick_board(targets, affordable_n=4, watch_n=2)
    lines = [f"{_mode_tag()}", ""]
    lines.extend(intro_clauses(position, len(targets), balance))
    lines.append("🎯 Los mejores que puedes pagar")
    lines.append("")
    buttons: list[Button] = [
        ("🧤 POR", "clpos:1"),
        ("🛡️ DEF", "clpos:2"),
        ("⚙️ MED", "clpos:3"),
        ("🎯 DEL", "clpos:4"),
    ]
    if not board:
        word = POS_PLURAL[position] if position else "jugadores"
        lines.append(f"No hay {word} con cláusula que puedas pagar ahora y mejoren el once.")
        lines.append("")
    for t in board:
        lines.extend(explain_target(t, balance))
        btn = _target_button(t)
        if btn:
            buttons.append(btn)
    if watch:
        lines.append("💎 Fuera de tu presupuesto")
        lines.append("")
        for t in watch:
            lines.extend(explain_target(t, balance))
    buttons.append(("💶 ¿Quién puede pagar qué?", "cmd:presupuesto"))
    return "\n".join(lines).strip(), buttons


def _fill_buy_prices(players: list[Player], moves) -> None:
    last_pay: dict[tuple[int, int], int] = {}
    for move in sorted(moves, key=lambda m: m.date):
        if move.payer_id and move.player_id:
            last_pay[(int(move.payer_id), int(move.player_id))] = move.amount
    for player in players:
        if player.owner_id and not player.buy_price:
            player.buy_price = last_pay.get((int(player.owner_id), int(player.id)))


def budget_report(client: BiwengerClient) -> tuple[str, list[Button]]:
    team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    listings, _balance, my_max_bid = client.get_market()
    standings = client.get_standings()
    settings_league = client.get_league_settings()
    news = client.get_season_news(SEASON_START, max_pages=16)
    since = last_reset_epoch(news) or SEASON_START
    moves = parse_moves(news, since=since)
    _fill_buy_prices(list(catalog.values()), moves)
    bonus = int(settings_league.get("bonusPoint") or 25_000)
    rule = str(settings_league.get("maximumBid") or "quarterTeam")
    budgets, start = build_budgets(
        standings,
        moves,
        my_id=client.team_id,
        my_balance=team.balance,
        bonus_per_point=bonus,
        max_bid_rule=rule,
        start_money=START_MONEY,
        players=list(catalog.values()),
        listings=listings,
    )
    prev = load_previous_cash()
    save_snapshot(budgets, start)

    mine = next((b for b in budgets if b.is_me), None)
    recon_ok = mine is not None and abs(mine.cash_raw - team.balance) <= 1
    richest = max(budgets, key=lambda b: b.wealth)
    most_cash = max(budgets, key=lambda b: b.cash)
    broke = [b for b in budgets if b.cash == 0]
    can_5 = [b.name for b in budgets if b.cash >= 5_000_000]
    can_10 = [b.name for b in budgets if b.cash >= 10_000_000]

    lines = [
        "💶 <b>CAJA DE LA LIGA</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"Salida: {money(START_MONEY)} por cabeza. El saldo de los demás no se ve en Biwenger: "
        "lo reconstruyo con cada fichaje, venta, cláusula y cesión del tablón.",
        "La caja no puede ser negativa. Si alguien gastó de más, lo dejo en 0€ y lo digo. "
        "El techo de puja es caja + 25% del valor de la plantilla. Las cláusulas salen solo de la caja.",
    ]
    if recon_ok:
        lines.append(
            f"Control: en tu equipo el recuento cuadra al euro ({money(team.balance)}). "
            f"Tu techo de puja real es {money(my_max_bid)}."
        )
    elif mine:
        lines.append(
            f"Control: en ti el recuento da {money(mine.cash_raw)} y Biwenger {money(team.balance)}. "
            "Revisa si hubo un movimiento que no salió en el tablón."
        )
    lines.append("")

    for b in budgets:
        tag = " ← tú" if b.is_me else ""
        src = "caja real" if not b.cash_is_estimate else "caja estimada"
        delta = ""
        if b.team_id in prev and not b.is_me:
            diff = b.cash_raw - prev[b.team_id]
            if abs(diff) >= 50_000:
                delta = f" ({'+' if diff > 0 else ''}{money(diff)} vs última vez)"
        value_arrow = "↑" if b.team_value_inc > 0 else ("↓" if b.team_value_inc < 0 else "=")
        pnl = b.unrealized
        pnl_txt = f"la plantilla vale {money(abs(pnl))} {'más' if pnl >= 0 else 'menos'} de lo que pagó"
        lines.append(f"{b.position}. {b.name}{tag}")
        if b.overdraft and b.cash_is_estimate:
            lines.append(
                f"   {src}: 0€ — fichó {money(b.overdraft)} por encima del inicial + ventas.{delta}"
            )
        else:
            lines.append(f"   {src}: {money(b.cash)}{delta}")
        lines.append(
            f"   plantilla {money(b.team_value)} {value_arrow}{money(abs(b.team_value_inc))} hoy · {pnl_txt}"
        )
        extra = ""
        if b.listed_count:
            extra = f" · {b.listed_count} en venta (pide {money(b.listed)})"
        clause_txt = "puede pagar cláusulas" if b.cash >= 1_000_000 else "casi no puede clavar cláusulas"
        lines.append(
            f"   patrimonio {money(b.wealth)} · techo puja {money(b.max_bid)} · {clause_txt}{extra}"
        )
        lines.append("")

    lines.append(f"Más patrimonio (caja + plantilla): {richest.name} con {money(richest.wealth)}.")
    lines.append(f"Más dinero líquido: {most_cash.name} con {money(most_cash.cash)}.")
    if broke:
        lines.append("Sin caja (no pagan cláusulas): " + ", ".join(b.name for b in broke) + ".")
    if can_10:
        lines.append("Pueden pagar una cláusula de 10M: " + ", ".join(can_10) + ".")
    elif can_5:
        lines.append("Pueden pagar una cláusula de 5M: " + ", ".join(can_5) + ".")
    lines.append("Si venden o les clavan un jugador, la caja sube. Si fichan, baja.")
    return "\n".join(lines).strip(), [("🔓 Buscar cláusulas", "cmd:clausulas")]


def intel_report(client: BiwengerClient) -> tuple[str, list[Button]]:
    team, squad, catalog = client.enrich_my_squad()
    intel = enrich_catalog(client, catalog)
    lines = [
        "📰 <b>PREVIA · AS + SofaScore</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "Onces: AS / Jornada Perfecta. Notas: partidos ya jugados.",
        "",
    ]
    mine_out = [p for p in squad if p.is_injured_or_suspended or p.starter_role == "out" or p.is_doubt]
    mine_xi = [p for p in squad if p.starter_role == "starter"]
    mine_bench = [p for p in squad if p.starter_role == "bench"]
    if mine_xi:
        lines.append("🟢 Tus titulares probables: " + ", ".join(p.name for p in mine_xi))
    if mine_bench:
        lines.append("🟡 Tus suplentes probables: " + ", ".join(p.name for p in mine_bench))
    if mine_out:
        lines.append("🚫 Dudas / bajas tuyas:")
        for p in mine_out:
            extra = f" — {p.status_info}" if p.status_info else ""
            role = p.status if p.status != "ok" else p.starter_role
            lines.append(f"  {p.status_emoji} {p.name} ({role}){extra}")
    if not mine_xi and not mine_out and not mine_bench:
        lines.append("Aún no hay previa de AS para tus jugadores (partido pendiente o ya cerrado).")
    lines.append("")
    lows = [p for p in catalog.values() if p.is_injured_or_suspended or p.is_doubt]
    lows.sort(key=lambda p: (p.status != "injured", p.name))
    if lows:
        lines.append(f"Partes de la jornada ({len(lows)} lesionados, sanciones o dudas):")
        for p in lows[:18]:
            note = p.status_info or p.status
            lines.append(f"  {p.status_emoji} {p.name} ({p.team_name or '?'}) — {note}")
        if len(lows) > 18:
            lines.append(f"  … y {len(lows) - 18} más.")
        lines.append("")
    sofa = [(p, p.sofascore) for p in catalog.values() if p.sofascore is not None]
    sofa.sort(key=lambda x: x[1], reverse=True)
    if sofa:
        lines.append("Último SofaScore (partidos ya jugados):")
        for p, rating in sofa[:8]:
            as_txt = f" · AS {p.as_points}" if p.as_points is not None else ""
            lines.append(f"  {rating:.1f} {p.name}{as_txt}")
        lines.append("")
    if intel.headlines:
        lines.append("Últimas de AS / Biwenger:")
        for h in intel.headlines[:6]:
            lines.append(f"  • {h.title}")
        lines.append("")
    lines.append(f"Tienes {money(team.balance)}. El once ya usa esta previa.")
    return "\n".join(lines).strip(), [
        ("⚽ Recalcular once", "cmd:alineacion"),
        ("💰 Fichajes", "cmd:mercado"),
    ]


def sell_report(client: BiwengerClient) -> tuple[str, list[Button]]:
    _, squad, catalog = client.enrich_my_squad()
    enrich_catalog(client, catalog)
    tips = sell_candidates(squad)
    if not tips:
        return "⏱️ Nadie urgente de vender. Plantilla estable.", []
    lines = [f"⏱️ Candidatos a vender  ·  {_mode_tag()}", ""]
    buttons: list[Button] = []
    for tip in tips:
        p = tip.player
        lines.append(f"{p.status_emoji} {p.name}  {money(p.price)}  ({tip.reason})")
        lines.append(f"   sugerido: {money(tip.suggested_price)}")
        buttons.append((f"Vender {p.name} {money(tip.suggested_price)}", f"sell:{p.id}:{tip.suggested_price}"))
        lines.append("")
    return "\n".join(lines).strip(), buttons


def edge_report(client: BiwengerClient) -> tuple[str, list[Button]]:
    team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    enrich_catalog(client, catalog)
    owners = {p.owner_id for p in catalog.values() if p.owner_id}
    n_mgr = max(len(owners), 1)
    apply_ownership(catalog, n_mgr)
    fixtures: dict = {}
    try:
        fixtures = client.get_team_fixtures(5)
        apply_next_home(catalog, fixtures)
    except Exception:
        pass
    listings, balance, max_bid = client.get_market()
    spendable = min(balance, max_bid) if max_bid else balance
    targets = find_targets(listings, catalog, squad, spendable)
    result = best_lineup(squad)
    cap = pick_captain(result, n_mgr)
    if cap:
        result.captain = cap

    standings = client.get_standings()
    news = client.get_season_news(SEASON_START, max_pages=12)
    moves = parse_moves(news, since=last_reset_epoch(news) or SEASON_START)
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

    lines = [
        "⚡ <b>VENTAJA DE HOY</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"🏟️ {team.name}   💶 {money(balance)}   🎯 techo {money(max_bid)}",
        f"{_mode_tag()}",
        "",
    ]
    buttons: list[Button] = []
    pos_hole = hole(squad)
    if pos_hole:
        word = POS_WORD.get(pos_hole, pos_hole.label)
        lines.append(f"1) Hueco letal: te falta {word}. Mientras no lo tapes, cada jornada regalas puntos.")
        fills = best_targets_for_hole(targets, pos_hole)
        if not fills:
            lines.append("   No hay uno asequible hoy. No gastes el saldo en otra cosa.")
        for t in fills[:2]:
            tag = "" if t.affordable else " · AHORRA, ahora no te llega"
            lines.append(
                f"   → {t.player.name} ({t.via} {money(t.cost)}) · "
                f"{predict(t.player):.1f} pts · {ownership_label(t.player, n_mgr)}{tag}"
            )
            btn = _target_button(t)
            if btn:
                buttons.append(btn)
        lines.append("")
    else:
        lines.append("1) Plantilla cubierta. Ahora toca mejorar, no rellenar.")
        lines.append("")

    diffs = differentials(catalog)
    lines.append("2) Diferenciales (puntos que solo sumas tú)")
    if diffs:
        for p in diffs[:4]:
            via = "cláusula" if p.clause and p.owner_id else "mercado"
            cost = p.clause or p.price
            lines.append(
                f"   → {p.name} ({p.position.label}) {money(cost)} · "
                f"{predict(p):.1f} pts · {ownership_label(p, n_mgr)}"
            )
            if p.clause and p.owner_id and (p.clause or 0) <= spendable:
                buttons.append((f"Cláusula {p.name} {money(p.clause)}", f"askclause:{p.id}:{p.clause}"))
    else:
        lines.append("   Hoy no hay un chollo único claro.")
    lines.append("")

    if result.captain:
        lines.append(
            f"3) Capitán: {result.captain.name} "
            f"({result.expected.get(result.captain.id, 0):.1f} x2, {ownership_label(result.captain, n_mgr)})"
        )
        if result.captain.next_is_home:
            lines.append("   Juega en casa.")
        lines.append(f"   Once {result.formation} · {result.total_expected:.1f} pts esperados.")
        if not result.formation.startswith("incompleto"):
            buttons.append(("✅ Aplicar XI + capitán", "apply:lineup"))
        lines.append("")

    risers = price_risers(catalog)
    mine_ids = {p.id for p in squad}
    lines.append("4) Precio: suben mañana / bajan los tuyos")
    up = [p for p in risers if p.id not in mine_ids][:3]
    if up:
        lines.append("   Coge antes de que suban: " + ", ".join(f"{p.name} ({p.price_trend_pct:+.1f}%)" for p in up))
    down = price_falls(squad)
    if down:
        lines.append("   Suéltanos antes de que sangren: " + ", ".join(f"{p.name} ({p.price_trend_pct:+.1f}%)" for p in down))
    lines.append("")

    wr = weak_rivals(catalog, budgets)
    lines.append("5) Rivales tocados (ahora se les puede clavar)")
    if wr:
        for note in wr:
            lines.append(f"   → {note}")
    else:
        lines.append("   Nadie está realmente contra las cuerdas.")
    lines.append("")

    vul = shield(squad)
    lines.append("6) Te pueden clavar a ti")
    if vul:
        for p in vul:
            lines.append(f"   → {p.name}: cláusula {money(p.clause or 0)} vs valor {money(p.price)}")
    else:
        lines.append("   Tus cracks no están regalados.")
    lines.append("")

    cal = calendar_edge(squad, fixtures)
    if cal:
        lines.append("7) Calendario (juega el fixture, no el nombre)")
        for row in cal:
            lines.append(f"   → {row}")
        lines.append("")

    lines.append("Esto es lo que gana ligas: tapar el hueco, pillar lo que nadie tiene, capitán diferencial.")
    buttons.append(("🔓 Cláusulas", "cmd:clausulas"))
    buttons.append(("💶 Cajas rivales", "cmd:presupuesto"))
    return "\n".join(lines).strip(), buttons


def calendar_text(client: BiwengerClient) -> str:
    _, squad, _ = client.enrich_my_squad()
    fixtures = client.get_team_fixtures(5)
    teams: dict[int, list[Player]] = {}
    for p in squad:
        if p.team_id:
            teams.setdefault(p.team_id, []).append(p)
    lines = ["📅 Calendario de tus clubs (próximas 5)", ""]
    for team_id, players in teams.items():
        runs = fixtures.get(team_id) or []
        club = players[0].team_name or str(team_id)
        names = ", ".join(p.name for p in players[:4])
        if not runs:
            lines.append(f"{club}: sin datos")
            continue
        bits = []
        for fx in runs:
            loc = "L" if fx.is_home else "V"
            diff = f"{fx.difficulty:.0f}" if fx.difficulty is not None else "?"
            bits.append(f"{loc} {fx.opponent} ({diff})")
        lines.append(f"{club}  [{names}]")
        lines.append("   " + " · ".join(bits))
        lines.append("")
    return "\n".join(lines).strip()


def standings_text(client: BiwengerClient) -> str:
    rows = client.get_standings()
    me = client.team_id
    lines = ["🏆 Clasificación", ""]
    for row in rows:
        mark = " ← tú" if me and row.team_id == me else ""
        lines.append(f"{row.position:>2}. {row.name}  {row.points} pts{mark}")
    return "\n".join(lines)


def daily_briefing(client: BiwengerClient) -> tuple[str, list[Button]]:
    team, squad, catalog = client.enrich_my_squad()
    client.attach_league_owners(catalog)
    enrich_catalog(client, catalog)
    result = best_lineup(squad)
    listings, balance, max_bid = client.get_market()
    spendable = min(balance, max_bid or balance)
    board, _watch = pick_board(find_targets(listings, catalog, squad, spendable), affordable_n=4, watch_n=0)
    tips = sell_candidates(squad, limit=3)
    offers = client.get_offers()

    lines = [
        f"📋 Resumen diario  ·  {_mode_tag()}",
        f"{team.name}  {money(balance)}  {team.points} pts",
        "",
        f"⚽ XI sugerido {result.formation}  ({result.total_expected:.1f} pts)",
    ]
    if result.captain:
        lines.append(f"   capitán: {result.captain.name}")
    lines.append("")
    if board:
        lines.append("🎯 Fichajes que más te mejoran el once")
        for t in board:
            extra = f"+{t.extra_xp:.1f} pts" if t.extra_xp > 0 else "no mejora el XI"
            lines.append(
                f"  {t.player.name}: {t.via} por {money(t.cost)}. "
                f"Esperamos {t.expected:.1f} pts ({extra})."
            )
        lines.append("")
    if tips:
        lines.append("⏱️ Ventas")
        for tip in tips:
            lines.append(f"  {tip.player.name}: {tip.reason}")
        lines.append("")
    if offers:
        lines.append(f"📥 {len(offers)} oferta(s) pendiente(s)")
        lines.append("")
    lines.append("Pulsa un botón o escribe /alineacion /mercado /equipo")
    buttons = [
        ("⚽ Ver XI", "cmd:alineacion"),
        ("💰 Mercado", "cmd:mercado"),
        ("🔓 Cláusulas", "cmd:clausulas"),
        ("💶 Presupuesto", "cmd:presupuesto"),
        ("👥 Equipo", "cmd:equipo"),
    ]
    return "\n".join(lines).strip(), buttons


def maybe_auto_lineup(client: BiwengerClient) -> str | None:
    from . import state

    if not state.get("auto_lineup"):
        return None
    kickoff = client.first_kickoff_epoch()
    if not kickoff:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    # ventana: entre 5h y 30 min antes del primer partido
    if not (30 * 60 <= kickoff - now <= 5 * 3600):
        return None
    round_id = client.get_current_round_id()
    if round_id and state.get("last_lineup_round") == round_id:
        return None
    team, squad, _ = client.enrich_my_squad()
    result = best_lineup(squad)
    client.set_lineup(result.player_ids, result.formation, result.captain.id if result.captain else None)
    if round_id:
        state.set_value("last_lineup_round", round_id)
    tag = "simulada" if settings.dry_run else "aplicada"
    return f"⚽ Auto-alineación {tag}: {result.formation} ({result.total_expected:.1f} pts)"


def apply_lineup(client: BiwengerClient) -> str:
    _, squad, _ = client.enrich_my_squad()
    result = best_lineup(squad)
    client.set_lineup(result.player_ids, result.formation, result.captain.id if result.captain else None)
    verb = "Simulada" if settings.dry_run else "Aplicada"
    cap = result.captain.name if result.captain else "—"
    return f"{verb} {result.formation}. Capitán {cap}. Esperado {result.total_expected:.1f}."


def confirm_clause(client: BiwengerClient, player_id: int, amount: int) -> tuple[str, list[Button]]:
    catalog = client.get_all_players()
    client.attach_league_owners(catalog)
    player = catalog.get(player_id)
    name = player.name if player else str(player_id)
    owner = player.owner_name if player else "?"
    return (
        f"⚠️ La cláusula es inmediata e irreversible.\n"
        f"¿Pagar {money(amount)} por {name} (de {owner})?\n"
        f"{_mode_tag()}",
        [
            (f"✅ Confirmar cláusula {name}", f"clause:{player_id}:{amount}"),
            ("❌ Cancelar", "cmd:mercado"),
        ],
    )


def apply_clause(client: BiwengerClient, player_id: int, amount: int) -> str:
    catalog = client.get_all_players()
    client.attach_league_owners(catalog)
    player = catalog.get(player_id)
    name = player.name if player else str(player_id)
    owner_id = player.owner_id if player else None
    client.pay_clause(player_id, amount, owner_id)
    verb = "Simulada" if settings.dry_run else "Pagada"
    return f"{verb} cláusula de {name} por {money(amount)}."


def schedule_close_bid(client: BiwengerClient, player_id: int, amount: int) -> str:
    from . import snipe

    listings, _, _ = client.get_market()
    listing = next((x for x in listings if x.player_id == player_id), None)
    catalog = client.get_all_players()
    name = catalog[player_id].name if player_id in catalog else str(player_id)
    if listing is None:
        return f"{name} no está ahora en el mercado. No programo la puja."
    if listing.has_visible_bids:
        return f"{name} ya tiene {listing.bid_count} puja(s). No programo nada."
    already = client.get_my_purchase_ids()
    if player_id in already:
        return f"Ya tienes una puja por {name}. No duplico."
    until = int(listing.until.timestamp())
    snipe.add(player_id, name, amount, until, listing.seller_id)
    when = listing.until.astimezone().strftime("%d/%m %H:%M")
    return (
        f"Programada puja al cierre por {name}: {money(amount)}.\n"
        f"Se lanza ~3 min antes de {when}, y solo si sigue sin puja "
        f"(la tuya o una visible). {_mode_tag()}"
    )


def snipe_list_text() -> str:
    from . import snipe

    items = snipe.pending()
    if not items:
        return "🎯 No hay pujas al cierre. Dime «pújame al cierre por Mariano»."
    lines = ["🎯 <b>Pujas al cierre</b>", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    for t in items:
        when = datetime.fromtimestamp(int(t["until"]), tz=timezone.utc).astimezone().strftime("%d/%m %H:%M")
        lines.append(f"  • {t.get('name')} {money(t.get('amount') or 0)} · cierra {when}")
    return "\n".join(lines)


def apply_bid(client: BiwengerClient, player_id: int, amount: int) -> str:
    listings, _, _ = client.get_market()
    listing = next((x for x in listings if x.player_id == player_id), None)
    catalog = client.get_all_players()
    name = catalog[player_id].name if player_id in catalog else str(player_id)
    client.place_bid(player_id, amount, listing.seller_id if listing else None)
    verb = "Simulada" if settings.dry_run else "Enviada"
    return f"{verb} puja de {money(amount)} por {name}."


def apply_sale(client: BiwengerClient, player_id: int, price: int) -> str:
    catalog = client.get_all_players()
    name = catalog[player_id].name if player_id in catalog else str(player_id)
    client.list_for_sale(player_id, price)
    verb = "Simulada" if settings.dry_run else "Puesta"
    return f"{verb} venta de {name} a {money(price)}."


def apply_offer(client: BiwengerClient, offer_id: int, accept: bool) -> str:
    if accept:
        client.accept_offer(offer_id)
        verb = "Aceptada" if not settings.dry_run else "Simulada aceptación de"
    else:
        client.reject_offer(offer_id)
        verb = "Rechazada" if not settings.dry_run else "Simulado rechazo de"
    return f"{verb} oferta #{offer_id}."
