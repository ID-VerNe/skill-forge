---
name: apple-ui-principles
description: Apply Apple's design philosophy for both static visual polish (Optical Correction, Weight Balance) and fluid motion (Springs, Interruptibility) translated for the web. Ships a deterministic checker for the geometric half so optical alignment is measured, not eyeballed. Use to catch visual bugs math misses and build gesture-driven UI.
---

# Apple Design Engineering (苹果设计工程)

This skill encodes the advanced UI design principles derived from Apple's design philosophy, encompassing both **"The Look" (Static Visual Polish)** and **"The Feel" (Fluid Motion & Interaction)**.

Use this skill when auditing UI mockups, reviewing front-end code for visual polish, building gesture-driven UI, or when the user mentions "视觉校正", "Optical Alignment", "Apple UI details", "fluid interfaces", "spring animations", "framer-motion", or "视觉平衡".

Each principle below carries a marker:

- **[可校验: #n]** — measurable. Run the checker, quote the number, do not hand-tune.
- **[不可校验]** — perceptual. Reason about it, but say so; never invent a pixel value.

---

## Part 1: The Look (静态视觉感知与光学校正)

Mathematical perfection often looks visually wrong because **"the human eye is not physics"** (人的眼睛并不物理).

### 1. Visual Weight Balance vs. Negative Space (负空间与视觉重量补偿) [不可校验]

- **Concept:** Elements with less "fill" or sharp tapering (like a Wi-Fi icon or a triangle) leave empty negative space that makes the design feel unbalanced or "floating".
- **Action:** Add subtle visual weight to compensate. For example, if the top of an icon is heavy, slightly enlarge or shift the bottom elements inward to anchor it.
- **Rule of Thumb:** Geometric symmetry $\neq$ Visual balance. Always look at the negative space to see if one side feels "emptier".

### 2. Optical Alignment (几何中心 ≠ 视觉中心) [可校验: #1 ink-bbox, #2 centroid]

- **Concept:** A triangle (like a play button) perfectly centered mathematically will look like it's falling to the left because its visual mass leans left.
- **Action:** Do not nudge by feel. Run `optical check` on the asset; if the report says `off`, bake the shift into the `viewBox` (see "Baking the correction" below).
- **Numbers, not vibes:** a play triangle spanning x∈[8,19] in a 24 grid has its area centroid 1.83px left of its bounding-box centre. That is the measured value; "one pixel feels right" is a separate, taste-driven decision with its own constant.

### 3. Text Vertical Centering (文字盒与基线) [可校验: #4, #5, #7]

- **Concept:** A text node's box includes the font's ascent/descent padding plus half-leading. `align-items: center` centres the *box*, not the *letters*, so labels sit low.
- **Action (preferred):** `text-box: trim-both cap alphabetic;` — Baseline since August 2026 (Chrome 133+, Safari 18.2+, Firefox 154+).
- **Critical caveat:** `text-box` has **no effect on flex or grid containers**, and Chromium does not trim inline boxes. Button labels almost always live in a flex container, so the declaration silently no-ops. Apply it on an inline child, or check the report for `rule/text-box-in-flex`.
- **What the checker accepts as "armed":** only `trim-both` / `trim-start` / `trim-end`, in the longhand or shorthand, resolved in source order. `text-box: normal` and `text-box: cap alphabetic` reset trimming to `none` (omitted shorthand components take their initial value), so neither is reported. `display: flex !important` still counts as flex; `display: var(--d)` and contexts that disagree about `display` report `unknown`.
- **Legacy fallback:** if the target browser lacks `text-box`, compute the compensation with `#7` rather than guessing `margin-top: -1px`. The offset is `fontSize × (ascender + descender − capHeight) / (2 × upem)`, independent of `line-height`. The ascender/descender are the pair the browser uses for the line box (OS/2 typo or win, not necessarily hhea); the checker reports which pair it picked as `metricSource`. Values are calibrated to Chrome on Windows.

### 4. Optical Illusions & Mach Bands (侧抑制与视觉错觉) [不可校验]

- **Concept:** A bright color next to a dark color will create a false edge (Mach band). Colors look different depending on their surroundings.
- **Action:**
  - **Retina font trap:** Small fonts look bolder/muddier. Use specific font weights for small text vs large text.
  - **Dark mode bleeding:** White text on a black background looks thicker than black text on a white background. Slightly reduce font-weight (e.g., from `font-semibold` to `font-medium`) in dark mode, or apply `-webkit-font-smoothing: antialiased`.

### 5. The Golden Set for Curves (黄金家族) [部分可校验: #6]

- **Concept:** Highly polished shapes (Logos, complex UI curves, squircles) rely on strict geometric constraints to feel "stable".
- **Action:** When generating SVGs or reviewing corner radii, check for continuous curves. Use `border-radius` smoothing (like `border-curve: continuous` or Apple's squircle shape) instead of basic CSS circles when possible. If an element feels "off", check if its proportions approximate the Golden Ratio ($1.618$).
- **Concentric corners:** the inner radius is `calc(R_outer − P)` **only when padding is uniform**. With unequal insets the correct form is elliptical (`R−Px` / `R−Py`), and when `P > R` the real problem is an oversized outer radius — clamping to `0` hides it. Conflicting Tailwind utilities are resolved in **scale order**, not by their order in `className`.

### 6. Proximity as Syntax (邻近原则) [暂不可校验]

- **Concept:** Spacing is not decoration; it is syntax.
- **Action:** Ensure `gap`, `margin`, and `padding` clearly group related elements.
  - $Distance_{internal} < Distance_{external}$.
  - The space between an icon and its text must be smaller than the space between that button and the next button.
- **Icon + text gutters:** the "shrink the icon side by ~20%" rule is a proxy. The real target is equal *ink* gaps: `padding-left = G − (ink left bearing inside the icon box)`, where the bearing comes from the same measurement as `#1`.

---

## Part 2: The Feel (流体交互与物理映射) [不可校验 — 逐项人工评审]

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

### 1. Translucency & Hierarchy (材质与层级) [不可校验]

- **Concept:** Translucent materials act as floating functional layers that bring structure without stealing focus.
- **Action:** Use `backdrop-filter: blur()` + semi-transparent backgrounds.
- **Rule:** Darker/heavier materials separate structural regions; lighter materials draw attention to interactive elements. **Never stack a light translucent surface on another** — legibility collapses.
- **Action:** Dim to focus, separate to keep flow. A modal task pairs the surface with a dimming scrim.

### 2. Dynamic Typography (动态排版) [部分可校验: #7]

- **Tracking (letter-spacing):** Size-specific. Large display text wants *negative* tracking (e.g., `-0.02em`); small text wants slightly *positive* tracking. Body near `0`.
- **Leading (line-height):** Tight on large headings (`1.05`), looser on body copy (`1.5`).
- **`font-size-adjust: from-font`** normalises **x-height** only (not cap height) across fallback fonts. Do not use it as a cap-height fix.

### 3. Reduced Motion & Accessibility (无障碍与优雅降级) [不可校验]

- **`prefers-reduced-motion: reduce`:** Replace slides/springs with short opacity cross-fades or static transitions. Drop elastic/overshoot.
- **`prefers-reduced-transparency: reduce`:** Make translucent surfaces solid (raise background opacity, drop the blur).

---

## Running the optical checker

The checker answers one question: *is this within tolerance, or is it a defect?* It reads source files only — no browser, no `npm install`.

```bash
node scripts/optical/cli.mjs check <path...> [--json] [--explain] [--mode <mode>]
node scripts/optical/cli.mjs font <font.ttf> --size 16 [--line-height 1.5]
```

`--size` and `--line-height` take bare decimal numbers only; `16px` and `0x10`
are usage errors (exit `64`), not values silently coerced by `Number()`.

| Input | Mode | What is measured |
|---|---|---|
| `icon.svg` | `standalone` | ink box vs viewBox, centroid vs ink box |
| `icon.svg` with `<text>`/`<image>` | — | `unknown`: visible ink that is not geometry |
| `icon.svg` painting through `<style>`/`class` | — | paint is resolved: sheet normal < inline normal < sheet `!important` < inline `!important` |
| `icon.svg` with `fill="var(--x)"` or `@import` | — | `unknown`: the value lives outside the file. Replace it with a literal to measure the icon — a themed colour does not change the area, but `none` does, and the checker cannot tell which you have |
| `icon.svg` with `%` geometry | — | `unknown`: relative to a viewport the checker cannot see |
| `icon.svg` with `%` `stroke-width` | — | resolved against the **nearest declared viewport**, including a `<svg>`/`<symbol>`'s own declaration and its children; invalid negative percentages fall back to the inherited width and its provenance; ink leaving the visible user area is `unknown` |
| `icon.svg` that animates, or draws outside its viewport | — | `unknown`: one frame is not the drawing, and the browser clips the rest |
| `icon.svg` with `mask`/`filter`/`marker-*` (attribute, `style` or class) | — | `unknown`: mask and filter rewrite the painted region, a marker draws a shape of its own outside the path |
| `icon.svg` with `fill="url(#missing)"` | — | measured as no ink: SVG leaves the element unrendered. A reference to a gradient or pattern is measured normally — colour is not area. Flatten these to shapes if the verdict matters |
| `icon.svg` whose subpaths overlap *within one shape* | — | `unknown`: `overlapping-subpaths`. Summing them over-counts one winding and under-counts the other, and a union needs a boolean operation the checker does not have. Split the artwork into separate shapes if the verdict matters |
| `icon.svg` with a `fill`/`stroke` value CSS cannot parse (`notacolor`, `3`, `#12345`) | — | treated as a browser treats it: `fill` falls back to black **and still paints**, `stroke` falls back to `none` **and paints nothing**. Write the value you mean |
| `icon.svg` with `--mode inline` | `inline` | `unknown`: the optical gutter needs a sibling text node, and the CLI has no way to hand one over. Use `standalone` |
| `icon.svg` painting with `fill="currentColor"` | — | resolved against the `color` this file declares, transparent included. When `color` is **not** in the file, the pass assumes it is opaque — an icon hidden by a class upstream (`text-transparent`) measures as painted |
| `icon.svg` with `transform="rotate(45deg)"` — a unit in the **attribute** | — | measured untransformed, because that is what browsers do: the `transform` attribute takes bare numbers and the whole attribute is dropped otherwise. Write `rotate(45)` |
| `icon.svg` with `preserveAspectRatio="…slice"` at the root | — | `unknown` when the crop cuts the ink: `slice` fills the viewport and throws the overflow away, so ink outside the visible strip is not on screen. Ink that fits inside it answers normally |
| `icon.svg` with `vector-effect="non-scaling-stroke"` | — | the authored width is **px**, not user units: on a 48px canvas over a 24-unit viewBox, `stroke-width="2"` is one user unit |
| `icons/` (dir) | `keyline` | fill-ratio outliers across the set (needs ≥3 icons of one family) |
| `styles.css` | rule | `text-box` in flex/grid, hard-coded nudges |
| `styles.css` with `margin-top: var(--gap)` / `1rem` / `50%` / invalid math (`calc(2px*2px)`, `calc(2px+1px)`, `calc(- 2px)`) / `transform: var(--t)` on a text block | rule | `unknown` (`rule/nudge-unreadable`): the declaration wins the cascade but is not a value this pass can resolve, so a nudge cannot be ruled out. `calc(2px)`, `min()`, `clamp()`, `em` against a px `font-size`, `matrix()` and `-webkit-transform` *are* evaluated — only genuinely unknowable values and expressions CSS would drop refuse. A measurable margin in the same block is still reported as `nudge`, with the unreadable half left out. Inline the computed px value to get a verdict |
| `Button.tsx` | rule | same, plus concentric radii from the element tree |

| Verdict | Exit | Meaning | Response |
|---|---|---|---|
| `ok` | 0 | within tolerance | leave it alone |
| `nudge` | 0 | measurable offset, acceptable band | adopt the suggestion, do not block |
| `off` | 1 | certain defect | fix it |
| `unknown` | 2 | context missing (display, parent, font, unmeasurable ink, relative units) | report the gap; **never guess** |

`ok` is a claim about *this measurement*, not a certificate that the asset is
optically perfect. Four deliberate approximations survive inside it — several
`<path>`s painted over each other, dashes (`stroke-dasharray`), a stroke under a
non-uniform scale, and a stroke on a filled shape (the band is added to the fill,
not unioned with it). On those, read `ok` as "nothing measurable was wrong" and
look at the artwork. `optical-model.md` §1 lists the numbers.

Two rules that make the output trustworthy:

1. **Tolerances are not a flag.** There is no `--tolerance`. If a project truly needs a different curve, pass `--policy` and the report will carry `policy_source: "custom"`. A policy can only rescale pixel comparisons — it cannot turn an `unknown` into `ok`.
2. **Heuristic findings cap at `nudge`.** Only exact geometry can produce `off`. A pixel `off` always carries a number you can re-derive by hand; a rule-level `off` carries evidence instead of a number, and prints `—`.

When a report holds both `off` and `unknown`, the exit code is `1` (the defect is certain and must be fixed) while the `unknown` stays listed on every run. Never read a `2` as "clean" — it means *unmeasured*.

### Keeping the installed copies in sync

This directory is also what the agents run from: their config stores
(`~/.claude/skills`, `~/.qoder/skills`, `~/.gemini/config/skills`, …) hold an
entry named `apple-ui-principles`. Directory junctions resolve by path, so they
are live the moment the repository changes. The Gemini CLI install cannot be a
junction — hardlinks work on files only — so it is a real tree whose files share
inodes with the repository.

That is the one fragile spot: git replaces a file by writing a new inode, which
silently breaks the hardlink and leaves the mirror serving the old rules. No
error, no warning. Repair it with:

```bash
node scripts/optical/cli.mjs check --self-heal
```

The repair is idempotent, reports on stderr so `--json` stays parseable, only
touches install positions that already exist, and never creates one. With no
paths it heals and stops — under `--json` that prints
`{"version":1,"self_heal":…}` instead of a verdict; with paths it heals first,
then checks. Exit `2` means the repair could not finish; exit `64` means it was
pointed at an installed copy rather than the repository. `--home` and
`--skill-dir` override the two directories involved — the tests use them, and so
can a project with an unusual layout.

Treat the mirror as read-only. Its files share inodes with the repository, so
editing one through the installed path rewrites the repository copy too.

### Baking the correction

Do not scatter `translate-x-[1.5px]` through components. Fix it in the asset, then re-run until `ok`; any `flex items-center justify-center` downstream inherits the fix for free.

The two geometry findings have **different** fixes, and the report says which:

| Finding | Fix | `suggested.value` |
|---|---|---|
| `geometry/ink-bbox` | move the viewBox origin | size of the correction in px (paste `suggested.viewBox`) |
| `geometry/centroid` | redraw the mass — translating cannot fix it | how far to move the visual mass |

A centroid offset survives any translation because the centroid and the ink box
move together. If the number is inside tolerance, leave the shape alone.

`geometry/ink-bbox` prints the literal attribute to paste:

```json
{ "kind": "viewBox-origin", "value": "-4px / 0px", "viewBox": "-4 0 24 24" }
```

`viewBox` is the corrected attribute — paste it. `value` is the size of that
correction in rendered px, the same units as `measured`, and it is **not**
always the number to add to the origin: the origin is in user units, so on a
512-unit grid `value` says `-0.57px` while the origin moves by `-12.19`. When a
user unit is not a pixel and the offset is non-zero, `suggested.delta` carries
the figure that goes into the origin; it is absent when it would just repeat
`value`. Sign: moving the origin by `d` moves the artwork by `−d`.

All reported offsets are in rendered px, not viewBox units. `meta.unitScale` says how they were derived: a root `width="48"` on a 24-unit viewBox yields `2`, and the evidence string appends `[user units ×2 = px]`. With no absolute `width`/`height` the icon is assumed to render at **24px on its short side**, so a 480-unit grid scales by `0.05`. That keeps the verdict a property of the drawing rather than of the canvas size — a 512-unit Font Awesome glyph and a 24-unit icon with the same 8% imbalance now agree.

---

## Workflow: Auditing & Applying Apple Design

When asked to "apply optical correction", "review visual balance", or "make it fluid":

1. **Measure first.** Run `optical check` on every SVG, stylesheet and component in scope. Quote numbers, not impressions.
2. **Identify Asymmetry & Fix Weight:** Use the `#1`/`#2` output to decide the shift; leave the `[不可校验]` judgements to a human.
3. **Eliminate Latency:** Ensure feedback triggers on `pointerdown` (instant), not `click`/`pointerup`.
4. **Upgrade to Springs:** Check if CSS transitions are used for interactive elements. Replace them with Spring libraries (like Framer Motion) using `damping 1.0` defaults.
5. **Fix Typography & Material:** Recommend `-webkit-font-smoothing`, check dark mode weights, apply appropriate tracking for large text, and ensure translucent layers don't incorrectly overlap.
6. **Check Accessibility:** Ensure `@media` queries exist for reduced motion and transparency.
7. **Re-run the checker** before claiming a visual fix. A claim without a report is a guess.

> *"Design isn't just about geometry, it's about how the human brain actually 'sees' it and how the hand 'feels' it."*

Derivations, constants and the reasons behind each threshold live in `references/optical-model.md`.
