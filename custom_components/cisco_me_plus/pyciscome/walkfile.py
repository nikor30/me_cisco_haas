"""Replay a saved SNMP walk (as written by tools/capture_snmp.py) instead of a live controller."""

from __future__ import annotations

from pathlib import Path

from .snmp import SnmpValue


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def parse_walk(text: str) -> dict[str, SnmpValue]:
    """Parse `<oid> = <TYPE>: <value>` lines into the value types PysnmpTransport returns."""
    values: dict[str, SnmpValue] = {}
    for line in text.splitlines():
        oid, sep, rest = line.partition(" = ")
        if not sep:
            continue
        kind, _, payload = rest.partition(": ")
        if kind == "Hex-STRING":
            values[oid] = bytes.fromhex(payload)
        elif kind == "ObjectIdentifier":
            values[oid] = payload
        else:
            values[oid] = int(payload)
    return dict(sorted(values.items(), key=lambda item: _oid_key(item[0])))


class WalkFileTransport:
    """SnmpTransport backed by a walk file; used by tests and for offline development."""

    def __init__(self, path: str | Path) -> None:
        self._values = parse_walk(Path(path).read_text())

    async def walk(self, root: str) -> dict[str, SnmpValue]:
        prefix = root + "."
        return {oid: value for oid, value in self._values.items() if oid.startswith(prefix)}
