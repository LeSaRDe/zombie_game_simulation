"""Versioned, read-only survival counts for the displayed cohort membership."""

VERSION = "zombie-sim/cohort-survival-v3"
DEFINITION = (
    "Human survival includes only members who entered the displayed source run as living Humans; "
    "it ends at conversion or permanent death. Identity survival includes both living entry types "
    "and ends only at permanent death. Eligible members without an event are right-censored "
    "at the displayed cursor. Dynamic cohorts describe membership at that cursor, not a fixed "
    "survival population. A branch enters at its own starting boundary; replay of an inherited "
    "prefix uses that historical source run's entry. Identities already dead at entry are excluded."
)


class SurvivalMeasurement:
    """Versioned source-run entry and survival measurement policy."""
    version = VERSION
    definition = DEFINITION

    def run_entry(self, history, state, *, check_cancelled=None):
        """Select this cursor's source-run entry using its immutable lineage.

        Branch creation is the first child commit, immediately after its recorded
        parent causal revision. Older prefix states retain their own run ID and
        lineage, so nested branches require neither scanning the whole history nor
        opening a possibly unavailable external parent ledger.
        """
        check=check_cancelled or (lambda:None)
        check()
        lineage=state.get("lineage")
        if lineage is not None:
            revision=int(lineage["revision"])+1
        else:
            revision=history.origin()[0]
        if revision is None or revision>int(state["revision"]):
            raise ValueError("The displayed cursor has no retained run-entry boundary")
        entry=history.state_at(revision=revision,check_cancelled=check)
        if entry.get("run_id")!=state.get("run_id"):
            raise ValueError("The retained entry boundary does not match the displayed source run")
        check()
        return entry


    def counts(self, agents, entry, *, missing=0, check_cancelled=None):
        """Keep non-Humans and unavailable entry evidence out of Human risk sets."""
        check = check_cancelled or (lambda: None)
        human = {"eligible": 0, "events": 0, "censored": 0,
                 "excluded_non_human": 0, "excluded_unknown_entry": 0,
                 "excluded_dead_at_entry": 0,
                 "missing_at_cursor": missing}
        identity = {"eligible": 0, "events": 0, "censored": 0,
                    "excluded_unknown_entry": 0, "excluded_dead_at_entry": 0,
                    "missing_at_cursor": missing}
        initial = entry.get("agents", {})
        for agent in agents:
            check()
            origin = initial.get(str(agent["id"]), {})
            if origin.get("type") not in {"Human", "Zombie"}:
                human["excluded_unknown_entry"] += 1
                identity["excluded_unknown_entry"] += 1
                continue
            if origin.get("status")=="DEAD" or origin.get("life",100)<=0:
                human["excluded_dead_at_entry"] += 1
                identity["excluded_dead_at_entry"] += 1
                continue
            dead = agent.get("status") == "DEAD" or agent.get("life", 100) <= 0
            identity["eligible"] += 1
            identity["events" if dead else "censored"] += 1
            if origin["type"] == "Human":
                human["eligible"] += 1
                human["events" if dead or agent.get("type") == "Zombie" else "censored"] += 1
            else:
                human["excluded_non_human"] += 1
        for counts in (human, identity):
            counts["denominator"] = counts["eligible"]
            counts["entry_run_id"] = entry.get("run_id")
            counts["entry_time"] = str(entry.get("time", 0))
            counts["entry_revision"] = str(entry.get("revision", 0))
        return {"human_survival": human, "identity_survival": identity,
                "survival_measurement_version": VERSION, "survival_definition": DEFINITION}


_default_service = SurvivalMeasurement()


def run_entry(history, state, *, check_cancelled=None):
    """Compatibility entry point; see :class:`SurvivalMeasurement`."""
    return _default_service.run_entry(history, state, check_cancelled=check_cancelled)


def survival_counts(agents, entry, *, missing=0, check_cancelled=None):
    """Compatibility entry point; see :class:`SurvivalMeasurement`."""
    return _default_service.counts(agents, entry, missing=missing, check_cancelled=check_cancelled)
