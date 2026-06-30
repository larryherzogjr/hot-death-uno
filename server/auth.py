"""Optional Google OAuth sign-in — verified identity (a first name) for players.

Configured entirely via environment, so the app runs unchanged when it's unset:

  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET  OAuth client (Google Cloud Console)
  HDU_BASE_URL                            public base URL, e.g. https://hdu.ospdy.com
                                          (used to build the callback; behind a proxy)
  HDU_SESSION_SECRET                      signs the session cookie — set a stable value
  HDU_REQUIRE_LOGIN=1                     require sign-in to create/join a game
  HDU_ALLOWED_EMAILS                      comma list; if set, only these may sign in

With GOOGLE_CLIENT_ID/SECRET unset, OAuth is disabled and the app behaves as
before (manual names, passcode/token gate). This is a consumer-layer concern —
the hdu/ engine is untouched.
"""

from __future__ import annotations

import os
from typing import Any

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request


def oauth_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def require_login() -> bool:
    return os.environ.get("HDU_REQUIRE_LOGIN", "").strip().lower() in ("1", "true", "yes")


def _allowed_emails() -> set[str] | None:
    raw = os.environ.get("HDU_ALLOWED_EMAILS", "").strip()
    if not raw:
        return None
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def email_allowed(email: str | None) -> bool:
    allow = _allowed_emails()
    if allow is None:
        return True
    return bool(email) and email.lower() in allow


_oauth = OAuth()
if oauth_enabled():
    _oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def google():
    return _oauth.google


def callback_url(request: Request) -> str:
    base = os.environ.get("HDU_BASE_URL", "").rstrip("/")
    return f"{base}/auth/callback" if base else str(request.url_for("auth_callback"))


def current_user(request: Request) -> dict[str, Any] | None:
    return request.session.get("user")


def session_name(user: dict[str, Any] | None) -> str | None:
    """The first name to display for a signed-in user."""
    if not user:
        return None
    given = (user.get("given_name") or "").strip()
    if given:
        return given
    full = (user.get("name") or "").strip()
    if full:
        return full.split()[0]
    email = user.get("email") or ""
    return email.split("@")[0] or None
