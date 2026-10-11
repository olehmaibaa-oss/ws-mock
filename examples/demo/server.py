"""
Demo backend for ws-mock: a food delivery "My orders" screen.

Serves index.html on / and pushes the whole list of orders over WebSocket on /ws.
One JSON frame = the whole screen, same shape as most real "list over socket" APIs.

Run:
    pip install aiohttp
    python3 server.py --host 0.0.0.0 --port 8000 --orders 60

Open it via your Mac's LAN IP (not localhost), otherwise traffic bypasses the proxy.
"""
import argparse
import asyncio
import json
import random as _random
import time
from pathlib import Path

from aiohttp import web

HERE = Path(__file__).parent

PLACES = [
    "Bao Bar", "Pho Corner", "Pizza Lab", "Green Bowl", "Taco Shed", "Sushi Line",
    "Burger Yard", "Curry House", "Falafel Kings", "Noodle Box", "Bagel Co", "Poke Point",
]
COURIERS = ["Sam", "Priya", "Tom", "Ana", "Kofi", "Lena", "Max", "Ivy"]
FLOW = ["placed", "preparing", "on_the_way", "delivered"]


def make_orders(n: int, seed: int = 42) -> list[dict]:
    # fixed seed: same ids every run, so presets can point at them
    rnd = _random.Random(seed)
    now = int(time.time())
    orders = []
    for i in range(n):
        status = rnd.choice(FLOW + ["placed", "preparing", "on_the_way"])
        orders.append({
            "id": 1000 + i,
            "restaurant": PLACES[i % len(PLACES)],
            "items": rnd.randint(1, 6),
            "total": {"amount": round(rnd.uniform(8, 60), 2), "currency": "GBP"},
            "status": status,
            "step": {"current": FLOW.index(status) + 1, "of": len(FLOW)},
            "courier": {"name": rnd.choice(COURIERS)} if status == "on_the_way" else None,
            "eta": now + rnd.randint(5, 45) * 60,
            "note": "Leave at the door, please. " * 2,
        })
    return orders


def tick(orders: list[dict]) -> None:
    """Move some orders forward so the screen visibly lives."""
    for o in orders:
        if o["status"] in ("delivered", "cancelled") or _random.random() > 0.08:
            continue
        nxt = FLOW[FLOW.index(o["status"]) + 1]
        o["status"] = nxt
        o["step"]["current"] = FLOW.index(nxt) + 1
        if nxt == "on_the_way":
            o["courier"] = {"name": _random.choice(COURIERS)}


async def index(_req: web.Request) -> web.FileResponse:
    return web.FileResponse(HERE / "index.html")


async def ws_handler(req: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
    await ws.prepare(req)
    orders = make_orders(req.app["n"])
    seq = 0
    try:
        while not ws.closed:
            seq += 1
            frame = {"type": "orders.snapshot", "seq": seq, "ts": int(time.time()), "orders": orders}
            await ws.send_str(json.dumps(frame))
            await asyncio.sleep(req.app["interval"])
            tick(orders)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return ws


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--orders", type=int, default=12,
                    help="more orders = bigger frame; anything over 4000 bytes hits the mitmproxy fragmentation issue")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between pushes")
    args = ap.parse_args()

    app = web.Application()
    app["n"] = args.orders
    app["interval"] = args.interval
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    print(f"demo on http://{args.host}:{args.port}  ws://{args.host}:{args.port}/ws  orders={args.orders}")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
