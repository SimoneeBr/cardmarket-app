"""Structured logging with correlation IDs carried through contextvars."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_var: ContextVar[dict[str, str]] = ContextVar("correlation", default={})  # noqa: B039

# Keys that must never be written to logs, even if passed in ``extra``.
_REDACTED_KEYS = frozenset(
    {"password", "password_hash", "token", "authorization", "cookie", "secret", "body"}
)


def bind_correlation(**ids: str) -> None:
    correlation_var.set({**correlation_var.get(), **ids})


class JsonFormatter(logging.Formatter):
    _STANDARD = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if rid := request_id_var.get():
            payload["request_id"] = rid
        payload.update(correlation_var.get())
        for key, value in record.__dict__.items():
            if key in self._STANDARD or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if key.lower() in _REDACTED_KEYS else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ids = dict(correlation_var.get())
        if rid := request_id_var.get():
            ids["request_id"] = rid
        suffix = " ".join(f"{k}={v}" for k, v in ids.items())
        return f"{base} {suffix}".rstrip()


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Access logs are produced by our middleware with request ids.
    logging.getLogger("uvicorn.access").disabled = True
