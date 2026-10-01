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
    UnitOfFrequency,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import MeConfigEntry, MeCoordinator
from .entity import ApEntity, ControllerEntity, RadioEntity, WlanEntity, add_discovered
from .pyciscome import AccessPoint, Radio, Snapshot, Wlan
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


def _discover(coordinator: MeCoordinator) -> Iterable[tuple[Hashable, Callable[[], Iterable[Entity]]]]:
    snapshot = coordinator.data
    yield "controller", lambda: [ControllerSensor(coordinator, d) for d in CONTROLLER_SENSORS]
    for mac, ap in snapshot.access_points.items():
        yield ("ap", mac), lambda mac=mac: [ApSensor(coordinator, mac, d) for d in AP_SENSORS]
        for slot in ap.radios:
            yield (
                ("radio", mac, slot),
                lambda mac=mac, slot=slot: [RadioSensor(coordinator, mac, slot, d) for d in RADIO_SENSORS],
            )
    for wlan_id in snapshot.wlans:
        yield (
            ("wlan", wlan_id),
            lambda wlan_id=wlan_id: [WlanSensor(coordinator, wlan_id, d) for d in WLAN_SENSORS],
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: MeConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    add_discovered(entry, async_add_entities, _discover)
