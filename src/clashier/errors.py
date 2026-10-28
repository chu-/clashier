"""Errors shared by application operations and their adapters."""

from typing import Any, Dict, Optional


class OperationError(Exception):
    """An operation failed, possibly after producing a known effect."""

    def __init__(self, code: str, message: str, *, data: Optional[Dict[str, Any]] = None,
                 details: Optional[Dict[str, Any]] = None, safe_to_retry: bool = False,
                 needs_reconcile: bool = False):
        super().__init__(message)
        self.code = code
        self.data = data
        self.details = details or {}
        self.safe_to_retry = safe_to_retry
        self.needs_reconcile = needs_reconcile


class ControllerError(OperationError):
    """A controller rejected a request or could not be reached."""

    def __init__(self, message: str, status: Optional[int] = None, *,
                 code: str = "CONTROLLER_UNAVAILABLE", request_sent: bool = False):
        super().__init__(code, message, details={"request_sent": request_sent},
                         safe_to_retry=not request_sent)
        self.status = status
