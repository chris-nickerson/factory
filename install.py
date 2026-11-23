#!/usr/bin/env python3
"""Install an immutable copy of the Factory skill and CLI on a POSIX host."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if os.name != "posix" or sys.version_info < (3, 11):
    sys.exit("Installing Software Factory requires macOS or Linux with Python 3.11+")

import fcntl  # noqa: E402 (POSIX only)

SOURCE = Path(__file__).resolve().parent / "skills/software-factory"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / "scripts"))
from workspace import release_id  # noqa: E402 (installed release identity)


def link_target(path):
    return os.readlink(path) if path.is_symlink() else None


def replace_link(link, target):
    with tempfile.TemporaryDirectory(dir=link.parent) as directory:
        temporary = Path(directory) / "next"
        temporary.symlink_to(target)
        os.replace(temporary, link)


def act(args):
    prefix = args.prefix.expanduser().resolve()
    root = prefix / "lib/software-factory"
    current = root / "current"
    manifest = root / "installation.json"
    saved = json.loads(manifest.read_text()) if manifest.exists() else {}
    skills = (
        args.skill_dir
        or [Path(d) for d in saved.get("skill_dirs", [])]
        or [Path.home() / ".agents/skills"]
    )
    skills = [d.expanduser().resolve() for d in skills]
    if saved and set(map(str, skills)) != set(saved["skill_dirs"]):
        raise ValueError(
            "Use the original skill directories for this installation or a different --prefix"
        )
    destinations = {prefix / "bin/factory": current / "scripts/factory"}
    destinations.update({d / "software-factory": current for d in skills})
    for link, target in destinations.items():
        if os.path.lexists(link) and link_target(link) != str(target):
            raise ValueError(f"Path already owned by another installation: {link}")
    if os.path.lexists(current) and (
        not current.is_symlink() or current.resolve().parent != root / "releases"
    ):
        raise ValueError(f"Foreign current release: {current}")
    old = link_target(current)
    if args.rollback:
        new = saved.get("previous")
        if not new:
            raise ValueError("No previous release recorded")
        release = Path(new)
        if (
            release.parent != root / "releases"
            or not release.is_dir()
            or release_id(release) != release.name
        ):
            raise ValueError("Previous release missing or modified")
    else:
        release = root / "releases" / release_id(SOURCE)
    print(
        json.dumps(
            dict(
                action="remove"
                if args.remove
                else "rollback"
                if args.rollback
                else "install",
                dry_run=args.dry_run,
                release=str(release),
                links=list(map(str, destinations)),
            ),
            indent=2,
        )
    )
    if args.dry_run:
        return
    if args.remove:
        if not saved:
            raise ValueError("Missing installation manifest")
        for link in destinations:
            if link.is_symlink():
                link.unlink()
        current.unlink(missing_ok=True)
        manifest.unlink()
        return
    release.parent.mkdir(parents=True, exist_ok=True)
    if release.exists():
        if release_id(release) != release.name:
            raise ValueError(f"Installed release content changed: {release}")
    else:
        with tempfile.TemporaryDirectory(dir=release.parent) as temp:
            stage = Path(temp) / "package"
            shutil.copytree(
                SOURCE, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            if release_id(stage) != release.name:
                raise ValueError("Source changed during installation")
            stage.rename(release)
    for link, target in destinations.items():
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(target)
    previous = old if old and old != str(release) else saved.get("previous")
    with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as handle:
        json.dump(dict(skill_dirs=list(map(str, skills)), previous=previous), handle)
        temp = Path(handle.name)
    temp.replace(manifest)
    replace_link(current, release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--skill-dir", action="append", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rollback", action="store_true")
    group.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        return act(args)
    root = args.prefix.expanduser().resolve() / "lib/software-factory"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        act(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(str(exc))
