"""
auth.py

Overgenomen uit barisdemirdelen/homeassistant-coolblue-energy (MIT-licentie,
Copyright (c) Baris Demirdelen).

OIDC authentication for the Coolblue portal.

Two rounds are required to obtain both session cookies:
  Round 1 – standard email/password login  → sets ``Coolblue-Session``
  Round 2 – energy-page redirect flow      → sets ``Secure-Coolblue``
"""

from __future__ import annotations

import logging
import secrets
from typing import Self

import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_ACCOUNTS_BASE = "https://accounts.coolblue.nl"

_AUTH_BASE = (
    f"{_ACCOUNTS_BASE}/connect/authorize"
    "?authentication_state=Unknown"
    "&client_id=Webshop"
    "&redirect_uri=https%3A%2F%2Fwww.coolblue.nl%2Fen%2Flogin%2Foidc"
    "&response_type=code"
    "&scope=openid+email+profile+offline_access"
    "+openid%3Acustomerid+openid%3Aidentityroleid"
    "+ucp%3Ascopes%3Acheckout_session+openid"
    "&ui_locales=en-US+en"
)

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0"

# Headers sent on every HTML page request (mirrors a real Firefox GET of a document).
_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "DNT": "1",
}


def _auth_url() -> str:
    """Build an OIDC authorize URL with fresh state and nonce values."""
    state = secrets.token_hex(16)
    nonce = secrets.token_hex(16)
    return f"{_AUTH_BASE}&nonce={nonce}&state={state}"


def _get_csrf(html: str, view: str) -> str:
    """
    Extract the CSRF JWT from the form that contains ``view=<view>``.
    Falls back to the first csrf input on the page.
    """
    soup = BeautifulSoup(html, "html.parser")
    view_input = soup.find("input", {"name": "view", "value": view})
    if view_input:
        form = view_input.find_parent("form")
        if form:
            csrf_input = form.find("input", {"name": "csrf"})
            if csrf_input:
                return str(csrf_input["value"])

    csrf_input = soup.find("input", {"name": "csrf"})
    if not csrf_input:
        raise ValueError(f"No CSRF token found on page (looking for view={view!r})")
    return str(csrf_input["value"])


# ── Exceptions ────────────────────────────────────────────────────────────────


class CoolblueAuthError(RuntimeError):
    """Coolblue rejected the account credentials.

    Raised where a login is refused, so callers branch on the type instead of
    reading an error message. A ``RuntimeError`` subclass because that is what
    ``api_client.API_ERRORS`` already promises callers of the client.
    """


# ── AuthService ───────────────────────────────────────────────────────────────


class AuthService:
    """
    Async OIDC authentication for the Coolblue Energy portal.

    Usage::

        auth = AuthService("you@example.com", "secret")
        session = await auth.get_session()   # authenticates lazily
        await auth.close()                   # or use as async context manager

        async with AuthService("you@example.com", "secret") as auth:
            session = await auth.get_session()
    """

    def __init__(self, email: str, password: str, energy_url: str) -> None:
        self._email = email
        self._password = password
        self._energy_url = energy_url
        self._session: aiohttp.ClientSession | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Return the authenticated session, authenticating lazily if needed."""
        if self._session is None or self._session.closed:
            await self.authenticate()
        assert self._session is not None
        return self._session

    async def authenticate(self) -> None:
        """
        Perform the full two-round OIDC login flow and store the session.

        :raises aiohttp.ClientResponseError: on non-2xx HTTP responses
        :raises CoolblueAuthError:           when Coolblue rejects the credentials
        :raises RuntimeError:                on other flow errors
        """
        if self._session and not self._session.closed:
            await self._session.close()

        session = aiohttp.ClientSession(headers=_BROWSER_HEADERS)

        try:
            logger.debug("Auth round 1: establish Coolblue-Session")
            await self._oidc_round(session, _auth_url())

            # Round 2: GET energy page → redirect → /nl/inloggen?returnUrl=… → accounts URL
            # That accounts URL carries returnUrl in its state, causing the OIDC
            # callback to also issue Secure-Coolblue.
            logger.debug("Auth round 2: obtain Secure-Coolblue")
            async with session.get(self._energy_url, allow_redirects=False) as r:
                logger.debug("Round 2 energy page status: %d", r.status)
                if r.status in (301, 302, 303, 307, 308):
                    loc = r.headers.get("Location", "")
                    if loc.startswith("/"):
                        loc = "https://www.coolblue.nl" + loc
                    async with session.get(loc, allow_redirects=False) as r2:
                        logger.debug(
                            "Round 2 login redirect status: %d → %s",
                            r2.status,
                            r2.headers.get("Location", "(none)")[:80],
                        )
                        if r2.status in (301, 302, 303, 307, 308):
                            accounts_url = r2.headers["Location"]
                            logger.debug("Round 2 accounts URL: %s", accounts_url[:80])
                            await self._oidc_round(session, accounts_url)
                        else:
                            logger.warning(
                                "Round 2: expected a redirect from login page "
                                "but got %d — Secure-Coolblue will not be set",
                                r2.status,
                            )
                else:
                    logger.warning(
                        "Round 2: expected a redirect from energy page but got %d "
                        "— Secure-Coolblue will not be set",
                        r.status,
                    )

        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            await session.close()
            raise

        cookies = session.cookie_jar.filter_cookies(URL(self._energy_url))
        if "Secure-Coolblue" not in cookies:
            logger.warning("Secure-Coolblue was not set – energy API calls may fail")

        logger.info("Authentication successful. Cookies: %s", list(cookies.keys()))
        self._session = session

    async def _oidc_round(self, session: aiohttp.ClientSession, auth_url: str) -> None:
        """Complete one OIDC email + password round starting from *auth_url*."""
        logger.debug("OIDC round: GET %s", auth_url[:80])
        async with session.get(auth_url, headers={"Sec-Fetch-Site": "none"}) as r:
            if r.status == 403:
                raise RuntimeError(
                    f"Cloudfront blocked the accounts login page (403). "
                    f"URL: {str(r.url)[:100]} — your IP may be rate-limited or "
                    "Coolblue has tightened WAF rules."
                )
            r.raise_for_status()
            html = await r.text()
            page_url = str(r.url)

        csrf = _get_csrf(html, "email-exists")
        async with session.post(
            page_url,
            data={"view": "email-exists", "csrf": csrf, "username": self._email},
            headers={"Sec-Fetch-Site": "same-origin", "Referer": page_url},
        ) as r:
            if r.status == 403:
                raise RuntimeError(
                    f"Cloudfront blocked the email-check POST (403). "
                    f"URL: {str(r.url)[:100]}"
                )
            r.raise_for_status()
            html = await r.text()
            page_url = str(r.url)

        csrf = _get_csrf(html, "login")
        # Stop before the final redirect — accounts.coolblue.nl will redirect
        # to www.coolblue.nl/en/login/oidc, which is a cross-site navigation.
        # We replay that redirect ourselves with the correct Sec-Fetch-Site
        # header so Cloudfront does not block it.
        async with session.post(
            page_url,
            data={
                "view": "login",
                "csrf": csrf,
                "username": self._email,
                "password": self._password,
            },
            headers={"Sec-Fetch-Site": "same-origin", "Referer": page_url},
            allow_redirects=False,
        ) as r:
            if r.status == 403:
                raise RuntimeError(
                    f"Cloudfront blocked the password POST (403). "
                    f"URL: {str(r.url)[:100]}"
                )
            if r.status not in (301, 302, 303, 307, 308):
                r.raise_for_status()
                raise CoolblueAuthError(
                    "Coolblue did not accept the account credentials: expected a "
                    f"redirect after the password POST but got {r.status}."
                )
            callback_url = r.headers["Location"]
            if callback_url.startswith("/"):
                callback_url = "https://accounts.coolblue.nl" + callback_url

        logger.debug("OIDC callback: GET %s", callback_url[:80])
        # Follow all subsequent redirects normally; only the first hop (from
        # accounts → www.coolblue.nl) needs Sec-Fetch-Site: cross-site.
        async with session.get(
            callback_url,
            headers={
                "Sec-Fetch-Site": "cross-site",
                "Referer": "https://accounts.coolblue.nl/",
            },
        ) as r:
            if r.status == 403:
                raise RuntimeError(
                    f"Cloudfront blocked the OIDC callback (403). "
                    f"URL: {str(r.url)[:100]} — your IP may be rate-limited or "
                    "Coolblue has tightened WAF rules. Try again later."
                )
            r.raise_for_status()
            if "accounts.coolblue.nl" in str(r.url):
                raise CoolblueAuthError(
                    "Coolblue did not accept the account credentials: still on the "
                    "accounts page after the OIDC callback."
                )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
