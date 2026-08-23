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

## Node

**VFX Naming Convention (Filename Prefix)** — category `VFX/naming`.

### Inputs

| Input | Purpose |
|---|---|
| `show_code`, `sequence_code` | 3-letter codes, auto-uppercased |
| `shot_number` | arrows snap to the nearest shot ending in 0; any number can be typed; padded to `shot_padding` |
| `task` | dropdown of task codes, plate types, `FINAL`, or `(custom)` |
| `task_custom` | free task code, used when `task` is `(custom)` |
| `plate_layer` | `0` = none; `2` turns `bg` into `bg02` |
| `vendor_id` | 3 letters; **leave empty for lab plates** |
| `version` | padded to `version_padding` |
| `sequence_subfolder` | on = `basename/basename`, off = `basename` |
| `parent_path` | optional sub-path, e.g. `SHW/SEQ` or `%date:yyyy-MM-dd%` |
| `first_frame` | work-range head; convention is `1001` (10 head + 10 tail handles) |
| `file_extension` | drives the `extension` and `example_filename` outputs |
| `strict` | on = abort on any violation; off = auto-correct and warn |

### Outputs

| Output | Example |
|---|---|
| `filename_prefix` | `SHW_SEQ_0010_comp_vnd_v001/SHW_SEQ_0010_comp_vnd_v001` |
| `folder_name` | `SHW_SEQ_0010_comp_vnd_v001` |
| `basename` | `SHW_SEQ_0010_comp_vnd_v001` |
| `shot_id` | `SHW_SEQ_0010` |
| `extension` | `exr` (lowercase, no leading dot) |
| `example_filename` | `SHW_SEQ_0010_comp_vnd_v001.1001.exr` |
| `first_frame` | `1001` (INT — feed frame-range inputs) |
| `report` | full breakdown plus any validation warnings |

Wire `filename_prefix` into the saver's `filename_prefix` widget (convert it to
an input first: right-click the Save node → *Convert widget to input*, or drag
from this node's output onto the widget in recent frontends).

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

## Shot number stepping

The +/- buttons move the shot number in tens, matching the convention,
but **any** number can be typed in manually — `15`, `125`, `7`. Off-grid values
are accepted even in strict mode; they only add an advisory note to the
`report` output. (The convention's own example `SHW_SEQ_0125_prev_vnd_v001` is
off-grid.)

Pressing +/- always lands on the nearest shot number ending in 0, in the
direction pressed — from 98, `+` goes to 100 and `-` goes to 90, rather than
dragging the off-grid number along to 108. On-grid values step normally
(20 -> 30).

Both behaviours need the bundled `web/vfx_naming.js`. ComfyUI's INT widget uses
one option (`step2`) for both the increment and for snapping committed values
onto that grid, so a plain `"step": 10` would round a typed 15 up to 20. Python
declares step 1 (always free to type), and the extension supplies the stepping.

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

Verified against a live ComfyUI 1.49.6: 20 stepping cases, free-form typing,
and no effect on the node's other INT widgets or on other nodes.

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

## Credits

Naming convention and node by **Victor Perez**, Visual Effects Supervisor —
[victorperez.online](https://victorperez.online)

Released under the [MIT License](LICENSE).
