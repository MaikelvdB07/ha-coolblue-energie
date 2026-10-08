"""Config and options flow."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CoolblueApi, CoolblueAuthError
from .const import (
    CONF_BLOCK_HOURS,
    CONF_DEBTOR_ID,
    CONF_ENERGY_TAX,
    CONF_GAS_PRICE_FALLBACK,
    CONF_LOCATION_ID,
    CONF_PRICE_MODE,
    CONF_PURCHASE_FEE,
    CONF_VAT,
    DEFAULT_BLOCK_HOURS,
    DEFAULT_ENERGY_TAX,
    DEFAULT_GAS_PRICE_FALLBACK,
    DEFAULT_NAME,
    DEFAULT_PRICE_MODE,
    DEFAULT_PURCHASE_FEE,
    DEFAULT_VAT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        vol.Required(CONF_PASSWORD): _PASSWORD,
    }
)
_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD})


def _euro(step: float = 0.00001, minimum: float = 0, maximum: float = 5) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    )


async def _try_connect(email: str, password: str) -> tuple[str, str, str | None]:
    try:
        async with CoolblueApi(email, password) as api:
            debtor, location = await api.get_energy_ids()
        return debtor, location, None
    except CoolblueAuthError:
        return "", "", "invalid_auth"
    except Exception:
        _LOGGER.exception("Kon niet verbinden met Coolblue")
        return "", "", "cannot_connect"


class CoolbluePricesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CoolbluePricesOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            debtor, location, error = await _try_connect(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"{debtor}_{location}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={
                        **user_input,
                        CONF_DEBTOR_ID: debtor,
                        CONF_LOCATION_ID: location,
                    },
                )
        return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            _, _, error = await _try_connect(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        )


class CoolbluePricesOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRICE_MODE, default=o.get(CONF_PRICE_MODE, DEFAULT_PRICE_MODE)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=["all_in", "market"],
                        translation_key=CONF_PRICE_MODE,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_PURCHASE_FEE, default=o.get(CONF_PURCHASE_FEE, DEFAULT_PURCHASE_FEE)
                ): _euro(),
                vol.Required(
                    CONF_ENERGY_TAX, default=o.get(CONF_ENERGY_TAX, DEFAULT_ENERGY_TAX)
                ): _euro(),
                vol.Required(CONF_VAT, default=o.get(CONF_VAT, DEFAULT_VAT)): _euro(
                    step=0.1, maximum=100
                ),
                vol.Required(
                    CONF_BLOCK_HOURS, default=o.get(CONF_BLOCK_HOURS, DEFAULT_BLOCK_HOURS)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=12, step=0.25, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_GAS_PRICE_FALLBACK,
                    default=o.get(CONF_GAS_PRICE_FALLBACK, DEFAULT_GAS_PRICE_FALLBACK),
                ): _euro(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
