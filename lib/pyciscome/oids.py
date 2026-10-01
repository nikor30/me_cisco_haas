"""OIDs and enum values, verified against ME 8.10.196.0 on an AIR-AP3802I (see CLAUDE.md)."""

from __future__ import annotations

SYSTEM = "1.3.6.1.2.1.1"
SYS_UPTIME = f"{SYSTEM}.3.0"
SYS_NAME = f"{SYSTEM}.5.0"

AIRESPACE = "1.3.6.1.4.1.14179"
LWAPP_AP = "1.3.6.1.4.1.9.9.513"
LWAPP_CLIENT = "1.3.6.1.4.1.9.9.599"

# agentInventory / agentResourceInfo (scalars)
INVENTORY = f"{AIRESPACE}.1.1.1"
INV_MODEL = f"{INVENTORY}.3.0"
INV_SERIAL = f"{INVENTORY}.4.0"
INV_MAC = f"{INVENTORY}.9.0"
INV_MANUFACTURER = f"{INVENTORY}.12.0"
INV_VERSION = f"{INVENTORY}.14.0"
RESOURCES = f"{AIRESPACE}.1.1.5"
RES_CPU = f"{RESOURCES}.1.0"
RES_MEM_TOTAL = f"{RESOURCES}.2.0"
RES_MEM_FREE = f"{RESOURCES}.3.0"

# Table entries: append ".<column>" to get a column, rows are indexed as noted.
WLAN_ENTRY = f"{AIRESPACE}.2.1.1.1"  # index: WLAN id
CLIENT_ENTRY = f"{AIRESPACE}.2.1.4.1"  # index: client MAC
CLIENT_STATS_ENTRY = f"{AIRESPACE}.2.1.6.1"  # index: client MAC
AP_ENTRY = f"{AIRESPACE}.2.2.1.1"  # index: AP base radio MAC
RADIO_ENTRY = f"{AIRESPACE}.2.2.2.1"  # index: AP MAC + slot
RADIO_LOAD_ENTRY = f"{AIRESPACE}.2.2.13.1"  # index: AP MAC + slot
RADIO_NOISE_ENTRY = f"{AIRESPACE}.2.2.15.1"  # index: AP MAC + slot + channel
LWAPP_AP_ENTRY = f"{LWAPP_AP}.1.1.1.1"  # index: AP MAC
LWAPP_RADIO_ENTRY = f"{LWAPP_AP}.1.2.1.1"  # index: AP MAC + slot
LWAPP_CLIENT_ENTRY = f"{LWAPP_CLIENT}.1.3.1.1"  # index: client MAC

AP_OPER_ASSOCIATED = 1
RADIO_ADMIN_ENABLED = 1
RADIO_OPER_UP = 2
WLAN_ADMIN_ENABLED = 1

# bsnMobileStationStatus
CLIENT_STATUS = {
    0: "idle",
    1: "aaa_pending",
    2: "authenticated",
    3: "associated",
    4: "powersave",
    5: "disassociated",
    6: "to_be_deleted",
    7: "probing",
    8: "blacklisted",
}

# cldcClientProtocol -> (name, band). 3, 6, 7 and 10 confirmed against `show client summary`.
# bsnMobileStationProtocol is not used: it reports 802.11ac clients as plain 802.11a.
CLIENT_PROTOCOL = {
    1: ("802.11a", "5"),
    2: ("802.11b", "2.4"),
    3: ("802.11g", "2.4"),
    6: ("802.11n", "2.4"),
    7: ("802.11n", "5"),
    10: ("802.11ac", "5"),
    11: ("802.11ax", "5"),
    12: ("802.11ax", "2.4"),
}

# cLApDot11 channel width enum -> MHz. 3 and 5 confirmed on the lab ME.
CHANNEL_WIDTH_MHZ = {1: 5, 2: 10, 3: 20, 4: 40, 5: 80, 6: 160}
