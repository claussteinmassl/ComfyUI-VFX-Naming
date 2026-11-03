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


def _write(directory, key, label, builtin=True):
    """Write a minimal valid schema whose label identifies its origin.

    `builtin` marks it as a preset; it only matters in the node's folder.
    """
    os.makedirs(directory, exist_ok=True)
    data = {"label": label,
            "tokens": {"show": {"label": "Show", "default": "abc"}},
            "file": "{show}"}
    if builtin:
        data["builtin"] = True
    with open(os.path.join(directory, key + ".json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle)


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
        for key in ("zeta", "vfx_default", "studio", "alpha"):
            _write(self.builtin, key, key)
        _write(self.user, "alpha", "override")
        _write(self.env_a, "mid", "mid")
        self.assertEqual(engine.schema_names(),
                         ["studio", "alpha", "mid", "vfx_default", "zeta"])


class TestBuiltinSwitch(LocationCase):
    """VFX_NAMING_BUILTIN_SCHEMAS turns the shipped presets off."""

    def setUp(self):
        super().setUp()
        _write(self.builtin, "vfx_default", "shipped default")
        _write(self.builtin, "studio", "shipped studio")
        _write(self.user, "kundex", "user schema")

    def switch(self, value):
        self.enterContext(mock.patch.dict(
            os.environ, {engine.BUILTIN_SCHEMAS_ENV: value}))

    def test_on_by_default(self):
        self.assertIn("studio", engine.schema_names())

    def test_off_leaves_only_studio_and_user_schemas(self):
        _write(self.env_a, "share", "studio share")
        for value in ("0", "false", "No", "OFF"):
            with self.subTest(value=value):
                self.switch(value)
                self.assertEqual(engine.schema_names(), ["kundex", "share"])

    def test_any_other_value_keeps_them(self):
        self.switch("1")
        self.assertIn("vfx_default", engine.schema_names())

    def test_a_user_file_with_a_builtin_name_stays(self):
        _write(self.user, "studio", "user studio")
        self.switch("0")
        self.assertEqual(engine.load_schema("studio").label, "user studio")

    def test_loading_a_switched_off_preset_says_why(self):
        self.switch("0")
        for key in ("studio", "vfx_default"):
            with self.subTest(key=key):
                with self.assertRaises(engine.NamingError) as caught:
                    engine.load_schema(key)
                self.assertIn(engine.BUILTIN_SCHEMAS_ENV, str(caught.exception))

    def test_an_unmarked_file_in_the_node_folder_stays(self):
        """A studio commits its own schema next to the presets."""
        _write(self.builtin, "atk", "client schema", builtin=False)
        self.switch("0")
        self.assertEqual(engine.schema_names(), ["atk", "kundex"])
        self.assertEqual(engine.schema_source("atk")[0], "node")
        self.assertEqual(engine.load_schema("atk").label, "client schema")

    def test_the_marker_counts_only_in_the_node_folder(self):
        """A preset copied to the user folder as a template is not hidden."""
        _write(self.user, "copied", "copy of a preset", builtin=True)
        self.switch("0")
        self.assertIn("copied", engine.schema_names())

    def test_a_marked_file_is_reported_as_built_in(self):
        self.assertEqual(engine.schema_source("studio")[0], "built-in")

    def test_no_schema_left_offers_a_placeholder_that_explains(self):
        self.switch("0")
        os.remove(os.path.join(self.user, "kundex.json"))
        self.assertEqual(engine.schema_names(), [engine.NO_SCHEMA])
        with self.assertRaises(engine.NamingError) as caught:
            engine.load_schema(engine.NO_SCHEMA)
        self.assertIn("No schema found", str(caught.exception))


class TestShippedPresets(unittest.TestCase):

    # Listed by name: a studio's own unmarked file in schemas/ must not fail
    # this test in its copy of the repo.
    PRESETS = ("episodic_dotted", "studio", "studio_nested", "vfx_default",
               "vfx_flat")

    def test_every_shipped_preset_is_marked(self):
        """Unmarked, a preset would survive VFX_NAMING_BUILTIN_SCHEMAS=0."""
        folder = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "schemas")
        for key in self.PRESETS:
            with self.subTest(schema=key):
                self.assertTrue(engine.is_preset(os.path.join(folder, f"{key}.json")))

    def test_the_embedded_default_is_marked(self):
        self.assertIs(json.loads(engine.DEFAULT_SCHEMA_JSON)["builtin"], True)


class TestDefaultSchema(LocationCase):
    """VFX_NAMING_DEFAULT_SCHEMA picks the schema a new node starts on."""

    def setUp(self):
        super().setUp()
        for key in ("alpha", "studio", "zeta"):
            _write(self.builtin, key, key)

    def default(self, value):
        self.enterContext(mock.patch.dict(
            os.environ, {engine.DEFAULT_SCHEMA_ENV: value}))

    def test_studio_leads_without_the_variable(self):
        self.assertEqual(engine.schema_names()[0], "studio")

    def test_the_variable_moves_its_schema_first(self):
        self.default("zeta")
        self.assertEqual(engine.schema_names(), ["zeta", "alpha", "studio"])

    def test_an_unknown_default_falls_back_to_sorted(self):
        self.default("nope")
        self.assertEqual(engine.schema_names(), ["alpha", "studio", "zeta"])


@needs_node
class TestNoSchemaNode(LocationCase):

    def test_the_node_still_loads_and_running_it_explains(self):
        self.enterContext(mock.patch.dict(
            os.environ, {engine.BUILTIN_SCHEMAS_ENV: "0"}))
        option = node_pkg.vfx_naming._schema_option(engine.NO_SCHEMA)
        self.assertEqual(option.inputs, [])
        self.assertNotIn(engine.NO_SCHEMA, node_pkg.vfx_naming.schema_meta())
        result = node_pkg.vfx_naming.preview({"schema": engine.NO_SCHEMA})
        self.assertFalse(result["ok"])
        self.assertIn("No schema found", result["error"])


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
