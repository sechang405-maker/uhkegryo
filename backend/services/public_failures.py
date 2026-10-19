"""Bounded public lookup failures; no retry for access restrictions or bad data."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx


def retry_after(value):
    if not value:
        return None
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


def public_failure(error):
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            return 'access_restricted', False, None
        if code == 429:
            return 'rate_limited', True, retry_after(error.response.headers.get('retry-after')) or 60
        if code in (404, 410):
            return 'deleted', False, None
        if code in (500, 502, 503, 504):
            return 'temporary', True, retry_after(error.response.headers.get('retry-after'))
    if isinstance(error, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
        return 'temporary', True, None
    return 'unavailable', False, None
