import argparse
import hashlib
import os
from pathlib import Path
from statistics import median
import subprocess
import tempfile
import time


def sample(directory, argv):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        started = time.monotonic_ns()
        result = subprocess.run(
            argv, cwd=directory, stdin=subprocess.DEVNULL, stdout=output, stderr=errors
        )
        elapsed = (time.monotonic_ns() - started) / 1_000_000
        size = os.fstat(output.fileno()).st_size
        output.seek(0)
        row = dict(
            elapsed_ms=elapsed,
            returncode=result.returncode,
            stdout_bytes=size,
            stdout_sha256=hashlib.file_digest(output, "sha256").hexdigest(),
        )
        if result.returncode:
            errors.seek(max(0, os.fstat(errors.fileno()).st_size - 4096))
            row["stderr_tail"] = errors.read(4096).decode(errors="replace")
        return row


def compare(args):
    directories = {
        "before": args.before.resolve(strict=True),
        "after": args.after.resolve(strict=True),
    }
    if not all(directory.is_dir() for directory in directories.values()):
        raise ValueError("Each comparison input must be a directory")
    if directories["before"].samefile(directories["after"]):
        raise ValueError("Choose separate before and after directories")
    if args.trials < 1:
        raise ValueError("Expected at least one trial per checkout")
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        raise ValueError("Supply the command and its arguments after --")
    rows = []
    report = dict(
        command=argv,
        directories={k: str(v) for k, v in directories.items()},
        samples=rows,
    )
    for trial in range(args.trials):
        order = ("after", "before") if trial % 2 else ("before", "after")
        for side in order:
            try:
                measurement = sample(directories[side], argv)
            except OSError as error:
                return dict(
                    **report,
                    status="BLOCKED",
                    side=side,
                    trial=trial + 1,
                    error=str(error),
                ), 2
            row = dict(side=side, trial=trial + 1, **measurement)
            rows.append(row)
            if row["returncode"]:
                return dict(**report, status="COMMAND_FAILED"), 1
            if row["stdout_sha256"] != rows[0]["stdout_sha256"]:
                return dict(**report, status="OUTPUT_CHANGED"), 1
    timings = {}
    for side in directories:
        values = [r["elapsed_ms"] for r in rows if r["side"] == side]
        timings[side] = dict(min=min(values), median=median(values), max=max(values))
    return dict(**report, status="MATCH", elapsed_ms=timings), 0


def register(sub):
    parser = sub.add_parser(
        "compare",
        help="Replay a command in two directories and compare stdout and elapsed time",
    )
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Pairs of runs, alternating which directory runs first",
    )
    parser.add_argument(
        "argv", nargs=argparse.REMAINDER, help="Command and arguments after --"
    )
    parser.set_defaults(action=compare)
