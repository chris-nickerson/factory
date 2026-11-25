"""Bounded, resumable turns through local agent CLIs, one adapter per harness.

An adapter declares what its harness can do and builds the restricted command
for each kind of turn. To support another harness, add an adapter here.
"""

from datetime import datetime, timezone
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


class Claude:
    name = "claude"
    vendor = "anthropic"
    title = "Claude Code CLI"
    login = "claude auth login"
    capabilities = frozenset(
        {"read_only", "edit", "file_only_edit", "sandboxed_shell", "resume", "reports_model"}
    )
    host_env = ("CLAUDECODE",)
    host_processes = ("claude",)
    caller_names_session = True

    @staticmethod
    def authenticated(probe, exe):
        _, raw = probe([exe, "auth", "status"])
        try:
            return json.loads(raw)["loggedIn"] is True
        except (ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def resolve_model(selector, probe=None):
        """Claude Code accepts a family alias or a full model name as given."""
        return selector

    @staticmethod
    def command(run, directory):
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
        ]
        if run["model_requested"]:
            argv.extend(["--model", run["model_requested"]])
        argv.extend(
            ["--resume" if run["resume"] else "--session-id", run["requested_session"]]
        )
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
        return argv, None

    @staticmethod
    def result(path):
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


class Codex:
    name = "codex"
    vendor = "openai"
    title = "Codex CLI"
    login = "codex login"
    # Codex edits through its shell, so an editing turn always has one.
    capabilities = frozenset(
        {"read_only", "read_only_shell", "edit", "sandboxed_shell", "resume"}
    )
    host_env = ("CODEX_THREAD_ID", "CODEX_SHELL")
    host_processes = ("codex",)
    caller_names_session = False

    @staticmethod
    def authenticated(probe, exe):
        return probe([exe, "login", "status"])[0] == 0

    @staticmethod
    def resolve_model(selector, probe):
        """Resolve a family name to the catalog's preferred listed model.

        Codex accepts only complete model names, and its catalog is the one
        place that says which complete name currently carries a family. A
        hyphenated selector is a complete name and needs no catalog.
        """
        if "-" in selector:
            return selector
        for argv in (["codex", "debug", "models"], ["codex", "debug", "models", "--bundled"]):
            try:
                catalog = json.loads(probe(argv)[1])["models"]
                return _family_member(catalog, selector)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        raise HarnessError(
            f"Codex did not provide a model catalog to resolve {selector!r}."
        )

    @staticmethod
    def command(run, directory):
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
            "workspace-write" if run["edit"] else "read-only",
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
        env = None
        if run["edit"]:
            # workspace-write also opens /tmp and TMPDIR by default. Confine
            # temporary files to a directory that belongs to this turn.
            scratch = directory / "tmp"
            scratch.mkdir(mode=0o700, exist_ok=True)
            for setting in (
                "sandbox_workspace_write.network_access=false",
                "sandbox_workspace_write.exclude_slash_tmp=true",
                "sandbox_workspace_write.exclude_tmpdir_env_var=true",
                "sandbox_workspace_write.writable_roots=" + json.dumps([str(scratch)]),
                'shell_environment_policy.inherit="all"',
            ):
                argv.extend(["-c", setting])
            env = {
                **os.environ,
                "TMPDIR": str(scratch),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        if run["model_requested"]:
            argv.extend(["--model", run["model_requested"]])
        if run["has_context"]:
            context = (directory / "context.txt").read_text(encoding="utf-8")
            argv.extend(
                [
                    "-c",
                    "developer_instructions=" + json.dumps(context, ensure_ascii=False),
                ]
            )
        if run["requested_session"]:
            argv.extend(["resume", run["requested_session"]])
        return [*argv, "-"], env

    @staticmethod
    def result(path):
        session = text = None
        complete = False
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                kind = event["type"]
                if kind == "thread.started":
                    session = event["thread_id"]
                elif (
                    kind == "item.completed"
                    and event["item"]["type"] == "agent_message"
                ):
                    text = event["item"].get("text")
                elif kind == "turn.completed":
                    complete = True
                elif kind == "turn.failed":
                    detail = str((event.get("error") or {}).get("message") or "")
                    raise HarnessError(
                        "Codex reported a failed turn"
                        + (f": {detail[:300]}" if detail else "")
                    )
        if not complete:
            raise HarnessError("Codex did not report a completed turn")
        return {"session_id": session, "text": text, "model_reported": None}


def _family_member(catalog, family):
    if any(model["slug"] == family for model in catalog):
        return family
    listed = sorted(
        (
            model
            for model in catalog
            if model.get("visibility") == "list" and not _retired(model)
        ),
        key=lambda model: model["priority"],
    )
    for model in listed:
        if family.lower() in model["slug"].lower().replace(".", "-").split("-"):
            return model["slug"]
    raise HarnessError(
        f"The Codex catalog lists no model in the {family!r} family. "
        "Run `codex debug models` to see the current names."
    )


def _retired(model):
    when = (model.get("upgrade") or {}).get("retirement_at")
    try:
        moment = datetime.fromisoformat(when)
    except (TypeError, ValueError):
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= datetime.now(timezone.utc)


ADAPTERS = {adapter.name: adapter for adapter in (Codex, Claude)}


def turn_capabilities(edit, local_shell):
    """Name what one turn needs from the harness that runs it."""
    if not edit:
        return {"read_only"}
    return {"edit", "sandboxed_shell"} if local_shell else {"edit", "file_only_edit"}


def _model_identity(record, result):
    requested = record["model_requested"]
    reported = result.get("model_usage", [])
    if not reported:
        return "unreported"
    if not requested:
        return "unrequested"
    # A request can be a family inside the reported name, or a longer form of
    # it such as a dated name or one with a bracketed option.
    wanted = requested.split("[")[0].lower()
    if not any(wanted in name.lower() or name.lower() in wanted for name in reported):
        raise HarnessError(
            f"The harness reports {', '.join(reported)}, not the requested {requested}"
        )
    return "matched" if len(reported) == 1 else "indeterminate"


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
        adapter = ADAPTERS[record["provider"]]
        argv, env = adapter.command(record, directory)
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
                env=env,
            )
            record["returncode"] = rc
        try:
            result = adapter.result(stdout)
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
        record.update(
            result, model_identity=_model_identity(record, result), status="success"
        )
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
    selector=None,
    session_id=None,
    edit=False,
    local_shell=False,
    output_dir,
):
    """Start or resume the specified session and return its saved receipt.

    The caller coordinates writes to the workspace. A read-only turn cannot
    change it. An editing turn can change worktree files and, with
    `local_shell`, run sandboxed commands that cannot write Git metadata. Use
    a new output directory outside the target workspace for each attempt. With
    `model=None` the harness chooses its own model.
    `selector` records the tier or family the caller resolved `model` from. The
    receipt's `model_identity` says whether the reported model matched the
    request, or that the harness reported none.
    """
    adapter = ADAPTERS.get(provider)
    if adapter is None:
        raise HarnessError(f"Unknown harness {provider!r}")
    missing = turn_capabilities(edit, local_shell) - adapter.capabilities
    if session_id and "resume" not in adapter.capabilities:
        missing.add("resume")
    if missing:
        raise HarnessError(
            f"{adapter.title} cannot provide {', '.join(sorted(missing))} for this turn"
        )
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or not isinstance(context, str)
    ):
        raise HarnessError("Expected a nonempty user prompt and text context")
    if local_shell and not edit:
        raise HarnessError("Local shell requires an editing turn")
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
    if adapter.caller_names_session:
        requested_session = session_id or str(uuid.uuid4())
    record = {
        "status": "starting",
        "coordinator_pid": os.getpid(),
        "repo": str(repo),
        "provider": provider,
        "model_requested": model,
        "model_selector": selector,
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
