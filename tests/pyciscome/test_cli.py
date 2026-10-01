from __future__ import annotations

from pathlib import Path

import pytest

from pyciscome import CliError, MobilityExpress, SshCli, WalkFileTransport
from pyciscome.parsers.cli import TOP_APPS, parse_top_apps

FIXTURES = Path(__file__).parent.parent / "fixtures"
TOP_APPS_OUTPUT = (FIXTURES / "cli" / "show_flexconnect_avc_statistics_top_apps.txt").read_text()


def test_parse_top_apps() -> None:
    apps = parse_top_apps(TOP_APPS_OUTPUT)
    assert len(apps) == 17
    assert len({app.name for app in apps}) == 17
    first = apps[0]
    assert first.name == "ms-teams-video"
    assert (first.packets_up, first.bytes_up) == (11455, 6942818)
    assert (first.packets_down, first.bytes_down) == (12531, 5814055)
    assert (first.total_packets_up, first.total_bytes_up) == (461006, 258896897)
    assert (first.total_packets_down, first.total_bytes_down) == (860837, 395239322)
    assert first.bytes == 6942818 + 5814055
    assert [app.bytes for app in apps] == sorted((app.bytes for app in apps), reverse=True)
    # an upstream-only application still gets its downstream row
    igmp = next(app for app in apps if app.name == "igmp")
    assert (igmp.bytes_up, igmp.bytes_down, igmp.total_bytes_down) == (744, 0, 0)


@pytest.mark.parametrize(
    "text", ["", "AVC Statstics Not found for the client.\n", "Incorrect usage.  Use the '?' key.\n"]
)
def test_parse_top_apps_without_data(text: str) -> None:
    assert parse_top_apps(text) == []


async def test_fetch_applications_runs_one_show_command() -> None:
    class Cli:
        def __init__(self) -> None:
            self.commands: list[str] = []

        async def run(self, commands: list[str]) -> dict[str, str]:
            self.commands += commands
            return {TOP_APPS: TOP_APPS_OUTPUT}

    cli = Cli()
    me = MobilityExpress(WalkFileTransport(FIXTURES / "snmp" / "me_8_10.walk"), cli)
    assert (await me.fetch_applications())[0].name == "ms-teams-video"
    assert cli.commands == [TOP_APPS]


async def test_fetch_applications_needs_a_cli() -> None:
    with pytest.raises(CliError):
        await MobilityExpress(WalkFileTransport(FIXTURES / "snmp" / "me_8_10.walk")).fetch_applications()


@pytest.mark.parametrize(
    "command",
    [
        "config wlan disable 1",
        "reset system",
        "save config",
        "show sysinfo\nconfig wlan disable 1",
        " show x",
    ],
)
async def test_ssh_cli_refuses_anything_but_show(command: str) -> None:
    # refused before any connection is attempted (the host does not exist)
    with pytest.raises(CliError, match="refusing"):
        await SshCli("192.0.2.1", "admin", "secret").run(["show sysinfo", command])
