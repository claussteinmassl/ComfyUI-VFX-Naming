import { app } from "../../scripts/app.js";
import {
    NODE_CLASS, OVERRIDES_WIDGET, SCHEMA_WIDGET, OPTION_NAMES,
    applyVisibility, classOf, fieldOf, findWidget, relayout, schemaFlags,
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

// The last mirrored value per widget OBJECT, not per name: the DynamicCombo
// recreates sub-widgets (a task's layer) whenever mirroring sets their token,
// and a recreated widget starts at its default. Keyed by name, that default
// would read as a user edit; keyed by object, the new widget has no memory
// and is simply mirrored.
const mirrored = new WeakMap();

/** Forget what was mirrored for a field (or, without one, the whole node). */
export function forget(node, field = null) {
    for (const widget of node.widgets ?? []) {
        if (field === null || fieldOf(widget) === field) mirrored.delete(widget);
    }
}

function mirror(node, source, overrides) {
    const own = findWidget(node, SCHEMA_WIDGET);
    const upstreamSchema = findWidget(source, SCHEMA_WIDGET)?.value;
    if (own && upstreamSchema != null && own.value !== upstreamSchema) {
        own.value = upstreamSchema;   // the DynamicCombo rebuilds the token widgets
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

        if (state === "inherited" && mirrored.has(widget)
                && widget.value !== mirrored.get(widget)) {
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
        mirrored.set(widget, widget.value);
    }
    return changed;
}

// A label as it was before decoration. The Vue renderer keeps widget state
// (label included) per node id, so a new node that reuses an id can start out
// with an old glyph already in its label.
const GLYPH_PREFIX = /^(?:[○●⛓] )+/;

function decorate(widget, state, glyph) {
    if (!("__vfxLabel" in widget)) widget.__vfxLabel = widget.label?.replace(GLYPH_PREFIX, "");
    const base = widget.__vfxLabel || widget.name.split(".").pop();
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
 *
 * Only widgets whose drawWidget() draws by itself are wrapped. DOM widgets
 * and legacy custom widgets (LegacyWidget) implement drawWidget() by calling
 * draw(), so a draw() that calls drawWidget() would recurse forever. Those
 * are recognised by having a draw() of their own (DOM widgets define it on
 * their class), an element, or isDOMWidget. The wrapper re-checks on every
 * call and guards against re-entry, so a widget that turns out to delegate
 * after all falls back to its class's draw() instead of recursing.
 */
function wrapCanvasDraw(widget) {
    if (widget.__vfxDraw || typeof widget.drawWidget !== "function") return;
    if (delegatesDraw(widget)) return;
    widget.__vfxDraw = true;
    widget.draw = function (ctx, node, width, y, height, lowQuality) {
        if (this.__vfxDrawing || this.element || this.isDOMWidget) {
            Object.getPrototypeOf(this)?.draw?.call(this, ctx, node, width, y, height, lowQuality);
            return;
        }
        const state = this.__vfxState;
        ctx.save();
        this.__vfxDrawing = true;
        try {
            if (state === "inherited") ctx.globalAlpha *= 0.5;
            this.drawWidget(ctx, { width, showText: !lowQuality });
        } finally {
            this.__vfxDrawing = false;
            ctx.restore();
        }
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

    // A click on the glyph toggles the row; anywhere else the widget behaves
    // as usual. processWidgetClick() asks onPointerDown() first.
    const original = widget.onPointerDown;
    widget.onPointerDown = function (pointer, node, canvas) {
        if (togglable(this)) {
            const x = canvas.graph_mouse[0] - node.pos[0];
            const [from, to] = glyphZone(this);
            if (x >= from && x <= to) {
                pointer.onClick = () => toggle(node, fieldOf(this));
                return true;
            }
        }
        return original ? original.call(this, pointer, node, canvas) : false;
    };
}

const delegatesDraw = (widget) =>
    !!widget.element || !!widget.isDOMWidget || "draw" in widget;

// Where the glyph sits on a canvas row, in node-local x (measured on a 2x zoom
// screenshot against frontend 1.52.7). The glyph is drawn at x = 31..35 on
// text and toggle rows and at x = 36..40 on rows with stepper arrows (number,
// combo); the zones add a few px of slack and end before the label text. The
// socket gutter (x < 15) belongs to the input slot. The stepper's left arrow
// is drawn at x = 21..31 and keeps x < 33 as its hit area.
function glyphZone(widget) {
    return widget.type === "number" || widget.type === "combo" ? [33, 45] : [26, 39];
}

const togglable = (widget) =>
    widget.__vfxGlyph && (widget.__vfxState === "inherited" || widget.__vfxState === "overridden");

/** Flip one field between inherited and overridden. */
export function toggle(node, field) {
    if (!field) return;
    const overrides = readOverrides(node);
    if (overrides.has(field)) overrides.delete(field);
    else overrides.add(field);
    writeOverrides(node, overrides);
    forget(node, field);   // an inherited field re-mirrors on this pass
    syncOverrides(node);
    node.setDirtyCanvas?.(true, true);
}

export function inheritAll(node) {
    writeOverrides(node, new Set());
    forget(node);
    syncOverrides(node);
    node.setDirtyCanvas?.(true, true);
}

// Vue nodes renderer. There is no API to decorate a widget row, so this reads
// the rendered DOM: a row is `.lg-node-widget`, its label cell carries
// data-testid="widget-layout-field-label" and shows `widget.label`, the cell
// after it holds the value. If the markup changes, the glyph in the label,
// auto-override on edit and the context menu still work.
const ROW = ".lg-node-widget";
const LABEL = '[data-testid="widget-layout-field-label"]';

/**
 * The widget a Vue label cell shows. With `fieldRowsOnly` (clicks), only a
 * field's own row can match, never a revealed sub-widget that happens to share
 * its label. Styling also accepts sub-widgets, preferring field rows.
 */
function widgetForLabel(node, cell, fieldRowsOnly = true) {
    const text = cell?.textContent?.trim();
    const shows = (w) => (w.label ?? w.name) === text;
    const row = node.widgets?.find((w) => shows(w) && isFieldRow(w, fieldOf(w)));
    if (row || fieldRowsOnly) return row ?? null;
    return node.widgets?.find(shows) ?? null;
}

/** Style the node's Vue rows after their state. The Vue renderer remounts rows, so this runs every tick. */
export function decorateVue(node) {
    const element = document.querySelector(`[data-node-id="${node.id}"]`);
    if (!element) return;
    for (const row of element.querySelectorAll(ROW)) {
        const cell = row.querySelector(LABEL);
        if (!cell) continue;
        const widget = widgetForLabel(node, cell, false);
        const state = widget?.__vfxState;
        const value = cell.nextElementSibling;
        if (value?.style) value.style.opacity = state === "inherited" ? "0.45" : "";
        cell.style.color = state === "overridden" ? ACCENT : "";
        cell.style.cursor = widget && togglable(widget) ? "pointer" : "";
    }
}

document.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const cell = event.target?.closest?.(`${ROW} ${LABEL}`);
    if (!cell) return;
    const id = cell.closest("[data-node-id]")?.dataset?.nodeId;
    const node = app.graph?.getNodeById?.(id) ?? app.graph?.getNodeById?.(Number(id));
    if (classOf(node) !== NODE_CLASS) return;
    const widget = widgetForLabel(node, cell);
    if (!widget || !togglable(widget)) return;
    event.preventDefault();
    event.stopPropagation();
    toggle(node, fieldOf(widget));
}, true);

/** Entries for the node's right-click menu (canvas and Vue renderer alike). */
export function menuItems(node) {
    if (classOf(node) !== NODE_CLASS || !upstreamOf(node).linked) return [];
    const overrides = readOverrides(node);
    const options = fieldsOf(node)
        .filter((field) => stateOf(node, field, overrides) !== "locked")
        .map((field) => ({
            content: overrides.has(field) ? `● Inherit ${field}` : `○ Override ${field}`,
            callback: () => toggle(node, field),
        }));
    if (overrides.size) options.push(null, { content: "Inherit all", callback: () => inheritAll(node) });
    return [null, { content: "VFX overrides", has_submenu: true, submenu: { options } }];
}

// --- Collapse switch ---------------------------------------------------------
//
// "Hide inherited": while on, inherited and locked rows (the Schema row too)
// are hidden with the same mechanism the schema flags use, so only the
// overridden rows, the preview and the switch remain. The switch exists only
// while a pipe is linked; its state is saved in node.properties.

const COLLAPSE_WIDGET = "vfx_collapse";

const hidesInherited = (node) => !!node.properties?.vfxHideInherited;

/** Rows the switch hides: inherited and locked fields, plus the Schema row. */
function inheritedCount(node) {
    const overrides = readOverrides(node);
    const flags = schemaFlags(node);
    // Options the schema hides are already gone; they are not "inherited rows".
    const shown = (field) => flags.options?.[field]?.visible !== false;
    return fieldsOf(node)
        .filter((field) => shown(field) && stateOf(node, field, overrides) !== "overridden")
        .length + 1;
}

const collapseText = (node) => {
    const count = inheritedCount(node);
    return hidesInherited(node)
        ? `▸ show ${count} inherited fields`
        : `▾ hide ${count} inherited fields`;
};

function toggleCollapse(node) {
    node.properties ??= {};
    node.properties.vfxHideInherited = !hidesInherited(node);
    applyVisibility(node, syncOverrides(node));   // now, not on the next tick
    node.setDirtyCanvas?.(true, true);
}

// A plain-object widget: the Vue renderer draws unknown widget types through
// its legacy canvas component (WidgetLegacy), so this one implementation
// serves both renderers. It is never serialized: not into widgets_values,
// not into the prompt.
function collapseWidget() {
    return {
        type: COLLAPSE_WIDGET,
        name: COLLAPSE_WIDGET,
        value: "",
        serialize: false,
        options: { serialize: false },
        computeSize: (width) => [width, 22],
        draw(ctx, node, width, y, height) {
            ctx.save();
            ctx.fillStyle = "#9a9a9a";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(collapseText(node), width / 2, y + height / 2);
            ctx.restore();
        },
        onPointerDown(pointer, node) {
            pointer.onClick = () => toggleCollapse(node);
            return true;
        },
    };
}

function ensureCollapse(node, linked) {
    const existing = findWidget(node, COLLAPSE_WIDGET);
    if (linked && !existing) {
        node.addCustomWidget(collapseWidget());
        relayout(node);   // the Vue renderer only sees a replaced widget list
    } else if (!linked && existing) {
        node.widgets.splice(node.widgets.indexOf(existing), 1);
        relayout(node);
    } else if (existing) {
        // WidgetLegacy redraws its own canvas only when asked to.
        const text = collapseText(node);
        if (existing.__vfxText !== text) {
            existing.__vfxText = text;
            existing.triggerDraw?.();
        }
    }
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
            forget(node);
            node.__vfxLinked = false;
            decorateVue(node);   // __vfxState is null now: rows lose their styling
            node.setDirtyCanvas?.(true, true);
        }
        // Outside the guard, so the switch never outlives the link, whatever
        // state the node was created or loaded in.
        ensureCollapse(node, false);
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
    decorateVue(node);
    ensureCollapse(node, true);
    return (widget, field) => hidesInherited(node)
        && (widget.name === SCHEMA_WIDGET || (field && widget.__vfxState !== "overridden"));
}
