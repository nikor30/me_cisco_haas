# Cisco Mobility Express Plus for Home Assistant

A UI-configured Home Assistant integration for Cisco Mobility Express controllers (developed against an
AIR-AP3802I on ME 8.10.196.0). It replaces the YAML-only core `cisco_mobility_express` integration.

**Status: early (v0.1, read-only).** Everything is polled over SNMP v2c; nothing is changed on the controller.

## What you get

| Device | Entities |
|---|---|
| Controller | CPU, memory, last restart, clients (total / 2.4 GHz / 5 GHz), access points online, reachable |
| Each access point | Online, clients, last restart, IP address |
| Each radio | Channel, channel width, transmit power level, channel utilization, noise floor, clients, radio up |
| Each WLAN | Enabled, clients |
| Each wireless client | `device_tracker` with SSID, AP, band, protocol, RSSI, SNR and data rate as attributes |

Client trackers are created disabled, like other router-based trackers in Home Assistant; enable the ones
you care about. A client stays `home` for a configurable time after it was last seen (default 180 s).

## Install

1. In HACS, add `https://github.com/nikor30/me_cisco_haas` as a custom repository of type *Integration*
   and install it, or copy `custom_components/cisco_me_plus` into your `config/custom_components` folder.
2. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Cisco Mobility Express Plus*, then enter the
   controller address and a read-only SNMP v2c community.

Polling interval (default 30 s) and the consider-home time are under the integration's *Configure* button.

## Not there yet

Actions (WLAN on/off, AP LED and reboot, PSK rotation), join/leave/roam events and SNMPv3 are planned;
see `cisco-me-home-assistant-kickstart.md`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Tests replay an anonymised SNMP walk in `tests/fixtures`. With `ME_HOST` and `ME_SNMP_COMMUNITY` set,
`tests/cisco_me_plus/test_live.py` also polls a real controller (read-only).
