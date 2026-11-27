"""Coordinator-owned interrupt requests, applied only at committed boundaries."""
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor
import signal
import threading


@contextmanager
def deferred_sigint():
    """Keep initialization, event publication, saving and cleanup indivisible.

    Repeated Ctrl+C requests remain stop requests; they never throw through a
    state mutation or checkpoint replacement. The caller checks the flag using
    the engine's committed-boundary ``should_yield`` callback.
    """
    requested = [False]
    def request_stop(signum, frame):
        requested[0] = True
    installed = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGINT, request_stop) if installed else None
    try:
        yield lambda: requested[0]
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous)


def ignore_worker_sigint():
    """A process-group Ctrl+C is handled by the authoritative coordinator."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal,"pthread_sigmask"):
        signal.pthread_sigmask(signal.SIG_UNBLOCK,{signal.SIGINT})


class BoundaryProcessPool(ProcessPoolExecutor):
    """Shield spawned workers until their coordinator-owned signal setup runs."""
    def submit(self, fn, /, *args, **kwargs):
        # Spawn inherits this thread's signal mask. Keep SIGINT blocked through
        # child module imports, then ignore/unblock it in the worker initializer.
        # The parent's pending signal is delivered to its normal handler on exit.
        old = signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT}) if hasattr(signal,"pthread_sigmask") else None
        try:
            return super().submit(fn,*args,**kwargs)
        finally:
            if old is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK,old)
