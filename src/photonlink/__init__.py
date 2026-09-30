"""photon-link: talk to an Anycubic Photon Mono X over the network.

The printer speaks a plain ASCII command language on TCP port 6000, bridged
from its mainboard serial port by a USR-C322 WiFi module. This package wraps
it in a small, safe client.

    >>> from photonlink import AnycubicPrinter
    >>> with AnycubicPrinter("192.168.87.251") as p:
    ...     print(p.sysinfo())
    {'model': 'Photon Mono X', 'firmware': 'V3.5.4', ...}
"""

from .client import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATE_CHANGING,
    AnycubicError,
    AnycubicPrinter,
)

__version__ = "0.1.0"

__all__ = [
    "AnycubicPrinter",
    "AnycubicError",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "STATE_CHANGING",
    "__version__",
]
