import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts")
)
import roles  # noqa: E402
from harness import ADAPTERS  # noqa: E402

OTHER_FAMILY_FIRST = {"slug": "gpt-9.2-sol", "visibility": "list", "priority": 1}
CURRENT_ASTRA = {"slug": "gpt-9.2-astra", "visibility": "list", "priority": 2}
HIDDEN_ASTRA = {"slug": "gpt-9.3-astra", "visibility": "hide", "priority": 0}
RETIRED_ASTRA = {
    "slug": "gpt-9.4-astra",
    "visibility": "list",
    "priority": 0,
    "upgrade": {"retirement_at": "2020-01-01T00:00:00"},
}
OLDER_ASTRA = {"slug": "gpt-9.1-astra", "visibility": "list", "priority": 6}
RETIRED_NAMED_LIKE_ITS_FAMILY = {
    "slug": "luna",
    "visibility": "hide",
    "priority": 0,
    "upgrade": {"retirement_at": "2020-01-01T00:00:00Z"},
}
CURRENT_LUNA = {"slug": "gpt-9-luna", "visibility": "list", "priority": 7}
UNHYPHENATED = {"slug": "o9", "visibility": "list", "priority": 9}
UNHYPHENATED_SIBLING = {"slug": "o9-pro", "visibility": "list", "priority": 8}
CATALOG = [
    OTHER_FAMILY_FIRST,
    CURRENT_ASTRA,
    HIDDEN_ASTRA,
    RETIRED_ASTRA,
    OLDER_ASTRA,
    UNHYPHENATED,
    UNHYPHENATED_SIBLING,
    RETIRED_NAMED_LIKE_ITS_FAMILY,
    CURRENT_LUNA,
]


def harnesses(*names):
    return {
        name: {
            "available": name in names,
            "path": f"/fake/{name}" if name in names else None,
            "version": "fixture",
            "authenticated": name in names,
            "vendor": adapter.vendor,
            "capabilities": sorted(adapter.capabilities),
        }
        for name, adapter in ADAPTERS.items()
    }


def use_machine(test, *names, host=None, catalog=CATALOG):

    def probe(argv):
        if argv[:3] == ["codex", "debug", "models"] and catalog is not None:
            return 0, json.dumps({"models": catalog})
        return 2, ""

    for target, value in (
        ("installed", lambda: harnesses(*names)),
        ("detect_host", lambda: {"harness": host, "evidence": "fixture"}),
        ("probe", probe),
    ):
        patcher = patch.object(roles, target, value)
        patcher.start()
        test.addCleanup(patcher.stop)
    which = patch.object(
        roles.shutil, "which", lambda name: f"/fake/{name}" if name in names else None
    )
    which.start()
    test.addCleanup(which.stop)
