#!/usr/bin/env python3
"""Install an immutable copy of the Factory skill and CLI on a POSIX host."""

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys

if os.name != "posix" or sys.version_info < (3, 11):
    sys.exit("Installing Software Factory requires macOS or Linux with Python 3.11+")

SOURCE = Path(__file__).resolve().parent / "skills/software-factory"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / "scripts"))
from installation import checkout_origin, install, installation_lock  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--skill-dir", action="append", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rollback", action="store_true")
    group.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    with nullcontext() if args.dry_run else installation_lock(prefix):
        origin = (
            None if args.rollback or args.remove else checkout_origin(SOURCE.parents[1])
        )
        report = install(
            prefix,
            SOURCE,
            skill_dirs=args.skill_dir,
            origin=origin,
            rollback=args.rollback,
            remove=args.remove,
            dry_run=args.dry_run,
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(str(exc))
