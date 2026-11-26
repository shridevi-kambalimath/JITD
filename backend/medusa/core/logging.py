"""Logging setup.

* One configuration for the app and uvicorn, so all lines share a format.
* Every record carries the current request id (or '-' outside a request).
* Text format for local work, JSON lines for anything machine-read.
* Optional rotating file handler.

configure_logging is idempotent: it replaces only the handlers it installed itself.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
from contextvars import ContextVar
from datetime import datetime, timezone

from .config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"
_EXTRA_FIELDS = ("method", "path", "status_code", "duration_ms", "client")
_MARK = "_medusa_handler"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_format == "json" else logging.Formatter(_TEXT_FORMAT)
    )
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file is not None:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            settings.log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"))

    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(h)
        h.close()
    for h in handlers:
        setattr(h, _MARK, True)
        h.setFormatter(formatter)
        h.addFilter(RequestIdFilter())
        root.addHandler(h)
    root.setLevel(settings.log_level)

    # Route uvicorn through the same handlers. Our middleware logs each request,
    # so uvicorn's own access log would only duplicate it.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
