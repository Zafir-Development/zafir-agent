"""uvicorn server construction for the gateway's loopback session listener.

The listener serves one native WebSocket route on loopback; there is no browser peer and no
dashboard application, so the server takes no proxy headers, no keepalive ping on loopback (a dead
local client sends a real FIN/RST) and no compression (loopback bytes are free and deflate runs on
the event loop for every streamed token).
"""

import logging
import sys


def _uvicorn_console_logging() -> None:
    """uvicorn's default console logging, without its ``dictConfig``.

    ``uvicorn.Config``'s default ``log_config`` runs ``dictConfig``, which calls
    ``logging.shutdown()`` on every live handler: a multiplexed gateway's profile log routers are
    already installed when its listener is built, and a closed router stays closed. The listener
    passes ``log_config=None`` and gets uvicorn's handlers here instead: ``uvicorn`` to stderr,
    ``uvicorn.access`` to stdout, neither propagating into the Hermes log files.
    """
    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter, DefaultFormatter

    formats = LOGGING_CONFIG["formatters"]
    for name, stream, formatter in (
        ("uvicorn", sys.stderr, DefaultFormatter(formats["default"]["fmt"])),
        ("uvicorn.access", sys.stdout, AccessFormatter(formats["access"]["fmt"])),
    ):
        logger = logging.getLogger(name)
        logger.propagate = False
        if not logger.handlers:  # a second listener in this process keeps the first one's
            handler = logging.StreamHandler(stream)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    # LOGGING_CONFIG's level for the parent; uvicorn.Config sets only the child loggers' levels.
    logging.getLogger("uvicorn").setLevel(logging.INFO)


def build_listener_server(served_app, host: str, port: int, *, ws_max_size: int,
                          timeout_graceful_shutdown: float = 5):
    """uvicorn ``Config`` + ``Server`` for the gateway's local session listener (FastAPI-free)."""
    import uvicorn

    _uvicorn_console_logging()
    config = uvicorn.Config(
        served_app, host=host, port=port, log_level="warning", log_config=None,
        # A loopback listener has no upstream proxy: never honour X-Forwarded-*.
        proxy_headers=False, forwarded_allow_ips=None,
        # No WS keepalive ping on loopback: it only detects half-open connections, impossible there
        # where a dead client sends a real FIN/RST (the ping would run on the agent event loop).
        ws_ping_interval=None, ws_ping_timeout=None,
        ws_per_message_deflate=False,
        ws_max_size=ws_max_size,
        # A client sends a single SIGTERM; uvicorn's default (None) waits on lingering ASGI tasks
        # forever, so a mid-turn request orphans the listener past that budget.
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        lifespan="off",
    )
    return config, uvicorn.Server(config)
