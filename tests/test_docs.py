"""Keep the links in the repository's Markdown pointing at files and headings that exist."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#+\s+(.*)$", re.MULTILINE)


def anchors(markdown):
    return {
        re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        for title in HEADING.findall(markdown)
    }


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        pages = [p for p in ROOT.rglob("*.md") if ".git" not in p.parts]
        self.assertTrue(pages)
        broken = []
        for page in pages:
            for target in LINK.findall(page.read_text()):
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, anchor = target.partition("#")
                destination = (page.parent / path).resolve() if path else page
                if not destination.exists():
                    broken.append(f"{page.relative_to(ROOT)}: {target}")
                elif anchor and destination.suffix == ".md":
                    if anchor not in anchors(destination.read_text()):
                        broken.append(f"{page.relative_to(ROOT)}: {target}")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
