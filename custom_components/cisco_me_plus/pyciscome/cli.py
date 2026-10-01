"""SSH CLI transport. Read-only: anything that is not a `show` command is refused."""

from __future__ import annotations

import asyncio
import re
from typing import Protocol

import asyncssh

PROMPT = re.compile(r"\n\(.+?\) >\s*$")
LOGIN_OR_PROMPT = re.compile(r"(User:\s*$|\n\(.+?\) >\s*$)")
PASSWORD = re.compile(r"Password:\s*$")


class CliError(Exception):
    """The CLI session failed or the controller did not answer as expected."""


class CliAuthError(CliError):
    """The controller rejected the user name or password."""


class CliTransport(Protocol):
    async def run(self, commands: list[str]) -> dict[str, str]:
        """Run `show` commands in one session and return their output keyed by command."""


class SshCli:
    """One short SSH session per call, so no session is left open on the controller."""

    def __init__(
        self, host: str, username: str, password: str, *, port: int = 22, timeout: float = 20
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout = timeout

    async def _read_until(self, reader: asyncssh.SSHReader[str], pattern: re.Pattern[str]) -> str:
        buf = ""
        while not pattern.search(buf):
            chunk = await reader.read(4096)
            if not chunk:
                raise CliError(f"{self._host}: session closed unexpectedly")
            buf += chunk
        return buf

    async def _session(self, commands: list[str]) -> dict[str, str]:
        # The controller's host key is self-signed and regenerated on reset: it cannot be pinned.
        async with asyncssh.connect(
            self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            known_hosts=None,
        ) as conn:
            writer, reader, _ = await conn.open_session(term_type="vt100", term_size=(250, 1000))
            # AireOS accepts the SSH login as-is and then asks for the credentials again in the shell
            banner = await self._read_until(reader, LOGIN_OR_PROMPT)
            if banner.rstrip().endswith("User:"):
                writer.write(self._username + "\n")
                await self._read_until(reader, PASSWORD)
                writer.write(self._password + "\n")
                answer = await self._read_until(reader, LOGIN_OR_PROMPT)
                if answer.rstrip().endswith("User:"):
                    raise CliAuthError(f"{self._host}: user name or password rejected")
            writer.write("config paging disable\n")  # session-local, changes no configuration
            await self._read_until(reader, PROMPT)

            output: dict[str, str] = {}
            for command in commands:
                writer.write(command + "\n")
                raw = await self._read_until(reader, PROMPT)
                lines = raw.replace("\r", "").split("\n")
                # drop the echoed command and the trailing prompt
                output[command] = "\n".join(lines[1:-1]).strip("\n") + "\n"
            writer.write("logout\n")
            return output

    async def run(self, commands: list[str]) -> dict[str, str]:
        for command in commands:
            if not command.startswith("show ") or "\n" in command or "\r" in command:
                raise CliError(f"refusing non-show command: {command!r}")
        try:
            return await asyncio.wait_for(self._session(commands), self._timeout)
        except asyncssh.PermissionDenied as err:
            raise CliAuthError(f"{self._host}: {err.reason}") from err
        except TimeoutError as err:
            raise CliError(f"{self._host}: no answer within {self._timeout:g} s") from err
        except (OSError, asyncssh.Error) as err:
            raise CliError(f"{self._host}: {err}") from err
