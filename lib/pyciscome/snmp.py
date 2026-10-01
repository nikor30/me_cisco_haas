"""SNMP transport: the only place that talks to the network."""

from __future__ import annotations

from typing import Protocol

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulk_walk_cmd,
)
from pysnmp.proto.rfc1902 import ObjectIdentifier, OctetString

SnmpValue = int | bytes | str


class SnmpError(Exception):
    """The controller did not answer, or answered with an SNMP error."""


class SnmpTransport(Protocol):
    async def walk(self, root: str) -> dict[str, SnmpValue]:
        """Return every varbind below `root`, keyed by full numeric OID, in MIB order."""


class PysnmpTransport:
    """SNMP v2c over UDP. Read-only: only GETBULK is ever sent."""

    def __init__(
        self,
        host: str,
        community: str,
        *,
        port: int = 161,
        timeout: float = 5,
        retries: int = 2,
        max_repetitions: int = 25,
    ) -> None:
        self._host = host
        self._port = port
        self._community = CommunityData(community, mpModel=1)
        self._timeout = timeout
        self._retries = retries
        self._max_repetitions = max_repetitions
        self._engine: SnmpEngine | None = None
        self._target: UdpTransportTarget | None = None

    async def walk(self, root: str) -> dict[str, SnmpValue]:
        if self._engine is None:
            self._engine = SnmpEngine()
        if self._target is None:
            self._target = await UdpTransportTarget.create(
                (self._host, self._port), timeout=self._timeout, retries=self._retries
            )
        result: dict[str, SnmpValue] = {}
        async for error_indication, error_status, _, var_binds in bulk_walk_cmd(
            self._engine,
            self._community,
            self._target,
            ContextData(),
            0,
            self._max_repetitions,
            ObjectType(ObjectIdentity(root)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if error_indication:
                raise SnmpError(f"{self._host}: {error_indication}")
            if error_status:
                raise SnmpError(f"{self._host}: {error_status.prettyPrint()}")
            for oid, value in var_binds:
                if isinstance(value, OctetString):
                    result[str(oid)] = bytes(value)
                elif isinstance(value, ObjectIdentifier):
                    result[str(oid)] = str(value)
                else:
                    try:
                        result[str(oid)] = int(value)
                    except (TypeError, ValueError):  # noSuchObject / endOfMibView
                        continue
        return result

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close_dispatcher()
            self._engine = None
            self._target = None
