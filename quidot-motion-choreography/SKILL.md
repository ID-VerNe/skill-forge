---
name: quidot-motion-choreography
description: >
  Playful shape-morphing and elastic micro-choreography add-on for Web (React/Framer Motion) and
  Mobile/Desktop (Kotlin/Jetpack Compose), inspired by quidot/yui. Strictly agnostic to colors,
  static geometry, and materials—designed to layer cleanly on top of `apple-ui-principles` or any
  existing design system. Use when components need expressive stretching, vector path deflection,
  coupled drag follow-through, or morphing state transitions across Web or Compose.
---

# Quidot Motion Choreography (跨端交互形变编排)

This skill is a **pure motion-choreography extension**. It intentionally **does NOT define** colors, typography, corner radii, optical alignment, or base accessibility rules—defer all static aesthetics, materials, and baseline fluid rules (interruptibility, immediate touch feedback, reduced motion) to `apple-ui-principles` or the host design system.

Your sole responsibility here is **how UI geometry dynamically deforms, bridges, and reacts during interaction**.

## 1. Compatibility Rules (Layering on Apple UI Principles)
- **Inherit Geometry & Theme**: Apply deformations relative to whatever shape, size, and color tokens the component already uses.
- **Always Interruptible**: Never lock input or rely on non-interruptible fixed timelines. Drive every morph via continuous Spring physics (`useSpring` / `Animatable`) so mid-flight reversal carries velocity seamlessly.
- **Zero-Latency Down State**: Trigger tactile compression and elastic cues immediately on `pointerdown` (Web) or `awaitFirstDown` / `MutableInteractionSource` press (Compose), never waiting for `click` release.
- **Respect Reduced Motion**: Honor `prefers-reduced-motion` (Web) or system animator scale / reduced motion settings (Compose) by collapsing stretches and bends into gentle fades or instant states.

## 2. Stack Detection & Execution Routing
Before writing code, detect the target platform from the workspace or prompt:
- **Web (React / Next.js / TypeScript)**: Read `references/recipes-web-motion.md`. Prefer Framer Motion (`motion/react`) wrapped in `<MotionConfig reducedMotion="user">`.
- **Kotlin / Jetpack Compose (Android / Compose Multiplatform)**: Read `references/recipes-compose.md`. Strictly follow Compose performance rules:
  - Use `Animatable` + `spring(...)` for interruptible animations.
  - Defer state reads into `Modifier.graphicsLayer { ... }` or `Canvas` / `drawBehind` lambdas to avoid unnecessary recomposition.
  - Use `pointerInput` (`awaitEachGesture { awaitFirstDown() ... }`) instead of waiting for `clickable` when triggering instant down-press deformations.

## 3. Six Expressive Morphing Manifestations
When building interactive components, avoid flat uniform `scale` or `opacity` fades. Match the interaction to one of these 6 kinematic patterns:

1. **Transient Axis Elongation (过渡轴向拉伸)**
   - *Use for*: Stepper/date badges, carousels, compact value switchers.
   - *Kinematics*: Momentarily pulse the container along the axis of travel (`scaleX` + subtle inverse `scaleY` to preserve perceived volume) synchronized with clipped inner content sliding, then spring back.
2. **Force-Vector Path Deflection (力矢量路径弯曲)**
   - *Use for*: Action icons (upload, download, submit, dividers).
   - *Kinematics*: Drive a Quadratic Bézier control point (`Q` in SVG / `quadraticTo` in Compose `Path`) with an interruptible spring along the force vector so straight strokes bow like a rubber membrane and snap back.
3. **Aspect-Ratio & Curvature Morph (长宽比与曲率跨态变形)**
   - *Use for*: Icon groups, segmented controls, multi-state action dots.
   - *Kinematics*: Transition asymmetrically between compact and expanded states (morphing aspect ratio and relative corner curvature) so neighboring elements yield space smoothly.
4. **Coupled Secondary Follow-Through (主从弹性跟随)**
   - *Use for*: Joysticks, sliders, magnetic handles.
   - *Kinematics*: The grabbed handle tracks the pointer 1:1 (direct manipulation), while its outer track/socket derives a dampened secondary offset (`~18%–25%` of primary displacement) to simulate flexible silicone coupling.
5. **Synchronous Extrusion Collapse (同步 Z 轴下沉压缩)**
   - *Use for*: Tactile push buttons (`+`/`-`, keys, triggers).
   - *Kinematics*: Translate the foreground surface along Y while synchronously collapsing the solid bottom lip offset on press-down.
6. **Shared-Boundary Bridging (共享边界流体衔接)**
   - *Use for*: Tab indicators, radio focus rings, active pill selectors.
   - *Kinematics*: Glide active selection containers across siblings (`layoutId` on Web; `SharedTransitionLayout` / animated offset + custom concave `Shape` in Compose) so active items visually weld to their base surface.
