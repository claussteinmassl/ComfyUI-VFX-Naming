import { app } from "../../scripts/app.js";

// Shot-number stepping for the VFX Naming Convention node.
//
// Two behaviours ComfyUI's stock INT widget cannot give at the same time:
//
//   1. Manual entry is free-form. The widget uses a single option (`step2`)
//      for both the increment AND for snapping every committed value onto that
//      grid, so a Python `"step": 10` would round a typed 15 up to 20. Python
//      therefore declares step 1, and the snap is neutralised during commit.
//
//   2. The +/- buttons land on the nearest shot number ending in 0, in the
//      direction pressed - 98 goes up to 100 and down to 90 - instead of a
//      blind +/-10 that would carry an off-grid number along (98 -> 108).
//
// With Comfy.VueNodes enabled the widget renders as a DOM component whose
// +/- buttons do `model = clamp(model +/- step)` and commit by calling
// `widget.callback(value)` directly - never `setValue()` or `onClick()`. So
// the grid step is applied two ways, both of which are no-ops when the value
// is already on the grid:
//
//   a. On pointerdown, `options.step2` is set to the exact distance to the
//      next grid point in that direction. The option is reactive, and a
//      pointerdown precedes the click by a full task, so the component has
//      re-rendered with the new step before it computes the value. It is
//      restored on the following click.
//   b. As a safety net (and for the keyboard arrows, where there is no
//      re-render between keydown and the handler), the wrapped callback
//      redirects an armed change onto the grid.
//
// If this script fails to load, the widget falls back to increments of 1 and
// remains fully usable.

const NODE_CLASS = "VFXNamingConvention";
const WIDGET_NAME = "shot_number";
const INCREMENT = 10;
const ARM_TIMEOUT_MS = 800;

// Nearest multiple of INCREMENT strictly above / below the current value.
const gridStep = (value, direction) =>
    direction > 0
        ? Math.floor(value / INCREMENT) * INCREMENT + INCREMENT
        : Math.ceil(value / INCREMENT) * INCREMENT - INCREMENT;

const clampToWidget = (value, options) =>
    Math.min(options?.max ?? Infinity, Math.max(options?.min ?? -Infinity, value));

/** The armed spinner press: { widget, node, target } or null. */
let armed = null;
let armedTimer = null;

function disarm() {
    if (armed) armed.widget.options.step2 = INCREMENT;
    armed = null;
    if (armedTimer) { clearTimeout(armedTimer); armedTimer = null; }
}

/** Resolve a DOM element inside a widget back to our node's shot_number widget. */
function resolveWidget(element) {
    const container = element.closest?.(`[aria-label="${WIDGET_NAME}"]`);
    if (!container) return null;

    const nodeElement = container.closest("[data-node-id]");
    const id = nodeElement?.dataset?.nodeId;
    if (!id) return null;

    const graph = app.graph;
    const node = graph?.getNodeById?.(id) ?? graph?.getNodeById?.(Number(id));
    if (!node) return null;
    if ((node.comfyClass ?? node.constructor?.comfyClass) !== NODE_CLASS) return null;

    const widget = node.widgets?.find((w) => w.name === WIDGET_NAME);
    if (!widget || typeof widget.value !== "number") return null;

    // The component's own model is what it steps from; it is what the input
    // displays. Fall back to the widget value if that cannot be read.
    const shown = Number(container.querySelector("input")?.value);
    const base = Number.isFinite(shown) ? shown : widget.value;

    return { node, widget, base };
}

function arm(element, direction) {
    const resolved = resolveWidget(element);
    if (!resolved) return;

    const { node, widget, base } = resolved;
    const target = clampToWidget(gridStep(base, direction), widget.options);

    disarm();
    armed = { widget, node, target };
    // Let the component compute the grid value itself where it can.
    widget.options.step2 = Math.abs(target - base) || INCREMENT;
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
// component's handler, so these rely on the callback safety net below.
document.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    arm(target, event.key === "ArrowUp" ? 1 : -1);
}, true);

app.registerExtension({
    name: "vfx.naming.shot_number_increment",

    nodeCreated(node) {
        const cls = node.comfyClass ?? node.constructor?.comfyClass;
        if (cls !== NODE_CLASS) return;

        const widget = node.widgets?.find((w) => w.name === WIDGET_NAME);
        if (!widget || widget.__vfxIncrementPatched) return;
        widget.__vfxIncrementPatched = true;

        widget.options = widget.options ?? {};
        widget.options.step2 = INCREMENT;      // +/- increment
        widget.options.step = INCREMENT * 10;  // drag sensitivity

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
    },
});
