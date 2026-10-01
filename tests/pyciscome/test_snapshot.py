"""Parse the anonymised walk of the lab ME (3 APs, 2 WLANs, 31 clients) end to end."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyciscome import MobilityExpress, Snapshot, WalkFileTransport
from pyciscome.parsers import airespace
from pyciscome.walkfile import parse_walk

WALK = Path(__file__).parent.parent / "fixtures" / "snmp" / "me_8_10.walk"


@pytest.fixture
async def snapshot() -> Snapshot:
    return await MobilityExpress(WalkFileTransport(WALK)).fetch_snapshot()


def test_parse_walk_types() -> None:
    values = parse_walk(
        "1.3.6.1.2.1.1.5.0 = Hex-STRING: 41 50 31\n"
        "1.3.6.1.2.1.1.3.0 = TimeTicks: 7810900\n"
        "1.3.6.1.2.1.1.2.0 = ObjectIdentifier: 1.3.6.1.4.1.9.1.2373\n"
        "1.3.6.1.2.1.1.4.0 = Hex-STRING: \n"
    )
    assert values["1.3.6.1.2.1.1.5.0"] == b"AP1"
    assert values["1.3.6.1.2.1.1.3.0"] == 7810900
    assert values["1.3.6.1.2.1.1.2.0"] == "1.3.6.1.4.1.9.1.2373"
    assert values["1.3.6.1.2.1.1.4.0"] == b""
    assert list(values) == sorted(values, key=lambda oid: [int(p) for p in oid.split(".")])


async def test_walk_is_limited_to_subtree() -> None:
    rows = await WalkFileTransport(WALK).walk("1.3.6.1.4.1.14179.2.1.1.1.2")
    assert set(rows) == {"1.3.6.1.4.1.14179.2.1.1.1.2.1", "1.3.6.1.4.1.14179.2.1.1.1.2.2"}


def test_controller(snapshot: Snapshot) -> None:
    controller = snapshot.controller
    assert controller.name == "AP1"
    assert controller.model == "AIR-AP3802I-E-K9"
    assert controller.serial == "FCW0000A001"
    assert controller.mac == "02:00:00:00:00:01"
    assert controller.version == "8.10.196.0"
    assert controller.manufacturer == "Cisco Systems Inc."
    assert controller.uptime_seconds and controller.uptime_seconds > 70_000
    assert 0 <= controller.cpu_percent <= 100
    assert controller.memory_total_kb == 1028200
    assert 70 < controller.memory_used_percent < 90


def test_wlans(snapshot: Snapshot) -> None:
    assert sorted(snapshot.wlans) == [1, 2]
    main, guest = snapshot.wlans[1], snapshot.wlans[2]
    assert (main.ssid, guest.ssid) == ("ssid-1", "ssid-2")
    assert main.enabled and guest.enabled
    assert main.interface == "management"
    assert main.client_count + guest.client_count == 31


def test_access_points(snapshot: Snapshot) -> None:
    by_name = {ap.name: ap for ap in snapshot.access_points.values()}
    assert sorted(by_name) == ["bedroom", "kitchen", "studio"]
    for mac, ap in snapshot.access_points.items():
        assert mac == ap.mac
        assert ap.online
        assert ap.model == "AIR-AP3802I-E-K9"
        assert ap.serial.startswith("FCW0000A")
        assert ap.ip.startswith("192.0.2.")
        assert ap.ethernet_mac and ap.ethernet_mac != ap.mac
        assert ap.uptime_seconds > 70_000
        assert sorted(ap.radios) == [0, 1]
    # the master AP shares its serial with the controller
    assert by_name["studio"].serial == snapshot.controller.serial
    assert by_name["studio"].client_count == 19


def test_radios(snapshot: Snapshot) -> None:
    by_name = {ap.name: ap for ap in snapshot.access_points.values()}
    studio_24, studio_5 = by_name["studio"].radios[0], by_name["studio"].radios[1]
    assert (studio_24.band, studio_24.channel, studio_24.channel_width_mhz) == ("2.4", 1, 20)
    assert (studio_5.band, studio_5.channel, studio_5.channel_width_mhz) == ("5", 100, 80)
    assert studio_24.admin_enabled and studio_24.oper_up
    assert studio_24.tx_power_level == 1
    assert studio_24.client_count == 14
    assert 0 <= studio_24.channel_utilization <= 100
    assert -110 < studio_24.noise_dbm < -60
    # kitchen's 2.4 GHz radio is administratively disabled
    kitchen_24 = by_name["kitchen"].radios[0]
    assert kitchen_24.admin_enabled is False
    assert kitchen_24.oper_up is False
    assert kitchen_24.client_count == 0


def test_clients(snapshot: Snapshot) -> None:
    clients = snapshot.clients
    assert len(clients) == 31
    assert all(client.associated for client in clients.values())
    assert all(client.ap_mac in snapshot.access_points for client in clients.values())
    assert {client.ap_name for client in clients.values()} == {"bedroom", "kitchen", "studio"}
    assert {client.ssid for client in clients.values()} == {"ssid-1", "ssid-2"}
    assert all(client.ip is None or client.ip.startswith("192.0.2.") for client in clients.values())
    assert all(-100 < client.rssi < 0 for client in clients.values())
    assert all(client.snr > 0 for client in clients.values())
    # counts match `show client summary`: 11 ac + 1 n on 5 GHz, 13 n + 6 g on 2.4 GHz
    assert snapshot.clients_on_band("5") == 12
    assert snapshot.clients_on_band("2.4") == 19
    protocols = [client.protocol for client in clients.values()]
    assert protocols.count("802.11ac") == 11
    assert protocols.count("802.11g") == 6
    assert protocols.count("802.11n") == 14


def test_client_details(snapshot: Snapshot) -> None:
    client = snapshot.clients["02:00:00:00:00:02"]
    assert client.ap_name == "studio"
    assert (client.slot, client.wlan_id, client.ssid) == (0, 2, "ssid-2")
    assert (client.protocol, client.band) == ("802.11g", "2.4")
    assert client.data_rate_mbps == 54.0
    assert client.uptime_seconds > 0
    assert client.bytes_rx is not None and client.bytes_tx is not None


def test_missing_columns_leave_fields_empty() -> None:
    assert airespace.parse_wlans({}) == {}
    assert airespace.parse_access_points({}) == {}
    clients = airespace.parse_clients({"1.3.6.1.4.1.14179.2.1.4.1.1": {"2.0.0.0.0.9": b"\x02\0\0\0\0\x09"}})
    client = clients["02:00:00:00:00:09"]
    assert client.status is None and client.rssi is None and not client.associated
    assert airespace.parse_controller({}).memory_used_percent is None
