"""Non-mutating local capability checks. A live provider turn is a separate check."""

import json
import os
import shutil
import subprocess
import sys


PROVIDERS = {
    "codex": ("Codex CLI", "codex login"),
    "claude": ("Claude Code CLI", "claude auth login"),
}


def probe(argv):
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=12, stdin=subprocess.DEVNULL
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 2, ""


def diagnose(args):
    checks = {
        "python": {
            "version": sys.version.split()[0],
            "available": sys.version_info >= (3, 11),
        },
        "posix": {"available": os.name == "posix"},
    }
    required = ["git"] if args.profile == "local" else ["git", *PROVIDERS]
    for tool in required:
        exe = shutil.which(tool)
        rc, version = probe([exe, "--version"]) if exe else (2, "")
        details = {"available": rc == 0, "path": exe, "version": version}
        if exe and tool == "claude":
            _, raw = probe([exe, "auth", "status"])
            try:
                logged_in = json.loads(raw)["loggedIn"] is True
            except (ValueError, KeyError, TypeError):
                logged_in = False
            details.update(
                authenticated=logged_in, available=details["available"] and logged_in
            )
        if exe and tool == "codex":
            auth, _ = probe([exe, "login", "status"])
            details.update(
                authenticated=auth == 0, available=details["available"] and auth == 0
            )
        checks[tool] = details
    ready = all(row["available"] for row in checks.values())
    report = {
        "profile": args.profile,
        "status": "AVAILABLE" if ready else "BLOCKED",
        "checks": checks,
        "scope": "Local executables and reported login state. Model access requires a live turn.",
    }
    steps = [
        f"Install {name} on PATH, then run `{login}`."
        if checks[tool]["path"] is None
        else f"Check `{tool} --version` and authenticate with `{login}`."
        for tool, (name, login) in PROVIDERS.items()
        if tool in checks and not checks[tool]["available"]
    ]
    if steps:
        report["next_steps"] = [
            *steps,
            "Use `factory doctor --profile local` and the local evidence workflow "
            "when provider CLIs are unavailable.",
        ]
    return report, 0 if ready else 2


def register(sub):
    parser = sub.add_parser(
        "doctor", help="Inspect local prerequisites and optional model logins"
    )
    parser.add_argument("--profile", choices=("local", "paired"), default="local")
    parser.set_defaults(action=diagnose)
