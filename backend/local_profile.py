"""Personal loopback profile, kept only in an ignored local file."""
import os
import re
from pathlib import Path
from backend.shared.auth import create_session_token


def load_or_create_profile(path: Path) -> str:
    try:
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    output.write(create_session_token())
            except FileExistsError:
                pass
        token = path.read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError('invalid profile')
        return token
    except (OSError, ValueError):
        raise SystemExit('Local profile unavailable; preserve .env.local-profile and check its permissions') from None
