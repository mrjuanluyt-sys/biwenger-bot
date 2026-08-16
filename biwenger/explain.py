"""Textos largos y claros para alguien que no vive en el fantasy."""
from __future__ import annotations

from .market import NEED_LABEL, Target, money
from .models import Player, Position
from .predictor import predict

POS_WORD = {
    Position.GOALKEEPER: "portero",
    Position.DEFENDER: "defensa",
    Position.MIDFIELDER: "centrocampista",
    Position.FORWARD: "delantero",
}

POS_PLURAL = {
    Position.GOALKEEPER: "porteros",
    Position.DEFENDER: "defensas",
    Position.MIDFIELDER: "centrocampistas",
    Position.FORWARD: "delanteros",
}

HOW_VIA = {
    "clause": "pagando su cláusula (compra inmediata)",
    "sale": "pujando en la venta de un rival",
    "free": "pujando en el mercado libre",
    "market": "pujando en el mercado",
}


def leftover(balance: int, cost: int) -> str:
    rest = balance - cost
    if rest >= 0:
        return f"Si lo fichas te quedarían {money(rest)}."
    return f"Ahora mismo te faltan {money(-rest)}."


def explain_target(t: Target, balance: int) -> list[str]:
    p = t.player
    pos = POS_WORD.get(p.position, p.position.label.lower())
    who = p.owner_name or "nadie"
    lines = [
        f"{p.status_emoji} {p.name} · {pos} · {t.via}",
        f"Es de {who}. Lo puedes fichar {HOW_VIA.get(t.source, t.via)}.",
        f"Te costaría {money(t.cost)}. En el mercado vale {money(p.price)} "
        f"({_premium_phrase(t.premium_pct)}).",
        "",
        "¿Merece la pena?",
    ]
    lines.append(_expect_phrase(p, t.expected))
    lines.append(_intel_phrase(p))
    lines.append(_upgrade_phrase(t, pos))
    if t.cost_per_extra:
        lines.append(
            f"Cada punto extra que suma al once te sale por {money(t.cost_per_extra)}."
        )
    lines.append(_need_phrase(t.need, pos))
    if t.trend_pct >= 1.5:
        lines.append(f"Su precio está subiendo ({t.trend_pct:+.1f}%): si esperas, mañana sale más caro.")
    elif t.trend_pct <= -1.5:
        lines.append(f"Su precio está bajando ({t.trend_pct:+.1f}%): no hay prisa por el valor.")
    lines.append(leftover(balance, t.cost))
    lines.append("")
    return lines


def _premium_phrase(premium: float) -> str:
    if premium <= 5:
        return "casi lo que vale"
    if premium < 0:
        return f"{abs(premium):.0f}% más barato que su valor"
    return f"pagas un {premium:.0f}% extra sobre su valor"


def _intel_phrase(player: Player) -> str:
    bits: list[str] = []
    if player.starter_role == "starter":
        bits.append("AS / Jornada Perfecta lo pone de titular.")
    elif player.starter_role == "bench":
        bits.append("No está en el once probable: riesgo de quedarse en el banquillo.")
    elif player.starter_role == "out":
        bits.append("Está fuera de la convocatoria.")
    if player.is_injured_or_suspended:
        bits.append(player.status_info or "Lesionado o sancionado.")
    elif player.is_doubt:
        bits.append("Duda: " + (player.status_info or "hay un parte médico abierto."))
    if player.sofascore is not None:
        bits.append(f"Último SofaScore: {player.sofascore:.1f}.")
    if player.as_points is not None:
        bits.append(f"Últimos puntos AS: {player.as_points}.")
    if player.headlines:
        bits.append("Sale en AS: " + player.headlines[0])
    return " ".join(bits) if bits else "Sin novedad médica ni de alineación."


def _expect_phrase(player: Player, expected: float) -> str:
    form = ""
    if player.fitness:
        last = player.fitness[-1]
        form = f" El último partido hizo {last} puntos."
    rival = ""
    if player.fixture_difficulty is not None:
        if player.fixture_difficulty <= 35:
            rival = " El próximo rival es asequible."
        elif player.fixture_difficulty >= 65:
            rival = " El próximo rival es complicado."
    return f"De él esperamos unos {expected:.1f} puntos esta jornada.{form}{rival}"


def _upgrade_phrase(t: Target, pos: str) -> str:
    if t.extra_xp >= 1.5:
        return (
            f"Tu mejor {pos} ahora mismo rinde menos: el once subiría "
            f"unos {t.extra_xp:.1f} puntos."
        )
    if t.extra_xp > 0.2:
        return f"Mejora un poco tu {pos} (+{t.extra_xp:.1f} puntos en el once)."
    if t.extra_xp > -0.4:
        return f"No mejora el once: rinde parecido a tu {pos} actual."
    return f"Rinde peor que tu {pos} actual ({t.extra_xp:.1f} puntos). Solo sirve de recambio."


def _need_phrase(need: str, pos: str) -> str:
    if need == "urgent":
        return f"En tu plantilla te falta gente en {pos}. Es un hueco de verdad."
    if need == "upgrade":
        return f"Ya tienes {pos}, pero este sería una mejora clara."
    return f"Lo tendrías de fondo de armario ({NEED_LABEL[need]})."


def intro_gangas(n_total: int, n_mkt: int, n_clause: int, balance: int, max_bid: int) -> list[str]:
    return [
        "Te miro el mercado y también las cláusulas de toda la liga.",
        "No elijo por «vale 3M y la cláusula es 3.2M». Elijo por si te suma puntos "
        "en el once y lo caro que te sale cada punto extra.",
        f"Tienes {money(balance)} en el banco. Tu techo de puja es {money(max_bid)}.",
        f"He analizado {n_total} jugadores: {n_mkt} en el mercado y {n_clause} con cláusula.",
        "",
    ]


def intro_clauses(pos: Position | None, n: int, balance: int) -> list[str]:
    if pos:
        word = POS_PLURAL[pos]
        head = f"Clausulazos de {word}"
        body = f"Solo {word} de otros equipos. He encontrado {n} con cláusula."
    else:
        head = "Clausulazos de toda la liga"
        body = f"He encontrado {n} jugadores de rivales que puedes comprar pagando la cláusula."
    return [
        head,
        body,
        "La cláusula es inmediata: el jugador pasa a ser tuyo en el acto y no se puede deshacer.",
        f"Tu saldo: {money(balance)}.",
        "",
    ]
