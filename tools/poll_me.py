#!/usr/bin/env python3
"""Poll the live controller once with pyciscome and print a summary (read-only smoke test).

Reads ME_HOST and ME_SNMP_COMMUNITY from the environment (see .env, untracked).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from pyciscome import MobilityExpress, PysnmpTransport


async def main() -> int:
    transport = PysnmpTransport(os.environ["ME_HOST"], os.environ["ME_SNMP_COMMUNITY"])
    me = MobilityExpress(transport)
    try:
        started = time.monotonic()
        snapshot = await me.fetch_snapshot()
        full = time.monotonic() - started
        started = time.monotonic()
        await me.fetch_clients()
        clients_only = time.monotonic() - started
    finally:
        transport.close()

    c = snapshot.controller
    print(f"{c.name}  {c.model}  {c.version}  cpu {c.cpu_percent}%  mem {c.memory_used_percent}%")
    for ap in snapshot.access_points.values():
        print(f"  AP {ap.name}: online={ap.online} clients={ap.client_count}")
        for radio in ap.radios.values():
            print(
                f"    slot {radio.slot}: {radio.band} GHz ch {radio.channel}/{radio.channel_width_mhz} MHz "
                f"up={radio.oper_up} util={radio.channel_utilization}% clients={radio.client_count} "
                f"noise={radio.noise_dbm} dBm"
            )
    for wlan in snapshot.wlans.values():
        print(f"  WLAN {wlan.wlan_id}: enabled={wlan.enabled} clients={wlan.client_count}")
    print(
        f"  clients: {len(snapshot.clients)} "
        f"(2.4 GHz {snapshot.clients_on_band('2.4')}, 5 GHz {snapshot.clients_on_band('5')})"
    )
    print(f"full snapshot {full:.1f}s, client table only {clients_only:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
