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
- **A stroke that draws nothing is not a hairline.** `stroke-width:0` and
  `stroke-opacity:0` both leave the canvas empty, so the band is not counted —
  a `Math.max(width, 0.0001)` floor would otherwise manufacture a few thousands
  of a pixel of ink and hand back `ok` for an empty drawing. A translucent
  stroke *is* ink: only the alpha changes, not the band. A negative width is an
  invalid declaration, which browsers drop, so the element inherits its parent's
  width instead of drawing in the opposite direction.
- **A broken paint server paints nothing.** `fill="url(#missing)"` is not "a
  colour we cannot read": SVG leaves the element unrendered. Counting it invented
  a region out of nothing, and every verdict built on it described ink the browser
  never drew. `url(#g) red` carries a fallback colour and does paint; a reference
  to a real gradient or pattern paints the same region, since only the colour
  changes and colour is not measured. A reference to something that is **not** a
  paint server (`url(#someClipPath)`) is refused as `paint-server` rather than
  read as "nothing" — if the tag is one this pass has not heard of, guessing
  would delete ink silently, which is the one failure that costs a verdict.
- **`vector-effect="non-scaling-stroke"` keeps its width.** The band stays at the
  authored width while its path is scaled, so the area is computed from the path
  geometry at scale 1 — under `scale(4)` a 1-unit stroke on a 16-unit perimeter
  covers 64 units, not 256.
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
| `mask` or `filter` present, as an attribute, in `style`, or through a class | `geometry/unresolved-graphics` — a class-based mask used to be dropped between the sheet and the node, which reported the unmasked shape as measurable |
| `marker`, `marker-start`, `marker-mid`, `marker-end` other than `none` | `geometry/unresolved-graphics` (`marker-end`) — a marker draws its own shape outside the path it decorates; arrowheads routinely stick out past the ink box |
| `<text>`, `<image>`, `<foreignObject>`, `<video>`, `<canvas>`, `<switch>` | `geometry/unresolved-graphics` (`unsupported-ink:*`) — visible, but not geometry |
| a `clip-path` whose geometry is not a plain rect, or one that cuts the ink | `geometry/unresolved-graphics` |
| `<use>` pointing at a missing id, nested deeper than 3, or targeting a non-renderable node | `geometry/unresolved-graphics` |
| a `<use>` / nested `<svg>` sized in em, ch or viewport units | `geometry/unresolved-graphics` |
| a `transform` with a percentage or unit argument, or with trailing junk | `geometry/unresolved-graphics` (`unparsed-transform`) |
| a percentage or relative `stroke-width`, on the shape **or any ancestor** | `geometry/unresolved-graphics` (`stroke-width-percentage`, `stroke-width-relative`) |
| a `stroke-width` that overflows to infinity (`1e999`) | `geometry/unresolved-graphics` (`stroke-width-not-finite`) — one engine clamps it to the largest length and paints over the canvas, another drops the declaration |
| a `stroke-width` that is finite but whose band area is not (`1e308`) | `geometry/unresolved-graphics` (`non-finite-ink`) — `width × length` overflows to `Infinity` and the centroid comes back `NaN`; `NaN` compares false against every tolerance, so without this check the report reads `off` with a `NaN` displacement instead of admitting it has no measurement |
| a `d` the path parser rejects or only partially parses | `geometry/unresolved-graphics` (`unparsed-path`) — svgpath reports `M0 0 L` as "missed param" and still returns one point |
| a geometry length in `%`, `em`, `pt`… | `geometry/unresolved-graphics` (`unparsed-length`) — a percentage is relative to a viewport we cannot see, and `parseFloat("100%")` is `100` |
| a `viewBox` attribute that is not four finite numbers with a positive size | `geometry/unresolved-graphics` (`invalid-viewBox`) — the element does not render, so there is no canvas to measure against |
| no `viewBox` and a relative `width`/`height` | `geometry/unresolved-graphics` (`relative-canvas`) — the canvas is whatever the host gives it |
| a root `width="0"` or `height="0"` | `geometry/unresolved-graphics` (`zero-canvas`) — SVG 1.1 §7.7: zero disables rendering |
| `<style>` rules this pass cannot evaluate (combinators, pseudo-classes, `@media`, geometry properties) | `geometry/unresolved-graphics` (`stylesheet-selector`, `stylesheet-conditional`, `stylesheet-geometry`) |
| `<style>` containing `@import` | `geometry/unresolved-graphics` (`stylesheet-unparsed`) — the imported sheet may paint any element, and it is not in the file |
| a matching rule that declares `animation` / `animation-name` (other than `none`) | `geometry/unresolved-graphics` (`css-animation`) — the paint comes from a `@keyframes` block this pass does not evaluate |
| `fill` / `stroke` set to `var()` or `env()` | `geometry/unresolved-graphics` (`runtime-paint`) — the value is defined outside the file |
| `fill` / `stroke` set to `url(#id)` where `#id` is not a paint server | `geometry/unresolved-graphics` (`paint-server`) — no engine paints it, but calling it "no ink" would delete real ink if the tag were one this pass has not heard of |
| `<?xml-stylesheet?>` pointing at an external sheet | `geometry/unresolved-graphics` (`external-stylesheet`) |
| animation that moves ink (`animateTransform`, `animateMotion`, `animate` on a geometry attribute, or on `fill`/`stroke`/an opacity reaching zero paint) | `geometry/unresolved-graphics` (`animated-ink`) — one frame is not the drawing |
| ink that leaves its viewport | `geometry/unresolved-graphics` (`ink-outside-viewport`) — the browser clips it |
| groups nested more than 200 deep | `geometry/unresolved-graphics` (`nesting-too-deep`) |
| two subpaths with the same outline | `geometry/unresolved-graphics` (`overlapping-subpaths`) — they cancel under even-odd and render once under nonzero, so the sum is wrong either way |
| even-odd outlines that partially overlap | `geometry/unresolved-graphics` (`overlapping-subpaths`) |
| a subpath that crosses itself over more than 0.1% of its own area | `geometry/unresolved-graphics` (`self-intersecting`) — the shoelace formula integrates the winding number, so a bowtie comes back zero while painting two triangles, and a pentagram comes back 40% too large. Smaller crossings are measured as if they were simple, and the error that introduces is bounded by the tolerance below |
| two **disjoint** lobes joined at one shared vertex and wound in opposite directions | `geometry/unresolved-graphics` (`self-intersecting`) — nothing crosses, so the test above stays quiet, yet shoelace subtracts one lobe from the other: `M12 12 L4 2 L2 12 L12 12 L16 8 L17 12 Z` measures 40 where the render paints 60. The outline is split at its repeated vertices; same-wound lobes add up, and opposite-wound lobes that overlap are subtracted by the renderer too, so both are measured normally |
| a computed centroid outside its own ink box | `geometry/unresolved-graphics` (`centroid-outside-ink`) |
| a file the CLI could not read or parse in a batch | `geometry/input-error` |
| an empty directory passed to keyline mode | `geometry/keyline-empty` |

`<use>` is resolved when the target exists: the referenced node is re-walked
with `x`/`y`, its `transform` and the target's `viewBox` folded into the matrix,
and `<symbol>` targets contribute their children *and their presentation
attributes* (a sprite set puts `fill`/`stroke`/`fill-rule` on the symbol).

### Internal stylesheets

Exported icons often paint through a class rather than a presentation attribute:

```html
<style>.cls-1{fill:none}</style>
<rect class="cls-1" width="18" height="18"/>
```

Ignoring that block does not leave the file ambiguous — it makes the checker
wrong, because the element it measures as a solid background is in fact
invisible. So `<style>` bodies are parsed and applied, in cascade order:

```
sheet normal  <  inline normal  <  sheet !important  <  inline !important
```

then specificity (`#id` > `.class` > `tag`) breaking ties before source order.
Importance belongs to a *declaration*, not to its block or its property name:
in `.bg{fill:none !important; stroke:#000}` only `fill` is important, so a later
`#bg{stroke:none}` still wins on `stroke`. Marking the whole block important
painted a background and turned a certain `off` into `ok`.

The same rule decides duplicates *within* one block. `fill:none !important;
fill:#000` resolves to `none`, because a normal declaration never displaces an
earlier important one. Collecting important flags in a per-property set made the
second declaration inherit the first one's flag, so both looked equally important
and the later one won — again painting a background the sheet had switched off.

The supported selector grammar is deliberately small: a compound of one tag,
one `#id` and any number of `.classes`, in any order, plus `*`, and comma lists
of those. Anything else — descendant combinators, `:hover`, `[attr=…]`, `@media`
— that would change a paint property becomes `unresolved`. A rule we might have
to apply and did not is exactly the case where a guess turns into a wrong
verdict.

Three things a stylesheet can say that are not measurements:

- `@import` pulls in a sheet that is not in the file. Every rule after it is a
  guess, so the whole `<style>` is refused rather than read as if the import
  were not there.
- `animation` / `animation-name` (anything but `none`) hands the paint to a
  `@keyframes` block this pass does not evaluate. The static declarations still
  look complete, which is how an animated icon used to come back `ok`.
- `fill: var(--x)` and `env()` name a value defined elsewhere. `transparent`,
  `#rrggbb00` and zero-alpha colours are the opposite case: they are declarations
  of *no* ink, and measuring them as solid invents a shape the render does not
  have. `currentColor` is fine — it paints, and only its hue is unknown, which
  never moves a centroid.

Two details that are easy to get wrong and were:

- Comments are stripped first. `<!-- <style>.a{fill:none}</style> -->` is
  documentation; scanning raw text made a commented-out rule paint.
- A stray `}` is a CSS parse error the browser consumes and recovers from.
  Returning there dropped every later rule silently, so the sheet lost rules and
  nothing said so.

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

Each of those elements resolves its clip in a different space, and two of the
three are not where the spec prose makes them look:

| Clip sits on | Resolved in | What that was measured with |
|---|---|---|
| a plain container (`<g>`, `<path>`, …) | that element's own user space | — |
| `<use>` | **after** the element's own `x`/`y` | `x="6"`, clip `0 0 12 12` → the whole 12×12 drawn; clip `6 6 12 12` → 6×6 drawn |
| nested `<svg>` | the space its `viewBox` establishes — the **inner** one | 5 clip units over a 10-unit viewBox scaled 2.4× → 12 px of ink, not 5 |
| `<symbol>` | the same inner space | identical to the nested `<svg>` above |

All four rows were rendered and measured in headless Chrome on one 24×24
drawing, not reasoned out: reading a nested `<svg>` clip in the outer space is
what the property's wording invites and it is wrong, which is why a symbol and
a nested `<svg>` of the same artwork used to disagree. The three tests in
`regression.test.mjs` that pin this down are cheaper than re-deriving it.

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
**nearest enclosing** viewport, not the root one — that is what a nested viewport
means. `em`/`ch`/viewport units cannot be resolved statically and become
`unknown` rather than `0`.

The viewport **clips** its content: `overflow: hidden` is the default for a
nested `<svg>` and for `<symbol>`. Ink that leaves the viewport is refused
(`ink-outside-viewport`) rather than measured as if visible, because the reported
offset would describe a drawing nobody can see. Under a rotated ancestor the
viewport rect is taken as its axis-aligned bounding box, which is a superset —
lenient, and stated here rather than hidden.

`overflow="visible"` is the one declaration that turns that clip off, and then
the escaping ink is measured as authored. `auto` and `scroll` still clip (they
add scrollbars), so only the literal `visible` opts out.

A `transform` on the **root** `<svg>` is ignored on purpose. That transform
belongs to the host page's placement of the canvas, not to the artwork's
internal coordinate system, so letting it through would report a `104px` offset
for an icon that is perfectly centred.

`transform` parsing is strict, and it separates two failures that look alike.
A `%` argument, `2em` or `var(--x)` names a value defined outside the file, so
the list is refused (`unparsed-transform`) rather than guessed: dropping the bad
argument would shift the rest left, and `translate(10%,8)` would silently become
`translate(8,0)`. Malformed syntax is a different answer — an unknown function,
trailing junk after the last `)`, or the wrong argument count. Browsers drop the
whole attribute there, so the element is measured in its untransformed space;
applying the parseable prefix instead put ink at `translate(10 20)` for an
attribute every engine ignores. Two notations are accepted because they are
unambiguous rather than because they are convenient: commas *between* functions,
as the CSS form writes them (`translate(1px,2px), rotate(45deg)`), and a `px`
suffix on a length — on an SVG element `transform-origin` is the origin, so
`1px` is one user unit and the number is the same either way.

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
ratio, `meet` the smaller. That holds on the assumed branch too — with no
`width`, each axis is given 24px rather than sharing one factor.

Absolute physical units are converted on the root, not ignored: `width="1in"` is
96px by definition, so it takes the declared branch instead of falling through to
the nominal 24px. A nested viewport sized in `in` is not converted; it goes
through the relative-length path and is refused.

### Fill rule

`fill-rule` is inherited and honoured, and the two rules are not the same
arithmetic.

**even-odd** ignores winding: a subpath nested an odd number of containment
levels is a hole, two levels is solid again. Icons routinely draw even-odd holes
with the same winding as their container, so anything that used the signed area
here would flip both the area and the centroid.

**nonzero** is decided per subpath, because winding only carries meaning
*inside* another outline. The winding number just outside a subpath is the sum of
its ancestors' directions; just inside it is that plus its own. A region is
painted where the winding is non-zero, so a subpath contributes its area exactly
when crossing its own boundary flips the paint on or off:

```
outer  = Σ sign(ancestor)              // accumulating, not just the parent
weight = fill(outer + sign(self)) − fill(outer)     // fill(w) = w ≠ 0 ? 1 : 0
```

| Nesting | Winding outside → inside | Contribution |
|---|---|---|
| no container | 0 → ±1 | `+|A|` — two disjoint regions each have winding 1, so an opposite direction is not a hole |
| two levels, opposite | +1 → 0 | `−|A|` — a hole |
| two levels, same | +1 → +2 | `0` — still paints, once |
| three levels, +then−then+ | +1 → 0 → +1 | `+|A|` — an island inside a hole inside an island paints |
| four levels, alternating | +1 → 0 → +1 → 0 | `−|A|` |

The last two rows are why the winding has to accumulate. Comparing each subpath
against its immediate parent gets two levels right and reports the island in row
four as another hole — `576 − 400 + 64` came back `112`.

Summing signed areas looks like it handles all of this and handles the disjoint
case wrong: `M0 0 H10 V10 H0 Z M20 0 V10 H30 V0 Z` — two squares, the second
drawn the other way — sums to **zero**, so the whole icon reads as "no ink".

Containment is classified per vertex: a subpath is *inside* another only when
none of its vertices fall outside and **at least one lands strictly inside**.
Vertices on the boundary are otherwise ignored, so an L-shaped icon whose hole
shares a corner still measures — but "no vertex outside" alone would also call a
notch sitting in a concavity a hole. A hole that meets its container only at a
corner leaves *every* vertex on the boundary: none outside, none strictly
inside, so the hole was painted as an extra island (`418` where the render paints
`382`). The area centroid is never a vertex, so when both vertex counts are zero
it is asked instead. Two subpaths with the same bounding box and
the same absolute area are treated as one outline drawn twice: under even-odd
they cancel to nothing, under nonzero they render once, and in both cases summing
them is wrong.

A subpath that crosses itself defeats the shoelace formula entirely — it
integrates the winding number, not the painted area, so a bowtie returns `0`
while painting two triangles and a pentagram returns 40% too much. The checker
sums the bounding boxes of the crossing segments as an upper bound on the
doubled region and refuses when that exceeds 0.1% of the subpath's own area.
Below that the outline is measured as if it were simple; the error it introduces
is smaller than the tolerance the verdict is judged against.

A related case slips past the crossing test: a figure-eight
(`M12 12 L4 2 L2 12 L12 12 L20 2 L22 12 Z`) is two loops joined at one vertex,
wound in opposite directions, so its area is exactly zero while both paint. The
outline is therefore split at its repeated vertices and the lobes compared.

Mixed winding alone does not make the total wrong, though, and treating it as if
it did cost two real icons. A **retraced edge** (`… V6 L0 0 L0 6 L6 0 Z`, or
antd's `file-zip` retracing its teeth) produces an opposite-wound lobe that sits
*inside* the outer one — that subtraction is exactly what non-zero fill does, so
the shoelace total agrees with the render and the icon must be measured. What
separates the two cases is whether the opposite-wound loops overlap: separate
blobs add in the render and cancel in the formula, nested or edge-sharing loops
do both. The same rule answers for even-odd, where the lobes were reported as
`40` ink worth `60` until the split was wired in there too.

The bar for "a lobe" is the **scene** area, not the shape's own. Flattening antd's
`twotone/eye` outline into polylines makes it revisit its own start 70 times, and
every lobe that comes out of the split is under `4e-11` on an 896-unit canvas:
that is rounding noise, not cancellation, and judging it against the subpath's own
area — which is also nearly zero — refused an icon that had been measurably
correct.

**What is still approximate.** Three things, and they are why `off` on
`geometry/centroid` deserves a second look at the artwork:

1. Partially overlapping outlines. An even-odd XOR needs a boolean polygon
   operation, so the checker reports `overlapping-subpaths` rather than a
   centroid that may land outside the artwork. Under `nonzero` a genuine overlap
   is still summed, which over-counts area.
2. Overlap **between shapes**. Each `<path>` is measured on its own and the areas
   are added, so two opaque shapes painted over each other count twice while the
   render paints once. A three-shape shield logo where one path is the same
   silhouette split in two came out 190% over an independent scanline
   measurement. The error is in `ink.area` and, when the overlap is asymmetric,
   in the centroid; `geometry/ink-bbox` is unaffected. Catching it needs the same
   boolean machinery as case 1.
3. The stroke model — joins, caps and dashes are approximated as a swept band.

None of these can move `geometry/ink-bbox`, which depends on extreme points only.

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

Shoelace area and polygon centroid per subpath, combined by the winding rule
above so holes subtract:

```
A  = ½ Σ (x_i·y_{i+1} − x_{i+1}·y_i)
Cx = 1/(6A) Σ (x_i + x_{i+1})(x_i·y_{i+1} − x_{i+1}·y_i)
```

Reference value used in the tests: triangle `(8,5) (8,19) (19,12)` → `A = 77`,
`Cx = 35/3 ≈ 11.667`, while its bbox centre is `13.5`, so `dx = −1.833px`.

A centroid offset is judged against the **smaller ink dimension**, not the
horizontal extent. A tall thin glyph and a wide flat one of equal mass are
equally sensitive to drift, and under `preserveAspectRatio="none"` the two axes
carry different px scales — measuring a vertical drift with the horizontal one
made a 0.55px sag read as `ok` on a stretched icon. (`#1` uses the viewBox short
side instead, because it asks a different question: how far the ink sits from
the *canvas* centre.)

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
- Nested `<svg>` viewports clip their content. Ink that escapes the viewport is
  detected and refused (`ink-outside-viewport`); the trimmed remainder is never
  computed (§1 "Nested viewports", "Clips").
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
