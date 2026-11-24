"""Install and update the CLI and skill as one content-addressed release."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from workspace import git, release_id, write_json


DEFAULT_ORIGIN = "https://github.com/chris-nickerson/factory.git"
SKILL_ENTRY = "scripts/skill-entry.md"


def git_environment():
    # Git hooks can export GIT_DIR, GIT_INDEX_FILE and other checkout-specific paths.
    local = subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"], text=True
    ).splitlines()
    return {k: v for k, v in os.environ.items() if k not in local}


def checkout_origin(checkout):
    if not (checkout / ".git").exists() or not shutil.which("git"):
        return None
    result = git(
        checkout,
        "config",
        "--local",
        "--get",
        "remote.origin.url",
        check=False,
        env=git_environment(),
    )
    if result.returncode:
        return None
    url = os.fsdecode(result.stdout).rstrip("\n")
    if ":" not in url and not os.path.isabs(url):
        return str((checkout / url).resolve())
    return url


@contextmanager
def installation_lock(prefix):
    root = prefix / "lib/software-factory"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def link_target(path):
    return os.readlink(path) if path.is_symlink() else None


def replace_link(link, target):
    with tempfile.TemporaryDirectory(dir=link.parent) as directory:
        temporary = Path(directory) / "next"
        temporary.symlink_to(target)
        os.replace(temporary, link)


def skill_links(current):
    return {
        "release": current,
        "references": current / "references",
        "scripts": current / "scripts",
    }


def is_skill_entry(path, current, templates):
    """Whether path is an unmodified skill directory published by this installation."""
    links = skill_links(current)
    entry = path / "SKILL.md"
    return (
        path.is_dir()
        and not path.is_symlink()
        and {p.name for p in path.iterdir()} == {"SKILL.md", *links}
        and all(link_target(path / n) == str(t) for n, t in links.items())
        and entry.is_file()
        and not entry.is_symlink()
        and any(t.is_file() and t.read_bytes() == entry.read_bytes() for t in templates)
    )


def publish_default_skill(path, current, template):
    """Publish a regular SKILL.md beside links into current, or the link older releases expect."""
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        stage = Path(temp) / "skill"
        if template.is_file():
            if path.is_dir() and not path.is_symlink():
                shutil.copyfile(template, stage)
                os.replace(stage, path / "SKILL.md")
                return
            stage.mkdir()
            shutil.copyfile(template, stage / "SKILL.md")
            for name, target in skill_links(current).items():
                (stage / name).symlink_to(target)
        elif path.is_symlink():
            return
        else:
            stage.symlink_to(current)
        previous = Path(temp) / "previous"
        if os.path.lexists(path):
            path.rename(previous)
        try:
            stage.rename(path)
        except OSError:
            if os.path.lexists(previous):
                previous.rename(path)
            raise


def install(
    prefix,
    source,
    *,
    skill_dirs=(),
    origin=None,
    rollback=False,
    remove=False,
    dry_run=False,
):
    root = prefix / "lib/software-factory"
    current = root / "current"
    manifest = root / "installation.json"
    saved = json.loads(manifest.read_text()) if manifest.exists() else {}
    default_skill_root = (Path.home() / ".agents/skills").resolve()
    default_skill = default_skill_root / "software-factory"
    skills = (
        skill_dirs
        or [Path(d) for d in saved.get("skill_dirs", [])]
        or [default_skill_root]
    )
    skills = [d.expanduser().resolve() for d in skills]
    if saved and set(map(str, skills)) != set(saved["skill_dirs"]):
        raise ValueError(
            "Use the original skill directories for this installation or a different --prefix"
        )
    destinations = {prefix / "bin/factory": current / "scripts/factory"}
    destinations.update({d / "software-factory": current for d in skills})
    if os.path.lexists(current) and (
        not current.is_symlink() or current.resolve().parent != root / "releases"
    ):
        raise ValueError(f"Foreign current release: {current}")
    entries = (current / SKILL_ENTRY, source / SKILL_ENTRY)
    for link, target in destinations.items():
        if not os.path.lexists(link) or link_target(link) == str(target):
            continue
        if link != default_skill or not is_skill_entry(link, current, entries):
            raise ValueError(f"Path already owned by another installation: {link}")
    old = link_target(current)
    if rollback:
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
        exe = source / "scripts/factory"
        if not (
            (source / "SKILL.md").is_file()
            and exe.is_file()
            and os.access(exe, os.X_OK)
        ):
            raise ValueError("Factory source is missing its skill or executable")
        release = root / "releases" / release_id(source)
    report = dict(
        action="remove" if remove else "rollback" if rollback else "install",
        dry_run=dry_run,
        release=str(release),
        links=list(map(str, destinations)),
    )
    if dry_run:
        return report
    if remove:
        if not saved:
            raise ValueError("Missing installation manifest")
        for link in destinations:
            if link.is_symlink():
                link.unlink()
            elif link.is_dir():
                shutil.rmtree(link)
        current.unlink(missing_ok=True)
        manifest.unlink()
        return report
    release.parent.mkdir(parents=True, exist_ok=True)
    if release.exists():
        if release_id(release) != release.name:
            raise ValueError(f"Installed release content changed: {release}")
    else:
        with tempfile.TemporaryDirectory(dir=release.parent) as temp:
            stage = Path(temp) / "package"
            shutil.copytree(
                source, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            if release_id(stage) != release.name:
                raise ValueError("Source changed during installation")
            probe = subprocess.run(
                [sys.executable, "-IB", str(stage / "scripts/factory"), "--version"],
                cwd=stage,
                capture_output=True,
                text=True,
            )
            if probe.returncode:
                raise ValueError(f"Factory CLI failed to start: {probe.stderr.strip()}")
            stage.rename(release)
    for link, target in destinations.items():
        link.parent.mkdir(parents=True, exist_ok=True)
        if link == default_skill:
            publish_default_skill(link, current, release / SKILL_ENTRY)
        elif not link.is_symlink():
            link.symlink_to(target)
    previous = old if old and old != str(release) else saved.get("previous")
    write_json(
        manifest,
        dict(
            skill_dirs=list(map(str, skills)),
            previous=previous,
            update_origin=origin or saved.get("update_origin") or DEFAULT_ORIGIN,
        ),
    )
    replace_link(current, release)
    return report


def update(args):
    package = Path(__file__).resolve().parents[1]
    root = package.parent.parent
    if root.name == "software-factory" and package.parent.name == "releases":
        prefix = root.parent.parent
    else:
        prefix = Path.home() / ".local"
        root = prefix / "lib/software-factory"
    manifest = root / "installation.json"
    if not manifest.is_file():
        raise ValueError("Install Factory once with python3 install.py before updating")
    with installation_lock(prefix):
        saved = json.loads(manifest.read_text())
        origin = saved.get("update_origin", DEFAULT_ORIGIN)
        old = (root / "current").resolve(strict=True)
        env = git_environment()
        with tempfile.TemporaryDirectory(prefix="factory-update-") as directory:
            checkout = Path(directory)
            git(checkout, "init", "--quiet", env=env)
            git(
                checkout,
                "fetch",
                "--quiet",
                "--depth=1",
                "--no-tags",
                "--",
                origin,
                "refs/heads/main",
                env=env,
            )
            git(
                checkout,
                "-c",
                "core.hooksPath=/dev/null",
                "checkout",
                "--quiet",
                "--detach",
                "FETCH_HEAD",
                env=env,
            )
            commit = git(checkout, "rev-parse", "HEAD", env=env).stdout.decode().strip()
            report = install(
                prefix, checkout / "skills/software-factory", origin=origin
            )
    return dict(
        status="up_to_date" if Path(report["release"]) == old else "updated",
        commit=commit,
        release=report["release"],
    ), 0
