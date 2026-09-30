"""
Tests for where schemas are loaded from: the built-in presets, the directories
in VFX_NAMING_SCHEMA_DIR and the ComfyUI user folder.

Run from the repository root, like the rest of the suite:

    COMFYUI_PATH=/path/to/ComfyUI python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_naming import _named, engine, needs_node, node_pkg


def _write(directory, key, label):
    """Write a minimal valid schema whose label identifies its origin."""
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, key + ".json"), "w", encoding="utf-8") as handle:
        json.dump({"label": label,
                   "tokens": {"show": {"label": "Show", "default": "abc"}},
                   "file": "{show}"}, handle)


class LocationCase(unittest.TestCase):
    """Three empty temp directories standing in for the three sources."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.builtin = os.path.join(tmp.name, "builtin")
        self.env_a = os.path.join(tmp.name, "env_a")
        self.env_b = os.path.join(tmp.name, "env_b")
        self.user = os.path.join(tmp.name, "user", "vfx_naming", "schemas")
        for path in (self.builtin, self.env_a, self.env_b):
            os.makedirs(path)
        self.enterContext(mock.patch.object(engine, "SCHEMA_DIR", self.builtin))
        self.enterContext(mock.patch.object(engine, "_user_schema_dir",
                                            lambda: self.user))
        self.set_env(self.env_a, self.env_b)

    def enterContext(self, patcher):
        """Start a patcher for the test's lifetime (unittest's own needs 3.11)."""
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def set_env(self, *dirs):
        value = os.pathsep.join(dirs)
        self.enterContext(mock.patch.dict(
            os.environ, {engine.SCHEMA_DIR_ENV: value}))


class TestPrecedence(LocationCase):

    def test_order_is_builtin_then_env_then_user(self):
        self.assertEqual(
            engine.schema_dirs(),
            [("built-in", self.builtin), ("studio", self.env_a),
             ("studio", self.env_b), ("user", self.user)])

    def test_env_beats_builtin(self):
        _write(self.builtin, "x", "builtin")
        _write(self.env_a, "x", "env")
        self.assertEqual(engine.load_schema("x").label, "env")

    def test_later_env_entry_beats_earlier(self):
        _write(self.env_a, "x", "env_a")
        _write(self.env_b, "x", "env_b")
        self.assertEqual(engine.load_schema("x").label, "env_b")

    def test_user_beats_env_and_builtin(self):
        _write(self.builtin, "x", "builtin")
        _write(self.env_b, "x", "env")
        _write(self.user, "x", "user")
        self.assertEqual(engine.load_schema("x").label, "user")

    def test_source_reports_kind_and_path(self):
        _write(self.builtin, "a", "a")
        _write(self.env_a, "b", "b")
        _write(self.user, "c", "c")
        self.assertEqual(engine.schema_source("a"),
                         ("built-in", os.path.join(self.builtin, "a.json")))
        self.assertEqual(engine.schema_source("b")[0], "studio")
        self.assertEqual(engine.schema_source("c")[0], "user")

    def test_unset_env_variable_adds_no_directories(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(engine.SCHEMA_DIR_ENV, None)
            kinds = [kind for kind, _ in engine.schema_dirs()]
        self.assertEqual(kinds, ["built-in", "user"])


class TestMissingSchema(LocationCase):

    def test_unknown_key_raises_and_lists_searched_directories(self):
        with self.assertRaises(engine.NamingError) as caught:
            engine.load_schema("nope")
        message = str(caught.exception)
        self.assertIn("nope", message)
        for path in (self.builtin, self.env_a, self.env_b, self.user):
            self.assertIn(path, message)

    def test_vfx_default_falls_back_to_the_embedded_json(self):
        config = engine.load_schema("vfx_default")
        self.assertEqual(config.label, "VFX default")
        self.assertEqual(engine.schema_names(), ["vfx_default"])

    def test_a_vfx_default_file_wins_over_the_embedded_json(self):
        _write(self.user, "vfx_default", "custom default")
        self.assertEqual(engine.load_schema("vfx_default").label, "custom default")


class TestDropdown(LocationCase):

    def test_default_first_rest_sorted_without_duplicates(self):
        for key in ("zeta", "vfx_default", "alpha"):
            _write(self.builtin, key, key)
        _write(self.user, "alpha", "override")
        _write(self.env_a, "mid", "mid")
        self.assertEqual(engine.schema_names(),
                         ["vfx_default", "alpha", "mid", "zeta"])


class TestUserDirectory(unittest.TestCase):

    def _folder_paths(self, base):
        module = types.ModuleType("folder_paths")
        module.get_user_directory = lambda: base
        return module

    def test_missing_directory_is_created(self):
        with tempfile.TemporaryDirectory() as base:
            with mock.patch.dict(sys.modules,
                                 {"folder_paths": self._folder_paths(base)}):
                path = engine._user_schema_dir()
            self.assertEqual(path, os.path.join(base, "vfx_naming", "schemas"))
            self.assertTrue(os.path.isdir(path))

    def test_without_folder_paths_the_user_source_is_skipped(self):
        with mock.patch.dict(sys.modules, {"folder_paths": None}):
            self.assertIsNone(engine._user_schema_dir())
            with mock.patch.dict(os.environ):
                os.environ.pop(engine.SCHEMA_DIR_ENV, None)
                kinds = [kind for kind, _ in engine.schema_dirs()]
        self.assertEqual(kinds, ["built-in"])

    def test_a_failure_to_create_the_directory_does_not_raise(self):
        with tempfile.TemporaryDirectory() as base:
            blocker = os.path.join(base, "file")
            open(blocker, "w").close()
            with mock.patch.dict(sys.modules,
                                 {"folder_paths": self._folder_paths(blocker)}):
                self.assertIsNone(engine._user_schema_dir())


@needs_node
class TestReportSource(LocationCase):

    def test_report_names_the_source(self):
        _write(self.user, "x", "user schema")
        result = _named("x", {})
        self.assertIn(f"Source : user ({os.path.join(self.user, 'x.json')})",
                      result["report"])


if __name__ == "__main__":
    unittest.main()
