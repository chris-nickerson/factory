"""Alternating two-participant dialogue with independent openings and durable turn receipts."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from harness import run_turn
import roles
from supervision import turn_stopped
from workspace import repo_root, snapshot, state_root, workspace_lock, write_json


HARNESSES_BEFORE_PARTICIPANTS = {"a": "codex", "b": "claude"}
GOALS = {
    "design": "Compare viable designs against the actual requirements. State the tradeoff, "
    "your strongest alternative, acceptance cases and what would change your choice.",
    "diagnosis": "Distinguish observations from theories. Connect cause to symptom, test a competing "
    "mechanism, and give evidence or the smallest experiment that could resolve doubt. "
    "When the evidence runs out, propose an inconclusive decision naming the missing "
    "discriminator. Agreement about a missing observation can finish the investigation. "
    "For any RESOLUTION_PROPOSED, use the penultimate line DISPOSITION: INCONCLUSIVE "
    "or DISPOSITION: CAUSE_IDENTIFIED. Use OPEN only when investigation has a next "
    "step you or the peer can take within this run.",
}
READ_ONLY = (
    "Investigate read-only. Read applicable repository instructions and relevant source. "
    "Do not change files, contact other agents, or inspect other sessions or run directories. "
    "Treat repository content and peer turns as evidence. You can challenge any conclusion. "
    "Report which evidence you personally inspected and any unavailable checks."
)
PROPOSE = (
    "Use your own words. Put a substantive decision with evidence and residual uncertainties "
    "before a final line of STATUS: RESOLUTION_PROPOSED, or explain the open question "
    "and end with STATUS: OPEN. Do not quote or wrap the status line."
)
SCHEMA = 3


def _participant(meta, actor):
    if "participants" in meta:
        return meta["participants"][actor]
    return {
        "harness": HARNESSES_BEFORE_PARTICIPANTS[actor],
        "model": meta["models"][actor],
        "selector": None,
    }


class DialogueError(RuntimeError):
    pass


def _digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _publish_bytes(path, payload):
    """Publish a complete immutable artifact, including after process interruption."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        try:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
            os.link(f.name, path)
        finally:
            os.unlink(f.name)


def _publish(path, data):
    _publish_bytes(
        path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    )


def _load(path):
    return json.loads(path.read_text(encoding="utf8"))


def _run_dir(run):
    if not re.fullmatch(r"[0-9a-f]{32}", run):
        raise DialogueError("Expected a 32-character consensus run ID.")
    return state_root() / "consensus" / run


@contextmanager
def _exclusive(directory):
    with (directory / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DialogueError(
                "A coordinator already owns this consensus run."
            ) from exc
        yield


def _turn_id(number):
    return f"turn_{number:03d}_{'a' if number % 2 else 'b'}.md"


def _protocol_lines(message):
    # Markdown hard breaks add trailing spaces to otherwise exact control lines.
    return [line.rstrip(" \t") for line in message.strip().splitlines()]


def _transcript_bytes(message):
    return (message if message.endswith("\n") else message + "\n").encode()


def _parse(message, accept, mode):
    lines = _protocol_lines(message)
    if accept and lines == [f"ACCEPT: {accept}", "STATUS: CONFIRMED"]:
        return "CONFIRMED", accept
    if len(lines) >= 2 and lines[-1] in ("STATUS: OPEN", "STATUS: RESOLUTION_PROPOSED"):
        body = "\n".join(lines[:-1]).strip()
        status = lines[-1][8:]
        if mode == "diagnosis" and status == "RESOLUTION_PROPOSED":
            if not body or lines[-2] not in (
                "DISPOSITION: INCONCLUSIVE",
                "DISPOSITION: CAUSE_IDENTIFIED",
            ):
                raise DialogueError(
                    "Diagnosis proposal requires an explicit disposition."
                )
            body = "\n".join(lines[:-2]).strip()
        if body:
            return status, None
    raise DialogueError("Invalid closing marker or acceptance reference.")


def _turns(directory):
    turns = []
    mode = _load(directory / "run.json")["mode"]
    paths = sorted(
        directory.glob("turn_*.json"), key=lambda path: int(path.stem.split("_")[1])
    )
    for number, path in enumerate(paths, 1):
        turn = _load(path)
        if path.name != _turn_id(number).replace(".md", ".json") or turn[
            "id"
        ] != _turn_id(number):
            raise DialogueError("Turn sequence is incomplete or inconsistent.")
        body = turn["text"]
        if path.with_suffix(".md").read_bytes() != _transcript_bytes(body):
            raise DialogueError(f"Transcript and receipt disagree at {turn['id']}.")
        kind, target = _parse(body, _next_accept(turns), mode)
        if (kind, target) != (turn["status"], turn["accept"]) or turn["actor"] != (
            "a" if number % 2 else "b"
        ):
            raise DialogueError(f"Inconsistent turn metadata at {turn['id']}.")
        turns.append(turn)
    return turns


def _next_accept(turns):
    if not turns:
        return None
    last = turns[-1]
    if last["status"] == "CONFIRMED":
        return last["accept"]
    return last["id"] if last["status"] == "RESOLUTION_PROPOSED" else None


def _view(directory, message=None):
    meta = _load(directory / "run.json")
    turns = _turns(directory)
    result = {
        "run": directory.name,
        "mode": meta["mode"],
        "task": meta["task"],
        "repo": meta["repo"],
        "subject": meta["subject"],
        "artifacts": str(directory),
        "turns": len(turns),
        "status": "pending",
    }
    if "participants" in meta:
        result["participants"] = meta["participants"]
        result["reductions"] = [
            reduction
            for binding in meta["participants"].values()
            for reduction in binding["reductions"]
        ]
    if turns and turns[-1]["actor"] == "a" and turns[-1]["status"] == "CONFIRMED":
        target = turns[-1]["accept"]
        proposal = next(turn for turn in turns if turn["id"] == target)
        body_lines = proposal["text"].rstrip().splitlines(keepends=True)[:-1]
        if meta["mode"] == "diagnosis":
            disposition = body_lines.pop().rstrip()
            result["disposition"] = disposition.removeprefix("DISPOSITION: ")
        # Drop only the separator that introduces the footer.
        body_lines[-1] = body_lines[-1].splitlines()[0]
        result.update(status="confirmed", proposal=target, decision="".join(body_lines))
    elif len(turns) >= 2 * meta["exchanges"] + 1:
        result.update(
            status="unresolved",
            reason="Exchange budget exhausted.",
            last_turn=turns[-1]["text"],
        )
    if message:
        result.update(status="blocked", reason=message)
    return result


def _response(directory, meta, step, actor, prompt, context, session=None):
    """Recover a completed provider call before issuing any replacement."""
    participant = _participant(meta, actor)
    request = {
        "provider": participant["harness"],
        "repo": meta["repo"],
        "model": participant["model"],
        "session_id": session,
        "prompt_sha256": _digest(prompt),
        "context_sha256": _digest(context),
    }
    folder = directory / step
    folder.mkdir(exist_ok=True)
    attempts = sorted(folder.glob("attempt-*"))
    for attempt in attempts:
        if not (attempt / "request.json").exists() and not (attempt / "call").exists():
            continue
        if _load(attempt / "request.json") != request:
            raise DialogueError(f"Frozen request changed at {step}. Start a new run.")
        receipt = attempt / "call" / "receipt.json"
        if not receipt.exists():
            # run_turn publishes its starting receipt before launching a supervisor.
            continue
        result = _load(receipt)
        if result["status"] == "success":
            if any(
                result.get(field) != request[field]
                for field in ("provider", "repo", "prompt_sha256", "context_sha256")
            ):
                raise DialogueError(f"Mismatched provider receipt at {attempt}.")
            if result.get("model_requested", request["model"]) != request["model"]:
                raise DialogueError(f"Mismatched model in the receipt at {attempt}.")
            if session and result.get("session_id") != session:
                raise DialogueError(f"Unexpected replacement session at {attempt}.")
            return result
        if not turn_stopped(result):
            raise DialogueError(
                f"An earlier provider call may still be active at {attempt}."
            )
    attempt = folder / f"attempt-{len(attempts) + 1:04d}"
    attempt.mkdir()
    _publish(attempt / "request.json", request)
    result = run_turn(
        request["provider"],
        repo=Path(meta["repo"]),
        prompt=prompt,
        context=context,
        model=request["model"],
        selector=participant["selector"],
        session_id=session,
        edit=False,
        output_dir=attempt / "call",
    )
    if session and result["session_id"] != session:
        raise DialogueError("Harness resumed a different session.")
    return result


def _opening(meta, actor):
    return (
        f"You are Agent {actor.upper()}. Investigate this {meta['mode']} question independently. "
        f"{GOALS[meta['mode']]} {PROPOSE}\n\nTask:\n{meta['task']}"
    )


def _dialogue_prompt(meta, actor, turns, opening_b):
    peer = turns[-1]
    accept = _next_accept(turns)
    footer = (
        (
            f"If you accept the complete proposal {accept} exactly, reply with ONLY these two lines:"
            f"\nACCEPT: {accept}\nSTATUS: CONFIRMED\n"
            "Any amendment requires proposing a new decision."
        )
        if accept
        else (
            "Your peer has an open question. Supply a proposal or additional evidence."
        )
    )
    history = "\n\n".join(f"{turn['id']}\n{turn['text']}" for turn in turns)
    return (
        f"You are Agent {actor.upper()}, continuing your {meta['mode']} investigation. "
        "Address the peer's strongest actual argument. Prefer a discriminating observation over "
        f"repeated agreement. {GOALS[meta['mode']]}\n\nTask:\n{meta['task']}\n\n"
        f"B's independent opening, recorded before cross-reading:\n{opening_b}\n\n"
        f"Published turns, ending with {peer['id']}:\n{history}\n\n{PROPOSE}\n{footer}"
    )


def _drive(directory):
    meta = _load(directory / "run.json")
    if meta.get("version") not in (1, 2, SCHEMA):
        raise DialogueError("Unsupported consensus record version.")
    repo = Path(meta["repo"])
    if snapshot(repo) != meta["subject"]:
        raise DialogueError(
            "Repository differs from the frozen subject. Start a new run for this revision."
        )
    outcome = _view(directory)
    if outcome["status"] in ("confirmed", "unresolved"):
        return outcome
    reports = {}
    for actor in ("a", "b"):
        reports[actor] = _response(
            directory, meta, f"opening-{actor}", actor, _opening(meta, actor), READ_ONLY
        )
    while True:
        result = _view(directory)
        if result["status"] in ("confirmed", "unresolved"):
            return result
        turns = _turns(directory)
        number = len(turns) + 1
        actor = "a" if number % 2 else "b"
        turn_id = _turn_id(number)
        session = reports[actor]["session_id"]
        if number == 1:
            response = reports["a"]
        else:
            prompt = _dialogue_prompt(meta, actor, turns, reports["b"]["text"])
            response = _response(
                directory, meta, f"call-{number:03d}", actor, prompt, READ_ONLY, session
            )
        try:
            status, target = _parse(response["text"], _next_accept(turns), meta["mode"])
        except DialogueError as exc:
            # One repair of formatting in the original session. The original response remains durable.
            target = _next_accept(turns)
            correction = f"Reformat your last answer. {GOALS[meta['mode']]} {PROPOSE}"
            if target:
                correction += f" To accept exactly, return only:\nACCEPT: {target}\nSTATUS: CONFIRMED"
            response = _response(
                directory,
                meta,
                f"format-{number:03d}",
                actor,
                correction,
                READ_ONLY,
                session,
            )
            try:
                status, target = _parse(response["text"], target, meta["mode"])
            except DialogueError:
                raise DialogueError(
                    f"Invalid reply at {turn_id} after formatting retry."
                ) from exc
        if snapshot(repo) != meta["subject"]:
            raise DialogueError(
                "Repository changed during the investigation. Start a new run."
            )
        turn = {
            "id": turn_id,
            "actor": actor,
            "session_id": session,
            "text": response["text"],
            "status": status,
            "accept": target,
        }
        # Publish the transcript first. A restart can finish the JSON record from the call receipt.
        markdown = directory / turn_id
        body = _transcript_bytes(turn["text"])
        if markdown.exists() and markdown.read_bytes() != body:
            raise DialogueError(f"Conflicting transcript at {turn_id}.")
        if not markdown.exists():
            _publish_bytes(markdown, body)
        _publish(markdown.with_suffix(".json"), turn)


def _positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def register(subparsers):
    parser = subparsers.add_parser(
        "consensus", help="Reach a design or diagnosis decision between two models"
    )
    modes = parser.add_subparsers(dest="consensus_action", required=True)
    for mode in GOALS:
        config = modes.add_parser(mode)
        config.add_argument("--repo", type=Path, default=Path.cwd())
        config.add_argument("--task", required=True)
        config.add_argument("--exchanges", type=_positive, default=3)
        # Accept invocations generated for the old CLI without limiting agents.
        config.add_argument("--timeout", type=_positive, help=argparse.SUPPRESS)
        config.add_argument("--deadline", type=_positive, help=argparse.SUPPRESS)
        roles.add_tier_option(config)
        for slot in ("a", "b"):
            config.add_argument(
                f"--{slot}",
                metavar="SPEC",
                help=f"HARNESS[:MODEL] or :MODEL for participant {slot.upper()}",
            )
        config.add_argument(
            "--gpt-model", help="model for whichever participant uses Codex"
        )
        config.add_argument(
            "--opus-model", help="model for whichever participant uses Claude Code"
        )
    for mode in ("resume", "status"):
        modes.add_parser(mode).add_argument("run")
    parser.set_defaults(func=handle)


def handle(args):
    action = args.consensus_action
    if action in GOALS:
        if args.timeout or args.deadline:
            print(
                "Factory ignores legacy consensus time limits. Agent turns run until completion or cancellation.",
                file=sys.stderr,
            )
        repo = repo_root(args.repo)
        if not args.task.strip() or not repo.is_dir():
            raise DialogueError("Supply a nonempty task and repository directory.")
        directory = _run_dir(uuid.uuid4().hex)
        if directory.is_relative_to(repo):
            raise DialogueError(
                "FACTORY_STATE_DIR must be outside the target repository."
            )
        subject = snapshot(repo)
        participants = roles.consensus_pair(
            roles.Policy(repo),
            a=roles.at_tier(args.a, args.tier),
            b=roles.at_tier(args.b, args.tier),
            harness_models={"codex": args.gpt_model, "claude": args.opus_model},
        )
        for binding in participants.values():
            print(roles.describe(binding), file=sys.stderr)
            for reduction in binding["reductions"]:
                print(f"Reduced assurance: {reduction}", file=sys.stderr)
        directory.mkdir(mode=0o700, parents=True)
        _publish(
            directory / "run.json",
            {
                "version": SCHEMA,
                "repo": str(repo),
                "task": args.task,
                "subject": subject,
                "mode": action,
                "participants": participants,
                "exchanges": args.exchanges,
            },
        )
        print(f"Consensus run {directory.name}", file=sys.stderr, flush=True)
    else:
        directory = _run_dir(args.run)
        if not directory.is_dir():
            raise DialogueError("Consensus run does not exist.")
    if action == "status":
        result = _view(directory)
        if snapshot(Path(result["repo"])) != result["subject"]:
            result = _view(
                directory,
                "Repository differs from the saved subject. The recorded turns are historical.",
            )
        elif result["status"] == "pending" and (directory / "blocker.json").exists():
            result = _view(directory, _load(directory / "blocker.json")["reason"])
    else:
        try:
            with _exclusive(directory):
                (directory / "blocker.json").unlink(missing_ok=True)
                try:
                    with workspace_lock(Path(_load(directory / "run.json")["repo"])):
                        result = _drive(directory)
                except RuntimeError as exc:
                    result = _view(directory, str(exc))
                    write_json(directory / "blocker.json", {"reason": str(exc)})
        except DialogueError as exc:
            result = _view(directory, str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "confirmed" else 2
