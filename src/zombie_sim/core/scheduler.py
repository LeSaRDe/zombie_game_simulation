"""SchedulerService owns scheduler behavior behind an explicit context port."""
from __future__ import annotations
from fractions import Fraction
import heapq
from ..domain_model import ScheduledTask
from pathlib import Path
from ..domain import profile
from ..engine import clock, stamp
from .ports import SchedulerContext


class SchedulerService:
    def __init__(self, context: SchedulerContext):
        self.context = context

    def _schedule(self, time, phase, kind, agent=None, **fields):
        context = self.context
        time = clock(time)
        if time < context.time:
            raise ValueError("Cannot schedule in the past")
        context._serial += 1
        key = f"{kind}:{agent}:{fields.get('occurrence', '')}:{stamp(time)}:{context._serial}"
        priority = context._random("event-arbitration", key)
        row=ScheduledTask.from_record((time, phase, priority, context._serial, {"kind": kind, "agent": agent, **fields}))
        heapq.heappush(context.queue,row)
        from ..runtime import _encode
        context._runtime_queue_delta.append(["set",["queue",str(context._serial)],_encode(row)])

    def _schedule_decision(self, aid, when):
        context = self.context
        token = (aid, stamp(when))
        if context.decision_mode not in {"scripted","external"} and token not in context._decision_due:
            context._decision_due.add(token)
            context._schedule(when, 6, "decision", aid)

    def _schedule_starvation(self,a):
        context = self.context
        generation = a.setdefault("_hunger_generation",0)
        rate = Fraction(str(profile(a,stamp(context.time)).get("hunger_rate",.05)))
        hunger = Fraction(str(a.get("hunger",20)))
        if rate == 0 and hunger < 100:
            return
        begins = context.time+(100-hunger)/rate if hunger < 100 else context.time
        a["starvation_started_at"] = stamp(begins) if hunger == 100 else None
        due = begins+10
        a["_starvation_due_at"] = stamp(due)
        a["next_starvation_damage_at"] = stamp(due) if hunger == 100 else None
        context._schedule(due,2,"starvation",a["id"],generation=generation)

    def next_event_time(self):
        context = self.context
        return context.queue[0][0] if context.queue else context.horizon

    def advance_until(self, until, max_events=None,return_snapshot=True,should_yield=None):
        context = self.context
        until = min(clock(until),context.horizon)
        if until < context.time:
            raise ValueError("Use history replay to inspect the past")
        count = 0
        yielded = False
        context.run_status = "RUNNING"
        while context.queue and context.queue[0][0] <= until:
            if should_yield is not None and should_yield():
                yielded = True
                break
            if max_events is not None and count >= max_events:
                break
            with context._scheduled_boundary():
                when,phase,priority,serial,event = heapq.heappop(context.queue)
                context._runtime_queue_delta.append(["remove",["queue",str(serial)]])
                context.time = when
                previous_revision=context.revision
                if phase==5:
                    context._prepare_completions(event)
                if phase == 6:
                    batch = [event["agent"]]
                    while context.queue and context.queue[0][0] == when and context.queue[0][1] == 6:
                        queued=heapq.heappop(context.queue)
                        context._runtime_queue_delta.append(["remove",["queue",str(queued[3])]])
                        batch.append(queued[4]["agent"])
                    for aid in batch:
                        context._decision_due.discard((aid,stamp(when)))
                    if when < context.horizon:
                        context._decide(batch)
                else:
                    context._dispatch(event)
                if context.revision==previous_revision:
                    context._commit("scheduler_advanced",scheduled_kind=event["kind"])
            count += 1
            if not any(a["life"] > 0 for a in context.world_view["agents"].values()):
                context.run_status,context.termination_reason="COMPLETED","NO_LIVING_AGENTS"
                break
            if should_yield is not None and should_yield():
                yielded = True
                break
            context._checkpoint_if_due()
        if not yielded and should_yield is not None and should_yield():
            yielded = True
        if not yielded and max_events is None and context.run_status != "COMPLETED":
            with context._scheduled_boundary():
                context.time = until
                context._commit("clock_advanced")
        if context.time >= context.horizon and (not context.queue or context.queue[0][0]>context.horizon):
            context.run_status,context.termination_reason="COMPLETED","HORIZON"
        elif context.run_status == "RUNNING":
            context.run_status="PAUSED"
        # A request can arrive while the final clock commit is made durable.
        # Recheck before beginning another synchronous checkpoint.
        if not yielded and (should_yield is None or not should_yield()):
            context._checkpoint_if_due()
        return context.snapshot() if return_snapshot else {"time":stamp(context.time),"revision":context.revision,"status":context.run_status}

    def _checkpoint_if_due(self):
        """Enforce cadence within a long headless advance at committed boundaries."""
        context = self.context
        interval=clock(context.config.get("checkpoint_interval",30))
        transactions=int(context.config.get("checkpoint_transactions",50000))
        if context.time-context._last_checkpoint>=interval or context._since_checkpoint>=transactions:
            context.checkpoint(str(Path(context.history_path).with_suffix(".checkpoint.json")))

    def step(self, timestamp=False,return_snapshot=True,should_yield=None):
        context = self.context
        if not context.queue:
            return context.snapshot()
        return context.advance_until(context.queue[0][0],max_events=None if timestamp else 1,return_snapshot=return_snapshot,should_yield=should_yield)

    def _dispatch(self,event):
        return self.context._run_rule('event', {'event':event})
