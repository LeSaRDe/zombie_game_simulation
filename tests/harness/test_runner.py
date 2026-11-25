import unittest
from tests.run_acceptance import execute_isolated, factory_from_spec


class RunnerHarnessTests(unittest.TestCase):
    def test_request_and_response_cross_process_boundary(self):
        self.assertEqual(execute_isolated("tests.harness.fakes:factory", {"payload": {"n": 3}}, 5), {"n": 3})

    def test_adapter_exception_fails(self):
        with self.assertRaisesRegex(RuntimeError, "injected adapter exception"):
            execute_isolated("tests.harness.fakes:factory", {"error": True}, 5)

    def test_cleanup_exception_fails(self):
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            execute_isolated("tests.harness.fakes:broken_close", {}, 5)

    def test_timeout_fails(self):
        with self.assertRaises(TimeoutError):
            execute_isolated("tests.harness.fakes:factory", {"sleep": 5}, 0.1)

    def test_invalid_factory_format(self):
        with self.assertRaises(ValueError):
            factory_from_spec("missing-separator")
