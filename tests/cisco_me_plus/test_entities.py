from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_me_plus.const import DOMAIN

from .conftest import SERIAL, FakeTransport

CLIENT = "02:00:00:00:00:02"


def state_of(hass: HomeAssistant, platform: str, unique_id: str) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, f"no {platform} entity with unique id {unique_id}"
    state = hass.states.get(entity_id)
    assert state, f"{entity_id} has no state"
    return state


def ap_mac(loaded_entry: MockConfigEntry, name: str) -> str:
    return next(mac for mac, ap in loaded_entry.runtime_data.data.access_points.items() if ap.name == name)


async def test_devices(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), loaded_entry.entry_id)
    assert sorted(d.name for d in devices) == [
        "AP1",
        "WLAN ssid-1",
        "WLAN ssid-2",
        "bedroom",
        "kitchen",
        "studio",
    ]
    controller = next(d for d in devices if d.name == "AP1")
    assert controller.serial_number == SERIAL
    assert controller.sw_version == "8.10.196.0"
    assert all(d.via_device_id == controller.id for d in devices if d is not controller)


async def test_controller_entities(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert state_of(hass, "sensor", f"{SERIAL}_clients").state == "31"
    assert state_of(hass, "sensor", f"{SERIAL}_clients_24").state == "19"
    assert state_of(hass, "sensor", f"{SERIAL}_clients_5").state == "12"
    assert state_of(hass, "sensor", f"{SERIAL}_access_points").state == "3"
    assert 0 <= int(state_of(hass, "sensor", f"{SERIAL}_cpu").state) <= 100
    assert 70 < float(state_of(hass, "sensor", f"{SERIAL}_memory").state) < 90
    assert state_of(hass, "binary_sensor", f"{SERIAL}_reachable").state == STATE_ON


async def test_ap_radio_and_wlan_entities(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    studio, kitchen = ap_mac(loaded_entry, "studio"), ap_mac(loaded_entry, "kitchen")
    assert state_of(hass, "sensor", f"{studio}_clients").state == "19"
    assert state_of(hass, "binary_sensor", f"{studio}_online").state == STATE_ON
    assert state_of(hass, "sensor", f"{studio}_ip").state.startswith("192.0.2.")

    channel = state_of(hass, "sensor", f"{studio}_radio1_channel")
    assert channel.state == "100"
    assert channel.name == "studio 5 GHz channel"
    assert state_of(hass, "sensor", f"{studio}_radio1_channel_width").state == "80"
    assert state_of(hass, "sensor", f"{studio}_radio0_clients").state == "14"
    assert state_of(hass, "binary_sensor", f"{studio}_radio0_up").state == STATE_ON

    kitchen_radio = state_of(hass, "binary_sensor", f"{kitchen}_radio0_up")
    assert kitchen_radio.state == STATE_OFF
    assert kitchen_radio.attributes["admin_enabled"] is False

    assert state_of(hass, "binary_sensor", f"{SERIAL}_wlan1_enabled").state == STATE_ON
    assert state_of(hass, "sensor", f"{SERIAL}_wlan1_clients").state == "30"
    assert state_of(hass, "sensor", f"{SERIAL}_wlan2_clients").state == "1"


async def test_uptime_sensor_ignores_poll_jitter(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    before = state_of(hass, "sensor", f"{SERIAL}_uptime").state
    # the replayed uptime does not advance, so a naive "now - uptime" would move by 30 s here
    freezer.tick(timedelta(seconds=30))
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "sensor", f"{SERIAL}_uptime").state == before


async def test_controller_unreachable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.fail = True
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor", f"{SERIAL}_reachable").state == STATE_OFF
    assert state_of(hass, "sensor", f"{SERIAL}_clients").state == STATE_UNAVAILABLE

    transport.fail = False
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor", f"{SERIAL}_reachable").state == STATE_ON
    assert state_of(hass, "sensor", f"{SERIAL}_clients").state == "31"


async def test_ap_leaving_is_offline_not_unknown(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, transport: FakeTransport
) -> None:
    kitchen = ap_mac(loaded_entry, "kitchen")
    index = "." + ".".join(str(b) for b in bytes.fromhex(kitchen.replace(":", "")))
    for oid in [o for o in transport._values if f"{index}." in o + "."]:
        del transport._values[oid]
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor", f"{kitchen}_online").state == STATE_OFF
    assert state_of(hass, "sensor", f"{kitchen}_clients").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", f"{SERIAL}_access_points").state == "2"


async def test_trackers_are_created_disabled(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    trackers = [
        e
        for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if e.domain == "device_tracker"
    ]
    assert len(trackers) == 31
    assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in trackers)


async def test_tracker_consider_home(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, CLIENT)
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = loaded_entry.runtime_data

    state = hass.states.get(entity_id)
    assert state.state == STATE_HOME
    assert state.attributes["ap_name"] == "studio"
    assert state.attributes["ssid"] == "ssid-2"
    assert state.attributes["band"] == "2.4"
    assert state.attributes["protocol"] == "802.11g"
    assert state.attributes["mac"] == CLIENT
    assert state.attributes["ip"].startswith("192.0.2.")
    assert state.attributes["rssi"] < 0

    # the client drops off the controller: still home inside the 180 s window
    transport.remove_client(CLIENT)
    freezer.tick(timedelta(seconds=60))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == STATE_HOME
    assert state.attributes["ap_name"] == "studio"  # last known details are kept

    freezer.tick(timedelta(seconds=150))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_NOT_HOME


async def test_away_client_keeps_its_entity_across_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, transport: FakeTransport
) -> None:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, CLIENT)
    registry.async_update_entity(entity_id, disabled_by=None)
    transport.remove_client(CLIENT)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_NOT_HOME


async def test_unload(hass: HomeAssistant, loaded_entry: MockConfigEntry, transport: FakeTransport) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert transport.closed


async def test_setup_retries_when_controller_is_down(
    hass: HomeAssistant, config_entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.fail = True
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert transport.closed
