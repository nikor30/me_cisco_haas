"""Polling coordinators for one Mobility Express controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pysnmp.hlapi.v3arch.asyncio import SnmpEngine

from .const import (
    APP_SCAN_INTERVAL,
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RATE_STALE_SECONDS,
)
from .pyciscome import (
    Application,
    Client,
    CliError,
    MobilityExpress,
    PysnmpTransport,
    Snapshot,
    SnmpError,
    SshCli,
)

_LOGGER = logging.getLogger(__name__)

type MeConfigEntry = ConfigEntry[MeCoordinator]


async def async_create_transport(
    hass: HomeAssistant, host: str, community: str, port: int
) -> PysnmpTransport:
    """Create the SNMP transport; the engine loads MIB files, so build it off the event loop."""
    engine = await hass.async_add_executor_job(SnmpEngine)
    return PysnmpTransport(host, community, port=port, engine=engine)


def create_cli(host: str, username: str, password: str) -> SshCli:
    return SshCli(host, username, password)


@dataclass(slots=True)
class ClientTraffic:
    """Byte counters of one client and the rates derived from them, in bit/s."""

    bytes_rx: int
    bytes_tx: int
    changed_at: float
    download: float = 0.0
    upload: float = 0.0


class MeCoordinator(DataUpdateCoordinator[Snapshot]):
    """Fetch a full snapshot per interval; derive presence windows and traffic rates from it."""

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
        self.traffic: dict[str, ClientTraffic] = {}
        self.apps: MeAppCoordinator | None = None

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
        self._update_traffic(snapshot)
        return snapshot

    def _update_traffic(self, snapshot: Snapshot) -> None:
        """Turn byte counters into rates.

        The controller refreshes a client's counters only every ~90 s, so the rate is the change
        divided by the time since the counters last moved, and it is held until they move again.
        """
        now = dt_util.utcnow().timestamp()
        for mac in self.traffic.keys() - snapshot.clients.keys():
            del self.traffic[mac]
        for mac, client in snapshot.clients.items():
            if client.bytes_rx is None or client.bytes_tx is None:
                continue
            previous = self.traffic.get(mac)
            if previous is None:
                self.traffic[mac] = ClientTraffic(client.bytes_rx, client.bytes_tx, now)
                continue
            if (client.bytes_rx, client.bytes_tx) == (previous.bytes_rx, previous.bytes_tx):
                if now - previous.changed_at > RATE_STALE_SECONDS:
                    previous.download = previous.upload = 0.0
                continue
            received, sent = client.bytes_rx - previous.bytes_rx, client.bytes_tx - previous.bytes_tx
            elapsed = now - previous.changed_at
            if received < 0 or sent < 0 or elapsed <= 0:
                # counters restart when the client re-associates
                upload = download = 0.0
            else:
                # "received" is what the controller got from the client: the client's upload
                upload, download = received * 8 / elapsed, sent * 8 / elapsed
            self.traffic[mac] = ClientTraffic(client.bytes_rx, client.bytes_tx, now, download, upload)

    def client_is_home(self, mac: str) -> bool:
        """Associated now, or last associated within the consider_home window."""
        client = self.data.clients.get(mac)
        if client is not None and client.associated:
            return True
        last_seen = self.last_seen.get(mac)
        return last_seen is not None and dt_util.utcnow() - last_seen <= self.consider_home

    def rate(self, direction: str, match: Callable[[Client], bool] | None = None) -> float:
        """Summed download or upload rate in bit/s of all clients, or of those `match` selects."""
        total = 0.0
        for mac, traffic in self.traffic.items():
            client = self.data.clients.get(mac)
            if client is not None and (match is None or match(client)):
                total += getattr(traffic, direction)
        return round(total)

    def clients_by_rate(self) -> list[tuple[Client, ClientTraffic]]:
        """Clients that are moving data right now, busiest first."""
        active = [
            (client, traffic)
            for mac, traffic in self.traffic.items()
            if traffic.download + traffic.upload > 0 and (client := self.data.clients.get(mac))
        ]
        return sorted(active, key=lambda item: item[1].download + item[1].upload, reverse=True)

    def clients_by_usage(self) -> list[Client]:
        """Clients by bytes moved since they associated, biggest first."""
        used = [c for c in self.data.clients.values() if (c.bytes_rx or 0) + (c.bytes_tx or 0) > 0]
        return sorted(used, key=lambda c: (c.bytes_rx or 0) + (c.bytes_tx or 0), reverse=True)


class MeAppCoordinator(DataUpdateCoordinator[list[Application]]):
    """Top applications from AVC. Separate because it needs SSH and is slower-moving than SNMP."""

    config_entry: MeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MeConfigEntry, transport: PysnmpTransport) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title} applications",
            update_interval=timedelta(seconds=APP_SCAN_INTERVAL),
        )
        cli = create_cli(entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        self.me = MobilityExpress(transport, cli)

    async def _async_update_data(self) -> list[Application]:
        try:
            return await self.me.fetch_applications()
        except CliError as err:
            raise UpdateFailed(str(err)) from err
