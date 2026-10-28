"""Subscription downloads and explicit HTTP health requests."""

import time
from typing import Any, Dict, Optional

import httpx

from clashier.errors import OperationError


def download_subscription(url: str, timeout: float) -> str:
    """Download a subscription using the caller's normal environment proxy policy."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.RequestError as exc:
        raise OperationError("DOWNLOAD_FAILED", "Subscription download failed ({})".format(
            type(exc).__name__)) from None
    if not response.is_success:
        raise OperationError("DOWNLOAD_FAILED", "Subscription server rejected the request",
                             details={"http_status": response.status_code})
    return response.text


def check_url(url: str, proxy: Optional[str], timeout: float) -> Dict[str, Any]:
    """Check one caller-selected URL directly or through an explicit proxy."""
    started = time.monotonic()
    data = {"url": url, "via_proxy": proxy is not None, "status": "unreachable", "http_status": None}
    try:
        with httpx.Client(proxy=proxy, timeout=timeout, trust_env=False, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.RequestError as exc:
        if isinstance(exc, httpx.TimeoutException):
            data["status"] = "timeout"
        data["latency_ms"] = round((time.monotonic() - started) * 1000)
        raise OperationError("HEALTH_CHECK_FAILED", "HTTP health request failed ({})".format(
            type(exc).__name__), data=data) from None
    data.update(http_status=response.status_code, latency_ms=round((time.monotonic() - started) * 1000))
    if not response.is_success:
        data["status"] = "unhealthy"
        raise OperationError("HEALTH_CHECK_FAILED", "HTTP endpoint returned a non-success status", data=data)
    data["status"] = "reachable"
    return data
