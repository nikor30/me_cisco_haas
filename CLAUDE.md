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

- **Milestone:** M0 reported done by Niko (ME reachable from this dev host, a Raspberry Pi, with SNMP +
  SSH enabled) — not yet verified by an actual walk. Repo contains only docs — no code yet.
- **Next step:** M1 — get ME IP + credentials from Niko (via env vars, never committed), capture
  `snmpbulkwalk` and CLI fixtures, resolve the `{tbd}` OIDs in kickstart §2.1, then start M2 (`pyciscome`).

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
| 2026-10-01 | Repo stays `me_cisco_haas`; integration domain is `cisco_me_plus` | Niko's choice; kickstart §7 name `cisco-me-ha` is obsolete |
| 2026-10-01 | `pyciscome` lives in this repo under `lib/pyciscome` | Simplest while iterating; can be split out to PyPI before the HACS release |
| 2026-10-01 | Commit directly to `main` and push | Solo repo, Niko's choice |
| 2026-10-01 | Project memory lives in this file, in git | Requested by Niko |

## Open questions

Carried over from kickstart §12 plus anything new. Remove when answered (move the answer to "Lab findings").

- Which syslog messages does ME 8.10 emit for client assoc/disassoc/roam? (decides AD-04)
- Is per-client RSSI available via SNMP on ME, or only CLI/web?
- Does ME allow parallel SSH sessions without locking out the GUI?

## Lab findings

Verified facts about the real device (OIDs, CLI quirks, timings). Empty until M1.

## Session log

- **2026-10-01** — Read kickstart, created this memory file, settled naming, library location and git workflow.
  No code yet.
