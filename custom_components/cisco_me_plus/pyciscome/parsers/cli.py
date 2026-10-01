"""Parse `show` command output."""

from __future__ import annotations

import re

from ..models import Application

TOP_APPS = "show flexconnect avc statistics top-apps"

# " ms-teams-video          (U)    11455    6942818    606        461006       258896897"
# "                         (D)    12531    5814055    463        860837       395239322"
_APP_ROW = re.compile(r"^\s*(?P<name>\S+)?\s+\((?P<dir>[UD])\)\s+(?P<numbers>\d+(?:\s+\d+){4})\s*$")


def parse_top_apps(text: str) -> list[Application]:
    """Applications from the AVC top-apps table, busiest first (by bytes in the recent window)."""
    apps: list[Application] = []
    current: Application | None = None
    for line in text.splitlines():
        match = _APP_ROW.match(line)
        if not match:
            continue
        packets, recent_bytes, _avg_size, total_packets, total_bytes = (
            int(n) for n in match["numbers"].split()
        )
        if match["name"]:
            current = Application(name=match["name"])
            apps.append(current)
        if current is None:
            continue
        if match["dir"] == "U":
            current.packets_up, current.bytes_up = packets, recent_bytes
            current.total_packets_up, current.total_bytes_up = total_packets, total_bytes
        else:
            current.packets_down, current.bytes_down = packets, recent_bytes
            current.total_packets_down, current.total_bytes_down = total_packets, total_bytes
    return sorted(apps, key=lambda app: (app.bytes, app.total_bytes), reverse=True)
