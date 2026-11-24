"""
Tests for schema outputs: one schema with several output variants (e.g. an
image sequence and a movie) that share its tokens, and how a node in a pipe
chain chooses one.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from test_naming import engine, needs_node, node_pkg
from test_naming import setUpModule, tearDownModule  # noqa: F401

SHOTS = {
    "label": "Shots",
    "tokens": {
        "show": {"default": "ORB"},
        "seq": {"type": "int", "pad": 3, "prefix": "sq", "default": 10},
        "shot": {"type": "int", "pad": 4, "prefix": "sh", "default": 40},
        "name": {"default": "imggen", "presets": ["imggen", "vidgen", "upscale"]},
        "version": {"type": "int", "pad": 3, "prefix": "v", "default": 1},
        "frame": {"type": "int", "pad": 4, "default": 1001},
        "ext": {"default": "exr", "presets": ["exr", "png", "mp4", "mov"],
                "allow_custom": False},
    },
    "folders": ["{show}", "{seq}", "{shot}", "{name}", "{version}"],
    "file": "{shot}_{name}_{version}",
    "filename": "{basename}.{frame}.{ext}",
    "outputs": {
        "images": {
            "label": "Image sequence",
            "folders": ["{show}", "{seq}", "{shot}", "{name}", "{version}",
                        "{shot}_{name}_{version}"],
            "tokens": {"name": {"default": "imggen"}, "ext": {"default": "exr"}},
        },
        "movie": {
            "label": "Movie",
            "filename": "{basename}.{ext}",
            "tokens": {
                "name": {"default": "vidgen"},
                "ext": {"default": "mp4", "overridable": False},
                "frame": {"visible": False},
            },
        },
    },
}


def _schema(data=None):
    return engine.Schema("shots", copy.deepcopy(data or SHOTS))


def _with(**outputs):
    data = copy.deepcopy(SHOTS)
    data["outputs"] = outputs
    return data


class TestOutputLoading(unittest.TestCase):

    def test_outputs_keep_schema_order_and_the_first_is_the_default(self):
        schema = _schema()
        self.assertEqual(schema.outputs, ["images", "movie"])
        self.assertEqual(schema.default_output, "images")
        self.assertEqual(schema.variant().output, "images")
        self.assertEqual(schema.variant("").output, "images")

    def test_a_schema_without_outputs_is_its_own_view(self):
        data = copy.deepcopy(SHOTS)
        del data["outputs"]
        schema = _schema(data)
        self.assertEqual(schema.outputs, [])
        self.assertIs(schema.variant(), schema)
        self.assertIs(schema.variant("movie"), schema)
        self.assertEqual(schema.output, "")

    def test_an_output_replaces_only_the_templates_it_names(self):
        movie = _schema().variant("movie")
        self.assertEqual(movie.filename, "{basename}.{ext}")
        self.assertEqual(movie.folders, SHOTS["folders"])
        self.assertEqual(movie.file, SHOTS["file"])
        images = _schema().variant("images")
        self.assertEqual(images.folders[-1], "{shot}_{name}_{version}")
        self.assertEqual(images.filename, SHOTS["filename"])

    def test_an_output_patches_token_settings(self):
        movie = _schema().variant("movie")
        self.assertEqual(movie.tokens["ext"].initial(), "mp4")
        self.assertFalse(movie.tokens["ext"].overridable)
        self.assertTrue(movie.tokens["ext"].visible)
        self.assertFalse(movie.tokens["frame"].visible)
        self.assertEqual(movie.output_defaults, {"name": "vidgen", "ext": "mp4"})
        self.assertEqual(movie.output_label, "Movie")
        self.assertEqual(movie.output_config("images")["label"], "Image sequence")
        # The schema itself is untouched.
        self.assertTrue(_schema().tokens["ext"].overridable)

    def test_an_unknown_output_is_an_error(self):
        with self.assertRaises(engine.NamingError) as caught:
            _schema().variant("prores")
        self.assertIn("prores", str(caught.exception))
        self.assertIn("images, movie", str(caught.exception))

    def test_malformed_outputs_are_refused(self):
        cases = {
            "not a dict": [],
            "empty": {},
            "output not a dict": {"movie": "mp4"},
            "unknown key": {"movie": {"presets": ["mp4"]}},
            "unknown token": {"movie": {"tokens": {"codec": {"default": "h264"}}}},
            "unknown token key": {"movie": {"tokens": {"ext": {"presets": ["mp4"]}}}},
            "non-bool flag": {"movie": {"tokens": {"ext": {"visible": "no"}}}},
            "default outside closed presets": {
                "movie": {"tokens": {"ext": {"default": "avi"}}}},
        }
        for label, outputs in cases.items():
            data = copy.deepcopy(SHOTS)
            data["outputs"] = outputs
            with self.subTest(case=label), self.assertRaises(engine.NamingError):
                _schema(data)

    def test_an_output_cannot_show_a_hidden_token(self):
        data = copy.deepcopy(SHOTS)
        data["tokens"]["frame"]["visible"] = False
        data["outputs"]["images"]["tokens"]["frame"] = {"visible": True}
        with self.assertRaises(engine.NamingError) as caught:
            _schema(data)
        self.assertIn("frame", str(caught.exception))

    def test_an_output_cannot_touch_a_revealed_token_or_the_counter(self):
        data = copy.deepcopy(SHOTS)
        data["tokens"]["kind"] = {"presets": ["shots", "assets"],
                                  "reveals": {"assets": ["asset"]}}
        data["tokens"]["asset"] = {"default": "tree"}
        data["tokens"]["gen"] = {"type": "counter"}
        for token in ("asset", "gen"):
            broken = copy.deepcopy(data)
            broken["outputs"]["movie"]["tokens"][token] = {"default": "x"}
            with self.subTest(token=token), self.assertRaises(engine.NamingError):
                _schema(broken)

    def test_a_token_named_output_clashes(self):
        data = copy.deepcopy(SHOTS)
        data["tokens"]["output"] = {"default": "x"}
        with self.assertRaises(engine.NamingError) as caught:
            _schema(data)
        self.assertIn("output", str(caught.exception))


class OutputSchemaCase(unittest.TestCase):
    """Runs each test with `schemas/` replaced by a folder holding SHOTS."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self._tmp.name, "shots.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(SHOTS, handle)
        patcher = mock.patch.object(engine, "SCHEMA_DIR", self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    @staticmethod
    def node():
        return node_pkg.vfx_naming.VFXNamingConvention

    def main(self, **tokens):
        """A main node: no pipe, its own values only."""
        return self.node().execute(schema={"schema": "shots", **tokens}).result[0]

    def child(self, pipe, overrides=(), strict=True, **own):
        return self.node().execute(
            schema={"schema": "shots", **own}, naming_pipe=pipe, strict=strict,
            overrides=json.dumps(list(overrides))).result[0]


@needs_node
class TestOutputNode(OutputSchemaCase):

    def test_the_output_field_leads_the_schema_inputs(self):
        option = node_pkg.vfx_naming._schema_option("shots")
        ids = [i.id for i in option.inputs]
        self.assertEqual(ids[0], "output")
        # frame is hidden only by the movie output, so it keeps its field.
        self.assertIn("frame", ids)
        self.assertEqual(option.inputs[0].options, ["images", "movie"])

    def test_a_schema_without_outputs_has_no_output_field(self):
        option = node_pkg.vfx_naming._schema_option("vfx_default")
        self.assertNotIn("output", [i.id for i in option.inputs])

    def test_the_default_output_renders_without_an_output_value(self):
        pipe = self.main()
        self.assertEqual(pipe["output"], "images")
        self.assertEqual(pipe["result"]["example_filename"],
                         "sh0040_imggen_v001.1001.exr")
        self.assertTrue(pipe["result"]["filename_prefix"].endswith(
            "sh0040_imggen_v001/sh0040_imggen_v001"))

    def test_a_main_node_renders_the_output_it_picks(self):
        pipe = self.main(output="movie", name="vidgen", ext="mp4")
        self.assertEqual(pipe["output"], "movie")
        self.assertEqual(pipe["result"]["example_filename"], "sh0040_vidgen_v001.mp4")
        self.assertIn("Output : Movie (movie)", pipe["result"]["report"])

    def test_a_field_the_output_hides_takes_the_schema_value(self):
        pipe = self.main(output="movie", ext="mp4", frame=1234)
        self.assertEqual(pipe["result"]["first_frame"], 1001)

    def test_an_unknown_output_fails_strict_and_warns_permissive(self):
        with self.assertRaises(engine.NamingError):
            self.main(output="prores")
        pipe = self.node().execute(schema={"schema": "shots", "output": "prores"},
                                   strict=False).result[0]
        self.assertEqual(pipe["output"], "images")
        self.assertIn("prores", pipe["result"]["report"])

    def test_fields_carry_the_output(self):
        fields = self.main(output="movie", ext="mp4")["fields"]
        self.assertEqual(list(fields)[0], "output")
        self.assertEqual(fields["output"], "movie")

    def test_a_schema_without_outputs_keeps_its_fields_and_report(self):
        pipe = self.node().execute(schema={"schema": "vfx_default"}).result[0]
        self.assertEqual(pipe["output"], "")
        self.assertNotIn("output", pipe["fields"])
        self.assertNotIn("Output :", pipe["result"]["report"])


@needs_node
class TestOutputChain(OutputSchemaCase):

    def test_a_child_that_chooses_an_output_gets_its_defaults(self):
        parent = self.main(name="upscale", version=3)
        child = self.child(parent, ["output"], output="movie")
        self.assertEqual(child["output"], "movie")
        # name and ext come from the movie output, the rest is inherited.
        self.assertEqual(child["result"]["example_filename"], "sh0040_vidgen_v003.mp4")

    def test_a_childs_own_override_beats_the_output_default(self):
        child = self.child(self.main(), ["output", "name"],
                           output="movie", name="upscale")
        self.assertEqual(child["result"]["basename"], "sh0040_upscale_v001")

    def test_a_field_the_output_locks_cannot_be_overridden(self):
        with self.assertRaises(engine.NamingError) as caught:
            self.child(self.main(), ["output", "ext"], output="movie", ext="mov")
        self.assertIn("'ext' is locked by output 'movie'", str(caught.exception))
        parent = self.node().execute(schema={"schema": "shots"}, strict=False).result[0]
        child = self.child(parent, ["output", "ext"], output="movie", ext="mov")
        self.assertTrue(child["result"]["example_filename"].endswith(".mp4"))

    def test_a_child_that_inherits_the_output_inherits_its_values(self):
        parent = self.main(output="movie", name="upscale", ext="mov")
        child = self.child(parent, ["version"], version=2)
        self.assertEqual(child["output"], "movie")
        self.assertEqual(child["result"]["example_filename"], "sh0040_upscale_v002.mov")

    def test_choosing_the_same_output_still_applies_its_defaults(self):
        parent = self.main(name="upscale", ext="png")
        child = self.child(parent, ["output"], output="images")
        self.assertEqual(child["result"]["example_filename"],
                         "sh0040_imggen_v001.1001.exr")

    def test_a_grandchild_inherits_what_the_chosen_output_set(self):
        child = self.child(self.main(), ["output"], output="movie")
        grandchild = self.child(child, ["version"], version=5)
        self.assertEqual(grandchild["result"]["example_filename"],
                         "sh0040_vidgen_v005.mp4")

    def test_overriding_output_on_a_schema_without_outputs_is_refused(self):
        node = self.node()
        parent = node.execute(schema={"schema": "vfx_default"}).result[0]
        with self.assertRaises(engine.NamingError) as caught:
            node.execute(schema={"schema": "vfx_default", "output": "movie"},
                         naming_pipe=parent, overrides='["output"]')
        self.assertIn("output", str(caught.exception))

    def test_schema_meta_describes_the_outputs(self):
        meta = node_pkg.vfx_naming.schema_meta()
        self.assertEqual(list(meta["shots"]["outputs"]), ["images", "movie"])
        movie = meta["shots"]["outputs"]["movie"]
        self.assertEqual(movie["label"], "Movie")
        self.assertEqual(movie["tokens"]["ext"], {"default": "mp4", "overridable": False})


if __name__ == "__main__":
    unittest.main()
