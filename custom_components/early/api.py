"""Thin async client for the EARLY (Timeular) public API v4."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)


class EarlyError(Exception):
    """Base error for the EARLY API."""


class EarlyAuthError(EarlyError):
    """Raised when the API key/secret pair is rejected."""


class EarlyConnectionError(EarlyError):
    """Raised when EARLY cannot be reached."""


class EarlyNotFoundError(EarlyError):
    """Raised when EARLY has nothing to return for the requested resource."""


class EarlyConflictError(EarlyError):
    """Raised when a request clashes with the current tracking state.

    Stopping while nothing runs is the case that shows up in practice; EARLY
    answers it with a 409 and "there is no tracking in progress".
    """


def api_timestamp(value: datetime) -> str:
    """Format a datetime the way EARLY expects it.

    EARLY exchanges naive timestamps without a zone suffix; they are UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse a naive EARLY timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _LOGGER.debug("Unparseable timestamp from EARLY: %s", value)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class EarlyApi:
    """Talks to the EARLY public API and keeps the access token fresh."""

    def __init__(self, session: ClientSession, api_key: str, api_secret: str) -> None:
        """Initialise the client."""
        self._session = session
        self._api_key = api_key
        self._api_secret = api_secret
        self._token: str | None = None
        self._token_lock = asyncio.Lock()

    async def async_sign_in(self) -> str:
        """Exchange key and secret for an access token."""
        async with self._token_lock:
            try:
                response = await self._session.post(
                    f"{API_BASE_URL}/developer/sign-in",
                    json={"apiKey": self._api_key, "apiSecret": self._api_secret},
                    timeout=TIMEOUT,
                )
                if response.status in (401, 403):
                    raise EarlyAuthError("Invalid API key or secret")
                response.raise_for_status()
                payload = await response.json()
            except ClientResponseError as err:
                raise EarlyError(f"EARLY sign-in failed: {err.status}") from err
            except (TimeoutError, ClientError) as err:
                raise EarlyConnectionError(f"Cannot reach EARLY: {err}") from err

            token = payload.get("token")
            if not token:
                raise EarlyError("EARLY sign-in returned no token")
            self._token = token
            return token

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> Any:
        """Perform a signed request, renewing the token once on a 401."""
        if self._token is None:
            await self.async_sign_in()

        try:
            response = await self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                json=json,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=TIMEOUT,
            )
        except (TimeoutError, ClientError) as err:
            raise EarlyConnectionError(f"Cannot reach EARLY: {err}") from err

        if response.status == 401 and _retry:
            # The token lifetime is undocumented, so an expired token is only
            # visible as a 401. Sign in again and replay the request once.
            self._token = None
            await self.async_sign_in()
            return await self._async_request(method, path, json=json, _retry=False)

        if response.status in (401, 403):
            raise EarlyAuthError("EARLY rejected the access token")

        if response.status == 404:
            raise EarlyNotFoundError(await self._async_error_message(response))

        if response.status == 409:
            raise EarlyConflictError(await self._async_error_message(response))

        if response.status >= 400:
            message = await self._async_error_message(response)
            raise EarlyError(f"EARLY returned {response.status}: {message}")

        if response.status == 204:
            return None
        try:
            return await response.json()
        except (ClientError, ValueError):
            # Some endpoints answer with an empty body on success.
            return None

    @staticmethod
    async def _async_error_message(response: aiohttp.ClientResponse) -> str:
        """Pull the human readable part out of an EARLY error response."""
        try:
            payload = await response.json()
        except (ClientError, ValueError):
            return response.reason or "unknown error"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if payload.get("message"):
                return str(payload["message"])
        return response.reason or "unknown error"

    async def async_get_me(self) -> dict[str, Any]:
        """Return the signed-in user, used to verify credentials."""
        return await self._async_request("GET", "/me") or {}

    async def async_get_tracking(self) -> dict[str, Any] | None:
        """Return the running tracking, or None when nothing is tracked."""
        try:
            payload = await self._async_request("GET", "/tracking")
        except EarlyNotFoundError:
            # Idle is a 404 here, not an empty body. Anything else is an error.
            return None
        if not payload:
            return None
        # v4 documents the tracking at the root, v3 wrapped it in
        # "currentTracking". Accept both so a rollback does not break us.
        if "currentTracking" in payload:
            return payload["currentTracking"] or None
        if payload.get("activity"):
            return payload
        return None

    async def async_get_activities(self) -> list[dict[str, Any]]:
        """Return the activities that can currently be tracked."""
        payload = await self._async_request("GET", "/activities") or {}
        return list(payload.get("activities") or [])

    async def async_get_time_entries(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Return the completed time entries overlapping the given range."""
        path = f"/time-entries/{api_timestamp(start)}/{api_timestamp(end)}"
        payload = await self._async_request("GET", path) or {}
        return list(payload.get("timeEntries") or [])

    async def async_start_tracking(
        self,
        activity_id: str,
        *,
        started_at: datetime | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Start tracking the given activity."""
        body: dict[str, Any] = {
            "startedAt": api_timestamp(started_at or datetime.now(UTC))
        }
        if note is not None:
            body["note"] = {"text": note}
        return await self._async_request(
            "POST", f"/tracking/{activity_id}/start", json=body
        )

    async def async_stop_tracking(
        self, stopped_at: datetime | None = None
    ) -> dict[str, Any]:
        """Stop the running tracking, turning it into a time entry."""
        body = {"stoppedAt": api_timestamp(stopped_at or datetime.now(UTC))}
        return await self._async_request("POST", "/tracking/stop", json=body)

    async def async_cancel_tracking(self) -> None:
        """Discard the running tracking without creating a time entry."""
        await self._async_request("DELETE", "/tracking")
