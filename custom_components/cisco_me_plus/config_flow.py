"""Config and options flow for Cisco Mobility Express Plus."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_COMMUNITY,
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import MeConfigEntry, async_create_transport, create_cli
from .pyciscome import CliAuthError, CliError, Controller, MobilityExpress, SnmpError

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_COMMUNITY): PASSWORD_SELECTOR,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)


class MeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> tuple[Controller | None, dict[str, str]]:
        """Check SNMP, then SSH if a login was given. Returns the controller or the form errors."""
        transport = await async_create_transport(
            self.hass, data[CONF_HOST], data[CONF_COMMUNITY], data[CONF_PORT]
        )
        try:
            controller = await MobilityExpress(transport).fetch_controller()
        except SnmpError:
            return None, {"base": "cannot_connect"}
        finally:
            transport.close()
        if controller.serial is None:
            return None, {"base": "not_mobility_express"}

        if data.get(CONF_USERNAME):
            if not data.get(CONF_PASSWORD):
                return None, {CONF_PASSWORD: "password_required"}
            cli = create_cli(data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])
            try:
                await cli.run(["show sysinfo"])
            except CliAuthError:
                return None, {"base": "invalid_auth"}
            except CliError:
                return None, {"base": "cannot_connect_ssh"}
        return controller, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            controller, errors = await self._async_validate(user_input)
            if controller is not None:
                await self.async_set_unique_id(controller.serial)
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=user_input)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=controller.name or user_input[CONF_HOST], data=user_input
                )
        suggested = user_input
        if suggested is None and self.source == SOURCE_RECONFIGURE:
            suggested = dict(self._get_reconfigure_entry().data)
        return self.async_show_form(
            step_id="reconfigure" if self.source == SOURCE_RECONFIGURE else "user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the address or credentials, e.g. to add the SSH login later."""
        return await self.async_step_user(user_input)

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
