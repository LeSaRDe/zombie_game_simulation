"""Frozen pre-I06 sampler for the independent before/after work comparison.

Only the original sampler and its required imports/cache globals are retained.
Projection and aggregate helpers are shared unchanged with the current product.
The function body below is byte-for-byte the saved pre-I06 source.
"""
from __future__ import annotations

import threading
from zombie_sim.storage import exact_time
from zombie_sim.visualization import VERSION, populations, project_state, resources

# Original src/zombie_sim/visualization.py SHA-256: 308c1e0b1fbd1c6cd07f0fb88e8e1f37bc4ecb41e1c4132510b7366a446fa845
# Original sampled_metrics function SHA-256: a4e46c8e2530d651446509eaf6938fdc249bfc8473da9041b7d95955a6f684c2
_metric_cache = {}
_metric_lock = threading.RLock()


def sampled_metrics(history, end=None, interval=1, limit=2000, revision=None):
    revision = history.revision if revision is None else int(revision)
    last = history.state_at(revision=revision)
    frontier = exact_time(last.get("time", 0))
    duration = frontier if end is None else exact_time(end)
    committed_time = exact_time(history.state_at().get("time", 0))
    if duration < 0 or duration > committed_time:
        raise ValueError("Metric time must lie within the committed history")
    interval = exact_time(interval)
    if interval <= 0:
        raise ValueError("Metric sample interval must be positive")
    spacing = max(interval, duration / max(1, limit))
    cache_key = (str(history.path) if history.path else id(history.connection), str(spacing))
    with _metric_lock:
        entry = _metric_cache.setdefault(cache_key, {"samples": [], "revision": -1, "frontier": 0})
        cache = entry["samples"]
        if entry["revision"] != revision:
            boundary = min(frontier, exact_time(entry["frontier"]))
            cache[:] = [sample for sample in cache if exact_time(sample["time"]) < boundary]
            entry.update(revision=revision, frontier=str(frontier))
        t = spacing * len(cache)
        while t <= duration:
            state = project_state(history.state_at(time=t, revision=revision), t)
            cache.append({"time": str(t), "seconds": float(t), "revision": str(state.get("revision", 0)),
                          **populations(state), "resources": resources(state)})
            t += spacing
        samples = [s for s in cache if exact_time(s["time"]) <= duration]
        if len(_metric_cache) > 64:
            _metric_cache.pop(next(iter(_metric_cache)))
    return {"definition": "Living healthy/infected humans, living zombies and cumulative dead identities; remains excluded.",
            "sample_interval": str(spacing), "version": VERSION, "samples": samples}
