"""
VFX Naming Convention node for ComfyUI.

Builds a filename_prefix string that follows the standard VFX plate/shot naming
convention:

    <SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>
    AAA_AAA_####_aaaa_aaa_v###.####.aaa

Image sequences live in a folder named after the file basename, e.g.

    SHW_SEQ_0010_comp_vnd_v001/
        SHW_SEQ_0010_comp_vnd_v001.1001.exr
        SHW_SEQ_0010_comp_vnd_v001.1002.exr

Reference: "VFX Naming Convention" paper by Victor Perez, VFX Supervisor.
"""

import re

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

PLATE_RE = re.compile(r"^(mp|bg|fg|el|cp|rp)(\d{1,2})?$")


class VFXNamingError(ValueError):
    """Raised when strict validation rejects a component."""


# --- Helpers -----------------------------------------------------------------

def _fail(message, strict, warnings):
    if strict:
        raise VFXNamingError(message)
    warnings.append(message)


def _alpha_code(value, length, upper, label, strict, warnings):
    """Validate/normalise an alphabetic component such as SHOW or SEQUENCE."""
    raw = (value or "").strip()
    cleaned = re.sub(r"[^A-Za-z]", "", raw)

    if cleaned != raw:
        _fail(
            f"{label}: only letters are allowed - '{raw}' was reduced to '{cleaned}'.",
            strict, warnings,
        )

    cleaned = cleaned.upper() if upper else cleaned.lower()

    if not cleaned:
        raise VFXNamingError(f"{label} cannot be empty.")

    if length and len(cleaned) != length:
        _fail(
            f"{label} must be exactly {length} letters "
            f"(got '{cleaned}', {len(cleaned)}).",
            strict, warnings,
        )
        if len(cleaned) > length:
            cleaned = cleaned[:length]

    return cleaned


def _resolve_task(preset, custom, plate_layer, strict, warnings):
    """Return (task_string, is_plate)."""
    task = (custom or "").strip() if preset == CUSTOM else preset

    if not task:
        raise VFXNamingError(
            "Task is empty: pick a preset or fill in 'task_custom' when using "
            f"'{CUSTOM}'."
        )

    if task.upper() == FINAL_TASK:
        return FINAL_TASK, False

    base = re.sub(r"[^A-Za-z0-9]", "", task).lower()
    if base != task.lower().strip():
        _fail(
            f"Task: only letters and digits are allowed - '{task}' was reduced "
            f"to '{base}'.",
            strict, warnings,
        )

    match = PLATE_RE.match(base)
    if match:
        stem, layer = match.group(1), match.group(2)
        if plate_layer > 0:
            if layer and int(layer) != plate_layer:
                warnings.append(
                    f"Task: '{base}' already carries a layer number; "
                    f"'plate_layer' ({plate_layer}) was ignored."
                )
            elif not layer:
                layer = f"{plate_layer:02d}"
        return stem + (layer or ""), True

    if not re.fullmatch(r"[a-z]{4}", base):
        _fail(
            f"Task '{base}' is not valid: use 4 lowercase letters (e.g. 'comp'), "
            f"a 2-character plate type {PLATE_TASKS} optionally followed by a "
            f"layer number (e.g. 'bg02'), or '{FINAL_TASK}'.",
            strict, warnings,
        )

    return base, False


def _sanitize_path(value, strict, warnings):
    """Clean a relative sub-path, keeping ComfyUI %date:...% tokens intact."""
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        return ""

    cleaned = re.sub(r"[^A-Za-z0-9_\-%:./]", "", raw)
    if cleaned != raw:
        _fail(
            f"parent_path: unsupported characters removed from '{raw}'.",
            strict, warnings,
        )

    segments = [s for s in cleaned.split("/") if s and s != "."]
    if any(s == ".." for s in segments):
        _fail(
            "parent_path: '..' segments are not allowed and were removed.",
            strict, warnings,
        )
        segments = [s for s in segments if s != ".."]

    return "/".join(segments)


# --- Node --------------------------------------------------------------------

class VFXNamingConvention:
    """Compose a VFX-compliant filename_prefix for Save Image / video nodes."""

    @classmethod
    def INPUT_TYPES(cls):
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
                        "plates - the component and its underscore are dropped."
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
                        "Wrap the sequence in a folder named after the file "
                        "basename, per the convention."
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
        "Name of the sequence folder.",
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
        "Build a VFX naming convention filename_prefix:\n"
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
    ):
        warnings = []

        show = _alpha_code(show_code, 3, True, "Show code", strict, warnings)
        seq = _alpha_code(sequence_code, 3, True, "Sequence code", strict, warnings)

        shot = f"{shot_number:0{shot_padding}d}"
        if len(shot) > shot_padding:
            _fail(
                f"Shot number {shot_number} does not fit in {shot_padding} digits.",
                strict, warnings,
            )
        if shot_number % 10 != 0:
            warnings.append(
                f"Note: shot number {shot_number} is not a multiple of 10. The "
                "convention increments shots by tens, but off-grid shot numbers "
                "are accepted."
            )

        task_str, is_plate = _resolve_task(task, task_custom, plate_layer, strict, warnings)

        vendor = ""
        raw_vendor = (vendor_id or "").strip()
        if raw_vendor:
            if is_plate:
                warnings.append(
                    f"Task '{task_str}' is a lab plate type; plates carry no "
                    f"vendor id, so '{raw_vendor}' was dropped."
                )
            else:
                vendor = _alpha_code(raw_vendor, 3, False, "Vendor id", strict, warnings)

        ver = f"v{version:0{version_padding}d}"
        if len(ver) - 1 > version_padding:
            _fail(
                f"Version {version} does not fit in {version_padding} digits.",
                strict, warnings,
            )

        shot_id = f"{show}_{seq}_{shot}"
        parts = [show, seq, shot, task_str]
        if vendor:
            parts.append(vendor)
        parts.append(ver)
        basename = "_".join(parts)

        folder_name = basename
        parent = _sanitize_path(parent_path, strict, warnings)

        prefix_segments = []
        if parent:
            prefix_segments.append(parent)
        if sequence_subfolder:
            prefix_segments.append(folder_name)
        prefix_segments.append(basename)
        filename_prefix = "/".join(prefix_segments)

        extension = (example_extension or file_extension or "").strip().lstrip(".").lower()
        if not extension:
            raise VFXNamingError("File extension cannot be empty.")

        example_filename = (
            f"{basename}.{first_frame:0{frame_padding}d}.{extension}"
        )

        report_lines = [
            "VFX NAMING CONVENTION",
            "<SHOW>_<SEQ>_<SHOT>_<TASK>_<VENDOR>_v<VERSION>.<FRAME>.<EXT>",
            "",
            f"  Show code     : {show}",
            f"  Sequence code : {seq}",
            f"  Shot number   : {shot}",
            f"  Task          : {task_str}"
            + (f"  ({PLATE_LABELS.get(task_str[:2], 'plate')})" if is_plate else "")
            + ("  (approved final)" if task_str == FINAL_TASK else ""),
            f"  Vendor id     : {vendor or '- (omitted)'}",
            f"  Version       : {ver}",
            f"  First frame   : {first_frame:0{frame_padding}d}",
            f"  Extension     : {extension}",
            "",
            f"  Shot ID       : {shot_id}",
            f"  Folder        : {folder_name if sequence_subfolder else '- (none)'}",
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
