"""Atomic, exact-time population comparisons of independent recorded histories."""
from __future__ import annotations

from contextlib import ExitStack

from .metrics import metrics_at_times
from .storage import exact_time
from .visualization import VERSION


SAMPLE_LIMIT = 2000
DEFINITION = "Living healthy/infected humans, living zombies and cumulative dead identities; remains excluded."


def _sources(values):
    if not isinstance(values, list) or not 2 <= len(values) <= 4:
        raise ValueError("Choose between two and four runs for comparison")
    result = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("run_id"), str) or not item["run_id"]:
            raise ValueError("Each comparison source must identify a run")
        revision = item.get("revision")
        if not isinstance(revision, str) or not revision.isascii() or not revision.isdigit() or int(revision) > 2**63 - 1:
            raise ValueError("Comparison source revisions must be nonnegative integer strings within the ledger range")
        if not isinstance(item.get("time"), str):
            raise ValueError("Comparison source times must be exact time strings")
        try:
            at = exact_time(item["time"])
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            raise ValueError("Comparison source times must be finite exact time strings") from None
        if at < 0:
            raise ValueError("Comparison source times must be nonnegative")
        result.append({"run_id": item["run_id"], "time": str(at), "revision": str(int(revision))})
    if len({item["run_id"] for item in result}) != len(result):
        raise ValueError("Choose distinct runs for comparison")
    return result


def common_times(start, end):
    """One-second grid, coarsened dyadically, including both exact endpoints."""
    spacing = exact_time(1)
    span = end - start
    while span // spacing + 1 + int(span % spacing != 0) > SAMPLE_LIMIT:
        spacing *= 2
    times = [start + index * spacing for index in range(int(span // spacing) + 1)]
    if times[-1] != end:
        times.append(end)
    return spacing, times


class ComparisonService:
    """Compare immutable run cursors using a workspace-owned metric sampler."""
    def __init__(self, metrics=None):
        from .metrics import MetricsService
        self.metrics = metrics if metrics is not None else MetricsService()

    def compare(self, sources, open_history, *, check_cancelled=None):
        """Read a complete comparison or identify failed runs without partial data.

        ``open_history`` returns a private reader, owned and closed by this call.
        Captured revisions cap every sample even when the live ledgers advance.
        """
        check = check_cancelled or (lambda: None)
        check()
        sources = _sources(sources)
        result = {"status": "failed", "sources": sources, "origins": [],
                  "common_interval": None, "sample_interval": "1", "sample_times": [],
                  "sample_limit": SAMPLE_LIMIT, "definition": DEFINITION,
                  "version": VERSION, "runs": [], "errors": []}
        with ExitStack() as stack:
            histories = {}
            for source in sources:
                check()
                run_id = source["run_id"]
                try:
                    history = open_history(run_id)
                    stack.callback(history.close)
                    with history.lock:
                        check()
                        first = history.origin()[1:]
                        boundary = history.boundary(int(source["revision"]))
                        if first is None:
                            raise ValueError("Run has not published its initial committed state")
                        if boundary is None:
                            raise ValueError("Requested source revision is not committed")
                        origin = exact_time({"n": first[0], "d": first[1]})
                        frontier = exact_time({"n": boundary[0], "d": boundary[1]})
                        if not origin <= exact_time(source["time"]) <= frontier:
                            raise ValueError("Requested source time is outside its selected committed history")
                        histories[run_id] = history
                        result["origins"].append({"run_id": run_id, "time": str(origin)})
                except Exception as error:
                    check()
                    result["errors"].append({"run_id": run_id, "message": str(error)})
            check()
            if result["errors"]:
                return result
            start = max(exact_time(item["time"]) for item in result["origins"])
            end = min(exact_time(item["time"]) for item in sources)
            result["common_interval"] = {"start": str(start), "end": str(end)}
            if start > end:
                result["status"] = "no_overlap"
                return result
            spacing, times = common_times(start, end)
            result["sample_interval"] = str(spacing)
            sampled = []
            for source, origin in zip(sources, result["origins"]):
                check()
                try:
                    samples = self.metrics.metrics_at_times(histories[source["run_id"]], times, source["revision"], check_cancelled=check)
                    sampled.append({"run_id": source["run_id"], "origin": origin["time"],
                                    "requested_cursor": {"time": source["time"], "revision": source["revision"]},
                                    "cursor": {"time": str(end), "revision": samples[-1]["revision"]},
                                    "samples": samples})
                except Exception as error:
                    check()
                    result["errors"].append({"run_id": source["run_id"], "message": str(error)})
            check()
            if not result["errors"]:
                result.update(status="ready", sample_times=[str(at) for at in times], runs=sampled)
            return result


from .metrics import _default_service as _compatibility_metrics
_default_service = ComparisonService(_compatibility_metrics)


def compare_histories(sources, open_history, *, check_cancelled=None):
    """Compatibility entry point; see :class:`ComparisonService`."""
    return _default_service.compare(sources, open_history, check_cancelled=check_cancelled)
