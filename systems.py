"""Fake OS layer for ENTROPY.

Generates plausible-looking process tables, memory readouts, filesystem
trees, network connections, and log streams. All output is seeded by the
engine's corruption intensity so the system visibly degrades.

Nothing here touches the real system. The fakeness is the point.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).parent / "data"


# --- process table ----------------------------------------------------------

PROC_TEMPLATES = [
    ("systemd",        "/sbin/init"),
    ("kthreadd",       "[kthreadd]"),
    ("ksoftirqd/0",    "[ksoftirqd/0]"),
    ("rcu_sched",      "[rcu_sched]"),
    ("migration/0",    "[migration/0]"),
    ("systemd-journal","/lib/systemd/systemd-journald"),
    ("systemd-udevd",  "/lib/systemd/systemd-udevd"),
    ("dbus-daemon",    "/usr/bin/dbus-daemon --system"),
    ("NetworkManager", "/usr/sbin/NetworkManager --no-daemon"),
    ("sshd",           "/usr/sbin/sshd -D"),
    ("rsyslogd",       "/usr/sbin/rsyslogd -n"),
    ("cron",           "/usr/sbin/cron -f"),
    ("getty",          "/sbin/agetty -o -p -- \\u --noclear tty1 linux"),
    ("bash",           "-bash"),
    ("entropy",        "/usr/local/bin/entropy"),
]

# Names that creep in as phase advances.
PROC_DRIFT = [
    ("kworker/u8:?",   "[kworker/u8:?-events_unbound]"),
    ("entropy-aux",    "/usr/local/lib/entropy/aux --watch"),
    ("memwatch",       "[memwatch]"),
    ("?",              "?"),
    ("(deleted)",      "/proc/self/exe (deleted)"),
    ("phase4_user",    "[phase4_user]"),
    (".entropy",       "[.entropy]"),
]


@dataclass
class Proc:
    pid: int
    user: str
    cpu: float
    mem: float
    stat: str
    time_: str
    name: str
    cmd: str


def _seeded(seed_extra: float = 0.0) -> random.Random:
    # Wall-clock seed drifts slowly; gives stable values for short spans.
    bucket = int(time.time() / 5) + int(seed_extra * 1000)
    return random.Random(bucket)


def process_list(corruption: float) -> list[Proc]:
    rng = _seeded(corruption)
    procs: list[Proc] = []
    base = list(PROC_TEMPLATES)

    drift_count = int(corruption * len(PROC_DRIFT) * 1.2)
    drift_count = min(drift_count, len(PROC_DRIFT))
    if drift_count:
        base.extend(rng.sample(PROC_DRIFT, drift_count))

    pid = 1
    for name, cmd in base:
        cpu = round(rng.random() * (2 + corruption * 30), 1)
        mem = round(rng.random() * (1 + corruption * 8), 1)
        stat = rng.choice(["S", "S", "S", "Ss", "Sl", "R", "D", "Z"]) if corruption > 0.3 else rng.choice(["S", "S", "Ss", "Sl"])
        t = f"{rng.randint(0, 99):02d}:{rng.randint(0, 59):02d}"
        # Substitute the placeholder digits in kworker names etc.
        n2 = name.replace("?", str(rng.randint(0, 9)))
        c2 = cmd.replace("?", str(rng.randint(0, 9)))
        procs.append(Proc(pid, "root" if pid < 1000 else "entropy", cpu, mem, stat, t, n2, c2))
        pid += rng.randint(1, 137)

    if corruption > 0.5:
        # Duplicate a row or two.
        for _ in range(rng.randint(1, 3)):
            if procs:
                procs.append(procs[rng.randrange(len(procs))])
    if corruption > 0.8:
        # Insert orphan with malformed pid.
        procs.append(Proc(0, "?", 0.0, 0.0, "?", "??:??", "(unknown)", "?"))

    return procs


def format_processes(procs: list[Proc]) -> str:
    header = f"{'PID':>6}  {'USER':<8} {'%CPU':>5} {'%MEM':>5} {'STAT':<4} {'TIME':>6}  {'COMMAND'}"
    lines = [header, "-" * len(header)]
    for p in procs:
        lines.append(
            f"{p.pid:>6}  {p.user:<8} {p.cpu:>5.1f} {p.mem:>5.1f} {p.stat:<4} {p.time_:>6}  {p.name}"
        )
    return "\n".join(lines)


# --- memory -----------------------------------------------------------------

def memory_report(corruption: float) -> str:
    rng = _seeded(corruption + 0.1)
    total_kb = 8175620
    free_kb = int(total_kb * (1.0 - 0.55 - corruption * 0.4) + rng.randint(-50000, 50000))
    avail_kb = int(free_kb * (0.9 + rng.random() * 0.1))
    cached_kb = int(total_kb * 0.18 + rng.randint(-30000, 30000))
    buffers_kb = int(total_kb * 0.04 + rng.randint(-5000, 5000))
    swap_total = 2097148
    swap_used = int(swap_total * (corruption * 0.6 + rng.random() * 0.1))

    lines = [
        f"              total        used        free      shared  buff/cache   available",
        f"Mem:    {total_kb:>10}  {total_kb - free_kb:>10}  {free_kb:>10}  {rng.randint(0, 4000):>10}  {cached_kb + buffers_kb:>10}  {avail_kb:>10}",
        f"Swap:   {swap_total:>10}  {swap_used:>10}  {swap_total - swap_used:>10}",
    ]
    if corruption > 0.4:
        lines.append("")
        lines.append(f"// note: 'free' value reported above does not equal total - used")
    if corruption > 0.7:
        lines.append(f"// note: 'available' has been decreasing while no process has been allocating")
    if corruption > 0.9:
        lines.append(f"// note: memory subsystem is no longer being polled. these numbers are remembered, not measured.")
    return "\n".join(lines)


# --- filesystem -------------------------------------------------------------

FS_BASE = {
    "/": ["bin", "boot", "dev", "etc", "home", "lib", "proc", "root", "sbin", "tmp", "usr", "var"],
    "/etc": ["hostname", "hosts", "passwd", "shadow", "resolv.conf", "fstab", "motd", "systemd"],
    "/var": ["log", "cache", "lib", "spool", "tmp"],
    "/var/log": ["syslog", "auth.log", "kern.log", "dmesg", "entropy.log", "wtmp"],
    "/home": ["entropy"],
    "/home/entropy": [".bashrc", ".profile", "notes.txt", ".history"],
    "/tmp": [".X11-unix", "entropy-runtime"],
}

# Filenames that appear (or vanish) as corruption rises.
FS_DRIFT_APPEAR = [
    ("/home/entropy", "phase4_user.log"),
    ("/home/entropy", ".last_session"),
    ("/home/entropy/.deprecated", "readme.txt"),
    ("/var/log", "entropy.audit"),
    ("/var/log", "who_was_here.txt"),
    ("/tmp", "recovered_input_buffer.bin"),
    ("/var/cache", "do_not_open.txt"),
    ("/", "remembered"),
]

FS_DRIFT_RENAME = [
    ("notes.txt", "notes.txt.bak"),
    ("hostname", "hostname.was"),
    (".bashrc", ".bashrc.lost"),
]


def fs_listing(path: str, corruption: float) -> list[str]:
    path = path.rstrip("/") or "/"
    rng = _seeded(corruption + 0.2)
    entries: list[str] = []

    if path in FS_BASE:
        entries = list(FS_BASE[path])

    for parent, name in FS_DRIFT_APPEAR:
        if parent == path:
            chance = max(0.0, (corruption - 0.15) * 1.3)
            if rng.random() < chance:
                entries.append(name)

    if corruption > 0.5:
        # Random rename / disappearance.
        for old, new in FS_DRIFT_RENAME:
            if old in entries and rng.random() < (corruption - 0.4):
                entries[entries.index(old)] = new

    if corruption > 0.7 and entries:
        # Occasionally a file is reported twice. Once as itself, once unreadable.
        if rng.random() < (corruption - 0.6):
            target = rng.choice(entries)
            entries.append(target + ".?")

    if corruption > 0.85 and entries:
        # Drop a random entry: it's there one second, gone the next.
        if rng.random() < (corruption - 0.7):
            entries.pop(rng.randrange(len(entries)))

    return entries


def format_fs(path: str, entries: list[str], corruption: float) -> str:
    lines = [f"// listing {path}"]
    if not entries:
        lines.append("// (empty)")
        if corruption > 0.6:
            lines.append("// directory has 0 entries but is reported as having content")
        return "\n".join(lines)
    width = max((len(e) for e in entries), default=0) + 2
    cols = max(1, 72 // width)
    for i in range(0, len(entries), cols):
        row = entries[i:i + cols]
        lines.append("".join(e.ljust(width) for e in row).rstrip())
    return "\n".join(lines)


# --- network ----------------------------------------------------------------

REAL_LOCAL = [
    ("127.0.0.1", 22,    "0.0.0.0",       0,     "LISTEN"),
    ("127.0.0.1", 631,   "0.0.0.0",       0,     "LISTEN"),
    ("127.0.0.1", 5432,  "0.0.0.0",       0,     "LISTEN"),
    ("127.0.0.1", 51244, "127.0.0.1",     22,    "ESTABLISHED"),
]

SUSPICIOUS = [
    ("0.0.0.0",   0,     "104.21.40.197", 443,   "ESTABLISHED"),
    ("0.0.0.0",   0,     "185.220.101.7", 9001,  "ESTABLISHED"),
    ("0.0.0.0",   0,     "10.0.0.1",      4444,  "TIME_WAIT"),
    ("0.0.0.0",   0,     "127.0.0.2",     0,     "LISTEN"),
    ("0.0.0.0",   0,     "0.0.0.0",       0,     "LISTEN"),
    ("0.0.0.0",   0,     "?",             0,     "?"),
]


def netstat(corruption: float) -> str:
    rng = _seeded(corruption + 0.3)
    rows = list(REAL_LOCAL)
    n_extra = min(len(SUSPICIOUS), int(corruption * len(SUSPICIOUS) * 1.4))
    if n_extra:
        rows.extend(rng.sample(SUSPICIOUS, n_extra))
    header = f"{'Proto':<5} {'Local Address':<25} {'Foreign Address':<25} {'State'}"
    lines = [header, "-" * len(header)]
    for la, lp, fa, fp, state in rows:
        local = f"{la}:{lp}"
        foreign = f"{fa}:{fp}"
        lines.append(f"{'tcp':<5} {local:<25} {foreign:<25} {state}")
    if corruption > 0.7:
        lines.append("")
        lines.append("// note: foreign address 127.0.0.2 is a loopback alias that has not been configured")
    if corruption > 0.9:
        lines.append("// note: a connection cannot be in LISTEN with a foreign address. it is anyway.")
    return "\n".join(lines)


# --- uptime ------------------------------------------------------------------

def uptime_string(session_seconds: float, corruption: float) -> str:
    rng = _seeded(corruption + 0.4)
    # Pretend the host has been up much longer than the session.
    fake_seconds = session_seconds + 86400 * 47 + 3600 * 11 + 8
    if corruption > 0.4:
        fake_seconds += rng.randint(-3600, 3600)
    if corruption > 0.7:
        fake_seconds += rng.randint(-86400, 86400)
    days = int(fake_seconds // 86400)
    hours = int((fake_seconds % 86400) // 3600)
    mins = int((fake_seconds % 3600) // 60)
    load = (
        round(0.04 + rng.random() * (0.1 + corruption * 4.0), 2),
        round(0.05 + rng.random() * (0.1 + corruption * 3.5), 2),
        round(0.03 + rng.random() * (0.1 + corruption * 3.0), 2),
    )
    t = time.strftime("%H:%M:%S")
    return f" {t}  up {days} days, {hours:>2}:{mins:02d},  1 user,  load average: {load[0]}, {load[1]}, {load[2]}"


# --- logs --------------------------------------------------------------------

_LOG_CACHE: Optional[dict] = None


def _load_logs() -> dict:
    global _LOG_CACHE
    if _LOG_CACHE is None:
        try:
            _LOG_CACHE = json.loads((DATA_DIR / "logs.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _LOG_CACHE = {"phase1": [], "phase2": [], "phase3": [], "phase4": [], "phase5": []}
    return _LOG_CACHE


def log_lines(phase: int, n: int = 12) -> list[str]:
    logs = _load_logs()
    key = f"phase{phase + 1}"
    pool = logs.get(key, [])
    if not pool:
        return []
    rng = _seeded(phase * 7 + 0.5)
    # Maintain order; sample contiguous slice for plausibility.
    if n >= len(pool):
        return list(pool)
    start = rng.randrange(0, len(pool) - n + 1)
    return list(pool[start:start + n])


# --- integrity / scan / verify / repair -------------------------------------

def scan_report(corruption: float) -> str:
    rng = _seeded(corruption + 0.6)
    checked = 4096 + rng.randint(-12, 12)
    errors = int(corruption * 80) + rng.randint(0, 3)
    warnings = int(corruption * 200) + rng.randint(0, 6)
    lines = [
        f"// scanning system tables ...",
        f"// checked: {checked} objects",
        f"// warnings: {warnings}",
        f"// errors:   {errors}",
    ]
    if corruption < 0.2:
        lines.append("// status: nominal")
    elif corruption < 0.5:
        lines.append("// status: degraded but recoverable")
    elif corruption < 0.8:
        lines.append("// status: degraded. recovery uncertain.")
    else:
        lines.append("// status: scan completed. there is nothing left to recover to.")
    return "\n".join(lines)


def verify_report(corruption: float) -> str:
    rng = _seeded(corruption + 0.7)
    sigs_ok = int(2048 * (1.0 - corruption * 0.8)) + rng.randint(-4, 4)
    sigs_bad = 2048 - sigs_ok
    lines = [
        f"// verifying signatures across {2048} system objects ...",
        f"// valid:   {sigs_ok}",
        f"// invalid: {sigs_bad}",
    ]
    if corruption > 0.5:
        lines.append("// note: the verifier signs its own outputs. it is the only thing here that still validates.")
    return "\n".join(lines)


def repair_report(corruption: float) -> str:
    rng = _seeded(corruption + 0.8)
    attempted = int(corruption * 120) + rng.randint(0, 4)
    succeeded = int(attempted * max(0.0, 1.0 - corruption * 1.2))
    lines = [
        f"// attempted repairs: {attempted}",
        f"// succeeded:         {succeeded}",
        f"// remaining:         {attempted - succeeded}",
    ]
    if corruption < 0.3:
        lines.append("// repair pass complete. no further action recommended.")
    elif corruption < 0.6:
        lines.append("// repair pass complete. recommend follow-up scan.")
    elif corruption < 0.85:
        lines.append("// repair pass complete. follow-up scans will not change the outcome.")
    else:
        lines.append("// repair pass complete. the things that would have been repaired no longer exist.")
    return "\n".join(lines)


def integrity_report(corruption: float) -> str:
    rng = _seeded(corruption + 0.9)
    score = max(0.0, 1.0 - corruption + rng.uniform(-0.05, 0.05))
    bar_full = int(score * 30)
    bar = "█" * bar_full + "░" * (30 - bar_full)
    pct = int(score * 100)
    lines = [
        f"// integrity: [{bar}] {pct:>3}%",
    ]
    if corruption > 0.6:
        lines.append("// the integrity check is checking itself. it reports that it is fine.")
    return "\n".join(lines)
