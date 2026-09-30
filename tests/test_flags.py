"""
Tests for the schema flags: which fields a node shows and which a downstream
node may override.

Run from the repository root, like the rest of the suite:

    COMFYUI_PATH=/path/to/ComfyUI python3 -m unittest discover -s tests
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from test_naming import _named, engine, needs_node, node_pkg


class TestTokenFlags(unittest.TestCase):

    def test_flags_default_to_true(self):
        spec = engine.TokenSpec("t", {})
        self.assertTrue(spec.visible)
        self.assertTrue(spec.overridable)

    def test_a_hidden_token_is_never_overridable(self):
        spec = engine.TokenSpec("t", {"visible": False, "overridable": True})
        self.assertFalse(spec.visible)
        self.assertFalse(spec.overridable)

    def test_a_locked_token_stays_visible(self):
        spec = engine.TokenSpec("t", {"overridable": False})
        self.assertTrue(spec.visible)
        self.assertFalse(spec.overridable)

    def test_a_flag_must_be_a_boolean(self):
        for key in ("visible", "overridable"):
            with self.subTest(flag=key):
                with self.assertRaises(engine.NamingError) as caught:
                    engine.TokenSpec("t", {key: "no"})
                self.assertIn(key, str(caught.exception))

    def test_overridable_is_validated_even_when_hidden(self):
        with self.assertRaises(engine.NamingError) as caught:
            engine.TokenSpec("t", {"visible": False, "overridable": "no"})
        self.assertIn("overridable", str(caught.exception))


class TestOptionFlags(unittest.TestCase):

    def schema(self, **data):
        return engine.Schema("k", data)

    def test_every_option_defaults_to_visible_and_overridable(self):
        schema = self.schema()
        for name in engine.OPTION_NAMES:
            with self.subTest(option=name):
                self.assertEqual(schema.option_flags(name), {
                    "visible": True, "overridable": True,
                    "value": engine.OPTION_DEFAULTS[name]})

    def test_the_options_block_sets_flags_and_value(self):
        schema = self.schema(options={
            "strict": {"visible": False, "value": False},
            "folders": {"overridable": False}})
        self.assertEqual(schema.option_flags("strict"),
                         {"visible": False, "overridable": False, "value": False})
        self.assertEqual(schema.option_flags("folders"),
                         {"visible": True, "overridable": False, "value": True})

    def test_an_unknown_option_is_rejected(self):
        with self.assertRaises(engine.NamingError) as caught:
            self.schema(options={"stirct": {"visible": False}})
        self.assertIn("stirct", str(caught.exception))

    def test_an_unknown_flag_is_rejected(self):
        with self.assertRaises(engine.NamingError) as caught:
            self.schema(options={"strict": {"visibel": False}})
        self.assertIn("visibel", str(caught.exception))

    def test_a_non_boolean_option_flag_is_rejected(self):
        with self.assertRaises(engine.NamingError):
            self.schema(options={"strict": {"visible": 0}})

    def test_option_overridable_is_validated_even_when_hidden(self):
        with self.assertRaises(engine.NamingError) as caught:
            self.schema(options={"strict": {"visible": False, "overridable": "no"}})
        self.assertIn("overridable", str(caught.exception))

    def test_a_token_may_not_share_a_name_with_an_option(self):
        with self.assertRaises(engine.NamingError) as caught:
            self.schema(tokens={"folders": {}})
        self.assertIn("folders", str(caught.exception))

    def test_effective_options_fix_hidden_ones(self):
        schema = self.schema(options={
            "strict": {"visible": False, "value": False},
            "template_override": {"visible": False}})
        effective = schema.effective_options({
            "strict": True, "template_override": "{show}", "folders": False})
        self.assertEqual(effective["strict"], False)            # schema value
        self.assertEqual(effective["template_override"], "")    # input default
        self.assertEqual(effective["folders"], False)           # supplied
        self.assertEqual(effective["parent_path"], "")          # default

    def test_the_shipped_schemas_all_load_with_flags(self):
        for key in engine.schema_names():
            with self.subTest(schema=key):
                engine.load_schema(key).option_flags("strict")
