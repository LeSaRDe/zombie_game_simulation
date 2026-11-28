"""Immutable swept-path broad phase, shared by committed and planning views.

An envelope includes the whole admitted trajectory. Exact-time positions and
line-of-sight predicates still decide visibility; this index only finds a
conservative candidate set. Updating one agent shares all unaffected branches.
"""
from dataclasses import dataclass, field
import math
from .persistent import PersistentMap


@dataclass(frozen=True)
class SpatialIndex:
    cells: PersistentMap = field(default_factory=PersistentMap)
    membership: PersistentMap = field(default_factory=PersistentMap)
    order: PersistentMap = field(default_factory=PersistentMap)
    next_order: int = 0
    cell_size: float = 50.0

    def with_agent(self, identity, points):
        cells, membership, order, next_order = self.cells, self.membership, self.order, self.next_order
        previous = membership.get(identity, ())
        if points is None:
            selected = ()
        else:
            xs, ys = zip(*points)
            selected = tuple((x, y) for x in range(math.floor(min(xs)/self.cell_size), math.floor(max(xs)/self.cell_size)+1)
                             for y in range(math.floor(min(ys)/self.cell_size), math.floor(max(ys)/self.cell_size)+1))
        if previous == selected and identity in order:
            return self
        for cell in set(previous) - set(selected):
            members = cells[cell] - {identity}
            cells = cells.set(cell, members) if members else cells.remove(cell)
        for cell in set(selected) - set(previous):
            cells = cells.set(cell, cells.get(cell, frozenset()) | {identity})
        membership = membership.set(identity, selected) if points is not None else membership.remove(identity)
        if identity not in order:
            order = order.set(identity, next_order); next_order += 1
        return SpatialIndex(cells, membership, order, next_order, self.cell_size)

    def with_typed_agent(self, agent, occurrences):
        state = agent.current_state
        occurrence = occurrences.get(state.active_action)
        points = (tuple((float(point.x), float(point.y)) for point in occurrence.parameters.path.points)
                  if occurrence and occurrence.action in {'move', 'dash'}
                  else ((float(state.position.x), float(state.position.y)),))
        return self.with_agent(agent.identity.agent_id, points)

    @classmethod
    def build(cls, agents, occurrences):
        result = cls()
        for agent in agents.values():
            result = result.with_typed_agent(agent, occurrences)
        return result

    def candidates(self, position, radius):
        lowx, highx = math.floor((position[0]-radius)/self.cell_size), math.floor((position[0]+radius)/self.cell_size)
        lowy, highy = math.floor((position[1]-radius)/self.cell_size), math.floor((position[1]+radius)/self.cell_size)
        return {identity for x in range(lowx, highx+1) for y in range(lowy, highy+1)
                for identity in self.cells.get((x, y), ())}
