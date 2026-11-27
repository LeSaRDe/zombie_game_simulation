"""Read-only researcher projections, cohorts and portable research exports."""
from __future__ import annotations

import copy
import csv
import io
import math
from collections import Counter
from pathlib import Path
from .storage import History, exact_time, canonical

VERSION = "zombie-sim/view-v1"


def entities(state, name):
    value = state.get(name, {})
    return list(value.values()) if isinstance(value, dict) else list(value)


def populations(state):
    counts = {"healthy": 0, "infected": 0, "zombies": 0, "dead": 0}
    for agent in entities(state, "agents"):
        if agent.get("status") == "DEAD" or agent.get("life", 100) <= 0:
            counts["dead"] += 1
        elif str(agent.get("type", "")).lower() == "zombie":
            counts["zombies"] += 1
        elif agent.get("status") == "INFECTED" or agent.get("infection_episode"):
            counts["infected"] += 1
        else:
            counts["healthy"] += 1
    counts["total"] = sum(counts.values())
    return counts


def resources(state):
    totals = Counter()
    reserved = Counter()
    for agent in entities(state, "agents"):
        totals.update(agent.get("inventory", {}))
        reserved.update(agent.get("reserved", {}))
    for stock in entities(state, "stockpiles"):
        totals.update(stock.get("resources", stock.get("inventory", stock.get("items", {}))))
        reserved.update(stock.get("reserved", {}))
    return {"available_and_reserved": dict(totals), "reserved_subset": dict(reserved)}


def project_state(state, time=None):
    """Evaluate the engine's recorded anchors without decisions or random draws."""
    state = copy.deepcopy(state)
    time = state.get("time", 0) if time is None else time
    try:
        from .runtime import materialize_snapshot
    except ImportError:
        from .domain import profile, status, action_status
        for agent in entities(state, "agents"):
            agent.update(profile(agent, str(time)))
            agent.update(status=status(agent), action_state=action_status(agent))
        if exact_time(time) != exact_time(state.get("time", 0)):
            state["projection_note"] = "Positions shown at the last committed boundary."
    else:
        state = materialize_snapshot(state, time)
    return state


def view_bundle(state, *, run_id=None, mode="live", sequence=0, frontier=None, generation=0):
    # Scene transport contains current occurrences, not every past action or
    # submitted intent. The complete immutable records remain queryable in the
    # ledger, keeping live frame size independent of elapsed action count.
    scene = dict(state)
    active = {a.get("active_action") for a in entities(state, "agents") if a.get("active_action")}
    if "occurrences" in state:
        scene["occurrences"] = {key: value for key, value in state["occurrences"].items() if key in active}
    scene.pop("intents", None)
    return {"schema": VERSION, "run_id": run_id or state.get("run_id"),
            "sequence": str(sequence), "query_generation": str(generation), "mode": mode,
            "time": str(state.get("time", 0)), "revision": str(state.get("revision", 0)),
            "committed_frontier": str(frontier if frontier is not None else state.get("revision", 0)),
            "measurement_watermark": str(state.get("revision", 0)), "state": scene,
            "metrics": {"populations": populations(state), "resources": resources(state)}}


def cohort_members(state, definition, *, check_cancelled=None):
    check = check_cancelled or (lambda: None)
    check()
    if definition.get("mode") == "fixed":
        return [str(x) for x in definition.get("members", [])]
    predicate = definition.get("predicate", {})
    result = []
    for agent in entities(state, "agents"):
        check()
        from .domain import status
        current = dict(agent, status=status(agent))
        assignment = agent.get("model_assignment") or {}
        current["model_assignment"] = assignment.get("model_id") if isinstance(assignment, dict) else assignment
        if not definition.get("include_dead", True) and current["status"] == "DEAD":
            continue
        matches = all(str(current.get(key, "")) == str(value)
                      for key, value in predicate.items() if key in {"type", "role", "status", "model_assignment"} and value != "")
        region = predicate.get("region")
        if region:
            matches = matches and region[0] <= agent["x"] <= region[2] and region[1] <= agent["y"] <= region[3]
        if matches:
            result.append(str(agent["id"]))
    return result


def cohort_summary(state, definition, *, check_cancelled=None):
    check = check_cancelled or (lambda: None)
    membership = cohort_members(state, definition, check_cancelled=check)
    identities = set(membership)
    selected = []
    for agent in entities(state, "agents"):
        check()
        if str(agent["id"]) in identities:
            selected.append(agent)
    denominator = len(selected)
    return {"definition": definition, "members": membership, "denominator": len(membership),
            "present": denominator, "populations": populations({"agents": selected}),
            "mean_life": sum(a.get("life", 0) for a in selected) / denominator if denominator else None,
            "mean_stamina": sum(a.get("stamina", 0) for a in selected) / denominator if denominator else None,
            "mean_life_denominator": denominator, "mean_stamina_denominator": denominator,
            "resources": resources({"agents": selected}), "measurement_version": VERSION,
            "survival_definition": "Human survival applies to members who entered as Human and ends at conversion or death; identity survival ends at death. Eligible members without an event are right-censored at the displayed time."}


def sampled_metrics(history, end=None, interval=1, limit=2000, revision=None, *, check_cancelled=None):
    from .metrics import sampled_metrics as collect
    return collect(history, end, interval, limit, revision, check_cancelled=check_cancelled)


def events_csv(records):
    output = io.StringIO()
    columns = ["ledger_sequence", "ledger_revision", "id", "time", "phase", "kind", "actor", "target", "action", "outcome", "details"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for record in records:
        writer.writerow({**{key: record.get(key, "") for key in columns[:-1]}, "details": canonical(record)})
    return output.getvalue()


def world_svg(state, width=1000):
    from html import escape
    world = state.get("world", {})
    length = float(world.get("length", 1000)); height = float(world.get("width", 1000))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {length} {height}" width="{width}" height="{width * height / length}">',
             '<rect width="100%" height="100%" fill="#101b25"/>', f'<g transform="translate(0 {height}) scale(1 -1)">']
    for barrier in entities(state, "barriers"):
        rect = barrier.get("footprint", barrier.get("rect"))
        if rect and len(rect) == 4:
            color = "#6ba68a" if barrier.get("mode") == "OPEN" else "#647687"
            parts.append(f'<rect x="{rect[0]}" y="{rect[1]}" width="{rect[2]-rect[0]}" height="{rect[3]-rect[1]}" fill="{color}"/>')
    for agent in entities(state, "agents"):
        color = "#77838d" if agent.get("status") == "DEAD" else "#f4b85a" if agent.get("status") == "INFECTED" else "#f17788" if str(agent.get("type")).lower() == "zombie" else "#66d7cb"
        parts.append(f'<circle cx="{agent.get("x", 0)}" cy="{agent.get("y", 0)}" r="{max(length / 250, 1)}" fill="{color}"><title>{escape(str(agent.get("id")))}</title></circle>')
    parts.append('</g></svg>')
    return ''.join(parts)


def replay_animation(history, start=0, end=None, interval=1, run_id=None, max_frames=300):
    """A portable, offline HTML replay built exclusively from recorded history."""
    latest = history.state_at()
    start = exact_time(start)
    end = exact_time(latest.get("time", 0) if end is None else end)
    interval = exact_time(interval)
    if not 0 <= start <= end <= exact_time(latest.get("time", 0)):
        raise ValueError("Animation interval must lie within the committed history")
    if interval <= 0:
        raise ValueError("Animation sample interval must be positive")
    spacing = max(interval, (end - start) / max(1, max_frames - 1))
    frames = []
    time = start
    while time <= end:
        state = project_state(history.state_at(time=time), time)
        frames.append({"time": str(time), "revision": str(state.get("revision", 0)),
                       "svg": world_svg(state, 800), "populations": populations(state)})
        time += spacing
    payload = canonical({"schema": VERSION, "run_id": run_id, "start": str(start), "end": str(end),
                         "sample_interval": str(spacing), "interpolation": "recorded continuous segments only", "frames": frames}).replace("<", "\\u003c")
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Recorded outbreak replay</title>
<style>body{font:14px system-ui;background:#101b25;color:#d8e5e7;max-width:900px;margin:30px auto;padding:15px}h1{font-weight:450}button,input{font:inherit}button{padding:9px 15px;background:#d5e9bc;border:0;border-radius:4px}#frame svg{width:100%;height:auto;max-height:70vh}#cursor{width:70%}small{color:#95adb6}pre{white-space:pre-wrap}</style>
<h1>Recorded outbreak replay</h1><p id="metadata"></p><div id="frame" aria-label="Recorded world"></div><p id="status" role="status"></p><button id="play">Play</button> <input id="cursor" type="range" min="0" value="0" aria-label="Replay frame"><details><summary>Provenance and sampling</summary><pre id="provenance"></pre></details>
<script>const data=''' + payload + ''';let index=0,timer;const slider=document.getElementById('cursor');slider.max=data.frames.length-1;function show(){const f=data.frames[index];document.getElementById('frame').innerHTML=f.svg;document.getElementById('status').textContent='Time '+f.time+' s · revision '+f.revision+' · '+JSON.stringify(f.populations);slider.value=index;}slider.oninput=()=>{index=Number(slider.value);show();};document.getElementById('play').onclick=()=>{if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='Play';}else{document.getElementById('play').textContent='Pause';timer=setInterval(()=>{index=(index+1)%data.frames.length;show();},250);}};document.getElementById('metadata').textContent='Run '+data.run_id+' · '+data.frames.length+' recorded samples';const{frames,...metadata}=data;document.getElementById('provenance').textContent=JSON.stringify(metadata,null,2);show();</script></html>'''
