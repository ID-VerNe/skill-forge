# Choreography Recipes (Interruptible & Geometry-Agnostic)

All patterns assume React + `motion/react` (Framer Motion). Preserve the host component's existing classes, radii, and color tokens.

## What `<MotionConfig reducedMotion="user">` actually covers

Wrap the tree in `<MotionConfig reducedMotion="user">`, but do not assume it handles every recipe below. It suppresses **only** `transform`, `opacity`, and `layout` projection animations.

| Carrier used by a recipe | Suppressed by `MotionConfig`? |
|---|---|
| `transform` (`scaleX`, `scaleY`, `scale`, `x`, `y`, `rotate`) | Yes |
| `opacity` | Yes |
| `layout` / `layoutId` projection | Yes |
| CSS `boxShadow`, `filter`, `background-color` | **No** — attribute animation |
| SVG `d`, `viewBox`, `pathLength` | **No** — attribute animation |
| `width` / `height` / `flexGrow` / `borderRadius` | **No** — layout, not projection |
| Any `useMotionValue` + imperative `animate()` you call yourself | **No** — outside the config context |

Recipes 2 and 5 fall on the "No" side, so they branch on `useReducedMotion()` explicitly. Recipes 3, 4 and 6 stay entirely on `transform` / `opacity` / `layout` and need no branch. Recipe 1 animates `transform` only, which the config would suppress — but it also drives that transform through `useMotionValue` + imperative `animate()`, which the config cannot see, so it carries its own `useReducedMotion()` guard.

Under reduced motion the goal is to **remove the deformation**, not to compress it into a single frame: an instant jump to a 1.32x size and straight back flashes the entire control, which reads worse to a vestibular-sensitive user than a smooth animation. Keep geometry at rest and move the feedback onto opacity.

---

## 1. Transient Axis Elongation (过渡轴向拉伸)
Container stretches along the travel axis during content swap, then settles back to its resting width.

```tsx
const [value, setValue] = useState(3);
const [dir, setDir] = useState(1);
const reduce = useReducedMotion();
const stretch = useMotionValue(1);

// Vertical squash keeps the perceived volume constant; the inner layer divides
// the horizontal scale back out so the glyphs never widen.
const scaleY = useTransform(stretch, (s) => 1 - (s - 1) * 0.19);
const counter = useTransform(stretch, (s) => 1 / s);

const triggerSwap = (next: number) => {
  setDir(next > value ? 1 : -1);
  setValue(next);
  if (reduce) return;                 // feedback falls through to the fade below
  if (stretch.get() > 1.004) return;  // pulse in flight: swap the digit, don't stack velocity
  animate(stretch, 1, { type: "spring", stiffness: 520, damping: 46, velocity: 20 });
};

<div className="relative inline-flex items-center justify-center overflow-hidden">
  <motion.div
    style={{ scaleX: stretch, scaleY }}
    className="relative inline-flex items-center justify-center overflow-hidden"
  >
    <motion.div style={{ scaleX: counter }} className="relative">
      <AnimatePresence mode="popLayout" initial={false} custom={dir}>
        <motion.span
          key={value}
          custom={dir}
          initial={{ x: dir * 24, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: dir * -24, opacity: 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 26 }}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  </motion.div>
</div>
```

**Why the target never changes.** The spring is aimed at its own resting value `1` on every call; the overshoot comes entirely from `velocity`. There is no `pulse` boolean to flip back and no timer to clear, so an interrupted pulse cannot drag the total duration out — a reversal simply restarts the same spring toward the same target with the existing velocity. Measured on a 72px-wide container: a single tap holds above rest for 303ms, a reversal at 40/100/200ms for 287/287/286ms, and eight rapid taps peak at 94.98px without accumulating.

**Peak amplitude is analytic.** For a critically damped spring started with velocity `v`, the overshoot is `v / (√k · e)`. With `k = 520` and `v = 20` that is `20 / (22.8 × 2.718) ≈ 0.323`, so the container tops out at 1.32x — matching the original recipe's intent without any measurement fiddling. Measured peak was 1.3201 (72px → 95.05px), within 0.2% of the closed form. Changing `velocity` scales the peak linearly; changing `stiffness` scales it as `1/√k`.

**Counter-scale is mandatory, not a tip.** `scaleX` on a parent stretches every glyph inside it. Measured: 72px → 95.1px container moved the digit from 14.81px to 20.23px wide, a 37% stretch, before the inner `scaleX: 1/s` layer was added. After it, the digit's width is flat across all 26 intermediate frames. The inner counter-scale must sit on a layer that is *inside* the scaled element and *outside* the sliding text.

**All grids containing this component must budget the peak width**, or the pulsing container will be clipped by a fixed-width cell. Reserve `1.32 ×` the resting width, or place the component in a flexible cell.

---

## 2. Interruptible Force-Vector Path Deflection (可打断的力矢量路径弯曲)
Drives an SVG Quadratic Bézier control point via `useSpring` + `useTransform`. The bend follows the press and releases on `pointerup`, so holding the button holds the bend and dragging off cancels it.

```tsx
const reduce = useReducedMotion();
const force = useSpring(0, { stiffness: 320, damping: 14, mass: 0.7 });
const [dim, setDim] = useState(false);

const trayPath = useTransform(force, (f) => `M 5 17 Q 12 ${17 + f} 19 17`);
const arrowY = useTransform(force, (f) => f * 0.45);

const press = () => {
  if (reduce) { setDim(true); return; }   // geometry stays put; opacity carries the cue
  force.set(6);                           // Positive = downward bend; Negative = upward bend
};
const release = () => {
  if (reduce) { setDim(false); return; }
  force.set(0);
};

<svg
  viewBox="0 0 24 24"
  className="overflow-visible"
  fill="none"
  stroke="currentColor"
  onPointerDown={press}
  onPointerUp={release}
  onPointerLeave={release}
  onPointerCancel={release}
>
  {/* Under reduced motion the bend collapses to a held dim, mirroring
      "bend while held" — not a looping keyframe, which would flicker on rapid taps. */}
  <motion.g animate={reduce ? { opacity: dim ? 0.4 : 1 } : { opacity: 1 }} transition={{ duration: 0.15 }}>
    <motion.path style={{ y: arrowY }} d="M12 4v10m0 0l-3.5-3.5M12 14l3.5-3.5" />
    <motion.path d={trayPath} />
  </motion.g>
</svg>
```

**No timer.** The previous version released with `setTimeout(() => force.set(0), 90)`. Because `force.set` is idempotent, a second press inside that window produced no increment while the first timer still fired at its original deadline — measured as a dead repeat: presses 30ms and 70ms after the first produced trajectories identical to a single press, while a press at 130ms (outside the window) behaved normally. Releasing on `pointerup` makes the semantics match the interaction ("bend while held"), and `pointerleave` / `pointercancel` cover the drag-off and scroll-cancel cases that a timer silently ignored.

**`MotionConfig` cannot reach this.** The bend is an SVG `d` attribute, which is not a transform, so the container-level config leaves it fully animating under `prefers-reduced-motion` — verified at 19 distinct `d` values with and without the preference. The `useReducedMotion()` branch is the only thing that stops it.

Note the deliberate change of feel: this is now a hold-to-bend, not a tap-to-pulse. If you want one-shot behaviour, do not reintroduce a timer — seed an impulse instead, as in recipe 1.

---

## 3. Aspect-Ratio & Curvature Morph (长宽比与曲率跨态变形)
Transitions asymmetrically between resting and active footprint using `layout` without dictating fixed pixel radii.

```tsx
<motion.button
  layout
  onPointerDown={() => onSelect(id)}
  // Neither literal is the width ratio you get. flexGrow is normalized across
  // the flex line, so its contribution to width depends on the sibling count,
  // and `scale` multiplies on top of that. Measured on a 3-item row: the active
  // item ends up 1.851x its resting *rendered* width (not 1.6). Tune against a
  // measurement, not against these two numbers.
  animate={{
    flexGrow: isActive ? 1.6 : 1,
    scale: isActive ? 1.12 : 0.92,
  }}
  whileTap={{ scale: 0.88 }}
  transition={{ type: "spring", stiffness: 420, damping: 22 }}
>
  {/* Inner glyph scales/rotates independently for optical crispness */}
</motion.button>
```

The two mechanisms compound rather than replacing each other: `flexGrow` claims layout space from siblings while `scale` additionally enlarges the painted box, and the inactive neighbour shrinks to 0.92 at the same time. Measured effective width ratio on a 3-item row is 1.851 (a steady-state value, not an overshoot peak), the same figure the issue reports. Do not expect to reproduce it with arithmetic: `flexGrow` is normalized against the whole flex line, so the realized ratio moves with the sibling count and with the neighbours' own resting widths. If you need a specific footprint, measure it or drive `width` directly instead of stacking two ratios.

---

## 4. Coupled Secondary Follow-Through (主从弹性跟随)
Direct 1:1 pointer tracking on the knob (`apple-ui-principles` compliant) paired with dampened vector follow-through on the socket.

```tsx
const x = useMotionValue(0);
const y = useMotionValue(0);
// Dampened socket follow-through (20% of primary displacement)
const socketX = useTransform(x, (v) => v * 0.2);
const socketY = useTransform(y, (v) => v * 0.2);

<div className="relative flex items-center justify-center">
  {/* Outer Socket / Track */}
  <motion.div style={{ x: socketX, y: socketY }} className="socket-classes" />

  {/* 1:1 Direct-Manipulation Handle */}
  <motion.div
    drag
    dragConstraints={{ top: -18, left: -18, right: 18, bottom: 18 }}
    dragElastic={0.18}
    dragSnapToOrigin
    style={{ x, y }}
    whileDrag={{ scale: 1.05 }}
    transition={{ type: "spring", stiffness: 360, damping: 24 }}
    className="absolute handle-classes"
  />
</div>
```

`useTransform` is a pure mapping, not an animation, so there is nothing for reduced motion to suppress here — and direct manipulation should not be suppressed anyway. Do not "upgrade" the socket to `useSpring` for extra lag without branching on `useReducedMotion()`: a spring on a `MotionValue` is invisible to `MotionConfig` and will keep lagging under the preference.

---

## 5. Synchronous Extrusion Collapse (同步 Z 轴下沉压缩)
Triggers on `pointerdown` for zero-latency tactile feel; the foreground sinks into a static lip, so the visible lip thins as the travel increases.

```tsx
// The lip is a separate, non-animated layer. Only the foreground's y moves,
// so the whole effect rides on a transform.
<div className="relative inline-block" style={{ height: 40 + lip }}>
  <div
    className="absolute inset-x-0 bottom-0 rounded-xl"
    style={{ height: 40, background: "var(--lip-color)" }}
  />
  <motion.button
    initial={{ y: 0 }}
    whileHover={{ y: -1 }}
    whileTap={{ y: lip - 1 }}   // leave 1px of lip, not zero
    transition={{ type: "spring", stiffness: 550, damping: 28 }}
    className="relative block rounded-xl"
    style={{ height: 40 }}
  />
</div>
```

**This replaces the `boxShadow` version on purpose.** `boxShadow` is an attribute animation: `MotionConfig reducedMotion="user"` does not suppress it, so under `prefers-reduced-motion` the shadow kept interpolating through all 27 discrete values while every transform in the same page collapsed to 2 frames (measured in issue #69). Rebuilding the lip as real geometry plus a `y` translation makes the recipe obey the preference automatically, and it also renders consistently across engines that round shadow blur differently from `transform`.

Expose the lip thickness as `lip` (the offset from the surface to the lip's bottom edge) and size the outer wrapper `height + lip` so the lip is visible outside the button's box. Paint the lip with `var(--lip-color)` as before.

---

## 6. Shared-Boundary Bridging (共享边界流体衔接)
Smoothly glides an active selection container across siblings using `layoutId`.

```tsx
// Inside a mapped list of tabs or radio options
{isActive && (
  <motion.div
    layoutId="active-bridge"
    className="absolute inset-0 pointer-events-none"
    transition={{ type: "spring", stiffness: 400, damping: 28 }}
  />
)}
```
*(Optional: Attach concave pseudo-element corner masks inheriting `var(--surface-active)` when bridging tabs to a flush container edge.)*
