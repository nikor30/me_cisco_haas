"""Sensors for the controller, APs, radios and WLANs."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfFrequency,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TOP_LIST_SIZE
from .coordinator import MeConfigEntry, MeCoordinator
from .entity import ApEntity, ControllerEntity, RadioEntity, WlanEntity, add_discovered
from .pyciscome import AccessPoint, Client, Radio, Snapshot, Wlan
from .pyciscome.models import BAND_5, BAND_24

# an uptime-derived boot time moves by a second or two between polls; ignore that
UPTIME_TOLERANCE = timedelta(minutes=2)


@dataclass(frozen=True, kw_only=True)
class MeSensorDescription[T](SensorEntityDescription):
    value_fn: Callable[[T], StateType]
    is_uptime: bool = False


MEASUREMENT = SensorStateClass.MEASUREMENT
DIAGNOSTIC = EntityCategory.DIAGNOSTIC

CONTROLLER_SENSORS: tuple[MeSensorDescription[Snapshot], ...] = (
    MeSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
        entity_category=DIAGNOSTIC,
        value_fn=lambda s: s.controller.cpu_percent,
    ),
    MeSensorDescription(
        key="memory",
        translation_key="memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
        entity_category=DIAGNOSTIC,
        value_fn=lambda s: s.controller.memory_used_percent,
    ),
    MeSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=DIAGNOSTIC,
        is_uptime=True,
        value_fn=lambda s: s.controller.uptime_seconds,
    ),
    MeSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=MEASUREMENT,
        value_fn=lambda s: sum(1 for c in s.clients.values() if c.associated),
    ),
    MeSensorDescription(
        key="clients_24",
        translation_key="clients_24",
        state_class=MEASUREMENT,
        value_fn=lambda s: s.clients_on_band(BAND_24),
    ),
    MeSensorDescription(
        key="clients_5",
        translation_key="clients_5",
        state_class=MEASUREMENT,
        value_fn=lambda s: s.clients_on_band(BAND_5),
    ),
    MeSensorDescription(
        key="access_points",
        translation_key="access_points",
        state_class=MEASUREMENT,
        value_fn=lambda s: sum(1 for ap in s.access_points.values() if ap.online),
    ),
)

AP_SENSORS: tuple[MeSensorDescription[AccessPoint], ...] = (
    MeSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=MEASUREMENT,
        value_fn=lambda ap: ap.client_count,
    ),
    MeSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=DIAGNOSTIC,
        is_uptime=True,
        value_fn=lambda ap: ap.uptime_seconds,
    ),
    MeSensorDescription(
        key="ip",
        translation_key="ip",
        entity_category=DIAGNOSTIC,
        value_fn=lambda ap: ap.ip,
    ),
)

RADIO_SENSORS: tuple[MeSensorDescription[Radio], ...] = (
    MeSensorDescription(
        key="channel",
        translation_key="radio_channel",
        value_fn=lambda r: r.channel,
    ),
    MeSensorDescription(
        key="channel_width",
        translation_key="radio_channel_width",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        entity_category=DIAGNOSTIC,
        value_fn=lambda r: r.channel_width_mhz,
    ),
    MeSensorDescription(
        key="tx_power_level",
        translation_key="radio_tx_power_level",
        entity_category=DIAGNOSTIC,
        value_fn=lambda r: r.tx_power_level,
    ),
    MeSensorDescription(
        key="utilization",
        translation_key="radio_utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
        value_fn=lambda r: r.channel_utilization,
    ),
    MeSensorDescription(
        key="noise",
        translation_key="radio_noise",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=MEASUREMENT,
        entity_category=DIAGNOSTIC,
        value_fn=lambda r: r.noise_dbm,
    ),
    MeSensorDescription(
        key="clients",
        translation_key="radio_clients",
        state_class=MEASUREMENT,
        value_fn=lambda r: r.client_count,
    ),
)

WLAN_SENSORS: tuple[MeSensorDescription[Wlan], ...] = (
    MeSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=MEASUREMENT,
        value_fn=lambda w: w.client_count,
    ),
)


class MeSensorMixin(SensorEntity):
    """Shared state handling; the concrete classes say which object the description reads."""

    entity_description: MeSensorDescription
    _boot_time: datetime | None = None

    def _source(self) -> object | None:
        raise NotImplementedError

    @property
    def native_value(self) -> StateType | datetime:
        source = self._source()
        if source is None:
            return None
        value = self.entity_description.value_fn(source)
        if not self.entity_description.is_uptime:
            return value
        if value is None:
            return None
        boot_time = dt_util.utcnow().replace(microsecond=0) - timedelta(seconds=value)
        if self._boot_time is None or abs(boot_time - self._boot_time) > UPTIME_TOLERANCE:
            self._boot_time = boot_time
        return self._boot_time


class ControllerSensor(MeSensorMixin, ControllerEntity):
    def __init__(self, coordinator: MeCoordinator, description: MeSensorDescription[Snapshot]) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _source(self) -> Snapshot:
        return self.coordinator.data


class ApSensor(MeSensorMixin, ApEntity):
    def __init__(
        self, coordinator: MeCoordinator, ap_mac: str, description: MeSensorDescription[AccessPoint]
    ) -> None:
        super().__init__(coordinator, ap_mac, description.key)
        self.entity_description = description

    def _source(self) -> AccessPoint | None:
        return self.ap


class RadioSensor(MeSensorMixin, RadioEntity):
    def __init__(
        self, coordinator: MeCoordinator, ap_mac: str, slot: int, description: MeSensorDescription[Radio]
    ) -> None:
        super().__init__(coordinator, ap_mac, slot, description.key)
        self.entity_description = description

    def _source(self) -> Radio | None:
        return self.radio


class WlanSensor(MeSensorMixin, WlanEntity):
    def __init__(
        self, coordinator: MeCoordinator, wlan_id: int, description: MeSensorDescription[Wlan]
    ) -> None:
        super().__init__(coordinator, wlan_id, description.key)
        self.entity_description = description

    def _source(self) -> Wlan | None:
        return self.wlan


DIRECTIONS = ("download", "upload")


class RateSensorMixin(SensorEntity):
    """Throughput summed over the clients the concrete class selects."""

    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.BITS_PER_SECOND
    _attr_suggested_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _direction: str

    def _set_direction(self, direction: str) -> None:
        self._direction = direction
        self._attr_translation_key = f"{direction}_rate"

    def _matches(self, client: Client) -> bool:
        return True

    @property
    def native_value(self) -> float:
        return self.coordinator.rate(self._direction, self._matches)


class ControllerRateSensor(RateSensorMixin, ControllerEntity):
    def __init__(self, coordinator: MeCoordinator, direction: str) -> None:
        super().__init__(coordinator, f"{direction}_rate")
        self._set_direction(direction)


class ApRateSensor(RateSensorMixin, ApEntity):
    def __init__(self, coordinator: MeCoordinator, ap_mac: str, direction: str) -> None:
        super().__init__(coordinator, ap_mac, f"{direction}_rate")
        self._set_direction(direction)

    def _matches(self, client: Client) -> bool:
        return client.ap_mac == self._ap_mac


class WlanRateSensor(RateSensorMixin, WlanEntity):
    def __init__(self, coordinator: MeCoordinator, wlan_id: int, direction: str) -> None:
        super().__init__(coordinator, wlan_id, f"{direction}_rate")
        self._set_direction(direction)

    def _matches(self, client: Client) -> bool:
        return client.wlan_id == self._wlan_id


class TopClientSensor(ControllerEntity, SensorEntity):
    """Name of the busiest client; the ranked list is in the attributes."""

    # the list changes on every poll and would bloat the recorder
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(self, coordinator: MeCoordinator, by_usage: bool) -> None:
        key = "top_client_usage" if by_usage else "top_client"
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._by_usage = by_usage

    def _name(self, client: Client) -> str:
        """The name the user gave the client's tracker, else its MAC."""
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, client.mac)
        entry = registry.async_get(entity_id) if entity_id else None
        return (entry.name if entry else None) or client.mac

    def _ranking(self) -> list[dict[str, str | int | None]]:
        rows: list[dict[str, str | int | None]] = []
        if self._by_usage:
            for client in self.coordinator.clients_by_usage()[:TOP_LIST_SIZE]:
                rows.append({"bytes_down": client.bytes_tx, "bytes_up": client.bytes_rx})
                rows[-1] |= self._describe(client)
        else:
            for client, traffic in self.coordinator.clients_by_rate()[:TOP_LIST_SIZE]:
                rows.append({"download_bps": round(traffic.download), "upload_bps": round(traffic.upload)})
                rows[-1] |= self._describe(client)
        return rows

    def _describe(self, client: Client) -> dict[str, str | int | None]:
        return {
            "name": self._name(client),
            "mac": client.mac,
            "ip": client.ip,
            "ap": client.ap_name,
            "ssid": client.ssid,
        }

    @property
    def native_value(self) -> str | None:
        ranking = self._ranking()
        return str(ranking[0]["name"]) if ranking else None

    @property
    def extra_state_attributes(self) -> dict[str, list[dict[str, str | int | None]]]:
        return {"clients": self._ranking()}


class TopApplicationSensor(ControllerEntity, SensorEntity):
    """Busiest application according to AVC; the ranked list is in the attributes."""

    _attr_translation_key = "top_application"
    _unrecorded_attributes = frozenset({"applications"})

    def __init__(self, coordinator: MeCoordinator) -> None:
        super().__init__(coordinator, "top_application")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.apps is not None:
            self.async_on_remove(self.coordinator.apps.async_add_listener(self._handle_apps_update))

    @callback
    def _handle_apps_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        apps = self.coordinator.apps
        return apps is not None and apps.last_update_success

    @property
    def native_value(self) -> str | None:
        apps = self.coordinator.apps
        return apps.data[0].name if apps and apps.data else None

    @property
    def extra_state_attributes(self) -> dict[str, list[dict[str, str | int]]]:
        apps = self.coordinator.apps
        return {
            "applications": [
                {
                    "name": app.name,
                    "bytes_down": app.bytes_down,
                    "bytes_up": app.bytes_up,
                    "total_bytes_down": app.total_bytes_down,
                    "total_bytes_up": app.total_bytes_up,
                }
                for app in (apps.data if apps and apps.data else [])[:TOP_LIST_SIZE]
            ]
        }


def _controller_sensors(coordinator: MeCoordinator) -> list[Entity]:
    entities: list[Entity] = [ControllerSensor(coordinator, d) for d in CONTROLLER_SENSORS]
    entities += [ControllerRateSensor(coordinator, direction) for direction in DIRECTIONS]
    entities += [TopClientSensor(coordinator, by_usage=False), TopClientSensor(coordinator, by_usage=True)]
    if coordinator.apps is not None:
        entities.append(TopApplicationSensor(coordinator))
    return entities


def _discover(coordinator: MeCoordinator) -> Iterable[tuple[Hashable, Callable[[], Iterable[Entity]]]]:
    snapshot = coordinator.data
    yield "controller", lambda: _controller_sensors(coordinator)
    for mac, ap in snapshot.access_points.items():
        yield (
            ("ap", mac),
            lambda mac=mac: [
                *(ApSensor(coordinator, mac, d) for d in AP_SENSORS),
                *(ApRateSensor(coordinator, mac, direction) for direction in DIRECTIONS),
            ],
        )
        for slot in ap.radios:
            yield (
                ("radio", mac, slot),
                lambda mac=mac, slot=slot: [RadioSensor(coordinator, mac, slot, d) for d in RADIO_SENSORS],
            )
    for wlan_id in snapshot.wlans:
        yield (
            ("wlan", wlan_id),
            lambda wlan_id=wlan_id: [
                *(WlanSensor(coordinator, wlan_id, d) for d in WLAN_SENSORS),
                *(WlanRateSensor(coordinator, wlan_id, direction) for direction in DIRECTIONS),
            ],
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: MeConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    add_discovered(entry, async_add_entities, _discover)
