# Cisco Mobility Express Plus for Home Assistant

A UI-configured Home Assistant integration for Cisco Mobility Express controllers (developed against an
AIR-AP3802I on ME 8.10.196.0). It replaces the YAML-only core `cisco_mobility_express` integration.

**Status: early (v0.1, read-only).** Data is polled over SNMP v2c, plus one `show` command over SSH for
application statistics if you give it an SSH login. Nothing is changed on the controller.

## What you get

| Device | Entities |
|---|---|
| Controller | CPU, memory, last restart, clients (total / 2.4 GHz / 5 GHz), access points online, reachable, download and upload rate, top client (by current throughput and by data usage), top application |
| Each access point | Online, clients, last restart, IP address, download and upload rate |
| Each radio | Channel, channel width, transmit power level, channel utilization, noise floor, clients, radio up |
| Each WLAN | Enabled, clients, download and upload rate |
| Each wireless client | `device_tracker` with SSID, AP, band, protocol, RSSI, SNR, data rate and current download/upload as attributes |

Client trackers are created disabled, like other router-based trackers in Home Assistant; enable the ones
you care about. A client stays `home` for a configurable time after it was last seen (default 180 s).

### Traffic, top clients and applications

- **Rates** come from the controller's per-client byte counters. The controller refreshes those only about
  every 90 seconds, so rates are averages over that window and lag by up to that long.
- **Top client** and **Top client by data usage** show the busiest client's name (the name of its tracker
  entity if you renamed it, else its MAC); the `clients` attribute holds the top 10 with their numbers.
  Data usage counts from when each client last connected.
- **Top application** needs an SSH login and Application Visibility enabled on the WLAN. The
  `applications` attribute holds the top 10 with bytes up/down. The integration refuses to send anything
  but `show` commands. The statistics are controller-wide; this controller does not report them per client.

## Install

1. In HACS, add `https://github.com/nikor30/me_cisco_haas` as a custom repository of type *Integration*
   and install it, or copy `custom_components/cisco_me_plus` into your `config/custom_components` folder.
2. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Cisco Mobility Express Plus*, then enter the
   controller address and a read-only SNMP v2c community. The SSH user name and password are optional
   (application statistics only) and can be added later with *Reconfigure*.

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

Tests replay anonymised captures in `tests/fixtures`. With `ME_HOST` and `ME_SNMP_COMMUNITY` set,
`tests/cisco_me_plus/test_live.py` also polls a real controller (read-only).
