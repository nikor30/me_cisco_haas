"""Presence: one tracker per wireless client MAC, with a configurable consider_home window."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import DOMAIN as TRACKER_DOMAIN
from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MeConfigEntry, MeCoordinator
from .pyciscome import Client


async def async_setup_entry(
    hass: HomeAssistant, entry: MeConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new(macs: set[str]) -> None:
        new = macs - known
        if new:
            known.update(new)
            async_add_entities(MeClientTracker(coordinator, mac) for mac in sorted(new))

    # clients that are away during startup must keep their entity: restore them from the registry
    registry = er.async_get(hass)
    _add_new(
        {
            entity.unique_id
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
            if entity.domain == TRACKER_DOMAIN
        }
    )
    _add_new(set(coordinator.data.clients))
    entry.async_on_unload(coordinator.async_add_listener(lambda: _add_new(set(coordinator.data.clients))))


class MeClientTracker(CoordinatorEntity[MeCoordinator], ScannerEntity):
    # signal values change on every poll; keep them out of the recorder
    _unrecorded_attributes = frozenset({"rssi", "snr", "data_rate", "download_bps", "upload_bps"})

    def __init__(self, coordinator: MeCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._attr_mac_address = mac
        self._attr_name = mac
        self._client: Client | None = None
        self._update_from_snapshot()

    def _update_from_snapshot(self) -> None:
        client = self.coordinator.data.clients.get(self._attr_mac_address or "")
        if client is not None:
            # keep the last known details while the client is away
            self._client = client
            self._attr_ip_address = client.ip
            self._attr_hostname = client.username

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_snapshot()
        super()._handle_coordinator_update()

    @property
    def is_connected(self) -> bool:
        return self.coordinator.client_is_home(self._attr_mac_address or "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        client = self._client
        if client is None:
            return {}
        attributes = {
            "ssid": client.ssid,
            "wlan_id": client.wlan_id,
            "ap_name": client.ap_name,
            "ap_mac": client.ap_mac,
            "band": client.band,
            "protocol": client.protocol,
            "device_type": client.device_type,
            "rssi": client.rssi,
            "snr": client.snr,
            "data_rate": client.data_rate_mbps,
        }
        traffic = self.coordinator.traffic.get(client.mac)
        if traffic is not None and self.coordinator.data.clients.get(client.mac) is client:
            attributes["download_bps"] = round(traffic.download)
            attributes["upload_bps"] = round(traffic.upload)
        return {key: value for key, value in attributes.items() if value is not None}
