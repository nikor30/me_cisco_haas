"""Read-only check against a real controller. Skipped unless ME_HOST and ME_SNMP_COMMUNITY are set."""

from __future__ import annotations

import os

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.cisco_me_plus.const import CONF_COMMUNITY, DOMAIN

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ME_HOST") and os.environ.get("ME_SNMP_COMMUNITY")),
    reason="no live controller configured",
)


async def test_live_config_flow_and_setup(hass: HomeAssistant, socket_enabled: None) -> None:
    config = {
        CONF_HOST: os.environ["ME_HOST"],
        CONF_COMMUNITY: os.environ["ME_SNMP_COMMUNITY"],
        CONF_PORT: 161,
    }
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}, data=config)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED

    snapshot = entry.runtime_data.data
    assert snapshot.access_points
    assert snapshot.wlans
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    print(
        f"\nlive: {len(snapshot.access_points)} APs, {len(snapshot.wlans)} WLANs, "
        f"{len(snapshot.clients)} clients, {len(entities)} entities"
    )
    clients = hass.states.get(
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{snapshot.controller.serial}_clients")
    )
    assert int(clients.state) == sum(1 for c in snapshot.clients.values() if c.associated)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
