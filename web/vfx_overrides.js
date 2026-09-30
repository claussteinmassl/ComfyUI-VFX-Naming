import {
    NODE_CLASS, OVERRIDES_WIDGET, SCHEMA_WIDGET, OPTION_NAMES,
    classOf, fieldOf, findWidget, schemaFlags,
} from "./vfx_widgets.js";

// Per-field overrides for a naming node that receives a naming pipe.
//
// Python is the only place the convention is interpreted, and at execution it
// merges the real pipe with the fields listed in the hidden `overrides`
// widget. The frontend's job is to make that visible and editable:
//
//   * Mirroring. Every field that is not overridden shows the upstream node's
//     value, so the row, the live preview and a reload all agree with what
//     execution will do. The upstream node is found by following the pipe
//     link; its own widgets are already mirrored when it is a child itself,
//     so chains resolve one hop per tick.
//   * Edit detection. Rather than hooking every widget type's callback in two
//     renderers, the last mirrored value of each widget is remembered. A value
//     that differs from it on the next tick was changed by the user, and
//     turns the field into an override.
//   * Row states. The label carries a glyph (reactive in both renderers); the
//     canvas renderer additionally dims inherited rows and outlines overridden
//     ones; locked rows use the stock `disabled` state.
//
// State lives by field name in `overrides` and on the node, never on widget
// objects alone: the DynamicCombo recreates token widgets on every rebuild.

export const PIPE_INPUT = "naming_pipe";
export const ACCENT = "#f0a030";
const GLYPH = { inherited: "○ ", overridden: "● ", locked: "⛓ " };
const MAX_HOPS = 32;

/** The naming node that feeds this one, following legacy Reroute nodes. */
export function upstreamOf(node) {
    const slot = node.inputs?.findIndex((input) => input.name === PIPE_INPUT) ?? -1;
    if (slot < 0 || node.inputs[slot].link == null) return { linked: false, source: null };
    let source = node.getInputNode(slot);
    for (let hops = 0; source && classOf(source) !== NODE_CLASS && hops < MAX_HOPS; hops++) {
        if (source.type !== "Reroute") break;
        source = source.getInputNode(0);
    }
    const found = classOf(source) === NODE_CLASS && source !== node;
    return { linked: true, source: found ? source : null };
}

export function readOverrides(node) {
    try {
        const parsed = JSON.parse(findWidget(node, OVERRIDES_WIDGET)?.value || "[]");
        return new Set(Array.isArray(parsed) ? parsed : []);
    } catch {
        return new Set();
    }
}

export function writeOverrides(node, overrides) {
    const widget = findWidget(node, OVERRIDES_WIDGET);
    if (widget) widget.value = JSON.stringify([...overrides].sort());
}

function overridable(node, field) {
    const flags = schemaFlags(node);
    if (OPTION_NAMES.includes(field)) {
        const option = flags.options?.[field];
        return option?.visible !== false && option?.overridable !== false;
    }
    return flags.tokens?.[field]?.overridable !== false;
}

export function stateOf(node, field, overrides) {
    if (!overridable(node, field)) return "locked";
    return overrides.has(field) ? "overridden" : "inherited";
}

/** A token's own row, as opposed to a sub-widget it reveals. */
export const isFieldRow = (widget, field) =>
    widget.name === field || widget.name === `${SCHEMA_WIDGET}.${field}`;

/** Fields shown on this node, in row order. */
export function fieldsOf(node) {
    const fields = [];
    for (const widget of node.widgets ?? []) {
        const field = fieldOf(widget);
        if (field && isFieldRow(widget, field) && !fields.includes(field)) fields.push(field);
    }
    return fields;
}

const memoryOf = (node) => (node.__vfxMirrored ??= new Map());

/** Forget what was mirrored for a field, so the next tick mirrors it afresh. */
export function forget(node, field) {
    const memory = memoryOf(node);
    for (const name of [...memory.keys()]) {
        if (fieldOf({ name }) === field) memory.delete(name);
    }
}

function mirror(node, source, overrides) {
    const own = findWidget(node, SCHEMA_WIDGET);
    const upstreamSchema = findWidget(source, SCHEMA_WIDGET)?.value;
    if (own && upstreamSchema != null && own.value !== upstreamSchema) {
        own.value = upstreamSchema;   // the DynamicCombo rebuilds the token widgets
        memoryOf(node).clear();
        // The rebuild is synchronous. Drop overrides the new schema does not
        // allow (unknown or locked fields): Python refuses them, which is an
        // error in strict mode.
        const fields = fieldsOf(node);
        const unknown = [...overrides].filter(
            (field) => !fields.includes(field) || !overridable(node, field));
        for (const field of unknown) overrides.delete(field);
        if (unknown.length) writeOverrides(node, overrides);
        return true;
    }

    const memory = memoryOf(node);
    let changed = false;
    // Iterate over a copy: setting a nested DynamicCombo (a task with layer
    // presets) splices its sub-widgets in and out of node.widgets. Widgets it
    // removed are skipped, the ones it added are mirrored on the next tick.
    for (const widget of [...(node.widgets ?? [])]) {
        if (!node.widgets.includes(widget)) continue;
        const field = fieldOf(widget);
        if (!field) continue;
        const state = stateOf(node, field, overrides);
        if (state === "overridden") continue;
        const upstream = findWidget(source, widget.name);
        if (!upstream) continue;

        if (state === "inherited" && memory.has(widget.name)
                && widget.value !== memory.get(widget.name)) {
            // Changed since we last mirrored it: the user edited it.
            overrides.add(field);
            writeOverrides(node, overrides);
            forget(node, field);
            changed = true;
            continue;
        }
        if (widget.value !== upstream.value) {
            widget.value = upstream.value;
            changed = true;
        }
        memory.set(widget.name, widget.value);
    }
    return changed;
}

function decorate(widget, state, glyph) {
    if (!("__vfxLabel" in widget)) widget.__vfxLabel = widget.label;
    const base = widget.__vfxLabel ?? widget.name.split(".").pop();
    const label = state && glyph ? GLYPH[state] + base : base;
    if (widget.label !== label) widget.label = label;

    const locked = state === "locked";
    if (locked && !widget.disabled) { widget.disabled = true; widget.__vfxDisabled = true; }
    if (!locked && widget.__vfxDisabled) { widget.disabled = false; delete widget.__vfxDisabled; }

    widget.__vfxState = state;
    widget.__vfxGlyph = !!glyph;
    if (widget.element?.style) {
        // DOM widgets (multiline text) sit on top of the canvas: style the element.
        widget.element.style.opacity = state === "inherited" ? "0.5" : "";
        widget.element.style.outline = state === "overridden" ? `1.5px solid ${ACCENT}` : "";
        // A textarea shows its name as placeholder rather than a label.
        if ("placeholder" in widget.element) {
            widget.__vfxPlaceholder ??= widget.element.placeholder;
            widget.element.placeholder = label;
        }
    }
    wrapCanvasDraw(widget);
}

function undecorate(widget) {
    if ("__vfxLabel" in widget) { widget.label = widget.__vfxLabel; delete widget.__vfxLabel; }
    if (widget.__vfxDisabled) { widget.disabled = false; delete widget.__vfxDisabled; }
    if (widget.element?.style) {
        widget.element.style.opacity = "";
        widget.element.style.outline = "";
        if (widget.__vfxPlaceholder != null) {
            widget.element.placeholder = widget.__vfxPlaceholder;
            delete widget.__vfxPlaceholder;
        }
    }
    widget.__vfxState = null;
}

/**
 * Canvas renderer only: dim inherited rows, outline overridden ones.
 * DOM widgets are left alone: their drawWidget() calls draw() itself, so a
 * wrapper would recurse. The same goes for widgets that bring their own draw.
 */
function wrapCanvasDraw(widget) {
    if (widget.__vfxDraw || typeof widget.drawWidget !== "function") return;
    if (widget.element || widget.isDOMWidget || typeof widget.draw === "function") return;
    widget.__vfxDraw = true;
    widget.draw = function (ctx, node, width, y, height, lowQuality) {
        const state = this.__vfxState;
        ctx.save();
        if (state === "inherited") ctx.globalAlpha *= 0.5;
        this.drawWidget(ctx, { width, showText: !lowQuality });
        ctx.restore();
        if (state === "overridden") {
            ctx.save();
            ctx.strokeStyle = ACCENT;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(15, y, width - 30, height, height * 0.5);
            ctx.stroke();
            ctx.restore();
        }
    };
}

/**
 * One pass over a node: mirror, decorate, and report which rows the collapse
 * switch hides. Returns the `extraHidden` predicate for applyVisibility().
 *
 * `node.__vfxUnresolved` is set while a pipe is linked but no naming node can
 * be found behind it (a subgraph boundary, an unknown relay node): mirroring
 * stops, and the preview shows "(from pipe)" instead of a name it cannot know.
 */
export function syncOverrides(node) {
    const { linked, source } = upstreamOf(node);
    node.__vfxUnresolved = linked && !source;
    if (!linked) {
        if (node.__vfxLinked) {
            for (const widget of node.widgets ?? []) undecorate(widget);
            node.__vfxMirrored?.clear();
            node.__vfxLinked = false;
            node.setDirtyCanvas?.(true, true);
        }
        return () => false;
    }
    node.__vfxLinked = true;

    const overrides = readOverrides(node);
    if (source && mirror(node, source, overrides)) node.setDirtyCanvas?.(true, true);

    for (const widget of node.widgets ?? []) {
        if (widget.name === SCHEMA_WIDGET) { decorate(widget, "locked", true); continue; }
        const field = fieldOf(widget);
        if (field) decorate(widget, stateOf(node, field, overrides), isFieldRow(widget, field));
    }
    return () => false;   // Task 9 returns the collapse predicate here
}
