#!/usr/bin/env python3
"""Capture read-only CLI output from a Cisco Mobility Express controller as test fixtures.

Reads ME_HOST, ME_SSH_USER and ME_SSH_PASS from the environment (see .env, which is untracked).
Only `show` commands are sent, plus the session-local `config paging disable`.

Usage: capture_cli.py OUTPUT_DIR [COMMAND ...]
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncssh

DEFAULT_COMMANDS = [
    "show sysinfo",
    "show inventory",
    "show ap summary",
    "show advanced 802.11a summary",
    "show advanced 802.11b summary",
    "show client summary",
    "show wlan summary",
    "show rogue ap summary",
    "show snmpversion",
    "show snmpcommunity",
    "show snmpv3user",
    "show logging",
]

PROMPT = re.compile(r"\n\(.+?\) >\s*$")
TIMEOUT = 30


async def read_until(reader: asyncssh.SSHReader, pattern: re.Pattern[str]) -> str:
    buf = ""
    while not pattern.search(buf):
        chunk = await asyncio.wait_for(reader.read(4096), TIMEOUT)
        if not chunk:
            break
        buf += chunk
    return buf


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out_dir = Path(sys.argv[1])
    commands = sys.argv[2:] or DEFAULT_COMMANDS
    for command in commands:
        if not command.startswith("show "):
            print(f"refusing non-show command: {command}")
            return 2
    host = os.environ["ME_HOST"]
    user = os.environ["ME_SSH_USER"]
    password = os.environ["ME_SSH_PASS"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # AireOS/ME accepts any SSH-level auth and then asks for User:/Password: in the shell.
    async with asyncssh.connect(
        host,
        username=user,
        password=password,
        known_hosts=None,
        kex_algs="*",
        encryption_algs="*",
        server_host_key_algs="*",
        mac_algs="*",
    ) as conn:
        writer, reader, _ = await conn.open_session(term_type="vt100", term_size=(250, 1000))
        login = re.compile(r"(User:\s*$|\n\(.+?\) >\s*$)")
        banner = await read_until(reader, login)
        if banner.rstrip().endswith("User:"):
            writer.write(user + "\n")
            await read_until(reader, re.compile(r"Password:\s*$"))
            writer.write(password + "\n")
            await read_until(reader, PROMPT)
        writer.write("config paging disable\n")
        await read_until(reader, PROMPT)

        for command in commands:
            writer.write(command + "\n")
            raw = await read_until(reader, PROMPT)
            lines = raw.replace("\r", "").split("\n")
            # drop the echoed command and the trailing prompt
            body = "\n".join(lines[1:-1]).strip("\n") + "\n"
            name = re.sub(r"[^a-z0-9.]+", "_", command.lower()).strip("_") + ".txt"
            (out_dir / name).write_text(body)
            print(f"{name}: {len(body.splitlines())} lines")

        writer.write("logout\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
