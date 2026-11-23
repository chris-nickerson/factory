"""Bounded, resumable turns through the local Codex and Claude Code CLIs."""

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

from supervision import ProcessError, execute_owned, run_worker
from workspace import write_json as _save


class HarnessError(RuntimeError):
    """The provider could not produce a trustworthy, complete turn."""


def _command(run, directory):
    provider, session = run["provider"], run["requested_session"]
    model = run["model_requested"]
    if provider == "claude":
        tools = "Read,Glob,Grep" + (",Edit,Write" if run["edit"] else "")
        shell = run.get("local_shell", False)
        argv = [
            "claude",
            "--print",
            "--safe-mode",
            "--restricted",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            tools + (",Bash" if shell else ""),
            "--permission-mode",
            "auto" if shell else "dontAsk",
            "--output-format",
            "json",
            "--model",
            model,
            "--resume" if run["resume"] else "--session-id",
            session,
        ]
        if shell:
            # Let Auto classify commands. Preapproving Bash would skip that decision.
            settings = {
                "env": {"PYTHONDONTWRITEBYTECODE": "1"},
                "sandbox": {
                    "enabled": True,
                    "failIfUnavailable": True,
                    "allowUnsandboxedCommands": False,
                    "autoAllowBashIfSandboxed": False,
                    "filesystem": {"denyWrite": ["./.git"]},
                },
                "permissions": {"deny": ["Bash(git commit *)", "Bash(git push *)"]},
            }
            argv.extend(["--settings", json.dumps(settings)])
        else:
            argv.extend(["--allowedTools", tools])
        if run["has_context"]:
            argv.extend(
                [
                    "--append-system-prompt-file",
                    str(directory / "context.txt"),
                    "--system-prompt-snapshot",
                    "off" if run["resume"] else "on",
                ]
            )
        return argv

    argv = [
        "codex",
        "--no-daemon",
        "-a",
        "never",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "hooks",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
        "-c",
        "mcp_servers={}",
    ]
    if model:
        argv.extend(["--model", model])
    if run["has_context"]:
        context = (directory / "context.txt").read_text(encoding="utf-8")
        argv.extend(
            ["-c", "developer_instructions=" + json.dumps(context, ensure_ascii=False)]
        )
    if session:
        argv.extend(["resume", session])
    return [*argv, "-"]


def _codex_result(path):
    session = text = None
    complete = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            kind = event["type"]
            if kind == "thread.started":
                session = event["thread_id"]
            elif kind == "item.completed" and event["item"]["type"] == "agent_message":
                text = event["item"].get("text")
            elif kind == "turn.completed":
                complete = True
            elif kind == "turn.failed":
                raise HarnessError("Codex reported a failed turn")
    if not complete:
        raise HarnessError("Codex did not report a completed turn")
    return {"session_id": session, "text": text, "model_reported": None}


def _claude_result(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise HarnessError("Claude returned an unexpected result format")
    if result.get("is_error") or result.get("subtype") != "success":
        message = str(result.get("result", "")).lower()
        if (
            "authenticate" in message
            or "login" in message
            or "not logged in" in message
        ):
            raise HarnessError(
                "Claude authentication failed. Run claude auth login and retry."
            )
        raise HarnessError("Claude reported an unsuccessful turn")
    if result.get("permission_denials"):
        raise HarnessError(
            "Claude reported denied tools. Inspect the turn before continuing."
        )
    models = list(result.get("modelUsage") or {})
    return {
        "session_id": result.get("session_id"),
        "text": result.get("result"),
        "model_reported": models[0] if len(models) == 1 else None,
        "model_usage": models,
    }


def _supervise(directory):
    """Own the CLI process group even if the calling coordinator is killed."""
    receipt = directory / "receipt.json"
    record = json.loads(receipt.read_text(encoding="utf-8"))
    started = time.monotonic()
    record["supervisor_pid"] = os.getpid()
    _save(receipt, record)

    def started_group(pid):
        record.update(status="running", pid=pid, pgid=pid)
        _save(receipt, record)

    try:
        argv = _command(record, directory)
        stdout = directory / "stdout"
        with (
            (directory / "prompt.txt").open("rb") as prompt,
            stdout.open("wb") as out,
            (directory / "stderr").open("wb") as err,
        ):
            rc = execute_owned(
                argv,
                cwd=record["repo"],
                stdin=prompt,
                stdout=out,
                stderr=err,
                timeout=None,
                on_start=started_group,
            )
            record["returncode"] = rc
        try:
            result = (
                _claude_result(stdout)
                if record["provider"] == "claude"
                else _codex_result(stdout)
            )
        except (ValueError, KeyError, TypeError) as error:
            raise HarnessError(f"Invalid provider response (exit {rc})") from error
        if rc:
            raise HarnessError(f"Provider exited with status {rc}")
        if not isinstance(result["text"], str) or not result["text"].strip():
            raise HarnessError("Provider returned an empty final message")
        uuid.UUID(result["session_id"])
        if (
            record["requested_session"]
            and result["session_id"] != record["requested_session"]
        ):
            raise HarnessError("Provider returned a different session ID")
        if record["model_requested"] == "opus" and result.get("model_usage"):
            if not any("opus" in name.lower() for name in result["model_usage"]):
                raise HarnessError(
                    "Claude usage reports a different model family than Opus"
                )
        record.update(result, status="success")
    except (
        HarnessError,
        ProcessError,
        ValueError,
        AttributeError,
        TypeError,
        OSError,
    ) as error:
        record.update(status="failed", error=str(error))
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _save(receipt, record)


def run_turn(
    provider,
    *,
    repo,
    prompt,
    context="",
    model=None,
    session_id=None,
    edit=False,
    local_shell=False,
    output_dir,
):
    """Start a fresh session or resume its exact ID; return the persisted receipt.

    The requester owns workspace write coordination. Claude's restricted mode
    exposes worktree file tools and can enable sandboxed Bash for Auto edits.
    Codex accepts read-only tasks here. Keep output directories outside the target and use a new one for
    every attempt. Codex JSON events do not currently report a resolved model.
    """
    if provider not in ("codex", "claude") or (edit and provider != "claude"):
        raise HarnessError("Unsupported provider or edit mode")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or not isinstance(context, str)
    ):
        raise HarnessError("Expected a nonempty user prompt and text context")
    if local_shell and (provider != "claude" or not edit):
        raise HarnessError("Local shell requires an Opus editing turn")
    if session_id:
        try:
            uuid.UUID(session_id)
        except (ValueError, AttributeError) as error:
            raise HarnessError("Expected an explicit provider session UUID") from error
    repo = Path(repo).resolve()
    directory = Path(output_dir).resolve()
    if not repo.is_dir() or directory.is_relative_to(repo):
        raise HarnessError(
            "Provide an existing workspace and a new receipt directory outside it"
        )
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    except OSError as error:
        raise HarnessError(
            f"Cannot create private turn directory {directory}: {error}"
        ) from error
    payload = prompt.encode("utf-8")
    context_bytes = context.encode("utf-8")
    (directory / "prompt.txt").write_bytes(payload)
    if context:
        (directory / "context.txt").write_bytes(context_bytes)
    requested_session = session_id
    if provider == "claude":
        requested_session = session_id or str(uuid.uuid4())
        model = model or "opus"
    record = {
        "status": "starting",
        "coordinator_pid": os.getpid(),
        "repo": str(repo),
        "provider": provider,
        "model_requested": model,
        "requested_session": requested_session,
        "resume": bool(session_id),
        "prompt_sha256": hashlib.sha256(payload).hexdigest(),
        "context_sha256": hashlib.sha256(context_bytes).hexdigest(),
        "has_context": bool(context),
        "edit": edit,
        "local_shell": local_shell,
    }
    receipt = directory / "receipt.json"
    _save(receipt, record)
    try:
        run_worker(Path(__file__).resolve(), directory, None)
    except (ProcessError, OSError) as exc:
        raise HarnessError(f"{exc} (receipt: {receipt})") from exc
    result = json.loads(receipt.read_text(encoding="utf-8"))
    if result["status"] != "success":
        detail = result.get("error", "Supervisor ended without a completed result")
        raise HarnessError(f"{detail} (receipt: {receipt})")
    return result


if __name__ == "__main__":
    _supervise(Path(sys.argv[1]))
