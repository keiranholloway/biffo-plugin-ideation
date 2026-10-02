"""Read the owner's email from a bearer token the ingress has already verified.

The plugin host verifies the JWT's signature, issuer, audience and expiry before
this code ever sees it (and Core re-verifies it on every forwarded call), so the
payload is only *read* here, never trusted for authorisation. ``ForwardedUser``
carries ``sub``, groups and the raw token only, so the email has to come from the
claims. Best-effort: a token without an ``email`` claim (e.g. an access token)
yields ``None`` and the session simply records no email.
"""

from __future__ import annotations

import base64
import json


def email_from_token(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, UnicodeDecodeError):
        return None
    email = claims.get("email") if isinstance(claims, dict) else None
    return email.strip() or None if isinstance(email, str) else None
