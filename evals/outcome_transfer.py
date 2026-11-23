"""Replay a synthetic keyboard correction across two repositories in real Chrome."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from qualify import FACTORY, WEB, WEB_CHECK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="New directory for checkouts and receipts"
    )
    out = parser.parse_args().output.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = {**os.environ, "FACTORY_STATE_DIR": str(out / "state")}
    keyboard = out / "keyboard.cjs"
    keyboard.write_text(WEB_CHECK)
    pointer = out / "pointer.cjs"
    pointer.write_text("""
const assert = require('node:assert/strict');
const {chromium} = require(process.env.FACTORY_PLAYWRIGHT || 'playwright');
const {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(process.cwd() + '/index.html').href);
    const panel = page.locator('#details');
    assert.equal(await panel.isVisible(), false);
    await page.getByRole('button', {name: 'Show details'}).click();
    assert.equal(await panel.isVisible(), true);
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
""")
    report = {}

    def invoke(repo, *args, expected=0):
        p = subprocess.run(
            [FACTORY, *args], cwd=repo, env=env, capture_output=True, text=True
        )
        if p.returncode != expected:
            raise RuntimeError(
                f"factory {args[0]} exited {p.returncode}: {p.stdout} {p.stderr}"
            )
        return json.loads(p.stdout)

    def check(repo, claim, expect, argv, expected=0):
        contract = out / f"{repo.name}-{claim}.json"
        contract.write_text(json.dumps([dict(id=claim, expect=expect, argv=argv)]))
        run = invoke(repo, "start", "--task", expect, "--contract", contract)["run"]
        return invoke(repo, "check", run, expected=expected)

    def checkout(name):
        repo = out / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        return repo

    # The second implementation has a focusable span and supports Enter. Space is missing.
    other = """<button>Show details</button><section id="details" hidden>Settings</section>
<script>
const button = document.querySelector('button');
button.setAttribute('aria-expanded', 'false');
button.onclick = () => {
  const panel = document.querySelector('section');
  panel.hidden = !panel.hidden;
  button.setAttribute('aria-expanded', String(!panel.hidden));
};
</script>"""
    broken = (
        other.replace("<button>", '<span role="button" tabindex="0">')
        .replace("</button>", "</span>")
        .replace("querySelector('button')", "querySelector('span')")
        .replace(
            "</script>",
            "button.onkeydown = e => { if (e.key === 'Enter') button.click(); };\n</script>",
        )
    )
    for name, source in (("release-notes", WEB), ("settings", broken)):
        repo = checkout(name)
        page = repo / "index.html"
        page.write_text(source)
        old = check(
            repo, "pointer", "Pointer expands the disclosure", ["node", str(pointer)]
        )
        failed = check(
            repo,
            "keyboard",
            "Keyboard and pointer operate the disclosure",
            ["node", str(keyboard)],
            1,
        )
        log = Path(failed["artifacts"]) / failed["claims"]["keyboard"]["latest"]["log"]
        if "Space expands" not in log.read_text():
            raise RuntimeError(f"Expected a keyboard behavior failure. Inspect {log}")
        if name == "release-notes":
            outcome = invoke(
                repo,
                "outcome",
                old["run"],
                "--note",
                "Pointer passed, but Space failed to open the disclosure.",
                "--evidence",
                str(log),
            )
            report["observation"] = dict(
                run=old["run"], id=outcome["outcome"]["id"], subject=old["subject"]
            )
        page.write_text(
            other
            if name == "settings"
            else WEB.replace(
                '<a href="#details" id="open" role="button"', '<button id="open"'
            ).replace("</a>", "</button>")
        )
        repaired = invoke(repo, "check", failed["run"])
        report[name] = dict(
            pointer=old["status"],
            keyboard=failed["status"],
            repaired=repaired["status"],
            run=failed["run"],
        )

    repo = checkout("command-line")
    (repo / "version.py").write_text("print('v1')\n")
    result = check(
        repo,
        "version",
        "CLI prints v1",
        [
            sys.executable,
            "-E",
            "-c",
            "import subprocess,sys; assert subprocess.check_output([sys.executable,'version.py']).strip()==b'v1'",
        ],
    )
    report["unrelated"] = dict(
        status=result["status"], claims=list(result["claims"]), run=result["run"]
    )
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
