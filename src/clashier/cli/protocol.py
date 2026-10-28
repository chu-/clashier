"""Versioned result data and request validation; rendering lives in render.py."""

import json
import time
import uuid
from datetime import datetime, timezone
from pkgutil import get_data
from typing import Any, Dict, Optional

import click
import httpx
from jsonschema import Draft202012Validator

from clashier.bootstrap import Bootstrap
from clashier.errors import OperationError
from clashier.models import SelectRequest

SCHEMAS = {"proxy.select": "proxy-select", "proxy.list": "proxy-list", "proxy.probe": "proxy-probe"}


class HttpURL(click.ParamType):
    """Validate an explicit HTTP URL at the CLI boundary."""

    name = "http-url"

    def convert(self, value, param, ctx):
        try:
            parsed = httpx.URL(value)
        except httpx.InvalidURL:
            self.fail("Expected an absolute HTTP(S) URL", param, ctx)
        if parsed.scheme not in ("http", "https") or not parsed.host:
            self.fail("Expected an absolute HTTP(S) URL", param, ctx)
        return value


HTTP_URL = HttpURL()


def load_schema(name: str) -> Dict[str, Any]:
    """Read a published schema from installed package resources."""
    return json.loads(get_data("clashier", "schemas/" + name + "-v1.json").decode("utf-8"))


def envelope(data: Any, state: Optional[Bootstrap] = None,
             error: Optional[OperationError] = None) -> Dict[str, Any]:
    """Project an operation into the stable wire format."""
    context = state.context() if state else None
    if context is not None:
        context = dict(context, source="live", observed_at=datetime.now(timezone.utc).isoformat())
    return {"schema_version": "1", "ok": error is None, "data": data,
            "error": None if error is None else {"code": error.code, "message": str(error),
            "safe_to_retry": error.safe_to_retry, "needs_reconcile": error.needs_reconcile,
            "details": error.details}, "context": context,
            "meta": {"request_id": state.request_id if state else uuid.uuid4().hex,
                     "duration_ms": round((time.monotonic() - state.started) * 1000) if state else 0}}


def select_request(path: Optional[str], fields: Dict[str, Any]) -> SelectRequest:
    """Validate once, at the CLI input boundary, before constructing a request."""
    if path is not None:
        if any(value is not None for value in fields.values()):
            raise click.UsageError("--input-json cannot be combined with selection fields")
        try:
            with click.open_file(path, encoding="utf-8") as stream:
                payload = json.load(stream)
        except (ValueError, OSError) as exc:
            raise click.UsageError("Invalid JSON input: {}".format(type(exc).__name__)) from None
    else:
        payload = {key: value for key, value in fields.items() if value is not None}
    errors = list(Draft202012Validator(load_schema("proxy-select-input")).iter_errors(payload))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "request"
        raise click.UsageError("Invalid {}: check required fields and their types (schema show proxy.select)".format(
            location))
    return SelectRequest(**payload)
