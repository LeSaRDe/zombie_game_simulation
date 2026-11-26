"""Read-only progress/resource samples for one explicitly named acceptance ledger."""
from __future__ import annotations
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time


def read_text(path):
    try: return Path(path).read_text().strip()
    except OSError: return None


def resource_scope(pid):
    cgroup = read_text(f"/proc/{pid}/cgroup") or ""
    directories = {Path("/sys/fs/cgroup")}
    for line in cgroup.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3: continue
        controllers, location = fields[1:]
        bases = [Path("/sys/fs/cgroup")] if not controllers else [Path("/sys/fs/cgroup") / key for key in {controllers, *controllers.split(",")}]
        for base in bases:
            directory = base / location.lstrip("/")
            while directory == base or base in directory.parents:
                directories.add(directory)
                if directory == base: break
                directory = directory.parent
    limits = {}
    for directory in directories:
        for name in ("cpu.max", "cpu.stat", "cpu.cfs_quota_us", "cpu.cfs_period_us", "memory.max", "memory.current"):
            value = read_text(directory / name)
            if value is not None: limits[str(directory / name)] = value
    return {"cgroup": cgroup, "affinity": sorted(os.sched_getaffinity(pid)), "visible_limits": limits,
            "cgroup_mounts": [line for line in (read_text(f"/proc/{pid}/mountinfo") or "").splitlines() if " - cgroup" in line]}


def processes_for(ledger):
    result = subprocess.run(["fuser", str(ledger)], capture_output=True, text=True)
    owners = {int(value) for value in result.stdout.split() if value.isdecimal()}
    pending = list(owners); seen = set(); rows = []
    while pending:
        pid = pending.pop()
        if pid in seen: continue
        seen.add(pid)
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            pending.extend(int(child) for child in children)
            row = {"pid": pid, "coordinator": pid in owners,
                         "cpu_seconds": (int(fields[11])+int(fields[12]))/os.sysconf("SC_CLK_TCK"),
                         "rss_bytes": int(fields[21])*os.sysconf("SC_PAGE_SIZE"),
                         "wait_channel": read_text(f"/proc/{pid}/wchan"),
                         "schedstat": read_text(f"/proc/{pid}/schedstat"),
                         "io": read_text(f"/proc/{pid}/io")}
            if pid in owners: row["resource_scope"] = resource_scope(pid)
            rows.append(row)
        except (OSError, ValueError, IndexError):
            continue
    return sorted(rows, key=lambda row: row["pid"])


def sample(ledger):
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    files = [ledger, Path(str(ledger)+"-wal")]
    filesystem = os.statvfs(ledger.parent)
    available = next((int(line.split()[1])*1024 for line in (read_text("/proc/meminfo") or "").splitlines()
                      if line.startswith("MemAvailable:")), None)
    return {"wall_time": time.time(), "revision": row[0], "time": str(Fraction(int(row[1]), int(row[2]))),
            "seconds": float(Fraction(int(row[1]), int(row[2]))),
            "ledger_bytes": sum(path.stat().st_size for path in files if path.exists()),
            "run_files_bytes": sum(path.stat().st_size for path in ledger.parent.rglob("*") if path.is_file()),
            "scratch_available_bytes": filesystem.f_bavail*filesystem.f_frsize,
            "host_mem_available_bytes": available,
            "processes": processes_for(ledger)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--samples", type=int, default=360)
    arguments = parser.parse_args()
    if arguments.interval <= 0 or arguments.samples < 1:
        parser.error("positive interval and sample count required")
    for index in range(arguments.samples):
        if not arguments.ledger.exists():
            print(json.dumps({"wall_time": time.time(), "status": "ledger_removed"}), flush=True)
            break
        print(json.dumps(sample(arguments.ledger)), flush=True)
        if index+1 < arguments.samples: time.sleep(arguments.interval)
