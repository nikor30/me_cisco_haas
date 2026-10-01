"""Read-only check against a real controller. Skipped unless ME_HOST and ME_SNMP_COMMUNITY are set.

ME_SSH_USER / ME_SSH_PASS add the application statistics; ME_LIVE_RATE_SECONDS=120 also waits for the
controller to refresh its byte counters so real traffic rates show up.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_socket import socket_allow_hosts

from custom_components.cisco_me_plus.const import CONF_COMMUNITY, DOMAIN

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ME_HOST") and os.environ.get("ME_SNMP_COMMUNITY")),
    reason="no live controller configured",
)


async def test_live_config_flow_and_setup(hass: HomeAssistant, socket_enabled: None) -> None:
    # the HA test setup only lets TCP reach localhost; SSH needs the controller too
    socket_allow_hosts([os.environ["ME_HOST"], "127.0.0.1"])
    config = {
        CONF_HOST: os.environ["ME_HOST"],
        CONF_COMMUNITY: os.environ["ME_SNMP_COMMUNITY"],
        CONF_PORT: 161,
    }
    if os.environ.get("ME_SSH_USER"):
        config |= {CONF_USERNAME: os.environ["ME_SSH_USER"], CONF_PASSWORD: os.environ["ME_SSH_PASS"]}
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

    registry = er.async_get(hass)
    serial = snapshot.controller.serial

    def state(key: str) -> str:
        return hass.states.get(registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_{key}")).state

    assert state("top_client_usage") in snapshot.clients
    if CONF_USERNAME in config:
        apps = entry.runtime_data.apps.data
        assert apps and state("top_application") == apps[0].name
        print(f"live: {len(apps)} applications")

    wait = int(os.environ.get("ME_LIVE_RATE_SECONDS", "0"))
    if wait:
        for _ in range(wait // 30):
            await asyncio.sleep(30)
            await entry.runtime_data.async_refresh()
            await hass.async_block_till_done()
        moving = entry.runtime_data.clients_by_rate()
        rates = f"{state('download_rate')} down / {state('upload_rate')} up Mbit/s"
        print(f"live: {len(moving)} clients moving data, {rates}")
        assert moving
        assert float(state("download_rate")) > 0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
