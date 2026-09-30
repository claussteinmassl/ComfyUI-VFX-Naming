# ComfyUI VFX Naming Convention

A single node that composes a VFX-compliant `filename_prefix` string for
**Save Image**, **Save Image (Advanced)**, and video saver nodes
(VideoHelperSuite `Video Combine`, etc.), so ComfyUI output drops straight into
a film or episodic VFX pipeline instead of `ComfyUI_00001_.png`.

Based on the *VFX Naming Convention* paper by Victor Perez, VFX Supervisor —
generic, with no show-specific codes baked in.

```
SHW_SEQ_0010_comp_vnd_v001/
    SHW_SEQ_0010_comp_vnd_v001.1001.exr
```

## The naming convention

Every file exchanged with or within the VFX department follows one string.
Each department is responsible for naming the material it generates; transfers
that do not meet the convention should be treated as undelivered.

### Structure

```
AAA_AAA_####_aaaa_aaa_v###.####.aaa
```

```
<SHOW CODE>_<SEQUENCE CODE>_<SHOT NUMBER>_<TASK>_<VENDOR ID>_<VERSION NUMBER>.<FRAME NUMBER>.<FILE EXTENSION>
```

### Components

| Component | Specification |
|---|---|
| `<SHOW CODE>` | 3 alphabetic characters (letters), uppercase |
| `_` | 1 underscore separator (fixed) |
| `<SEQUENCE CODE>` | 3 alphabetic characters (letters), uppercase |
| `_` | 1 underscore separator (fixed) |
| `<SHOT NUMBER>` | 4 digits (padded numbers), in increments of tens |
| `_` | 1 underscore separator (fixed) |
| `<TASK>` | 4 alphabetic characters (letters), lowercase &nbsp;<sup>1</sup> |
| `_` | 1 underscore separator (fixed) |
| `<VENDOR ID>` | 3 alphabetic characters (letters), lowercase &nbsp;<sup>2</sup> |
| `_` | 1 underscore separator (fixed) |
| `<VERSION NUMBER>` | `v` prefixed + 3 digits (padded numbers) |
| `.` | 1 period separator (fixed) |
| `<FRAME NUMBER>` | 4 digits (padded numbers) — first frame `1001` |
| `.` | 1 period separator (fixed) |
| `<FILE EXTENSION>` | 3 alphabetic characters (letters), lowercase |

<sup>1</sup> Plates provided by the Lab use fewer characters (usually 2) and may
include numbers; this is described under **Plates** below. Finalised VFX shots
delivered by a vendor use a special `<TASK>` format — see **Vendor
exceptions**.

<sup>2</sup> Plates provided by the Lab do not contain the `<VENDOR ID>`
component, nor the corresponding underscore separator between components.

**Filename examples**

```
SHW_SEQ_0010_comp_vnd_v001.1001.exr
SHW_SEQ_0125_prev_vnd_v001.1001.exr
```

### Shot ID and task denominators

```
SHW_SEQ_0010_comp_vnd_v001.1001.exr
└────── shot id ─────┘└─ task denominators ─┘
```

| Part | Meaning |
|---|---|
| **Shot ID** | The unique shot name — show, sequence and shot number |
| **Task denominators** | Define the work, task or element contained in the file |

Read as: show `SHW`, sequence `SEQ`, shot 1, task compositing, vendor `vnd`,
version 1, frame 1001 (first frame of the range), OpenEXR.

### Vendor exceptions

VFX vendors must add the `<VENDOR ID>` tag assigned to them for any exchange of
files out of their facility. The vendor code is assigned by the VFX Producer
and communicated in advance.

For complete and approved VFX shots — marked as *Final* — the status in the
`<TASK>` component is `FINAL`, in uppercase:

```
SHW_SEQ_0030_FINAL_vnd_v012.1234.exr
```

> `FINAL` is **not** among the shipped presets. Add it to your schema's `task`
> presets if you use it — a preset is taken verbatim, so it keeps its uppercase
> even though the token is otherwise lowercase.

### Folder structure

File sequences must be contained in folders named after the Shot ID and the
Task and Version Number denominators — that is, the filename without the frame
number and extension:

```
SHW_SEQ_0010_comp_vnd_v001/
    SHW_SEQ_0010_comp_vnd_v001.1001.exr
    SHW_SEQ_0010_comp_vnd_v001.1002.exr
```

### Plates — Lab inputs to VFX

In this context, *plates* are image sequences derived from images captured by a
camera and processed by the laboratory to be provided to the VFX vendors for
visual effects work.

Plates do **not** contain the `<VENDOR ID>` component, nor its underscore
separator. For plates the `<TASK>` component is an exception of only 2
characters, and shall have one of the following values:

| Task | Plate type |
|---|---|
| `mp` | **Main Plate** — when only one element is required to produce the final VFX work |
| `bg` | **Background plate** — for VFX work requiring multiple elements. Background plates carry layer identification, for example `bg` or `bg02` |
| `fg` | **Foreground plate** — for VFX work requiring multiple elements. Foreground plates include layer information, for example `fg12` |
| `el` | **Element plate** — isolated elements of the shot: partial composites in multi-vendor shots, or rotoscoped and CG elements delivered at production's request |
| `cp` | **Clean Plate** — to be used for cleanup work |
| `rp` | **Reference Plate** — such as lighting reference |

> There is some redundancy between `fg` and `el`. Where ambiguous, the choice is
> user preference.

LMTs, CDLs and any other LUTs must carry the same name as the plate they refer
to, with the exception of the extension:

```
SHW_SEQ_0010_mp_v001.1001.exr
SHW_SEQ_0010_mp_v001.1001.cube
SHW_SEQ_0010_cp_v001.1001.exr
SHW_SEQ_0010_cp_v001.1001.cdl
SHW_SEQ_0010_bg02_v001.1001.exr
```

### Frame ranges

| | |
|---|---|
| First frame of the plate | `1001` |
| First frame of the edit range | `1011` |
| Frame handles | 10 head + 10 tail |
| Work range | Matches the plate range |

VFX work must be executed for the whole work range, **including the handles**.
A 44 frame shot therefore runs 1001–1064:

```
 1001         1011                     1054         1064
  |____________|________________________|____________|
  |  handles   |       edit range       |  handles   |
  |   10 fr    |         44 fr          |   10 fr    |
  |____________|________________________|____________|
  |                                                  |
  |<------- work range = plate range = 64 fr ------->|
```

> **Editorial** should be aware of the handles when reconforming VFX shots in
> the timeline. An eyeballing check is advised.

## Nodes

Two nodes work together: **VFX Naming Convention** builds a naming pipe, and
**VFX Naming Breakout** unpacks it into `filename_prefix` and the other
values. A single node still covers the simple case — connect its
`naming_pipe` straight into a breakout — while a shot with several passes can
chain further Naming Convention nodes off the first one; see **Inheriting and
overriding (naming pipe)** below.

### VFX Naming Convention

**VFX Naming Convention (Filename Prefix)** — category `VFX/naming`.

#### Inputs

**The schema decides which fields this node shows.** Picking a schema swaps the
token fields for the ones that schema declares — there is no fixed list of
widgets, and none of the token names below are known to the Python code.

| Input | Purpose |
|---|---|
| `naming_pipe` | optional — inherit schema, tokens and options from an upstream VFX Naming Convention node instead of configuring this node from scratch; see **Inheriting and overriding (naming pipe)** below |
| `schema` | which JSON schema in `schemas/` to render — and therefore which fields appear below it. Ignored while `naming_pipe` is connected: the schema always comes from upstream |
| `folders` | on = render the schema's folder levels, off = files straight into the output folder |
| `strict` | on = abort on any violation; off = auto-correct and warn |
| `parent_path` | optional sub-path, e.g. `SHW/SEQ` or `%date:yyyy-MM-dd%` |
| `template_override` | override the schema's templates for this node only |
| `custom_tokens` | extra `name=value` tokens for the template; a name matching a token above overrides it |
| `preview` | read-only: the assembled result, refreshed as you type |

There is also an `overrides` input: a hidden, socketless widget holding a JSON
list of the field names this node overrides on its `naming_pipe` (e.g.
`["task", "ext"]`). It has no widget of its own in either renderer — the
override UI described below manages it — and it is saved with the workflow
like any other value.

With `vfx_default` selected, the token fields are:

| Field | Purpose |
|---|---|
| `show`, `seq` | 3-letter codes, auto-uppercased |
| `shot` | arrows snap to the nearest shot ending in 0; any number can be typed |
| `task` | dropdown of task codes and plate types, plus `(custom)` |
| `task_custom` | free task code; appears only when `task` is `(custom)` |
| `task_layer` | appears only on a plate preset — `2` turns `bg` into `bg02` |
| `vendor` | 3 letters; **leave empty for lab plates** |
| `version` | zero padded, `v` prefixed |
| `frame` | work-range head; convention is `1001` (10 head + 10 tail handles) |
| `ext` | dropdown of extensions, plus `(custom)` |

Pick `studio` instead and `seq`, `vendor` and `task_layer` are gone, while a
`colorspace` dropdown appears. A field shared by both schemas keeps its value
across the switch.

#### Output

The only output is `naming_pipe`: schema, tokens, options and the rendered
result, bundled for a downstream **VFX Naming Breakout** node or another
**VFX Naming Convention** node that inherits from it.

### VFX Naming Breakout

**VFX Naming Breakout** — category `VFX/naming`. Unpacks a `naming_pipe` into
the ten values a single naming node used to output directly.

#### Inputs

| Input | Purpose |
|---|---|
| `naming_pipe` | from a VFX Naming Convention node |

#### Outputs

| Output | Example |
|---|---|
| `filename_prefix` | `SHW_SEQ_0010_comp_vnd_v001/SHW_SEQ_0010_comp_vnd_v001` |
| `folder_name` | `SHW_SEQ_0010_comp_vnd_v001` |
| `directory` | `/Volumes/projects/Atlas/02_wip/shots/sh010/aov_depth/out` — absolute, empty unless the schema declares a `root` |
| `full_path` | `directory` + `basename`, without frame or extension |
| `basename` | `SHW_SEQ_0010_comp_vnd_v001` |
| `shot_id` | `SHW_SEQ_0010` — from the schema's `shot_id` template, empty when it declares none |
| `extension` | `exr` (lowercase, no leading dot) |
| `example_filename` | `SHW_SEQ_0010_comp_vnd_v001.1001.exr` |
| `first_frame` | `1001` (INT — feed frame-range inputs) |
| `report` | full breakdown plus any validation warnings |

Wire the breakout's `filename_prefix` into the saver's `filename_prefix`
widget (convert it to an input first: right-click the Save node → *Convert
widget to input*, or drag from the breakout's output onto the widget in
recent frontends).

## Inheriting and overriding (naming pipe)

One main node holds a shot's settings. Further nodes take its `naming_pipe`
output and change only the fields that differ, so show, sequence, shot and
version stay in sync automatically instead of being retyped — and drifting
apart — across a plate, a roto pass and a comp:

```
[VFX Naming Convention]   main: show, seq, shot, version, ...
        │ naming_pipe
        ▼
[VFX Naming Convention]   child: task = roto, everything else inherited
        │ naming_pipe
        ▼
[VFX Naming Breakout]  →  filename_prefix, directory, shot_id, ...
```

### The schema is locked

**The schema always comes from upstream and is locked on a node that receives
a pipe.** The child's own `schema` widget is set to match it, the widget set
is rebuilt to that schema's fields, and the schema row itself is drawn
locked — the same as a field the schema marks `overridable: false`.
Overriding the schema itself is not supported.

### Row states

Only while `naming_pipe` is connected, every field row is in one of three
states:

| State | Canvas renderer | Vue nodes renderer | Meaning |
|---|---|---|---|
| inherited | switch off (grey), row dimmed | `○ name` | value comes from the upstream node and follows it live |
| overridden | switch on (orange), orange outline, `↺` after the label | `● name` in orange, `↺` after it | this node's own value is used instead of the upstream one |
| locked | `⛓` in place of the switch | `⛓ name` | `overridable: false` in the schema, or the `schema` row itself — always inherited, no switch |

Without a pipe connected, rows carry no switch or glyph and behave exactly as
before. Multiline fields (`template_override`, `custom_tokens`) show the glyph
in their placeholder in both renderers.

### Toggling a field

- **Click the switch** at the left of the row (canvas renderer) to turn the
  override off or on. On rows with stepper arrows the switch sits just right
  of the left arrow; the arrows, the dropdown and number dragging keep
  working everywhere else on the row.
  - **Off keeps the value.** The row goes back to the inherited look and
    shows the upstream value, but the node remembers what you had set,
    including values of fields a token reveals (a plate's `task_layer`).
  - **On restores it.** Switching the override back on brings the
    remembered values back. They are saved with the workflow (in the node's
    properties), so this also works after reloading.
- **Click `↺`** after the label of an overridden row to discard the override
  for good: the field goes back to inherited and the remembered value is
  deleted, so switching it on again starts from the upstream value. When the
  label and value leave no room for the icon, it is not drawn; use the
  right-click action instead.
- **Edit an inherited value** — typing into the field (or stepping it with
  its arrows) overrides it automatically, with no need to click the switch
  first. The fresh edit replaces any remembered value.
- **Right-click a row** for its actions at the top of the menu:
  "● Override task: off (keep value)" or "○ Override task: on", and
  "↺ Reset task" when the field is overridden or has a remembered value. A
  revealed row such as `task_layer` acts on its token (`task`).
- **Right-click the node** → **VFX overrides** submenu: one entry per
  overridable field ("○ Override task" when inherited, "● Inherit task" when
  overridden; inheriting keeps the value like the switch does), plus
  **Inherit all** to clear every override and every remembered value on the
  node at once (shown only once something is overridden).

In the **Vue nodes renderer** the label glyph is the switch: click the label
cell of a row to flip it (off keeps the value, on restores it, as above), and
click the `↺` next to the label to reset it. Right-clicking a row adds the
same row actions to the node menu, where the Vue renderer lists them first
under **Extensions**.

Switching a field back to inherited re-mirrors the upstream value
immediately.

### Collapsing inherited rows

A switch at the bottom of the node reads "▾ hide *N* inherited fields" while
inherited/locked rows are shown, and "▸ show *N* inherited fields" while they
are hidden. Toggling it hides, or shows again, every inherited and locked
row — useful once a node overrides only one or two fields out of a large
schema. It is present only while a pipe is connected.

### Chains

A node's `naming_pipe` can itself come from another node that is a child of a
further node — main → child → grandchild, and so on. Each link only needs to
override what differs from its immediate parent; anything not overridden
anywhere in the chain still tracks the main node live.

### Refused overrides

An override is refused for one of three reasons:

- the named field does not exist on the pipe's schema — "schema '&lt;key&gt;'
  has no field '&lt;name&gt;'";
- the field is locked (`overridable: false`, or invisible via
  `visible: false`) — "'&lt;name&gt;' is locked by schema '&lt;key&gt;'";
- the field belongs to a different schema than the one this node currently
  shows, so this node has nothing of its own to apply — "this node has no
  value for '&lt;name&gt;'".

What governs strict vs. permissive is not this node's own `strict` widget in
isolation, but the **merged effective `strict`** — the pipe's `strict`
overridden by this node's own `strict` when `strict` is itself one of the
fields being overridden (and that override is allowed):

- **Strict**: the node fails with an error naming every refused field.
- **Permissive**: the inherited value is used for each refused field instead,
  and a note listing them is added to the `report` output — the run still
  completes.

### Renderers

Both the classic canvas renderer and the Vue nodes renderer are supported.
The switch and the drawn `↺` belong to the canvas renderer. In the Vue nodes
renderer the extra row styling (the dimmed look, the `↺` next to the label)
is best effort; the glyph labels, auto-override on edit and the "VFX
overrides" context menu always work in both renderers.

## Schemas — the convention is configuration

No naming rule is hardcoded in the logic. Which tokens exist, how each one is
cased, padded and validated, the delimiters, the order of the tokens, how many
folder levels they render into **and how each token is offered in the node** all
live in JSON under [`schemas/`](schemas). `naming_schema.py` is only the engine
that loads and renders them; `vfx_naming.py` contains no token name and no token
vocabulary at all.

Pick one with the `schema` widget. Five ship with the node:

| Schema | Renders |
|---|---|
| `vfx_default` | `SHW_SEQ_0010_comp_vnd_v001/SHW_SEQ_0010_comp_vnd_v001` |
| `vfx_flat` | `SHW_SEQ_0010_comp_vnd_v001` (no sequence folder) |
| `studio_nested` | `SHW/SEQ/0010/comp-vnd/v001-0010-comp-vnd` |
| `episodic_dotted` | `SHW/ep101/SEQ.0010/SHW.SEQ.0010.comp.vp.v001` |
| `studio` | `Atlas/02_wip/shots/sh010/imggen_main/out/sh010_imggen_main_v001_acescg_1001` |

`studio` is a worked example of how far a schema can depart from the
default: the show code is kept verbatim rather than uppercased, shots read
`sh010` instead of `0010`, there is no sequence and no vendor, and a
`colorspace` token exists that no other schema has — with `rec709` and `acescg`
as its only accepted values. It is also the one that declares a `root`, so it
fills the absolute path outputs; see **Absolute paths and the mount point**.

Its task list covers **AI generation work only**, since that is what ComfyUI
produces — the paper's `comp`/`layt`/`anim` vocabulary and the lab plates stay
in the other four schemas, where they belong:

```
imggen  vidgen  audgen  3dgen  retouch  restyle  relight  roto  aov  upscale  interp
```

Alongside `task` it carries a **`variant`** token that refines it, and which is
never empty — `main` for ordinary work, the pass name under `aov`:

```
shots/sh010/imggen_main/out/sh010_imggen_main_v001_acescg_1001.1001.exr
shots/sh010/aov_depth/out/sh010_aov_depth_v001_acescg_1001.1001.exr
shots/sh010/aov_normal/out/sh010_aov_normal_v001_acescg_1001.1001.exr
shots/sh010/roto_hair/out/sh010_roto_hair_v001_acescg_1001.1001.exr
```

`main` in every ordinary name is deliberate: a component that is sometimes
present and sometimes not cannot be parsed back reliably, so `variant` always
occupies its slot and every name splits into the same components.

### Writing your own

Drop a JSON file in `schemas/` and it appears in the dropdown after a restart:

```json
{
  "label": "My studio",
  "tokens": {
    "show":    {"label": "Show code", "charset": "alpha", "case": "upper", "length": 4},
    "shot":    {"label": "Shot", "type": "int", "pad": 3, "default": 10, "step": 10},
    "stage":   {"label": "Stage", "charset": "alnum", "case": "lower",
                "presets": ["previz", "postviz", "final"], "default": "previz",
                "allow_custom": false},
    "version": {"label": "Version", "type": "int", "pad": 2, "prefix": "V", "default": 1}
  },
  "folders": ["{show}", "{stage}"],
  "file": "{show}-{shot}-{stage}-{version}",
  "filename": "{basename}.{frame}.{ext}",
  "shot_id": "{show}-{shot}"
}
```

**Token specs** — `charset` (`alpha` / `alnum` / `any`), `allow` for extra
characters on top of it, `case` (`upper` / `lower`), `length` for an exact
character count, `type: "int"` with `pad`, `prefix` (the `v` in `v001`),
`pattern` for an extra regex check, and `optional: true` to allow it to be
empty.

`allow` is how a token gets a word separator:

```json
"variant": { "charset": "alnum", "case": "lower", "allow": "-" }
```

```
hair-fine   ->  hair-fine     kept
hair_fine   ->  hairfine      stripped, with a warning
hair!fine   ->  hairfine      stripped, with a warning
```

> **Never list a character the schema uses as a delimiter.** `studio` joins its
> components with `_`, so `-` is safe there and `_` is not. `studio_nested`
> joins with `-`, so the reverse holds. A delimiter inside a token forges a
> component boundary and the name stops being parseable — which is the whole
> point of having a convention.

**How a token is offered** — every token becomes a field in the node, in the
order it appears in the file:

| Field | Effect |
|---|---|
| `presets` | list of values → the token renders as a dropdown instead of a text box |
| `allow_custom` | default `true`; adds a `(custom)` entry that reveals a free-text field. Set `false` and the presets are the only accepted values |
| `default` | the field's starting value |
| `step` | spinner increment for an `int` token |
| `layer_pattern` | presets matching this regex reveal a layer number that is appended: `bg` + `2` → `bg02` |
| `layer_pad` | digits for that layer number (default `2`) |
| `os` | per-platform starting value, keyed `windows` / `macos` / `linux`; the entry for the running machine beats `default` |
| `visible` | default `true`; `false` gives the token no field at all — it always renders its starting value (`os`, then `default`, then the first preset) and any supplied value is ignored. A hidden token is implicitly not overridable |
| `overridable` | default `true`; `false` means a node that receives a naming pipe always takes this token from the pipe — its row shows the inherited value, disabled, with no toggle. Without a pipe it has no effect |

**A preset is taken verbatim.** It was written by the schema author, so
`charset`, `case`, `length` and `pattern` do not touch it — which is how a
lowercase token can still offer an uppercase preset like `FINAL`. Text typed
into a `(custom)` field takes the normal route and is cleaned and checked.

**Hiding or locking the node's own inputs** — `folders`, `strict`,
`parent_path`, `template_override` and `custom_tokens` are the same five
inputs on every schema, but a schema can hide or lock them with a top-level
`options` block:

```json
"options": {
  "template_override": {"visible": false},
  "strict":            {"visible": false, "value": true},
  "folders":           {"overridable": false}
}
```

- `visible: false` hides that input's widget while this schema is selected.
  The backend ignores any value supplied for it and uses `value`, or the
  input's normal default when `value` is absent.
- `overridable: false` behaves as for a token: a node that receives a naming
  pipe always inherits this input and cannot switch it to overridden.

`load_schema` raises an error at load time when a schema's `options` block:

- names a key that is not one of the five inputs above,
- gives a token the same name as one of them, because an override list could
  not tell the two apart,
- sets `visible` or `overridable` to anything other than `true` or `false`.

> **After changing a schema's token list, delete and re-add the node.** ComfyUI
> stores widget values by position, so a node already on the canvas keeps the
> old field order and a value further down slides into the new token. A reload
> is not enough — the node in the graph keeps its widget list. The node refuses
> a true/false value with an explanatory warning rather than building a path out
> of it, which is how this announces itself.

**Templates** — `folders` is a list of path levels (any depth), `file` is the
basename, `filename` is the full name used for the `example_filename` output,
`shot_id` feeds the output of the same name, and `root` holds the levels that
sit *above* `folders` on disk — see below.

| Syntax | Meaning |
|---|---|
| `{token}` | substitute a token |
| `{token:upper}` | modifiers: `upper`, `lower`, or a pad width like `04` |
| `[ ... ]` | optional group — dropped whole when every token inside is empty, which is how a component *and its delimiter* disappear together |
| `/` | folder separator, any number of levels |
| anything else | a literal, so delimiters are whatever you type |

**Rules** drop tokens that cannot coexist. The shipped rule is the lab-plate
one: when `task` matches a plate type, `vendor` is omitted along with its
delimiter.

### Per-node overrides

`template_override` replaces the schema's templates for one node — handy for a
one-off without writing a file:

```
{show}/{seq}/{shot}/{task}/{show}_{shot}_{version}
```

`custom_tokens` adds tokens the widgets do not cover, one `name=value` per
line, referenced as `{episode}`:

```
episode=101
artist=vp
```

## Absolute paths and the mount point

Everything above is relative to ComfyUI's `output/` folder, because that is all
`filename_prefix` can ever be — see the next section. Plenty of savers do take a
real path, though, so a schema can also declare **where it sits on disk**:

```json
"tokens": {
  "mount": {
    "label": "Mount point",
    "charset": "any",
    "optional": true,
    "os": {
      "windows": "C:/projects",
      "macos":   "/Volumes/projects",
      "linux":   "/mnt/projects"
    }
  }
},
"root": ["{mount}"]
```

`root` is a list of path levels like `folders`, but they sit *above* it. They
feed two outputs and nothing else:

```
filename_prefix : Atlas/02_wip/shots/sh010/aov_depth/out/sh010_aov_depth_v001_acescg_1001
directory       : /Volumes/projects/Atlas/02_wip/shots/sh010/aov_depth/out
full_path       : /Volumes/projects/Atlas/.../out/sh010_aov_depth_v001_acescg_1001
```

So one node feeds both kinds of saver: `filename_prefix` for ComfyUI's own,
`directory` + `basename` for one that writes wherever you point it. There is no
mode switch — both are always available, and `filename_prefix` never becomes
absolute behind your back.

`mount` is an ordinary token, so it is a normal field in the node and can be
overridden per node. What makes it useful is `os`: the node reads the entry for
the machine ComfyUI is running on, so the same schema resolves to
`/Volumes/projects` on a Mac and `C:/projects` on Windows. Detection is
automatic and there is no override — set the field by hand to build a path for
another platform.

Forward slashes throughout, including on Windows. Windows accepts them
everywhere and VFX pipelines use them by convention.

`parent_path` plays no part here: it is a sub-path *inside* ComfyUI's output
folder, which is a relative-mode idea. A schema that declares no `root` leaves
`directory` and `full_path` empty rather than quietly handing back a relative
path.

## Live preview

The node shows the assembled result while you type — no run needed:

```
prefix    : Atlas/02_wip/shots/sh010/aov_depth/out/sh010_aov_depth_v003_acescg_1001
example   : sh010_aov_depth_v003_acescg_1001.1001.exr
directory : /Volumes/projects/Atlas/02_wip/shots/sh010/aov_depth/out
full path : /Volumes/projects/Atlas/.../out/sh010_aov_depth_v003_acescg_1001

! Show code must be exactly 3 characters (got 'SH', 2).
```

Warnings appear as you go, so a value that breaks the convention shows up
immediately instead of at execution time. The preview is always evaluated
permissively — a half-typed value still renders, whatever `strict` is set to;
`strict` still governs the real run.

The naming rules are **not** reimplemented in JavaScript. `web/vfx_naming.js`
posts the current widget values to `/vfx_naming/preview` and displays whatever
Python renders, so there is only ever one interpretation of a schema. If the
extension fails to load or the route is unavailable, the preview field stays
empty and everything else works as before.

## Important: what ComfyUI appends

ComfyUI's own savers always append their own counter and extension:

```python
file = f"{filename_with_batch_num}_{counter:05}_.png"   # nodes.py, SaveImage
```

So a prefix of `SHW_SEQ_0010_comp_vnd_v001` lands on disk as:

```
SHW_SEQ_0010_comp_vnd_v001/SHW_SEQ_0010_comp_vnd_v001_00001_.png
```

The **name, folder and every component up to the version are exactly correct**;
the `.1001.exr` frame/extension tail is controlled by the saver, not the prefix,
and stock ComfyUI uses `_00001_` counters starting at 1 instead of `.1001`.
Nodes with an explicit extension/format widget (Save Image Advanced variants,
VHS Video Combine) honour the format you pick there.

To get literal `basename.1001.exr` on disk you need a saver that writes the
frame token itself — that is a separate node, not something a prefix string can
do. `extension`, `example_filename` and `first_frame` are provided so you can
drive one, or feed the format widget of a saver that accepts a string.

**Absolute paths are rejected outright**, not silently made relative:

```python
if not is_within_directory(output_dir, full_output_folder):   # folder_paths.py
    raise Exception("**** ERROR: Saving image outside the output folder is not allowed.")
```

That is why `filename_prefix` stays relative no matter what and the absolute
path is a separate output — see **Absolute paths and the mount point**.

## Shot number stepping

A schema declares the increment with `"step": 10` on an int token. The +/-
buttons then move the shot number in tens, matching the convention, but **any**
number can be typed in manually — `15`, `125`, `7`. Off-grid values are accepted
even in strict mode; they only add an advisory note to the `report` output. (The
convention's own example `SHW_SEQ_0125_prev_vnd_v001` is off-grid.)

Pressing +/- always lands on the nearest shot number ending in 0, in the
direction pressed — from 98, `+` goes to 100 and `-` goes to 90, rather than
dragging the off-grid number along to 108. On-grid values step normally
(20 -> 30).

Both behaviours need the bundled `web/vfx_naming.js`. ComfyUI's INT widget uses
one option (`step2`) for both the increment and for snapping committed values
onto that grid, so a plain `"step": 10` would round a typed 15 up to 20. The
extension supplies the stepping instead, and finds the widgets to apply it to
through the `vfxGridStep` option the node attaches to any int token whose schema
declares a step — the token can be named anything, and the `schema` dropdown
creates and destroys these widgets as you switch.

With `Comfy.VueNodes` enabled the widget renders as a DOM component whose +/-
buttons do `model = clamp(model +/- step)` and commit by calling
`widget.callback(value)` directly — never `setValue()` or `onClick()`. The grid
step is therefore applied on `pointerdown`, by setting `step2` to the exact
distance to the next grid point in that direction (the option is reactive, and
a pointerdown precedes the click by a full task, so the component re-renders
with the new step before it computes the value). The wrapped callback then
redirects an armed change onto the grid as a safety net — which is also what
makes the keyboard Up/Down arrows snap, since no re-render happens between
keydown and the component's handler.

The mechanism was verified against a live ComfyUI 1.49.6 — 20 stepping cases,
free-form typing, and no effect on other INT widgets or other nodes — before it
was retargeted from a fixed widget name to the `vfxGridStep` option in 2.0.

## Install

**ComfyUI Manager** — *Install via Git URL*, paste this repository's URL.

**Manually** — clone into your `custom_nodes` folder and restart ComfyUI:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/vctrprzvfx/ComfyUI-VFX-Naming.git
```

No dependencies beyond the Python standard library. After restarting, add the
node from the `VFX/naming` category. If the shot-number stepping behaves oddly
after an update, hard-refresh the browser (Cmd/Ctrl+Shift+R) — the bundled
JavaScript is cached.

**Requires ComfyUI 0.8.0 or newer.** The `schema` dropdown swaps the node's
fields through the V3 node API's `io.DynamicCombo`, which arrived in 0.4.0; the
nested option expansion this node relies on landed in 0.8.0. Developed and
tested against 0.34.0.

## Upgrading to 3.0

3.0 moves the ten outputs off **VFX Naming Convention** onto the new **VFX
Naming Breakout** node; the naming node's only output is now `naming_pipe`.
This is a breaking change, and it requires surgery, not just rewiring:
**every existing VFX Naming Convention node has to be deleted and re-added.**

The reason is how the frontend restores a saved node. `LGraphNode.configure()`
(frontend 1.52.7) recreates a node's inputs and outputs from what was saved on
disk, so an old node reopens with its ten old outputs and their links intact
and no `naming_pipe` input at all — the node on the canvas does not match the
node this version defines. Queuing a workflow with such a node fails
validation, typically with "Return type mismatch" or "tuple index out of
range". There is no automatic migration; `configure()` runs before this
node's Python code ever sees the workflow, so nothing here can intervene.

To upgrade:

1. Note the widget values on each existing VFX Naming Convention node (schema,
   tokens, options) — deleting the node loses them.
2. Delete the node and add a fresh **VFX Naming Convention** in its place;
   re-enter (or copy) the widget values you noted.
3. Add a **VFX Naming Breakout** node and wire the naming node's
   `naming_pipe` output into it, then reconnect the breakout's outputs
   (`filename_prefix`, `directory`, `shot_id`, ...) to whatever the old node's
   outputs used to feed.

## Upgrading to 2.0

2.0 moved the token fields out of Python and into the schema files. This is a
breaking change: ComfyUI stores widget values by position, and the widget set
now changes with the selected schema, so **a saved workflow containing this node
has to be reconfigured once**. Newly added nodes are unaffected.

What changed for schema authors:

- `task_rules` is gone. `standard_pattern` is the token's own `pattern`,
  `plate_pattern` is its `layer_pattern`, and `final` is no longer needed — a
  preset keeps its case on its own.
- `shot_padding`, `version_padding` and `frame_padding` are gone. Padding is
  `pad` on the token; copy the schema if you need a different one.
- `FINAL` is no longer a shipped preset, and `task` no longer has to be four
  characters.
- `sequence_subfolder` is now called `folders`.

## Tests

```bash
COMFYUI_PATH=/path/to/ComfyUI python3 -m unittest discover -s tests
```

`COMFYUI_PATH` is only needed for the node tests; the engine tests run without
it. `tests/golden_v1.json` holds the output of the pre-2.0 node across the four
schemas that predate it, and the suite asserts that the rewrite still produces
it byte for byte. `tests/test_flags.py` covers the `visible`/`overridable`
schema flags and `tests/test_pipe.py` covers the naming pipe, inheritance,
overrides and the breakout node — both run as part of the same
`unittest discover`.

## Credits

Naming convention and node by **Victor Perez**, Visual Effects Supervisor —
[victorperez.online](https://victorperez.online)

The schema-driven design — keeping the configuration separate from the logic,
so studios can vary nesting depth, delimiters and token order — was suggested
by **Sam Hodge**.

Released under the [MIT License](LICENSE).
