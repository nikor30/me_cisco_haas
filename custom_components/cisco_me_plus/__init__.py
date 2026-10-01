"""Cisco Mobility Express Plus: controller, AP, radio, WLAN and client entities over SNMP."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_COMMUNITY, DEFAULT_PORT
from .coordinator import MeConfigEntry, MeCoordinator, async_create_transport

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: MeConfigEntry) -> bool:
    transport = await async_create_transport(
        hass, entry.data[CONF_HOST], entry.data[CONF_COMMUNITY], entry.data.get(CONF_PORT, DEFAULT_PORT)
    )
    coordinator = MeCoordinator(hass, entry, transport)
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        transport.close()
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(transport.close)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_options_change(hass: HomeAssistant, entry: MeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
