"""Install and update the CLI and skill as one content-addressed release."""

from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from workspace import SKILL_RELEASE_PATHS, git, release_id, write_json


DEFAULT_ORIGIN = "https://github.com/chris-nickerson/factory.git"
LEGACY_STUB = "scripts/skill-entry.md"


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


@contextmanager
def skill_root_lock(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def link_target(path):
    return os.readlink(path) if path.is_symlink() else None


def replace_link(link, target):
    with tempfile.TemporaryDirectory(dir=link.parent) as directory:
        temporary = Path(directory) / "next"
        temporary.symlink_to(target)
        os.replace(temporary, link)


def skill_links(current):
    return {name: current / path for name, path in SKILL_RELEASE_PATHS.items()}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def is_managed_skill_directory(path, current, digests):
    links = skill_links(current)
    entry = path / "SKILL.md"
    return (
        path.is_dir()
        and not path.is_symlink()
        and {p.name for p in path.iterdir()} == {"SKILL.md", *links}
        and all(link_target(path / name) == str(target) for name, target in links.items())
        and entry.is_file()
        and not entry.is_symlink()
        and digest(entry.read_bytes()) in digests
    )


def skill_transition(path):
    return path.with_name("." + path.name + ".previous")


def discard_skill_transition(path):
    with tempfile.TemporaryDirectory(prefix=".factory-", dir=path.parent) as temp:
        path.rename(Path(temp) / "retired")


def publish_default_skill(path, current, entry):
    replace = os.path.lexists(path)
    with tempfile.TemporaryDirectory(prefix=".factory-", dir=path.parent) as temp:
        stage = Path(temp) / "skill"
        if entry is None:
            stage.symlink_to(current)
        else:
            stage.mkdir()
            (stage / "SKILL.md").write_bytes(entry)
            for name, target in skill_links(current).items():
                (stage / name).symlink_to(target)
        previous = skill_transition(path)
        if replace:
            path.rename(previous)
        try:
            stage.rename(path)
        except OSError:
            if replace:
                previous.rename(path)
            raise
        if replace:
            discard_skill_transition(previous)


def settle_release(configuration, pending):
    configuration.update(
        previous=pending["previous"],
        previous_full_entry=pending.get("previous_full_entry", False),
        commit=pending["commit"],
    )


def read_installation(manifest, current):
    saved = json.loads(manifest.read_text()) if manifest.exists() else {}
    pending = saved.pop("pending_release", None)
    if pending and link_target(current) == pending["release"]:
        settle_release(saved, pending)
    return saved


def install(
    prefix,
    source,
    *,
    skill_dirs=(),
    origin=None,
    rollback=False,
    remove=False,
    dry_run=False,
    commit=None,
):
    root = prefix / "lib/software-factory"
    current = root / "current"
    manifest = root / "installation.json"
    saved = read_installation(manifest, current)
    default_skill_root = (Path.home() / ".agents/skills").resolve()
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
    if prefix.name == ".local" and default_skill_root not in skills:
        default_skill_root = (prefix.parent / ".agents/skills").resolve()
    registration = saved.get("skill_entry", {})
    default_skill = Path(
        registration.get("path", default_skill_root / "software-factory")
    )
    with ExitStack() as locks:
        if not dry_run:
            for skill_root in sorted(set(skills)):
                if not remove:
                    skill_root.mkdir(parents=True, exist_ok=True)
                if skill_root.is_dir():
                    locks.enter_context(skill_root_lock(skill_root))
        return install_release(
            prefix,
            source,
            saved,
            skills,
            default_skill,
            origin=origin,
            rollback=rollback,
            remove=remove,
            dry_run=dry_run,
            commit=commit,
        )


def install_release(
    prefix,
    source,
    saved,
    skills,
    default_skill,
    *,
    origin,
    rollback,
    remove,
    dry_run,
    commit,
):
    root = prefix / "lib/software-factory"
    current = root / "current"
    manifest = root / "installation.json"
    registration = saved.get("skill_entry", {})
    digests = {registration.get("sha256"), registration.get("replacing")}
    destinations = {prefix / "bin/factory": current / "scripts/factory"}
    destinations.update({d / "software-factory": current for d in skills})
    if os.path.lexists(current) and (
        not current.is_symlink() or current.resolve().parent != root / "releases"
    ):
        raise ValueError(f"Foreign current release: {current}")
    detached = remove and saved and not os.path.lexists(current) and not os.path.lexists(
        prefix / "bin/factory"
    )
    has_entry = False
    for link, target in destinations.items():
        if link == prefix / "bin/factory":
            continue
        previous = skill_transition(link)
        if not os.path.lexists(previous):
            continue
        if link_target(previous) != str(target) and not is_managed_skill_directory(
            previous, current, digests
        ):
            if detached:
                continue
            raise ValueError(f"Another installation owns the pending skill change: {link}")
        if not dry_run:
            if not os.path.lexists(link):
                previous.rename(link)
            elif link_target(link) == str(target) or is_managed_skill_directory(
                link, current, digests
            ):
                discard_skill_transition(previous)
    for link, target in destinations.items():
        if not os.path.lexists(link) or link_target(link) == str(target):
            continue
        if link == default_skill and is_managed_skill_directory(
            link, current, digests
        ):
            has_entry = True
        elif not detached:
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
        retired = []
        for skill_root in skills:
            path = skill_root / "software-factory"
            if link_target(path) == str(current) or (path == default_skill and has_entry):
                previous = skill_transition(path)
                path.rename(previous)
                retired.append(previous)
        cli = prefix / "bin/factory"
        if link_target(cli) == str(current / "scripts/factory"):
            cli.unlink()
        current.unlink(missing_ok=True)
        for previous in retired:
            discard_skill_transition(previous)
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
    installed_entry = (default_skill / "SKILL.md").read_bytes() if has_entry else None
    configuration = dict(
        skill_dirs=list(map(str, skills)),
        previous=saved.get("previous"),
        previous_full_entry=saved.get("previous_full_entry", False),
        commit=saved.get("commit"),
        update_origin=origin or saved.get("update_origin") or DEFAULT_ORIGIN,
    )
    if registration:
        configuration["skill_entry"] = registration
    entry = None
    if default_skill in destinations:
        template = release / "SKILL.md"
        if rollback and not saved.get("previous_full_entry"):
            template = release / LEGACY_STUB
        default_skill.parent.mkdir(parents=True, exist_ok=True)
        if template.is_file():
            entry = template.read_bytes()
            registration = {"path": str(default_skill), "sha256": digest(entry)}
            if entry == installed_entry:
                entry = None
            elif installed_entry is not None:
                registration["replacing"] = digest(installed_entry)
            configuration["skill_entry"] = registration
        elif link_target(default_skill) != str(current):
            publish_default_skill(default_skill, current, None)
    for link, target in destinations.items():
        if link != default_skill and not link.is_symlink():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
    switching = old and old != str(release)
    if switching:
        configuration["pending_release"] = {
            "release": str(release),
            "previous": old,
            "previous_full_entry": has_entry and not (Path(old) / LEGACY_STUB).is_file(),
            "commit": commit,
        }
    else:
        configuration["commit"] = commit
    write_json(manifest, configuration)
    replace_link(current, release)
    if entry is not None:
        publish_default_skill(default_skill, current, entry)
    pending = configuration.pop("pending_release", None)
    if pending:
        settle_release(configuration, pending)
    configuration.get("skill_entry", {}).pop("replacing", None)
    write_json(manifest, configuration)
    return report


HISTORY_DEPTH = 50


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
        saved = read_installation(manifest, root / "current")
        origin = saved.get("update_origin", DEFAULT_ORIGIN)
        previous = saved.get("commit")
        old = (root / "current").resolve(strict=True)
        env = git_environment()
        progress = getattr(args, "progress", None)
        if progress:
            progress("Checking for a new Factory release")
        with tempfile.TemporaryDirectory(prefix="factory-update-") as directory:
            checkout = Path(directory)
            git(checkout, "init", "--quiet", env=env)
            git(
                checkout,
                "fetch",
                "--quiet",
                f"--depth={HISTORY_DEPTH}",
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
            head = commit_log(checkout, "-1", "HEAD", env=env)[0]
            changes = None
            if previous and previous != commit:
                changes = commit_log(checkout, f"{previous}..HEAD", env=env)
            report = install(
                prefix, checkout / "skills/software-factory", origin=origin, commit=commit
            )
    return dict(
        status="up_to_date" if Path(report["release"]) == old else "updated",
        commit=commit,
        previous=previous,
        release=report["release"],
        origin=origin,
        head=head,
        changes=changes,
    ), 0


def commit_log(checkout, *revisions, env=None):
    """Commits as dicts, or None when the range reaches past the fetched history."""
    result = git(
        checkout,
        "log",
        "--format=%H%x1f%s%x1f%cr",
        *revisions,
        "--",
        check=False,
        env=env,
    )
    if result.returncode:
        return None
    return [
        dict(zip(("commit", "subject", "when"), line.split("\x1f")))
        for line in result.stdout.decode(errors="replace").splitlines()
    ]


def display_origin(origin):
    home = str(Path.home())
    if os.path.isabs(origin):
        return "~" + origin[len(home) :] if origin.startswith(home + "/") else origin
    for scheme in ("https://", "http://", "ssh://", "git@"):
        origin = origin.removeprefix(scheme)
    return origin.removesuffix(".git").replace(":", "/", 1)


def render_update(report, color=True):
    def paint(code, text):
        return f"\033[{code}m{text}\033[0m" if color else text

    bold, dim = (lambda t: paint("1", t)), (lambda t: paint("2", t))
    short = report["commit"][:7]
    head = report["head"]
    lines = [""]
    if report["status"] == "up_to_date":
        lines.append(f"  {paint('32', '✔')} {bold('Factory is up to date')}  {dim(short)}")
        lines.append(f"    {head['subject']} {dim('· ' + head['when'])}")
    else:
        before = report["previous"]
        arrow = f"{dim(before[:7])} {paint('36', '→')} " if before else ""
        lines.append(
            f"  {paint('32', '✔')} {bold('Factory updated')}  {arrow}{paint('1;36', short)}"
        )
        lines.append("")
        changes = report["changes"] or [head]
        shown = changes[:10]
        width = min(60, max(len(c["subject"]) for c in shown))
        for change in shown:
            subject = change["subject"]
            if len(subject) > width:
                subject = subject[: width - 1] + "…"
            lines.append(
                f"    {paint('32', '+')} {paint('33', change['commit'][:7])} "
                f"{subject.ljust(width)}  {dim(change['when'])}"
            )
        if len(changes) > len(shown):
            lines.append(dim(f"      … and {len(changes) - len(shown)} more"))
        if report["changes"] is None and before:
            lines.append(dim(f"      (only the latest change is shown; the rest predate the last {HISTORY_DEPTH} commits)"))
    lines.append("")
    lines.append(dim(f"    from {display_origin(report['origin'])} @ main"))
    lines.append("")
    return "\n".join(lines)
