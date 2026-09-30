#!/usr/bin/env python3
"""
Transparent logging proxy for an Anycubic printer on TCP 6000.

The printer's WiFi module is a raw TCP<->UART bridge, so this sits in the middle
and records every byte both directions. Point the vendor app at THIS host instead
of the printer and we learn the protocol by observation instead of guessing.

Usage:
    python3 anyproxy.py [--listen 0.0.0.0] [--port 6000]
                        [--target 192.168.87.251:6000]
                        [--out captures]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime

import aiohttp
from aiohttp import web


class Capture:
    """Append-only binary capture with connection boundaries preserved."""

    def __init__(self, outdir: str):
        self.outdir = os.path.abspath(outdir)
        os.makedirs(self.outdir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_path = os.path.join(outdir, f"session-{stamp}.bin")
        self._fh = open(self.session_path, "ab")
        self.conn = 0
        self.dir = "?"
        self.t0 = time.time()

    def event(self, direction: str, data: bytes) -> None:
        # 1 byte dir tag + 8 byte big-endian unix ts + payload
        self._fh.write(direction.encode("ascii") + b":" + b"%016x" % int(time.time())
                       + data)
        self._fh.flush()

    def open_conn(self) -> None:
        self.conn += 1
        self.t0 = time.time()
        print(f"\n--- connection #{self.conn} ---")

    def note(self, msg: str) -> None:
        print(f"    [{time.time() - self.t0:7.3f}s] {msg}")


def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        hexs = hexs.ljust(width * 3 - 1)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:04x}  {hexs}  |{txt}|")
    return "\n".join(lines)


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
               cap: Capture, tag: str, label: str) -> None:
    total = 0
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            cap.event(tag, data)
            total += len(data)
            direction = f"{label} -> {'printer' if tag == 'T' else 'app'}"
            cap.note(f"{direction}  {len(data)}B (total {total})")
            print(hexdump(data))
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        cap.note(f"{label} closed (moved {total} bytes)")
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader: asyncio.StreamReader,
                 client_writer: asyncio.StreamWriter,
                 app: web.Application) -> None:
    cap: Capture = app["cap"]
    lock: asyncio.Lock = app["printer_lock"]
    host, port = app["target"]

    # The USR module's TCP server accepts exactly one client at a time and has
    # a near-zero accept backlog: leaving one connection half-open wedges port
    # 6000 for everybody until it is closed. So serialise every upstream
    # connection and never hold one open longer than necessary.
    await lock.acquire()
    try:
        cap.open_conn()
        try:
            printer_reader, printer_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10)
        except Exception as exc:
            cap.note(f"could not reach printer {host}:{port}: {exc!r}")
            return
        cap.note(f"bridged app -> {host}:{port}")
        try:
            await asyncio.gather(
                pipe(client_reader, printer_writer, cap, "T", "app"),
                pipe(printer_reader, client_writer, cap, "R", "printer"),
            )
        finally:
            try:
                printer_writer.close()
                await printer_writer.wait_closed()
            except Exception:
                pass
            cap.note("released printer connection")
    finally:
        lock.release()
        try:
            client_writer.close()
        except Exception:
            pass


async def control(request: web.Request) -> web.Response:
    """Tiny status endpoint so we can confirm the app is pointed at us."""
    app = request.app
    cap: Capture = app["cap"]
    return web.json_response({
        "listening": f"{app['bind']}:{app['listen_port']}",
        "target": app["target"],
        "session_file": cap.session_path,
        "connections_seen": cap.conn,
    })


async def run(args: argparse.Namespace) -> None:
    host, _, portstr = args.target.partition(":")
    cap = Capture(args.out)
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app["cap"] = cap
    app["target"] = (host, int(portstr or 6000))
    app["bind"] = args.listen
    app["listen_port"] = args.port
    app["printer_lock"] = asyncio.Lock()
    app.router.add_get("/", control)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", args.http_port)
    await site.start()

    server = await asyncio.start_server(
        lambda r, w: handle(r, w, app), args.listen, args.port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    print(f"proxy  tcp  listening on {addrs}")
    print(f"       forwarding to {host}:{portstr or 6000}")
    print(f"       http status on 127.0.0.1:{args.http_port}")
    print(f"       capturing to {cap.session_path}", flush=True)

    async with server:
        await server.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--target", default="192.168.87.251:6000")
    ap.add_argument("--out", default="captures")
    ap.add_argument("--http-port", type=int, default=8099, help="status endpoint")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass



if __name__ == "__main__":
    main()
