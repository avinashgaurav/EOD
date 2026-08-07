"""The gate: every promise in README.md must have a test, and vice versa.

This exists because "write the docs after the code, and check them" is advice,
and advice does not survive a long session. A build failure does.

    README.md          <!--claim:source-failure-visible-->
    test_claims.py     CLAIM_source_failure_visible = "source-failure-visible"

If a claim appears in one and not the other, this fails. So:

  * adding a sentence to the README that promises behaviour, without a test that
    proves it, breaks the build
  * deleting the behaviour without touching the README breaks the build, because
    its test goes red first
  * deleting a test while leaving the promise standing breaks the build here

It cannot verify prose nobody marked up. What it does guarantee is that the
marked claims stay honest, and marking one is cheaper than arguing about it.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
CLAIMS_TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_claims.py")

MARKER = re.compile(r"<!--\s*claim:([a-z0-9-]+)\s*-->")
DECLARED = re.compile(r"^\s*CLAIM_[a-z0-9_]+\s*=\s*[\"']([a-z0-9-]+)[\"']", re.M)


def readme_claims():
    with open(README, encoding="utf-8") as f:
        return set(MARKER.findall(f.read()))


def tested_claims():
    with open(CLAIMS_TEST, encoding="utf-8") as f:
        return set(DECLARED.findall(f.read()))


class TestClaimCoverage(unittest.TestCase):

    def test_every_readme_claim_has_a_test(self):
        missing = sorted(readme_claims() - tested_claims())
        self.assertEqual(missing, [], (
            "README.md promises behaviour with no test proving it: %s\n"
            "Add a test to tests/test_claims.py declaring "
            "CLAIM_<name> = \"<claim>\", or remove the promise.\n"
            "This is the exact failure mode the gate exists for: the doc was "
            "written before the last mile of the code." % ", ".join(missing)))

    def test_every_test_claim_is_actually_promised(self):
        orphans = sorted(tested_claims() - readme_claims())
        self.assertEqual(orphans, [], (
            "tests/test_claims.py proves claims the README no longer makes: %s\n"
            "Either restore the <!--claim:...--> marker or drop the test." %
            ", ".join(orphans)))

    def test_the_gate_is_not_trivially_empty(self):
        """A gate guarding nothing passes forever and protects nothing."""
        self.assertGreaterEqual(len(readme_claims()), 8,
                                "suspiciously few marked claims; has the markup been lost?")

    def test_markers_are_unique(self):
        with open(README, encoding="utf-8") as f:
            found = MARKER.findall(f.read())
        dupes = sorted({c for c in found if found.count(c) > 1})
        self.assertEqual(dupes, [], "duplicate claim markers: %s" % ", ".join(dupes))


if __name__ == "__main__":
    unittest.main()
