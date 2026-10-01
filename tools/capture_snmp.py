#!/usr/bin/env python3
"""Walk an SNMP subtree on a Cisco Mobility Express controller and save it as a test fixture.

Reads ME_HOST and ME_SNMP_COMMUNITY (v2c, read-only) from the environment (see .env, untracked).
Output is one line per varbind: `<numeric oid> = <TYPE>: <value>`; octet strings are hex-encoded.

Usage: capture_snmp.py OUTPUT_FILE [ROOT_OID]
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulk_walk_cmd,
)
from pysnmp.proto.rfc1902 import OctetString

DEFAULT_ROOT = "1.3.6.1.4.1.14179"


def render(value: object) -> str:
    kind = type(value).__name__
    if isinstance(value, OctetString):
        return f"Hex-STRING: {bytes(value).hex(' ')}"
    return f"{kind}: {value.prettyPrint()}"  # type: ignore[attr-defined]


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out_file = Path(sys.argv[1])
    root = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ROOT
    out_file.parent.mkdir(parents=True, exist_ok=True)

    engine = SnmpEngine()
    target = await UdpTransportTarget.create((os.environ["ME_HOST"], 161), timeout=5, retries=2)
    count = 0
    with out_file.open("w") as out:
        async for error_indication, error_status, _, var_binds in bulk_walk_cmd(
            engine,
            CommunityData(os.environ["ME_SNMP_COMMUNITY"], mpModel=1),
            target,
            ContextData(),
            0,
            25,
            ObjectType(ObjectIdentity(root)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if error_indication or error_status:
                print(f"error after {count} varbinds: {error_indication or error_status}")
                return 1
            for oid, value in var_binds:
                out.write(f"{oid} = {render(value)}\n")
                count += 1
    engine.close_dispatcher()
    print(f"{out_file}: {count} varbinds under {root}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
