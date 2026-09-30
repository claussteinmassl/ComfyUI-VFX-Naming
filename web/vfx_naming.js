import { app } from "../../scripts/app.js";
import {
    NODE_CLASS, OVERRIDES_WIDGET, PREVIEW_WIDGET, applyVisibility, classOf,
    loadSchemaFlags,
} from "./vfx_widgets.js";
import { menuItems, syncOverrides } from "./vfx_overrides.js";

// Grid stepping for the VFX Naming Convention node's numeric tokens.
//
// A schema can declare `"step": 10` on an int token - shot numbers increment by
// tens. Two behaviours ComfyUI's stock INT widget cannot give at the same time:
//
//   1. Manual entry stays free-form. The widget uses a single option (`step2`)
//      for both the increment AND for snapping every committed value onto that
//      grid, so a plain step of 10 would round a typed 15 up to 20. The snap is
//      therefore neutralised during commit.
//
//   2. The +/- buttons land on the nearest number on the grid, in the direction
//      pressed - 98 goes up to 100 and down to 90 - instead of a blind +/-10
//      that would carry an off-grid number along (98 -> 108).
//
// With Comfy.VueNodes enabled the widget renders as a DOM component whose
// +/- buttons do `model = clamp(model +/- step)` and commit by calling
// `widget.callback(value)` directly - never `setValue()` or `onClick()`. So the
// grid step is applied two ways, both no-ops when the value is already on grid:
//
//   a. On pointerdown, `options.step2` is set to the exact distance to the next
//      grid point in that direction. The option is reactive, and a pointerdown
//      precedes the click by a full task, so the component has re-rendered with
//      the new step before it computes the value. It is restored on the click.
//   b. As a safety net (and for the keyboard arrows, where there is no
//      re-render between keydown and the handler), the wrapped callback
//      redirects an armed change onto the grid.
//
// Which widget this applies to is not known ahead of time: the `schema`
// DynamicCombo creates and destroys the token widgets as the user switches
// schema, and a token can be named anything. So instead of matching a widget
// name, this looks for the `vfxGridStep` option that `_token_input()` in
// vfx_naming.py attaches to any int token whose schema declares a step, and
// patches that widget the first time it is touched.
//
// If this script fails to load, the widgets fall back to increments of 1 and
// remain fully usable.

const OPTION = "vfxGridStep";
const ARM_TIMEOUT_MS = 800;

// Nearest multiple of `increment` strictly above / below the current value.
const gridStep = (value, increment, direction) =>
    direction > 0
        ? Math.floor(value / increment) * increment + increment
        : Math.ceil(value / increment) * increment - increment;

const clampToWidget = (value, options) =>
    Math.min(options?.max ?? Infinity, Math.max(options?.min ?? -Infinity, value));

/** The armed spinner press: { widget, increment, target } or null. */
let armed = null;
let armedTimer = null;

function disarm() {
    if (armed) armed.widget.options.step2 = armed.increment;
    armed = null;
    if (armedTimer) { clearTimeout(armedTimer); armedTimer = null; }
}

/**
 * Give a widget free-form entry plus grid-aligned spinner buttons.
 * Widgets come and go with the schema, so this runs on first contact rather
 * than at node creation.
 */
function patch(widget, increment) {
    if (widget.__vfxGridPatched) return;
    widget.__vfxGridPatched = true;

    widget.options.step2 = increment;      // +/- increment
    widget.options.step = increment * 10;  // drag sensitivity

    const originalCallback = widget.callback;
    widget.callback = function (value, ...rest) {
        const target = this?.options ? this : widget;
        let committed = value;

        // Armed spinner press: force the result onto the grid.
        if (armed && armed.widget === target && typeof value === "number") {
            committed = armed.target;
            disarm();
        }

        // Free-form manual entry: suppress the grid snap during commit.
        const saved = target.options.step2;
        target.options.step2 = 1;
        try {
            if (typeof originalCallback === "function") {
                return originalCallback.call(this, committed, ...rest);
            }
            target.value = Math.round(committed);
        } finally {
            target.options.step2 = saved;
        }
    };
}

/** Resolve a DOM element inside a widget back to a grid-stepped widget. */
function resolveWidget(element) {
    const container = element.closest?.("[aria-label]");
    const name = container?.getAttribute("aria-label");
    if (!name) return null;

    const nodeElement = container.closest("[data-node-id]");
    const id = nodeElement?.dataset?.nodeId;
    if (!id) return null;

    const graph = app.graph;
    const node = graph?.getNodeById?.(id) ?? graph?.getNodeById?.(Number(id));
    if (!node) return null;
    if ((node.comfyClass ?? node.constructor?.comfyClass) !== NODE_CLASS) return null;

    const widget = node.widgets?.find((w) => w.name === name);
    if (!widget || typeof widget.value !== "number") return null;

    const increment = Number(widget.options?.[OPTION]);
    if (!Number.isFinite(increment) || increment <= 1) return null;

    // The component's own model is what it steps from; it is what the input
    // displays. Fall back to the widget value if that cannot be read.
    const shown = Number(container.querySelector("input")?.value);
    const base = Number.isFinite(shown) ? shown : widget.value;

    return { widget, increment, base };
}

function arm(element, direction) {
    const resolved = resolveWidget(element);
    if (!resolved) return;

    const { widget, increment, base } = resolved;
    patch(widget, increment);

    const target = clampToWidget(
        gridStep(base, increment, direction), widget.options,
    );

    disarm();
    armed = { widget, increment, target };
    // Let the component compute the grid value itself where it can.
    widget.options.step2 = Math.abs(target - base) || increment;
    armedTimer = setTimeout(disarm, ARM_TIMEOUT_MS);
}

document.addEventListener("pointerdown", (event) => {
    const button = event.target?.closest?.(
        '[data-testid="increment"],[data-testid="decrement"]',
    );
    if (!button) return;
    arm(button, button.dataset.testid === "increment" ? 1 : -1);
}, true);

// Runs after the component's own click handler, so the step has been used.
document.addEventListener("click", () => { if (armed) disarm(); }, false);
document.addEventListener("pointercancel", disarm, true);

// Keyboard arrows on the input: no re-render happens between keydown and the
// component's handler, so these rely on the callback safety net above.
document.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    arm(target, event.key === "ArrowUp" ? 1 : -1);
}, true);

// --- Live preview ------------------------------------------------------------
//
// The node shows its assembled name while you type. The naming rules are not
// reimplemented here: the current widget values are posted to /vfx_naming/preview
// and whatever Python renders is written into the read-only `preview` widget.
//
// Which widgets exist changes as the user switches schema, and the DynamicCombo
// replaces them wholesale rather than firing a single change event we could hook.
// So instead of subscribing, this snapshots the values on a slow timer and only
// calls the backend when the snapshot actually differs - a string compare per
// node, several times a second, against a request that only fires on real edits.
// The same tick re-applies the schema's visibility flags for the same reason:
// the DynamicCombo rebuilds widgets without an event, and runs the pipe
// override pass (vfx_overrides.js), which mirrors the upstream node's values
// before the snapshot is taken. `overrides` is left out of the snapshot: which
// fields are overridden changes nothing in the rendered name.

const PREVIEW_ROUTE = "/vfx_naming/preview";
const POLL_MS = 250;
const DEBOUNCE_MS = 120;

const previewInput = (widget) =>
    widget.name !== PREVIEW_WIDGET && widget.name !== OVERRIDES_WIDGET;

const snapshot = (node) => JSON.stringify(
    (node.widgets ?? []).filter(previewInput).map((w) => [w.name, w.value]),
);

function collect(node) {
    const widgets = {};
    for (const widget of node.widgets ?? []) {
        if (previewInput(widget)) widgets[widget.name] = widget.value;
    }
    return widgets;
}

function show(node, text) {
    const widget = node.widgets?.find((w) => w.name === PREVIEW_WIDGET);
    if (!widget || widget.value === text) return;
    widget.value = text;
    if (widget.element) widget.element.value = text;
    node.setDirtyCanvas?.(true, false);
}

async function refresh(node, controller) {
    let response;
    try {
        response = await fetch(PREVIEW_ROUTE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ widgets: collect(node) }),
            signal: controller.signal,
        });
    } catch (error) {
        if (error?.name !== "AbortError") show(node, "(preview unavailable)");
        return;
    }
    if (!response.ok) { show(node, `(preview failed: HTTP ${response.status})`); return; }

    const data = await response.json().catch(() => null);
    if (!data) return;
    show(node, data.ok ? data.text : `! ${data.error}`);
}

function watch(node) {
    let last = null;
    let debounce = null;
    let inFlight = null;

    const tick = () => {
        applyVisibility(node, syncOverrides(node));
        if (node.__vfxUnresolved) {
            // Linked, but the pipe's source is out of reach: execution still
            // uses the real pipe, so do not render a name from stale values.
            last = null;
            clearTimeout(debounce);
            inFlight?.abort();
            show(node, "(from pipe)");
            return;
        }
        const current = snapshot(node);
        if (current === last) return;
        last = current;
        clearTimeout(debounce);
        debounce = setTimeout(() => {
            inFlight?.abort();
            inFlight = new AbortController();
            refresh(node, inFlight);
        }, DEBOUNCE_MS);
    };

    const timer = setInterval(tick, POLL_MS);
    const originalRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
        clearInterval(timer);
        clearTimeout(debounce);
        inFlight?.abort();
        return originalRemoved?.apply(this, args);
    };
}

app.registerExtension({
    name: "vfx.naming",

    async setup() {
        await loadSchemaFlags();
    },

    getNodeMenuItems(node) {
        return menuItems(node);
    },

    nodeCreated(node) {
        if (classOf(node) !== NODE_CLASS || node.__vfxPreviewWatched) return;
        node.__vfxPreviewWatched = true;

        const widget = node.widgets?.find((w) => w.name === PREVIEW_WIDGET);
        if (widget?.element) {
            widget.element.readOnly = true;
            widget.element.style.opacity = "0.85";
        }
        watch(node);
    },
});
