from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_me_plus.const import CONF_CONSIDER_HOME, DOMAIN

from .conftest import CONFIG, SERIAL, FakeTransport


async def test_user_flow_creates_entry(hass: HomeAssistant, transport: FakeTransport) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONFIG)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AP1"
    assert result["data"] == CONFIG
    assert result["result"].unique_id == SERIAL


async def test_user_flow_cannot_connect_then_recovers(hass: HomeAssistant, transport: FakeTransport) -> None:
    transport.fail = True
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}, data=CONFIG)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert transport.closed

    transport.fail = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONFIG)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_rejects_other_snmp_devices(hass: HomeAssistant, transport: FakeTransport) -> None:
    transport.clear()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}, data=CONFIG)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_mobility_express"}


async def test_user_flow_aborts_when_already_configured(
    hass: HomeAssistant, config_entry: MockConfigEntry, transport: FakeTransport
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}, data=CONFIG)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_reloads_with_new_values(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 15, CONF_CONSIDER_HOME: 60}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    coordinator = loaded_entry.runtime_data
    assert coordinator.update_interval.total_seconds() == 15
    assert coordinator.consider_home.total_seconds() == 60
