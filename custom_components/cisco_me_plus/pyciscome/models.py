"""Data models returned by the client. Plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field

BAND_24 = "2.4"
BAND_5 = "5"


@dataclass(slots=True)
class Controller:
    name: str | None = None
    model: str | None = None
    serial: str | None = None
    mac: str | None = None
    manufacturer: str | None = None
    version: str | None = None
    uptime_seconds: int | None = None
    cpu_percent: int | None = None
    memory_total_kb: int | None = None
    memory_free_kb: int | None = None

    @property
    def memory_used_percent(self) -> float | None:
        if not self.memory_total_kb or self.memory_free_kb is None:
            return None
        return round(100 * (1 - self.memory_free_kb / self.memory_total_kb), 1)


@dataclass(slots=True)
class Radio:
    ap_mac: str
    slot: int
    band: str | None = None
    channel: int | None = None
    channel_width_mhz: int | None = None
    tx_power_level: int | None = None
    admin_enabled: bool | None = None
    oper_up: bool | None = None
    channel_utilization: int | None = None
    rx_utilization: int | None = None
    tx_utilization: int | None = None
    client_count: int | None = None
    noise_dbm: int | None = None


@dataclass(slots=True)
class AccessPoint:
    mac: str
    """Base radio MAC: the SNMP index and the stable identifier of the AP."""
    name: str | None = None
    location: str | None = None
    model: str | None = None
    serial: str | None = None
    ip: str | None = None
    ethernet_mac: str | None = None
    version: str | None = None
    online: bool | None = None
    uptime_seconds: int | None = None
    client_count: int | None = None
    radios: dict[int, Radio] = field(default_factory=dict)


@dataclass(slots=True)
class Wlan:
    wlan_id: int
    ssid: str | None = None
    enabled: bool | None = None
    client_count: int | None = None
    interface: str | None = None


@dataclass(slots=True)
class Client:
    mac: str
    ip: str | None = None
    username: str | None = None
    ap_mac: str | None = None
    ap_name: str | None = None
    slot: int | None = None
    wlan_id: int | None = None
    ssid: str | None = None
    status: str | None = None
    protocol: str | None = None
    band: str | None = None
    rssi: int | None = None
    snr: int | None = None
    uptime_seconds: int | None = None
    data_rate_mbps: float | None = None
    device_type: str | None = None
    bytes_rx: int | None = None
    bytes_tx: int | None = None

    @property
    def associated(self) -> bool:
        return self.status == "associated"


@dataclass(slots=True)
class Snapshot:
    """Everything one poll returns."""

    controller: Controller
    access_points: dict[str, AccessPoint] = field(default_factory=dict)
    wlans: dict[int, Wlan] = field(default_factory=dict)
    clients: dict[str, Client] = field(default_factory=dict)

    def clients_on_band(self, band: str) -> int:
        return sum(1 for c in self.clients.values() if c.associated and c.band == band)
