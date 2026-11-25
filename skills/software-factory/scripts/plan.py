from graphlib import CycleError, TopologicalSorter
import json
from pathlib import Path
from subprocess import CalledProcessError

import evidence


def read_plan(path):
    entries = json.loads(path.read_text())
    if not isinstance(entries, list) or not entries:
        raise ValueError("Plan must be a nonempty array of work items")
    items = {}
    runs = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {
            "id",
            "task",
            "needs",
            "run",
            "inputs",
        }:
            raise ValueError("Expected id, task, optional needs, run and inputs")
        key = entry.get("id")
        if not isinstance(key, str) or not key.strip() or key in items:
            raise ValueError("Each item needs a unique nonempty id")
        task = entry.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"{key}: expected a nonempty task")
        needs = entry.get("needs", [])
        if (
            not isinstance(needs, list)
            or not all(isinstance(n, str) for n in needs)
            or len(set(needs)) != len(needs)
        ):
            raise ValueError(f"{key}: needs must be an array of distinct item IDs")
        if "inputs" in entry:
            inputs = entry["inputs"]
            if not isinstance(inputs, dict) or not all(
                isinstance(v, str) for v in inputs.values()
            ):
                raise ValueError(
                    f"{key}: expected input subjects keyed by prerequisite ID"
                )
            if "run" not in entry or inputs.keys() - set(needs):
                raise ValueError(
                    f"{key}: inputs must belong to a run and name its prerequisites"
                )
        if "run" in entry:
            run = entry["run"]
            if not isinstance(run, str):
                raise ValueError(f"{key}: expected a Factory run ID")
            try:
                evidence.run_path(run)
            except ValueError as error:
                raise ValueError(f"{key}: {error}") from error
            if run in runs:
                raise ValueError(f"{key}: run already assigned to another item")
            runs.add(run)
        items[key] = entry
    for key, entry in items.items():
        missing = set(entry.get("needs", [])) - items.keys()
        if missing:
            raise ValueError(f"{key}: unknown dependencies {sorted(missing)}")
    return items


def inspect_item(entry, inputs):
    if "run" not in entry:
        return dict(state="READY")
    if entry.get("inputs", {}) != inputs:
        return dict(
            state="ATTENTION",
            reason="Run inputs differ from current prerequisites",
            current_inputs=inputs,
        )
    try:
        report, code = evidence.run_status(entry["run"])
    except CalledProcessError as error:
        detail = (error.stderr or b"").decode(errors="replace").strip()
        return dict(state="ATTENTION", reason=detail or str(error))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        return dict(state="ATTENTION", reason=str(error))
    if not Path(report["repo"]).is_dir():
        return dict(
            state="ATTENTION",
            reason=f"Workspace directory unavailable: {report['repo']}",
        )
    if report["task"] != entry["task"]:
        return dict(state="ATTENTION", reason="The run task differs from the plan item")
    return dict(
        state="VERIFIED" if code == 0 else "ATTENTION",
        evidence=report["status"],
        subject=report["subject"],
        repo=report["repo"],
        review_reductions=report["review_reductions"],
    )


def plan(args):
    items = read_plan(args.file)
    graph = TopologicalSorter({k: v.get("needs", []) for k, v in items.items()})
    try:
        order = tuple(graph.static_order())
    except CycleError as error:
        raise ValueError(f"Dependency cycle: {' -> '.join(error.args[1])}") from error
    results = {}
    for key in order:
        entry = items[key]
        waiting = [
            n for n in entry.get("needs", []) if results[n]["state"] != "VERIFIED"
        ]
        if waiting:
            decision = dict(state="WAITING", waiting_for=waiting)
        else:
            inputs = {n: results[n]["subject"] for n in entry.get("needs", [])}
            decision = inspect_item(entry, inputs)
        results[key] = {**entry, **decision}
    rows = [results[key] for key in items]
    return dict(
        complete=all(row["state"] == "VERIFIED" for row in rows),
        next=[row["id"] for row in rows if row["state"] in {"READY", "ATTENTION"}],
        items=rows,
    ), 0


def register(sub):
    parser = sub.add_parser(
        "plan", help="Inspect dependencies and live evidence across Factory runs"
    )
    parser.add_argument("file", type=Path, help="JSON array of work items")
    parser.set_defaults(action=plan)
