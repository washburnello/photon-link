"""Client for the Anycubic Photon Mono X network protocol.

The printer's WiFi module (USR-C322) is a transparent TCP<->UART bridge, so
port 6000 carries the mainboard's own command language verbatim: plain ASCII,
comma-separated, terminated by ",end". No binary framing, no checksum.

Discovered by static analysis of the mainboard firmware plus wire probing.
See docs/PROTOCOL.md.
"""
from __future__ import annotations

import socket
import time

DEFAULT_HOST = "192.168.87.251"
DEFAULT_PORT = 6000


class AnycubicError(RuntimeError):
    """Raised when the printer cannot be reached or the reply is unusable."""


class AnycubicPrinter:
    """A connection to one printer.

    Use as a context manager to hold a single connection for several commands::

        with AnycubicPrinter("192.168.87.251") as p:
            print(p.status())
            print(p.sysinfo())

    Always use a context manager (or call :meth:`close`). The module's TCP
    server accepts only ONE client at a time and has a near-zero accept
    backlog, so a single abandoned connection wedges port 6000 for everything
    else until it is released.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 4.0, quiet: float = 0.35):
        self.host = host
        self.port = port
        self.timeout = timeout
        #: How long to wait after sending before draining the reply.
        self.quiet = quiet
        self.sock: socket.socket | None = None

    # -- transport ---------------------------------------------------------
    def _connect(self) -> socket.socket:
        s = socket.socket()
        s.settimeout(self.timeout)
        try:
            s.connect((self.host, self.port))
        except OSError as exc:
            s.close()
            raise AnycubicError(
                f"cannot reach {self.host}:{self.port}: {exc}") from exc
        return s

    def _drain(self, s: socket.socket) -> str:
        """Read until the printer stops sending.

        The printer emits unsolicited lines (notably ``getmode,0,end``) that can
        be interleaved with replies, and can coalesce several replies into one
        read, so callers should tolerate extra data.
        """
        s.setblocking(False)
        buf = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except (BlockingIOError, OSError):
            pass
        finally:
            s.setblocking(True)
            s.settimeout(self.timeout)
        return buf.decode("utf-8", errors="replace")

    def send(self, cmd: str) -> str:
        """Send one raw command on the open connection and return the reply."""
        if self.sock is None:
            raise AnycubicError("not connected: use 'with AnycubicPrinter() as p'")
        self.sock.sendall(cmd.encode("ascii"))
        time.sleep(self.quiet)
        return self._drain(self.sock).strip()

    def command(self, cmd: str) -> str:
        """Send one command on a connection of its own."""
        with self as p:
            return p.send(cmd)

    # -- session management ------------------------------------------------
    def __enter__(self) -> "AnycubicPrinter":
        self.sock = self._connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    # -- read-only commands ------------------------------------------------
    def status(self) -> dict:
        """Current printer state.

        Idle printers answer ``getstatus,stop``. While printing, the reply
        carries a 12-field payload whose members are not yet fully decoded --
        see docs/PROTOCOL.md ("getstatus fields").
        """
        return _parse_status(self.command("getstatus"))

    def sysinfo(self) -> dict:
        """Model, firmware version, serial number and joined SSID.

        ``sysinfo,%s,%s,%s,%s`` -> model, version, serial, ssid
        """
        f = _fields(self.command("sysinfo"))
        keys = ("model", "firmware", "serial", "ssid")
        return dict(zip(keys, f))

    def getmode(self) -> int:
        """Operating mode as an integer."""
        f = _fields(self.command("getmode"))
        return int(f[0]) if f and f[0].lstrip("-").isdigit() else -1

    def wifi_ssid(self) -> str:
        """SSID of the network the printer is joined to."""
        f = _fields(self.command("getwifi"))
        return f[0] if f else ""

    def getpara(self) -> list[str]:
        """Printer parameters.

        Answers ``getpara,ERROR1`` unless given arguments, so the argument
        list is not yet determined.
        """
        return _fields(self.command("getpara"))

    def gethistory(self) -> str:
        """Print history. Answers ``gethistory,ERROR2`` when unsupported."""
        return self.command("gethistory")

    def getfirmware(self) -> str:
        """Firmware information. Answers ``ERROR2,end`` when unsupported."""
        return self.command("getFirmware")


# -- unconfirmed commands -------------------------------------------------
# These exist in the firmware's string table but have not been exercised.
# They change printer state, so they are deliberately not wrapped in
# convenience methods. See docs/PROTOCOL.md before calling them.

STATE_CHANGING = (
    "goprint", "gopause", "goresume", "gostop",
    "setpara", "setZhome", "setZmove", "setZstop", "setZero",
    "detect", "stopUV", "setwifi", "delfile", "delhistory",
)


# -- helpers --------------------------------------------------------------
def _fields(reply: str) -> list[str]:
    """Strip the leading verb and the trailing terminator from a reply.

    ``getmode,0,end`` -> ``["0"]``
    ``sysinfo,Photon Mono X,V3.5.4,203330345030500E,washburn home,end``
        -> ``["Photon Mono X", "V3.5.4", "203330345030500E", "washburn home"]``

    Every reply is ``<verb>,<value>...[,end]``, so token 0 is always the verb
    and is not itself a value.
    """
    parts = [p.strip() for p in reply.split(",")]
    parts = parts[1:]  # drop the verb
    while parts and parts[-1] == "":
        parts = parts[:-1]
    # Some replies terminate with "end" and some with a bare newline before it.
    if parts and parts[-1] == "end":
        parts = parts[:-1]
    return parts


def _parse_status(reply: str) -> dict:
    """Normalise a getstatus reply.

    Idle:      ``getstatus,stop`` / ``,end``       -> ``{"state": "stop"}``
    Printing:  ``getstatus,<12 values>`` / ``,end`` -> values in ``"fields"``
    """
    flat = reply.replace("\r\n", ",")
    values = [p.strip() for p in flat.split(",") if p.strip()]
    if not values or values[0] != "getstatus":
        return {"state": "unknown", "raw": reply}
    values = values[1:]
    while values and values[-1] == "end":
        values = values[:-1]
    out: dict = {"state": values[0] if values else "unknown", "raw": reply}
    # Idle units answer just "getstatus,stop"; an active print carries the full
    # 12-field payload after the state.
    if len(values) > 1:
        out["fields"] = values[1:]
    return out
