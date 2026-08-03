"""Tests for the EARLY config flow."""

from __future__ import annotations

import re

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.early.const import API_BASE_URL, CONF_API_SECRET, DOMAIN

CREDENTIALS = {CONF_API_KEY: "key", CONF_API_SECRET: "secret"}


def mock_sign_in(aioclient_mock: AiohttpClientMocker, status: int = 200) -> None:
    """Mock the sign-in and me endpoints."""
    aioclient_mock.post(
        f"{API_BASE_URL}/developer/sign-in",
        status=status,
        json={"token": "abc"} if status == 200 else {"message": "nope"},
    )
    aioclient_mock.get(
        f"{API_BASE_URL}/me",
        json={"id": "42", "name": "Jonathan", "email": "me@example.com"},
    )
    # A successful flow sets the entry up, which immediately polls EARLY.
    aioclient_mock.get(f"{API_BASE_URL}/tracking", json={"currentTracking": None})
    aioclient_mock.get(f"{API_BASE_URL}/activities", json={"activities": []})
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"),
        json={"timeEntries": []},
    )


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Valid credentials create an entry titled after the account."""
    mock_sign_in(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "me@example.com"
    assert result["data"] == CREDENTIALS
    assert result["result"].unique_id == "42"


async def test_user_flow_rejects_bad_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 from EARLY is surfaced as an auth error, not a crash."""
    mock_sign_in(aioclient_mock, status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_account_is_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The same EARLY account cannot be added twice."""
    mock_sign_in(aioclient_mock)

    for _ in range(2):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
