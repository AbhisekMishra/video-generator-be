"""
Structured logging utility with per-request context (userId, sessionId).

Usage:
    from utils.logger import get_logger, set_request_context, log_conversion_success

    logger = get_logger(__name__)
    set_request_context(user_id="user@example.com", session_id="abc-123")
    logger.info("Processing started")
    log_conversion_success(logger, "transcribe", words=1234, language="en")
"""

import logging
import sys
from contextvars import ContextVar

_user_id_var: ContextVar[str] = ContextVar('user_id', default='unknown')
_session_id_var: ContextVar[str] = ContextVar('session_id', default='unknown')


def set_request_context(user_id: str, session_id: str = 'unknown') -> None:
    """Set userId and sessionId for all log messages in the current async context."""
    _user_id_var.set(user_id)
    _session_id_var.set(session_id)


def get_user_id() -> str:
    return _user_id_var.get()


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.userId = _user_id_var.get()      # type: ignore[attr-defined]
        record.sessionId = _session_id_var.get()  # type: ignore[attr-defined]
        return True


def setup_logging() -> None:
    """Configure root logger with structured format. Call once at app startup."""
    fmt = "%(asctime)s [%(levelname)s] [userId=%(userId)s] [sessionId=%(sessionId)s] %(name)s: %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "faster_whisper", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_conversion_success(logger: logging.Logger, stage: str, **metrics) -> None:
    """
    Emit a structured CONVERSION_SUCCESS line for dashboard ingestion.

    Format:
        CONVERSION_SUCCESS | userId=X | sessionId=Y | stage=Z | key=value | ...

    Example grep filter:  grep "CONVERSION_SUCCESS"
    Example stage filter: grep "stage=render_complete"
    """
    user_id = _user_id_var.get()
    session_id = _session_id_var.get()
    parts = [f"userId={user_id}", f"sessionId={session_id}", f"stage={stage}"]
    parts += [f"{k}={v}" for k, v in metrics.items()]
    logger.info("CONVERSION_SUCCESS | " + " | ".join(parts))
