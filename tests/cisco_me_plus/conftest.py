"""Fixtures: the integration talks to a replayed walk of the lab ME instead of the network."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_me_plus.const import CONF_COMMUNITY, DOMAIN
from custom_components.cisco_me_plus.pyciscome import SnmpError, WalkFileTransport

WALK = Path(__file__).parent.parent / "fixtures" / "snmp" / "me_8_10.walk"
CLIENT_TABLES = ("1.3.6.1.4.1.14179.2.1.4.1.", "1.3.6.1.4.1.14179.2.1.6.1.", "1.3.6.1.4.1.9.9.599.1.3.1.1.")

SERIAL = "FCW0000A001"
CONFIG = {CONF_HOST: "192.0.2.1", CONF_COMMUNITY: "public", CONF_PORT: 161}


class FakeTransport(WalkFileTransport):
    """Replays the fixture; tests can make it fail or take clients away."""

    def __init__(self) -> None:
        super().__init__(WALK)
        self.fail = False
        self.closed = False

    async def walk(self, root: str):
        if self.fail:
            raise SnmpError("No SNMP response received before timeout")
        return await super().walk(root)

    def remove_client(self, mac: str) -> None:
        index = "." + ".".join(str(b) for b in bytes.fromhex(mac.replace(":", "")))
        for oid in [o for o in self._values if o.startswith(CLIENT_TABLES) and o.endswith(index)]:
            del self._values[oid]

    def clear(self) -> None:
        self._values.clear()

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return


@pytest.fixture
def transport() -> Iterator[FakeTransport]:
    fake = FakeTransport()
    module = "custom_components.cisco_me_plus.coordinator"
    with (
        patch(f"{module}.PysnmpTransport", return_value=fake),
        patch(f"{module}.SnmpEngine", return_value=MagicMock()),
    ):
        yield fake


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="AP1", unique_id=SERIAL, data=CONFIG)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, transport: FakeTransport
) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
