"""Probe: a rejected WebSocket credential must arrive as close code 1008 with a reason.

Run against a live uvicorn instance (real ASGI server, not TestClient) to prove
the browser-visible close code, which is what the kiosk UI keys off.
"""
import asyncio
import json
import sys

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8011"


async def probe(path: str, label: str):
    url = f"{BASE}{path}"
    try:
        async with websockets.connect(url) as ws:
            # Accepted-then-closed: the close frame carries code + reason.
            await ws.recv()
            print(f"{label}: UNEXPECTED — connection stayed open")
            return False
    except websockets.exceptions.ConnectionClosed as exc:
        code, reason = exc.rcvd.code, exc.rcvd.reason
        ok = code == 1008 and bool(reason)
        print(f"{label}: close_code={code} reason={reason!r} -> {'PASS' if ok else 'FAIL'}")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: FAIL — {type(exc).__name__}: {exc}")
        return False


async def main():
    results = [
        await probe("/ws?type=station", "station without credentials"),
        await probe("/ws?type=station&station_code=ST-CC-01&token=stale-token", "station with stale token"),
        await probe("/ws?type=dashboard", "dashboard without token"),
        await probe("/ws?type=dashboard&token=garbage", "dashboard with invalid token"),
        await probe("/ws?type=nonsense", "unsupported client type"),
    ]
    print(f"\n{sum(results)}/{len(results)} rejected with a readable 1008")
    return 0 if all(results) else 1


sys.exit(asyncio.run(main()))
