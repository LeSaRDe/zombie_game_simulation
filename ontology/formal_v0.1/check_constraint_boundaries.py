"""Focused query tests for interval boundaries, separate from full trace fixtures."""
from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF, SH, XSD
from build_spec import Z

E = Namespace('urn:zombie-game:boundary-test:')


def check(shapes):
    def graph(second_start=0., reciprocal=False, second_result=None):
        g = Graph()
        for state, agent in [(E.left, E.agent1), (E.right, E.agent2)]:
            g.add((state, Z.ofAgent, agent))
        g.add((Z.action_melee, Z.mayCause, Z.PhysicalDamageEffect))
        for action, actor, target, start, result in [
            (E.first, E.left, E.right, 0., Z.MISSED),
            (E.second, E.right if reciprocal else E.left, E.left,
             second_start, second_result or Z.MISSED),
        ]:
            for p, v in [(RDF.type, Z.ActionOccurrence), (Z.actorStart, actor),
                         (Z.targetStart, target), (Z.actionDefinition, Z.action_melee),
                         (Z.actionResult, result),
                         (Z.startTime, Literal(str(start), datatype=XSD.decimal)),
                         (Z.plannedEnd, Literal(str(start + 1), datatype=XSD.decimal)),
                         (Z.resolvedAt, Literal(str(start + 1), datatype=XSD.decimal))]:
                g.add((action, p, v))
        return g

    cases = [
        ('Same-actor overlapping intervals detected', 'OneActionAtATime', graph(), True),
        ('Touching action intervals do not overlap', 'OneActionAtATime', graph(1.), False),
        ('Two reciprocal misses still conflict', 'ReciprocalAttackExclusion', graph(reciprocal=True), True),
        ('One cancelled reciprocal attempt is allowed', 'ReciprocalAttackExclusion',
         graph(reciprocal=True, second_result=Z.CANCELLED_BY_CONFLICT), False),
    ]
    rows = []
    for name, constraint, data, expected in cases:
        query = shapes.value(Z[constraint], SH.select)
        if query is None:
            raise ValueError('Missing constraint: ' + constraint)
        actual = bool(list(data.query(str(query), initBindings={'this': E.first})))
        rows.append({'name': name, 'passed': actual == expected,
                     'constraint': constraint, 'expected_violation': expected,
                     'actual_violation': actual,
                     'scope': 'Isolated query boundary test; not whole-graph conformance.'})
    return rows
