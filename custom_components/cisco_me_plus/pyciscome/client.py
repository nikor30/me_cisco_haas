"""High-level client: decides what to walk and hands the result to the parsers."""

from __future__ import annotations

from . import oids
from .cli import CliError, CliTransport
from .models import AccessPoint, Application, Client, Controller, Snapshot, Wlan
from .parsers import airespace
from .parsers import cli as cli_parsers
from .snmp import SnmpTransport, SnmpValue

# Only the columns the parsers read are walked; a whole-table walk would fetch ~10x more.
WLAN_COLUMNS = {oids.WLAN_ENTRY: (2, 6, 38, 42)}
AP_COLUMNS = {
    oids.AP_ENTRY: (3, 4, 6, 8, 16, 17, 19, 33),
    oids.LWAPP_AP_ENTRY: (6, 54),
    oids.RADIO_ENTRY: (4, 6, 12, 34),
    oids.RADIO_LOAD_ENTRY: (1, 2, 3, 4),
    oids.RADIO_NOISE_ENTRY: (21,),
    oids.LWAPP_RADIO_ENTRY: (23,),
}
CLIENT_COLUMNS = {
    oids.CLIENT_ENTRY: (1, 2, 3, 4, 5, 6, 7, 9),
    oids.CLIENT_STATS_ENTRY: (1, 2, 3, 26),
    oids.LWAPP_CLIENT_ENTRY: (6, 15, 17, 44),
}
CONTROLLER_ROOTS = (oids.SYSTEM, oids.INVENTORY, oids.RESOURCES)


class MobilityExpress:
    """Read-only view of one Mobility Express controller."""

    def __init__(self, transport: SnmpTransport, cli: CliTransport | None = None) -> None:
        self._transport = transport
        self._cli = cli

    async def _columns(self, spec: dict[str, tuple[int, ...]]) -> dict[str, dict[str, SnmpValue]]:
        columns: dict[str, dict[str, SnmpValue]] = {}
        # sequential on purpose: the controller runs on an AP CPU
        for entry, numbers in spec.items():
            for number in numbers:
                root = f"{entry}.{number}"
                rows = await self._transport.walk(root)
                columns[root] = {oid[len(root) + 1 :]: value for oid, value in rows.items()}
        return columns

    async def fetch_controller(self) -> Controller:
        scalars: dict[str, SnmpValue] = {}
        for root in CONTROLLER_ROOTS:
            scalars.update(await self._transport.walk(root))
        return airespace.parse_controller(scalars)

    async def fetch_wlans(self) -> dict[int, Wlan]:
        return airespace.parse_wlans(await self._columns(WLAN_COLUMNS))

    async def fetch_access_points(self) -> dict[str, AccessPoint]:
        return airespace.parse_access_points(await self._columns(AP_COLUMNS))

    async def fetch_clients(self, ap_names: dict[str, str | None] | None = None) -> dict[str, Client]:
        """Client table only: the cheap call for fast presence polling."""
        return airespace.parse_clients(await self._columns(CLIENT_COLUMNS), ap_names)

    async def fetch_snapshot(self) -> Snapshot:
        controller = await self.fetch_controller()
        access_points = await self.fetch_access_points()
        wlans = await self.fetch_wlans()
        clients = await self.fetch_clients({mac: ap.name for mac, ap in access_points.items()})
        return Snapshot(controller=controller, access_points=access_points, wlans=wlans, clients=clients)

    async def fetch_applications(self) -> list[Application]:
        """Top applications seen by AVC, busiest first. Needs the CLI: the data is not in SNMP."""
        if self._cli is None:
            raise CliError("no CLI transport configured")
        output = await self._cli.run([cli_parsers.TOP_APPS])
        return cli_parsers.parse_top_apps(output[cli_parsers.TOP_APPS])
