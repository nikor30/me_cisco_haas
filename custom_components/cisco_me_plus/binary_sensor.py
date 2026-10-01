"""Binary sensors: controller reachable, AP online, radio up, WLAN enabled."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MeConfigEntry, MeCoordinator
from .entity import ApEntity, ControllerEntity, RadioEntity, WlanEntity, add_discovered


class ControllerReachable(ControllerEntity, BinarySensorEntity):
    _attr_translation_key = "reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MeCoordinator) -> None:
        super().__init__(coordinator, "reachable")

    @property
    def available(self) -> bool:
        # this entity reports the outage instead of disappearing with it
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class ApOnline(ApEntity, BinarySensorEntity):
    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: MeCoordinator, ap_mac: str) -> None:
        super().__init__(coordinator, ap_mac, "online")

    @property
    def available(self) -> bool:
        # an AP that drops off the controller vanishes from the table: that is "offline", not "unknown"
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        ap = self.ap
        return bool(ap and ap.online)


class RadioUp(RadioEntity, BinarySensorEntity):
    _attr_translation_key = "radio_up"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: MeCoordinator, ap_mac: str, slot: int) -> None:
        super().__init__(coordinator, ap_mac, slot, "up")

    @property
    def is_on(self) -> bool | None:
        radio = self.radio
        return radio.oper_up if radio else None

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        radio = self.radio
        return {"admin_enabled": radio.admin_enabled if radio else None}


class WlanEnabled(WlanEntity, BinarySensorEntity):
    _attr_translation_key = "wlan_enabled"

    def __init__(self, coordinator: MeCoordinator, wlan_id: int) -> None:
        super().__init__(coordinator, wlan_id, "enabled")

    @property
    def is_on(self) -> bool | None:
        wlan = self.wlan
        return wlan.enabled if wlan else None


def _discover(coordinator: MeCoordinator) -> Iterable[tuple[Hashable, Callable[[], Iterable[Entity]]]]:
    snapshot = coordinator.data
    yield "controller", lambda: [ControllerReachable(coordinator)]
    for mac, ap in snapshot.access_points.items():
        yield ("ap", mac), lambda mac=mac: [ApOnline(coordinator, mac)]
        for slot in ap.radios:
            yield ("radio", mac, slot), lambda mac=mac, slot=slot: [RadioUp(coordinator, mac, slot)]
    for wlan_id in snapshot.wlans:
        yield ("wlan", wlan_id), lambda wlan_id=wlan_id: [WlanEnabled(coordinator, wlan_id)]


async def async_setup_entry(
    hass: HomeAssistant, entry: MeConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    add_discovered(entry, async_add_entities, _discover)
