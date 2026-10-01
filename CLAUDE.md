# CLAUDE.md — Project Memory

Working memory for Claude Code sessions in this repo. Kept in git so it survives across machines.
The full spec is `cisco-me-home-assistant-kickstart.md` — this file does **not** repeat it; it tracks
state, decisions and lab findings. Update it at the end of every working session.

## Project in one paragraph

`cisco_me_plus`: a HACS custom integration for Home Assistant (2026.x) that replaces the YAML-only core
`cisco_mobility_express` integration. Target: Cisco AIR-AP3802I running Mobility Express 8.10.196.0 (lab).
Exposes controller / AP / radio / WLAN / client entities, actions (WLAN on/off, AP reboot, LED, PSK
rotation) and events (client join/leave/roam). Owner: Niko.

## Current status

- **Milestone:** M0–M2 done. **M3 code-complete** (2026-10-01): `custom_components/cisco_me_plus` has
  config flow (host, v2c community, port), options flow (scan interval, consider_home), one SNMP
  coordinator, sensors and binary sensors for controller/AP/radio/WLAN, and a `device_tracker` per client.
  26 tests pass, including a live read-only setup against the ME (97 entities).
- **Not yet done for M3's exit criterion:** it has never run in a real Home Assistant install; the
  "24 h in dev HA without errors" check is open. Niko has not said which HA instance to test on.
- **Next step:** install on a real HA (HACS custom repo or copy the folder), watch it for a day, then M4
  (CLI driver + actions) — which needs Niko to lift the read-only rule.
- **Still open from M1:** per-AP/per-client `show … detail` captures and CLI parsers (needed for M4),
  web UI JSON endpoints (not looked at yet).
- **Waiting on Niko:** pointing ME syslog at the HA server (agreed; the level must also be raised from
  `errors` or client join/leave will not be sent). SNMPv3 is postponed — v2c for now.

## How to work here

- `.venv/bin/pytest -q` and `.venv/bin/ruff check . && .venv/bin/ruff format --check .` before committing.
- `set -a; . ./.env; set +a` then `.venv/bin/python tools/poll_me.py` for a live read-only smoke test;
  with the same env, `pytest tests/cisco_me_plus/test_live.py -s` sets the integration up against the ME.
- The venv is Python 3.13 with HA 2026.2.3 (`pytest-homeassistant-custom-component`) and pysnmp 7.1.22
  (HA's own pin). Building it needed `apt install python3-dev`. Keep `asyncssh<2.22` (newer ones need a
  `cryptography` HA does not allow).
- Custom integrations read `translations/en.json`; there is no `strings.json`.
- New captures: `tools/capture_cli.py` / `tools/capture_snmp.py` into `tests/fixtures/raw/`, then
  `tools/anonymise_fixtures.py` regenerates `tests/fixtures/{snmp,cli}` and aborts if any original MAC,
  IP, serial or SSID survives. Add new SNMP tables to its allowlist; never commit anything from `raw/`.
- **Read-only against the ME** (Niko, 2026-10-01): `show` commands and SNMP reads only, until he says
  otherwise. He is on that network himself.

## Ground rules (from the kickstart)

- ME 8.10 has no REST API: SNMP is the primary polling channel, SSH CLI for actions and gaps,
  web UI JSON (`/data/*.html`) as supplement, syslog (default) or SNMP traps for events.
- All device I/O lives in the `pyciscome` library; the integration only maps data to entities (AD-05).
- UI config flow + options flow only, no YAML (AD-02). One `DataUpdateCoordinator` per channel (AD-03).
- Unique IDs: controller = serial, AP = base radio MAC, radio = AP MAC + slot,
  WLAN = controller serial + WLAN ID, client = MAC (AD-06).
- Safety (AD-07): reboot buttons disabled by default, `run_command` accepts `show …` only, secrets never
  in state, attributes, diagnostics or logs.
- OIDs and CLI syntax marked `{tbd}` in the kickstart are **unverified** — confirm against the lab ME
  and save the output as a test fixture before coding against them.
- Never commit real credentials, PSKs, SNMP communities or unredacted walks containing them.

## Decisions log

Decisions made after the kickstart was written. Newest first.

| Date | Decision | Why |
|---|---|---|
| 2026-10-01 | SNMP v2c for now, v3 later; read-only commands only | Niko's choice |
| 2026-10-01 | Syslog will be pointed at the HA server (by Niko) | The listener runs inside the integration |
| 2026-10-01 | Poll SNMP per column, sequentially | Whole-table walks fetch ~10x unused data; ME runs on an AP CPU |
| 2026-10-01 | Repo stays `me_cisco_haas`; integration domain is `cisco_me_plus` | Niko's choice; kickstart §7 name `cisco-me-ha` is obsolete |
| 2026-10-01 | `pyciscome` is vendored at `custom_components/cisco_me_plus/pyciscome` (was `lib/pyciscome`) | HACS only ships the integration folder and the lib is not on PyPI; `pyproject.toml` still exposes it as top-level `pyciscome`. Claude's call — Niko had picked "inside this repo" |
| 2026-10-01 | One coordinator, full snapshot every 30 s (min 10 s), instead of a separate fast client poll | A full snapshot takes ~1.2 s, so the split in AD-03 is not needed yet |
| 2026-10-01 | WLAN "enabled" is a read-only binary sensor until M4 turns it into a switch | Read-only rule |
| 2026-10-01 | Commit directly to `main` and push | Solo repo, Niko's choice |
| 2026-10-01 | Project memory lives in this file, in git | Requested by Niko |

## Open questions

Carried over from kickstart §12 plus anything new. Remove when answered (move the answer to "Lab findings").

- Which syslog messages does ME 8.10 emit for client assoc/disassoc/roam? (decides AD-04)
- Does ME allow parallel SSH sessions without locking out the GUI?

## Lab findings

Verified facts about the real device (OIDs, CLI quirks, timings). Captured 2026-10-01.

### Environment

- The "lab" is Niko's **live home network**: 3× AIR-AP3802I-E-K9 (`studio` = ME master, `kitchen`,
  `bedroom`), 2 WLANs (`home`, `pronto`), ~31 clients. Treat it as production: read-only unless Niko
  explicitly approves a specific change.
- ME at `192.168.10.164`, system name `AP1`, 8.10.196.0. TCP 22 and 443 open, 80 closed.
- Credentials live in the untracked `.env` (`ME_HOST`, `ME_SSH_USER`, `ME_SSH_PASS`, `ME_SNMP_COMMUNITY`).
- SNMP: v2c enabled (RO community in `.env`), v3 enabled but **no v3 users configured**.
- Syslog: **no remote host configured**, level `errors` — client join/leave is not logged at that level.
- Dev host has no net-snmp/sshpass/expect; use `.venv` (asyncssh, pysnmp 7) and `tools/capture_*.py`.
- Raw captures are in `tests/fixtures/raw/` (gitignored — the GitHub repo is public and the dumps contain
  client MACs/IPs, neighbours' SSIDs, serials and the SNMP community). Only anonymised fixtures get committed.

### SSH

- asyncssh connects fine with default algorithms; SSH-level auth is accepted, then the shell asks
  `User:` / `Password:` again. Prompt is `(Cisco Controller) >`. `config paging disable` works.
- `show client summary` etc. match the formats assumed in kickstart §2.2.

### SNMP — AIRESPACE (`1.3.6.1.4.1.14179`), 6489 varbinds, walk takes well under a minute

| What | OID (under 14179) | Notes |
|---|---|---|
| Model / serial / burned-in MAC | `1.1.1.3.0` / `1.1.1.4.0` / `1.1.1.9.0` | |
| Manufacturer / product / version | `1.1.1.12.0` / `1.1.1.13.0` / `1.1.1.14.0` | |
| CPU % | `1.1.5.1.0` | |
| Memory total / free (kB) | `1.1.5.2.0` / `1.1.5.3.0` | used % matches `show sysinfo` |
| AP table `bsnAPTable` | `2.2.1.1.<col>.<base radio MAC>` | 3 = name, 4 = location, 6 = oper status (1 = up), 16 = model, 17 = serial, 19 = IP, 33 = ethernet MAC, 8/31 = sw version |
| Radio table `bsnAPIfTable` | `2.2.2.1.<col>.<MAC>.<slot>` | 1 = slot, 4 = channel, 6 = tx power level, 12 = oper status (2 = up, 1 = down), 34 = admin status (1 = enabled, 2 = disabled) |
| Radio load | `2.2.13.1.<col>.<MAC>.<slot>` | 1 = rx util, 2 = tx util, 3 = channel util %, 4 = clients |
| Radio noise | `2.2.15.1.21.<MAC>.<slot>.<channel>` | dBm, one row per channel |
| WLAN table `bsnDot11EssTable` | `2.1.1.1.<col>.<wlan id>` | 2 = SSID, 6 = admin status (1 = enabled), 38 = client count, 42 = interface. PSK columns read as `****` |
| Client table | `2.1.4.1.<col>.<client MAC>` | 1 = MAC, 2 = IP, 3 = username, 4 = AP base radio MAC, 5 = slot, 6 = WLAN id, 7 = SSID, 9 = status (3 = associated), 23 = policy state (`RUN`), 25 = protocol (**unreliable**: reports 802.11ac as 1 = 802.11a; use LWAPP col 6) |
| Client RSSI / SNR | `2.1.6.1.1` / `2.1.6.1.26` | **available via SNMP**; also byte/packet counters in cols 2–6 |

All AP/radio/client tables are indexed by MAC as 6 decimal sub-identifiers. Octet-string values (MACs,
IPs, names) come back as raw bytes. The master AP's serial equals the controller serial.

### SNMP — CISCO-LWAPP (`1.3.6.1.4.1.9.9`), 11079 varbinds

- `513.1.1.1.1.<col>.<MAC>` (AP): 5 = name, 6 = AP uptime, 7 = CAPWAP uptime, 8 = join time, 54 = clients.
- `513.1.2.1.1.<col>.<MAC>.<slot>` (radio): 23 = channel width (3 = 20 MHz, 5 = 80 MHz), 24 = extension channels.
- `599.1.3.1.1.<col>.<client MAC>` (client): 6 = protocol (3 = g, 6 = n 2.4, 7 = n 5, 10 = ac — checked
  against `show client summary`), 8 = AP MAC, 15 = uptime (s), 17 = data rate, 28 = SSID, 44 = device type.

## Session log

- **2026-10-01** — Read kickstart, created this memory file, settled naming, library location and git workflow.
  Then got ME access, added `tools/capture_cli.py` and `tools/capture_snmp.py`, captured CLI output and
  both SNMP walks, resolved the core OIDs. Only read-only commands were sent to the ME.
  Built `tools/anonymise_fixtures.py`, committed anonymised fixtures, built `lib/pyciscome` (M2).
  Built the HA integration (M3) with tests; verified live read-only.
