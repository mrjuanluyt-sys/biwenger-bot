from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biwenger.client import BiwengerClient
from biwenger.services import (
    budget_report,
    build_lineup,
    calendar_text,
    clause_report,
    daily_briefing,
    market_report,
    sell_report,
    squad_text,
    standings_text,
)
from biwenger.settings import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_check() -> int:
    client = BiwengerClient()
    client.login()
    team = client.get_my_team()
    print(f"OK  equipo={team.name}  id={team.team_id}  liga={client.league_id}")
    print(f"    saldo={team.balance}  jugadores={len(team.player_ids)}  pts={team.points}")
    print(f"    dry_run={settings.dry_run}  version={settings.app_version}")
    return 0


def cmd_once() -> int:
    client = BiwengerClient()
    client.login()
    text, _buttons, _ = build_lineup(client)
    print(text)
    print("\n" + "=" * 40 + "\n")
    market, _ = market_report(client)
    print(market)
    return 0


def cmd_print(kind: str) -> int:
    client = BiwengerClient()
    client.login()
    if kind == "lineup":
        text, _, _ = build_lineup(client)
    elif kind == "market":
        text, _ = market_report(client)
    elif kind == "squad":
        text = squad_text(client)
    elif kind == "sell":
        text, _ = sell_report(client)
    elif kind == "calendar":
        text = calendar_text(client)
    elif kind == "table":
        text = standings_text(client)
    elif kind == "briefing":
        text, _ = daily_briefing(client)
    elif kind == "budget":
        text, _ = budget_report(client)
    elif kind == "clauses":
        text, _ = clause_report(client)
    elif kind == "intel":
        from biwenger.services import intel_report

        text, _ = intel_report(client)
    elif kind == "edge":
        from biwenger.services import edge_report

        text, _ = edge_report(client)
    else:
        raise SystemExit(f"kind desconocido: {kind}")
    print(text)
    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Bot personal de Biwenger")
    parser.add_argument("--check", action="store_true", help="Probar login y mostrar contexto")
    parser.add_argument("--once", action="store_true", help="Imprimir XI + mercado y salir")
    parser.add_argument(
        "--print",
        dest="kind",
        choices=["lineup", "market", "squad", "sell", "calendar", "table", "briefing", "budget", "clauses", "intel", "edge"],
        help="Imprimir un informe concreto",
    )
    args = parser.parse_args()

    if args.check:
        return cmd_check()
    if args.once:
        return cmd_once()
    if args.kind:
        return cmd_print(args.kind)

    start_health_server()
    from bot.telegram_app import run_bot

    run_bot()
    return 0


def start_health_server() -> None:
    """Keep-alive para hosts gratuitos (Render/Koyeb)."""
    port = int(os.environ.get("PORT", "8080"))

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    def serve():
        HTTPServer(("0.0.0.0", port), Health).serve_forever()

    threading.Thread(target=serve, daemon=True).start()
    logging.getLogger(__name__).info("Health en :%s", port)

    public = os.environ.get("PUBLIC_URL", "").strip()
    if public:
        def ping():
            import time
            import requests

            while True:
                time.sleep(240)
                try:
                    requests.get(public, timeout=10)
                except Exception:
                    pass

        threading.Thread(target=ping, daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())
