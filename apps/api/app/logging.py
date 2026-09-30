"""Structured logging (implementation shared with the agent)."""

from cmc_shared.logging import (
    ConsoleFormatter,
    JsonFormatter,
    bind_correlation,
    configure_logging,
    correlation_var,
    request_id_var,
)

__all__ = [
    "ConsoleFormatter",
    "JsonFormatter",
    "bind_correlation",
    "configure_logging",
    "correlation_var",
    "request_id_var",
]
