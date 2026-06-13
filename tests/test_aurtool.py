"""Unit tests for aurtool's pure logic.

None of these require a live AUR, pacman, or makepkg. Subprocess-backed
helpers (vercmp) are tested by monkeypatching the runner.
"""

import importlib.util
import os
import unittest
from unittest import mock

# Load the extension-less `aurtool` script as a module.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_HERE, "..", "aurtool")
_spec = importlib.util.spec_from_loader(
    "aurtool", importlib.machinery.SourceFileLoader("aurtool", _SCRIPT)
)
aurtool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aurtool)


class ParseSrcinfoTest(unittest.TestCase):
    def test_basic(self):
        text = """
pkgbase = foo
\tpkgver = 1.2.3
\tpkgrel = 2
\tdepends = glibc>=2.38
\tdepends = bar
\tmakedepends = cmake

pkgname = foo
"""
        info = aurtool.parse_srcinfo(text)
        self.assertEqual(info["pkgbase"], "foo")
        self.assertEqual(info["pkgver"], "1.2.3")
        self.assertEqual(info["pkgrel"], "2")
        self.assertEqual(info["version"], "1.2.3-2")
        self.assertEqual(info["pkgname"], ["foo"])
        self.assertIn("glibc", info["depends"])
        self.assertIn("bar", info["depends"])
        self.assertEqual(info["makedepends"], ["cmake"])

    def test_epoch(self):
        text = "pkgbase = x\nepoch = 1\npkgver = 2.0\npkgrel = 1\npkgname = x\n"
        info = aurtool.parse_srcinfo(text)
        self.assertEqual(info["version"], "1:2.0-1")

    def test_split_package(self):
        text = (
            "pkgbase = base\npkgver = 1\npkgrel = 1\n"
            "pkgname = first\npkgname = second\n"
        )
        info = aurtool.parse_srcinfo(text)
        self.assertEqual(info["pkgbase"], "base")
        self.assertEqual(info["pkgname"], ["first", "second"])

    def test_pkgbase_falls_back_to_first_pkgname(self):
        text = "pkgname = only\npkgver = 1\npkgrel = 1\n"
        info = aurtool.parse_srcinfo(text)
        self.assertEqual(info["pkgbase"], "only")

    def test_missing_version_is_none(self):
        info = aurtool.parse_srcinfo("pkgbase = foo\npkgname = foo\n")
        self.assertIsNone(info["version"])

    def test_dep_name_stripping(self):
        self.assertEqual(aurtool._dep_name("glibc>=2.38"), "glibc")
        self.assertEqual(aurtool._dep_name("foo=1.0"), "foo")
        self.assertEqual(aurtool._dep_name("bar<3"), "bar")
        self.assertEqual(aurtool._dep_name("baz: an optional dep"), "baz")
        self.assertEqual(aurtool._dep_name("plain"), "plain")


class VercmpTest(unittest.TestCase):
    def _fake_run(self, stdout):
        m = mock.Mock()
        m.stdout = stdout
        m.stderr = ""
        m.returncode = 0
        return m

    def test_signs(self):
        with mock.patch.object(aurtool, "_run", return_value=self._fake_run("-1\n")):
            self.assertEqual(aurtool.vercmp("1.0-1", "1.0-2"), -1)
        with mock.patch.object(aurtool, "_run", return_value=self._fake_run("0\n")):
            self.assertEqual(aurtool.vercmp("1.0-1", "1.0-1"), 0)
        with mock.patch.object(aurtool, "_run", return_value=self._fake_run("1\n")):
            self.assertEqual(aurtool.vercmp("2.0-1", "1.0-1"), 1)

    def test_normalizes_large_values(self):
        # vercmp can emit values other than -1/0/1; normalize to sign.
        with mock.patch.object(aurtool, "_run", return_value=self._fake_run("5\n")):
            self.assertEqual(aurtool.vercmp("9.0", "1.0"), 1)


class BuildOrderTest(unittest.TestCase):
    def test_dependency_first(self):
        order, cycle = aurtool.build_order(["app", "lib"], {"app": {"lib"}, "lib": set()})
        self.assertLess(order.index("lib"), order.index("app"))
        self.assertFalse(cycle)

    def test_no_deps_preserves_order(self):
        order, cycle = aurtool.build_order(["a", "b", "c"], {})
        self.assertEqual(order, ["a", "b", "c"])
        self.assertFalse(cycle)

    def test_cycle_detected(self):
        order, cycle = aurtool.build_order(["a", "b"], {"a": {"b"}, "b": {"a"}})
        self.assertTrue(cycle)
        self.assertEqual(sorted(order), ["a", "b"])

    def test_external_deps_ignored(self):
        order, cycle = aurtool.build_order(["a"], {"a": {"glibc"}})
        self.assertEqual(order, ["a"])
        self.assertFalse(cycle)


class StateRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = __import__("tempfile").mkdtemp()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        __import__("shutil").rmtree(self._tmp, ignore_errors=True)

    def test_load_default_when_absent(self):
        state = aurtool.load_state()
        self.assertEqual(state["packages"], {})
        self.assertEqual(state["version"], aurtool.STATE_VERSION)

    def test_save_then_load(self):
        state = {"version": 1, "packages": {"foo": {"approved_commit": "abc123"}}}
        aurtool.save_state(state)
        self.assertTrue(os.path.exists(aurtool.STATE_FILE))
        loaded = aurtool.load_state()
        self.assertEqual(loaded["packages"]["foo"]["approved_commit"], "abc123")

    def test_save_is_atomic_no_temp_left(self):
        aurtool.save_state({"version": 1, "packages": {}})
        leftovers = [f for f in os.listdir(".") if f.startswith(".aurtool.")]
        self.assertEqual(leftovers, [])


class ReviewLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(aurtool.review_label({"present": False}), "MISSING")
        self.assertEqual(
            aurtool.review_label({"present": True, "approved": None, "reviewed": False}),
            "UNREVIEWED",
        )
        self.assertEqual(
            aurtool.review_label({"present": True, "approved": "x", "reviewed": False}),
            "CHANGED",
        )
        self.assertEqual(
            aurtool.review_label({"present": True, "approved": "x", "reviewed": True}),
            "reviewed",
        )


if __name__ == "__main__":
    unittest.main()
