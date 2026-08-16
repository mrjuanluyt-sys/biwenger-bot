"""Mensajes Telegram más visuales (HTML)."""
from __future__ import annotations

import html
import re


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


def h1(title: str, emoji: str = "") -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}<b>{esc(title)}</b>"


def h2(title: str, emoji: str = "") -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}<b>{esc(title)}</b>"


def rule() -> str:
    return "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


def kv(label: str, value: object, emoji: str = "•") -> str:
    return f"{emoji} {esc(label)}: <b>{esc(value)}</b>"


def bullet(text: str, emoji: str = "•") -> str:
    return f"{emoji} {esc(text)}"


def mode_html(dry_run: bool) -> str:
    if dry_run:
        return "🧪 <b>SIMULACIÓN</b> · no toca Biwenger"
    return "⚡ <b>EN VIVO</b> · las acciones son reales"


def auto_html(text: str) -> str:
    """Si el texto no trae HTML, lo pone un poco más de cartelera."""
    if "<b>" in text or "<i>" in text:
        return text
    lines = text.splitlines()
    out: list[str] = []
    first = True
    for raw in lines:
        line = raw.rstrip()
        if first and line:
            out.append(f"<b>{esc(line)}</b>")
            out.append(rule())
            first = False
            continue
        if not line:
            out.append("")
            continue
        if re.fullmatch(r"[━┄─=-]{4,}", line):
            out.append(rule())
            continue
        out.append(esc(line))
    return "\n".join(out)


def chunk(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            parts.append("".join(buf).rstrip())
            buf = [line]
            size = len(line)
        else:
            buf.append(line)
            size += len(line)
    if buf:
        parts.append("".join(buf).rstrip())
    return parts or [text[:limit]]
