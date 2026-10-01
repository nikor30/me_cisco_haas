"""Base entities: one per kind of thing the controller knows about."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MeConfigEntry, MeCoordinator
from .pyciscome import AccessPoint, Radio, Wlan

MANUFACTURER = "Cisco"


def add_discovered(
    entry: MeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    discover: Callable[[MeCoordinator], Iterable[tuple[Hashable, Callable[[], Iterable[Entity]]]]],
) -> None:
    """Add entities now and whenever a poll shows something new (an AP joins, a WLAN is created).

    `discover` yields (key, factory) pairs; the factory is only called for keys not seen before.
    """
    coordinator = entry.runtime_data
    known: set[Hashable] = set()

    @callback
    def _add_new() -> None:
        entities: list[Entity] = []
        for key, factory in discover(coordinator):
            if key not in known:
                known.add(key)
                entities.extend(factory())
        if entities:
            async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class MeEntity(CoordinatorEntity[MeCoordinator]):
    _attr_has_entity_name = True

    @property
    def serial(self) -> str:
        # the coordinator refuses snapshots without a serial
        return self.coordinator.data.controller.serial  # type: ignore[return-value]


class ControllerEntity(MeEntity):
    def __init__(self, coordinator: MeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        controller = coordinator.data.controller
        self._attr_unique_id = f"{controller.serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.serial)},
            name=controller.name or "Mobility Express",
            manufacturer=MANUFACTURER,
            model="Mobility Express",
            model_id=controller.model,
            serial_number=controller.serial,
            sw_version=controller.version,
            configuration_url=f"https://{coordinator.config_entry.data['host']}",
        )


class ApEntity(MeEntity):
    def __init__(self, coordinator: MeCoordinator, ap_mac: str, key: str) -> None:
        super().__init__(coordinator)
        self._ap_mac = ap_mac
        ap = coordinator.data.access_points[ap_mac]
        self._attr_unique_id = f"{ap_mac}_{key}"
        connections = {(CONNECTION_NETWORK_MAC, ap.ethernet_mac)} if ap.ethernet_mac else set()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ap_mac)},
            connections=connections,
            name=ap.name or ap_mac,
            manufacturer=MANUFACTURER,
            model=ap.model,
            serial_number=ap.serial,
            sw_version=ap.version,
            via_device=(DOMAIN, self.serial),
        )

    @property
    def ap(self) -> AccessPoint | None:
        return self.coordinator.data.access_points.get(self._ap_mac)

    @property
    def available(self) -> bool:
        return super().available and self.ap is not None


class RadioEntity(ApEntity):
    def __init__(self, coordinator: MeCoordinator, ap_mac: str, slot: int, key: str) -> None:
        super().__init__(coordinator, ap_mac, f"radio{slot}_{key}")
        self._slot = slot
        radio = coordinator.data.access_points[ap_mac].radios[slot]
        self._attr_translation_placeholders = {"radio": f"{radio.band} GHz" if radio.band else f"Slot {slot}"}

    @property
    def radio(self) -> Radio | None:
        ap = self.ap
        return ap.radios.get(self._slot) if ap else None

    @property
    def available(self) -> bool:
        return super().available and self.radio is not None


class WlanEntity(MeEntity):
    def __init__(self, coordinator: MeCoordinator, wlan_id: int, key: str) -> None:
        super().__init__(coordinator)
        self._wlan_id = wlan_id
        wlan = coordinator.data.wlans[wlan_id]
        self._attr_unique_id = f"{self.serial}_wlan{wlan_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.serial}_wlan{wlan_id}")},
            name=f"WLAN {wlan.ssid or wlan_id}",
            manufacturer=MANUFACTURER,
            model="WLAN",
            via_device=(DOMAIN, self.serial),
        )

    @property
    def wlan(self) -> Wlan | None:
        return self.coordinator.data.wlans.get(self._wlan_id)

    @property
    def available(self) -> bool:
        return super().available and self.wlan is not None
