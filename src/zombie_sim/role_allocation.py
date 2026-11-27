"""Check optional GUI role targets against the scenario's integer role counts.

The metadata is provenance for an editor conversion, not a second source of
population inputs. Validation never changes counts or individual assignments.
"""
from fractions import Fraction
import re


ROLE_ORDER = {
    "Human": ("unassigned", "DOCTOR", "WARRIOR", "SCOUT", "ENGINEER"),
    "Zombie": ("unassigned", "TYRANT", "RUNNER", "SPITTER", "SCREAMER"),
}
_INTEGER_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def validate_role_allocation(config, error_type=ValueError):
    """Validate exact shares and deterministic rounding, when metadata exists.

    ``gui`` is already excluded from the semantic fingerprint. Legacy scenarios
    with no role-allocation metadata retain their existing validation behavior.
    Import/export call this too, so contradictory provenance cannot round-trip.
    """
    gui = config.get("gui") if isinstance(config, dict) else None
    if not isinstance(gui, dict) or "role_allocation" not in gui:
        return
    path = "gui.role_allocation"

    def fail(where, message):
        raise error_type(f"{where}: {message}")

    def mapping(value, where, keys=None):
        if not isinstance(value, dict):
            fail(where, "expected an object")
        if keys is not None and set(value) != set(keys):
            fail(where, "expected exactly " + ", ".join(keys))
        return value

    def count(value, where):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail(where, "expected a nonnegative integer")
        return value

    def share(value, where):
        value = mapping(value, where, ("numerator", "denominator"))
        parts = []
        for key in ("numerator", "denominator"):
            text = value[key]
            if not isinstance(text, str) or not _INTEGER_TEXT.fullmatch(text):
                fail(where + "." + key, "expected a canonical nonnegative integer string")
            try:
                parts.append(int(text))
            except ValueError:
                fail(where + "." + key, "integer string is too large to read")
        numerator, denominator = parts
        if denominator == 0 or numerator > denominator:
            fail(where, "share must be between zero and one with a positive denominator")
        result = Fraction(numerator, denominator)
        if (result.numerator, result.denominator) != (numerator, denominator):
            fail(where, "fraction must be reduced to canonical form")
        return result

    metadata = mapping(gui["role_allocation"], path,
                       ("schema_version", "method", "Human", "Zombie"))
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        fail(path + ".schema_version", "expected version 1")
    if metadata["method"] != "largest_remainder":
        fail(path + ".method", "expected largest_remainder")
    population = mapping(config.get("population"), "population")
    for kind, order in ROLE_ORDER.items():
        record_path = path + "." + kind
        record = mapping(metadata[kind], record_path, ("tie_order", "targets"))
        if record["tie_order"] != list(order):
            fail(record_path + ".tie_order", "expected the fixed ontology-table order")
        targets = mapping(record["targets"], record_path + ".targets", order)
        shares = [share(targets[role], record_path + ".targets." + role) for role in order]
        if sum(shares) != 1:
            fail(record_path + ".targets", "shares including unassigned must total exactly one")
        total_key, roles_key = (("humans", "human_roles") if kind == "Human"
                                else ("zombies", "zombie_roles"))
        total = count(population.get(total_key), "population." + total_key)
        roles_path = "population." + roles_key
        roles = mapping(population.get(roles_key), roles_path)
        for role, value in roles.items():
            if role not in order[1:]:
                fail(roles_path + "." + str(role), "incompatible or unknown role")
            count(value, roles_path + "." + role)
        if sum(roles.values()) > total:
            fail(roles_path, "role allocations exceed " + kind + " count")
        quotas = [total * value for value in shares]
        expected = [value.numerator // value.denominator for value in quotas]
        remaining = total - sum(expected)
        priority = sorted(range(len(order)), key=lambda index: (-(quotas[index] - expected[index]), index))
        for index in priority[:remaining]:
            expected[index] += 1
        actual = [total - sum(roles.values())] + [roles.get(role, 0) for role in order[1:]]
        if actual != expected:
            fail(roles_path, "counts do not match role targets; expected " +
                 ", ".join(f"{role}={value}" for role, value in zip(order, expected)))
