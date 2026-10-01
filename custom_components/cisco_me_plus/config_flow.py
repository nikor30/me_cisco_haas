"""Config and options flow for Cisco Mobility Express Plus."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_COMMUNITY,
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import MeConfigEntry, async_create_transport
from .pyciscome import MobilityExpress, SnmpError

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_COMMUNITY): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


class MeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            transport = await async_create_transport(
                self.hass, user_input[CONF_HOST], user_input[CONF_COMMUNITY], user_input[CONF_PORT]
            )
            try:
                controller = await MobilityExpress(transport).fetch_controller()
            except SnmpError:
                errors["base"] = "cannot_connect"
            else:
                if controller.serial is None:
                    errors["base"] = "not_mobility_express"
                else:
                    await self.async_set_unique_id(controller.serial)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=controller.name or user_input[CONF_HOST], data=user_input
                    )
            finally:
                transport.close()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: MeConfigEntry) -> MeOptionsFlow:
        return MeOptionsFlow()


class MeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
                vol.Required(
                    CONF_CONSIDER_HOME, default=options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
