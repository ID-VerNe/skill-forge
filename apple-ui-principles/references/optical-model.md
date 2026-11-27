# Optical model

Why the checker computes what it computes, and where each constant comes from.
If a number in the code disagrees with this document, the document wins — file a
bug against the code.

## 1. Measure ink, not boxes

Layout boxes are a fiction of the font file and the syntax. A `path` that spans
x∈[8,19] inside a `viewBox="0 0 24 24"` is *drawn* off-centre no matter what the
container does; `align-items: center` will faithfully centre the wrong thing.

So every geometric check starts from flattened polygons: cubic/quadratic curves
are sampled (`24` segments), `rect`/`circle`/`ellipse`/`polygon`/`polyline`/`line`
are converted to path data first, transforms are composed down the `<g>` tree,
and all measurements happen on the resulting point sets.

Two rules keep that pipeline from lying:

- **Non-rendering nodes are not ink.** `defs`, `clipPath`, `mask`, `symbol`,
  `pattern`, `marker`, `linearGradient`, `radialGradient`, `filter`, `style`,
  `title`, `desc`, `metadata` are skipped entirely, as are subtrees carrying
  `display:none` or `opacity:0`.
- **`visibility` is not `display`.** `visibility:hidden` hides a subtree but
  descendants may set `visibility:visible` and reappear, so the flag is carried
  down the tree and applied per shape instead of pruning the branch.
- **Presentation attributes live in `style` too.** `style="fill:none;stroke:…;
  stroke-width:2"` is merged over the XML attributes before anything is
  measured, so a stroke-only icon is not silently treated as an empty fill.

### What makes ink *unverifiable* rather than zero

A missing measurement is never zero. If the drawing cannot be resolved, the
report returns `geometry/no-ink` or `geometry/unresolved-graphics` with verdict
`unknown` (exit `2`) and emits no geometric numbers at all:

| Cause | Reported as |
|---|---|
| empty canvas, no shapes, all shapes `fill:none` without stroke | `geometry/no-ink` |
| `mask` or `filter` present | `geometry/unresolved-graphics` |
| `<text>`, `<image>`, `<foreignObject>`, `<video>`, `<canvas>`, `<switch>` | `geometry/unresolved-graphics` (`unsupported-ink:*`) — visible, but not geometry |
| a `clip-path` whose geometry is not a plain rect, or one that cuts the ink | `geometry/unresolved-graphics` |
| `<use>` pointing at a missing id, nested deeper than 3, or targeting a non-renderable node | `geometry/unresolved-graphics` |
| a `<use>` / nested `<svg>` sized in em, ch or viewport units | `geometry/unresolved-graphics` |
| a `transform` with a percentage or unit argument | `geometry/unresolved-graphics` (`unparsed-transform`) |
| a percentage `stroke-width` | `geometry/unresolved-graphics` (`stroke-width-percentage`) |
| a shape whose `d` failed to parse | `geometry/unresolved-graphics` |
| even-odd outlines that partially overlap | `geometry/unresolved-graphics` (`overlapping-subpaths`) |
| a computed centroid outside its own ink box | `geometry/unresolved-graphics` (`centroid-outside-ink`) |

`<use>` is resolved when the target exists: the referenced node is re-walked
with `x`/`y`, its `transform` and the target's `viewBox` folded into the matrix,
and `<symbol>` targets contribute their children (a symbol only renders when
instantiated).

### Clips

Icon exporters wrap the artwork in a clip the exact size of the canvas:

```svg
<defs><clipPath id="c"><rect x="0" y="0" width="16" height="16"/></clipPath></defs>
<g clip-path="url(#c)">…</g>
```

Refusing to measure that makes the checker blind on most real icon sets, but a
clip is not automatically a no-op either. The rule is therefore *resolve or
refuse*, never approximate:

| Clip | Behaviour |
|---|---|
| single `<rect>`, no `rx`/`ry`, `clipPathUnits="userSpaceOnUse"`, no transform | resolved to an AABB and tested for containment |
| the subtree's ink bbox fits inside that rect | the clip is a no-op; measurement proceeds |
| the subtree's ink escapes the rect | `clip-path-cuts-ink`, `unknown` — the remainder needs a boolean intersection |
| any other geometry (circles, paths, rounded rects, multiple children, `objectBoundingBox`) | `clip-path`, `unknown` |
| a shape clipping itself | `clip-path`, `unknown` — the container walk would drop the shape |

On a viewport-establishing element (`<use>` of a `<symbol>`, nested `<svg>`) the
clip's coordinate space is ambiguous — authored in the outer space or the inner
one? The checker resolves the clip in **both** readings and passes only when both
contain the ink, so an ambiguous clip can only produce a refusal, never a wrong
pass.

A `clip-path` on a shape that clips **itself** needs the intersection of two
outlines, so it is refused. A `clip-path` on a `transform`ed clip rect is refused
too: the rect would have to be rotated, and the containment test only knows about
axis-aligned boxes. Both are refusals, not approximations.

### Nested viewports

`viewBox` is a coordinate system, not a comment. A `<symbol viewBox>` or a
nested `<svg viewBox>` rescales everything below it, so measuring children in the
outer user space reports an offset that does not exist — a 10-unit glyph placed
in a 24-unit viewport reads as `10 × 10` ink centred at `(5,5)` instead of `(12,12)`,
i.e. a fictitious `−7px off` on both axes.

Both cases build the SVG 1.1 viewBox transform:

```
scale  = min(viewport.w / vb.w, viewport.h / vb.h)     // preserveAspectRatio: meet
offset = viewport.origin + (viewport.size − vb.size·scale)·align − vb.origin·scale
```

`preserveAspectRatio="none"` switches to independent `sx`/`sy`. A `<use>` of a
`<symbol>` gets a viewport of `(x, y, width ?? 100%, height ?? 100%)`; a nested
`<svg>` gets its own `x`/`y`/`width`/`height`. Percentages resolve against the
root viewBox; `em`/`ch`/viewport units cannot be resolved statically and become
`unknown` rather than `0`.

The nested viewport's **clip** is not modelled: ink drawn outside it is measured
as if visible. This only matters for artwork that overflows its own viewport,
which is a defect worth seeing.

A `transform` on the **root** `<svg>` is ignored on purpose. That transform
belongs to the host page's placement of the canvas, not to the artwork's
internal coordinate system, so letting it through would report a `104px` offset
for an icon that is perfectly centred.

`transform` parsing is strict: an argument that is not a plain number (`10%`,
`2em`, `var(--x)`) invalidates the *whole* list. Dropping the bad argument would
shift the rest left — `translate(10%,8)` would silently become `translate(8,0)`,
a wrong answer with no warning.

### Units

Measurements are taken in viewBox user units, but every reported `measured`,
`basis` and suggestion is in **rendered px**. The conversion comes from the root
element's `width`/`height`: `width="48"` on a 24-unit viewBox means each user
unit is 2px, so a 10-unit offset is reported as `20px`.

Without absolute `width`/`height` the icon is assumed to be **rendered at 24px
on its short side**, so a 480-unit canvas gets a scale of `0.05`. This is not
cosmetic: the tolerance curve clamps at 1.5px, so measuring a 480-unit glyph in
its own units applies a 0.3% threshold while a 24-unit glyph gets 2%. The same
optical error would be `off` on one canvas and `nudge` on the other, which makes
the verdict a property of the grid instead of the drawing. Normalising to a
nominal 24px removes that dependence — a 480-unit Font Awesome glyph and a
24-unit hand-drawn icon with the same 8% imbalance now reach the same verdict.

`meta.unitScale`, `meta.unitScaleX`/`unitScaleY` and `meta.unitSource` record
which conversion was used, and the evidence string appends
`[user units ×N = px]` (or `= 24px nominal`) whenever it is not 1.

`preserveAspectRatio="none"` stretches the axes independently, so there is no
single scale: x and y are converted separately, `meta.unitScale` is `null`, and
the tolerance basis is the smaller rendered dimension. `slice` uses the larger
ratio, `meet` the smaller.

### Fill rule

`fill-rule` is inherited and honoured. Under `nonzero`, same-winding subpaths
add (holes must be wound opposite). Under `evenodd`, winding is irrelevant: a
subpath nested an odd number of containment levels is a hole, two levels is
solid again. Icons routinely draw even-odd holes with the same winding as their
container, and treating those as additive flips both the area and the centroid.

Containment is classified per vertex: a subpath is *inside* another only when
none of its vertices fall outside, and vertices lying on the boundary are
ignored so an L-shaped icon whose hole shares a corner still measures correctly.
**Partially overlapping outlines are out of scope** — an even-odd XOR needs a
boolean polygon operation, so the checker reports `overlapping-subpaths` rather
than a centroid that may land outside the artwork.

## 2. `#1` ink bbox vs viewBox

```
dx = (ink.minX + ink.maxX)/2 − (viewBox.x + viewBox.w/2)
```

This is the single most common icon defect: a Figma export with asymmetric
padding. It is also the one an agent can never fix by adjusting a container,
which is why it is reported separately from `#2`.

Stroke-only shapes expand the box by `stroke-width/2`; joins and caps are not
modelled, so treat `±half-linewidth` as the accuracy of the bbox for stroke icons.

### Reading a suggestion

Every `suggested` object is `{kind, value}` and `kind` fixes what the number
means. The two geometric kinds move the ink in *opposite* directions, which is
why the kind is part of the contract rather than decoration:

| `kind` | `value` means | `measured.dx` relation |
|---|---|---|
| `viewBox-origin` | the correction sized in px; add `delta` to the origin | equal to `measured.dx` |
| `redraw` | how far to move the **visual mass inside the artwork** | `−measured.dx` |

```json
{ "kind": "viewBox-origin", "value": "-4px / 0px", "viewBox": "-4 0 24 24" }
```

Moving the origin by `d` moves the artwork by `−d`, so `viewBox-origin` equals
the measured offset itself. The `viewBox` string is the unambiguous form — an
agent that pastes it gets the centred result, whereas a signed number invites a
sign flip.

`value` is px, but the origin is in user units, so the two only line up on a
1:1 icon. On a 512-unit grid the same finding reads `value: "-0.57px"` with
`viewBox "-12.19 -12.19 512 512"`; adding `-0.57` to the origin would move the
artwork by half a unit and change nothing visible. Whenever the scale is not 1
the finding therefore also carries `delta`, the user-unit form that actually
goes into the attribute. `delta` is omitted when it would merely repeat `value`
— that is, on a 1:1 icon, or when the offset is already zero.

`redraw` is the `#2` case, and it is a different fix: **translating the artwork
cannot change a centroid offset**, because the centroid and the ink box move
together. The imbalance is in the mass distribution, so the shape has to change —
lengthen the opposite arm, thin the heavy side, or accept the offset as taste
(§3).

## 3. `#2` area centroid

Shoelace area and polygon centroid, summed over subpaths with the *signed* area
so holes subtract:

```
A  = ½ Σ (x_i·y_{i+1} − x_{i+1}·y_i)
Cx = 1/(6A) Σ (x_i + x_{i+1})(x_i·y_{i+1} − x_{i+1}·y_i)
```

Reference value used in the tests: triangle `(8,5) (8,19) (19,12)` → `A = 77`,
`Cx = 35/3 ≈ 11.667`, while its bbox centre is `13.5`, so `dx = −1.833px`.

### The damping constant `k` is taste, not physics

Design practice nudges a play glyph right by ~1px on a 24 grid. The pure
centroid says 1.833px. A common compromise is `k·dx` with `k∈[0.6,0.8]`; matching
the 1px habit implies `k≈0.55`.

Because that constant is a preference, it **never enters a verdict**. The
checker reports the raw geometric offset and puts a suggestion next to it. A
verdict built on `k` would be checking one convention with another convention.

## 4. `#3` keyline overshoot (heuristic)

Fill ratio `inkArea / viewBoxArea` is compared across a set in **linear** units
(`sqrt(ratio)`), because perceived size tracks linear extent, not area. An icon
whose linear size deviates more than `20%` from the set median is flagged, and
the delta is reported in px (`(linear − median) × size`).

Two refusals are built in, both learned from running the checker on a real icon
directory:

- **mixed families** — a stroke-only icon's fill ratio is dominated by its line
  width, so mixing it with solid glyphs produces a "norm" that describes
  neither. The set is reported `unknown` and must be split.
- **fewer than three icons** — two data points are not a norm.

Treat `nudge` here as "look at this", never as "this is broken".

## 5. `#4` `text-box` inside flex/grid

`text-box-trim` reached Baseline in August 2026 (Chrome 133+, Safari 18.2+,
Firefox 154+). Two implementation facts matter:

- trimming does not apply to flex or grid **containers**;
- Chromium does not trim inline boxes at all, while Firefox and Safari do.

A button label is almost always a flex child, so the declaration silently
no-ops in the exact place it is most needed.

### When the container type is known

Rules are merged **per selector**, not per selector-and-at-rule: `@media`,
`@supports` and `@layer` *add* declarations to a selector rather than replacing
it, so `display` in one block and `text-box` in another still describe the same
element. Keying the merge by context would turn that into "display was never
declared" and a silent pass.

Two escape hatches keep that merge honest:

| Situation | Verdict |
|---|---|
| `display: flex !important` | `off` — `!important` changes priority, not layout |
| `display: var(--d)` / `env()` | `unknown` — the value is not in this file |
| two contexts disagree about `display` | `unknown` — unless every branch is flexy (`flex` / `inline-flex`), which is a conflict in form but not in meaning: then `off` |
| `display` never declared but `text-box` is present | `unknown` |
| no `display` anywhere for that selector | `unknown` |

### What counts as a trim request

`text-box` is a shorthand for `text-box-trim` + `text-box-edge`, and omitted
components reset to their initial value. Two declarations that produce the same
property map mean opposite things:

```css
text-box: trim-both; text-box-trim: none;   /* no trimming */
text-box-trim: none; text-box: trim-both;   /* trimming */
```

So the checker replays declarations **in source order** rather than reading a
map, and:

- `text-box: normal` is the initial value (`trim: none`, `edge: auto`) — not a
  request to trim, even though it is not spelled `none`;
- `text-box: cap alphabetic` resets trimming to none, because the shorthand
  omits the trim component;
- only `trim-both` / `trim-start` / `trim-end` in either longhand or shorthand
  count as arming the check.

## 6. `#5` hard-coded vertical nudges (heuristic)

`margin-top: ±1..3px` or `translateY(±1..3px)` on a block that also carries text
metrics (`line-height` / `font-size` / `letter-spacing`) is the fossil of a
`text-box` workaround. It is reported so it can be replaced, but always as a
heuristic: the same declaration can be legitimate optical correction.

## 7. `#6` concentric radii

For uniformly inset surfaces the inner radius that keeps the curvature
continuous is

```
R_inner = R_outer − P
```

Three situations are handled explicitly:

| Case | Behaviour |
|---|---|
| uniform `p-*` | expected inner radius `R − P`, reported as `calc(Rpx - Ppx)` |
| unequal `px-*` / `py-*` | `unknown` — the correct radius is elliptical (`rx = R − Px`, `ry = R − Py`) and a single `calc()` would be wrong |
| `P ≥ R` | reported as an **outer radius defect**: the inner radius resolves to `0` and the outer curve is lost. The fix is a larger outer radius or less padding, not a negative `calc()` |

Only the JSX element tree closes the parent-child relation. CSS alone cannot, so
no finding is emitted for CSS input (`unknown` would be noise here — there is no
claim to make).

## 8. `#7` cap midpoint

Let `upem` be units per em, `asc`/`desc` the hhea ascender/descender, `cap` the
OS/2 `sCapHeight`, `S` the font size and `L` the line-height.

```
content height  C = (asc − desc)/upem · S
half-leading    H = (L·S − C)/2
baseline        B = H + asc/upem · S
cap top         T = B − cap/upem · S
line box centre M = L·S/2

delta = (T + B)/2 − M
      = S · (asc + desc − cap) / (2 · upem)
```

The `L` terms cancel: **the cap-midpoint offset is independent of line-height**.
That is why the check only needs four metrics and never needs to know the
computed line-height of the element. Negative means the letters look higher than
the box centre.

Only `.ttf`/`.otf` are parsed. WOFF2 requires table reconstruction; refusing it
is deliberate — a wrong `capHeight` yields a confidently wrong offset.

## 9. Tolerance curve

```
tol = clamp(0.02 × size, 0.5px, 1.5px)
```

- `0.02 × size` is a Weber-style relative floor: the same 1px error matters far
  more on a 16px icon than on a 120px hero glyph.
- The `0.5px` floor keeps sub-pixel noise from being reported as a defect.
- The `1.5px` ceiling stops large elements from earning a free pass.

Verdicts: `≤ tol` → `ok`, `≤ 3·tol` → `nudge`, beyond → `off`.
Heuristic-layer findings cap at `nudge`, so `off` is always backed by exact math.

Categorical findings — `no-ink`, `unresolved-graphics`, `text-box-in-flex`,
`unparsed-css`, and the keyline refusals — carry a *forced* verdict and never a
pixel number. They print as `—`, because inventing `+1px` for a rule that is not
about pixels invites an agent to "compensate" by one pixel.

`--policy` may only rescale comparisons that are actually pixel measurements.
Forced and categorical verdicts pass through untouched: a policy must not be
able to launder an unverifiable file into `ok`.

Exit codes: `0` ok/nudge, `1` off, `2` unknown, `64` usage error. When a report
contains both `off` and `unknown`, `off` wins the exit code — the fix is
mandatory either way, and the gap stays visible in every run's findings. The two
codes stay distinct so a broken project never looks like an unverifiable one.

## 10. Known limits

- No rendering. Font fallback, glyph hinting, sub-pixel positioning and
  `letter-spacing` accumulation are out of scope.
- Stroke joins, caps and dashes are approximated by a constant-width band.
- Tailwind variant prefixes (`md:`, `dark:hover:`, `supports-[…]:`) are stripped
  before matching, because `hidden md:flex` and `md:flex` describe the same
  container. The consequence is that a variant-qualified `flex` is treated as
  unconditional; at breakpoints where it does not apply, `text-box` may in fact
  work.
- Conflicting `text-box` declarations across `@layer`s are `unknown`: layer order
  decides the winner, and the order may live in another file.
- CSS is tokenised, not parsed. Unbalanced braces, unterminated strings and
  declaration-less preludes degrade to `unknown` rather than a best guess.
- `<use>` resolution is single-target and single-pass, capped at three levels
  of nesting. Targets without their own `viewBox` inherit the caller's user
  space; targets sized in relative units degrade to `unknown`.
- Nested `<svg>` viewports are transformed but not clipped (§1 "Nested
  viewports").
- Tailwind numeric scales are **v3's**. v4 derives every radius from
  `--radius-*`, so a themed project may disagree with `titleRadius()`. That is
  why non-concentric radius is `heuristic` and capped at `nudge`.
- JSX class names are read as *literal sets*: `clsx('flex', 'text-box-trim')`
  is understood. A conditional expression (`a ? 'flex' : 'block'`) describes
  two mutually exclusive worlds, so any finding it would produce is downgraded
  to `unknown`; a class name assembled entirely at runtime produces no finding
  at all. `{/* … */}` comments are skipped, fragments and `<React.Fragment>` are
  transparent in the element tree. A `text-box` utility with no layout-display
  utility beside it is `unknown` — the container type lives elsewhere.
- `--size` / `--line-height` belong to the `font` subcommand. Passing them to
  `check` is a usage error (exit `64`) rather than a silently ignored flag.
- Perceptual rules (Mach bands, dark-mode weight compensation) are never
  computed. They stay human judgement, marked `[不可校验]` in `SKILL.md`.

## 11. Running the tests

```bash
node --test "apple-ui-principles/scripts/optical/test/*.test.mjs"
```

Use the glob form: on some Node/Windows combinations `node --test <dir>` treats
the directory as a module path and fails with `MODULE_NOT_FOUND`.

Fixtures live in `test/fixtures` and come in three flavours:

| Kind | Purpose |
|---|---|
| symmetric icons | must report exactly `0`; any drift means the parser is broken |
| hand-computed shapes | must match the arithmetic in §3 to `< 0.01px` |
| false-positive traps | `text-box` on a flex *child*, `@layer` nesting, `}` inside a string |
