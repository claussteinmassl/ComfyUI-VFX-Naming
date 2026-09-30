"""
VFX Naming Convention node for ComfyUI.

Builds a filename_prefix that follows a VFX shot/plate naming convention. The
convention is *configuration*, not code: which tokens exist, how each one is
formatted and validated, the delimiters, the token order, the folder depth and
the way each token is offered in the node all live in JSON under `schemas/`.
This module only turns a schema into inputs and renders the result - see
`naming_schema.py` for the engine.

The `schema` widget is an `io.DynamicCombo` whose options are generated from
the JSON files, so picking a schema swaps the node's fields for that schema's
tokens. A token that declares `presets` becomes a dropdown of its own, with a
`(custom)` entry when the schema allows free text.

Default schema:

    <SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>
    AAA_AAA_####_aaaa_aaa_v###.####.aaa

Reference: "VFX Naming Convention" paper by Victor Perez, VFX Supervisor.
"""

import json
import re

from comfy_api.latest import io

from .naming_schema import (
    CUSTOM,
    NamingError,
    OPTION_NAMES,
    load_schema,
    parse_custom_tokens,
    render,
    schema_names,
    schema_source,
)

# Kept as an alias so existing imports and error handling keep working.
VFXNamingError = NamingError

MAX_INT = 999999999

# The naming pipe: one output that carries the inputs and the rendered result,
# so a downstream naming node can inherit and a breakout node can unpack.
PIPE = io.Custom("VFX_NAMING")
PIPE_VERSION = 1

# What a pipe's `result` holds, in the order the breakout node outputs it.
RESULTS = (
    ("filename_prefix", io.String,
     "Connect to filename_prefix on Save Image / Save Image (Advanced) / "
     "video savers."),
    ("folder_name", io.String,
     "Folder levels the schema renders (empty when there are none)."),
    ("directory", io.String,
     "Absolute folder, from the schema's 'root' levels (a mount point) plus "
     "folder_name. Empty when the schema declares no root. For savers that "
     "take a real path - ComfyUI's own reject one."),
    ("full_path", io.String,
     "directory + basename, without frame or extension. Empty when the schema "
     "declares no root."),
    ("basename", io.String, "Filename without frame number or extension."),
    ("shot_id", io.String,
     "The schema's shot identifier, empty when it declares no 'shot_id' "
     "template."),
    ("extension", io.String,
     "File extension, lowercase and without a leading dot."),
    ("example_filename", io.String,
     "Fully formed example filename including frame and extension."),
    ("first_frame", io.Int, "First frame of the work range."),
    ("report", io.String,
     "Human-readable breakdown plus any validation warnings."),
)
RESULT_NAMES = tuple(name for name, _, _ in RESULTS)


def _sanitize_path(value, strict, warnings):
    """Clean a relative sub-path, keeping ComfyUI %date:...% tokens intact."""
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        return ""

    cleaned = re.sub(r"[^A-Za-z0-9_\-%:./]", "", raw)
    if cleaned != raw:
        _fail(f"parent_path: unsupported characters removed from '{raw}'.",
              strict, warnings)

    segments = [s for s in cleaned.split("/") if s and s != "."]
    if any(s == ".." for s in segments):
        _fail("parent_path: '..' segments are not allowed and were removed.",
              strict, warnings)
        segments = [s for s in segments if s != ".."]

    return "/".join(segments)


def _fail(message, strict, warnings):
    if strict:
        raise NamingError(message)
    warnings.append(message)


# --- Turning a schema into node inputs ---------------------------------------

def _preset_input(spec):
    """A dropdown of the token's presets, plus the fields each one reveals."""
    layered = set(spec.layered_presets())
    initial = str(spec.initial())

    # The first option is what the node starts on, so the default leads.
    presets = list(spec.presets)
    if initial in presets:
        presets.remove(initial)
        presets.insert(0, initial)

    options = []
    for preset in presets:
        revealed = []
        if preset in layered:
            revealed.append(io.Int.Input(
                f"{spec.name}_layer", display_name="layer",
                default=0, min=0, max=10 ** spec.layer_pad - 1, step=1,
                tooltip=(f"Layer number appended to '{preset}' "
                         f"(0 = none): {preset} -> {preset}"
                         f"{2:0{spec.layer_pad}d}."),
            ))
        options.append(io.DynamicCombo.Option(preset, revealed))

    if spec.allow_custom:
        options.append(io.DynamicCombo.Option(CUSTOM, [
            io.String.Input(
                f"{spec.name}_custom", display_name=f"{spec.label} (custom)",
                default="",
                tooltip=(f"{spec.label} used instead of a preset. Unlike a "
                         "preset this is validated against the schema."),
            ),
        ]))

    return io.DynamicCombo.Input(
        spec.name, display_name=spec.label, options=options,
        tooltip=_token_tooltip(spec),
    )


def _token_input(spec):
    """The node input one token contributes."""
    if spec.options:
        return _preset_input(spec)

    if spec.is_int:
        step = int(spec.step or 1)
        return io.Int.Input(
            spec.name, display_name=spec.label,
            default=int(spec.initial() or 0), min=0, max=MAX_INT, step=step,
            # web/vfx_naming.js reads this to snap the +/- buttons onto the
            # schema's grid without also snapping typed values.
            extra_dict={"vfxGridStep": step} if step > 1 else None,
            tooltip=_token_tooltip(spec),
        )

    return io.String.Input(
        spec.name, display_name=spec.label, default=str(spec.initial() or ""),
        tooltip=_token_tooltip(spec),
    )


def _token_tooltip(spec):
    """Describe a token's rules in the words of the schema that declared it."""
    parts = []
    if spec.is_int:
        if spec.pad:
            parts.append(f"zero padded to {spec.pad} digits")
        if spec.step and spec.step > 1:
            parts.append(f"increments of {spec.step}")
    else:
        if spec.charset == "alpha":
            parts.append("letters only")
        elif spec.charset == "alnum":
            parts.append("letters and digits only")
        if spec.case:
            parts.append(f"{spec.case}case")
        if spec.length:
            parts.append(f"exactly {spec.length} characters")
        if spec.pattern:
            parts.append(f"matching /{spec.pattern}/")
    if spec.prefix:
        parts.append(f"prefixed '{spec.prefix}'")
    if spec.presets and not spec.allow_custom:
        parts.append("no other values accepted")
    if spec.optional:
        parts.append("may be left empty, in which case it and its delimiter "
                     "are dropped")
    return f"{spec.label}: " + (", ".join(parts) if parts else "free text") + "."


def _schema_option(key):
    """One entry of the schema dropdown: its label and its visible token fields."""
    config = load_schema(key)
    inputs = [_token_input(spec) for spec in config.tokens.values() if spec.visible]
    return io.DynamicCombo.Option(key, inputs)


# --- Reading the values back -------------------------------------------------

def _as_int(text, spec):
    """Read a rendered token back as a number, stepping over its prefix."""
    raw = str(text or "")
    if spec and spec.prefix and raw.startswith(spec.prefix):
        raw = raw[len(spec.prefix):]
    try:
        return int(raw)
    except ValueError:
        return 0


def _token_values(spec, supplied):
    """Split one token's node input into (value, custom, layer)."""
    # A DynamicCombo whose selected option reveals fields arrives as
    # {"<token>": selected, "<token>_custom": ...}. An option that reveals
    # nothing arrives as the bare selection, so a plain value is valid here too.
    if not spec.options or not isinstance(supplied, dict):
        return supplied, None, 0

    return (
        supplied.get(spec.name),
        supplied.get(f"{spec.name}_custom"),
        supplied.get(f"{spec.name}_layer", 0),
    )


def _check_pipe(pipe):
    """Refuse anything that is not a naming pipe of this version."""
    required = {"version", "schema", "tokens", "options", "result"}
    valid = (
        isinstance(pipe, dict)
        and pipe.get("version") == PIPE_VERSION
        and required <= set(pipe)
        and isinstance(pipe.get("schema"), str)
        and isinstance(pipe.get("tokens"), dict)
        and isinstance(pipe.get("options"), dict)
        and isinstance(pipe.get("result"), dict)
        and set(RESULT_NAMES) <= set(pipe["result"])
    )
    if not valid:
        raise NamingError(
            "naming_pipe: this is not a VFX naming pipe - connect the output "
            "of a VFX Naming Convention node.")
    return pipe


def _parse_overrides(text):
    """Read the `overrides` widget: a JSON list of field names."""
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except ValueError:
        names = None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise NamingError(
            f"overrides: expected a JSON list of field names, got {raw!r}.")
    return list(dict.fromkeys(names))


def _inherit(pipe, own_tokens, own_options, overridden):
    """Take everything from an incoming pipe except the fields this node overrides.

    Args:
        pipe: The incoming naming pipe.
        own_tokens: This node's raw token input.
        own_options: This node's option values.
        overridden: Field names this node overrides.

    Returns:
        The new pipe, rendered from the merged inputs.

    Raises:
        NamingError: For a foreign pipe, or - in strict mode - an override the
            pipe's schema does not allow.
    """
    pipe = _check_pipe(pipe)
    key = pipe["schema"]
    config = load_schema(key)
    tokens = dict(pipe["tokens"])
    options = dict(pipe["options"])

    refused = []          # human-readable reasons, for the error/warning text
    refused_names = set()  # field names that were refused, for `applied`
    for name in overridden:
        if name in OPTION_NAMES:
            flags = config.option_flags(name)
            if flags["visible"] and flags["overridable"]:
                options[name] = own_options[name]
                continue
            refused.append(f"'{name}' is locked by schema '{key}'")
        elif name in config.tokens:
            if not config.tokens[name].overridable:
                refused.append(f"'{name}' is locked by schema '{key}'")
            elif name not in own_tokens:
                # A different schema on this node, or a stale override list -
                # there is nothing of this node's own to apply.
                refused.append(f"this node has no value for '{name}'")
            else:
                tokens[name] = own_tokens[name]
                continue
        else:
            refused.append(f"schema '{key}' has no field '{name}'")
        refused_names.add(name)

    notes = []
    if refused:
        joined = "; ".join(refused)
        if config.effective_options(options)["strict"]:
            raise NamingError(f"Cannot override: {joined}.")
        notes.append(f"Cannot override: {joined} - the inherited value is used.")

    applied = [n for n in overridden if n not in refused_names]
    return build(key, tokens, options, notes=notes, overridden=applied)


def build(key, tokens, options, notes=None, overridden=None):
    """Render one name and wrap it, with the inputs it came from, as a pipe.

    Args:
        key: Schema key.
        tokens: Raw per-token input, as the DynamicCombo delivers it.
        options: The node options; missing ones take their defaults and the
            ones the schema hides are fixed.
        notes: Warnings raised before rendering, e.g. by an override merge.
        overridden: Field names this node overrode on an incoming pipe, or
            None when it received no pipe. Only used for the report.

    Returns:
        The pipe dict: version, schema, tokens, options and result.

    Raises:
        NamingError: If strict validation rejects a value or a template.
    """
    config = load_schema(key)
    options = config.effective_options(options)
    strict = options["strict"]
    warnings = list(notes or [])

    values = {}
    for name, spec in config.tokens.items():
        # A hidden token has no widget; whatever arrives is ignored. A token
        # that is simply absent starts from its initial value, as a new node.
        raw = tokens.get(name, spec.initial()) if spec.visible else spec.initial()
        value, custom, layer = _token_values(spec, raw)
        values[name] = spec.resolve(
            value, strict, warnings, custom=custom, layer=layer,
        )

    # Extra tokens for the template; a matching name overrides its widget.
    extras = parse_custom_tokens(options["custom_tokens"], strict)
    for name, value in extras.items():
        spec = config.tokens.get(name)
        values[name] = spec.resolve(value, strict, warnings) if spec else value

    config.apply_rules(values, warnings)

    template_override = options["template_override"]
    prefix_body, basename, unknown = config.render_prefix(
        values,
        include_folders=options["folders"],
        override=template_override,
        strict=strict,
    )
    if unknown and not strict:
        warnings.append(
            "Template refers to unknown token(s): "
            + ", ".join("{" + n + "}" for n in unknown)
            + " - rendered as empty."
        )

    parent = _sanitize_path(options["parent_path"], strict, warnings)
    filename_prefix = "/".join(s for s in (parent, prefix_body) if s)
    folder_name = "/".join(prefix_body.split("/")[:-1])
    shot_id = config.render_shot_id(values)

    # The absolute location, for savers that take a real path. `parent_path`
    # is a sub-path of ComfyUI's output folder, so it plays no part here.
    root = config.render_root(values)
    directory = "/".join(s for s in (root, folder_name) if s) if root else ""
    full_path = "/".join(s for s in (directory, basename) if s) if directory else ""
    example_filename, _ = render(
        config.filename, dict(values, basename=basename), strict=False,
    )

    # Two results name a token: a schema without 'ext' or 'frame' simply
    # leaves them empty rather than failing.
    extension = values.get("ext", "")
    first_frame = _as_int(values.get("frame"), config.tokens.get("frame"))

    report = VFXNamingConvention._report(
        key, config, values, extras, template_override, shot_id,
        folder_name, filename_prefix, example_filename, directory,
        full_path, warnings, overridden,
    )

    result = dict(zip(RESULT_NAMES, (
        filename_prefix, folder_name, directory, full_path, basename,
        shot_id, extension, example_filename, first_frame, report,
    )))
    return {
        "version": PIPE_VERSION,
        "schema": key,
        # Only keep what was actually supplied - not every token name with a
        # None filler - so a token absent here still falls back to its
        # initial value on the next build(), the same as a fresh node.
        "tokens": {name: tokens[name] for name in config.tokens if name in tokens},
        "options": options,
        "result": result,
    }


# --- Node --------------------------------------------------------------------

class VFXNamingConvention(io.ComfyNode):
    """Compose a VFX-compliant filename_prefix for Save Image / video nodes."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="VFXNamingConvention",
            display_name="VFX Naming Convention (Filename Prefix)",
            category="VFX/naming",
            description=(
                "Build a VFX naming convention filename_prefix from a JSON "
                "schema. The schema decides which fields this node shows:\n"
                "<SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>\n"
                "Outputs a naming pipe: unpack it with VFX Naming Breakout."
            ),
            inputs=[
                PIPE.Input(
                    "naming_pipe", optional=True,
                    tooltip=(
                        "Inherit everything from another VFX Naming Convention "
                        "node. The schema is taken from it; any other field "
                        "can be overridden with the toggle on its row."
                    ),
                ),
                io.DynamicCombo.Input(
                    "schema",
                    display_name="Schema",
                    options=[_schema_option(key) for key in schema_names()],
                    tooltip=(
                        "Naming schema from the schemas/ folder: token rules, "
                        "delimiters, token order and folder depth. The fields "
                        "below are the tokens it declares. Drop your own JSON "
                        "in there to add a studio convention."
                    ),
                ),
                io.Boolean.Input(
                    "folders", default=True,
                    label_on="folder + files", label_off="files only",
                    tooltip=(
                        "Render the schema's folder levels. Off writes the "
                        "files straight into the output folder."
                    ),
                ),
                io.Boolean.Input(
                    "strict", default=True,
                    label_on="strict", label_off="permissive",
                    tooltip=(
                        "Strict: abort on any violation. Permissive: "
                        "auto-correct and list the issues in the report output."
                    ),
                ),
                io.String.Input(
                    "parent_path", default="", optional=True,
                    tooltip=(
                        "Optional sub-path under the output folder, e.g. "
                        "'SHW/SEQ' or '%date:yyyy-MM-dd%'."
                    ),
                ),
                io.String.Input(
                    "template_override", default="", multiline=True, optional=True,
                    tooltip=(
                        "Override the schema's templates for one node. Use "
                        "{token}, [optional groups] and / for folder levels, "
                        "e.g.\n{show}/{seq}/{show}_{seq}_{shot}_{task}"
                        "[_{vendor}]_{version}"
                    ),
                ),
                io.String.Input(
                    "custom_tokens", default="", multiline=True, optional=True,
                    tooltip=(
                        "Extra tokens for the template, one 'name=value' per "
                        "line, e.g. episode=101. Reference them as {episode}. "
                        "A name that matches a token above overrides it."
                    ),
                ),
                io.String.Input(
                    "preview", default="", multiline=True, optional=True,
                    tooltip=(
                        "Live result, refreshed as you type - nothing needs to "
                        "run. Filled in by web/vfx_naming.js and ignored on "
                        "execution; edits to it have no effect."
                    ),
                ),
                io.String.Input(
                    "overrides", default="", optional=True, socketless=True,
                    tooltip=(
                        "Fields this node overrides on its naming_pipe, as a "
                        "JSON list. Managed by web/vfx_overrides.js and hidden "
                        "on the node."
                    ),
                ),
            ],
            outputs=[PIPE.Output("naming_pipe", tooltip="Everything this node "
                "decided. Connect to a VFX Naming Breakout for filename_prefix "
                "and the other values, or to another VFX Naming Convention to "
                "inherit and override.")],
        )

    @classmethod
    def execute(cls, schema, folders=True, strict=True, naming_pipe=None,
                parent_path="", template_override="", custom_tokens="",
                preview="", overrides=""):
        # The DynamicCombo hands over {"schema": key, <token>: value, ...}.
        supplied = schema if isinstance(schema, dict) else {"schema": str(schema)}
        tokens = {k: v for k, v in supplied.items() if k != "schema"}
        options = {"folders": folders, "strict": strict,
                   "parent_path": parent_path,
                   "template_override": template_override,
                   "custom_tokens": custom_tokens}
        if naming_pipe is None:
            return io.NodeOutput(build(supplied.get("schema"), tokens, options))
        return io.NodeOutput(
            _inherit(naming_pipe, tokens, options, _parse_overrides(overrides)))

    @staticmethod
    def _report(key, config, values, extras, template_override, shot_id,
                folder_name, filename_prefix, example_filename, directory,
                full_path, warnings, overridden=None):
        """Break the result down in the schema's own vocabulary."""
        lines = [f"SCHEMA: {config.label}  ({key})"]
        if config.description:
            lines.append(f"  {config.description}")
        source = schema_source(key)
        if source:
            lines.append(f"  Source : {source[0]} ({source[1]})")
        lines.append("")

        width = max([len(s.label) for s in config.tokens.values()] + [12])
        for name, spec in config.tokens.items():
            shown = values.get(name) or "- (omitted)"
            suffix = "  (custom_tokens)" if name in extras else ""
            lines.append(f"  {spec.label:<{width}} : {shown}{suffix}")
        for name in sorted(n for n in extras if n not in config.tokens):
            lines.append(f"  {name:<{width}} : {values.get(name, '')}  (custom_tokens)")

        template = template_override.strip() or "/".join(config.folders + [config.file])
        lines += [
            "",
            f"  {'Template':<{width}} : {template}",
            f"  {'Shot ID':<{width}} : {shot_id or '- (none)'}",
            f"  {'Folder':<{width}} : {folder_name or '- (none)'}",
            f"  {'Prefix':<{width}} : {filename_prefix}",
            f"  {'Example file':<{width}} : {example_filename}",
        ]
        if overridden is not None:
            lines.append(
                f"  {'Overrides':<{width}} : "
                + (", ".join(overridden) if overridden else "- (all inherited)"))
        if directory:
            lines += [
                f"  {'Directory':<{width}} : {directory}",
                f"  {'Full path':<{width}} : {full_path}",
            ]
        if warnings:
            lines += ["", "WARNINGS:"] + [f"  ! {w}" for w in warnings]
        return "\n".join(lines)


class VFXNamingBreakout(io.ComfyNode):
    """Unpack a naming pipe into filename_prefix and the other results."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="VFXNamingBreakout",
            display_name="VFX Naming Breakout",
            category="VFX/naming",
            description=(
                "Unpack the naming pipe of a VFX Naming Convention node into "
                "filename_prefix, paths, shot id, extension, first frame and "
                "the report."
            ),
            inputs=[PIPE.Input("naming_pipe", tooltip="From VFX Naming Convention.")],
            outputs=[kind.Output(name, tooltip=tooltip)
                     for name, kind, tooltip in RESULTS],
        )

    @classmethod
    def execute(cls, naming_pipe):
        result = _check_pipe(naming_pipe)["result"]
        return io.NodeOutput(*(result[name] for name in RESULT_NAMES))


# --- Schema flags for the frontend -------------------------------------------

SCHEMAS_ROUTE = "/vfx_naming/schemas"


def schema_meta():
    """Describe each schema's field flags for web/vfx_widgets.js.

    Hidden tokens are left out - they have no widget to describe.

    Returns:
        A dict keyed by schema, each with `tokens` and `options` flag maps.
    """
    meta = {}
    for key in schema_names():
        config = load_schema(key)
        options = {}
        for name in OPTION_NAMES:
            flags = config.option_flags(name)
            options[name] = {"visible": flags["visible"],
                             "overridable": flags["overridable"]}
        meta[key] = {
            "tokens": {name: {"overridable": spec.overridable}
                       for name, spec in config.tokens.items() if spec.visible},
            "options": options,
        }
    return meta


# --- Live preview ------------------------------------------------------------
#
# The node shows its result while you type, which needs the values before the
# graph runs. Rather than reimplement the naming rules in JavaScript, the
# frontend posts the widget values here and renders whatever comes back, so
# Python stays the only place the convention is interpreted.

PREVIEW_ROUTE = "/vfx_naming/preview"

TOP_LEVEL_INPUTS = ("folders", "strict", "parent_path", "template_override",
                    "custom_tokens")


def _nest(flat):
    """
    Rebuild ComfyUI's dotted widget names into the shape `execute()` expects.

    A DynamicCombo's own value shares its name with the group it opens, which is
    how ComfyUI resolves it too: `{"schema": "studio", "schema.show": "A"}`
    becomes `{"schema": {"schema": "studio", "show": "A"}}`. Shallow keys are
    handled first, so the scalar is always in place before the group needs it.
    """
    nested = {}
    for key in sorted(flat, key=lambda k: k.count(".")):
        parts = key.split(".")
        cursor = nested
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                cursor[part] = {} if existing is None else {part: existing}
            cursor = cursor[part]
        leaf = parts[-1]
        existing = cursor.get(leaf)
        if isinstance(existing, dict):
            existing[leaf] = flat[key]
        else:
            cursor[leaf] = flat[key]
    return nested


def preview(widgets):
    """Render the node's outputs from raw widget values. Never raises."""
    try:
        values = _nest(widgets or {})
        supplied = values.get("schema")
        if not isinstance(supplied, dict):
            return {"ok": False, "error": "No schema selected yet."}

        options = {name: values[name] for name in TOP_LEVEL_INPUTS if name in values}
        # Permissive: a half-typed value should show a preview, not an error.
        options["strict"] = False

        pipe = VFXNamingConvention.execute(schema=supplied, **options).result[0]
        fields = pipe["result"]

        rows = [("prefix", "filename_prefix"), ("example", "example_filename"),
                ("directory", "directory"), ("full path", "full_path")]
        width = max(len(label) for label, _ in rows)
        lines = [f"{label:<{width}} : {fields[key]}"
                 for label, key in rows if fields.get(key)]

        warned = fields["report"].split("WARNINGS:")
        if len(warned) > 1:
            lines += [""] + [w.strip() for w in warned[1].strip().splitlines()]

        return {"ok": True, "text": "\n".join(lines), "fields": fields}
    except Exception as error:  # a preview must never break the server
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def _register_routes():
    """Expose `preview()` and `schema_meta()` over HTTP when running inside a
    ComfyUI server."""
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception:
        return False
    instance = getattr(PromptServer, "instance", None)
    if instance is None or not hasattr(instance, "routes"):
        return False

    @instance.routes.post(PREVIEW_ROUTE)
    async def _preview(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return web.json_response(preview(body.get("widgets") or {}))

    @instance.routes.get(SCHEMAS_ROUTE)
    async def _schemas(request):
        try:
            return web.json_response(schema_meta())
        except Exception as error:  # a broken schema must not break the server
            return web.json_response({"error": str(error)}, status=500)

    return True


ROUTES_REGISTERED = _register_routes()
