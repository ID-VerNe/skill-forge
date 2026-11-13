# Choreography Recipes (Interruptible & Geometry-Agnostic)

All patterns assume React + `motion/react` (Framer Motion) wrapped in `<MotionConfig reducedMotion="user">`. Preserve the host component's existing classes, radii, and color tokens.

---

## 1. Transient Axis Elongation (过渡轴向拉伸)
Container stretches along the travel axis during content swap, then settles back to its resting width.

```tsx
// Assumes container already has its own resting width/height/radius classes
const [pulse, setPulse] = useState(false);
const timerRef = useRef<number>();

const triggerSwap = (next: number) => {
  setPulse(true);
  window.clearTimeout(timerRef.current);
  timerRef.current = window.setTimeout(() => setPulse(false), 140);
  onChange(next);
};

<motion.div
  className="relative inline-flex items-center justify-center overflow-hidden"
  animate={{ scaleX: pulse ? 1.32 : 1, scaleY: pulse ? 0.94 : 1 }} // Preserves volume feel
  transition={{ type: "spring", stiffness: 460, damping: 22 }}
>
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
```
*(Tip: If inner text shouldn't distort horizontally during `scaleX`, animate explicit `width` instead of `scaleX`, or counter-scale the inner span.)*

---

## 2. Interruptible Force-Vector Path Deflection (可打断的力矢量路径弯曲)
Drives an SVG Quadratic Bézier control point via `useSpring` + `useTransform` so rapid clicks reverse smoothly mid-bend.

```tsx
// Deflects horizontal line at y=17 downward/upward based on spring force
const force = useSpring(0, { stiffness: 320, damping: 14, mass: 0.7 });
const trayPath = useTransform(force, (f) => `M 5 17 Q 12 ${17 + f} 19 17`);
const arrowY = useTransform(force, (f) => f * 0.45);

const handleTrigger = () => {
  force.set(6); // Positive = downward bend; Negative = upward bend
  setTimeout(() => force.set(0), 90);
};

<svg
  viewBox="0 0 24 24"
  className="overflow-visible"
  fill="none"
  stroke="currentColor"
  onPointerDown={handleTrigger}
>
  <motion.path style={{ y: arrowY }} d="M12 4v10m0 0l-3.5-3.5M12 14l3.5-3.5" />
  <motion.path d={trayPath} />
</svg>
```

---

## 3. Aspect-Ratio & Curvature Morph (长宽比与曲率跨态变形)
Transitions asymmetrically between resting and active footprint using `layout` without dictating fixed pixel radii.

```tsx
<motion.button
  layout
  onPointerDown={() => onSelect(id)}
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

---

## 5. Synchronous Extrusion Collapse (同步 Z 轴下沉压缩)
Triggers on `pointerdown` for zero-latency tactile feel; collapses shadow offset proportionally to Y-travel.

```tsx
// Uses CSS variable `--lip-color` inherited from host theme
<motion.button
  initial={{ y: 0, boxShadow: "0 4px 0 var(--lip-color)" }}
  whileHover={{ y: -1, boxShadow: "0 5px 0 var(--lip-color)" }}
  whileTap={{ y: 3, boxShadow: "0 1px 0 var(--lip-color)" }}
  transition={{ type: "spring", stiffness: 550, damping: 28 }}
/>
```

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
