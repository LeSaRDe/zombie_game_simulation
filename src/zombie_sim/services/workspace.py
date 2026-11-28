"""Composition root for one independent research workspace.

Process pools, exports and HTTP libraries are created only when requested. A
headless modeling client can use configuration and history services directly.
"""
from __future__ import annotations

import threading


class WorkspaceServices:
    """Own application collaborators and close them in dependency order."""

    def __init__(self, root="experiments", *, read_only=False, manager=None,
                 configuration=None, metrics=None, comparison=None, timeline=None,
                 visualization=None, readers_factory=None, exports_factory=None):
        from ..application import RunManager
        self.manager = manager if manager is not None else RunManager(
            root, read_only=read_only, configuration=configuration, metrics=metrics,
            comparison=comparison, timeline=timeline, visualization=visualization)
        self.configuration = self.manager.configuration
        self.metrics = self.manager.metrics
        self.comparison = self.manager.comparisons
        self.timeline = self.manager.timelines
        self.visualization = self.manager.visualization
        self.repository = self.manager.repository
        self.workers = self.manager.workers
        self.queries = self.manager.queries
        self._readers_factory = readers_factory
        self._exports_factory = exports_factory
        self._readers = None
        self._exports = None
        self._shutdown = None
        self._closed = False
        self._lifecycle_lock = threading.RLock()

    def _require_open(self):
        if self._closed:
            raise RuntimeError("Workspace services are closed")

    @property
    def readers(self):
        with self._lifecycle_lock:
            self._require_open()
            if self._readers is None:
                from ..read_tasks import ReadPool
                factory = self._readers_factory or ReadPool
                self._readers = factory(self.manager.root)
            return self._readers

    @property
    def exports(self):
        with self._lifecycle_lock:
            self._require_open()
            if self._exports is None:
                from ..export_jobs import ExportJobs
                factory = self._exports_factory or ExportJobs
                self._exports = factory(self.manager)
            return self._exports

    @property
    def shutdown(self):
        with self._lifecycle_lock:
            self._require_open()
            if self._shutdown is None:
                from ..service_shutdown import ShutdownCoordinator
                self._shutdown = ShutdownCoordinator(self.manager, self.readers, self.exports)
            return self._shutdown

    def close(self):
        with self._lifecycle_lock:
            if self._closed:
                return
            if self._exports is not None:
                self._exports.close()
            if self._readers is not None:
                self._readers.close()
            self.manager.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
