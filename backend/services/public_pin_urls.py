"""Bounded public search identifiers and Pinterest CDN URLs; no network access."""
import re
from urllib.parse import urlsplit


def is_opaque_pin_id(value: str) -> bool:
    return re.fullmatch(r"e1_[A-Za-z0-9_-]{1,200}", value) is not None


def public_search_image(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.hostname == "i.pinimg.com"
                and url.username is None and url.password is None and url.port is None
                and url.path.startswith("/") and url.path != "/" and not url.fragment):
            return value
    except ValueError:
        pass
    return None
