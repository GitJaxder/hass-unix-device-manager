"""SSH client and package-manager abstraction."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import shlex

import asyncssh

from .discovery import (
    ADDR_CMD,
    FACTS_CMD,
    clean_mac,
    identity_from_facts,
    parse_facts,
    pick_interface,
)

CONNECT_TIMEOUT = 15
QUERY_TIMEOUT = 300
REFRESH_TIMEOUT = 900
UPGRADE_TIMEOUT = 3600

# Non-interactive SSH sessions often lack the sbin dirs.
PATH_FIX = "PATH=$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/sbin; export PATH; "
DETECT_CMD = (
    "for c in apt-get dnf yum apk pacman zypper; do "
    "command -v $c >/dev/null 2>&1 && echo $c && break; done"
)


class UnixError(Exception):
    """Base error."""


class CannotConnect(UnixError):
    """Host unreachable or SSH failure."""


class InvalidAuth(UnixError):
    """Credentials rejected."""


class UnsupportedSystem(UnixError):
    """No supported package manager found."""


class CommandFailed(UnixError):
    """Remote command failed."""


# --- package manager definitions -------------------------------------------------

def _parse_apt(out: str) -> list[str]:
    return [l.split("/", 1)[0] for l in out.splitlines() if "/" in l and "[upgradable" in l]


def _parse_dnf(out: str) -> list[str]:
    pkgs: list[str] = []
    for line in out.splitlines():
        if line.startswith("Obsoleting"):
            break
        parts = line.split()
        if len(parts) == 3 and "." in parts[0]:
            pkgs.append(parts[0].rsplit(".", 1)[0])
    return pkgs


def _parse_apk(out: str) -> list[str]:
    return [l.split()[0] for l in out.splitlines() if " < " in l]


def _parse_pacman(out: str) -> list[str]:
    return [l.split()[0] for l in out.splitlines() if " -> " in l]


def _parse_zypper(out: str) -> list[str]:
    pkgs: list[str] = []
    for line in out.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 5 and cols[0] == "v":
            pkgs.append(cols[2])
    return pkgs


@dataclass(frozen=True)
class PackageManager:
    """Commands for one package manager. '{sudo}' is replaced at run time."""

    name: str
    list_cmd: str
    parse: Callable[[str], list[str]]
    refresh_cmd: str
    upgrade_cmd: str
    list_ok: tuple[int, ...] = (0,)
    refresh_ok: tuple[int, ...] = (0,)


PACKAGE_MANAGERS: dict[str, PackageManager] = {
    "apt-get": PackageManager(
        "apt",
        "apt list --upgradable 2>/dev/null",
        _parse_apt,
        "{sudo}apt-get -q update",
        "{sudo}env DEBIAN_FRONTEND=noninteractive apt-get -y -q "
        "-o Dpkg::Options::=--force-confold upgrade",
    ),
    "dnf": PackageManager(
        "dnf", "dnf -q check-update", _parse_dnf,
        "{sudo}dnf -y makecache", "{sudo}dnf -y upgrade", list_ok=(0, 100),
    ),
    "yum": PackageManager(
        "yum", "yum -q check-update", _parse_dnf,
        "{sudo}yum -y makecache", "{sudo}yum -y upgrade", list_ok=(0, 100),
    ),
    "apk": PackageManager(
        "apk", "apk version -l '<'", _parse_apk,
        "{sudo}apk update", "{sudo}apk upgrade",
    ),
    # checkupdates (pacman-contrib) syncs a temp DB, so we never do a partial
    # `pacman -Sy`. Exit 2 means "no updates".
    "pacman": PackageManager(
        "pacman", "checkupdates", _parse_pacman,
        "checkupdates", "{sudo}pacman -Syu --noconfirm",
        list_ok=(0, 2), refresh_ok=(0, 2),
    ),
    "zypper": PackageManager(
        "zypper", "zypper --non-interactive -q list-updates", _parse_zypper,
        "{sudo}zypper --non-interactive refresh",
        "{sudo}zypper --non-interactive update",
    ),
}


@dataclass
class UnixData:
    """Snapshot returned by a poll."""

    os_version: str
    package_manager: str
    updates: list[str]
    architecture: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    mac_address: str | None = None
    ip_address: str | None = None


def load_key(path: str) -> asyncssh.SSHKey:
    """Load an (unencrypted) private key. Blocking - run in an executor."""
    return asyncssh.read_private_key(path)


def _detached(cmd: str) -> str:
    """Run under nohup with output to a temp file so a dropped SSH session
    can't kill a package manager half-way through a transaction."""
    return (
        f'LOG=$(mktemp); nohup {cmd} >"$LOG" 2>&1; rc=$?; '
        'tail -n 20 "$LOG"; rm -f "$LOG"; exit $rc'
    )


class UnixClient:
    """Talks to one remote unix host over SSH."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        client_key: asyncssh.SSHKey | None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key = client_key
        self._lock = asyncio.Lock()  # one operation at a time per host
        self._pm: PackageManager | None = None

    def _render(self, template: str) -> str:
        return template.replace("{sudo}", "" if self._username == "root" else "sudo -n ")

    @asynccontextmanager
    async def _connect(self):
        try:
            async with asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                client_keys=[self._key] if self._key else None,
                known_hosts=None,  # TODO: host-key pinning
                config=None,
                connect_timeout=CONNECT_TIMEOUT,
            ) as conn:
                yield conn
        except asyncssh.PermissionDenied as err:
            raise InvalidAuth(str(err)) from err
        except (OSError, asyncssh.Error, asyncio.TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def _run(
        self,
        conn: asyncssh.SSHClientConnection,
        script: str,
        *,
        ok: tuple[int, ...] = (0,),
        timeout: int = QUERY_TIMEOUT,
    ) -> str:
        # `sh -c` so it works regardless of the login shell (fish, csh, ...).
        full = f"sh -c {shlex.quote(PATH_FIX + script)}"
        try:
            res = await conn.run(full, check=False, timeout=timeout)
        except (asyncssh.TimeoutError, asyncio.TimeoutError) as err:
            raise CommandFailed("command timed out") from err
        if res.exit_status not in ok:
            tail = str(res.stderr or res.stdout or "").strip()[-300:]
            raise CommandFailed(f"exit {res.exit_status}: {tail}")
        return str(res.stdout or "")

    async def _package_manager(self, conn) -> PackageManager:
        if self._pm is None:
            found = (await self._run(conn, DETECT_CMD)).strip()
            if found not in PACKAGE_MANAGERS:
                raise UnsupportedSystem("no supported package manager found")
            self._pm = PACKAGE_MANAGERS[found]
        return self._pm

    async def _identity(self, conn) -> dict[str, str | None]:
        """OS, hardware and network facts about the host."""
        info = identity_from_facts(parse_facts(await self._run(conn, FACTS_CMD)))
        info["mac_address"] = info["ip_address"] = None
        try:  # network details are best-effort (minimal systems may lack `ip`)
            peer = (conn.get_extra_info("peername") or ("",))[0]
            iface, ip = pick_interface(await self._run(conn, ADDR_CMD), peer)
            info["ip_address"] = ip
            if iface:
                path = shlex.quote(f"/sys/class/net/{iface}/address")
                info["mac_address"] = clean_mac(
                    await self._run(conn, f"cat {path} 2>/dev/null; true")
                )
        except CommandFailed:
            pass
        return info

    async def async_validate(self) -> str:
        """Connect, detect the package manager, return the OS version."""
        async with self._connect() as conn:
            await self._package_manager(conn)
            return (await self._identity(conn))["os_version"]

    async def async_poll(self) -> UnixData:
        async with self._lock, self._connect() as conn:
            pm = await self._package_manager(conn)
            identity = await self._identity(conn)
            out = await self._run(conn, self._render(pm.list_cmd), ok=pm.list_ok)
            return UnixData(
                package_manager=pm.name,
                updates=sorted(set(pm.parse(out))),
                **identity,
            )

    async def async_refresh_repositories(self) -> None:
        async with self._lock, self._connect() as conn:
            pm = await self._package_manager(conn)
            await self._run(
                conn, _detached(self._render(pm.refresh_cmd)),
                ok=pm.refresh_ok, timeout=REFRESH_TIMEOUT,
            )

    async def async_upgrade(self) -> None:
        async with self._lock, self._connect() as conn:
            pm = await self._package_manager(conn)
            await self._run(
                conn, _detached(self._render(pm.upgrade_cmd)), timeout=UPGRADE_TIMEOUT
            )
