"""Install the thing the way the README says to, then run it.

The package split nearly shipped broken on a real machine while every unit test
passed, because the installed artifact is a symlink into a checkout and the shim
resolved the wrong side of it. Reading the diff could not find that. Building the
install and running it can.

So this constructs each install shape that actually exists in the wild and
exercises it end to end as a subprocess:

  copy      the documented `cp -R ./*`, what a new user does
  symlink   a checkout linked into ~/.hammerspoon, what a developer does
  partial   only extract.py copied, i.e. someone upgrading from the single-file
            version with a stale script. Must fail loudly and usefully.

What this file does NOT prove: that the shim resolves its own directory
correctly. Reverting realpath to abspath leaves every test here green, because
Python resolves sys.path[0] for a symlinked script and quietly rescues it. That
is the difference between "it works" and "it works for the reason we wrote".
tests/test_entrypoint.py asserts the second, and does go red on that revert.
Both are needed; neither replaces the other.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = "2026-08-06"
PAYLOAD = ["extract.py", "eod", "eod.lua", "init.lua"]


def run(script, cwd="/", home=None):
    """Run the installed entry point with an empty HOME.

    That makes ~/.claude empty, so these test the install wiring rather than
    re-parsing the developer's real transcript history, which took 15s a call.
    """
    env = dict(os.environ)
    env["HOME"] = home or tempfile.mkdtemp(prefix="eod-home-")
    env.pop("EOD_SOURCE_DIR", None)
    env["EOD_SOURCE_DIR"] = os.path.join(env["HOME"], "no-plugins")
    return subprocess.run([sys.executable, script, "--date", DAY],
                          cwd=cwd, capture_output=True, text=True, timeout=300, env=env)


class InstallCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="eod-install-")
        self.home = os.path.join(self.tmp, "hammerspoon")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDocumentedInstall(InstallCase):
    """`mkdir -p ~/.hammerspoon && cp -R ./* ~/.hammerspoon/`"""

    def _copy_install(self):
        for name in PAYLOAD:
            src = os.path.join(ROOT, name)
            dst = os.path.join(self.home, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
        return os.path.join(self.home, "extract.py")

    def test_a_copied_install_runs(self):
        r = run(self._copy_install())
        self.assertEqual(r.returncode, 0, r.stderr[-900:])

    def test_a_copied_install_is_self_contained(self):
        """It must not reach back into the checkout it was copied from."""
        script = self._copy_install()
        r = run(script)
        self.assertEqual(r.returncode, 0, r.stderr[-900:])
        self.assertNotIn(ROOT, r.stdout,
                         "a copied install wrote into the source checkout")
        self.assertIn(self.home, r.stdout)

    def test_a_copied_install_keeps_its_own_cache(self):
        script = self._copy_install()
        run(script)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "cache")))


class TestSymlinkInstall(InstallCase):
    """What a developer actually has: ~/.hammerspoon/extract.py -> checkout."""

    def _link_install(self):
        for name in PAYLOAD:
            os.symlink(os.path.join(ROOT, name), os.path.join(self.home, name))
        return os.path.join(self.home, "extract.py")

    def test_a_symlinked_install_runs(self):
        r = run(self._link_install())
        self.assertEqual(r.returncode, 0, r.stderr[-900:])
        self.assertNotIn("ModuleNotFoundError", r.stderr)

    def test_a_symlinked_install_uses_the_checkout_cache(self):
        """The link points at the checkout, so its cache is the checkout's. If
        this ever wrote beside the link instead, the widget would read one cache
        while the engine wrote another and the receipt would freeze."""
        r = run(self._link_install())
        self.assertIn(os.path.realpath(ROOT), r.stdout)
        self.assertFalse(os.path.isdir(os.path.join(self.home, "cache")))

    def test_extract_py_alone_symlinked_still_works(self):
        """The narrowest real case: only the entry point is linked, the package
        is not. This is what nearly shipped broken."""
        os.symlink(os.path.join(ROOT, "extract.py"),
                   os.path.join(self.home, "extract.py"))
        r = run(os.path.join(self.home, "extract.py"))
        self.assertEqual(r.returncode, 0, r.stderr[-900:])


class TestPartialInstall(InstallCase):
    """Someone upgrading from the single-file version whose script copies only
    extract.py. It cannot work, so it must say why."""

    def test_a_partial_install_fails_with_an_actionable_message(self):
        shutil.copy2(os.path.join(ROOT, "extract.py"),
                     os.path.join(self.home, "extract.py"))
        r = run(os.path.join(self.home, "extract.py"))
        self.assertNotEqual(r.returncode, 0, "a partial install must not appear to work")
        combined = r.stderr + r.stdout
        self.assertIn("eod", combined.lower())
        for hint in ("cp -R", "package"):
            self.assertIn(hint, combined,
                          "the error should tell the user how to fix it, got:\n%s"
                          % combined[-600:])


if __name__ == "__main__":
    unittest.main()
