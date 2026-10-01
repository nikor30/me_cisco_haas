#!/usr/bin/env python3
"""Turn raw captures (tests/fixtures/raw, untracked) into fixtures that are safe to commit.

SNMP: only the allowlisted tables below are kept. MACs (in indexes and values), IPv4 addresses,
serial numbers and SSIDs are replaced consistently; a few opaque columns are blanked.
CLI: the same replacements are applied as text substitutions, so SNMP and CLI fixtures still agree.

The script refuses to finish if any original identifier survives in the output.

Usage: anonymise_fixtures.py [RAW_DIR] [OUT_DIR]   (defaults: tests/fixtures/raw, tests/fixtures)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AIRESPACE = "1.3.6.1.4.1.14179"
CISCO = "1.3.6.1.4.1.9.9"

# table prefix -> True if the row index starts with a 6-octet MAC
SNMP_TABLES: dict[str, bool] = {
    "1.3.6.1.2.1.1": False,
    f"{AIRESPACE}.1.1.1": False,
    f"{AIRESPACE}.1.1.5": False,
    f"{AIRESPACE}.2.1.1.1": False,
    f"{AIRESPACE}.2.1.4.1": True,
    f"{AIRESPACE}.2.1.6.1": True,
    f"{AIRESPACE}.2.2.1.1": True,
    f"{AIRESPACE}.2.2.2.1": True,
    f"{AIRESPACE}.2.2.13.1": True,
    f"{AIRESPACE}.2.2.15.1": True,
    f"{CISCO}.513.1.1.1.1": True,
    f"{CISCO}.513.1.2.1.1": True,
    f"{CISCO}.599.1.3.1.1": True,
}
SSID_COLUMNS = (f"{AIRESPACE}.2.1.1.1.2.",)
# opaque or identifying string columns that nothing parses: blank them
BLANK_COLUMNS = (
    f"{AIRESPACE}.2.2.1.1.10.",
    f"{CISCO}.513.1.1.1.1.37.",
    f"{CISCO}.599.1.3.1.1.38.",
)
# never publish: SNMP settings, full WLAN config dumps, and files named after a client MAC
CLI_SKIP = re.compile(r"show_snmp|show_wlan_\d|(?:[0-9a-f]{2}_){5}[0-9a-f]{2}")

MAC_RE = re.compile(r"(?<![0-9a-fA-F:])([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})(?![0-9a-fA-F]|:[0-9a-fA-F])")
IP_RE = re.compile(
    r"(?<![\d.:])((?:192[.:]168|10[.:]\d{1,3}|172[.:](?:1[6-9]|2\d|3[01]))[.:]\d{1,3}[.:]\d{1,3})(?![\d.:])"
)
SERIAL_RE = re.compile(r"\b[A-Z]{3}\d{4}[A-Z0-9]{4}\b")


class Mapper:
    def __init__(self) -> None:
        self.macs: dict[bytes, bytes] = {}
        self.ips: dict[bytes, bytes] = {}
        self.strings: dict[str, str] = {}
        self._serials = 0
        self._ssids = 0

    def mac(self, raw: bytes) -> bytes:
        if not any(raw):
            return raw
        if raw not in self.macs:
            n = len(self.macs) + 1
            self.macs[raw] = bytes([0x02, 0, 0, 0, n >> 8, n & 0xFF])
        return self.macs[raw]

    def ip(self, raw: bytes) -> bytes:
        if not any(raw) or raw[0] == 0xFF:
            return raw
        if raw not in self.ips:
            self.ips[raw] = bytes([192, 0, 2, len(self.ips) + 1])
        return self.ips[raw]

    def serial(self, value: str) -> str:
        if value not in self.strings:
            self._serials += 1
            self.strings[value] = f"FCW0000A{self._serials:03d}"
        return self.strings[value]

    def ssid(self, value: str) -> str:
        if value not in self.strings:
            self._ssids += 1
            self.strings[value] = f"ssid-{self._ssids}"
        return self.strings[value]

    def text(self, value: str) -> str:
        """Anonymise free text (CLI output or printable SNMP strings)."""

        def mac_sub(m: re.Match[str]) -> str:
            return self.mac(bytes.fromhex(m[1].replace(":", ""))).hex(":")

        def ip_sub(m: re.Match[str]) -> str:
            sep = ":" if ":" in m[1] else "."
            mapped = self.ip(bytes(int(p) for p in re.split("[.:]", m[1])))
            return sep.join(str(b) for b in mapped)

        value = MAC_RE.sub(mac_sub, value)
        value = IP_RE.sub(ip_sub, value)
        value = SERIAL_RE.sub(lambda m: self.serial(m[0]), value)
        for original, replacement in self.strings.items():
            if not original.startswith("FCW"):
                value = re.sub(rf"(?<![\w-]){re.escape(original)}(?![\w-])", replacement, value)
        return value

    def leaks(self) -> list[str]:
        """Every textual form in which an original identifier could show up in the output."""
        out = list(self.strings)
        for mac in self.macs:
            out += [mac.hex(":"), mac.hex(" "), ".".join(str(b) for b in mac)]
        for ip in self.ips:
            out += [".".join(str(b) for b in ip), ":".join(str(b) for b in ip), ip.hex(" ")]
        return out


def oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in oid.split("."))


def anonymise_walks(raw_dir: Path, mapper: Mapper) -> list[str]:
    lines: dict[str, str] = {}
    for walk in sorted(raw_dir.glob("*.walk")):
        for line in walk.read_text().splitlines():
            oid, _, value = line.partition(" = ")
            table = next((t for t in SNMP_TABLES if oid.startswith(t + ".")), None)
            if table is None:
                continue
            if SNMP_TABLES[table]:
                column, *index = oid[len(table) + 1 :].split(".")
                mac = mapper.mac(bytes(int(p) for p in index[:6]))
                oid = ".".join([table, column, *(str(b) for b in mac), *index[6:]])
            kind, _, payload = value.partition(": ")
            if kind == "Hex-STRING":
                raw = bytes.fromhex(payload)
                if oid.startswith(BLANK_COLUMNS):
                    raw = b""
                elif oid.startswith(SSID_COLUMNS):
                    raw = mapper.ssid(raw.decode()).encode()
                elif raw and all(32 <= b < 127 for b in raw):
                    raw = mapper.text(raw.decode()).encode()
                elif len(raw) == 6:
                    raw = mapper.mac(raw)
                elif len(raw) == 4:
                    raw = mapper.ip(raw)
                elif any(raw):
                    raw = bytes(len(raw))
                value = f"Hex-STRING: {raw.hex(' ')}"
            lines[oid] = value
    return [f"{oid} = {lines[oid]}" for oid in sorted(lines, key=oid_key)]


def main() -> int:
    raw_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/raw")
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "tests/fixtures")
    mapper = Mapper()

    # SSIDs must be known before any other string is rewritten
    for walk in sorted((raw_dir / "snmp").glob("*.walk")):
        for line in walk.read_text().splitlines():
            if line.startswith(SSID_COLUMNS):
                mapper.ssid(bytes.fromhex(line.split("Hex-STRING: ")[1]).decode())

    outputs: dict[Path, str] = {}
    walk_lines = anonymise_walks(raw_dir / "snmp", mapper)
    outputs[out_dir / "snmp" / "me_8_10.walk"] = "\n".join(walk_lines) + "\n"
    for cli in sorted((raw_dir / "cli").glob("*.txt")):
        if not CLI_SKIP.search(cli.name):
            outputs[out_dir / "cli" / cli.name] = mapper.text(cli.read_text())

    leaks = mapper.leaks()
    for path, content in outputs.items():
        found = [leak for leak in leaks if leak in content]
        if found:
            print(f"LEAK in {path}: {len(found)} original identifier(s) survived; nothing written")
            return 1
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"{path}: {len(content.splitlines())} lines")
    print(f"mapped {len(mapper.macs)} MACs, {len(mapper.ips)} IPs, {len(mapper.strings)} strings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
