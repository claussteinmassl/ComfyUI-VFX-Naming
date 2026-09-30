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
//   * Row states. The canvas renderer draws a switch (a pill) at the left of
//     each field row, dims inherited rows, outlines overridden ones and puts a
//     reset icon (↺) after their label; the Vue renderer shows a glyph in the
//     label and a ↺ span instead. Locked rows use the stock `disabled` state.
//   * Stash. Switching an override off keeps its values in
//     `node.properties.vfxStash` (saved with the workflow); switching it on
//     again restores them. ↺ discards an override together with its stash.
//
// State lives by field name in `overrides` and on the node, never on widget
// objects alone: the DynamicCombo recreates token widgets on every rebuild.

export const PIPE_INPUT = "naming_pipe";
export const ACCENT = "#f0a030";
const GLYPH = { inherited: "○ ", overridden: "● ", locked: "⛓ " };
const RESET = "↺";
const MAX_HOPS = 32;
// How many sync passes a pending restore waits for sub-widgets that a token's
// rebuild has not created (yet). A preset without them never creates them.
const RESTORE_PASSES = 4;

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

// The remembered values of switched-off overrides, by field and widget name:
// `{ task: { "schema.task": "bg", "schema.task.task_layer": 3 } }`. A node
// property, so the workflow saves it; Python never reads it.
const stashOf = (node) => node.properties?.vfxStash ?? {};

export const hasStash = (node, field) => !!stashOf(node)[field];

function dropStash(node, field) {
    const stash = node.properties?.vfxStash;
    if (stash && field in stash) delete stash[field];
    if (stash && !Object.keys(stash).length) delete node.properties.vfxStash;
    if (node.__vfxPending) delete node.__vfxPending[field];
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
        for (const field of Object.keys(stashOf(node))) {
            if (!fields.includes(field)) dropStash(node, field);
        }
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
            // Changed since we last mirrored it: the user edited it. The fresh
            // edit wins over any remembered value.
            overrides.add(field);
            writeOverrides(node, overrides);
            dropStash(node, field);
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
// with an old glyph or padding already in its label.
const GLYPH_PREFIX = /^(?:[○●⛓] |\u00a0)+/;

// Canvas rows make room for the switch with non-breaking spaces rather than a
// glyph: the label starts at x = 35 on rows with stepper arrows and at x = 30
// on the others, a non-breaking space is 3.4 px wide in the widget font
// (12px Inter, frontend 1.52.7), and the switch ends at x = 62 / 48.
const PAD = { stepped: "\u00a0".repeat(9), plain: "\u00a0".repeat(7) };

const vueMode = () => !!globalThis.LiteGraph?.vueNodesMode;

/**
 * Whether this row gets the canvas switch (and so a padded, glyph-free label):
 * a widget our draw wrapper wraps (or will wrap), in the canvas renderer.
 */
const drawsSwitch = (widget) => !vueMode() && (!!widget.__vfxDraw
    || (typeof widget.drawWidget === "function" && !delegatesDraw(widget)));

function composeLabel(widget, state, glyph, base) {
    if (!state || !glyph) return base;
    if (drawsSwitch(widget)) return (stepped(widget) ? PAD.stepped : PAD.plain) + base;
    return GLYPH[state] + base;
}

function decorate(widget, state, glyph) {
    if (!("__vfxLabel" in widget)) widget.__vfxLabel = widget.label?.replace(GLYPH_PREFIX, "");
    const base = widget.__vfxLabel || widget.name.split(".").pop();
    const label = composeLabel(widget, state, glyph, base);
    if (widget.label !== label) widget.label = label;

    const locked = state === "locked";
    if (locked && !widget.disabled) { widget.disabled = true; widget.__vfxDisabled = true; }
    if (!locked && widget.__vfxDisabled) { widget.disabled = false; delete widget.__vfxDisabled; }

    widget.__vfxState = state;
    widget.__vfxGlyph = !!glyph;
    widget.__vfxSwitch = !!(state && glyph) && drawsSwitch(widget);
    if (widget.element?.style) {
        // DOM widgets (multiline text) sit on top of the canvas: style the element.
        widget.element.style.opacity = state === "inherited" ? "0.5" : "";
        widget.element.style.outline = state === "overridden" ? `1.5px solid ${ACCENT}` : "";
        // A textarea shows its name as placeholder rather than a label; it
        // never gets the switch, so the placeholder keeps the glyph.
        if ("placeholder" in widget.element) {
            widget.__vfxPlaceholder ??= widget.element.placeholder;
            widget.element.placeholder = state && glyph ? GLYPH[state] + base : base;
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
    widget.__vfxSwitch = false;
    widget.__vfxResetZone = null;
}

/**
 * Canvas renderer only: dim inherited rows, outline overridden ones, and draw
 * the switch and the reset icon (see drawControls()).
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
        this.__vfxResetZone = null;
        if (this.__vfxSwitch && !lowQuality) drawControls(this, ctx, width, y, height);
    };

    // A click on the switch toggles the row, a click on ↺ resets it; anywhere
    // else the widget behaves as usual (arrows, dropdown, drag, prompt).
    // processWidgetClick() asks onPointerDown() first.
    const original = widget.onPointerDown;
    widget.onPointerDown = function (pointer, node, canvas) {
        const x = canvas.graph_mouse[0] - node.pos[0];
        const field = fieldOf(this);
        if (this.__vfxSwitch && togglable(this) && within(x, switchZone(this))) {
            pointer.onClick = () => toggle(node, field);
            return true;
        }
        if (this.__vfxState === "overridden" && within(x, this.__vfxResetZone)) {
            pointer.onClick = () => resetOverride(node, field);
            return true;
        }
        return original ? original.call(this, pointer, node, canvas) : false;
    };
}

const delegatesDraw = (widget) =>
    !!widget.element || !!widget.isDOMWidget || "draw" in widget;

const stepped = (widget) => widget.type === "number" || widget.type === "combo";

const within = (x, zone) => !!zone && x >= zone[0] && x <= zone[1];

// Where the switch sits on a canvas row, in node-local x (frontend 1.52.7).
// The stock stepper widgets (number, combo) decrement on any click at x < 40
// and draw their left arrow at x = 21..31, so on those rows the switch starts
// after that zone; text and toggle rows have no arrows and start it at the
// widget's rounded edge. The click zones add a pixel or two of slack.
const switchSpan = (widget) => (stepped(widget) ? [42, 62] : [28, 48]);
const switchZone = (widget) => (stepped(widget) ? [41, 64] : [27, 50]);

// Where the stock widgets start their label: margin * 2 plus the left padding
// of drawTruncatingText() (5 on stepper rows, 0 on text rows; toggle rows draw
// the label at margin * 2).
const labelStart = (widget) => (stepped(widget) ? 35 : 30);

/**
 * The switch (or, on locked rows, a chain mark in its place) and, on
 * overridden rows, ↺ after the label. The reset icon's hit zone is stored on
 * the widget for onPointerDown(); it is skipped, and has no zone, when it
 * would run into the value text.
 */
function drawControls(widget, ctx, width, y, height) {
    const [from, to] = switchSpan(widget);
    const middle = y + height * 0.5;
    const state = widget.__vfxState;
    ctx.save();
    if (state === "locked") {
        ctx.fillStyle = widget.secondary_text_color ?? "#999";
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(GLYPH.locked.trim(), (from + to) / 2, middle);
        ctx.restore();
        return;
    }
    const on = state === "overridden";
    const pillHeight = 11;
    ctx.fillStyle = on ? ACCENT : "#5a5a5a";
    ctx.beginPath();
    ctx.roundRect(from, middle - pillHeight / 2, to - from, pillHeight, pillHeight / 2);
    ctx.fill();
    ctx.fillStyle = on ? "#fff" : "#b8b8b8";
    ctx.beginPath();
    ctx.arc(on ? to - pillHeight / 2 : from + pillHeight / 2, middle, pillHeight / 2 - 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    if (on) drawReset(widget, ctx, width, y, height);
}

function drawReset(widget, ctx, width, y, height) {
    // ctx still carries the font the widget drew its label with.
    const labelWidth = ctx.measureText(widget.displayName ?? "").width;
    const labelX = labelStart(widget);
    let valueLeft;
    if (widget.type === "toggle") {
        const text = widget.value ? widget.options?.on || "true" : widget.options?.off || "false";
        valueLeft = width - 40 - ctx.measureText(text).width;
    } else {
        // Mirrors drawTruncatingText(): no icon once the label gets truncated.
        const valueWidth = ctx.measureText(String(widget._displayValue ?? "")).width;
        const totalWidth = width - labelX - 30 - (stepped(widget) ? 20 : 0);
        if (labelWidth + 5 + valueWidth > totalWidth) return;
        valueLeft = labelX + totalWidth - valueWidth;
    }
    ctx.save();
    ctx.font = `12px ${ctx.font.replace(/^.*?\d+(?:\.\d+)?px\s*/, "") || "sans-serif"}`;
    const iconX = labelX + labelWidth + 4;
    const iconWidth = ctx.measureText(RESET).width;
    if (iconX + iconWidth + 4 <= valueLeft) {
        ctx.fillStyle = widget.secondary_text_color ?? "#999";
        ctx.textAlign = "left";
        ctx.fillText(RESET, iconX, y + height * 0.7);
        widget.__vfxResetZone = [iconX - 2, iconX + iconWidth + 3];
    }
    ctx.restore();
}

const togglable = (widget) =>
    widget.__vfxGlyph && (widget.__vfxState === "inherited" || widget.__vfxState === "overridden");

function finish(node) {
    syncOverrides(node);
    node.setDirtyCanvas?.(true, true);
}

/** Switch a field's override off, remembering its values for enableOverride(). */
export function disableOverride(node, field) {
    if (!field) return;
    const values = {};
    for (const widget of node.widgets ?? []) {
        if (fieldOf(widget) === field) values[widget.name] = widget.value;
    }
    node.properties ??= {};
    node.properties.vfxStash = { ...stashOf(node), [field]: values };
    if (node.__vfxPending) delete node.__vfxPending[field];
    const overrides = readOverrides(node);
    overrides.delete(field);
    writeOverrides(node, overrides);
    forget(node, field);   // the field re-mirrors on this pass
    finish(node);
}

/** Switch a field's override on, restoring what disableOverride() remembered. */
export function enableOverride(node, field) {
    if (!field) return;
    const overrides = readOverrides(node);
    overrides.add(field);
    writeOverrides(node, overrides);
    const values = stashOf(node)[field];
    dropStash(node, field);
    if (values) {
        // The token's own row first: on a DynamicCombo, setting it rebuilds
        // the sub-widgets the rest of the values belong to.
        const own = node.widgets?.find((w) => fieldOf(w) === field && isFieldRow(w, field));
        const rest = { ...values };
        if (own && own.name in rest) {
            if (own.value !== rest[own.name]) own.value = rest[own.name];
            delete rest[own.name];
        }
        if (Object.keys(rest).length) {
            node.__vfxPending ??= {};
            node.__vfxPending[field] = { values: rest, passes: RESTORE_PASSES };
        }
    }
    finish(node);
}

/** Discard a field's override for good: inherited, nothing remembered. */
export function resetOverride(node, field) {
    if (!field) return;
    const overrides = readOverrides(node);
    overrides.delete(field);
    writeOverrides(node, overrides);
    dropStash(node, field);
    forget(node, field);
    finish(node);
}

/**
 * Apply restored sub-widget values once their widgets exist. A value whose
 * widget has not shown up after a few passes is dropped (the restored token
 * may simply not reveal it).
 */
function applyPending(node, overrides) {
    const pending = node.__vfxPending;
    for (const [field, entry] of Object.entries(pending)) {
        if (!overrides.has(field)) { delete pending[field]; continue; }
        // In row order, so a nested token is set before the widgets it reveals.
        for (const [name, value] of Object.entries(entry.values)) {
            const widget = findWidget(node, name);
            if (!widget) continue;
            if (widget.value !== value) widget.value = value;
            delete entry.values[name];
        }
        entry.passes -= 1;
        if (!Object.keys(entry.values).length || entry.passes <= 0) delete pending[field];
    }
    if (!Object.keys(pending).length) delete node.__vfxPending;
}

/** Flip one field between inherited and overridden, keeping switched-off values. */
export function toggle(node, field) {
    if (!field) return;
    if (readOverrides(node).has(field)) disableOverride(node, field);
    else enableOverride(node, field);
}

export function inheritAll(node) {
    writeOverrides(node, new Set());
    if (node.properties) delete node.properties.vfxStash;
    delete node.__vfxPending;
    forget(node);
    finish(node);
}

// Vue nodes renderer. There is no API to decorate a widget row, so this reads
// the rendered DOM: a row is `.lg-node-widget`, its label cell carries
// data-testid="widget-layout-field-label" and shows `widget.label`, the cell
// after it holds the value. If the markup changes, the glyph in the label,
// auto-override on edit and the context menu still work.
const ROW = ".lg-node-widget";
const LABEL = '[data-testid="widget-layout-field-label"]';
const RESET_SPAN = "[data-vfx-reset]";

/** The label a Vue label cell shows, without our ↺ span. */
const labelText = (cell) => cell?.textContent?.replace(RESET, "").trim();

/**
 * The widget a Vue label cell shows. With `fieldRowsOnly` (clicks), only a
 * field's own row can match, never a revealed sub-widget that happens to share
 * its label. Styling also accepts sub-widgets, preferring field rows.
 */
function widgetForLabel(node, cell, fieldRowsOnly = true) {
    const text = labelText(cell);
    const shows = (w) => (w.label ?? w.name) === text;
    const row = node.widgets?.find((w) => shows(w) && isFieldRow(w, fieldOf(w)));
    if (row || fieldRowsOnly) return row ?? null;
    return node.widgets?.find(shows) ?? null;
}

/** The naming node a Vue element belongs to, or null. */
function nodeOfElement(element) {
    const id = element?.closest?.("[data-node-id]")?.dataset?.nodeId;
    if (id == null) return null;
    const graph = app.canvas?.graph ?? app.graph;
    const node = graph?.getNodeById?.(id) ?? graph?.getNodeById?.(Number(id));
    return classOf(node) === NODE_CLASS ? node : null;
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
        decorateResetSpan(cell, state === "overridden" && !!widget && togglable(widget));
    }
}

function decorateResetSpan(cell, wanted) {
    const existing = cell.querySelector(RESET_SPAN);
    if (!wanted) { existing?.remove(); return; }
    if (existing) return;
    const span = document.createElement("span");
    span.dataset.vfxReset = "";
    span.textContent = RESET;
    span.title = "Reset override (discard the value)";
    span.style.marginLeft = "6px";
    span.style.cursor = "pointer";
    span.style.color = "var(--p-text-muted-color, #999)";
    cell.appendChild(span);
}

document.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const cell = event.target?.closest?.(`${ROW} ${LABEL}`);
    if (!cell) return;
    const node = nodeOfElement(cell);
    if (!node) return;
    const widget = widgetForLabel(node, cell);
    if (!widget || !togglable(widget)) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.target.closest(RESET_SPAN)) {
        if (widget.__vfxState === "overridden") resetOverride(node, fieldOf(widget));
        return;
    }
    toggle(node, fieldOf(widget));
}, true);

// The row a Vue right-click landed on. The node menu is built right after the
// contextmenu event, from getNodeMenuOptions(); rowMenuItems() reads this.
const ROW_CLICK_MAX_AGE_MS = 1000;
let vueRowClick = null;

document.addEventListener("contextmenu", (event) => {
    const row = event.target?.closest?.(ROW);
    const node = row && nodeOfElement(row);
    const cell = row?.querySelector(LABEL);
    vueRowClick = node && cell
        ? { node, widget: widgetForLabel(node, cell, false), time: performance.now() }
        : null;
}, true);

/** The widget under the pointer that opened the node's context menu, if any. */
function widgetUnderPointer(node) {
    if (vueMode()) {
        const click = vueRowClick;
        const fresh = click && performance.now() - click.time < ROW_CLICK_MAX_AGE_MS;
        return fresh && click.node === node ? click.widget : null;
    }
    const [x, y] = app.canvas?.graph_mouse ?? [];
    if (x == null || typeof node.getWidgetOnPos !== "function") return null;
    return node.getWidgetOnPos(x, y, true) ?? null;
}

/** Actions for the row under the pointer: override on/off and ↺ reset. */
export function rowMenuItems(node) {
    if (classOf(node) !== NODE_CLASS || !upstreamOf(node).linked) return [];
    const field = fieldOf(widgetUnderPointer(node));
    if (!field) return [];
    const overrides = readOverrides(node);
    const state = stateOf(node, field, overrides);
    if (state === "locked") return [];
    const items = [state === "overridden"
        ? { content: `● Override ${field}: off (keep value)`, callback: () => disableOverride(node, field) }
        : { content: `○ Override ${field}: on`, callback: () => enableOverride(node, field) }];
    if (state === "overridden" || hasStash(node, field)) {
        items.push({ content: `${RESET} Reset ${field}`, callback: () => resetOverride(node, field) });
    }
    return items;
}

/**
 * Put the row actions at the top of the node's context menu. Items from the
 * extension hook (getNodeMenuItems, see menuItems()) are appended at the end
 * of the menu; items a node's getExtraMenuOptions() adds to `options` come
 * first. The Vue renderer's menu files both under "Extensions", in this order.
 */
export function installRowMenu(node) {
    if (node.__vfxRowMenu) return;
    node.__vfxRowMenu = true;
    const original = node.getExtraMenuOptions;
    node.getExtraMenuOptions = function (canvas, options) {
        const extra = original?.call(this, canvas, options);
        const items = rowMenuItems(this);
        if (items.length) options.unshift(...items, null);
        return extra;
    };
}

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
    if (node.__vfxPending) applyPending(node, readOverrides(node));
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
