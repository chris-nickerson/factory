"""Discovery, source identity and local state shared by Factory workflows."""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import tomllib
from contextvars import ContextVar
from pathlib import Path


def state_root():
    default = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return (
        Path(os.environ.get("FACTORY_STATE_DIR") or default / "software-factory")
        .expanduser()
        .resolve()
    )


def git(repo, *args, check=True, env=None):
    argv = ["git", "-C", str(repo), *args]
    try:
        return subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, env=env
        )
    except FileNotFoundError:
        if check or any(
            (p / ".git").exists() for p in (Path(repo), *Path(repo).parents)
        ):
            raise ValueError("Git is required to inspect this checkout")
        return subprocess.CompletedProcess(argv, 127, b"", b"Git unavailable")


def repo_root(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"Expected a directory: {path}")
    result = git(path, "rev-parse", "--show-toplevel", check=False)
    return (
        Path(os.fsdecode(result.stdout.rstrip(b"\n"))).resolve()
        if not result.returncode
        else path
    )


def check_state_location(repo):
    if state_root().is_relative_to(repo.resolve()):
        raise ValueError("FACTORY_STATE_DIR must be outside the target workspace")


_lock_fds = ContextVar("factory_lock_fds", default=())


def workspace_lock_fds():
    """The watchdog inherits the lock so a dying coordinator cannot release it early."""
    return _lock_fds.get()


@contextlib.contextmanager
def workspace_lock(repo):
    repo = Path(repo).resolve()
    check_state_location(repo)
    directory = state_root() / "locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(os.fsencode(repo)).hexdigest()
    with (directory / key).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another Factory operation owns {repo}") from exc
        token = _lock_fds.set((*workspace_lock_fds(), handle.fileno()))
        try:
            yield
        finally:
            _lock_fds.reset(token)


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(path)


def ensure_visible_index(repo):
    """Require a complete working diff for review and Git checkpoint operations."""
    entries = git(repo, "ls-files", "-v", "-z").stdout.split(b"\0")
    hidden = [
        os.fsdecode(e[2:]) for e in entries if e and (e[:1].islower() or e[:1] == b"S")
    ]
    if hidden:
        raise ValueError(
            f"Git can hide working changes for {hidden[:5]}. Use a full worktree without assume-unchanged or skip-worktree flags."
        )


def release_digests(root):
    """Hash installable content and local access modes in one traversal."""
    content = hashlib.sha256()
    modes = hashlib.sha256(root.stat().st_mode.to_bytes(4, "big"))
    for p in sorted(root.rglob("*")):
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        mode = p.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Unexpected link in package: {p}")
        name = os.fsencode(p.relative_to(root)) + b"\0"
        modes.update(name)
        modes.update(mode.to_bytes(4, "big"))
        if stat.S_ISREG(mode):
            content.update(name)
            content.update(bytes([bool(mode & 0o111)]))
            with p.open("rb") as stream:
                content.update(hashlib.file_digest(stream, "sha256").digest())
    return content.hexdigest(), modes.hexdigest()


def release_id(root):
    """The installer's portable release identity treats executability as a bit."""
    return release_digests(root)[0]


SKILL_RELEASE_PATHS = {"release": "", "references": "references", "scripts": "scripts"}


def installed_skill_release(link, destination):
    target = link.readlink()
    if link.name == "software-factory":
        skill_root, relative = link.parent, ""
    elif link.parent.name == "software-factory" and link.name in SKILL_RELEASE_PATHS:
        skill_root, relative = link.parent.parent, SKILL_RELEASE_PATHS[link.name]
    else:
        return None
    current = target.parent if relative else target
    if (
        not current.is_absolute()
        or current.name != "current"
        or target != current / relative
    ):
        return None
    root = current.parent
    if (
        root.name != "software-factory"
        or root.parent.name != "lib"
        or not current.is_symlink()
    ):
        return None
    release = current.resolve()
    if (
        destination != release / relative
        or release.parent != root / "releases"
        or not re.fullmatch(r"[a-f0-9]{64}", release.name)
    ):
        return None
    manifest = root / "installation.json"
    if not manifest.is_file() or str(skill_root) not in json.loads(
        manifest.read_text()
    ).get("skill_dirs", []):
        return None
    content, modes = release_digests(release)
    if content != release.name:
        raise ValueError(f"Installed Factory release changed: {release}")
    return f"{content}:{modes}"


def snapshot(repo, *, plain_directory=False, follow_symlinks=True):
    """Hash Git's source set, index and HEAD, or all files in a plain directory."""
    repo = Path(repo).resolve()
    digest = hashlib.sha256()

    def field(value):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    is_git = not plain_directory and (
        git(repo, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip()
        == b"true"
    )
    gitlinks = set()
    if is_git:
        field(git(repo, "rev-parse", "--verify", "HEAD", check=False).stdout.strip())
        index = git(repo, "ls-files", "--stage", "-z").stdout
        field(index)
        paths = set()
        for entry in index.split(b"\0"):
            if entry:
                metadata, name = entry.split(b"\t", 1)
                paths.add(name)
                if metadata.startswith(b"160000 "):
                    gitlinks.add(name)
        paths.update(
            filter(
                None,
                git(
                    repo, "ls-files", "--others", "--exclude-standard", "-z"
                ).stdout.split(b"\0"),
            )
        )
    else:
        paths = {
            os.fsencode(p.relative_to(repo))
            for p in repo.rglob("*")
            if p.is_symlink() or not p.is_dir()
        }

    for name in sorted(paths):
        field(name)
        p = repo / os.fsdecode(name)
        if p.parent.resolve() != p.parent:
            field(b"replaced ancestor")
            continue
        try:
            mode = p.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            field(b"missing")
            continue
        field(str(mode).encode())
        if stat.S_ISLNK(mode):
            field(os.fsencode(os.readlink(p)))
            if not follow_symlinks:
                continue
            try:
                dest = p.resolve(strict=True)
            except FileNotFoundError:
                field(b"broken symlink")
                continue
            if dest.is_file():
                with dest.open("rb") as stream:
                    field(hashlib.file_digest(stream, "sha256").digest())
                field(str(dest.stat().st_mode).encode())
            elif dest.is_dir() and (release := installed_skill_release(p, dest)):
                field(release.encode())
            elif dest.is_dir() and dest.is_relative_to(repo):
                # The source set hashes files in an internal link's target separately.
                # An ignored directory or uninitialized checkout cannot be verified this way.
                prefix = os.fsencode(dest.relative_to(repo)) + b"/"
                if dest != repo and not any(item.startswith(prefix) for item in paths):
                    raise ValueError(
                        f"Directory link {p} points outside the verified source set"
                    )
            else:
                raise ValueError(
                    f"Cannot bind directory or special-file link {p} to this source set"
                )
        elif name in gitlinks and p.is_dir():
            # ls-files in a deinitialized submodule would discover the parent repo.
            field(
                snapshot(
                    p,
                    plain_directory=not (p / ".git").exists(),
                    follow_symlinks=follow_symlinks,
                ).encode()
            )
        elif stat.S_ISREG(mode):
            with p.open("rb") as stream:
                field(hashlib.file_digest(stream, "sha256").digest())
        elif not stat.S_ISDIR(mode):
            raise ValueError(f"Cannot verify special file {p}")
        elif name not in gitlinks:
            raise ValueError(
                f"Nested repository or unexpected directory needs its own verification scope: {p}"
            )
    return digest.hexdigest()


def package_manager(folder, root):
    locks = {
        "package-lock.json": "npm",
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "yarn",
        "bun.lock": "bun",
        "bun.lockb": "bun",
    }
    for parent in (folder, *folder.parents):
        manifest = parent / "package.json"
        if manifest.is_file():
            manager = json.loads(manifest.read_text()).get("packageManager", "")
            if isinstance(manager, str) and manager.split("@")[0] in locks.values():
                return manager.split("@")[0]
        found = {
            manager for name, manager in locks.items() if (parent / name).is_file()
        }
        if len(found) > 1:
            raise ValueError(f"Conflicting package manager locks in {parent}")
        if found:
            return found.pop()
        if parent == root:
            break
    return "npm"


def inspect(repo, targets):
    """Return evidence locators and declared commands without running project code."""
    scopes = {repo}
    for target in targets:
        path = (repo / target).resolve()
        if not path.is_relative_to(repo):
            raise ValueError(f"Path outside checkout: {target}")
        folder = path if path.is_dir() else path.parent
        while folder != repo:
            scopes.add(folder)
            folder = folder.parent
    instructions, sources, commands, skills = [], [], [], []
    seen = set()
    for folder in sorted(scopes, key=lambda p: (len(p.parts), p)):
        for filename in ("AGENTS.override.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            p = folder / filename
            if p.is_file() and p.resolve() not in seen:
                instructions.append(str(p.relative_to(repo)))
                seen.add(p.resolve())
        for filename in (
            "README.md",
            "Makefile",
            "justfile",
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "mise.toml",
            ".xcode-version",
            ".nvmrc",
            "software-factory.toml",
            "pom.xml",
            "build.gradle",
            "CMakeLists.txt",
            "Dockerfile",
            "Gemfile",
            "pubspec.yaml",
        ):
            p = folder / filename
            if not p.is_file():
                continue
            source = str(p.relative_to(repo))
            sources.append(source)
            cwd = str(folder.relative_to(repo))
            if filename == "package.json":
                manifest = json.loads(p.read_text())
                names = list(manifest.get("scripts", {}))
                manager = package_manager(folder, repo)
                commands.extend(
                    dict(source=source, cwd=cwd, argv=[manager, "run", name])
                    for name in names
                )
            elif filename == "Makefile":
                names = re.findall(
                    r"^([a-zA-Z][\w.-]*):(?!=)", p.read_text(errors="replace"), re.M
                )
                commands.extend(
                    dict(source=source, cwd=cwd, argv=["make", name])
                    for name in dict.fromkeys(names)
                )
            elif filename == "pyproject.toml":
                settings = tomllib.loads(p.read_text()).get("tool", {})
                prefix = (
                    ["uv", "run", "--no-sync"] if (folder / "uv.lock").is_file() else []
                )
                for tool, check in {
                    "pytest": ["python", "-m", "pytest"],
                    "ruff": ["ruff", "check", "."],
                    "pyrefly": ["pyrefly", "check"],
                }.items():
                    if tool in settings:
                        commands.append(
                            dict(
                                source=source,
                                cwd=cwd,
                                argv=prefix + check,
                                inferred=True,
                            )
                        )
            elif filename in ("Cargo.toml", "go.mod"):
                argv = (
                    ["cargo", "test"]
                    if filename == "Cargo.toml"
                    else ["go", "test", "./..."]
                )
                commands.append(dict(source=source, cwd=cwd, argv=argv, inferred=True))
            elif filename == "software-factory.toml":
                config = tomllib.loads(p.read_text())
                for name, argv in config.get("checks", {}).items():
                    if (
                        not isinstance(argv, list)
                        or not argv
                        or not all(isinstance(a, str) for a in argv)
                    ):
                        raise ValueError(
                            f"{source}: checks.{name} must be an argv array"
                        )
                    commands.append(dict(source=source, cwd=cwd, name=name, argv=argv))
        for loc in (".agents/skills", ".claude/skills", ".cursor/skills"):
            for p in sorted((folder / loc).glob("*/SKILL.md")):
                if p.resolve() not in seen:
                    skills.append(str(p.relative_to(repo)))
                    seen.add(p.resolve())
    workflows = repo / ".github/workflows"
    sources.extend(
        str(p.relative_to(repo))
        for p in sorted(workflows.glob("*"))
        if p.suffix in (".yaml", ".yml")
    )
    return dict(
        repo=str(repo),
        instructions=instructions,
        sources=sources,
        commands=commands,
        skills=skills,
    )
