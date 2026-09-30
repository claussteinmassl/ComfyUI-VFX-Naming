// Shared helpers for the VFX naming frontend: which widget belongs to which
// field, the schema flags the backend serves, and hiding widgets so that both
// renderers agree.
//
// Hiding needs two flags because the renderers read different ones: the
// LiteGraph canvas checks `widget.hidden`, the Vue nodes renderer checks
// `widget.options.hidden`. The Vue renderer only re-reads a node's widget list
// when the array itself is replaced, which `relayout()` does.

export const NODE_CLASS = "VFXNamingConvention";
export const SCHEMA_WIDGET = "schema";
export const PREVIEW_WIDGET = "preview";
export const OVERRIDES_WIDGET = "overrides";
export const OPTION_NAMES = [
    "folders", "strict", "parent_path", "template_override", "custom_tokens",
];

const SCHEMAS_ROUTE = "/vfx_naming/schemas";

export const classOf = (node) => node?.comfyClass ?? node?.constructor?.comfyClass;
export const findWidget = (node, name) => node?.widgets?.find((w) => w.name === name);

/**
 * The field a widget belongs to: an option name, a token name, or null for
 * everything else (the schema combo, preview, overrides, our own widgets).
 * Revealed sub-widgets such as `schema.task.task_layer` belong to their token.
 */
export function fieldOf(widget) {
    const name = widget?.name ?? "";
    if (OPTION_NAMES.includes(name)) return name;
    const parts = name.split(".");
    return parts[0] === SCHEMA_WIDGET && parts.length >= 2 ? parts[1] : null;
}

let schemaFlagCache = {};

/** Fetch the per-schema flags once. Until it lands, every field counts as visible. */
export async function loadSchemaFlags() {
    try {
        const response = await fetch(SCHEMAS_ROUTE);
        if (response.ok) schemaFlagCache = await response.json();
    } catch {
        // Without flags every field stays visible and overridable.
    }
}

/** The flags of the schema a node currently shows. */
export function schemaFlags(node) {
    const key = findWidget(node, SCHEMA_WIDGET)?.value;
    return schemaFlagCache[key] ?? { tokens: {}, options: {} };
}

/** Hide or show one widget in both renderers. Returns whether anything changed. */
export function setHidden(widget, hidden) {
    if (!!widget.hidden === hidden) return false;
    widget.hidden = hidden;
    widget.options ??= {};
    widget.options.hidden = hidden;
    // A DOM widget (multiline text) is positioned outside the canvas.
    if (widget.element?.style) widget.element.style.display = hidden ? "none" : "";
    return true;
}

/** Make both renderers pick up visibility changes and fit the node to them. */
export function relayout(node) {
    node.widgets = [...node.widgets];
    node.setSize([node.size[0], node.computeSize()[1]]);
    node.setDirtyCanvas?.(true, true);
    // The Vue nodes renderer (checked against ComfyUI frontend 1.52.7) draws its
    // widget rows once at mount and does not react to later widget.hidden /
    // widget.options.hidden mutations, even when node.widgets is reassigned or
    // spliced in place. A synchronous collapse/expand toggle forces the node's
    // Vue component to remount and re-read the current widget list; the
    // intermediate collapsed frame is never painted because both calls happen
    // before the next animation frame. No-op in the canvas renderer, which
    // already redraws from live widget.hidden on every frame.
    if (typeof node.collapse === "function") {
        node.collapse();
        node.collapse();
    }
}

/**
 * Hide what the selected schema hides, plus the `overrides` bookkeeping widget.
 * `extraHidden(widget, field)` lets the override UI collapse inherited rows.
 */
export function applyVisibility(node, extraHidden = () => false) {
    const flags = schemaFlags(node);
    let changed = false;
    for (const widget of node.widgets ?? []) {
        const field = fieldOf(widget);
        const hidden = widget.name === OVERRIDES_WIDGET
            || (OPTION_NAMES.includes(widget.name)
                && flags.options?.[widget.name]?.visible === false)
            || !!extraHidden(widget, field);
        if (setHidden(widget, hidden)) changed = true;
    }
    if (changed) relayout(node);
}
