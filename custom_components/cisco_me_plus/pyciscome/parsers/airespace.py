"""Build models from AIRESPACE-WIRELESS-MIB and CISCO-LWAPP-* SNMP columns.

Every function takes `columns`: {column OID: {row index: value}}, where the row index is the dotted
suffix after the column OID. Missing columns or rows simply leave the model field as None.
"""

from __future__ import annotations

from collections.abc import Mapping

from .. import oids
from ..models import BAND_5, BAND_24, AccessPoint, Client, Controller, Radio, Wlan
from ..snmp import SnmpValue

Columns = Mapping[str, Mapping[str, SnmpValue]]


def _int(value: SnmpValue | None) -> int | None:
    return value if isinstance(value, int) else None


def _text(value: SnmpValue | None) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value.strip("\x00 ") or None
    return None


def _mac(value: SnmpValue | None) -> str | None:
    if isinstance(value, bytes) and len(value) == 6 and any(value):
        return value.hex(":")
    return None


def _ip(value: SnmpValue | None) -> str | None:
    if isinstance(value, bytes) and len(value) == 4 and any(value):
        return ".".join(str(b) for b in value)
    return None


def _float(value: SnmpValue | None) -> float | None:
    try:
        return float(_text(value) or "")
    except ValueError:
        return None


def index_mac(index: str) -> str:
    """First six sub-identifiers of a row index as a MAC address."""
    return ":".join(f"{int(part):02x}" for part in index.split(".")[:6])


def _band(channel: int | None) -> str | None:
    if not channel:
        return None
    return BAND_24 if channel <= 14 else BAND_5


def parse_controller(scalars: Mapping[str, SnmpValue]) -> Controller:
    uptime = _int(scalars.get(oids.SYS_UPTIME))
    return Controller(
        name=_text(scalars.get(oids.SYS_NAME)),
        model=_text(scalars.get(oids.INV_MODEL)),
        serial=_text(scalars.get(oids.INV_SERIAL)),
        mac=_mac(scalars.get(oids.INV_MAC)),
        manufacturer=_text(scalars.get(oids.INV_MANUFACTURER)),
        version=_text(scalars.get(oids.INV_VERSION)),
        uptime_seconds=uptime // 100 if uptime is not None else None,
        cpu_percent=_int(scalars.get(oids.RES_CPU)),
        memory_total_kb=_int(scalars.get(oids.RES_MEM_TOTAL)),
        memory_free_kb=_int(scalars.get(oids.RES_MEM_FREE)),
    )


def parse_wlans(columns: Columns) -> dict[int, Wlan]:
    def col(number: int) -> Mapping[str, SnmpValue]:
        return columns.get(f"{oids.WLAN_ENTRY}.{number}", {})

    wlans: dict[int, Wlan] = {}
    for index, ssid in col(2).items():
        admin = _int(col(6).get(index))
        wlans[int(index)] = Wlan(
            wlan_id=int(index),
            ssid=_text(ssid),
            enabled=admin == oids.WLAN_ADMIN_ENABLED if admin is not None else None,
            client_count=_int(col(38).get(index)),
            interface=_text(col(42).get(index)),
        )
    return wlans


def parse_access_points(columns: Columns) -> dict[str, AccessPoint]:
    def col(entry: str, number: int) -> Mapping[str, SnmpValue]:
        return columns.get(f"{entry}.{number}", {})

    aps: dict[str, AccessPoint] = {}
    for index, name in col(oids.AP_ENTRY, 3).items():
        oper = _int(col(oids.AP_ENTRY, 6).get(index))
        uptime = _int(col(oids.LWAPP_AP_ENTRY, 6).get(index))
        mac = index_mac(index)
        aps[mac] = AccessPoint(
            mac=mac,
            name=_text(name),
            location=_text(col(oids.AP_ENTRY, 4).get(index)),
            model=_text(col(oids.AP_ENTRY, 16).get(index)),
            serial=_text(col(oids.AP_ENTRY, 17).get(index)),
            ip=_ip(col(oids.AP_ENTRY, 19).get(index)),
            ethernet_mac=_mac(col(oids.AP_ENTRY, 33).get(index)),
            version=_text(col(oids.AP_ENTRY, 8).get(index)),
            online=oper == oids.AP_OPER_ASSOCIATED if oper is not None else None,
            uptime_seconds=uptime // 100 if uptime is not None else None,
            client_count=_int(col(oids.LWAPP_AP_ENTRY, 54).get(index)),
        )

    # noise rows are indexed MAC.slot.channel; keep them addressable by that full index
    noise = col(oids.RADIO_NOISE_ENTRY, 21)
    for index, channel_value in col(oids.RADIO_ENTRY, 4).items():
        ap = aps.get(index_mac(index))
        if ap is None:
            continue
        slot = int(index.rsplit(".", 1)[1])
        channel = _int(channel_value)
        admin = _int(col(oids.RADIO_ENTRY, 34).get(index))
        oper = _int(col(oids.RADIO_ENTRY, 12).get(index))
        width = _int(col(oids.LWAPP_RADIO_ENTRY, 23).get(index))
        ap.radios[slot] = Radio(
            ap_mac=ap.mac,
            slot=slot,
            band=_band(channel),
            channel=channel,
            channel_width_mhz=oids.CHANNEL_WIDTH_MHZ.get(width) if width is not None else None,
            tx_power_level=_int(col(oids.RADIO_ENTRY, 6).get(index)),
            admin_enabled=admin == oids.RADIO_ADMIN_ENABLED if admin is not None else None,
            oper_up=oper == oids.RADIO_OPER_UP if oper is not None else None,
            rx_utilization=_int(col(oids.RADIO_LOAD_ENTRY, 1).get(index)),
            tx_utilization=_int(col(oids.RADIO_LOAD_ENTRY, 2).get(index)),
            channel_utilization=_int(col(oids.RADIO_LOAD_ENTRY, 3).get(index)),
            client_count=_int(col(oids.RADIO_LOAD_ENTRY, 4).get(index)),
            noise_dbm=_int(noise.get(f"{index}.{channel}")),
        )
    return aps


def parse_clients(columns: Columns, ap_names: Mapping[str, str | None] | None = None) -> dict[str, Client]:
    def col(entry: str, number: int) -> Mapping[str, SnmpValue]:
        return columns.get(f"{entry}.{number}", {})

    ap_names = ap_names or {}
    clients: dict[str, Client] = {}
    for index in col(oids.CLIENT_ENTRY, 1):
        mac = index_mac(index)
        ap_mac = _mac(col(oids.CLIENT_ENTRY, 4).get(index))
        status = _int(col(oids.CLIENT_ENTRY, 9).get(index))
        protocol, band = oids.CLIENT_PROTOCOL.get(
            _int(col(oids.LWAPP_CLIENT_ENTRY, 6).get(index)) or 0, (None, None)
        )
        clients[mac] = Client(
            mac=mac,
            ip=_ip(col(oids.CLIENT_ENTRY, 2).get(index)),
            username=_text(col(oids.CLIENT_ENTRY, 3).get(index)),
            ap_mac=ap_mac,
            ap_name=ap_names.get(ap_mac) if ap_mac else None,
            slot=_int(col(oids.CLIENT_ENTRY, 5).get(index)),
            wlan_id=_int(col(oids.CLIENT_ENTRY, 6).get(index)),
            ssid=_text(col(oids.CLIENT_ENTRY, 7).get(index)),
            status=oids.CLIENT_STATUS.get(status) if status is not None else None,
            protocol=protocol,
            band=band,
            rssi=_int(col(oids.CLIENT_STATS_ENTRY, 1).get(index)),
            snr=_int(col(oids.CLIENT_STATS_ENTRY, 26).get(index)),
            uptime_seconds=_int(col(oids.LWAPP_CLIENT_ENTRY, 15).get(index)),
            data_rate_mbps=_float(col(oids.LWAPP_CLIENT_ENTRY, 17).get(index)),
            device_type=_text(col(oids.LWAPP_CLIENT_ENTRY, 44).get(index)),
            bytes_rx=_int(col(oids.CLIENT_STATS_ENTRY, 2).get(index)),
            bytes_tx=_int(col(oids.CLIENT_STATS_ENTRY, 3).get(index)),
        )
    return clients
