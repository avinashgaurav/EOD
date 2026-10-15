"""The gate: every promise in the docs must have a test, and vice versa.

This exists because "write the docs after the code, and check them" is advice,
and advice does not survive a long session. A build failure does.

    docs/plugins.md    <!--claim:source-failure-visible-->
    test_claims.py     CLAIM_source_failure_visible = "source-failure-visible"

If a claim appears in one and not the other, this fails. So:

  * adding a sentence to the docs that promises behaviour, without a test that
    proves it, breaks the build
  * deleting the behaviour without touching the docs breaks the build, because
    its test goes red first
  * deleting a test while leaving the promise standing breaks the build here

It cannot verify prose nobody marked up. What it does guarantee is that the
marked claims stay honest, and marking one is cheaper than arguing about it.

The claims used to live in README.md. They moved to docs/ when the README was
trimmed. CLAIM_DOCS is an explicit list, not a glob: a marker in a file nobody
listed is not scanned, so its test shows up as an orphan and fails the build.
"""

import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIM_DOCS = [os.path.join(ROOT, p) for p in (
    "README.md",
    "docs/how-it-works.md",
    "docs/privacy.md",
    "docs/configuration.md",
    "docs/plugins.md",
)]
CLAIMS_TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_claims.py")

MARKER = re.compile(r"<!--\s*claim:([a-z0-9-]+)\s*-->")
DECLARED = re.compile(r"^\s*CLAIM_[a-z0-9_]+\s*=\s*[\"']([a-z0-9-]+)[\"']", re.M)


def all_markers():
    """Every marker across CLAIM_DOCS, duplicates kept. A missing file raises."""
    found = []
    for path in CLAIM_DOCS:
        with open(path, encoding="utf-8") as f:
            found += MARKER.findall(f.read())
    return found


def doc_claims():
    return set(all_markers())


def tested_claims():
    with open(CLAIMS_TEST, encoding="utf-8") as f:
        return set(DECLARED.findall(f.read()))


class TestClaimCoverage(unittest.TestCase):

    def test_every_readme_claim_has_a_test(self):
        missing = sorted(doc_claims() - tested_claims())
        self.assertEqual(missing, [], (
            "The docs promise behaviour with no test proving it: %s\n"
            "Add a test to tests/test_claims.py declaring "
            "CLAIM_<name> = \"<claim>\", or remove the promise.\n"
            "This is the exact failure mode the gate exists for: the doc was "
            "written before the last mile of the code." % ", ".join(missing)))

    def test_every_test_claim_is_actually_promised(self):
        orphans = sorted(tested_claims() - doc_claims())
        self.assertEqual(orphans, [], (
            "tests/test_claims.py proves claims the docs no longer make: %s\n"
            "Either restore the <!--claim:...--> marker or drop the test." %
            ", ".join(orphans)))

    def test_the_gate_is_not_trivially_empty(self):
        """A gate guarding nothing passes forever and protects nothing."""
        self.assertGreaterEqual(len(doc_claims()), 8,
                                "suspiciously few marked claims; has the markup been lost?")

    def test_every_doc_with_a_claim_is_listed(self):
        """A marker in a docs file missing from CLAIM_DOCS is never scanned, so
        a new claim there would ship with no test. Listing the file is the fix."""
        listed = {os.path.abspath(p) for p in CLAIM_DOCS}
        unlisted = []
        for path in sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))):
            with open(path, encoding="utf-8") as f:
                if MARKER.search(f.read()) and os.path.abspath(path) not in listed:
                    unlisted.append(os.path.relpath(path, ROOT))
        self.assertEqual(unlisted, [], (
            "claim markers in files the gate does not scan: %s\n"
            "Add them to CLAIM_DOCS in tests/test_claim_coverage.py." %
            ", ".join(unlisted)))

    def test_markers_are_unique(self):
        found = all_markers()
        dupes = sorted({c for c in found if found.count(c) > 1})
        self.assertEqual(dupes, [], "duplicate claim markers: %s" % ", ".join(dupes))


if __name__ == "__main__":
    unittest.main()
