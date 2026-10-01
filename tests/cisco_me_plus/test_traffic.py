"""Traffic rates, top clients and top applications."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_me_plus.const import DOMAIN

from .conftest import CONFIG, SERIAL, SSH_CONFIG, CliAuthError, CliError, FakeCli, FakeTransport
from .test_entities import ap_mac, state_of

BUSY = "02:00:00:00:00:03"  # on studio, WLAN 1
QUIET = "02:00:00:00:00:02"  # on studio, WLAN 2


def approx(value: float) -> object:
    # the first poll happens a moment before the test clock is frozen, so elapsed times are ~0.1 % off
    return pytest.approx(value, rel=0.01)


def mbps(hass: HomeAssistant, unique_id: str) -> float:
    state = state_of(hass, "sensor", unique_id)
    assert state.attributes["unit_of_measurement"] == "Mbit/s"
    return float(state.state)


async def poll(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory, seconds: int
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_rates_are_zero_before_counters_move(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert mbps(hass, f"{SERIAL}_download_rate") == 0
    assert mbps(hass, f"{SERIAL}_upload_rate") == 0
    assert state_of(hass, "sensor", f"{SERIAL}_top_client").state == STATE_UNKNOWN


async def test_rates_follow_the_counters(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    studio, kitchen = ap_mac(loaded_entry, "studio"), ap_mac(loaded_entry, "kitchen")

    # polls where the controller has not refreshed its counters yet change nothing
    await poll(hass, loaded_entry, freezer, 30)
    await poll(hass, loaded_entry, freezer, 30)
    assert mbps(hass, f"{SERIAL}_download_rate") == 0

    # 90 s after the first poll the counters move: 9 MB down, 0.9 MB up for one client, less for another
    transport.add_client_bytes(BUSY, received=900_000, sent=9_000_000)
    transport.add_client_bytes(QUIET, received=9_000, sent=90_000)
    await poll(hass, loaded_entry, freezer, 30)

    assert mbps(hass, f"{SERIAL}_download_rate") == approx(0.808)  # (9 MB + 90 kB) * 8 / 90 s
    assert mbps(hass, f"{SERIAL}_upload_rate") == approx(0.0808)
    assert mbps(hass, f"{studio}_download_rate") == approx(0.808)
    assert mbps(hass, f"{kitchen}_download_rate") == 0
    assert mbps(hass, f"{SERIAL}_wlan1_download_rate") == approx(0.8)
    assert mbps(hass, f"{SERIAL}_wlan2_download_rate") == approx(0.008)

    top = state_of(hass, "sensor", f"{SERIAL}_top_client")
    assert top.state == BUSY
    assert [c["mac"] for c in top.attributes["clients"]] == [BUSY, QUIET]
    assert top.attributes["clients"][0] == {
        "download_bps": approx(800_000),
        "upload_bps": approx(80_000),
        "name": BUSY,
        "mac": BUSY,
        "ip": top.attributes["clients"][0]["ip"],
        "ap": "studio",
        "ssid": "ssid-1",
    }

    # the rate is held while the counters rest, then drops to zero once they are clearly stale
    await poll(hass, loaded_entry, freezer, 60)
    assert mbps(hass, f"{SERIAL}_wlan1_download_rate") == approx(0.8)
    await poll(hass, loaded_entry, freezer, 150)
    assert mbps(hass, f"{SERIAL}_download_rate") == 0
    assert state_of(hass, "sensor", f"{SERIAL}_top_client").state == STATE_UNKNOWN


async def test_counter_reset_is_not_a_negative_rate(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    received, sent = transport.client_bytes(BUSY)
    transport.add_client_bytes(BUSY, received=-received, sent=-sent)  # client re-associated
    await poll(hass, loaded_entry, freezer, 90)
    assert mbps(hass, f"{SERIAL}_download_rate") == 0
    assert mbps(hass, f"{SERIAL}_upload_rate") == 0


async def test_top_client_uses_the_tracker_name(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    registry = er.async_get(hass)
    registry.async_update_entity(
        registry.async_get_entity_id("device_tracker", DOMAIN, BUSY), name="Living room TV"
    )
    transport.add_client_bytes(BUSY, received=1_000, sent=1_000_000)
    await poll(hass, loaded_entry, freezer, 90)
    assert state_of(hass, "sensor", f"{SERIAL}_top_client").state == "Living room TV"


async def test_top_client_by_usage(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    clients = loaded_entry.runtime_data.data.clients.values()
    biggest = max(clients, key=lambda c: c.bytes_rx + c.bytes_tx)
    top = state_of(hass, "sensor", f"{SERIAL}_top_client_usage")
    assert top.state == biggest.mac
    ranking = top.attributes["clients"]
    assert len(ranking) == 10
    assert ranking[0]["bytes_down"] == biggest.bytes_tx
    assert ranking[0]["bytes_up"] == biggest.bytes_rx
    usage = [c["bytes_down"] + c["bytes_up"] for c in ranking]
    assert usage == sorted(usage, reverse=True)


async def test_tracker_reports_its_rate(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, BUSY)
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    transport.add_client_bytes(BUSY, received=90_000, sent=900_000)
    await poll(hass, loaded_entry, freezer, 90)
    attributes = hass.states.get(entity_id).attributes
    assert attributes["download_bps"] == approx(80_000)
    assert attributes["upload_bps"] == approx(8_000)


async def test_no_application_sensor_without_ssh(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_top_application") is None


async def test_top_application(hass: HomeAssistant, loaded_ssh_entry: MockConfigEntry, cli: FakeCli) -> None:
    assert cli.commands == ["show flexconnect avc statistics top-apps"]
    top = state_of(hass, "sensor", f"{SERIAL}_top_application")
    assert top.state == "ms-teams-video"
    apps = top.attributes["applications"]
    assert len(apps) == 10
    assert apps[0] == {
        "name": "ms-teams-video",
        "bytes_down": 5814055,
        "bytes_up": 6942818,
        "total_bytes_down": 395239322,
        "total_bytes_up": 258896897,
    }
    recent = [a["bytes_down"] + a["bytes_up"] for a in apps]
    assert recent == sorted(recent, reverse=True)


async def test_ssh_failure_only_affects_applications(
    hass: HomeAssistant, loaded_ssh_entry: MockConfigEntry, cli: FakeCli
) -> None:
    cli.error = CliError("connection refused")
    await loaded_ssh_entry.runtime_data.apps.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "sensor", f"{SERIAL}_top_application").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", f"{SERIAL}_clients").state == "31"

    cli.error = None
    await loaded_ssh_entry.runtime_data.apps.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "sensor", f"{SERIAL}_top_application").state == "ms-teams-video"


async def test_setup_survives_ssh_being_down(
    hass: HomeAssistant, transport: FakeTransport, cli: FakeCli
) -> None:
    cli.error = CliError("connection refused")
    entry = MockConfigEntry(domain=DOMAIN, title="AP1", unique_id=SERIAL, data=SSH_CONFIG)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert state_of(hass, "sensor", f"{SERIAL}_top_application").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", f"{SERIAL}_clients").state == "31"


async def test_flow_with_ssh_login(hass: HomeAssistant, transport: FakeTransport, cli: FakeCli) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=SSH_CONFIG
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == SSH_CONFIG
    assert cli.commands[0] == "show sysinfo"


async def test_flow_reports_ssh_problems(hass: HomeAssistant, transport: FakeTransport, cli: FakeCli) -> None:
    cli.error = CliAuthError("rejected")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=SSH_CONFIG
    )
    assert result["errors"] == {"base": "invalid_auth"}

    cli.error = CliError("connection refused")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SSH_CONFIG)
    assert result["errors"] == {"base": "cannot_connect_ssh"}

    cli.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG | {CONF_USERNAME: "admin"}
    )
    assert result["errors"] == {CONF_PASSWORD: "password_required"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], SSH_CONFIG)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reconfigure_adds_ssh_login(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, cli: FakeCli
) -> None:
    assert loaded_entry.runtime_data.apps is None
    result = await loaded_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], SSH_CONFIG)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data == SSH_CONFIG
    assert state_of(hass, "sensor", f"{SERIAL}_top_application").state == "ms-teams-video"
