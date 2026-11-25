"""Decide which harness and model fill each of Factory's roles.

A role states what a job needs. A binding names the harness and model that
fill it for one run, where the choice came from and which assurance it
reduces. Callers resolve a binding once, save it with the run and reuse the
saved binding on resume.
"""

from functools import cached_property
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from harness import ADAPTERS, HarnessError
from workspace import state_root, write_json


ROLE_NEEDS = {
    "reviewer": {"read_only"},
    "simplifier": {"read_only", "edit", "sandboxed_shell", "resume"},
    "consensus-a": {"read_only", "resume"},
    "consensus-b": {"read_only", "resume"},
}
TIERS = ("standard", "frontier")
HARNESS_DEFAULT = "default"
PORTABLE_MODELS = (*TIERS, HARNESS_DEFAULT)
DEFAULTS = Path(__file__).resolve().with_name("defaults.toml")
PROJECT_FILE = "software-factory.toml"


class RoleError(ValueError):
    """A role cannot be filled as requested."""


def probe(argv):
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=12, stdin=subprocess.DEVNULL
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 2, ""


def parse_spec(text):
    """Split HARNESS[:MODEL] or :MODEL into its harness and model parts."""
    harness, colon, model = str(text).strip().partition(":")
    if not (harness or model) or (colon and not model):
        raise RoleError(
            f"Expected HARNESS, HARNESS:MODEL or :MODEL in place of {text!r}."
        )
    if harness and harness not in ADAPTERS:
        raise RoleError(
            f"Unknown harness {harness!r}. Factory supports {', '.join(ADAPTERS)}."
        )
    return harness or None, model or None


def user_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base).expanduser() / "software-factory/config.toml"


def _tables(path, keys=("roles", "models")):
    """Read and validate the role tables of one configuration file."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RoleError(f"Cannot read role configuration {path}: {error}") from error
    tables = {key: data[key] for key in keys if key in data}
    try:
        unknown = set(tables.get("roles", {})) - set(ROLE_NEEDS)
        if unknown:
            raise RoleError(
                f"unknown roles: {', '.join(sorted(unknown))}. "
                f"The roles are {', '.join(ROLE_NEEDS)}"
            )
        for spec in tables.get("roles", {}).values():
            parse_spec(spec)
        for harness, families in tables.get("models", {}).items():
            if (
                harness not in ADAPTERS
                or not isinstance(families, dict)
                or not all(isinstance(name, str) and name for name in families.values())
            ):
                raise RoleError(
                    f"[models.{harness}] must map a tier to a model name for a "
                    "supported harness"
                )
    except (RoleError, AttributeError, TypeError) as error:
        raise RoleError(f"{path}: {error}") from error
    return tables


def _approvals():
    try:
        return json.loads((state_root() / "approved-projects.json").read_text())
    except (OSError, ValueError):
        return {}


def project_policy(repo):
    """Read a project's role settings and whether the user approved them.

    The project file may be part of the change under review. Its role
    settings count only after the user approves that exact content, and until
    then a mistake in them cannot stop a run.
    """
    if repo is None:
        return {}, None
    try:
        tables = _tables(Path(repo) / PROJECT_FILE)
    except RoleError as error:
        return {}, {"state": "invalid", "reason": str(error)}
    if not tables:
        return {}, None
    digest = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    approved = _approvals().get(str(Path(repo).resolve())) == digest
    return tables, {
        "state": "approved" if approved else "unapproved",
        "digest": digest,
    }


def approve_project(repo):
    tables, approval = project_policy(repo)
    if not tables:
        raise RoleError(
            (approval or {}).get("reason")
            or f"{Path(repo) / PROJECT_FILE} has no [roles] or [models] table."
        )
    approved = {**_approvals(), str(Path(repo).resolve()): approval["digest"]}
    state_root().mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(state_root() / "approved-projects.json", approved)


def detect_host(environ=None, ancestors=None):
    """Identify the harness whose session is running Factory.

    An outer host's environment leaks into a session nested inside it, so the
    nearest agent process decides before environment markers do.
    """
    environ = os.environ if environ is None else environ
    stated = environ.get("FACTORY_HOST")
    if stated:
        if stated != "none" and stated not in ADAPTERS:
            raise RoleError(
                f"FACTORY_HOST must be none or one of {', '.join(ADAPTERS)}."
            )
        return {
            "harness": None if stated == "none" else stated,
            "evidence": "FACTORY_HOST",
        }
    for name in _ancestors() if ancestors is None else ancestors:
        for adapter in ADAPTERS.values():
            if name in adapter.host_processes:
                return {
                    "harness": adapter.name,
                    "evidence": f"parent process {name}",
                }
    marked = {
        adapter.name: marker
        for adapter in ADAPTERS.values()
        for marker in adapter.host_env
        if environ.get(marker)
    }
    if len(marked) == 1:
        ((name, marker),) = marked.items()
        return {"harness": name, "evidence": f"environment variable {marker}"}
    if marked:
        return {
            "harness": None,
            "evidence": "ambiguous: environment names " + " and ".join(sorted(marked)),
        }
    return {"harness": None, "evidence": "no agent host detected"}


def _ancestors(limit=16):
    """Yield the names of this process's ancestors, nearest first."""
    pid = os.getppid()
    for _ in range(limit):
        code, row = probe(["ps", "-o", "ppid=,comm=", "-p", str(pid)])
        parent, _, command = row.strip().partition(" ")
        if code or not parent.isdigit():
            return
        yield Path(command.strip()).name.lower()
        pid = int(parent)
        if pid <= 1:
            return


def installed():
    """Report each harness's executable and login state."""
    report = {}
    for adapter in ADAPTERS.values():
        exe = shutil.which(adapter.name)
        code, version = probe([exe, "--version"]) if exe else (2, "")
        signed_in = bool(exe) and adapter.authenticated(probe, exe)
        report[adapter.name] = {
            "available": code == 0 and signed_in,
            "path": exe,
            "version": version,
            "authenticated": signed_in,
            "vendor": adapter.vendor,
            "capabilities": sorted(adapter.capabilities),
        }
    return report


class Policy:
    """The configuration layers and machine facts one resolution reads.

    Probing a CLI takes seconds, so the machine facts load on first use and
    each probe runs once.
    """

    def __init__(self, repo=None):
        self.shipped = _tables(DEFAULTS, ("roles", "models", "default-harness-order"))
        project, self.project_approval = project_policy(repo)
        approved = (self.project_approval or {}).get("state") == "approved"
        self.layers = [
            ("user", _tables(user_config_path())),
            ("project", project if approved else {}),
        ]
        self._probes = {}

    @cached_property
    def host(self):
        return detect_host()

    @cached_property
    def harnesses(self):
        return installed()

    def probe(self, argv):
        key = tuple(argv)
        if key not in self._probes:
            self._probes[key] = probe(argv)
        return self._probes[key]

    def default_model(self, role):
        return parse_spec(self.shipped["roles"][role])[1]

    def family(self, harness, tier):
        for _, tables in reversed([("shipped", self.shipped), *self.layers]):
            name = tables.get("models", {}).get(harness, {}).get(tier)
            if name:
                return name
        raise RoleError(
            f"No {tier} model is configured for {harness}. Add it under "
            f"[models.{harness}] in {user_config_path()}."
        )

    def candidates(self, role):
        order = self.shipped["default-harness-order"][role]
        return [
            name
            for name in [*order, *(n for n in ADAPTERS if n not in order)]
            if self.harnesses.get(name, {}).get("available")
            and ROLE_NEEDS[role] <= ADAPTERS[name].capabilities
        ]


def resolve(role, policy, *, explicit=None, avoid_vendor=None):
    """Choose the harness and model selector for a role.

    `explicit` is this run's flag. When nothing names a harness, the default
    prefers one whose vendor differs from `avoid_vendor`.
    """
    specs = [
        (source, *parse_spec(tables["roles"][role]))
        for source, tables in [*policy.layers, ("flag", {"roles": {role: explicit}})]
        if tables.get("roles", {}).get(role)
    ]
    named = [index for index, (_, harness, _) in enumerate(specs) if harness]
    harness_set_at = named[-1] if named else -1
    if named:
        source, harness, _ = specs[harness_set_at]
        missing = ROLE_NEEDS[role] - ADAPTERS[harness].capabilities
        if missing:
            raise RoleError(
                f"{ADAPTERS[harness].title} cannot fill the {role} role. It lacks "
                + ", ".join(sorted(missing))
                + "."
            )
        if not shutil.which(harness):
            raise RoleError(
                f"The {role} role is set to {harness} by the {source}, and "
                f"{ADAPTERS[harness].title} is not installed."
            )
    else:
        source = "default"
        options = policy.candidates(role)
        if not options:
            raise RoleError(
                f"No installed, signed-in harness can fill the {role} role. "
                "Run `factory doctor` to see what each harness is missing."
            )
        harness = next(
            (n for n in options if ADAPTERS[n].vendor != avoid_vendor), options[0]
        )
    selector, model_source = policy.default_model(role), "default"
    for index, (layer, written_for, model) in enumerate(specs):
        # A family or complete name belongs to the harness it was written
        # for. Written alone, it applies unless a later layer chose a harness.
        fits = written_for == harness or index > harness_set_at
        if model and (model in PORTABLE_MODELS or fits):
            selector, model_source = model, layer
    return {
        "role": role,
        "harness": harness,
        "vendor": ADAPTERS[harness].vendor,
        "selector": selector,
        "source": source,
        "model_source": model_source,
        "reductions": [],
    }


def bind_model(binding, policy):
    """Turn the binding's selector into the model argument the harness takes."""
    selector, harness = binding["selector"], binding["harness"]
    if selector == HARNESS_DEFAULT:
        return {**binding, "model": None, "family": None}
    family = policy.family(harness, selector) if selector in TIERS else selector
    try:
        model = ADAPTERS[harness].resolve_model(family, policy.probe)
    except HarnessError as error:
        raise RoleError(
            f"{error} To proceed without the catalog, set the {binding['role']} "
            f"role to {harness}:{HARNESS_DEFAULT} or name a complete model."
        ) from error
    return {**binding, "model": model, "family": family}


def describe(binding):
    """Say in one line what fills a role and why."""
    model = binding.get("model") or "the harness default model"
    text = f"{binding['role']}: {binding['harness']} with {model}"
    if binding["selector"] in TIERS:
        text += f" ({binding['selector']} tier)"
    return f"{text}, chosen by {binding['source']}"


def reviewer(policy, *, explicit=None, writer=None):
    """Bind the reviewer, preferring a vendor other than the last writer's."""
    writer = writer or {}
    binding = bind_model(
        resolve(
            "reviewer", policy, explicit=explicit, avoid_vendor=writer.get("vendor")
        ),
        policy,
    )
    if binding["vendor"] == writer.get("vendor"):
        binding["reductions"] = [
            f"The reviewer shares a vendor with {writer['description']}, "
            "so the review is less independent."
        ]
    return binding


def simplifier(policy, *, explicit=None):
    return bind_model(resolve("simplifier", policy, explicit=explicit), policy)


def consensus_pair(policy, *, a=None, b=None, harness_models=None):
    """Bind both consensus participants, from different vendors when possible.

    `harness_models` maps a harness to the model its participant must use,
    which is what the flags that predate role specs mean.
    """
    pinned = resolve("consensus-b", policy, explicit=b)
    first = resolve(
        "consensus-a",
        policy,
        explicit=a,
        avoid_vendor=pinned["vendor"] if pinned["source"] != "default" else None,
    )
    second = resolve("consensus-b", policy, explicit=b, avoid_vendor=first["vendor"])
    pair = {"a": first, "b": second}
    for harness, model in (harness_models or {}).items():
        if not model:
            continue
        slots = [slot for slot in pair if pair[slot]["harness"] == harness]
        if not slots:
            raise RoleError(
                f"A model was given for {harness}, and no consensus participant uses it."
            )
        for slot in slots:
            pair[slot] = {**pair[slot], "selector": model, "model_source": "flag"}
    pair = {slot: bind_model(binding, policy) for slot, binding in pair.items()}
    first, second = pair["a"], pair["b"]
    if first["harness"] != second["harness"] or first["model"] != second["model"]:
        if first["vendor"] == second["vendor"]:
            second["reductions"] = ["Both consensus participants come from one vendor."]
    elif "reports_model" in ADAPTERS[first["harness"]].capabilities:
        second["reductions"] = [
            "Same-model consensus: both participants use one harness and model."
        ]
    else:
        second["reductions"] = ["Same-harness consensus: model diversity is unverified."]
    return pair


def report(policy, writer=None):
    """Show what each role resolves to on this machine, and why.

    `writer` is who last changed the code, as `reviewer` takes it.
    """
    rows = {}

    def fill(build, *names):
        try:
            for role, binding in zip(names, build()):
                rows[role] = {
                    "status": "FILLED",
                    **binding,
                    "summary": describe(binding),
                }
        except RoleError as error:
            for role in names:
                rows[role] = {"status": "UNFILLED", "reason": str(error)}

    fill(lambda: [reviewer(policy, writer=writer)], "reviewer")
    fill(lambda: [simplifier(policy)], "simplifier")
    fill(lambda: consensus_pair(policy).values(), "consensus-a", "consensus-b")
    result = {
        "host": policy.host,
        "harnesses": policy.harnesses,
        "roles": rows,
        "configuration": {
            "user": str(user_config_path()),
            "project": policy.project_approval,
        },
    }
    state = (policy.project_approval or {}).get("state")
    if state == "invalid":
        result["configuration"]["note"] = (
            f"Factory ignores the role settings in {PROJECT_FILE}: "
            + policy.project_approval["reason"]
        )
    if state == "unapproved":
        result["configuration"]["note"] = (
            f"{PROJECT_FILE} sets roles or models that you have not approved, so "
            "Factory ignores them. Read them, then run `factory roles --approve`."
        )
    return result
