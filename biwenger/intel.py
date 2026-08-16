"""Lesiones, sanciones, onces AS/Jornada Perfecta, SofaScore y noticias."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from .models import Player
from .settings import settings

logger = logging.getLogger(__name__)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
BLOG_FEED = "https://biwenger.as.com/blog/feed/"
CACHE_TTL = 45 * 60


@dataclass
class Headline:
    title: str
    url: str
    source: str


@dataclass
class Intel:
    starters: set[int] = field(default_factory=set)
    bench_teams: set[int] = field(default_factory=set)
    unavailable: dict[int, tuple[str, str]] = field(default_factory=dict)
    sofascore: dict[int, float] = field(default_factory=dict)
    as_points: dict[int, int] = field(default_factory=dict)
    headlines: list[Headline] = field(default_factory=list)
    fetched_at: float = 0.0


def _cache_path() -> Path:
    return settings.data_dir / "intel.json"


def _load_cache() -> Intel | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(raw.get("fetched_at") or 0) > CACHE_TTL:
        return None
    return Intel(
        starters=set(raw.get("starters") or []),
        bench_teams=set(raw.get("bench_teams") or []),
        unavailable={int(k): tuple(v) for k, v in (raw.get("unavailable") or {}).items()},
        sofascore={int(k): float(v) for k, v in (raw.get("sofascore") or {}).items()},
        as_points={int(k): int(v) for k, v in (raw.get("as_points") or {}).items()},
        headlines=[Headline(**h) for h in raw.get("headlines") or []],
        fetched_at=float(raw.get("fetched_at") or 0),
    )


def _save_cache(intel: Intel) -> None:
    path = _cache_path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "starters": list(intel.starters),
                "bench_teams": list(intel.bench_teams),
                "unavailable": {str(k): list(v) for k, v in intel.unavailable.items()},
                "sofascore": intel.sofascore,
                "as_points": intel.as_points,
                "headlines": [h.__dict__ for h in intel.headlines],
                "fetched_at": intel.fetched_at,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _get(url: str, timeout: int = 18) -> str:
    resp = requests.get(url, headers=UA, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_preview(html: str) -> tuple[list[int], dict[int, tuple[str, str]]]:
    """Devuelve (onces probables, no disponibles id -> (kind, nota))."""
    split = re.split(r"No disponibles", html, maxsplit=1, flags=re.I)
    head = split[0]
    tail = split[1] if len(split) > 1 else ""
    lineup_ids = [int(x) for x in re.findall(r"/i/p/(\d+)\.png", head)]
    # quita duplicados conservando orden
    seen: set[int] = set()
    starters: list[int] = []
    for pid in lineup_ids:
        if pid not in seen:
            seen.add(pid)
            starters.append(pid)
    unavailable: dict[int, tuple[str, str]] = {}
    for match in re.finditer(r"/i/p/(\d+)\.png", tail):
        chunk = tail[match.start() : match.start() + 1400]
        kind = "out"
        if re.search(r"\bDuda\b", chunk):
            kind = "doubt"
        elif re.search(r"\bSancionado\b", chunk):
            kind = "sanctioned"
        elif re.search(r"\bLesionado\b", chunk):
            kind = "injured"
        note = ""
        title = re.search(r'title="([^"]+)"', chunk)
        small = re.search(r"<small>([^<]+)</small>", chunk)
        if small:
            note = unescape(re.sub("<[^>]+>", "", small.group(1))).strip()
        elif title:
            note = unescape(title.group(1)).strip()
        unavailable[int(match.group(1))] = (kind, note)
    return starters[:22], unavailable


def _parse_ratings(report: dict) -> tuple[float | None, int | None]:
    sofa = None
    as_pts = None
    opt = ((report.get("optionalPoints") or {}).get("superPicaExtraPoints") or {})
    breakdown = opt.get("breakdown") or []
    for item in breakdown:
        if not isinstance(item, list) or not item:
            continue
        label = str(item[0])
        rest = " ".join(str(x) for x in item)
        if "SofaScore" in label or "Sofascore" in label:
            nums = re.findall(r"(\d+(?:[.,]\d+)?)", rest)
            if nums:
                val = float(nums[0].replace(",", "."))
                sofa = val if val <= 10 else val / 2
        if "Diario AS" in label or label == "AS":
            nums = re.findall(r"(\d+)", rest)
            if nums:
                as_pts = int(nums[0])
    return sofa, as_pts


def fetch_blog_headlines(limit: int = 8) -> list[Headline]:
    try:
        xml = _get(BLOG_FEED)
        root = ET.fromstring(xml)
    except Exception:
        logger.warning("No pude leer el feed de AS/Biwenger")
        return []
    out: list[Headline] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or title == "Biwenger":
            continue
        out.append(Headline(title=title, url=url, source="AS / Biwenger"))
        if len(out) >= limit:
            break
    return out


def collect(client) -> Intel:
    cached = _load_cache()
    if cached:
        return cached
    intel = Intel(fetched_at=time.time())
    try:
        detail = client.get_round_detail()
    except Exception:
        logger.exception("round detail")
        detail = {}
    games = detail.get("games") or []
    for game in games:
        for side in ("home", "away"):
            team = game.get(side) or {}
            tid = team.get("id")
            for report in team.get("reports") or []:
                pid = (report.get("player") or {}).get("id")
                if not pid:
                    continue
                sofa, as_pts = _parse_ratings(report)
                if sofa is not None:
                    intel.sofascore[int(pid)] = sofa
                if as_pts is not None:
                    intel.as_points[int(pid)] = as_pts
        preview = game.get("preview") or {}
        url = preview.get("url") if isinstance(preview, dict) else None
        if not url:
            continue
        try:
            html = _get(url)
            starters, unav = parse_preview(html)
            intel.starters.update(starters)
            intel.unavailable.update(unav)
            hid = (game.get("home") or {}).get("id")
            aid = (game.get("away") or {}).get("id")
            if hid:
                intel.bench_teams.add(int(hid))
            if aid:
                intel.bench_teams.add(int(aid))
        except Exception:
            logger.warning("No pude leer la previa %s", url)
    intel.headlines = fetch_blog_headlines()
    _save_cache(intel)
    return intel


def apply(catalog: dict[int, Player], intel: Intel) -> None:
    for player in catalog.values():
        if player.id in intel.unavailable:
            kind, note = intel.unavailable[player.id]
            if kind == "doubt":
                player.status = player.status if player.is_doubt else "doubt"
            elif kind in {"injured", "sanctioned"}:
                player.status = kind
            player.starter_role = "out" if kind != "doubt" else "bench"
            if note:
                player.status_info = note
        if player.id in intel.starters:
            player.starter_role = "starter"
        elif (
            player.starter_role == "unknown"
            and player.team_id in intel.bench_teams
            and not player.is_injured_or_suspended
        ):
            player.starter_role = "bench"
        if player.id in intel.sofascore:
            player.sofascore = intel.sofascore[player.id]
        if player.id in intel.as_points:
            player.as_points = intel.as_points[player.id]
        name = (player.name or "").lower()
        if name:
            for h in intel.headlines:
                if name in h.title.lower():
                    player.headlines.append(h.title)


def enrich_catalog(client, catalog: dict[int, Player]) -> Intel:
    intel = collect(client)
    apply(catalog, intel)
    return intel
