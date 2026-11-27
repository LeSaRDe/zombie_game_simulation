"""Read-only, revision-pinned pages of the recorded causal event ledger.

Response size is bounded by the page. Legacy occurrence-only participant links
can require a scan of older records and a transient actor/target lookup; no full
history response or persistent derived cache is created.
"""
from __future__ import annotations

import copy
import hashlib

from .storage import _unpack, apply_patch, canonical, exact_time


_MAX_SEQUENCE = 2**63 - 1


def _integer(value, name, *, minimum=0, maximum=_MAX_SEQUENCE):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _cursor(history, revision, time, check):
    head = history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
    if head is None:
        raise ValueError("Events require a committed initial state")
    selected = head[0] if revision is None else _integer(revision, "Revision", maximum=head[0])
    row = history.connection.execute("SELECT time_n,time_d FROM commits WHERE revision=?", (selected,)).fetchone()
    if row is None:
        raise ValueError("Requested event revision is not committed")
    try:
        duration = exact_time({"n": row[0], "d": row[1]}) if time is None else exact_time(time)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        raise ValueError("Event source time must be a finite simulation time") from None
    if not 0 <= duration <= exact_time({"n": head[1], "d": head[2]}):
        raise ValueError("Event source time must lie within the committed history")
    rows = history.connection.execute(
        "SELECT revision,time_n,time_d FROM commits WHERE revision<=? AND seconds<=? ORDER BY revision DESC",
        (selected, float(duration) + max(1, abs(float(duration))) * 1e-14))
    try:
        for actual, numerator, denominator in rows:
            check()
            if exact_time({"n": numerator, "d": denominator}) <= duration:
                return actual, str(duration)
    finally:
        rows.close()
    raise ValueError("Event source time precedes the committed initial state")


def _occurrences(history, revision, check, *, identities=None, owners_only=False):
    """Project only requested occurrence fields, never reconstruct agents/RNG.

    A compressed anchor is decoded and integrity-checked as an atomic stage,
    then only the requested entities survive. Unverified legacy bare anchors are
    skipped in favor of the authoritative checksum-verified patch chain.
    """
    if identities is not None and not identities:
        return {}

    def record(value):
        return {key: copy.deepcopy(child) for key, child in value.items()
                if not owners_only or key in {"actor", "target"}}

    def collection(values):
        return {str(key): record(value) for key, value in values.items()
                if identities is None or str(key) in identities}

    start = -1
    document = {"occurrences": {}}
    anchor = history.connection.execute(
        "SELECT revision,anchor FROM commits WHERE revision<=? AND anchor IS NOT NULL ORDER BY revision DESC LIMIT 1",
        (revision,)).fetchone()
    if anchor:
        check()
        envelope = _unpack(anchor[1])
        if envelope.get("anchor_schema") == 1:
            state = envelope["state"]
            if hashlib.sha256(canonical(state).encode()).hexdigest() != envelope["checksum"]:
                raise ValueError("History anchor checksum mismatch; timeline loading halted")
            document["occurrences"] = collection(state.get("occurrences", {}))
            start = anchor[0]
            del state
        del envelope
    check()
    rows = history.connection.execute(
        "SELECT patch,checksum FROM commits WHERE revision>? AND revision<=? ORDER BY revision", (start, revision))
    try:
        for payload, checksum in rows:
            check()
            if hashlib.sha256(payload).hexdigest() != checksum:
                raise ValueError("History checksum mismatch; timeline loading halted")
            for operation in _unpack(payload):
                path = operation[1]
                if not path:
                    document = {"occurrences": collection(operation[2].get("occurrences", {}))}
                    continue
                if path[0] != "occurrences":
                    continue
                if len(path) > 1 and identities is not None and str(path[1]) not in identities:
                    continue
                if len(path) > 2 and owners_only and path[2] not in {"actor", "target"}:
                    continue
                if operation[0] == "set":
                    value = operation[2]
                    if len(path) == 1:
                        value = collection(value)
                    elif len(path) == 2:
                        value = record(value)
                    operation = ["set", path, value]
                document = apply_patch(document, [operation])
    finally:
        rows.close()
    check()
    return document.get("occurrences", {})


def _occurrence_id(record):
    value = record.get("occurrence")
    if value is None:
        value = record.get("action_id")
    return str(value) if value is not None else None


def event_page(history, run_id, revision=None, agent=None, *, time=None, limit=500,
               before_sequence=None, after_sequence=None, check_cancelled=None):
    check = check_cancelled or (lambda: None)
    check()
    limit = _integer(limit, "Event page size", minimum=1, maximum=5000)
    before = None if before_sequence is None else _integer(before_sequence, "Before sequence")
    after = None if after_sequence is None else _integer(after_sequence, "After sequence")
    if before is not None and after is not None:
        raise ValueError("Choose either before_sequence or after_sequence, not both")
    if agent is not None:
        if isinstance(agent, bool) or not isinstance(agent, (str, int)):
            raise ValueError("Event identity filter must be an agent ID")
        agent = str(agent)
    with history.lock:
        actual, selected_time = _cursor(history, revision, time, check)
        linked = set()
        if agent is not None:
            owners = _occurrences(history, actual, check, owners_only=True)
            linked = {identity for identity, item in owners.items()
                      if agent in {str(item[key]) for key in ("actor", "target") if item.get(key) is not None}}
            del owners

        def take(amount, *, before=None, after=None, descending=True):
            # Indexed direct participation supplements occurrence-only links.
            # A legacy linked record can lack direct participant columns, so
            # apply the complete predicate before counting toward the page.
            direct = "0" if agent is None else "EXISTS(SELECT 1 FROM participants p WHERE p.sequence=e.sequence AND p.agent_id=?)"
            sql = f"SELECT e.sequence,e.revision,e.payload,c.time_n,c.time_d,{direct} FROM events e JOIN commits c ON c.revision=e.revision WHERE e.revision<=?"
            args = [] if agent is None else [agent]
            args.append(actual)
            if before is not None:
                sql += " AND e.sequence<?"; args.append(before)
            if after is not None:
                sql += " AND e.sequence>?"; args.append(after)
            sql += " ORDER BY e.sequence DESC" if descending else " ORDER BY e.sequence"
            if agent is None:
                sql += " LIMIT ?"; args.append(amount)
            rows = history.connection.execute(sql, args)
            result = []
            try:
                for sequence, source_revision, payload, numerator, denominator, indexed_match in rows:
                    check()
                    record = _unpack(payload)
                    if agent is not None and not indexed_match:
                        direct_ids = {str(record[key]) for key in ("actor", "target", "agent", "agent_id", "target_id")
                                      if record.get(key) is not None}
                        direct_ids.update(str(identity) for identity in record.get("targets", []))
                        if agent not in direct_ids and _occurrence_id(record) not in linked:
                            continue
                    record = dict(record, ledger_sequence=str(sequence), ledger_revision=str(source_revision),
                                  type=str(record.get("kind", "event")).upper(),
                                  revision_before=str(max(0, source_revision - 1)), revision_after=str(source_revision))
                    record.setdefault("time", str(exact_time({"n": numerator, "d": denominator})))
                    result.append(record)
                    if len(result) == amount:
                        break
            finally:
                rows.close()
            return list(reversed(result)) if descending else result

        records = take(limit, before=before, after=after, descending=after is None)
        first = records[0]["ledger_sequence"] if records else None
        last = records[-1]["ledger_sequence"] if records else None
        has_older = bool(take(1, before=int(first))) if first is not None else False
        has_newer = bool(take(1, after=int(last), descending=False)) if last is not None else False
        requested = {_occurrence_id(record) for record in records} - {None}
        occurrences = _occurrences(history, actual, check, identities=requested)
        check()
        return {"run_id": run_id, "cursor": {"time": selected_time, "revision": str(actual)},
                "agent": agent, "records": records, "occurrences": occurrences,
                "page": {"limit": limit, "loaded_count": len(records), "first_sequence": first,
                         "last_sequence": last, "has_older": has_older, "has_newer": has_newer}}
