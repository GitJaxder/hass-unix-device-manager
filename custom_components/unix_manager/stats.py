"""Hardware statistics: the remote script and its parser (pure functions, no I/O)."""
from __future__ import annotations

from dataclasses import dataclass, field

# Linux only: everything comes from /proc, /sys and POSIX df, so it works on
# busybox systems too. Each source is optional; a missing one yields no line.
CPU_CMD = "sed -n 's/^cpu  *//p' /proc/stat | sed 's/^/cpu=/'\n"
STATS_CMD = CPU_CMD + r"""sed -n 's/^btime  *//p' /proc/stat | sed 's/^/btime=/'
[ -r /proc/loadavg ] && echo "load=$(cut -d' ' -f1-3 /proc/loadavg)"
awk '/^(MemTotal|MemAvailable|MemFree|Buffers|Cached|SwapTotal|SwapFree):/ {
  sub(":", "", $1); print "mem_" $1 "=" $2 }' /proc/meminfo 2>/dev/null
echo "disk=$(df -Pk / 2>/dev/null | tail -n 1)"
for z in /sys/class/thermal/thermal_zone*; do
  [ -r "$z/temp" ] && echo "tz=$(cat "$z/type" 2>/dev/null):$(cat "$z/temp" 2>/dev/null)"
done
for h in /sys/class/hwmon/hwmon*; do
  [ -r "$h/temp1_input" ] && echo "hw=$(cat "$h/name" 2>/dev/null):$(cat "$h/temp1_input" 2>/dev/null)"
done
true"""

# Thermal zone types and hwmon driver names that measure the CPU/SoC itself.
# Raspberry Pi reports "cpu-thermal"; Intel "x86_pkg_temp"/"coretemp"; AMD
# "k10temp". Anything else (e.g. "acpitz") is only used as a fallback.
_CPU_SENSOR_HINTS = ("cpu", "soc", "x86_pkg", "coretemp", "k10temp", "zenpower")


@dataclass
class UnixStats:
    """One hardware snapshot. None means the host doesn't expose that value."""

    cpu_usage: float | None = None
    cpu_temperature: float | None = None
    load: tuple[float, float, float] | None = None
    memory_total: int | None = None  # KiB
    memory_used: int | None = None  # KiB
    swap_total: int | None = None  # KiB
    swap_used: int | None = None  # KiB
    disk_total: int | None = None  # KiB, root filesystem
    disk_used: int | None = None  # KiB
    disk_free: int | None = None  # KiB available to unprivileged users
    boot_time: int | None = None  # unix epoch
    cpu_sample: tuple[int, int] | None = field(default=None, repr=False)

    @property
    def memory_usage(self) -> float | None:
        return _percent(self.memory_used, self.memory_total)

    @property
    def swap_usage(self) -> float | None:
        return _percent(self.swap_used, self.swap_total)

    @property
    def disk_usage(self) -> float | None:
        # Same as df's "Use%": reserved blocks count as neither used nor free.
        if self.disk_used is None or self.disk_free is None:
            return None
        return _percent(self.disk_used, self.disk_used + self.disk_free)


def _percent(part: int | None, whole: int | None) -> float | None:
    if part is None or not whole:
        return None
    return round(100 * part / whole, 1)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def cpu_sample(line: str) -> tuple[int, int] | None:
    """(busy, total) jiffies from the aggregate /proc/stat cpu line."""
    try:
        fields = [int(f) for f in line.split()]
    except ValueError:
        return None
    if len(fields) < 4:
        return None
    # user nice system idle iowait irq softirq steal; guest time is already
    # included in user/nice, so it is not added again.
    total = sum(fields[:8])
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return total - idle, total


def cpu_usage(
    before: tuple[int, int] | None, after: tuple[int, int] | None
) -> float | None:
    if before is None or after is None:
        return None
    busy, total = after[0] - before[0], after[1] - before[1]
    if total <= 0 or busy < 0:  # counters reset (reboot) or no time passed
        return None
    return round(100 * busy / total, 1)


def _pick_temperature(zones: list[tuple[str, str]], hwmons: list[tuple[str, str]]) -> float | None:
    readings: list[tuple[str, float]] = []
    for name, raw in zones + hwmons:
        milli = _int(raw)
        if milli is None:
            continue
        celsius = milli / 1000
        if -40 < celsius < 150 and milli != 0:  # skip unpopulated/bogus sensors
            readings.append((name.lower(), celsius))
    for name, celsius in readings:
        if any(hint in name for hint in _CPU_SENSOR_HINTS):
            return round(celsius, 1)
    return round(readings[0][1], 1) if readings else None


def parse_stats(out: str, previous_cpu: tuple[int, int] | None = None) -> UnixStats:
    """Parse STATS_CMD output.

    CPU usage is averaged since `previous_cpu` (the last poll). Without one,
    the output must hold two cpu lines taken a moment apart.
    """
    stats = UnixStats()
    cpu_lines: list[str] = []
    zones: list[tuple[str, str]] = []
    hwmons: list[tuple[str, str]] = []
    mem: dict[str, int] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if key == "cpu":
            cpu_lines.append(value)
        elif key == "btime":
            stats.boot_time = _int(value)
        elif key == "load":
            try:
                one, five, fifteen = (float(v) for v in value.split())
                stats.load = (one, five, fifteen)
            except ValueError:
                pass
        elif key.startswith("mem_"):
            if (kib := _int(value)) is not None:
                mem[key[4:]] = kib
        elif key == "disk":
            # Filesystem 1024-blocks Used Available Capacity Mounted-on
            cols = value.split()
            if len(cols) >= 6:
                stats.disk_total = _int(cols[1])
                stats.disk_used = _int(cols[2])
                stats.disk_free = _int(cols[3])
        elif key in ("tz", "hw"):
            name, _, raw = value.rpartition(":")
            (zones if key == "tz" else hwmons).append((name, raw))

    samples = [s for s in map(cpu_sample, cpu_lines) if s is not None]
    if samples:
        stats.cpu_sample = samples[-1]
        before = previous_cpu if previous_cpu is not None else (
            samples[0] if len(samples) > 1 else None
        )
        stats.cpu_usage = cpu_usage(before, samples[-1])

    if total := mem.get("MemTotal"):
        available = mem.get("MemAvailable")
        if available is None:  # kernels before 3.14
            available = mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0)
        stats.memory_total = total
        stats.memory_used = max(total - available, 0)
    if swap := mem.get("SwapTotal"):
        stats.swap_total = swap
        stats.swap_used = max(swap - mem.get("SwapFree", swap), 0)

    stats.cpu_temperature = _pick_temperature(zones, hwmons)
    return stats
