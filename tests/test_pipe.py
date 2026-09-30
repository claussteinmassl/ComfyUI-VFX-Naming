"""
Tests for the naming pipe: inheriting from an upstream node, overriding single
fields, and unpacking the result with the breakout node.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from test_flags import FLAGGED, FlaggedSchemaCase
from test_naming import engine, needs_node, node_pkg


def _node():
    return node_pkg.vfx_naming.VFXNamingConvention


def _parent(schema="vfx_default", strict=True, **tokens):
    """Run a main node: no pipe, own values only."""
    supplied = {"schema": schema, **tokens}
    return _node().execute(schema=supplied, strict=strict).result[0]


def _child(pipe, overrides=(), schema="vfx_default", strict=True, **own):
    """Run a node that receives `pipe` and overrides the named fields."""
    options = {k: own.pop(k) for k in list(own) if k in engine.OPTION_NAMES}
    options.setdefault("strict", strict)
    supplied = {"schema": schema, **own}
    return _node().execute(
        schema=supplied, naming_pipe=pipe,
        overrides=json.dumps(list(overrides)), **options).result[0]


@needs_node
class TestInheritance(unittest.TestCase):

    def test_a_child_without_overrides_equals_its_parent(self):
        for schema in ("vfx_default", "studio"):
            with self.subTest(schema=schema):
                parent = _parent(schema)
                child = _child(parent, schema=schema)
                self.assertEqual(child["result"]["filename_prefix"],
                                 parent["result"]["filename_prefix"])
                self.assertEqual(child["tokens"], parent["tokens"])

    def test_the_child_ignores_its_own_values_unless_overridden(self):
        parent = _parent(show="ABC")
        child = _child(parent, show="XYZ", task="roto")
        self.assertIn("ABC_", child["result"]["basename"])
        self.assertIn("_comp_", child["result"]["basename"])

    def test_the_schema_always_comes_from_the_pipe(self):
        parent = _parent("vfx_default")
        child = _child(parent, schema="studio")
        self.assertEqual(child["schema"], "vfx_default")

    def test_a_token_override(self):
        child = _child(_parent(), ["task"], task="roto")
        self.assertEqual(child["result"]["basename"], "SHW_SEQ_0010_roto_v001")

    def test_a_dropdown_override_carries_its_revealed_fields(self):
        child = _child(_parent(), ["task"], task={"task": "bg", "task_layer": 2})
        self.assertIn("_bg02_", child["result"]["basename"])

    def test_an_option_override(self):
        child = _child(_parent(), ["folders"], folders=False)
        self.assertEqual(child["result"]["filename_prefix"],
                         "SHW_SEQ_0010_comp_v001")

    def test_an_override_with_no_value_of_its_own_is_refused(self):
        """Listed as overridden but never actually supplied (e.g. the node's
        own schema does not carry that field) - must not silently inherit an
        empty/None value; it has to be refused like any other bad override."""
        with self.assertRaises(engine.NamingError) as caught:
            _child(_parent(), ["task"])
        self.assertIn("task", str(caught.exception))
        child = _child(_parent(strict=False), ["task"], strict=False)
        self.assertIn("task", child["result"]["report"])
        self.assertEqual(child["result"]["basename"], "SHW_SEQ_0010_comp_v001")

    def test_a_chain_of_three(self):
        parent = _parent(show="ABC")
        child = _child(parent, ["task"], task="roto")
        grandchild = _child(child, ["ext"], ext="png")
        self.assertEqual(grandchild["result"]["basename"], "ABC_SEQ_0010_roto_v001")
        self.assertEqual(grandchild["result"]["extension"], "png")

    def test_the_report_names_the_overrides(self):
        child = _child(_parent(), ["task"], task="roto")
        self.assertIn("Overrides", child["result"]["report"])
        self.assertIn(": task", child["result"]["report"])

    def test_an_unknown_override_is_strict_error_or_warning(self):
        with self.assertRaises(engine.NamingError) as caught:
            _child(_parent(), ["colorspace"], colorspace="acescg")
        self.assertIn("colorspace", str(caught.exception))
        child = _child(_parent(strict=False), ["colorspace"],
                       strict=False, colorspace="acescg")
        self.assertIn("colorspace", child["result"]["report"])

    def test_a_foreign_pipe_is_refused(self):
        for junk in ({"schema": "vfx_default"}, {"version": 2}, "pipe"):
            with self.subTest(junk=junk):
                with self.assertRaises(engine.NamingError):
                    _child(junk)

    def test_a_malformed_pipe_shape_is_refused(self):
        """A pipe with the right keys but the wrong value types must raise
        NamingError, not a TypeError from deeper inside the merge."""
        base = {"version": 1, "schema": "vfx_default", "tokens": {},
                "options": {}, "result": {}}
        for field, bad in (("schema", 5), ("tokens", "x"),
                           ("options", ["x"]), ("result", None)):
            with self.subTest(field=field):
                junk = dict(base, **{field: bad})
                with self.assertRaises(engine.NamingError):
                    _child(junk)

    def test_malformed_overrides_are_refused(self):
        with self.assertRaises(engine.NamingError):
            _node().execute(schema={"schema": "vfx_default"},
                            naming_pipe=_parent(), overrides="task,ext")


@needs_node
class TestLockedOverrides(FlaggedSchemaCase):

    def test_a_locked_token_cannot_be_overridden(self):
        parent = _parent("flagged")
        # FLAGGED hides strict and fixes it to False, so a locked override
        # becomes a warning; the value itself must still be inherited.
        child = _child(parent, ["show"], schema="flagged", show="XYZ")
        self.assertIn("SHW_", child["result"]["basename"])
        self.assertIn("show", child["result"]["report"])

    def test_a_locked_option_cannot_be_overridden(self):
        parent = _parent("flagged")
        child = _child(parent, ["folders"], schema="flagged", folders=False)
        self.assertIn("/", child["result"]["filename_prefix"])
        self.assertIn("folders", child["result"]["report"])
        self.assertIn("locked", child["result"]["report"])

    def test_a_hidden_option_cannot_be_overridden(self):
        parent = _parent("flagged")
        child = _child(parent, ["template_override"], schema="flagged",
                       template_override="{task}")
        self.assertEqual(child["result"]["basename"], "SHW_comp_v001")

    def test_a_hidden_token_cannot_be_overridden(self):
        """'mount' is hidden (visible: False), so it is locked like 'show' -
        FLAGGED also hides strict, so this is a warning, not a raise."""
        parent = _parent("flagged")
        child = _child(parent, ["mount"], schema="flagged", mount="/evil")
        self.assertIn("mount", child["result"]["report"])
        self.assertTrue(child["result"]["directory"].startswith("/mnt/proj/"))


# FLAGGED hides `strict` and fixes it to False, so TestLockedOverrides above
# only exercises the permissive (warning) path. This is FLAGGED with that one
# option restored to its default (visible, overridable, True), so a refused
# override can be seen raising in strict mode too.
FLAGGED_STRICT = copy.deepcopy(FLAGGED)
del FLAGGED_STRICT["options"]["strict"]
FLAGGED_STRICT["label"] = "Flagged strict"


class FlaggedStrictSchemaCase(unittest.TestCase):
    """Runs each test with `schemas/` replaced by a folder holding
    FLAGGED_STRICT under the key 'flagged_strict'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self._tmp.name, "flagged_strict.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(FLAGGED_STRICT, handle)
        patcher = mock.patch.object(engine, "SCHEMA_DIR", self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)


@needs_node
class TestLockedOverridesStrict(FlaggedStrictSchemaCase):

    def test_a_locked_token_override_raises_in_strict(self):
        parent = _parent("flagged_strict")
        with self.assertRaises(engine.NamingError) as caught:
            _child(parent, ["show"], schema="flagged_strict", show="XYZ")
        self.assertIn("show", str(caught.exception))

    def test_a_hidden_token_override_raises_in_strict(self):
        parent = _parent("flagged_strict")
        with self.assertRaises(engine.NamingError) as caught:
            _child(parent, ["mount"], schema="flagged_strict", mount="/evil")
        self.assertIn("mount", str(caught.exception))

    def test_a_locked_option_override_raises_in_strict(self):
        parent = _parent("flagged_strict")
        with self.assertRaises(engine.NamingError) as caught:
            _child(parent, ["folders"], schema="flagged_strict", folders=False)
        self.assertIn("folders", str(caught.exception))


@needs_node
class TestBreakout(unittest.TestCase):

    def breakout(self):
        return node_pkg.vfx_naming.VFXNamingBreakout

    def test_it_outputs_the_ten_results(self):
        info = self.breakout().GET_NODE_INFO_V1()
        self.assertEqual(list(info["output_name"]),
                         list(node_pkg.vfx_naming.RESULT_NAMES))
        self.assertEqual(list(info["output"]),
                         ["STRING"] * 8 + ["INT", "STRING"])
        self.breakout().define_schema().validate()

    def test_it_unpacks_the_pipe(self):
        pipe = _parent()
        values = self.breakout().execute(naming_pipe=pipe).result
        self.assertEqual(values, tuple(pipe["result"].values()))
        self.assertEqual(values[0], "SHW_SEQ_0010_comp_v001/SHW_SEQ_0010_comp_v001")

    def test_it_refuses_a_foreign_pipe(self):
        with self.assertRaises(engine.NamingError):
            self.breakout().execute(naming_pipe={"filename_prefix": "x"})
