"""
Tests for the VFX naming node.

Run from the repository root:

    COMFYUI_PATH=~/ComfyUI-Installs/main-local/ComfyUI python3 -m unittest discover tests

`COMFYUI_PATH` is only needed for the node tests - it is what makes `comfy_api`
importable. The engine tests in `TestTokenSpec` and `TestSchema` run without it.

`golden_v1.json` is the output of the pre-rewrite node, captured across the four
schemas that shipped before the token set became schema-driven. It is the
regression proof: the rewrite may change how values are supplied, but not what
comes out.
"""

import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

_PACKAGE = os.path.basename(ROOT).replace("-", "_")


def _load_engine():
    """Import naming_schema on its own - it has no ComfyUI dependency."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vfx_naming_schema", os.path.join(ROOT, "naming_schema.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


def _stub_torch():
    """
    Let `comfy_api.latest` import without a built torch.

    `comfy_api/latest/_input/basic_types.py` imports torch purely for tensor
    type hints. This node only touches `io`, so an empty placeholder is enough
    and keeps the suite runnable against a plain checkout of ComfyUI. Anything
    that genuinely needed torch would fail loudly rather than silently pass.
    """
    import types
    for name in ("torch", "torchvision", "torchaudio"):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.Tensor = object
            sys.modules[name] = module


def _load_node():
    """Import the node, which needs comfy_api on the path."""
    comfyui = os.environ.get("COMFYUI_PATH")
    if comfyui:
        sys.path.insert(0, os.path.expanduser(comfyui))
    try:
        import comfy_api.latest  # noqa: F401
    except ModuleNotFoundError as error:
        if error.name not in ("torch", "torchvision", "torchaudio"):
            return str(error)
        _stub_torch()
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"{_PACKAGE}_pkg", os.path.join(ROOT, "__init__.py"),
            submodule_search_locations=[ROOT])
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PACKAGE}_pkg"] = module
        spec.loader.exec_module(module)
        return module
    except ImportError as error:
        return str(error)


node_pkg = _load_node()
NODE_AVAILABLE = not isinstance(node_pkg, str)

# Use the package's own engine once it is loaded, so `NamingError` raised by the
# node is the same class the assertions catch.
if NODE_AVAILABLE:
    engine = node_pkg.naming_schema

needs_node = unittest.skipUnless(
    NODE_AVAILABLE,
    f"comfy_api not importable ({node_pkg if not NODE_AVAILABLE else ''}) - "
    "set COMFYUI_PATH to run the node tests",
)


_ISOLATION = []


def setUpModule():
    """Keep the user folder and VFX_NAMING_SCHEMA_DIR out of these tests.

    The suite asserts on the shipped presets, so neither the developer's own
    ComfyUI user folder nor a studio share may leak into what it finds.
    test_flags and test_pipe import both hooks, so they apply there too.
    """
    _ISOLATION[:] = [
        mock.patch.object(engine, "_user_schema_dir", lambda: None),
        mock.patch.dict(os.environ),
    ]
    for patcher in _ISOLATION:
        patcher.start()
    os.environ.pop(engine.SCHEMA_DIR_ENV, None)


def tearDownModule():
    for patcher in reversed(_ISOLATION):
        patcher.stop()
    _ISOLATION.clear()


# --- Engine ------------------------------------------------------------------

class TestTokenSpec(unittest.TestCase):

    def spec(self, **config):
        return engine.TokenSpec("t", config)

    def test_preset_is_taken_verbatim(self):
        """A preset was authored in the schema, so casing rules do not touch it."""
        spec = self.spec(charset="alnum", case="lower", presets=["comp", "FINAL"])
        warnings = []
        self.assertEqual(spec.resolve("FINAL", True, warnings), "FINAL")
        self.assertEqual(warnings, [])

    def test_custom_value_is_cleaned(self):
        spec = self.spec(charset="alnum", case="lower", presets=["comp"])
        warnings = []
        self.assertEqual(
            spec.resolve(engine.CUSTOM, False, warnings, custom="De-Noise!"),
            "denoise",
        )
        self.assertTrue(warnings)

    def test_allow_custom_false_rejects_custom(self):
        spec = self.spec(presets=["rec709", "acescg"], allow_custom=False)
        with self.assertRaises(engine.NamingError) as caught:
            spec.resolve(engine.CUSTOM, True, [])
        self.assertIn("rec709", str(caught.exception))

    def test_allow_custom_false_rejects_unknown_preset(self):
        spec = self.spec(presets=["rec709", "acescg"], allow_custom=False)
        with self.assertRaises(engine.NamingError):
            spec.resolve("srgb", True, [])

    def test_options_append_custom_only_when_allowed(self):
        self.assertEqual(
            self.spec(presets=["a", "b"]).options, ["a", "b", engine.CUSTOM])
        self.assertEqual(
            self.spec(presets=["a", "b"], allow_custom=False).options, ["a", "b"])
        self.assertEqual(self.spec().options, [])

    def test_layer_is_appended_and_padded(self):
        spec = self.spec(presets=["bg", "comp"], layer_pattern=r"(bg|fg)(\d{1,2})?")
        self.assertEqual(spec.resolve("bg", True, [], layer=2), "bg02")
        self.assertEqual(spec.resolve("bg", True, [], layer=0), "bg")
        self.assertEqual(spec.resolve("comp", True, [], layer=2), "comp")

    def test_layer_already_present_wins_with_a_warning(self):
        spec = self.spec(presets=["bg"], charset="alnum",
                         layer_pattern=r"(bg|fg)(\d{1,2})?")
        warnings = []
        self.assertEqual(
            spec.resolve(engine.CUSTOM, True, warnings, custom="bg07", layer=2),
            "bg07",
        )
        self.assertTrue(any("already carries" in w for w in warnings))

    def test_layered_value_skips_the_pattern_check(self):
        """'bg' is legitimate even though it fails the four-letter pattern."""
        spec = self.spec(charset="alnum", case="lower", pattern="[a-z]{4}",
                         layer_pattern=r"(bg|fg)(\d{1,2})?")
        self.assertEqual(spec.resolve("bg", True, []), "bg")
        with self.assertRaises(engine.NamingError):
            spec.resolve("xy", True, [])

    def test_layered_presets_lists_only_matching_ones(self):
        spec = self.spec(presets=["comp", "bg", "fg"],
                         layer_pattern=r"(bg|fg)(\d{1,2})?")
        self.assertEqual(spec.layered_presets(), ["bg", "fg"])

    def test_int_pads_and_prefixes(self):
        spec = self.spec(type="int", pad=3, prefix="sh")
        self.assertEqual(spec.resolve(10, True, []), "sh010")

    def test_int_off_step_warns_but_passes(self):
        spec = self.spec(type="int", pad=4, step=10)
        warnings = []
        self.assertEqual(spec.resolve(15, True, warnings), "0015")
        self.assertTrue(any("multiple of 10" in w for w in warnings))

    def test_optional_empty_renders_as_nothing(self):
        self.assertEqual(self.spec(optional=True).resolve("", True, []), "")
        with self.assertRaises(engine.NamingError):
            self.spec().resolve("", True, [])

    def test_initial_prefers_default_then_first_preset(self):
        self.assertEqual(self.spec(presets=["a", "b"], default="b").initial(), "b")
        self.assertEqual(self.spec(presets=["a", "b"]).initial(), "a")
        self.assertEqual(self.spec(type="int", default=7).initial(), 7)
        self.assertEqual(self.spec().initial(), "")

    def test_allow_keeps_extra_characters(self):
        """A hyphen has to survive so words can be separated inside a token."""
        spec = self.spec(charset="alnum", case="lower", allow="-")
        warnings = []
        self.assertEqual(spec.resolve("Face-Fix", True, warnings), "face-fix")
        self.assertEqual(warnings, [])

    def test_allow_does_not_open_the_gate_for_everything_else(self):
        spec = self.spec(charset="alnum", allow="-")
        warnings = []
        self.assertEqual(spec.resolve("a-b_c!d", False, warnings), "a-bcd")
        self.assertTrue(any("letters, digits and '-'" in w for w in warnings))

    def test_without_allow_a_hyphen_is_still_stripped(self):
        spec = self.spec(charset="alnum")
        warnings = []
        self.assertEqual(spec.resolve("face-fix", False, warnings), "facefix")
        self.assertTrue(warnings)

    def test_allow_accepts_a_regex_metacharacter_literally(self):
        spec = self.spec(charset="alnum", allow=".+")
        self.assertEqual(spec.resolve("a.b+c-d", False, []), "a.b+cd")

    def test_a_boolean_is_refused_rather_than_stringified(self):
        """
        A stale node on the canvas keeps the old field order, so a boolean from
        further down can land in a token. Building "True/SHOW/..." out of that
        is worse than saying it.
        """
        spec = self.spec(charset="any", optional=True)
        warnings = []
        self.assertEqual(spec.resolve(True, False, warnings), "")
        self.assertTrue(any("delete it and add it again" in w for w in warnings))
        with self.assertRaises(engine.NamingError):
            spec.resolve(True, True, [])

    def test_strict_raises_where_permissive_collects(self):
        spec = self.spec(charset="alpha", length=3)
        with self.assertRaises(engine.NamingError):
            spec.resolve("ab1", True, [])
        warnings = []
        self.assertEqual(spec.resolve("ab1", False, warnings), "ab")
        self.assertTrue(warnings)


class TestSchema(unittest.TestCase):

    def test_shipped_schemas_all_load(self):
        names = engine.schema_names()
        self.assertIn("studio", names)
        for key in names:
            config = engine.load_schema(key)
            self.assertTrue(config.tokens, f"{key} declares no tokens")
            self.assertTrue(config.file, f"{key} declares no file template")

    def test_task_rules_is_gone_from_every_schema(self):
        for key, path in engine.available_schemas().items():
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertNotIn("task_rules", data, f"{key} still carries task_rules")

    def test_token_order_follows_the_json(self):
        config = engine.load_schema("studio")
        self.assertEqual(
            list(config.tokens),
            ["show", "shot", "task", "variant", "version", "colorspace",
             "frame", "ext", "mount"],
        )

    def test_shot_id_is_a_template(self):
        self.assertEqual(engine.load_schema("studio").shot_id, "{shot}")
        self.assertEqual(
            engine.load_schema("vfx_default").shot_id, "{show}_{seq}_{shot}")

    def test_shot_id_absent_renders_empty(self):
        config = engine.Schema("x", {"tokens": {}, "file": "{a}"})
        self.assertEqual(config.render_shot_id({"a": "1"}), "")

    def test_rules_drop_the_vendor_for_plates(self):
        config = engine.load_schema("vfx_default")
        values = {"task": "bg02", "vendor": "abc"}
        notes = []
        config.apply_rules(values, notes)
        self.assertEqual(values["vendor"], "")
        self.assertTrue(notes)

    def test_studio_keeps_the_show_code_verbatim(self):
        spec = engine.load_schema("studio").spec("show")
        self.assertEqual(spec.resolve("Atlas Rising", True, []), "Atlas Rising")

    def test_studio_colorspace_is_a_closed_choice(self):
        spec = engine.load_schema("studio").spec("colorspace")
        self.assertFalse(spec.allow_custom)
        self.assertEqual(spec.options, ["rec709", "acescg"])


# --- Node --------------------------------------------------------------------

BASE = dict(show="SHW", seq="SEQ", shot=10, vendor="", version=1, frame=1001)

CASES = {
    "defaults":        {},
    "vendor":          dict(vendor="abc"),
    "plate_no_layer":  dict(task="bg", vendor="abc"),
    "plate_layer":     dict(task="bg", task_layer=2, vendor="abc"),
    "task_custom":     dict(task="(custom)", task_custom="dnse", vendor="abc"),
    "no_folders":      dict(folders=False, vendor="abc"),
    "parent_path":     dict(parent_path="ARCHIVE/2026", vendor="abc"),
    "override":        dict(template_override=
                            "{show}/{seq}/{show}_{seq}_{shot}_{task}_{version}"),
    "custom_tokens":   dict(custom_tokens="episode=101\nartist=vp"),
    "ext_png":         dict(ext="png"),
    "frame_and_ver":   dict(version=12, frame=1051, shot=250),
    "permissive_dirt": dict(strict=False, show="shwx!", seq="sq", vendor="ABCD"),
}

TOP_LEVEL = {"folders", "strict", "parent_path", "template_override", "custom_tokens"}


def _call(schema_key, case):
    """Run the node the way ComfyUI would; return the ten results in order."""
    settings = dict(BASE, **case)
    top = {k: settings.pop(k) for k in list(settings) if k in TOP_LEVEL}

    config = engine.load_schema(schema_key)
    supplied = {"schema": schema_key}
    for name, spec in config.tokens.items():
        if spec.options:
            chosen = settings.get(name, spec.initial())
            entry = {name: chosen}
            if f"{name}_custom" in settings:
                entry[f"{name}_custom"] = settings[f"{name}_custom"]
            if f"{name}_layer" in settings:
                entry[f"{name}_layer"] = settings[f"{name}_layer"]
            supplied[name] = entry
        else:
            supplied[name] = settings.get(name, spec.initial())

    Node = node_pkg.vfx_naming.VFXNamingConvention
    pipe = Node.execute(schema=supplied, **top).result[0]
    return tuple(pipe["result"][n] for n in node_pkg.vfx_naming.RESULT_NAMES)


def _named(schema_key, case):
    """Run the node and label the results the way the breakout names them."""
    return dict(zip(node_pkg.vfx_naming.RESULT_NAMES, _call(schema_key, case)))


@needs_node
class TestGoldenRegression(unittest.TestCase):
    """The rewritten node must reproduce the pre-rewrite output exactly."""

    # The report is deliberately reformatted, and FINAL was deliberately dropped.
    # `directory` and `full_path` are new outputs with no v1 counterpart.
    COMPARED = ("filename_prefix", "folder_name", "basename", "shot_id",
                "extension", "example_filename", "first_frame")

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "tests", "golden_v1.json"), encoding="utf-8") as h:
            cls.golden = json.load(h)

    def test_every_golden_case_matches(self):
        checked = 0
        for name, expected in sorted(self.golden.items()):
            schema_key, _, case = name.partition("::")
            if case.startswith("_") or case not in CASES:
                continue
            with self.subTest(case=name):
                result = _named(schema_key, CASES[case])
                for field in self.COMPARED:
                    self.assertEqual(
                        result[field], expected[field],
                        f"{name}: {field} drifted",
                    )
            checked += 1
        self.assertEqual(checked, 48, "expected 4 schemas x 12 cases")


@needs_node
class TestStudioWip(unittest.TestCase):

    def build(self, **overrides):
        settings = dict(show="Atlas", shot=10, task="imggen", variant="main",
                        version=1, colorspace="rec709", frame=1001, ext="exr")
        settings.update(overrides)
        return _named("studio", settings)

    def test_the_documented_example(self):
        result = self.build(colorspace="acescg")
        self.assertEqual(
            result["filename_prefix"],
            "Atlas/02_wip/shots/sh010/imggen_main/out/"
            "sh010_imggen_main_v001_acescg_1001",
        )
        self.assertEqual(
            result["example_filename"],
            "sh010_imggen_main_v001_acescg_1001.1001.exr",
        )

    def test_the_variant_separates_passes_of_one_task(self):
        """Two AOVs must not land on the same name or in the same folder."""
        depth = self.build(task="aov", variant="depth")
        normal = self.build(task="aov", variant="normal")
        self.assertEqual(
            depth["filename_prefix"],
            "Atlas/02_wip/shots/sh010/aov_depth/out/"
            "sh010_aov_depth_v001_rec709_1001")
        self.assertNotEqual(depth["folder_name"], normal["folder_name"])
        self.assertNotEqual(depth["basename"], normal["basename"])

    def test_the_variant_is_never_empty(self):
        """Every name has to split into the same components to stay parseable."""
        with self.assertRaises(engine.NamingError):
            self.build(variant="", strict=True)
        self.assertFalse(engine.load_schema("studio").spec("variant").optional)

    def test_hyphens_survive_in_task_and_variant(self):
        """'_' delimits this schema, so '-' is the safe word separator."""
        result = self.build(task="(custom)", task_custom="face-fix",
                            variant="hair-fine")
        self.assertEqual(
            result["filename_prefix"],
            "Atlas/02_wip/shots/sh010/face-fix_hair-fine/out/"
            "sh010_face-fix_hair-fine_v001_rec709_1001")

    def test_underscores_are_still_stripped_from_tokens(self):
        """An underscore inside a token would forge a component boundary."""
        result = self.build(variant="hair_fine", strict=False)
        self.assertIn("_hairfine_", result["basename"])

    def test_the_convention_schemas_do_not_allow_hyphens(self):
        """studio_nested delimits with '-', so one inside a token would break it."""
        for key in ("vfx_default", "vfx_flat", "studio_nested", "episodic_dotted"):
            with self.subTest(schema=key):
                self.assertEqual(engine.load_schema(key).spec("task").allow, "")

    def test_tasks_are_ai_generation_work_only(self):
        presets = engine.load_schema("studio").spec("task").presets
        self.assertEqual(presets, [
            "imggen", "vidgen", "audgen", "3dgen", "retouch", "restyle",
            "relight", "roto", "aov", "upscale", "interp"])
        for plate in ("mp", "bg", "fg", "el", "cp", "rp"):
            self.assertNotIn(plate, presets)

    def test_no_layer_field_without_plates(self):
        """layer_pattern went with the plates, so no task reveals a layer."""
        spec = engine.load_schema("studio").spec("task")
        self.assertIsNone(spec.layer_pattern)
        self.assertEqual(spec.layered_presets(), [])

    def test_the_convention_schemas_keep_their_plates(self):
        """Only studio was reshaped; the paper's schemas are untouched."""
        for key in ("vfx_default", "vfx_flat", "studio_nested", "episodic_dotted"):
            with self.subTest(schema=key):
                spec = engine.load_schema(key).spec("task")
                self.assertIn("bg", spec.presets)
                self.assertEqual(spec.layered_presets(),
                                 ["mp", "bg", "fg", "el", "cp", "rp"])

    def test_shot_is_three_digits_with_an_sh_prefix(self):
        self.assertIn("/sh020/", self.build(shot=20)["filename_prefix"])
        self.assertEqual(self.build(shot=20)["shot_id"], "sh020")

    def test_show_code_keeps_its_case_and_spaces(self):
        self.assertTrue(
            self.build(show="Atlas Rising")["filename_prefix"]
            .startswith("Atlas Rising/02_wip/"))

    def test_no_sequence_or_vendor_field_exists(self):
        config = engine.load_schema("studio")
        self.assertNotIn("seq", config.tokens)
        self.assertNotIn("vendor", config.tokens)

    def test_first_frame_output_strips_the_padding(self):
        self.assertEqual(self.build(frame=1051)["first_frame"], 1051)


@needs_node
class TestRegistration(unittest.TestCase):
    """Walk the path ComfyUI itself takes when it loads the extension."""

    def test_the_entrypoint_yields_the_node(self):
        import asyncio
        extension = asyncio.run(node_pkg.comfy_entrypoint())
        nodes = asyncio.run(extension.get_node_list())
        self.assertEqual(nodes, [node_pkg.vfx_naming.VFXNamingConvention,
                                 node_pkg.vfx_naming.VFXNamingBreakout])

    def test_the_schema_validates(self):
        """This is the check that rejects duplicate or missing input/output ids."""
        node_pkg.vfx_naming.VFXNamingConvention.define_schema().validate()

    def test_the_v1_node_info_is_complete(self):
        info = node_pkg.vfx_naming.VFXNamingConvention.GET_NODE_INFO_V1()
        self.assertEqual(list(info["output_name"]), ["naming_pipe"])
        self.assertEqual(list(info["output"]), ["VFX_NAMING"])
        self.assertEqual(list(info["input"]["required"]),
                         ["schema", "folders", "strict"])
        self.assertEqual(
            list(info["input"]["optional"]),
            ["naming_pipe", "parent_path", "template_override", "custom_tokens",
             "preview", "overrides"])

    def test_a_schema_option_carries_only_its_own_tokens(self):
        info = node_pkg.vfx_naming.VFXNamingConvention.GET_NODE_INFO_V1()
        options = info["input"]["required"]["schema"][1]["options"]
        by_key = {o["key"]: list(o["inputs"]["required"]) for o in options}
        self.assertEqual(
            by_key["studio"],
            ["show", "shot", "task", "variant", "version", "colorspace",
             "frame", "ext", "mount"])
        self.assertEqual(
            by_key["vfx_default"],
            ["show", "seq", "shot", "task", "vendor", "version", "frame", "ext"])

    def test_the_shot_widget_carries_the_grid_step_for_the_frontend(self):
        info = node_pkg.vfx_naming.VFXNamingConvention.GET_NODE_INFO_V1()
        options = info["input"]["required"]["schema"][1]["options"]
        wip = next(o for o in options if o["key"] == "studio")
        self.assertEqual(wip["inputs"]["required"]["shot"][1]["vfxGridStep"], 10)


@needs_node
class TestGeneratedInputs(unittest.TestCase):

    def test_every_schema_produces_a_valid_option(self):
        for key in engine.schema_names():
            with self.subTest(schema=key):
                option = node_pkg.vfx_naming._schema_option(key)
                self.assertEqual(option.key, key)
                self.assertTrue(option.inputs)
                for entry in option.inputs:
                    entry.validate()

    def test_a_preset_token_becomes_a_dropdown_with_custom_last(self):
        option = node_pkg.vfx_naming._schema_option("vfx_default")
        task = next(i for i in option.inputs if i.id == "task")
        self.assertEqual(task.options[-1].key, engine.CUSTOM)

    def test_a_closed_token_has_no_custom_entry(self):
        option = node_pkg.vfx_naming._schema_option("studio")
        colorspace = next(i for i in option.inputs if i.id == "colorspace")
        self.assertEqual([o.key for o in colorspace.options], ["rec709", "acescg"])

    def test_the_default_leads_the_dropdown(self):
        """DynamicCombo starts on its first option, so the default must be first."""
        option = node_pkg.vfx_naming._schema_option("vfx_default")
        for entry in option.inputs:
            if not hasattr(entry, "options"):
                continue
            spec = engine.load_schema("vfx_default").spec(entry.id)
            self.assertEqual(entry.options[0].key, str(spec.initial()))

    def test_only_plate_presets_reveal_a_layer_field(self):
        option = node_pkg.vfx_naming._schema_option("vfx_default")
        task = next(i for i in option.inputs if i.id == "task")
        with_layer = {o.key for o in task.options if o.inputs and
                      any(i.id == "task_layer" for i in o.inputs)}
        self.assertEqual(with_layer, {"mp", "bg", "fg", "el", "cp", "rp"})

    def test_the_schema_dropdown_lists_every_json(self):
        schema_input = next(
            i for i in node_pkg.vfx_naming.VFXNamingConvention.define_schema().inputs
            if i.id == "schema")
        self.assertEqual([o.key for o in schema_input.options], engine.schema_names())


@needs_node
class TestNodeBehaviour(unittest.TestCase):

    def test_custom_tokens_may_set_a_value_outside_an_open_dropdown(self):
        """allow_custom means free text, whichever route it arrives by."""
        result = _call("vfx_default", dict(custom_tokens="task=denoise"))
        self.assertIn("_denoise_", result[0])

    def test_custom_tokens_cannot_break_a_closed_dropdown(self):
        with self.assertRaises(engine.NamingError):
            _call("studio", dict(show="Atlas", custom_tokens="colorspace=srgb"))

    def test_custom_tokens_override_a_widget(self):
        result = _call("episodic_dotted", dict(custom_tokens="artist=vp"))
        self.assertIn(".vp.", result[0])

    def test_strict_rejects_what_permissive_repairs(self):
        with self.assertRaises(engine.NamingError):
            _call("vfx_default", dict(show="shwx!", strict=True))
        self.assertTrue(_call("vfx_default", dict(show="shwx!", strict=False))[0])

    def test_parent_path_refuses_to_climb(self):
        with self.assertRaises(engine.NamingError):
            _call("vfx_default", dict(parent_path="../../etc", strict=True))

    def test_report_names_every_token_of_the_schema(self):
        report = _named("studio", dict(show="Atlas"))["report"]
        for label in ("Show code", "Shot number", "Task", "Version",
                      "Colorspace", "First frame", "Extension"):
            self.assertIn(label, report)
        self.assertNotIn("Sequence code", report)
        self.assertNotIn("Vendor", report)

    def test_build_renders_a_pipe(self):
        pipe = node_pkg.vfx_naming.build("vfx_default", {}, {})
        self.assertEqual(pipe["version"], 1)
        self.assertEqual(pipe["schema"], "vfx_default")
        self.assertEqual(list(pipe["result"]), list(node_pkg.vfx_naming.RESULT_NAMES))
        self.assertEqual(pipe["result"]["filename_prefix"],
                         "SHW_SEQ_0010_comp_v001/SHW_SEQ_0010_comp_v001")
        self.assertEqual(pipe["options"]["strict"], True)


class TestOsDefaults(unittest.TestCase):
    """A token can start from a different value on each platform."""

    def spec(self, **config):
        return engine.TokenSpec("mount", config)

    def test_the_running_platform_wins_over_default(self):
        spec = self.spec(default="/fallback", os={
            "windows": "C:/projects", "macos": "/Volumes/projects",
            "linux": "/mnt/projects"})
        expected = {"windows": "C:/projects", "macos": "/Volumes/projects",
                    "linux": "/mnt/projects"}[engine.CURRENT_OS]
        self.assertEqual(spec.initial(), expected)

    def test_a_platform_the_map_omits_falls_back(self):
        spec = self.spec(default="/fallback", os={"aix": "/nowhere"})
        self.assertEqual(spec.initial(), "/fallback")

    def test_the_os_key_covers_the_three_platforms(self):
        self.assertIn(engine.CURRENT_OS, ("windows", "macos", "linux"))

    def test_studio_ships_all_three_mount_points(self):
        spec = engine.load_schema("studio").spec("mount")
        self.assertEqual(set(spec.os_defaults), {"windows", "macos", "linux"})
        self.assertEqual(spec.os_defaults["windows"], "C:/projects")
        self.assertEqual(spec.os_defaults["macos"], "/Volumes/projects")


@needs_node
class TestAbsolutePaths(unittest.TestCase):
    """`root` feeds the absolute outputs; filename_prefix stays relative."""

    def build(self, **overrides):
        settings = dict(show="Atlas", shot=10, task="imggen", variant="main",
                        version=1, colorspace="rec709", frame=1001, ext="exr",
                        mount="/Volumes/projects")
        settings.update(overrides)
        return _named("studio", settings)

    def test_directory_is_the_mount_plus_the_folders(self):
        self.assertEqual(
            self.build()["directory"],
            "/Volumes/projects/Atlas/02_wip/shots/sh010/imggen_main/out")

    def test_full_path_appends_the_basename(self):
        result = self.build()
        self.assertEqual(result["full_path"],
                         result["directory"] + "/" + result["basename"])

    def test_filename_prefix_stays_relative(self):
        """ComfyUI's own savers reject anything outside the output folder."""
        prefix = self.build()["filename_prefix"]
        self.assertFalse(prefix.startswith("/"))
        self.assertTrue(prefix.startswith("Atlas/02_wip/"))

    def test_a_windows_mount_keeps_its_drive_letter(self):
        self.assertEqual(
            self.build(mount="C:/projects")["directory"],
            "C:/projects/Atlas/02_wip/shots/sh010/imggen_main/out")

    def test_a_trailing_slash_does_not_double_up(self):
        self.assertEqual(
            self.build(mount="/Volumes/projects/")["directory"],
            "/Volumes/projects/Atlas/02_wip/shots/sh010/imggen_main/out")

    def test_an_empty_mount_leaves_the_absolute_outputs_empty(self):
        result = self.build(mount="")
        self.assertEqual(result["directory"], "")
        self.assertEqual(result["full_path"], "")
        self.assertTrue(result["filename_prefix"])

    def test_a_schema_without_root_has_no_absolute_outputs(self):
        result = _named("vfx_default", {})
        self.assertEqual(result["directory"], "")
        self.assertEqual(result["full_path"], "")

    def test_parent_path_does_not_reach_the_absolute_outputs(self):
        """parent_path is a sub-path of ComfyUI's output folder, nothing more."""
        result = self.build(parent_path="ARCHIVE")
        self.assertTrue(result["filename_prefix"].startswith("ARCHIVE/"))
        self.assertNotIn("ARCHIVE", result["directory"])


@needs_node
class TestPreview(unittest.TestCase):
    """The frontend posts raw widget values; Python renders the answer."""

    def nest(self, flat):
        return node_pkg.vfx_naming._nest(flat)

    def test_dotted_names_become_the_execute_shape(self):
        self.assertEqual(
            self.nest({"schema": "studio", "schema.show": "Atlas",
                       "schema.task": "bg", "schema.task.task_layer": 2,
                       "strict": True}),
            {"schema": {"schema": "studio", "show": "Atlas",
                        "task": {"task": "bg", "task_layer": 2}},
             "strict": True},
        )

    def test_key_order_does_not_matter(self):
        deep_first = self.nest({"schema.task.task_layer": 2,
                                "schema.task": "bg", "schema": "studio"})
        self.assertEqual(deep_first["schema"]["schema"], "studio")
        self.assertEqual(deep_first["schema"]["task"],
                         {"task": "bg", "task_layer": 2})

    def widgets(self, **overrides):
        flat = {
            "schema": "studio", "schema.show": "Atlas", "schema.shot": 10,
            "schema.task": "imggen", "schema.variant": "main",
            "schema.version": 1,
            "schema.colorspace": "acescg", "schema.frame": 1001,
            "schema.ext": "exr", "schema.mount": "/Volumes/projects",
            "folders": True, "strict": True,
        }
        flat.update(overrides)
        return flat

    def test_it_renders_the_assembled_name(self):
        result = node_pkg.vfx_naming.preview(self.widgets())
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIn("sh010_imggen_main_v001_acescg_1001", result["text"])
        self.assertIn("/Volumes/projects/Atlas/02_wip/", result["text"])

    def test_it_stays_permissive_so_half_typed_values_still_show(self):
        """Strict mode would abort on 'sh'; a preview must keep rendering."""
        result = node_pkg.vfx_naming.preview({
            "schema": "vfx_default", "schema.show": "sh", "schema.seq": "SEQ",
            "schema.shot": 10, "schema.task": "comp", "schema.vendor": "",
            "schema.version": 1, "schema.frame": 1001, "schema.ext": "exr",
            "folders": True, "strict": True,
        })
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIn("SH_SEQ_0010_comp_v001", result["text"])
        self.assertIn("must be exactly 3 characters", result["text"])

    def test_a_bare_dropdown_value_is_accepted(self):
        """An option that reveals no fields comes back as a plain value."""
        result = node_pkg.vfx_naming.preview(self.widgets())
        self.assertIn("_imggen_", result["text"])

    def test_a_dropdown_with_a_revealed_field_is_accepted(self):
        """vfx_default still reveals task_layer on a plate preset."""
        result = node_pkg.vfx_naming.preview({
            "schema": "vfx_default", "schema.show": "SHW", "schema.seq": "SEQ",
            "schema.shot": 10, "schema.task": "bg",
            "schema.task.task_layer": 2, "schema.vendor": "",
            "schema.version": 1, "schema.frame": 1001, "schema.ext": "exr",
            "folders": True, "strict": True})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIn("_bg02_", result["text"])

    def test_it_reports_instead_of_raising(self):
        result = node_pkg.vfx_naming.preview({"schema": "studio"})
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_no_schema_is_handled(self):
        self.assertFalse(node_pkg.vfx_naming.preview({})["ok"])

    def test_garbage_never_escapes_as_an_exception(self):
        for junk in ({"schema": 5}, {"schema.show": "x"},
                     {"schema": "nope", "schema.show": "x"}):
            with self.subTest(junk=junk):
                self.assertIn("ok", node_pkg.vfx_naming.preview(junk))


if __name__ == "__main__":
    unittest.main()
