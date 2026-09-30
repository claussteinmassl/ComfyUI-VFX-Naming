"""
Schema-driven naming.

The configuration - which tokens exist, how each one is formatted and
validated, what the delimiters are, in which order the tokens appear, how many
folder levels they render into and how each token is offered in the node - all
lives in JSON files under `schemas/`. This module is only the engine that loads
them and renders a template.

Template syntax
---------------
    {token}            substitute a token
    {token:upper}      modifiers: upper, lower, or a zero-pad width (e.g. 04)
    [ ... ]            optional group: dropped entirely when every token
                       inside it resolves to empty, which is how a component
                       and its delimiter disappear together
    /                  folder separator - any number of levels
    \\{ \\[ \\/          escape a literal brace, bracket or slash

Anything that is not a token is a literal, so delimiters are whatever you
type: `_`, `.`, `-`, or nothing at all.

Token configuration
-------------------
    label          human-readable name, used in messages and the report
    type           "string" (default) or "int"
    charset        "alpha", "alnum" or "any" - what a typed value may contain
    allow          extra characters kept on top of `charset`, e.g. "-" so words
                   can be separated. Never list a character the schema uses as
                   a delimiter, or names stop being parseable
    case           "upper", "lower" or absent
    length         exact character count
    pad            zero-pad width for an int
    prefix         literal glued in front, e.g. "v" for versions
    pattern        extra regex a typed value must match in full
    optional       an empty value is allowed and renders as nothing
    presets        list of values offered as a dropdown in the node
    allow_custom   whether that dropdown also offers free text (default true)
    default        the node's initial value
    step           spinner increment for an int
    layer_pattern  presets matching this regex take a layer number: bg -> bg02
    layer_pad      digits for that layer number (default 2)
    os             per-platform starting value, keyed windows / macos / linux;
                   the one for the running machine wins over `default`
    visible        false: the node shows no field and always renders the
                   token's starting value (default true)
    overridable    false: a node that receives a naming pipe always inherits
                   this token and cannot override it (default true)

A value picked from `presets` was written by the schema author, so it is taken
verbatim - `charset`, `case`, `length` and `pattern` do not touch it. That is
what lets a lowercase token still offer an uppercase preset. Free text typed
into the custom field takes the normal route and is cleaned and checked.

Tokens are offered to the user in the order they appear in the JSON file.

Schema templates
----------------
    folders        path levels below ComfyUI's output folder
    file           the basename
    filename       full name, used for the example_filename output
    shot_id        the shot_id output
    root           path levels that sit *above* `folders` on disk, e.g. a mount
                   point. These feed the absolute outputs only - filename_prefix
                   stays relative, because ComfyUI's own savers reject anything
                   outside the output folder.

Node options
------------
    options        per-input flags for folders, strict, parent_path,
                   template_override and custom_tokens: {"visible": false,
                   "value": ...} hides the input and fixes its value,
                   {"overridable": false} locks it against downstream overrides
"""

import json
import os
import re
import sys

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")

TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([^}]*))?\}")
PAD_MOD_RE = re.compile(r"^0?(\d+)$")

# The dropdown entry that reveals a token's free-text field.
CUSTOM = "(custom)"

# The node's inputs that are not tokens. A schema's `options` block may hide
# them or lock them against downstream overrides; a token may not share a name
# with one, because an override list could not tell the two apart.
OPTION_NAMES = ("folders", "strict", "parent_path", "template_override",
                "custom_tokens")

# What each option is when the node supplies nothing - and what a hidden option
# is fixed to unless the schema names a `value`.
OPTION_DEFAULTS = {
    "folders": True,
    "strict": True,
    "parent_path": "",
    "template_override": "",
    "custom_tokens": "",
}

OPTION_FLAG_KEYS = ("visible", "overridable", "value")


def _flag(config, key, where):
    """Read a boolean flag that defaults to true.

    Args:
        config: The token or option configuration.
        key: The flag to read.
        where: What the configuration belongs to, for the error message.

    Returns:
        The flag's value.

    Raises:
        NamingError: If the flag is present but not a boolean.
    """
    value = config.get(key, True)
    if not isinstance(value, bool):
        raise NamingError(f"{where}: '{key}' must be true or false (got {value!r}).")
    return value


def _current_os():
    """The key a token's `os` map is read under on this machine."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


CURRENT_OS = _current_os()


class NamingError(ValueError):
    """Raised when strict validation rejects a value or a template."""


# --- Template rendering ------------------------------------------------------

def _format_modifier(text, modifier):
    if not modifier:
        return text
    key = modifier.strip().lower()
    if key == "upper":
        return text.upper()
    if key == "lower":
        return text.lower()
    if key == "title":
        return text.title()
    pad = PAD_MOD_RE.match(key)
    if pad and text:
        try:
            return f"{int(text):0{int(pad.group(1))}d}"
        except ValueError:
            return text.rjust(int(pad.group(1)), "0")
    return text


def _render(template, values, strict, unknown):
    """Return (text, token_count, non_empty_count) for one template fragment."""
    out = []
    tokens = 0
    non_empty = 0
    i = 0
    while i < len(template):
        char = template[i]

        if char == "\\" and i + 1 < len(template):
            out.append(template[i + 1])
            i += 2
            continue

        if char == "[":
            depth = 1
            j = i + 1
            while j < len(template) and depth:
                if template[j] == "\\":
                    j += 2
                    continue
                if template[j] == "[":
                    depth += 1
                elif template[j] == "]":
                    depth -= 1
                j += 1
            if depth:
                raise NamingError("Template has an unclosed '[' optional group.")
            inner, inner_tokens, inner_filled = _render(
                template[i + 1:j - 1], values, strict, unknown,
            )
            # Keep a group with no tokens at all; drop one whose tokens are empty.
            if inner_tokens == 0 or inner_filled:
                out.append(inner)
                tokens += inner_tokens
                non_empty += inner_filled
            i = j
            continue

        if char == "]":
            raise NamingError("Template has a ']' with no matching '['.")

        match = TOKEN_RE.match(template, i)
        if match:
            name, modifier = match.group(1), match.group(2)
            tokens += 1
            if name in values:
                text = _format_modifier(str(values[name]), modifier)
            else:
                unknown.add(name)
                text = ""
            if text:
                non_empty += 1
            out.append(text)
            i = match.end()
            continue

        out.append(char)
        i += 1

    return "".join(out), tokens, non_empty


def render(template, values, strict=True):
    """Render one template against a mapping of token -> already formatted text."""
    unknown = set()
    text, _, _ = _render(template or "", values, strict, unknown)
    if unknown and strict:
        raise NamingError(
            "Template refers to unknown token(s): "
            + ", ".join("{" + n + "}" for n in sorted(unknown))
            + ". Known tokens: "
            + ", ".join("{" + n + "}" for n in sorted(values))
            + ". Add them with 'custom_tokens' (name=value, one per line)."
        )
    return text, sorted(unknown)


# --- Token specifications ----------------------------------------------------

# What each named charset keeps. `any` keeps everything, so it has no class.
CHARSET_RANGES = {
    "alpha": "A-Za-z",
    "alnum": "A-Za-z0-9",
    "any": None,
}

CHARSET_PARTS = {
    "alpha": ["letters"],
    "alnum": ["letters", "digits"],
}


def _describe_charset(charset, allow):
    """Word the rule for a message: 'letters and digits', 'letters, digits and -'."""
    parts = list(CHARSET_PARTS.get(charset, [charset]))
    parts += [f"'{c}'" for c in allow]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


class TokenSpec:
    """How one token is offered, cleaned, cased, padded and validated."""

    def __init__(self, name, config):
        config = config or {}
        self.name = name
        self.label = config.get("label", name)
        self.type = config.get("type", "string")        # string | int
        self.charset = config.get("charset", "any")     # alpha | alnum | any
        self.case = config.get("case")                  # upper | lower | None
        self.length = config.get("length")              # exact character count
        self.pad = config.get("pad")                    # zero pad width (int)
        self.prefix = config.get("prefix", "")          # e.g. "v" for versions
        self.pattern = config.get("pattern")            # extra regex check
        self.optional = bool(config.get("optional", False))

        # How the node offers this token.
        self.presets = [str(p) for p in (config.get("presets") or [])]
        self.allow_custom = bool(config.get("allow_custom", True))
        self.default = config.get("default")
        self.step = config.get("step")
        self.layer_pattern = config.get("layer_pattern")
        self.layer_pad = int(config.get("layer_pad", 2))
        # Per-OS starting values, e.g. a mount point that differs per platform.
        self.os_defaults = config.get("os") or {}

        # Whether the node shows the token at all, and whether a node that
        # receives a pipe may override it. A hidden token always renders its
        # initial value, so there is nothing to override.
        self.visible = _flag(config, "visible", f"Token '{name}'")
        overridable_flag = _flag(config, "overridable", f"Token '{name}'")
        self.overridable = self.visible and overridable_flag

        # Characters kept on top of `charset`, e.g. "-" to separate words. Only
        # meaningful for characters the schema does not use as a delimiter.
        self.allow = str(config.get("allow", ""))
        self.stripper = self._build_stripper()

    def _build_stripper(self):
        ranges = CHARSET_RANGES.get(self.charset)
        if ranges is None:          # "any", or an unknown name: keep everything
            return None
        extra = "".join(re.escape(c) for c in self.allow)
        return re.compile(f"[^{ranges}{extra}]")

    # -- what the node needs to build a widget --------------------------------

    @property
    def is_int(self):
        return self.type == "int"

    @property
    def options(self):
        """Dropdown entries, with the custom escape hatch last when allowed."""
        if not self.presets:
            return []
        return self.presets + ([CUSTOM] if self.allow_custom else [])

    def layered_presets(self):
        """Presets that take a layer number, e.g. the plate types."""
        if not self.layer_pattern:
            return []
        return [p for p in self.presets if re.fullmatch(self.layer_pattern, p)]

    def initial(self):
        """The node's starting value for this token, on this machine."""
        if self.os_defaults.get(CURRENT_OS) is not None:
            return self.os_defaults[CURRENT_OS]
        if self.default is not None:
            return self.default
        if self.presets:
            return self.presets[0]
        return 0 if self.is_int else ""

    # -- turning input into text ----------------------------------------------

    def resolve(self, value, strict, warnings, custom=None, layer=0):
        """Turn raw node input into the final token text, prefix included."""
        if self.presets:
            selected = str("" if value is None else value).strip()
            if not selected or selected == CUSTOM:
                if not self.allow_custom:
                    raise NamingError(
                        f"{self.label}: pick one of {', '.join(self.presets)}."
                    )
                body = self._clean(custom, strict, warnings)
            elif selected in self.presets:
                body = selected  # authored in the schema, so taken verbatim
            elif self.allow_custom:
                # Free text that arrived by another route, e.g. custom_tokens.
                body = self._clean(selected, strict, warnings)
            else:
                raise NamingError(
                    f"{self.label}: '{selected}' is not one of "
                    f"{', '.join(self.presets)}."
                )
        else:
            body = self._clean(value, strict, warnings)

        if not body:
            return ""
        return self.prefix + self._with_layer(body, layer, warnings)

    def _clean(self, value, strict, warnings):
        """Validate and normalise a free value. Returns text without the prefix."""
        if self.is_int:
            width = self.pad or 0
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise NamingError(f"{self.label} must be a whole number (got {value!r}).")
            text = f"{number:0{width}d}" if width else str(number)
            if width and len(text) > width:
                _fail(f"{self.label} {number} does not fit in {width} digits.",
                      strict, warnings)
            if self.step and self.step > 1 and number % self.step:
                warnings.append(
                    f"Note: {self.label.lower()} {number} is not a multiple of "
                    f"{self.step}. The schema increments by {self.step}, but "
                    "off-grid values are accepted."
                )
            return text

        # No token is ever legitimately true/false. This shows up when a node on
        # the canvas predates a token the schema has since gained: the frontend
        # renames the leftover widgets by position, so a boolean further down
        # lands here. Say so instead of quietly building a path out of "True".
        if isinstance(value, bool):
            _fail(f"{self.label} received {value!r}, which is not a name. A node "
                  "placed before this schema gained the token keeps the old "
                  "field order - delete it and add it again.", strict, warnings)
            value = ""

        raw = ("" if value is None else str(value)).strip()
        if not raw:
            if self.optional:
                return ""
            raise NamingError(f"{self.label} cannot be empty.")

        cleaned = raw
        if self.stripper is not None:
            cleaned = self.stripper.sub("", raw)
            if cleaned != raw:
                kind = _describe_charset(self.charset, self.allow)
                _fail(f"{self.label}: only {kind} are allowed - '{raw}' was "
                      f"reduced to '{cleaned}'.", strict, warnings)

        if self.case == "upper":
            cleaned = cleaned.upper()
        elif self.case == "lower":
            cleaned = cleaned.lower()

        if not cleaned:
            if self.optional:
                return ""
            raise NamingError(f"{self.label} cannot be empty.")

        if self.length and len(cleaned) != self.length:
            _fail(f"{self.label} must be exactly {self.length} characters "
                  f"(got '{cleaned}', {len(cleaned)}).", strict, warnings)
            if len(cleaned) > self.length:
                cleaned = cleaned[:self.length]

        # A value that carries a layer number answers to layer_pattern instead.
        if self.pattern and not self._is_layered(cleaned):
            if not re.fullmatch(self.pattern, cleaned):
                _fail(f"{self.label} '{cleaned}' does not match the schema pattern "
                      f"{self.pattern}.", strict, warnings)

        return cleaned

    def _is_layered(self, text):
        return bool(self.layer_pattern and re.fullmatch(self.layer_pattern, text))

    def _with_layer(self, text, layer, warnings):
        """Append the layer number a layered value is entitled to: bg -> bg02."""
        if not self.layer_pattern:
            return text
        match = re.fullmatch(self.layer_pattern, text)
        if not match:
            return text

        groups = match.groups()
        stem = groups[0] if groups and groups[0] else text
        number = groups[1] if len(groups) > 1 and groups[1] else ""
        try:
            layer = int(layer or 0)
        except (TypeError, ValueError):
            layer = 0

        if layer > 0:
            if number and int(number) != layer:
                warnings.append(
                    f"{self.label}: '{text}' already carries a layer number; "
                    f"'{layer}' was ignored."
                )
            elif not number:
                number = f"{layer:0{self.layer_pad}d}"

        return stem + number


def _fail(message, strict, warnings):
    if strict:
        raise NamingError(message)
    warnings.append(message)


# --- Schema ------------------------------------------------------------------

class Schema:
    """One naming configuration: tokens, templates, and omission rules."""

    def __init__(self, key, data):
        self.key = key
        self.label = data.get("label", key)
        self.description = data.get("description", "")
        self.tokens = {
            name: TokenSpec(name, cfg) for name, cfg in (data.get("tokens") or {}).items()
        }
        self.folders = list(data.get("folders") or [])
        self.file = data.get("file") or ""
        self.filename = data.get("filename") or "{basename}"
        self.shot_id = data.get("shot_id") or ""
        # Path levels that sit above `folders` on disk, e.g. a mount point.
        # Only the absolute outputs use them; filename_prefix never does.
        self.root = list(data.get("root") or [])
        self.rules = list(data.get("rules") or [])

        clash = sorted(set(self.tokens) & set(OPTION_NAMES))
        if clash:
            raise NamingError(
                f"Schema '{key}': token name(s) {', '.join(clash)} clash with "
                "the node's own inputs - rename the token.")
        self._options = self._read_options(key, data.get("options") or {})

    def spec(self, name):
        return self.tokens.get(name) or TokenSpec(name, {"optional": True})

    @staticmethod
    def _read_options(key, block):
        """Validate the schema's `options` block and fill in the defaults."""
        unknown = sorted(set(block) - set(OPTION_NAMES))
        if unknown:
            raise NamingError(
                f"Schema '{key}': unknown option(s) {', '.join(unknown)} in "
                f"'options'. Known: {', '.join(OPTION_NAMES)}.")
        flags = {}
        for name in OPTION_NAMES:
            config = block.get(name)
            if config is None:
                config = {}
            elif not isinstance(config, dict):
                raise NamingError(
                    f"Schema '{key}': option '{name}' must be a dict of "
                    f"{', '.join(OPTION_FLAG_KEYS)} (got {config!r}).")
            stray = sorted(set(config) - set(OPTION_FLAG_KEYS))
            if stray:
                raise NamingError(
                    f"Schema '{key}': option '{name}' has unknown key(s) "
                    f"{', '.join(stray)}. Known: {', '.join(OPTION_FLAG_KEYS)}.")
            where = f"Schema '{key}', option '{name}'"
            visible = _flag(config, "visible", where)
            overridable_flag = _flag(config, "overridable", where)
            default = OPTION_DEFAULTS[name]
            value = config.get("value", default)
            if type(value) is not type(default):
                raise NamingError(
                    f"{where}: 'value' must be a {type(default).__name__} "
                    f"(got {value!r}).")
            flags[name] = {
                "visible": visible,
                "overridable": visible and overridable_flag,
                "value": value,
            }
        return flags

    def option_flags(self, name):
        """How this schema offers one of the node's options.

        Args:
            name: One of `OPTION_NAMES`.

        Returns:
            A dict with `visible`, `overridable` and `value`.
        """
        return dict(self._options[name])

    def effective_options(self, supplied):
        """Resolve the node's options, fixing the ones this schema hides.

        Args:
            supplied: Option values from the node; missing ones use defaults.

        Returns:
            A dict with every name in `OPTION_NAMES`.
        """
        result = {}
        for name in OPTION_NAMES:
            flags = self._options[name]
            if flags["visible"]:
                result[name] = supplied.get(name, OPTION_DEFAULTS[name])
            else:
                result[name] = flags["value"]
        return result

    def apply_rules(self, values, notes):
        """Drop tokens that the schema says cannot coexist (e.g. plates + vendor)."""
        for rule in self.rules:
            when = rule.get("when") or {}
            token, pattern = when.get("token"), when.get("matches")
            if not token or not pattern:
                continue
            if not re.fullmatch(pattern, str(values.get(token, ""))):
                continue
            for name in rule.get("omit") or []:
                if values.get(name):
                    note = rule.get("note") or f"'{name}' omitted by schema rule"
                    notes.append(f"{note} (dropped '{values[name]}').")
                values[name] = ""
        return values

    def render_prefix(self, values, include_folders=True, override=None, strict=True):
        """Render the folder levels + basename that form a filename_prefix."""
        if override and override.strip():
            text, unknown = render(override.strip(), values, strict)
            segments = [s for s in text.split("/") if s]
            return "/".join(segments), (segments[-1] if segments else ""), unknown

        unknown = set()
        segments = []
        if include_folders:
            for level in self.folders:
                text, missing = render(level, values, strict)
                unknown.update(missing)
                if text:
                    segments.append(text)
        basename, missing = render(self.file, values, strict)
        unknown.update(missing)
        if basename:
            segments.append(basename)
        return "/".join(segments), basename, sorted(unknown)

    def render_root(self, values):
        """The absolute location this schema sits at, empty when it declares none."""
        segments = []
        for level in self.root:
            text, _ = render(level, values, strict=False)
            text = text.strip().rstrip("/")
            if text:
                segments.append(text)
        return "/".join(segments)

    def render_shot_id(self, values):
        """The schema's shot identifier, or empty when it declares none."""
        if not self.shot_id:
            return ""
        text, _ = render(self.shot_id, values, strict=False)
        return text


# --- Loading -----------------------------------------------------------------

def _builtin_default():
    return Schema("vfx_default", json.loads(DEFAULT_SCHEMA_JSON))


def available_schemas():
    """Map of schema key -> file path, for every JSON under schemas/."""
    found = {}
    if os.path.isdir(SCHEMA_DIR):
        for entry in sorted(os.listdir(SCHEMA_DIR)):
            if entry.lower().endswith(".json"):
                found[os.path.splitext(entry)[0]] = os.path.join(SCHEMA_DIR, entry)
    return found


def schema_names():
    names = list(available_schemas())
    if "vfx_default" in names:
        names.remove("vfx_default")
        names.insert(0, "vfx_default")
    return names or ["vfx_default"]


def load_schema(key):
    path = available_schemas().get(key)
    if not path:
        return _builtin_default()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return Schema(key, json.load(handle))
    except (OSError, ValueError) as error:
        raise NamingError(f"Could not load schema '{key}': {error}")


def parse_custom_tokens(text, strict=False):
    """Parse `name=value` lines (or comma separated pairs) into extra tokens."""
    values = {}
    if not text:
        return values
    for chunk in re.split(r"[\n,]", text):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if "=" not in chunk:
            if strict:
                raise NamingError(
                    f"custom_tokens: '{chunk}' is not a name=value pair."
                )
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
            if strict:
                raise NamingError(f"custom_tokens: '{name}' is not a valid token name.")
            continue
        values[name] = value.strip()
    return values


DEFAULT_SCHEMA_JSON = r"""
{
  "label": "VFX default",
  "description": "SHOW_SEQ_SHOT_task_ven_v### with the sequence in its own folder.",
  "tokens": {
    "show":    {"label": "Show code", "charset": "alpha", "case": "upper", "length": 3, "default": "SHW"},
    "seq":     {"label": "Sequence code", "charset": "alpha", "case": "upper", "length": 3, "default": "SEQ"},
    "shot":    {"label": "Shot number", "type": "int", "pad": 4, "default": 10, "step": 10},
    "task":    {
      "label": "Task", "charset": "alnum", "case": "lower", "default": "comp",
      "presets": ["comp", "prev", "roto", "pant", "layt", "anim", "lght", "rndr",
                  "mp", "bg", "fg", "el", "cp", "rp"],
      "allow_custom": true,
      "layer_pattern": "(mp|bg|fg|el|cp|rp)(\\d{1,2})?"
    },
    "vendor":  {"label": "Vendor id", "charset": "alpha", "case": "lower", "length": 3, "optional": true},
    "version": {"label": "Version", "type": "int", "pad": 3, "prefix": "v", "default": 1},
    "frame":   {"label": "Frame", "type": "int", "pad": 4, "default": 1001},
    "ext":     {
      "label": "Extension", "charset": "alnum", "case": "lower", "default": "exr",
      "presets": ["exr", "png", "tif", "jpg", "dpx", "mov", "mp4"],
      "allow_custom": true
    }
  },
  "folders": ["{show}_{seq}_{shot}_{task}[_{vendor}]_{version}"],
  "file": "{show}_{seq}_{shot}_{task}[_{vendor}]_{version}",
  "filename": "{basename}.{frame}.{ext}",
  "shot_id": "{show}_{seq}_{shot}",
  "rules": [
    {
      "when": {"token": "task", "matches": "(mp|bg|fg|el|cp|rp)\\d*"},
      "omit": ["vendor"],
      "note": "Lab plates carry no vendor id"
    }
  ]
}
"""
