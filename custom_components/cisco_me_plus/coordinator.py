"""Polling coordinator for one Mobility Express controller."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pysnmp.hlapi.v3arch.asyncio import SnmpEngine

from .const import CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME, DEFAULT_SCAN_INTERVAL, DOMAIN
from .pyciscome import MobilityExpress, PysnmpTransport, Snapshot, SnmpError

_LOGGER = logging.getLogger(__name__)

type MeConfigEntry = ConfigEntry[MeCoordinator]


async def async_create_transport(
    hass: HomeAssistant, host: str, community: str, port: int
) -> PysnmpTransport:
    """Create the SNMP transport; the engine loads MIB files, so build it off the event loop."""
    engine = await hass.async_add_executor_job(SnmpEngine)
    return PysnmpTransport(host, community, port=port, engine=engine)


class MeCoordinator(DataUpdateCoordinator[Snapshot]):
    """Fetch a full snapshot per interval and remember when each client was last associated."""

    config_entry: MeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MeConfigEntry, transport: PysnmpTransport) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.me = MobilityExpress(transport)
        self.consider_home = timedelta(seconds=entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME))
        self.last_seen: dict[str, datetime] = {}

    async def _async_update_data(self) -> Snapshot:
        try:
            snapshot = await self.me.fetch_snapshot()
        except SnmpError as err:
            raise UpdateFailed(str(err)) from err
        if snapshot.controller.serial is None:
            raise UpdateFailed("Controller did not return its inventory")
        now = dt_util.utcnow()
        for mac, client in snapshot.clients.items():
            if client.associated:
                self.last_seen[mac] = now
        return snapshot

    def client_is_home(self, mac: str) -> bool:
        """Associated now, or last associated within the consider_home window."""
        client = self.data.clients.get(mac)
        if client is not None and client.associated:
            return True
        last_seen = self.last_seen.get(mac)
        return last_seen is not None and dt_util.utcnow() - last_seen <= self.consider_home
