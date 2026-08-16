"""Cliente HTTP de la API no oficial de Biwenger (`api/v2`).

Biwenger no publica API. Estos endpoints son los de la propia web.
Si algo deja de funcionar, abre F12 → Network en biwenger.as.com y mira
la petición equivalente.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests

from .models import (
    Fixture,
    LeagueStanding,
    Lineup,
    MarketListing,
    Offer,
    Player,
    Position,
    TeamState,
    UpcomingFixture,
)
from .settings import Settings, settings as default_settings

logger = logging.getLogger(__name__)

API_BASE = "https://biwenger.as.com/api/v2"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class BiwengerError(RuntimeError):
    pass


class BiwengerAuthError(BiwengerError):
    pass


class BiwengerVersionError(BiwengerError):
    pass


class BiwengerClient:
    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or default_settings
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": BROWSER_UA,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://biwenger.as.com",
                "Referer": "https://biwenger.as.com/",
            }
        )
        self._token: str | None = self.cfg.token or None
        self._app_version = self.cfg.app_version or "631"
        self._league_id = self.cfg.league_id or None
        self._team_id = self.cfg.user_id or None
        if self._token:
            self._session.headers.update(self._auth_headers())

    @property
    def team_id(self) -> int | None:
        return int(self._team_id) if self._team_id else None

    @property
    def league_id(self) -> int | None:
        return int(self._league_id) if self._league_id else None

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Lang": "es",
            "X-Version": str(self._app_version),
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._league_id:
            headers["X-League"] = str(self._league_id)
        if self._team_id:
            headers["X-User"] = str(self._team_id)
        return headers

    def login(self) -> None:
        if self._token and not self.cfg.has_password_login:
            self._session.headers.update(self._auth_headers())
            self._resolve_context()
            logger.info(
                "Sesión por token (liga=%s equipo=%s versión=%s)",
                self._league_id,
                self._team_id,
                self._app_version,
            )
            return
        if not self.cfg.has_password_login:
            raise BiwengerAuthError(
                "Falta login. Pon BIWENGER_EMAIL+BIWENGER_PASSWORD o BIWENGER_TOKEN en .env"
            )
        resp = self._session.post(
            f"{API_BASE}/auth/login",
            json={"email": self.cfg.email, "password": self.cfg.password},
            headers={"X-Lang": "es", "X-Version": self._app_version},
            timeout=20,
        )
        if resp.status_code != 200:
            raise BiwengerAuthError(f"Login falló ({resp.status_code}): {resp.text[:240]}")
        payload = resp.json()
        self._token = payload.get("token") or (payload.get("data") or {}).get("token")
        if not self._token:
            raise BiwengerAuthError(f"Login OK pero sin token: {payload}")
        self._session.headers.update(self._auth_headers())
        self._resolve_context()
        logger.info(
            "Login OK (liga=%s equipo=%s versión=%s)",
            self._league_id,
            self._team_id,
            self._app_version,
        )

    def update_token(self, token: str) -> None:
        self._token = token.strip()
        self._session.headers.update(self._auth_headers())

    def _resolve_context(self) -> None:
        if self._league_id and self._team_id:
            return
        headers = {k: v for k, v in self._auth_headers().items() if k not in ("X-League", "X-User")}
        resp = self._session.get(f"{API_BASE}/account", headers=headers, timeout=20)
        if resp.status_code == 401:
            raise BiwengerAuthError("Token inválido o caducado. Renueva BIWENGER_TOKEN o el password.")
        resp.raise_for_status()
        data = resp.json().get("data", {})
        leagues = (
            data.get("leagues")
            or (data.get("account") or {}).get("leagues")
            or (data.get("lastSession") or {}).get("leagues")
            or []
        )
        if not leagues:
            raise BiwengerAuthError("La cuenta no tiene ligas.")
        chosen = leagues[0]
        if self.cfg.league_id:
            chosen = next((lg for lg in leagues if str(lg.get("id")) == str(self.cfg.league_id)), chosen)
        self._league_id = self._league_id or str(chosen["id"])
        self._team_id = self._team_id or str((chosen.get("user") or {}).get("id") or "")
        if not self._team_id:
            raise BiwengerAuthError("No pude resolver el id del equipo (X-User). Pon BIWENGER_USER_ID.")
        self._session.headers.update(self._auth_headers())

    def _ensure_auth(self) -> None:
        if not self._token:
            self.login()
            return
        if not self._league_id or not self._team_id:
            self._resolve_context()

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self._ensure_auth()
        kwargs.setdefault("timeout", 20)
        kwargs.setdefault("headers", self._auth_headers())
        resp = self._session.request(method, url, **kwargs)
        if resp.status_code == 400 and "version" in resp.text.lower():
            raise BiwengerVersionError(
                f"Biwenger rechaza X-Version={self._app_version}. "
                "Actualiza BIWENGER_APP_VERSION (F12 → Network → header X-Version)."
            )
        if resp.status_code == 401:
            if self.cfg.has_password_login:
                self._token = None
                self.login()
                kwargs["headers"] = self._auth_headers()
                resp = self._session.request(method, url, **kwargs)
            else:
                raise BiwengerAuthError(
                    "Token caducado. Saca uno nuevo: localStorage.getItem('satellizer_token')"
                )
        if resp.status_code >= 400:
            raise BiwengerError(f"{method} {url} → {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    def get_my_team(self) -> TeamState:
        fields = "*,lineup(type,captain,playersID),players(id,owner),balance"
        data = self._request("GET", f"{API_BASE}/user", params={"fields": fields})["data"]
        owned = {int(p["id"]): p.get("owner") or {} for p in data.get("players") or []}
        raw = data.get("lineup") or {}
        lineup = None
        if raw.get("playersID"):
            lineup = Lineup(
                formation=raw.get("type") or "",
                player_ids=[int(i) for i in (raw.get("playersID") or []) if i is not None],
                captain_id=raw.get("captain"),
            )
        return TeamState(
            team_id=int(self._team_id or 0),
            name=data.get("name") or "",
            balance=int(data.get("balance") or 0),
            player_ids=list(owned.keys()),
            lineup=lineup,
            owned=owned,
            points=int(data.get("points") or 0),
        )

    def get_market(self) -> tuple[list[MarketListing], int, int]:
        """Ventas + saldo + puja máxima."""
        data = self._request("GET", f"{API_BASE}/market")["data"]
        listings: list[MarketListing] = []
        for sale in data.get("sales") or []:
            user = sale.get("user")
            until = sale.get("until") or 0
            bids = sale.get("bids") or sale.get("offers") or []
            bid_count = int(sale.get("bidCount") or sale.get("bidsCount") or 0)
            if isinstance(bids, list) and bids:
                bid_count = max(bid_count, len(bids))
            listings.append(
                MarketListing(
                    player_id=int(sale["player"]["id"]),
                    price=int(sale.get("price") or 0),
                    until=datetime.fromtimestamp(until, tz=timezone.utc) if until else datetime.now(timezone.utc),
                    seller_id=user.get("id") if user else None,
                    seller_name=user.get("name") if user else None,
                    bid_count=bid_count,
                )
            )
        status = data.get("status") or {}
        balance = int(status.get("balance") or 0)
        max_bid = int(status.get("maximumBid") or 0)
        return listings, balance, max_bid

    def get_my_purchase_ids(self) -> set[int]:
        """Jugadores por los que YA tenemos una puja/oferta nuestra (en curso o hecha)."""
        data = self._request("GET", f"{API_BASE}/offers", params={"limit": 50})["data"] or []
        mine: set[int] = set()
        me = self.team_id
        for raw in data:
            frm = (raw.get("from") or {}).get("id")
            if me and frm and int(frm) != int(me):
                continue
            if frm is None and (raw.get("to") or {}).get("id") == me:
                continue  # nos pujan a nosotros
            status = (raw.get("status") or "").lower()
            if status in {"rejected", "cancelled", "canceled"}:
                continue
            for item in raw.get("requestedPlayers") or []:
                pid = item.get("id") if isinstance(item, dict) else item
                if pid:
                    mine.add(int(pid))
        return mine

    def get_offers(self) -> list[Offer]:
        data = self._request("GET", f"{API_BASE}/user", params={"fields": "offers"})["data"]
        offers: list[Offer] = []
        for raw in data.get("offers") or []:
            frm = raw.get("from") or {}
            offers.append(
                Offer(
                    id=int(raw.get("id") or 0),
                    amount=int(raw.get("amount") or 0),
                    player_ids=[int(i) for i in (raw.get("requestedPlayers") or [])],
                    from_id=frm.get("id"),
                    from_name=frm.get("name") or "?",
                    status=raw.get("status") or "",
                    until=raw.get("until"),
                )
            )
        return offers

    def get_all_players(self) -> dict[int, Player]:
        data = self._request(
            "GET",
            f"{API_BASE}/competitions/{self.cfg.competition}/data",
            params={"lang": "es", "score": 5},
        )["data"]
        teams = data.get("teams") or {}
        difficulty = _difficulty_by_team(teams)
        team_names = {int(tid): (td.get("name") or str(tid)) for tid, td in teams.items() if str(tid).isdigit()}
        raw_players = data.get("players") or {}
        max_games = 0
        games_by_id: dict[int, int] = {}
        for pid, pdata in raw_players.items():
            games = int(pdata.get("playedHome") or 0) + int(pdata.get("playedAway") or 0)
            games_by_id[int(pid)] = games
            max_games = max(max_games, games)

        result: dict[int, Player] = {}
        for pid, pdata in raw_players.items():
            try:
                player = player_from_json(pdata)
            except (KeyError, ValueError, TypeError):
                continue
            player.points_last_season = int(pdata.get("pointsLastSeason") or 0)
            player.points = int(pdata.get("points") or 0)
            if player.team_id in difficulty:
                player.fixture_difficulty = difficulty[player.team_id]
            if player.team_id in team_names:
                player.team_name = team_names[player.team_id]
            games = games_by_id.get(player.id, 0)
            player.starter_rate = (games / max_games) if max_games else 1.0
            player.points_home = int(pdata.get("pointsHome") or 0)
            player.points_away = int(pdata.get("pointsAway") or 0)
            player.played_home = int(pdata.get("playedHome") or 0)
            player.played_away = int(pdata.get("playedAway") or 0)
            result[player.id] = player
        return result

    def enrich_my_squad(self) -> tuple[TeamState, list[Player], dict[int, Player]]:
        team = self.get_my_team()
        catalog = self.get_all_players()
        squad: list[Player] = []
        for pid in team.player_ids:
            player = catalog.get(pid)
            if not player:
                continue
            player.is_owned_by_me = True
            owner = team.owned.get(pid) or {}
            player.clause = owner.get("clause")
            player.buy_price = owner.get("price")
            squad.append(player)
        return team, squad, catalog

    def get_team_fixtures(self, weeks: int = 5) -> dict[int, list[UpcomingFixture]]:
        data = self._request(
            "GET",
            f"{API_BASE}/competitions/{self.cfg.competition}/data",
            params={"lang": "es", "score": 5},
        )["data"]
        return _team_fixtures(data.get("teams") or {}, weeks)

    def get_current_round_id(self) -> int | None:
        data = self._request("GET", f"{API_BASE}/rounds/league")["data"]
        return (data.get("round") or {}).get("id")

    def get_round_detail(self) -> dict:
        round_id = self.get_current_round_id()
        if not round_id:
            return {}
        return self._request(
            "GET",
            f"{API_BASE}/rounds/{self.cfg.competition}/{round_id}",
            params={"lang": "es", "score": 5},
        )["data"] or {}

    def get_round_fixtures(self) -> list[Fixture]:
        data = self.get_round_detail()
        if not data:
            return []
        fixtures: list[Fixture] = []
        for game in data.get("games") or []:
            home = game.get("home") or {}
            away = game.get("away") or {}
            fixtures.append(
                Fixture(
                    home=home.get("name") or "?",
                    away=away.get("name") or "?",
                    home_difficulty=_rating(home),
                    away_difficulty=_rating(away),
                    status=game.get("status") or "",
                    date=int(game.get("date") or 0),
                )
            )
        return fixtures

    def get_standings(self) -> list[LeagueStanding]:
        data = self._request(
            "GET",
            f"{API_BASE}/league",
            params={"include": "all", "fields": "*,standings"},
        )["data"]
        out: list[LeagueStanding] = []
        for idx, row in enumerate(data.get("standings") or [], start=1):
            out.append(
                LeagueStanding(
                    team_id=int(row.get("id") or 0),
                    name=row.get("name") or "?",
                    points=int(row.get("points") or 0),
                    position=int(row.get("position") or idx),
                    team_value=int(row.get("teamValue") or 0),
                    team_value_inc=int(row.get("teamValueInc") or 0),
                    team_size=int(row.get("teamSize") or 0),
                )
            )
        return out

    def get_league_settings(self) -> dict:
        data = self._request("GET", f"{API_BASE}/league", params={"fields": "settings"})["data"]
        settings = dict(data.get("settings") or {})
        settings.pop("secret", None)
        return settings

    def get_season_news(self, since_epoch: int, page_size: int = 50, max_pages: int = 12) -> list[dict]:
        """Noticias de la liga desde `since_epoch` (más recientes primero)."""
        if self.league_id is None:
            return []
        out: list[dict] = []
        for page in range(max_pages):
            chunk = self._request(
                "GET",
                f"{API_BASE}/league/{self.league_id}/news",
                params={"limit": page_size, "offset": page * page_size},
            )["data"] or []
            if not chunk:
                break
            stop = False
            for item in chunk:
                if int(item.get("date") or 0) < since_epoch:
                    stop = True
                    continue
                out.append(item)
            if stop or len(chunk) < page_size:
                break
        return out

    def get_manager_roster(self, user_id: int) -> list[int]:
        data = self._request(
            "GET",
            f"{API_BASE}/user/{user_id}",
            params={"fields": "players(id)"},
        )["data"]
        return [int(p["id"]) for p in (data.get("players") or [])]

    def attach_league_owners(self, catalog: dict[int, Player]) -> dict[int, Player]:
        """Cuelga dueño + cláusula de cada plantilla de la liga sobre el catálogo."""
        standings = self.get_standings()
        me = self.team_id

        def _fetch(uid: int, name: str) -> tuple[int, str, list[dict]]:
            data = self._request(
                "GET",
                f"{API_BASE}/user/{uid}",
                params={"fields": "players(id,owner)"},
            )["data"]
            return uid, name, data.get("players") or []

        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(_fetch, s.team_id, s.name) for s in standings]
            for fut in as_completed(futs):
                uid, name, players = fut.result()
                for raw in players:
                    player = catalog.get(int(raw["id"]))
                    if not player:
                        continue
                    owner = raw.get("owner") or {}
                    if "loan" in owner:
                        player.on_loan = True
                        loan_user = (owner.get("loan") or {}).get("user") or {}
                        player.owner_id = loan_user.get("id") or uid
                        player.owner_name = loan_user.get("name") or name
                        if owner.get("price") is not None:
                            player.buy_price = owner.get("price")
                        continue
                    player.owner_id = uid
                    player.owner_name = name
                    player.clause = owner.get("clause")
                    player.buy_price = owner.get("price")
                    player.is_owned_by_me = me is not None and uid == me
        return catalog

    def pay_clause(self, player_id: int, amount: int, owner_id: int | None = None) -> dict | None:
        payload = {
            "type": "clause",
            "amount": int(amount),
            "requestedPlayers": [int(player_id)],
            "user": int(owner_id) if owner_id else None,
        }
        if self.cfg.dry_run:
            logger.info("[DRY RUN] pay_clause %s", payload)
            return {"dry_run": True, **payload}
        return self._request("POST", f"{API_BASE}/offers", json=payload)

    def first_kickoff_epoch(self) -> int | None:
        dates = [fx.date for fx in self.get_round_fixtures() if fx.date]
        return min(dates) if dates else None

    # --- escrituras (respetan DRY_RUN) ---------------------------------
    def set_lineup(self, player_ids: list[int], formation: str, captain_id: int | None = None) -> dict | None:
        payload = {
            "lineup": {
                "type": formation,
                "playersID": [int(p) for p in player_ids],
                "captain": captain_id,
            }
        }
        if self.cfg.dry_run:
            logger.info("[DRY RUN] set_lineup %s", payload)
            return {"dry_run": True, **payload}
        try:
            return self._request("PUT", f"{API_BASE}/user", json=payload)
        except BiwengerError:
            return self._request("POST", f"{API_BASE}/user", json=payload)

    def place_bid(self, player_id: int, amount: int, seller_id: int | None = None) -> dict | None:
        payload = {
            "type": "purchase",
            "amount": int(amount),
            "requestedPlayers": [int(player_id)],
            "user": int(seller_id) if seller_id else None,
        }
        if self.cfg.dry_run:
            logger.info("[DRY RUN] place_bid %s", payload)
            return {"dry_run": True, **payload}
        return self._request("POST", f"{API_BASE}/offers", json=payload)

    def accept_offer(self, offer_id: int) -> dict | None:
        if self.cfg.dry_run:
            logger.info("[DRY RUN] accept_offer(%s)", offer_id)
            return {"dry_run": True, "id": offer_id}
        try:
            return self._request("PUT", f"{API_BASE}/offers/{offer_id}", json={"status": "accepted"})
        except BiwengerError:
            return self._request("POST", f"{API_BASE}/offers/{offer_id}", json={"status": "accepted"})

    def reject_offer(self, offer_id: int) -> dict | None:
        if self.cfg.dry_run:
            logger.info("[DRY RUN] reject_offer(%s)", offer_id)
            return {"dry_run": True, "id": offer_id}
        try:
            return self._request("PUT", f"{API_BASE}/offers/{offer_id}", json={"status": "rejected"})
        except BiwengerError:
            return self._request("POST", f"{API_BASE}/offers/{offer_id}", json={"status": "rejected"})

    def list_for_sale(self, player_id: int, price: int) -> dict | None:
        payload = {"player": int(player_id), "price": int(price)}
        if self.cfg.dry_run:
            logger.info("[DRY RUN] list_for_sale %s", payload)
            return {"dry_run": True, **payload}
        return self._request("POST", f"{API_BASE}/market", json=payload)

    def remove_from_sale(self, player_id: int) -> dict | None:
        if self.cfg.dry_run:
            logger.info("[DRY RUN] remove_from_sale(%s)", player_id)
            return {"dry_run": True, "player": player_id}
        return self._request("DELETE", f"{API_BASE}/market/{int(player_id)}")


def _fix_text(raw) -> str:
    text = str(raw or "")
    if "Ã" in text or "Â" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return text


def player_from_json(data: dict) -> Player:
    try:
        position = Position(int(data.get("position") or 0))
    except ValueError:
        position = Position.MIDFIELDER
    team = data.get("teamID") or data.get("team")
    if isinstance(team, dict):
        team_id = team.get("id")
        team_name = team.get("name")
    else:
        team_id = team
        team_name = None
    return Player(
        id=int(data["id"]),
        name=data.get("name") or "?",
        position=position,
        price=int(data.get("price") or 0),
        price_increment=int(data.get("priceIncrement") or 0),
        status=data.get("status") or "ok",
        status_info=_fix_text(data.get("statusInfo") or data.get("statusText") or ""),
        fitness=_extract_fitness(data.get("fitness") or data.get("reports")),
        slug=data.get("slug"),
        team_id=int(team_id) if team_id else None,
        team_name=team_name,
        points=int(data.get("points") or 0),
        points_last_season=int(data.get("pointsLastSeason") or 0),
        price_history=_extract_prices(data.get("prices")),
    )


def _extract_fitness(raw: Any) -> list[int]:
    if not raw:
        return []
    points: list[int] = []
    for item in raw:
        if isinstance(item, (int, float)):
            points.append(int(item))
        elif isinstance(item, dict):
            p = item.get("points")
            if isinstance(p, (int, float)):
                points.append(int(p))
            elif isinstance(p, dict):
                val = p.get("1")
                if isinstance(val, (int, float)):
                    points.append(int(val))
    return points


def _extract_prices(raw: Any) -> list[tuple[int, int]]:
    if not raw or not isinstance(raw, list):
        return []
    out: list[tuple[int, int]] = []
    for item in raw:
        try:
            out.append((int(item[0]), int(item[1])))
        except (ValueError, TypeError, IndexError):
            continue
    out.sort()
    return out


def _rating(side: dict) -> float | None:
    diff = (side or {}).get("difficulty") or {}
    rating = diff.get("rating")
    return float(rating) if rating is not None else None


def _difficulty_by_team(teams: dict) -> dict[int, float]:
    result: dict[int, float] = {}
    for tid, tdata in (teams or {}).items():
        try:
            team_id = int(tid)
        except (TypeError, ValueError):
            continue
        games = tdata.get("nextGames") or []
        if not games:
            continue
        game = games[0]
        for side in ("home", "away"):
            s = game.get(side) or {}
            if s.get("id") == team_id and isinstance(s.get("difficulty"), dict):
                rating = s["difficulty"].get("rating")
                if rating is not None:
                    result[team_id] = float(rating)
                break
    return result


def _team_fixtures(teams: dict, weeks: int) -> dict[int, list[UpcomingFixture]]:
    names = {}
    for tid, tdata in (teams or {}).items():
        try:
            names[int(tid)] = tdata.get("name") or str(tid)
        except (TypeError, ValueError):
            continue
    result: dict[int, list[UpcomingFixture]] = {}
    for tid, tdata in (teams or {}).items():
        try:
            team_id = int(tid)
        except (TypeError, ValueError):
            continue
        runs: list[UpcomingFixture] = []
        for game in (tdata.get("nextGames") or [])[:weeks]:
            if not isinstance(game, dict):
                continue
            side = "home" if (game.get("home") or {}).get("id") == team_id else "away"
            other = "away" if side == "home" else "home"
            me = game.get(side) or {}
            opp = game.get(other) or {}
            rating = None
            diff = me.get("difficulty")
            if isinstance(diff, dict):
                rating = diff.get("rating")
            opp_name = opp.get("name") or names.get(opp.get("id"), "?")
            runs.append(
                UpcomingFixture(
                    opponent=opp_name,
                    is_home=(side == "home"),
                    difficulty=float(rating) if rating is not None else None,
                    date=int(game.get("date") or 0),
                )
            )
        if runs:
            result[team_id] = runs
    return result
