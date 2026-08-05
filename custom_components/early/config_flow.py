"""Config flow for the EARLY (Timeular) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import EarlyApi, EarlyAuthError, EarlyConnectionError, EarlyError
from .const import CONF_API_SECRET, DEFAULT_WORKDAY_HOURS, DOMAIN, WEEKDAYS

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): str, vol.Required(CONF_API_SECRET): str}
)

# hassfest rejects literal URLs in strings.json, so it is filled in here.
DESCRIPTION_PLACEHOLDERS = {"url": "https://product.early.app"}


HOUR_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0, max=24, step=0.25, mode=NumberSelectorMode.BOX, unit_of_measurement="h"
    )
)


class EarlyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of an EARLY account."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EarlyOptionsFlow:
        """Return the flow that edits the working-time target."""
        return EarlyOptionsFlow()

    async def _async_validate(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Sign in and return the EARLY user behind the credentials."""
        api = EarlyApi(
            async_get_clientsession(self.hass),
            data[CONF_API_KEY],
            data[CONF_API_SECRET],
        )
        await api.async_sign_in()
        return await api.async_get_me()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                me = await self._async_validate(user_input)
            except EarlyAuthError:
                errors["base"] = "invalid_auth"
            except EarlyConnectionError:
                errors["base"] = "cannot_connect"
            except EarlyError:
                _LOGGER.exception("Unexpected error while validating EARLY credentials")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(str(me.get("id")))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=me.get("email") or me.get("name") or "EARLY",
                    data=dict(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle credentials that stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh API key and secret."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                me = await self._async_validate(user_input)
            except EarlyAuthError:
                errors["base"] = "invalid_auth"
            except EarlyConnectionError:
                errors["base"] = "cannot_connect"
            except EarlyError:
                _LOGGER.exception("Unexpected error while validating EARLY credentials")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(str(me.get("id")))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=dict(user_input)
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )


class EarlyOptionsFlow(OptionsFlow):
    """Edits the working hours the tracked time is compared against.

    EARLY's own UI has this setting, but the public API does not expose it, so
    it is kept per config entry here.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the target hours per weekday."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(day, default=options.get(day, fallback)): HOUR_SELECTOR
                    for day, fallback in zip(
                        WEEKDAYS, DEFAULT_WORKDAY_HOURS, strict=True
                    )
                }
            ),
        )
