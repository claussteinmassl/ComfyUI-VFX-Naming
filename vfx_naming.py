"""
VFX Naming Convention node for ComfyUI.

Builds a filename_prefix that follows a VFX shot/plate naming convention. The
convention itself is *configuration*, not code: which tokens exist, how each is
formatted and validated, the delimiters, the token order and the number of
folder levels all live in JSON under `schemas/`. This module supplies the
values and renders the selected schema - see `naming_schema.py` for the engine.

Default schema:

    <SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>
    AAA_AAA_####_aaaa_aaa_v###.####.aaa

Reference: "VFX Naming Convention" paper by Victor Perez, VFX Supervisor.
"""

import re

from .naming_schema import (
    NamingError,
    load_schema,
    parse_custom_tokens,
    render,
    schema_names,
)

# Kept as an alias so existing imports and error handling keep working.
VFXNamingError = NamingError

# --- Task vocabularies -------------------------------------------------------

# Plate types produced by the lab: 2 characters, optionally + a layer number
# (bg02, fg12). Plates carry no vendor id.
PLATE_TASKS = ("mp", "bg", "fg", "el", "cp", "rp")

PLATE_LABELS = {
    "mp": "Main Plate",
    "bg": "Background Plate",
    "fg": "Foreground Plate",
    "el": "Element Plate",
    "cp": "Clean Plate",
    "rp": "Reference Plate",
}

FINAL_TASK = "FINAL"  # complete + approved shot, uppercase by convention
CUSTOM = "(custom)"

TASK_PRESETS = [
    # generic 4-letter task codes
    "comp", "prev", "post", "prep", "roto", "pant", "dmpt", "envr",
    "layt", "trck", "mmov", "anim", "crwd", "mdel", "txtr", "lkdv",
    "lght", "rndr", "fxsm", "cfxs", "genr", "upsc", "dnse", "test",
    # approved final
    FINAL_TASK,
    # lab plate types
    *PLATE_TASKS,
    CUSTOM,
]

EXTENSIONS = [
    "exr", "png", "tif", "tiff", "jpg", "dpx", "webp",
    "mov", "mp4", "mxf", "cube", "cdl",
]


def _fail(message, strict, warnings):
    if strict:
        raise NamingError(message)
    warnings.append(message)


def _resolve_task(schema, preset, custom, plate_layer, strict, warnings):
    """Return (task_string, is_plate) using the schema's task rules."""
    rules = schema.task_rules or {}
    final_task = rules.get("final", FINAL_TASK)
    plate_re = re.compile(f"^(?:{rules.get('plate_pattern', 'x^')})$")
    standard = rules.get("standard_pattern")

    task = (custom or "").strip() if preset == CUSTOM else preset
    if not task:
        raise NamingError(
            "Task is empty: pick a preset or fill in 'task_custom' when using "
            f"'{CUSTOM}'."
        )

    if final_task and task.upper() == final_task.upper():
        return final_task, False

    base = re.sub(r"[^A-Za-z0-9]", "", task).lower()
    if base != task.lower().strip():
        _fail(f"Task: only letters and digits are allowed - '{task}' was reduced "
              f"to '{base}'.", strict, warnings)

    match = plate_re.match(base)
    if match:
        groups = match.groups()
        stem = groups[0] if groups and groups[0] else base
        layer = groups[1] if len(groups) > 1 and groups[1] else ""
        if plate_layer > 0:
            if layer and int(layer) != plate_layer:
                warnings.append(
                    f"Task: '{base}' already carries a layer number; "
                    f"'plate_layer' ({plate_layer}) was ignored."
                )
            elif not layer:
                layer = f"{plate_layer:02d}"
        return stem + (layer or ""), True

    if standard and not re.fullmatch(standard, base):
        _fail(f"Task '{base}' is not valid for this schema: expected "
              f"/{standard}/, a plate type, or '{final_task}'.", strict, warnings)

    return base, False


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


# --- Node --------------------------------------------------------------------

class VFXNamingConvention:
    """Compose a VFX-compliant filename_prefix for Save Image / video nodes."""

    @classmethod
    def INPUT_TYPES(cls):
        schemas = schema_names()
        return {
            "required": {
                "show_code": ("STRING", {
                    "default": "SHW", "multiline": False,
                    "tooltip": "Show code: 3 letters, uppercase (e.g. SHW).",
                }),
                "sequence_code": ("STRING", {
                    "default": "SEQ", "multiline": False,
                    "tooltip": "Sequence/block code: 3 letters, uppercase (e.g. SEQ).",
                }),
                "shot_number": ("INT", {
                    "default": 10, "min": 0, "max": 999999, "step": 1,
                    "tooltip": (
                        "Shot number, zero padded. The arrows step in tens (the "
                        "convention's increment), but any number can be typed in "
                        "manually - 15, 0125, whatever the show uses."
                    ),
                }),
                "task": (TASK_PRESETS, {
                    "default": "comp",
                    "tooltip": (
                        "Task code: 4 lowercase letters, a 2-character lab plate "
                        "type (mp/bg/fg/el/cp/rp), FINAL for approved shots, or "
                        "(custom)."
                    ),
                }),
                "vendor_id": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": (
                        "Vendor id: 3 letters, lowercase. Leave empty for lab "
                        "plates - the component and its delimiter are dropped."
                    ),
                }),
                "version": ("INT", {
                    "default": 1, "min": 0, "max": 999999, "step": 1,
                    "tooltip": "Version number, 'v' prefixed and zero padded.",
                }),
                "sequence_subfolder": ("BOOLEAN", {
                    "default": True, "label_on": "folder + files",
                    "label_off": "files only",
                    "tooltip": (
                        "Render the schema's folder levels. Off writes the files "
                        "straight into the output folder."
                    ),
                }),
                "strict": ("BOOLEAN", {
                    "default": True, "label_on": "strict", "label_off": "permissive",
                    "tooltip": (
                        "Strict: abort on any violation. Permissive: auto-correct "
                        "and list the issues in the report output."
                    ),
                }),
            },
            "optional": {
                "task_custom": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Task code used when 'task' is set to (custom).",
                }),
                "plate_layer": ("INT", {
                    "default": 0, "min": 0, "max": 99, "step": 1,
                    "tooltip": "Layer number appended to plate tasks (0 = none): bg -> bg02.",
                }),
                "parent_path": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": (
                        "Optional sub-path under the output folder, e.g. "
                        "'SHW/SEQ' or '%date:yyyy-MM-dd%'."
                    ),
                }),
                "first_frame": ("INT", {
                    "default": 1001, "min": 0, "max": 9999999, "step": 1,
                    "tooltip": "First frame of the work range (plate head). Convention: 1001.",
                }),
                "shot_padding": ("INT", {"default": 4, "min": 1, "max": 8}),
                "version_padding": ("INT", {"default": 3, "min": 1, "max": 8}),
                "frame_padding": ("INT", {"default": 4, "min": 1, "max": 10}),
                "file_extension": (EXTENSIONS, {
                    "default": "exr",
                    "tooltip": (
                        "File extension for the 'extension' and 'example_filename' "
                        "outputs. ComfyUI savers pick their own format widget-side; "
                        "this drives downstream nodes and the preview."
                    ),
                }),
                "schema": (schemas, {
                    "default": schemas[0],
                    "tooltip": (
                        "Naming schema from the schemas/ folder: token rules, "
                        "delimiters, token order and folder depth. Drop your own "
                        "JSON in there to add a studio convention."
                    ),
                }),
                "template_override": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": (
                        "Override the schema's templates for one node. Use "
                        "{token}, [optional groups] and / for folder levels, e.g.\n"
                        "{show}/{seq}/{show}_{seq}_{shot}_{task}[_{vendor}]_{version}"
                    ),
                }),
                "custom_tokens": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": (
                        "Extra tokens for the template, one 'name=value' per line, "
                        "e.g. episode=101. Reference them as {episode}."
                    ),
                }),
            },
        }

    RETURN_TYPES = (
        "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "INT", "STRING",
    )
    RETURN_NAMES = (
        "filename_prefix", "folder_name", "basename", "shot_id",
        "extension", "example_filename", "first_frame", "report",
    )
    OUTPUT_TOOLTIPS = (
        "Connect to filename_prefix on Save Image / Save Image (Advanced) / video savers.",
        "Folder levels the schema renders (empty when there are none).",
        "Filename without frame number or extension.",
        "Show_Sequence_Shot identifier.",
        "File extension, lowercase and without a leading dot.",
        "Fully formed example filename including frame and extension.",
        "First frame of the work range.",
        "Human-readable breakdown plus any validation warnings.",
    )
    FUNCTION = "build"
    CATEGORY = "VFX/naming"
    DESCRIPTION = (
        "Build a VFX naming convention filename_prefix from a JSON schema:\n"
        "<SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>"
    )

    def build(
        self,
        show_code,
        sequence_code,
        shot_number,
        task,
        vendor_id,
        version,
        sequence_subfolder,
        strict,
        task_custom="",
        plate_layer=0,
        parent_path="",
        first_frame=1001,
        shot_padding=4,
        version_padding=3,
        frame_padding=4,
        file_extension="exr",
        example_extension=None,
        schema="vfx_default",
        template_override="",
        custom_tokens="",
    ):
        warnings = []
        config = load_schema(schema)

        task_str, is_plate = _resolve_task(
            config, task, task_custom, plate_layer, strict, warnings,
        )

        extension = (example_extension or file_extension or "").strip().lstrip(".").lower()
        if not extension:
            raise NamingError("File extension cannot be empty.")

        if shot_number % 10 != 0:
            warnings.append(
                f"Note: shot number {shot_number} is not a multiple of 10. The "
                "convention increments shots by tens, but off-grid shot numbers "
                "are accepted."
            )

        raw = {
            "show": show_code,
            "seq": sequence_code,
            "shot": shot_number,
            "task": task_str,
            "vendor": vendor_id,
            "version": version,
            "frame": first_frame,
            "ext": extension,
        }
        pads = {"shot": shot_padding, "version": version_padding, "frame": frame_padding}

        values = {}
        for name, value in raw.items():
            values[name] = config.spec(name).format(
                value, strict, warnings, pad_override=pads.get(name),
            )

        # Extra tokens declared by the schema but not backed by a widget.
        extras = parse_custom_tokens(custom_tokens, strict)
        for name, value in extras.items():
            spec = config.tokens.get(name)
            values[name] = spec.format(value, strict, warnings) if spec else value
        for name, spec in config.tokens.items():
            values.setdefault(name, "" if spec.optional else "")

        config.apply_rules(values, warnings)

        prefix_body, basename, unknown = config.render_prefix(
            values,
            include_folders=sequence_subfolder,
            override=template_override,
            strict=strict,
        )
        if unknown and not strict:
            warnings.append(
                "Template refers to unknown token(s): "
                + ", ".join("{" + n + "}" for n in unknown)
                + " - rendered as empty."
            )

        parent = _sanitize_path(parent_path, strict, warnings)
        filename_prefix = "/".join(s for s in (parent, prefix_body) if s)

        folder_name = "/".join(prefix_body.split("/")[:-1])
        shot_id = "_".join(v for v in (values["show"], values["seq"], values["shot"]) if v)
        example_filename, _ = render(
            config.filename, dict(values, basename=basename), strict=False,
        )

        report_lines = [
            f"SCHEMA: {config.label}  ({schema})",
        ]
        if config.description:
            report_lines.append(f"  {config.description}")
        report_lines += [
            "",
            f"  Show code     : {values['show']}",
            f"  Sequence code : {values['seq']}",
            f"  Shot number   : {values['shot']}",
            f"  Task          : {values['task']}"
            + (f"  ({PLATE_LABELS.get(task_str[:2], 'plate')})" if is_plate else "")
            + ("  (approved final)" if task_str == FINAL_TASK else ""),
            f"  Vendor id     : {values['vendor'] or '- (omitted)'}",
            f"  Version       : {values['version']}",
            f"  First frame   : {values['frame']}",
            f"  Extension     : {extension}",
        ]
        for name in sorted(extras):
            report_lines.append(f"  {name:<14}: {values.get(name, '')}  (custom)")
        report_lines += [
            "",
            f"  Template      : {(template_override.strip() or '/'.join(config.folders + [config.file]))}",
            f"  Shot ID       : {shot_id}",
            f"  Folder        : {folder_name or '- (none)'}",
            f"  Prefix        : {filename_prefix}",
            f"  Example file  : {example_filename}",
        ]
        if warnings:
            report_lines += ["", "WARNINGS:"] + [f"  ! {w}" for w in warnings]

        return (
            filename_prefix,
            folder_name,
            basename,
            shot_id,
            extension,
            example_filename,
            first_frame,
            "\n".join(report_lines),
        )


NODE_CLASS_MAPPINGS = {
    "VFXNamingConvention": VFXNamingConvention,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VFXNamingConvention": "VFX Naming Convention (Filename Prefix)",
}
