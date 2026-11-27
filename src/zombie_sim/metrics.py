"""Revision-consistent population/resource sampling from verified ledger patches.

Only discrete measurement inputs are retained. Positions, policy memories,
intents, completed occurrences and full reconstructed histories are not cached.
"""
from collections import Counter, OrderedDict
import copy
import hashlib
import threading

from .storage import apply_patch, exact_time, _unpack


_CAPACITY = 8
_cache = OrderedDict()
_cache_lock = threading.Lock()
_source_locks = [threading.Lock() for _ in range(8)]
_comparison_cache = OrderedDict()
_comparison_source_locks = [threading.Lock() for _ in range(8)]
_fields = {
    "agents": {"type", "status", "life", "infection_episode", "inventory", "reserved",
               "active_action", "_starvation_due_at", "next_starvation_damage_at", "next_charge_at"},
    "stockpiles": {"resources", "inventory", "items", "reserved"},
    "occurrences": {"planned_end"},
    "episodes": {"conversion_due_at"},
}


def _record(collection, value):
    return {key: copy.deepcopy(child) for key, child in value.items() if key in _fields[collection]}


def _collection(name, values):
    return {key: _record(name, value) for key, value in values.items()}


def _compact(document):
    return {name: _collection(name, document.get(name, {})) for name in _fields}


def _apply(state, patch):
    for operation in patch:
        path = operation[1]
        if not path:
            state = _compact(operation[2])
            continue
        name = path[0]
        if name not in _fields or len(path) > 2 and path[2] not in _fields[name]:
            continue
        if operation[0] == "set":
            value = operation[2]
            if len(path) == 1:
                value = _collection(name, value)
            elif len(path) == 2:
                value = _record(name, value)
            operation = ["set", path, value]
        state = apply_patch(state, [operation])
    return state


def _prune(state):
    actions = {a.get("active_action") for a in state.get("agents", {}).values()
               if isinstance(a.get("active_action"), str)}
    episodes = {a.get("infection_episode") for a in state.get("agents", {}).values()
                if a.get("infection_episode")}
    for name, keep in (("occurrences", actions), ("episodes", episodes)):
        state[name] = {key: value for key, value in state.get(name, {}).items() if key in keep}


def _sample(state, time, revision):
    from .visualization import populations, resources
    # Counts/inventories do not interpolate between commits. Keep the same
    # unresolved-deadline guards as scene projection, without materializing
    # positions, hunger, stamina, profiles or historical occurrence payloads.
    for agent in state.get("agents", {}).values():
        if agent.get("life", 100) <= 0:
            continue
        action = agent.get("active_action")
        occurrence = action if isinstance(action, dict) else state.get("occurrences", {}).get(action)
        if occurrence and time > exact_time(occurrence["planned_end"]):
            raise ValueError("Projection crosses an unresolved action completion; select the next committed state")
        episode = state.get("episodes", {}).get(agent.get("infection_episode"))
        if episode and time > exact_time(episode["conversion_due_at"]):
            raise ValueError("Projection crosses an unresolved conversion deadline")
        for deadline in (agent.get("_starvation_due_at", agent.get("next_starvation_damage_at")), agent.get("next_charge_at")):
            if deadline is not None and time > exact_time(deadline):
                raise ValueError("Projection crosses an unresolved biological deadline")
    result = {"time": str(time), "seconds": float(time), "revision": str(revision),
              **populations(state), "resources": resources(state)}
    _prune(state)
    return result


def _check_payload(payload, checksum):
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("History checksum mismatch; metric sampling halted")


def _source(history):
    first = history.connection.execute("SELECT time_n,time_d,patch,checksum FROM commits ORDER BY revision LIMIT 1").fetchone()
    if first is None:
        raise ValueError("Metrics require a committed initial state")
    _check_payload(first[2], first[3])
    origin = exact_time({"n": first[0], "d": first[1]})
    if history.path is None:
        # Do not key by id(connection), which Python may reuse after closure.
        if not hasattr(history, "_metric_source_token"):
            history._metric_source_token = object()
        return (history._metric_source_token, first[3]), origin
    stat = history.path.stat()
    return (str(history.path.resolve()), stat.st_dev, stat.st_ino, first[3]), origin


def clear_metric_cache():
    """Release derived data; used by isolated verification and service teardown."""
    with _cache_lock:
        _cache.clear()


def metric_cache_info():
    """Small read-only diagnostics, excluding any simulation contents."""
    with _cache_lock:
        return {"entries": len(_cache), "capacity": _CAPACITY,
                "samples": sum(len(entry["samples"]) for entry in _cache.values()),
                "agents": sum(len(entry["state"].get("agents", {})) for entry in _cache.values()),
                "occurrences": sum(len(entry["state"].get("occurrences", {})) for entry in _cache.values())}


def clear_comparison_cache():
    """Release bounded, derived comparison prefixes without touching history."""
    with _cache_lock:
        _comparison_cache.clear()


def comparison_cache_info():
    with _cache_lock:
        return {"entries": len(_comparison_cache), "capacity": _CAPACITY,
                "samples": sum(len(entry["samples"]) for entry in _comparison_cache.values())}


def metrics_at_times(history, sample_times, revision, *, check_cancelled=None):
    """Sample explicit exact times under one immutable per-run revision cap.

    Unlike the Statistics grid, these times may begin at another run's origin.
    A bounded prefix cache reuses only requested points strictly before its
    state time. Points at that time are recomputed, including newer commits at
    the same timestamp. The existing Statistics cache and API are independent.
    """
    check = check_cancelled or (lambda: None)
    check()
    if not isinstance(sample_times, (list, tuple)) or not 1 <= len(sample_times) <= 2000:
        raise ValueError("Comparison requires between 1 and 2000 explicit sample times")
    if isinstance(revision, bool) or not isinstance(revision, (str, int)) or not str(revision).isascii() or not str(revision).isdigit():
        raise ValueError("Comparison revision must be a nonnegative integer")
    selected = int(revision)
    if selected > 2**63 - 1:
        raise ValueError("Comparison revision exceeds the supported ledger range")
    try:
        if any(isinstance(value, bool) for value in sample_times):
            raise ValueError
        times = [exact_time(value) for value in sample_times]
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        raise ValueError("Comparison sample times must be finite exact times") from None
    if times[0] < 0 or any(left >= right for left, right in zip(times, times[1:])):
        raise ValueError("Comparison sample times must be nonnegative and strictly increasing")
    with history.lock:
        boundary = history.connection.execute("SELECT time_n,time_d FROM commits WHERE revision=?", (selected,)).fetchone()
        if boundary is None:
            raise ValueError("Requested comparison revision is not committed")
        source, origin = _source(history)
        if times[0] < origin or times[-1] > exact_time({"n": boundary[0], "d": boundary[1]}):
            raise ValueError("Comparison samples must lie within the selected committed history")
        candidates = history.connection.execute(
            "SELECT revision,time_n,time_d FROM commits WHERE revision<=? AND seconds<=? ORDER BY revision DESC",
            (selected, float(times[-1]) + max(1, abs(float(times[-1]))) * 1e-14))
        try:
            target = None
            for candidate, numerator, denominator in candidates:
                check()
                if exact_time({"n": numerator, "d": denominator}) <= times[-1]:
                    target = candidate
                    break
        finally:
            candidates.close()
        if target is None:
            raise ValueError("Comparison samples precede the committed initial state")
        lock = _comparison_source_locks[hash(source) % len(_comparison_source_locks)]
        while not lock.acquire(timeout=.05):
            check()
        try:
            check()
            time_strings = [str(at) for at in times]
            with _cache_lock:
                eligible = []
                for key, value in _comparison_cache.items():
                    if key[0] != source or value["revision"] > target:
                        continue
                    prefix_time = exact_time(value["time"])
                    available = {sample["time"] for sample in value["samples"]}
                    if all(str(at) in available for at in times if at < prefix_time):
                        eligible.append((key, value))
                cache_key, prefix = max(eligible, key=lambda item: item[1]["revision"]) if eligible else (None, None)
                if cache_key is not None:
                    _comparison_cache.move_to_end(cache_key)
            if prefix is not None:
                row = history.connection.execute("SELECT patch,checksum FROM commits WHERE revision=?", (prefix["revision"],)).fetchone()
                if row is None or row[1] != prefix["checksum"]:
                    prefix = None
                else:
                    _check_payload(*row)
            check()
            state = copy.deepcopy(prefix["state"]) if prefix is not None else _compact({})
            source_revision = prefix["revision"] if prefix is not None else -1
            source_time = exact_time(prefix["time"]) if prefix is not None else origin
            checksum = prefix["checksum"] if prefix is not None else None
            previous = {sample["time"]: sample for sample in prefix["samples"]} if prefix is not None else {}
            samples = [copy.deepcopy(previous[str(at)]) for at in times if prefix is not None and at < source_time]
            index = len(samples)
            cursor = history.connection.execute(
                "SELECT revision,time_n,time_d,patch,checksum FROM commits WHERE revision>? AND revision<=? ORDER BY revision",
                (source_revision, target))
            try:
                for count, (current, numerator, denominator, payload, expected) in enumerate(cursor):
                    check()
                    at = exact_time({"n": numerator, "d": denominator})
                    while source_revision >= 0 and index < len(times) and times[index] < at:
                        check()
                        samples.append(_sample(state, times[index], source_revision))
                        index += 1
                    _check_payload(payload, expected)
                    state = _apply(state, _unpack(payload))
                    source_revision, source_time, checksum = current, at, expected
                    if count % 128 == 127:
                        _prune(state)
                while index < len(times):
                    check()
                    samples.append(_sample(state, times[index], source_revision))
                    index += 1
            finally:
                cursor.close()
            check()
            entry = {"state": state, "revision": target, "time": str(source_time),
                     "checksum": checksum, "samples": samples}
            cache_key = (source, target, tuple(time_strings))
            with _cache_lock:
                _comparison_cache[cache_key] = entry
                _comparison_cache.move_to_end(cache_key)
                while len(_comparison_cache) > _CAPACITY:
                    _comparison_cache.popitem(last=False)
            result = copy.deepcopy(samples)
            check()
            return result
        finally:
            lock.release()


def sampled_metrics(history, end=None, interval=1, limit=2000, revision=None, *, check_cancelled=None):
    check = check_cancelled or (lambda: None)
    check()
    spacing = exact_time(interval)
    if spacing <= 0:
        raise ValueError("Metric sample interval must be positive")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise ValueError("Metric sample limit must be an integer from 1 through 2000")
    with history.lock:
        head = history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
        if head is None:
            raise ValueError("Metrics require a committed initial state")
        selected = head[0] if revision is None else int(revision)
        if not 0 <= selected <= head[0]:
            raise ValueError(f"Revision must lie between 0 and committed frontier {head[0]}")
        boundary = history.connection.execute("SELECT time_n,time_d FROM commits WHERE revision=?", (selected,)).fetchone()
        if boundary is None:
            raise ValueError("Requested metric revision is not committed")
        duration = exact_time({"n": boundary[0], "d": boundary[1]}) if end is None else exact_time(end)
        committed = exact_time({"n": head[1], "d": head[2]})
        if not 0 <= duration <= committed:
            raise ValueError("Metric time must lie within the committed history")
        candidates = history.connection.execute(
            "SELECT revision,time_n,time_d FROM commits WHERE revision<=? AND seconds<=? ORDER BY revision DESC",
            (selected, float(duration) + max(1, abs(float(duration))) * 1e-14))
        actual = next((row for row in candidates if exact_time({"n": row[1], "d": row[2]}) <= duration), None)
        candidates.close()
        if actual is None:
            raise ValueError("Metric time precedes the committed initial state")
        target = actual[0]
        # Stable dyadic bins avoid invalidating every cached point as duration
        # grows. At most limit+1 grid samples plus one exact endpoint are sent.
        source, origin = _source(history)
        while (duration - origin) / spacing > limit:
            spacing *= 2
        key = (source, str(spacing))
        lock = _source_locks[hash(source) % len(_source_locks)]
        while not lock.acquire(timeout=.05):
            check()
        try:
            check()
            with _cache_lock:
                eligible = [(cache_key, value) for cache_key, value in _cache.items()
                            if cache_key[:2] == key and value["revision"] <= target]
                cache_key, prefix = max(eligible, key=lambda item: item[1]["revision"]) if eligible else (None, None)
                if cache_key is not None:
                    _cache.move_to_end(cache_key)
            if prefix is not None:
                row = history.connection.execute("SELECT patch,checksum FROM commits WHERE revision=?", (prefix["revision"],)).fetchone()
                if row is None or row[1] != prefix["checksum"]:
                    prefix = None
                else:
                    _check_payload(*row)
            check()
            state = copy.deepcopy(prefix["state"]) if prefix is not None else _compact({})
            source_revision = prefix["revision"] if prefix is not None else -1
            source_time = exact_time(prefix["time"]) if prefix is not None else exact_time(0)
            checksum = prefix["checksum"] if prefix is not None else None
            # Later commits at the same timestamp can change the boundary.
            # Only strictly earlier grid points are reusable.
            samples = [sample for sample in prefix["samples"] if exact_time(sample["time"]) < source_time] if prefix is not None else []
            next_time = origin + spacing * len(samples)
            start_revision = source_revision
            cursor = history.connection.execute(
                "SELECT revision,time_n,time_d,patch,checksum FROM commits WHERE revision>? AND revision<=? ORDER BY revision",
                (source_revision, target))
            try:
                for current, numerator, denominator, payload, expected in cursor:
                    check()
                    at = exact_time({"n": numerator, "d": denominator})
                    while source_revision >= 0 and next_time < at and next_time <= duration:
                        check()
                        samples.append(_sample(state, next_time, source_revision))
                        next_time += spacing
                    _check_payload(payload, expected)
                    state = _apply(state, _unpack(payload))
                    source_revision, source_time, checksum = current, at, expected
                while next_time <= duration:
                    check()
                    samples.append(_sample(state, next_time, source_revision))
                    next_time += spacing
                endpoint = _sample(state, duration, source_revision)
            finally:
                cursor.close()
            check()
            totals = Counter(prefix["event_counts"]) if prefix is not None else Counter()
            totals.update(dict(history.connection.execute(
                "SELECT kind,COUNT(*) FROM events WHERE revision>? AND revision<=? GROUP BY kind", (start_revision, target))))
            check()
            entry = {"state": state, "revision": target, "time": str(source_time), "checksum": checksum,
                     "samples": samples, "event_counts": dict(totals)}
            with _cache_lock:
                _cache[key + (target,)] = entry
                _cache.move_to_end(key + (target,))
                while len(_cache) > _CAPACITY:
                    _cache.popitem(last=False)
            result_samples = list(samples)
            if not result_samples or (result_samples[-1]["time"], result_samples[-1]["revision"]) != (endpoint["time"], endpoint["revision"]):
                result_samples.append(endpoint)
            check()
            from .visualization import VERSION
            return copy.deepcopy({"definition": "Living healthy/infected humans, living zombies and cumulative dead identities; remains excluded.",
                                  "sample_interval": str(spacing), "version": VERSION, "samples": result_samples,
                                  "time": str(duration), "revision": str(target), "requested_revision": str(selected),
                                  "cursor": {"time": str(duration), "revision": str(target)}, "event_counts": dict(totals)})
        finally:
            lock.release()
