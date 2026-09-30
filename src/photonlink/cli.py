"""Command line interface: ``photonlink <command>``."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .client import DEFAULT_HOST, DEFAULT_PORT, AnycubicError, AnycubicPrinter


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2))


def cmd_info(args) -> int:
    with AnycubicPrinter(args.host, args.port) as p:
        _dump(p.sysinfo())
    return 0


def cmd_status(args) -> int:
    with AnycubicPrinter(args.host, args.port) as p:
        _dump(p.status())
    return 0


def cmd_wifi(args) -> int:
    with AnycubicPrinter(args.host, args.port) as p:
        print(p.wifi_ssid())
    return 0


def cmd_raw(args) -> int:
    """Send an arbitrary command. Refuses state-changing verbs by default."""
    verb = args.command.split(",", 1)[0].strip()
    if not args.yes and verb in _state_changing():
        print(
            f"refusing to send state-changing command {verb!r} without --yes\n"
            f"see docs/PROTOCOL.md for what it does",
            file=sys.stderr,
        )
        return 2
    with AnycubicPrinter(args.host, args.port) as p:
        print(p.send(args.command))
    return 0


def cmd_watch(args) -> int:
    """Poll getstatus, printing each distinct reply once."""
    seen: dict[str, int] = {}
    order: list[str] = []
    t0 = time.time()
    with AnycubicPrinter(args.host, args.port, quiet=0.15) as p:
        while time.time() - t0 < args.seconds:
            try:
                raw = p.send("getstatus")
            except AnycubicError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            key = raw.replace("\r\n", " | ")
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                order.append(key)
                print(f"[{time.time() - t0:6.1f}s] {key}", flush=True)
            time.sleep(args.interval)
    print(f"\n{len(order)} distinct replies in {args.seconds:.0f}s")
    return 0


def _state_changing() -> tuple[str, ...]:
    from .client import STATE_CHANGING
    return STATE_CHANGING


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="photonlink",
        description="Talk to an Anycubic Photon Mono X (TCP 6000, ASCII protocol).",
    )
    ap.add_argument("--host", default=DEFAULT_HOST, help="printer IP")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="model, firmware, serial, SSID").set_defaults(fn=cmd_info)
    sub.add_parser("status", help="current print state").set_defaults(fn=cmd_status)
    sub.add_parser("wifi", help="current SSID").set_defaults(fn=cmd_wifi)

    p_raw = sub.add_parser("raw", help="send a raw command")
    p_raw.add_argument("command")
    p_raw.add_argument("--yes", action="store_true",
                       help="allow state-changing commands")
    p_raw.set_defaults(fn=cmd_raw)

    p_watch = sub.add_parser("watch", help="poll status and show changes")
    p_watch.add_argument("--seconds", type=float, default=120.0)
    p_watch.add_argument("--interval", type=float, default=2.0)
    p_watch.set_defaults(fn=cmd_watch)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except AnycubicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
