---
name: apple-ui-principles
description: Apply Apple's design philosophy for both static visual polish (Optical Correction, Weight Balance) and fluid motion (Springs, Interruptibility) translated for the web. Use to catch visual bugs math misses and build gesture-driven UI.
---

# Apple Design Engineering (苹果设计工程)

This skill encodes the advanced UI design principles derived from Apple's design philosophy, encompassing both **"The Look" (Static Visual Polish)** and **"The Feel" (Fluid Motion & Interaction)**. 

Use this skill when auditing UI mockups, reviewing front-end code for visual polish, building gesture-driven UI, or when the user mentions "视觉校正", "Optical Alignment", "Apple UI details", "fluid interfaces", "spring animations", "framer-motion", or "视觉平衡".

---

## Part 1: The Look (静态视觉感知与光学校正)

Mathematical perfection often looks visually wrong because **"the human eye is not physics"** (人的眼睛并不物理). 

### 1. Visual Weight Balance vs. Negative Space (负空间与视觉重量补偿)
- **Concept:** Elements with less "fill" or sharp tapering (like a Wi-Fi icon or a triangle) leave empty negative space that makes the design feel unbalanced or "floating".
- **Action:** Add subtle visual weight to compensate. For example, if the top of an icon is heavy, slightly enlarge or shift the bottom elements inward to anchor it.
- **Rule of Thumb:** Geometric symmetry $\neq$ Visual balance. Always look at the negative space to see if one side feels "emptier".

### 2. Optical Alignment (几何中心 ≠ 视觉中心)
- **Concept:** A triangle (like a play button) perfectly centered mathematically will look like it's falling to the left because its visual mass leans left.
- **Action:** Manually nudge asymmetrical icons (Play buttons, send arrows, Chevrons) slightly towards their lighter side (e.g., move a Play button slightly right) so the visual mass is centered.
- **Action:** Text bounding boxes often include line-height padding. Vertically aligning a text node with an icon using `align-items: center` often looks mathematically right but optically too low. Adjust with slight margins or padding (e.g., `mt-[1px]`).

### 3. Optical Illusions & Mach Bands (侧抑制与视觉错觉)
- **Concept:** A bright color next to a dark color will create a false edge (Mach band). Colors look different depending on their surroundings.
- **Action:** 
  - **Retina font trap:** Small fonts look bolder/muddier. Use specific font weights for small text vs large text.
  - **Dark mode bleeding:** White text on a black background looks thicker than black text on a white background. Slightly reduce font-weight (e.g., from `font-semibold` to `font-medium`) in dark mode, or apply `-webkit-font-smoothing: antialiased`.

### 4. The Golden Set for Curves (黄金家族)
- **Concept:** Highly polished shapes (Logos, complex UI curves, squarcles) rely on strict geometric constraints to feel "stable".
- **Action:** When generating SVGs or reviewing corner radii, check for continuous curves. Use `border-radius` smoothing (like `border-curve: continuous` or Apple's squircle shape) instead of basic CSS circles when possible. If an element feels "off", check if its proportions approximate the Golden Ratio ($1.618$).

### 5. Proximity as Syntax (邻近原则)
- **Concept:** Spacing is not decoration; it is syntax. 
- **Action:** Ensure `gap`, `margin`, and `padding` clearly group related elements. 
  - $Distance_{internal} < Distance_{external}$.
  - The space between an icon and its text must be smaller than the space between that button and the next button.

---

## Part 2: The Feel (流体交互与物理映射)

An interface is fluid when it behaves like the physical world: things respond instantly, move continuously, carry momentum, resist at boundaries, and can be redirected mid-motion.

### 1. Interruptibility (可打断性)
- **Concept:** Every animation must be interruptible and redirectable at any moment. A user must be able to grab a moving element mid-flight and reverse it without waiting for the animation to finish.
- **Action:** Never lock out input during a transition. Always animate from the *presentation* (current) value, never the target value. Avoid CSS transitions/`@keyframes` for gesture-driven UI. Use Spring animations.

### 2. Behavior over Animation: Use Springs (弹簧物理模型)
- **Concept:** A pre-scripted animation can't respond to new input. Springs animate from the current value by default.
- **Action:** Map web springs (Framer Motion / Motion) to Apple's params:
  - **Default UI spring:** `damping: 1.0` (critically damped, no overshoot), `response: 0.3-0.4`.
  - **Momentum/flick spring:** `damping: ~0.8` (under-damped, slight bounce). Only use bounce when the gesture itself carried momentum.

### 3. Direct Manipulation & Velocity Handoff (1:1 跟手与速度继承)
- **Concept:** Touch and content should move together seamlessly.
- **Action:** 
  - Use Pointer Events (`setPointerCapture`) and respect the grab offset.
  - When a gesture ends, pass the pointer's release velocity as the spring's initial velocity so there is no visible seam between dragging and animating.
  - `relativeVelocity = gestureVelocity / (targetValue − currentValue)`

### 4. Momentum Projection & Rubber-banding (动量投射与边界阻尼)
- **Concept:** Don't snap to the nearest boundary from the release point. Use velocity to project the resting position.
- **Action:** Calculate projected endpoint `current + (v/1000)·d/(1−d)` where `d ≈ 0.998`.
- **Action:** At an edge, apply progressive resistance (rubber-banding) instead of a hard stop.

---

## Part 3: Materials, Depth & Typography (材质、空间与排版)

### 1. Translucency & Hierarchy (材质与层级)
- **Concept:** Translucent materials act as floating functional layers that bring structure without stealing focus.
- **Action:** Use `backdrop-filter: blur()` + semi-transparent backgrounds.
- **Rule:** Darker/heavier materials separate structural regions; lighter materials draw attention to interactive elements. **Never stack a light translucent surface on another** — legibility collapses.
- **Action:** Dim to focus, separate to keep flow. A modal task pairs the surface with a dimming scrim.

### 2. Dynamic Typography (动态排版)
- **Tracking (letter-spacing):** Size-specific. Large display text wants *negative* tracking (e.g., `-0.02em`); small text wants slightly *positive* tracking. Body near `0`.
- **Leading (line-height):** Tight on large headings (`1.05`), looser on body copy (`1.5`).

### 3. Reduced Motion & Accessibility (无障碍与优雅降级)
- **`prefers-reduced-motion: reduce`:** Replace slides/springs with short opacity cross-fades or static transitions. Drop elastic/overshoot.
- **`prefers-reduced-transparency: reduce`:** Make translucent surfaces solid (raise background opacity, drop the blur).

---

## Workflow: Auditing & Applying Apple Design

When asked to "apply optical correction", "review visual balance", or "make it fluid":
1. **Identify Asymmetry & Fix Weight:** Find icons/text with uneven mass and nudge them to fix the center of visual mass.
2. **Eliminate Latency:** Ensure feedback triggers on `pointerdown` (instant), not `click`/`pointerup`.
3. **Upgrade to Springs:** Check if CSS transitions are used for interactive elements. Replace them with Spring libraries (like Framer Motion) using `damping 1.0` defaults.
4. **Fix Typography & Material:** Recommend `-webkit-font-smoothing`, check dark mode weights, apply appropriate tracking for large text, and ensure translucent layers don't incorrectly overlap.
5. **Check Accessibility:** Ensure `@media` queries exist for reduced motion and transparency.

> *"Design isn't just about geometry, it's about how the human brain actually 'sees' it and how the hand 'feels' it."*
