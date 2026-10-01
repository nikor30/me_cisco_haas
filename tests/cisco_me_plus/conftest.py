"""Fixtures: the integration talks to a replayed walk of the lab ME instead of the network."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_me_plus.const import CONF_COMMUNITY, DOMAIN
from custom_components.cisco_me_plus.pyciscome import CliAuthError, CliError, SnmpError, WalkFileTransport

WALK = Path(__file__).parent.parent / "fixtures" / "snmp" / "me_8_10.walk"
CLIENT_TABLES = ("1.3.6.1.4.1.14179.2.1.4.1.", "1.3.6.1.4.1.14179.2.1.6.1.", "1.3.6.1.4.1.9.9.599.1.3.1.1.")

CLI_FIXTURES = Path(__file__).parent.parent / "fixtures" / "cli"
CLIENT_BYTES_RX = "1.3.6.1.4.1.14179.2.1.6.1.2"
CLIENT_BYTES_TX = "1.3.6.1.4.1.14179.2.1.6.1.3"

SERIAL = "FCW0000A001"
CONFIG = {CONF_HOST: "192.0.2.1", CONF_COMMUNITY: "public", CONF_PORT: 161}
SSH_CONFIG = CONFIG | {CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}


def mac_index(mac: str) -> str:
    return ".".join(str(b) for b in bytes.fromhex(mac.replace(":", "")))


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

    def client_bytes(self, mac: str) -> tuple[int, int]:
        index = mac_index(mac)
        return self._values[f"{CLIENT_BYTES_RX}.{index}"], self._values[f"{CLIENT_BYTES_TX}.{index}"]

    def add_client_bytes(self, mac: str, received: int, sent: int) -> None:
        index = mac_index(mac)
        self._values[f"{CLIENT_BYTES_RX}.{index}"] += received
        self._values[f"{CLIENT_BYTES_TX}.{index}"] += sent

    def clear(self) -> None:
        self._values.clear()

    def close(self) -> None:
        self.closed = True


class FakeCli:
    """Answers `show` commands from the captured CLI fixtures."""

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.commands: list[str] = []

    async def run(self, commands: list[str]) -> dict[str, str]:
        if self.error:
            raise self.error
        self.commands += commands
        return {
            command: (CLI_FIXTURES / (command.replace(" ", "_").replace("-", "_") + ".txt")).read_text()
            for command in commands
        }


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


@pytest.fixture
def cli() -> Iterator[FakeCli]:
    fake = FakeCli()
    with (
        patch("custom_components.cisco_me_plus.coordinator.create_cli", return_value=fake),
        patch("custom_components.cisco_me_plus.config_flow.create_cli", return_value=fake),
    ):
        yield fake


@pytest.fixture
async def loaded_ssh_entry(hass: HomeAssistant, transport: FakeTransport, cli: FakeCli) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="AP1", unique_id=SERIAL, data=SSH_CONFIG)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


__all__ = ["CliAuthError", "CliError"]
