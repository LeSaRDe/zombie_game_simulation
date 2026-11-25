"""Deliberately tiny test doubles for runner failure tests, never product adapters."""
import time

CONFORMANCE_TEST_DOUBLE = True


class Echo:
    def execute(self, request):
        if request.get("sleep"):
            time.sleep(request["sleep"])
        if request.get("error"):
            raise RuntimeError("injected adapter exception")
        return request.get("payload", {})

    def close(self):
        pass


def factory(*, workdir):
    assert workdir.is_dir()
    return Echo()


class BrokenClose(Echo):
    def close(self):
        raise RuntimeError("injected close failure")


def broken_close(*, workdir):
    return BrokenClose()
