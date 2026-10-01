# Project Kickstart — Cisco Mobility Express Integration for Home Assistant

| Field | Value |
|---|---|
| Working name | `cisco_me_plus` (custom integration, HACS-installable) |
| Owner | Niko |
| Target hardware | Cisco AIR-AP3802I running Mobility Express 8.10.196.0 (lab) |
| Target HA version | 2026.x (current stable) |
| Status | Kickstart / v0.1 |

Unknowns are marked **{tbd}**.

---

## 1. Goal

Build a modern, UI-configurable Home Assistant integration for Cisco Mobility Express (ME) that exposes **everything useful** the controller knows — controller health, APs, radios, WLANs and clients — and offers **actions** (WLAN on/off, AP reboot, LED, PSK rotation) and **events** (client join/leave/roam).

The existing core integration `cisco_mobility_express` is YAML-only, presence-only, has ~8 installs and known issues (DNS hostnames, no `consider_home`, timeouts since 2025.2). This project replaces it for our use case; it does not try to fix it upstream (optional later).
Create a memory file in GIT 

### Non-goals (v1)
- Catalyst 9800 / AireOS full WLC support (architecture should allow it later — see §9)
- Configuration management of the whole controller (only selected actions)
- Cloud / Meraki

---

## 2. Data Sources

ME 8.10 has **no official REST API**. We combine three channels, each for what it does best:

| Channel | Use for | Pros | Cons |
|---|---|---|---|
| **SNMP v2c/v3** (primary, polling) | Controller, AP, radio, WLAN, client metrics | Stable, documented MIBs, cheap to poll | Read-only in practice; walks on client tables can be large |
| **SSH CLI** (actions + gaps) | Actions, data not in MIBs | Everything is possible | Slow, screen-scraping, session handling |
| **Web UI JSON** (`/data/*.html`) | Client details as seen in dashboard | Same data as ME GUI | Undocumented, may change, needs session auth |
| **Syslog / SNMP traps** (push) | Events: client assoc/disassoc, AP up/down, rogue | Real-time | Needs HA-side listener, port config |

### 2.1 SNMP — MIBs & key OIDs
Verify all with `snmpwalk` against the lab ME before coding. **{tbd}** = not yet verified.

**AIRESPACE-WIRELESS-MIB / AIRESPACE-SWITCHING-MIB** (`1.3.6.1.4.1.14179`)

| Object | OID | Entity |
|---|---|---|
| Controller model / version / serial | `…14179.1.1.1.*` (agentInventory) {tbd exact leaves} | controller sensors |
| CPU utilization | `…14179.1.1.5.1.0` {tbd} | sensor % |
| Total / free memory | `…14179.1.1.5.2.0` / `…5.3.0` {tbd} | sensor |
| AP table (bsnAPTable) | `…14179.2.2.1.1` | one device per AP |
| — AP name | `…2.2.1.1.3` | |
| — AP model / serial / IP / uptime / oper status | `…2.2.1.1.x` {tbd leaves} | |
| AP radio table (bsnAPIfTable) | `…14179.2.2.2.1` | radio sub-entities |
| — channel | `…2.2.2.1.4` {tbd} | sensor |
| — tx power level | `…2.2.2.1.6` {tbd} | sensor |
| — clients per radio | {tbd} | sensor |
| Radio load / utilization / noise (bsnAPIfLoadParameters, bsnAPIfDBNoisePower) | `…14179.2.2.13` / `…2.2.15` {tbd} | sensors |
| WLAN table (bsnDot11EssTable) | `…14179.2.1.1.1` | one device per WLAN |
| — SSID | `…2.1.1.1.2` | |
| — admin status | `…2.1.1.1.6` {tbd} | binary_sensor / switch state |
| — number of clients | `…2.1.1.1.38` | sensor |
| Client table (bsnMobileStationTable) | `…14179.2.1.4.1` | device_tracker + attributes |
| — MAC / IP / username / AP MAC / SSID / status | `…2.1.4.1.{1,2,3,4,7,9}` {tbd} | |
| Client RSSI / SNR | `…14179.2.1.6.1.{1,26}` {tbd} | attributes or optional sensors |

**CISCO-LWAPP-AP-MIB / CISCO-LWAPP-DOT11-CLIENT-MIB** — richer AP/client data (uptime, join time, protocol 802.11ac/ax, data rate). Evaluate as supplement. {tbd}

### 2.2 SSH CLI — commands
Always start sessions with `config paging disable`.

| Purpose | Command |
|---|---|
| Controller info | `show sysinfo`, `show inventory` |
| AP list | `show ap summary`, `show ap config general <ap>` |
| Radio details | `show advanced 802.11a summary`, `show advanced 802.11b summary` |
| Clients | `show client summary`, `show client detail <mac>` |
| WLANs | `show wlan summary`, `show wlan <id>` |
| Rogues | `show rogue ap summary` |
| Enable / disable WLAN | `config wlan enable <id>` / `config wlan disable <id>` |
| Set PSK | `config wlan security wpa akm psk set-key ascii <key> <id>` (WLAN must be disabled first) |
| AP LED | `config ap led-state enable|disable <ap>` |
| AP flash LED (locate) | `config ap led-state flash <seconds> <ap>` {tbd syntax} |
| AP reboot | `config ap reset <ap>` |
| Disconnect client | `config client deauthenticate <mac>` |
| Save | `save config` (answer `y`) |
| Controller reboot | `reset system` (answer `y`) |

### 2.3 Web UI JSON
The core integration's library uses `/data/client-table.html` and `/data/systeminformation.html`. Map further endpoints with browser DevTools while clicking through the ME dashboard. {tbd}

### 2.4 Events (push)
- **Syslog** → UDP listener inside the integration (configurable port, default 5514). Parse assoc/disassoc/roam/AP-join messages → fire HA events.
- **SNMP traps** → alternative (pysnmp trap receiver). Decide one in AD-04.

---

## 3. Entity Model

Device hierarchy: **Controller → AP → Radio**, and **Controller → WLAN**. Clients are tracker entities linked to the controller (optionally to the AP they're on via attributes).

### 3.1 Controller device
| Platform | Entity | Source |
|---|---|---|
| sensor | Firmware version, model, serial (diagnostic) | SNMP |
| sensor | Uptime (timestamp) | SNMP |
| sensor | CPU %, memory used % | SNMP |
| sensor | Total clients, clients 2.4 GHz, clients 5 GHz | SNMP (aggregate) |
| sensor | Active APs, rogue APs detected | SNMP / CLI |
| binary_sensor | Controller reachable (connectivity) | poll result |
| button | Reboot controller (disabled by default) | CLI |
| button | Save config | CLI |
| update | Firmware update available? | {tbd — ME is EoL; likely skip} |

### 3.2 AP device (per AP)
| Platform | Entity | Source |
|---|---|---|
| sensor | Clients connected | SNMP |
| sensor | Uptime, IP, model, serial (diagnostic) | SNMP |
| binary_sensor | AP online | SNMP |
| switch | LED on/off | CLI |
| button | Locate (flash LED) | CLI |
| button | Reboot AP | CLI |

### 3.3 Radio (sub-entities of AP, per slot)
| Platform | Entity |
|---|---|
| sensor | Channel, channel width {tbd}, tx power level |
| sensor | Channel utilization %, noise floor dBm, interference % |
| sensor | Clients on radio |
| binary_sensor | Radio enabled |

### 3.4 WLAN device (per WLAN)
| Platform | Entity |
|---|---|
| switch | WLAN enabled |
| sensor | Clients on WLAN |
| text / service | PSK (write-only, never exposed as state) |
| button | Rotate PSK (generates random PSK, fires event with QR payload) |
| image | Wi-Fi QR code (`WIFI:T:WPA;S:<ssid>;P:<psk>;;`) — guest WLAN only, opt-in |

### 3.5 Clients
| Platform | Entity |
|---|---|
| device_tracker | One `ScannerEntity` per client MAC (disabled by default for new clients, like core HA trackers) |
| attributes | IP, hostname/username, SSID, AP name, band, protocol, RSSI, SNR, data rate, connected since |
| sensor (opt-in per client) | RSSI, AP name — for "which room is the phone in" |

Configurable **consider_home / grace period** (option flow), fixing the core integration's 8-minute away delay.

---

## 4. Services / Actions

| Service | Parameters | Notes |
|---|---|---|
| `cisco_me_plus.set_wlan_psk` | `wlan_id`, `psk` | Disables → sets → re-enables WLAN; save config |
| `cisco_me_plus.rotate_guest_psk` | `wlan_id`, `length` | Returns new PSK as response data |
| `cisco_me_plus.deauthenticate_client` | `mac` | Kick a client |
| `cisco_me_plus.run_command` | `command` | Admin-only, **show commands only**, returns output as response data |
| `cisco_me_plus.locate_ap` | `ap`, `seconds` | Flash LED |

## 5. Events

| Event | Data |
|---|---|
| `cisco_me_plus_client_connected` | mac, ip, ssid, ap, band |
| `cisco_me_plus_client_disconnected` | mac, ssid, ap, reason |
| `cisco_me_plus_client_roamed` | mac, from_ap, to_ap |
| `cisco_me_plus_ap_down` / `_ap_up` | ap, reason |
| `cisco_me_plus_rogue_detected` | bssid, ssid, rssi, channel |

Also exposed as **device triggers** in the automation editor.

---

## 6. Architecture Decisions

**AD-01 — Custom integration via HACS, not core.** Faster iteration, no core review constraints on SSH/scraping. Re-evaluate for core later.

**AD-02 — UI config flow + options flow.** Config: host, SNMP version/community or v3 creds, SSH user/pass, web user/pass. Options: scan intervals, consider_home, which features/channels are enabled, syslog port. No YAML.

**AD-03 — One `DataUpdateCoordinator` per channel.**
- `SnmpCoordinator` — 30 s default (controller, AP, radio, WLAN, client list)
- `CliCoordinator` — 300 s default, only for data not in SNMP
- Client presence may use a faster 15 s SNMP poll on the client table only.

**AD-04 — Events via syslog listener (default) with trap receiver as option.** {tbd — decide after checking what ME 8.10 actually emits for client assoc/disassoc}

**AD-05 — Separate Python library `pyciscome`.** All device I/O (pysnmp-lextudio async, asyncssh, aiohttp) in a PyPI-publishable lib; the HA integration only maps data to entities. Makes testing and future 9800/AireOS drivers easier.

**AD-06 — Stable unique IDs.** Controller: serial. AP: AP base radio MAC. Radio: AP MAC + slot. WLAN: controller serial + WLAN ID. Client: MAC.

**AD-07 — Safe actions.** Destructive buttons (controller reboot, AP reboot) are disabled by default. `run_command` only allows commands starting with `show`. Secrets never appear in entity state, attributes or diagnostics (redacted).

---

## 7. Repository Structure

```
cisco-me-ha/
├── custom_components/cisco_me_plus/
│   ├── __init__.py            # setup/unload entry, coordinators
│   ├── manifest.json          # iot_class: local_polling (+ local_push for events)
│   ├── config_flow.py         # config + options + reauth
│   ├── const.py
│   ├── coordinator.py         # Snmp/Cli coordinators
│   ├── entity.py              # base entity, DeviceInfo
│   ├── sensor.py
│   ├── binary_sensor.py
│   ├── switch.py
│   ├── button.py
│   ├── device_tracker.py
│   ├── image.py               # WLAN QR
│   ├── services.py / services.yaml
│   ├── device_trigger.py
│   ├── syslog_listener.py
│   ├── diagnostics.py         # redacted dump
│   ├── strings.json / translations/{en,de}.json
│   └── icons.json
├── lib/pyciscome/             # or separate repo → PyPI
│   ├── snmp.py  cli.py  web.py  models.py  parsers/
├── tests/
│   ├── fixtures/              # snmpwalk dumps, CLI output captures from lab ME
│   └── test_*.py              # pytest-homeassistant-custom-component
├── hacs.json
├── .github/workflows/         # hassfest, HACS validation, pytest, ruff
└── README.md
```

---

## 8. Milestones

| # | Milestone | Content | Done when |
|---|---|---|---|
| M0 | Lab ready | AP3800 on ME 8.10, SNMP v2c + v3 enabled, SSH enabled, test WLANs (main + guest), syslog pointed at dev HA | `snmpwalk` + SSH work from HA host |
| M1 | Discovery | Full `snmpwalk` of `1.3.6.1.4.1.14179` and CISCO-LWAPP MIBs saved as fixtures; CLI outputs captured; OIDs in §2.1 verified | all {tbd} in §2.1 resolved |
| M2 | Library core | `pyciscome` SNMP client + models + parsers, unit-tested on fixtures | tests green |
| M3 | Read-only integration | Config flow, controller/AP/radio/WLAN sensors, device_tracker with consider_home | runs in dev HA 24 h without errors |
| M4 | Actions | CLI driver, WLAN switch, AP LED/locate/reboot, services | actions verified in lab |
| M5 | Events | Syslog listener, events + device triggers | join/leave events arrive < 5 s |
| M6 | Polish | Diagnostics, translations EN/DE, icons, reauth flow, repair issues (controller unreachable), README, HACS release | v1.0.0 tagged |
| M7 | Optional | Dashboard card / Lovelace example, 9800 driver (RESTCONF), upstream to core | — |

---

## 9. Future: Catalyst 9800 / AireOS

Keep drivers pluggable in `pyciscome`:
- **AireOS 8.x** — same MIBs/CLI as ME → nearly free
- **Catalyst 9800** — RESTCONF/NETCONF YANG (`Cisco-IOS-XE-wireless-*-oper`), telemetry for events. Different driver, same entity model.

---

## 10. Dev Environment & Tooling

- HA dev container (`home-assistant/core` devcontainer) or local `hass` venv
- `pytest-homeassistant-custom-component`, `ruff`, `mypy`
- `snmpwalk`/`snmpbulkwalk` (net-snmp), `tio` for AP console
- CI: `hassfest`, `hacs/action`, pytest on push

## 11. Security

- Dedicated **read-only** ME user for SNMP/web polling; separate **read-write** user only if actions are enabled
- Prefer **SNMPv3 authPriv** (SHA/AES) over v2c
- ME management only reachable from home-lab VLAN
- All credentials in HA config entry storage, redacted in diagnostics and logs

## 12. Risks & Open Questions

| Type | Item |
|---|---|
| Risk | ME is End-of-Life — no firmware/security fixes; keep it isolated |
| Risk | Large client table walks may be slow on AP-hosted controller CPU → tune scan interval, use GETBULK |
| Risk | CLI output format differs between 8.x builds → fixture-based parser tests |
| Question | Which syslog messages does ME 8.10 emit for client assoc/disassoc/roam? {tbd} |
| Question | Is RSSI per client available via SNMP on ME, or only via CLI/web? {tbd} |
| Question | Does ME support multiple parallel SSH sessions without locking out the GUI? {tbd} |
| Assumption | Single-controller home setup (1–3 APs, < 100 clients) |

---

## 13. First Steps (today)

1. On ME: enable SNMP v3 user, SSH, and syslog to HA host.
2. From HA host:
   ```bash
   snmpbulkwalk -v3 -l authPriv -u ha -a SHA -A '<auth>' -x AES -X '<priv>' <me-ip> 1.3.6.1.4.1.14179 > fixtures/airespace.walk
   snmpbulkwalk -v3 ... <me-ip> 1.3.6.1.4.1.9.9 > fixtures/cisco.walk
   ```
3. Capture CLI outputs from §2.2 into `tests/fixtures/cli/*.txt`.
4. Resolve the {tbd} OIDs in §2.1, then start M2.
