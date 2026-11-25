import unittest
from tests.assertions import ContractFailure, assert_check, assert_checks, select, number


class AssertionHarnessTests(unittest.TestCase):
    def test_pointer_escaping_and_arrays(self):
        self.assertEqual(select({"a/b": {"~x": [3, 4]}}, "/a~1b/~0x/1"), [4])

    def test_wildcards(self):
        self.assertEqual(select({"x": {"a": {"n": 1}, "b": {"n": 2}}}, "/x/*/n"), [1, 2])

    def test_unknown_operator_fails(self):
        with self.assertRaises(ContractFailure):
            assert_check({}, {"path": "", "op": "assume_pass", "value": True})

    def test_negative_assertion_cannot_hide_missing_parent(self):
        with self.assertRaises(ContractFailure):
            assert_check({"observations": {}}, {"path": "/obeservations/hidden", "op": "absent"})

    def test_absent_leaf_and_empty_collection(self):
        assert_check({"x": {}}, {"path": "/x/hidden", "op": "absent"})
        assert_check({"x": []}, {"path": "/x/*", "op": "count", "value": 0})

    def test_missing_positive_value_fails(self):
        with self.assertRaises(ContractFailure):
            assert_check({}, {"path": "/n", "op": "eq", "value": None})

    def test_all_eq_not_vacuous(self):
        with self.assertRaises(ContractFailure):
            assert_check({"x": []}, {"path": "/x/*", "op": "all_eq", "value": "PASS"})

    def test_empty_sum_requires_opt_in(self):
        with self.assertRaises(ContractFailure):
            assert_check({"x": []}, {"path": "/x/*", "op": "sum_eq", "value": 0})
        assert_check({"x": []}, {"path": "/x/*", "op": "sum_eq", "value": 0, "allow_empty": True})

    def test_where_then_field(self):
        data = {"draws": [{"channel": "hit", "p": "0.72"}, {"channel": "infection", "p": "0.36"}]}
        assert_check(data, {"path": "/draws/*", "where": {"channel": "infection"}, "field": "p",
                            "op": "numeric_eq", "value": "9/25"})

    def test_exact_time_comparison(self):
        assert_check({"t": "1/3"}, {"path": "/t", "op": "numeric_eq", "value": "2/6"})
        with self.assertRaises(ContractFailure):
            assert_check({"t": "0.333333333333"}, {"path": "/t", "op": "numeric_eq", "value": "1/3"})

    def test_boolean_not_integer(self):
        with self.assertRaises(ContractFailure):
            assert_check({"n": True}, {"path": "/n", "op": "eq", "value": 1})
        with self.assertRaises(ContractFailure):
            number(False)

    def test_nonfinite_values_fail(self):
        for value in ["NaN", "Infinity", float("nan"), float("inf"), "1/0"]:
            with self.subTest(value=value), self.assertRaises(ContractFailure):
                number(value)

    def test_approx_tolerance_and_boundary(self):
        assert_check({"x": "0.999999999"}, {"path": "/x", "op": "approx", "value": "1"})
        with self.assertRaises(ContractFailure):
            assert_check({"x": "0.99999999"}, {"path": "/x", "op": "approx", "value": "1"})

    def test_same_and_different(self):
        data = {"left": {"n": 1}, "right": {"n": 1}, "changed": {"n": 2}}
        assert_check(data, {"path": "/left", "op": "same", "other_path": "/right"})
        assert_check(data, {"path": "/left", "op": "different", "other_path": "/changed"})

    def test_count_and_set_comparison(self):
        data = {"values": ["a", "a", "b"]}
        assert_check(data, {"path": "/values/*", "op": "count", "value": 3})
        assert_check(data, {"path": "/values/*", "op": "set_eq", "value": ["a", "b"]})
        assert_check(data, {"path": "/values", "op": "contains", "value": "b"})

    def test_between_includes_endpoints(self):
        for x in (0, 1):
            assert_check({"x": x}, {"path": "/x", "op": "between", "value": [0, 1]})

    def test_multi_failure_report(self):
        with self.assertRaises(ContractFailure) as caught:
            assert_checks({"a": 1, "b": 2}, [{"path": "/a", "op": "eq", "value": 3},
                                             {"path": "/b", "op": "eq", "value": 4}])
        self.assertIn("check 1", str(caught.exception))
        self.assertIn("check 2", str(caught.exception))
