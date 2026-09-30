"""Hardware and network discovery helpers (pure functions, no I/O)."""
from __future__ import annotations

import re

# Runs under `sh` and emits key=value lines. DMI covers x86 and VMs;
# device-tree covers Raspberry Pi and most other ARM boards.
FACTS_CMD = r"""[ -r /etc/os-release ] && . /etc/os-release
echo "os=${PRETTY_NAME:-$(uname -sr)}"
echo "arch=$(uname -m)"
if [ -r /sys/class/dmi/id/product_name ]; then
  echo "vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null)"
  echo "model=$(cat /sys/class/dmi/id/product_name 2>/dev/null)"
elif [ -r /proc/device-tree/model ]; then
  echo "model=$(tr -d '\000' </proc/device-tree/model)"
fi
true"""

# Trailing `true` so a missing `ip` binary yields empty output, not an error.
ADDR_CMD = "ip -o -4 addr show scope global 2>/dev/null; true"

_JUNK = frozenset(
    {
        "", "to be filled by o.e.m.", "o.e.m.", "system product name",
        "system manufacturer", "default string", "not specified",
        "unknown", "none", "n/a", "type1productconfigid",
    }
)
_ADDR_RE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/")
_MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_VIRTUAL_PREFIXES = (
    "docker", "br-", "veth", "virbr", "cni", "flannel", "cali",
    "tun", "tap", "wg", "tailscale", "zt",
)


def clean(value: str | None) -> str | None:
    """Drop placeholder strings that firmware vendors leave in DMI fields."""
    if value is None:
        return None
    value = value.strip()
    return None if value.lower() in _JUNK else value


def parse_facts(out: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            facts[key.strip()] = value.strip()
    return facts


def identity_from_facts(facts: dict[str, str]) -> dict[str, str | None]:
    vendor = clean(facts.get("vendor"))
    model = clean(facts.get("model"))
    if vendor is None and model and model.startswith("Raspberry Pi"):
        vendor = "Raspberry Pi"
    return {
        "os_version": facts.get("os") or "unknown",
        "architecture": clean(facts.get("arch")),
        "manufacturer": vendor,
        "model": model,
    }


def pick_interface(addr_output: str, peer: str) -> tuple[str | None, str | None]:
    """Choose the interface/IP we are reaching the host on.

    Prefer the address equal to the SSH peer; otherwise the first address that
    isn't a container/VPN/bridge interface.
    """
    candidates = [
        (m.group(1), m.group(2))
        for line in addr_output.splitlines()
        if (m := _ADDR_RE.match(line))
    ]
    for iface, ip in candidates:
        if ip == peer:
            return iface, ip
    for iface, ip in candidates:
        if iface != "lo" and not iface.startswith(_VIRTUAL_PREFIXES):
            return iface, ip
    return candidates[0] if candidates else (None, None)


def clean_mac(value: str) -> str | None:
    value = value.strip().lower()
    if _MAC_RE.match(value) and value != "00:00:00:00:00:00":
        return value
    return None
