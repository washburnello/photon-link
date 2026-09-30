"""Parser tests.

The reply shapes here are verbatim captures from a Photon Mono X running
firmware V3.5.4. These are the tests that caught an off-by-one in
``_fields`` (it was returning the leading verb as the first value) and a
leaked ``end`` token in ``status()["fields"]``.
"""
import pytest

from photonlink.client import (
    AnycubicError,
    AnycubicPrinter,
    _fields,
    _parse_status,
)


@pytest.mark.parametrize("raw,expected", [
    ("getmode,0,end", ["0"]),
    ("getwifi,washburn home,end", ["washburn home"]),
    (
        "sysinfo,Photon Mono X,V3.5.4,203330345030500E,washburn home,end",
        ["Photon Mono X", "V3.5.4", "203330345030500E", "washburn home"],
    ),
    # A reply may carry a trailing newline before ",end".
    ("getmode,0\n,end", ["0"]),
    # No terminator at all.
    ("getmode,0", ["0"]),
])
def test_fields_strips_verb_and_terminator(raw, expected):
    assert _fields(raw) == expected


def test_fields_does_not_return_the_verb():
    """Regression: model used to come back as "sysinfo"."""
    assert _fields("sysinfo,Photon Mono X,end")[0] == "Photon Mono X"


@pytest.mark.parametrize("raw,state,fields", [
    # Idle: bare state, no payload.
    ("getstatus,stop\r\n,end", "stop", None),
    ("getstatus,stop", "stop", None),
    # A finished print still carries a trailing value.
    ("getstatus,finish,%s\r\n,end", "finish", ["%s"]),
    # Anything else is treated as an active print.
    ("getstatus,print,end", "print", None),
])
def test_parse_status(raw, state, fields):
    out = _parse_status(raw)
    assert out["state"] == state
    assert out.get("fields") == fields


def test_parse_status_never_leaks_the_terminator():
    """Regression: "end" used to show up in status()["fields"]."""
    for raw in ("getstatus,stop\r\n,end", "getstatus,a,b\r\n,end"):
        assert "end" not in _parse_status(raw).get("fields", [])


def test_parse_status_ignores_foreign_replies():
    """The printer emits unsolicited getmode lines; don't misread them."""
    out = _parse_status("getmode,0,end")
    assert out["state"] == "unknown"
    assert out["raw"] == "getmode,0,end"


def test_send_requires_an_open_connection():
    p = AnycubicPrinter()
    with pytest.raises(AnycubicError, match="not connected"):
        p.send("getstatus")
