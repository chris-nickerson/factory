"""Local capability checks. A live turn is the only proof of model access."""

import os
from pathlib import Path
import shutil
import sys

from evidence import review_writer
from harness import ADAPTERS
import roles
from workspace import repo_root


def diagnose(args):
    checks = {
        "python": {
            "version": sys.version.split()[0],
            "available": sys.version_info >= (3, 11),
        },
        "posix": {"available": os.name == "posix"},
    }
    exe = shutil.which("git")
    rc, version = roles.probe([exe, "--version"]) if exe else (2, "")
    checks["git"] = {"available": rc == 0, "path": exe, "version": version}
    try:
        resolved = role_report(repo_root(Path(args.repo)))
    except (ValueError, OSError, RuntimeError) as error:
        resolved = {"roles_error": str(error)}
    if args.profile == "paired":
        for name, details in (resolved.get("harnesses") or roles.installed()).items():
            checks[name] = {
                key: details[key]
                for key in ("available", "path", "version", "authenticated")
            }
    ready = all(row["available"] for row in checks.values())
    report = {
        "profile": args.profile,
        "status": "AVAILABLE" if ready else "BLOCKED",
        "checks": checks,
        **resolved,
        "scope": "Local executables and reported login state. Model access requires a live turn.",
    }
    steps = [
        f"Install {adapter.title} on PATH, then run `{adapter.login}`."
        if checks[name]["path"] is None
        else f"Check `{name} --version` and authenticate with `{adapter.login}`."
        for name, adapter in ADAPTERS.items()
        if name in checks and not checks[name]["available"]
    ]
    if steps:
        report["next_steps"] = [
            *steps,
            "Use `factory doctor --profile local` and the local evidence workflow "
            "when provider CLIs are unavailable.",
        ]
    return report, 0 if ready else 2


def role_report(repo):
    policy = roles.Policy(repo)
    return roles.report(policy, writer=review_writer(repo, policy))


def show_roles(args):
    repo = repo_root(Path(args.repo))
    if args.approve:
        roles.approve_project(repo)
    return role_report(repo), 0


def register(sub):
    parser = sub.add_parser(
        "doctor",
        help="Inspect local prerequisites, model logins and what fills each role",
    )
    parser.add_argument("--profile", choices=("local", "paired"), default="local")
    parser.add_argument(
        "--repo", default=".", help="project whose role settings apply"
    )
    parser.set_defaults(action=diagnose)
    parser = sub.add_parser(
        "roles", help="Show which harness and model fill each role, and why"
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve this project's current role settings in software-factory.toml",
    )
    parser.set_defaults(action=show_roles)
