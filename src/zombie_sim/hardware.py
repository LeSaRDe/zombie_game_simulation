"""Discover the resources actually available to this process, without dependencies.

Logical CPU counts alone overlook affinity, containers, and memory limits. These
limits select compute capacity; they never change model time or event ordering.
"""
from __future__ import annotations

import math
import os
from pathlib import Path


def _text(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return None


def _positive(value):
    try:
        result = int(value)
        return result if 0 < result < (1 << 60) else None
    except (ValueError, TypeError):
        return None


def _cgroup_directories():
    """Include every ancestor: a child cannot exceed an ancestor's quota."""
    root = Path("/sys/fs/cgroup")
    result = {root}
    for line in (_text("/proc/self/cgroup") or "").splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        controllers, location = fields[1:]
        # Common cgroup v1 mounts combine controllers as "cpu,cpuacct".
        # Inspect that mount as well as individually mounted controllers.
        bases = [root] if not controllers else [root / name for name in {controllers, *controllers.split(",")}]
        for base in bases:
            directory = base / location.lstrip("/")
            while directory == base or base in directory.parents:
                result.add(directory)
                if directory == base:
                    break
                directory = directory.parent
    return sorted(result, key=str)


def available_resources():
    logical = os.cpu_count() or 1
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = logical
    capacity = float(min(logical, affinity))
    memory = None
    for line in (_text("/proc/meminfo") or "").splitlines():
        if line.startswith("MemAvailable:"):
            memory = int(line.split()[1]) * 1024
            break
    if memory is None:
        try:
            memory = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            memory = 2 * 1024**3
    limits = []
    for directory in _cgroup_directories():
        quota = _text(directory / "cpu.max")
        if quota:
            parts = quota.split()
            if len(parts) == 2 and _positive(parts[0]) and _positive(parts[1]):
                capacity = min(capacity, int(parts[0]) / int(parts[1]))
                limits.append(str(directory / "cpu.max"))
        else:
            quota = _positive(_text(directory / "cpu.cfs_quota_us"))
            period = _positive(_text(directory / "cpu.cfs_period_us"))
            if quota and period:
                capacity = min(capacity, quota / period)
                limits.append(str(directory / "cpu.cfs_quota_us"))
        ceiling = _positive(_text(directory / "memory.max")) or _positive(_text(directory / "memory.limit_in_bytes"))
        if ceiling:
            used = _positive(_text(directory / "memory.current")) or _positive(_text(directory / "memory.usage_in_bytes")) or 0
            memory = min(memory, max(0, ceiling - used))
            limits.append(str(directory / "memory.max"))
    return {"logical_cpus": logical, "affinity_cpus": affinity,
            "cpu_capacity": max(0.01, capacity), "available_memory_bytes": memory,
            "limit_sources": sorted(set(limits))}


def worker_budget(requested="auto", *, population=None, resources=None, concurrent_runs=1):
    """Resolve an explicit count or auto budget, including nested run pools.

    Auto reserves one logical CPU for the coordinator when possible. Explicit
    requests may use all available logical CPUs, but never exceed memory/CPU
    limits or the number of agents. A one-worker run executes in its coordinator.
    """
    if requested is None:
        requested = "auto"
    if requested != "auto" and (isinstance(requested, bool) or not isinstance(requested, int) or requested < 1):
        raise ValueError("workers must be a positive integer or 'auto'")
    if isinstance(concurrent_runs, bool) or not isinstance(concurrent_runs, int) or concurrent_runs < 1:
        raise ValueError("concurrent_runs must be positive")
    detected = dict(resources or available_resources())
    cpu_limit = max(1, math.ceil(detected["cpu_capacity"] / concurrent_runs))
    # Leave room for the coordinator, cached state, and OS/file-cache pressure.
    usable = max(0, int(detected["available_memory_bytes"] * .75) // concurrent_runs - 128 * 1024**2)
    memory_limit = max(1, usable // (192 * 1024**2))
    limit = min(cpu_limit, memory_limit)
    if population is not None:
        limit = min(limit, max(1, int(population)))
    automatic = max(1, cpu_limit - 1)
    workers = min(limit, automatic if requested == "auto" else requested)
    return {**detected, "requested_workers": requested, "workers": workers,
            "cpu_worker_limit": cpu_limit, "memory_worker_limit": memory_limit,
            "concurrent_runs": concurrent_runs, "auto_coordinator_reserve": int(requested == "auto" and cpu_limit > 1)}
