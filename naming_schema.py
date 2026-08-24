"""
Schema-driven naming.

The configuration - which tokens exist, how each one is formatted and
validated, what the delimiters are, in which order the tokens appear and how
many folder levels they render into - lives in JSON files under `schemas/`.
This module is only the engine that loads them and renders a template.

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
"""

import json
import os
import re

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")

TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([^}]*))?\}")
PAD_MOD_RE = re.compile(r"^0?(\d+)$")


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

CHARSETS = {
    "alpha": re.compile(r"[^A-Za-z]"),
    "alnum": re.compile(r"[^A-Za-z0-9]"),
    "any": None,
}


class TokenSpec:
    """How one token is cleaned, cased, padded and validated."""

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

    def format(self, value, strict, warnings, pad_override=None):
        """Clean and format a raw widget value into its final string."""
        if self.type == "int":
            width = pad_override if pad_override is not None else (self.pad or 0)
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise NamingError(f"{self.label} must be a whole number (got {value!r}).")
            text = f"{number:0{width}d}" if width else str(number)
            if width and len(text) > width:
                _fail(f"{self.label} {number} does not fit in {width} digits.",
                      strict, warnings)
            return self.prefix + text

        raw = ("" if value is None else str(value)).strip()
        if not raw:
            if self.optional:
                return ""
            raise NamingError(f"{self.label} cannot be empty.")

        cleaned = raw
        stripper = CHARSETS.get(self.charset)
        if stripper is not None:
            cleaned = stripper.sub("", raw)
            if cleaned != raw:
                kind = "letters" if self.charset == "alpha" else "letters and digits"
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

        if self.pattern and not re.fullmatch(self.pattern, cleaned):
            _fail(f"{self.label} '{cleaned}' does not match the schema pattern "
                  f"{self.pattern}.", strict, warnings)

        return self.prefix + cleaned


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
        self.rules = list(data.get("rules") or [])
        self.task_rules = data.get("task_rules") or {}

    def spec(self, name):
        return self.tokens.get(name) or TokenSpec(name, {"optional": True})

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
    "show":    {"label": "Show code", "charset": "alpha", "case": "upper", "length": 3},
    "seq":     {"label": "Sequence code", "charset": "alpha", "case": "upper", "length": 3},
    "shot":    {"label": "Shot number", "type": "int", "pad": 4},
    "task":    {"label": "Task", "charset": "alnum"},
    "vendor":  {"label": "Vendor id", "charset": "alpha", "case": "lower", "length": 3, "optional": true},
    "version": {"label": "Version", "type": "int", "pad": 3, "prefix": "v"},
    "frame":   {"label": "Frame", "type": "int", "pad": 4},
    "ext":     {"label": "Extension", "charset": "alnum", "case": "lower"}
  },
  "folders": ["{show}_{seq}_{shot}_{task}[_{vendor}]_{version}"],
  "file": "{show}_{seq}_{shot}_{task}[_{vendor}]_{version}",
  "filename": "{basename}.{frame}.{ext}",
  "task_rules": {
    "plate_pattern": "(mp|bg|fg|el|cp|rp)(\\d{1,2})?",
    "standard_pattern": "[a-z]{4}",
    "final": "FINAL"
  },
  "rules": [
    {
      "when": {"token": "task", "matches": "(mp|bg|fg|el|cp|rp)\\d*"},
      "omit": ["vendor"],
      "note": "Lab plates carry no vendor id"
    }
  ]
}
"""
