"""Fail-closed JSON assertions, independent of simulator implementation."""
from fractions import Fraction
import math


class ContractFailure(AssertionError):
    """An adapter result violates an explicit expectation."""


def number(value):
    if isinstance(value, bool) or value is None:
        raise ContractFailure(f"Expected finite number, got {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractFailure(f"Nonfinite number: {value!r}")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ContractFailure(f"Expected finite decimal/rational, got {value!r}") from exc


def equal(left, right):
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def select(data, pointer):
    """Resolve JSON Pointer plus '*' collection expansion.

    Missing leaf keys are allowed for absence/count assertions. Missing parents
    are errors, so a misspelled parent cannot make a negative test pass.
    """
    if pointer == "":
        return [data]
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ContractFailure(f"Not a JSON pointer: {pointer!r}")
    tokens = [s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/")]
    nodes = [data]
    for index, token in enumerate(tokens):
        final = index == len(tokens) - 1
        found = []
        for node in nodes:
            if token == "*":
                if isinstance(node, dict):
                    found.extend(node.values())
                elif isinstance(node, list):
                    found.extend(node)
                else:
                    raise ContractFailure(f"Wildcard on non-collection in {pointer}")
                continue
            if isinstance(node, dict):
                if token in node:
                    found.append(node[token])
                elif not final:
                    raise ContractFailure(f"Missing parent {token!r} in {pointer}")
            elif isinstance(node, list):
                if not token.isdigit():
                    raise ContractFailure(f"Invalid list index {token!r} in {pointer}")
                offset = int(token)
                if offset < len(node):
                    found.append(node[offset])
                elif not final:
                    raise ContractFailure(f"Missing list parent in {pointer}")
            else:
                raise ContractFailure(f"Cannot descend into {node!r} in {pointer}")
        nodes = found
    return nodes


def values(data, spec):
    nodes = select(data, spec["path"])
    if "where" in spec:
        kept = []
        for node in nodes:
            matches = True
            for key, expected in spec["where"].items():
                selected = select(node, key if key.startswith("/") else "/" + key)
                if len(selected) != 1 or not equal(selected[0], expected):
                    matches = False
                    break
            if matches:
                kept.append(node)
        nodes = kept
    if "field" in spec:
        field = spec["field"]
        nodes = [item for node in nodes
                 for item in select(node, field if field.startswith("/") else "/" + field)]
    return nodes


OPERATORS = {"eq", "numeric_eq", "approx", "absent", "count", "sum_eq", "set_eq",
             "all_eq", "contains", "between", "same", "different"}


def assert_check(data, spec):
    op = spec["op"]
    if op not in OPERATORS:
        raise ContractFailure(f"Unknown assertion operator {op!r}")
    nodes = values(data, spec)
    expected = spec.get("value")
    prefix = f"{spec['path']} ({op})"
    if op == "absent":
        ok = len(nodes) == 0
    elif op == "count":
        ok = len(nodes) == expected and not isinstance(expected, bool)
    elif op == "sum_eq":
        if not nodes and not spec.get("allow_empty", False):
            raise ContractFailure(f"{prefix}: empty sum requires explicit allow_empty")
        ok = sum((number(n) for n in nodes), Fraction(0)) == number(expected)
    elif op in {"set_eq", "contains"}:
        members = nodes[0] if len(nodes) == 1 and isinstance(nodes[0], (list, dict)) else nodes
        members = list(members)
        if op == "contains":
            ok = any(equal(n, expected) for n in members)
        else:
            if not isinstance(expected, list):
                raise ContractFailure(f"{prefix}: set_eq expects a list")
            ok = (all(any(equal(n, e) for e in expected) for n in members)
                  and all(any(equal(n, e) for n in members) for e in expected))
    elif op == "all_eq":
        ok = len(nodes) >= spec.get("min_count", 1) and all(equal(n, expected) for n in nodes)
    else:
        if len(nodes) != 1:
            raise ContractFailure(f"{prefix}: expected exactly one value, got {len(nodes)}")
        actual = nodes[0]
        if op == "eq":
            ok = equal(actual, expected)
        elif op == "numeric_eq":
            ok = number(actual) == number(expected)
        elif op == "approx":
            tolerance = number(spec.get("abs_tol", "0.000000001"))
            if tolerance < 0:
                raise ContractFailure(f"{prefix}: negative tolerance")
            ok = abs(number(actual) - number(expected)) <= tolerance
        elif op == "between":
            if not isinstance(expected, list) or len(expected) != 2:
                raise ContractFailure(f"{prefix}: between needs [lower, upper]")
            ok = number(expected[0]) <= number(actual) <= number(expected[1])
        else:
            other = select(data, spec["other_path"])
            if len(other) != 1:
                raise ContractFailure(f"{prefix}: other_path must select exactly one value")
            ok = equal(actual, other[0])
            if op == "different":
                ok = not ok
            expected = {"other_path": spec["other_path"], "value": other[0]}
    if not ok:
        raise ContractFailure(f"{prefix}: observed {nodes!r}; expected {expected!r}")


def assert_checks(data, checks):
    failures = []
    for i, spec in enumerate(checks):
        try:
            assert_check(data, spec)
        except (ContractFailure, KeyError, TypeError) as exc:
            failures.append(f"check {i + 1}: {exc}")
    if failures:
        raise ContractFailure("\n".join(failures))
