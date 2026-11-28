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
  never drew. `url(#g) red` carries a fallback colour and does paint. A reference
  to something that is **not** a paint server (`url(#someClipPath)`) is refused as
  `paint-server` rather than read as "nothing" — if the tag is one this pass has
  not heard of, guessing would delete ink silently, which is the one failure that
  costs a verdict.
- **A paint server that resolves to nothing also paints nothing.** Existence is
  not coverage: an empty `<pattern>` is a hole in the canvas, and a gradient with
  no stops — or whose stops all read `stop-opacity="0"` — puts down no colour.
  `<pattern>` with content, and a gradient with at least one visible stop, paint
  the shape's region as before (a pattern's internal geometry is not modelled, so
  its coverage is taken at the shape's own region). Stops reached through
  `href="#other"` are followed, because that is how export tools deduplicate them.
- **`vector-effect="non-scaling-stroke"` keeps its width — in px.** The band stays
  at the authored width while its path is scaled, so the area is computed from the
  path geometry at scale 1 — under `scale(4)` a 1-unit stroke on a 16-unit
  perimeter covers 64 units, not 256. The authored width is a **px** number, not a
  user-unit one: a 48px canvas over a 24-unit viewBox makes `stroke-width="2"` one
  user unit, so the width is divided by the root scale before it is used. Ignoring
  that doubled the band (402px² where Chrome draws 201) and pushed a stroked box
  outside its own canvas. Under `preserveAspectRatio="none"` the two axes carry
  different px-per-unit factors, so a single width cannot describe the band and
  the file is refused as `non-scaling-stroke-scale`. A `%` width has already been
  resolved through the viewport diagonal, so it is **not** divided again. A
  stylesheet may set the
  property too; the cascade carries `vector-effect` like any other paint property.
- **A paint value that does not parse is not a colour.** `fill`/`stroke` were
  asked one question — *is this the string `none`?* — and everything else became
  paint. CSS drops a declaration it cannot parse and the property keeps its
  initial value, which is **black for `fill` (still paint)** and **`none` for
  `stroke` (nothing at all)**. Six spellings of an invisible shape came back `ok`:
  `stroke="notacolor"`, `stroke="3"`, `fill-opacity="-1"`, `<g opacity="-1">`,
  `fill="inherit"` under `fill="none"`, and `fill:/* hidden */none` through a
  class. Opacity is clamped to `[0,1]` the way the spec says, the CSS-wide
  keywords are resolved against the parent, and comments are whitespace.
- **Anisotropic scaling multiplies area by |det|.** The band is `perimeter ×
  width`, and a linear map scales area by the determinant of the matrix. Pairing
  the already-stretched root-space perimeter with the mean of the two scales
  counted the scale twice: `scale(4,1)` on a 10-unit square with a 2-unit stroke
  reported `500` where `4 × (40 × 2)` is `320`. The box pads per axis
  (`r·hypot(a,c)` and `r·hypot(b,d)`), because the band is an ellipse there.
- **The ink box is made of ink.** A subpath that encloses nothing — a stray
  `M0 0`, a bare line — spans a bounding box and paints nothing. Unioning it into
  the box pulled a correct `4..20` square back to the origin: `off` by 2px, with a
  `viewBox="-2 -2 24 24"` suggestion that would have broken the icon. Only
  subpaths that enclose area contribute to a *filled* box; a stroked line is ink
  and still widens it. The stroke side had the same bug one layer down: its
  padding box was built from every point, so `M0 0 M4 4H20V20H4Z` with a 2-unit
  stroke still came back `(-1,-1)-(21,21)`. A subpath contributes to a *stroked*
  box only if it has a segment.
- **A zero-length segment is a cap, and the cap is not modelled.** `M12 12 L12 12`
  under `stroke-linecap="round"` is a 10×10 dot in Chrome (78.42 unit² for
  `stroke-width="10"`), while `perimeter × width` gives it 0. The same `<line>`
  with a butt cap draws nothing at all. Cap style is not read, so the two cases
  are separated by whether a cap is asked for, and the painted one is refused
  (`zero-length-stroke`) rather than called empty.
- **A prefixed tag is the same tag.** `xmlns:svg="…/svg"` makes `<svg:rect>` the
  same element as `<rect>`. Keeping the prefix missed the shape test, sent the
  node down the container branch, and deleted its geometry in silence: a
  400-unit rect measured as 16.
- **A clip in a rotated space is not a rectangle.** Transforming the clip rect's
  corners and taking their bounding box yields a *superset*, and a superset cannot
  cut anything — so the test concludes "the ink fits" for ink the render clips.
  Rotated and skewed spaces are refused instead.
- **A number that is not a number is not a measurement.** `scale(1e308)` overflows
  the coordinates; the shoelace sum is `NaN`, and `NaN > 0` is false, so the shape
  disappeared without a reason while the rest of the file reported `ok`.
- **Touching is not overlapping.** Two subpaths that share a region cannot be
  added (see §1); two that share only an edge or a corner — butted rectangles, a
  hole meeting its container at a corner — add up exactly and stay measurable.
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
| a `transform` that is not a bare-number list — a unit (`translate(2px,0)`, `rotate(45deg)`), a percentage, `var()`, an unknown function, wrong argument count, empty argument (`translate(10,)`), trailing junk, a trailing dot (`translate(6.,6.)`) | measured **untransformed**, with no finding — the engine drops the whole attribute, so the element sits in its parent's space. The parseable prefix is never applied: that would turn `translate(10%,8)` into `translate(8,0)`. A sign is a number (`+4`) and adjacent signed numbers are two of them (`6-6`, `.5.5`), both applied |
| a `stroke-width` in `%` with no declared viewBox and no absolute root sides | `geometry/unresolved-graphics` (`stroke-width-percentage`) — there is no real diagonal to take the percentage of; the nominal 24×24 canvas is a comparison convention, not a viewport. With a viewport, `10%` is 10% of the **nearest viewport's** normalised diagonal, expressed in that viewport's own user space (2.4 units on a 24-unit canvas). A nested `<svg viewBox="0 0 48 48">` uses 48, not the root's 24; reading the root turned a symmetric pair of bands into a 3px false `off`. A negative percentage is an invalid declaration — the width inherits, it is not a refusal |
| a `stroke-width` in `2pt` / `1em` / `1in` (`stroke-width-relative`), on the shape **or any ancestor** | `geometry/unresolved-graphics`. Absolute units are declined on purpose: `pt`, `pc`, `mm` and `in` would each need a px-per-unit constant, which is a second place to be wrong about the same number. `2px` is accepted — one px *is* one user unit. Write the others in user units |
| a `stroke-width` that overflows to infinity (`1e999`) | `geometry/unresolved-graphics` (`stroke-width-not-finite`) — one engine clamps it to the largest length and paints over the canvas, another drops the declaration |
| a `stroke-width` that is finite but whose band area is not (`1e308`) | `geometry/unresolved-graphics` (`non-finite-ink`) — `width × length` overflows to `Infinity` and the centroid comes back `NaN`; `NaN` compares false against every tolerance, so without this check the report reads `off` with a `NaN` displacement instead of admitting it has no measurement |
| a `d` the path parser rejects or only partially parses | `geometry/unresolved-graphics` (`unparsed-path`) — svgpath reports `M0 0 L` as "missed param" and still returns one point |
| a geometry length in `%`, `em`, `pt`… | `geometry/unresolved-graphics` (`unparsed-length`) — a percentage is relative to a viewport we cannot see, and `parseFloat("100%")` is `100` |
| a length or `viewBox` number the CSS lexer rejects — `width="16."`, `viewBox="0 0 0x18 0x18"` | `unresolved-length` / `invalid-viewBox`. A trailing dot is the number `16` followed by junk, so Chrome does not render the element; `Number("0x18")` answering `24` invented a canvas the browser does not have |
| an `<ellipse>` with neither `rx` nor `ry` | no ink, and no finding. `auto` copies the other radius; with neither there is nothing to copy, so the shape really is empty |
| a zero-length stroked segment that a cap turns into a dot (`M12 12 L12 12` with `stroke-linecap="round"`) | `geometry/unresolved-graphics` (`zero-length-stroke`) — the dot's area is the cap's, and cap style is not modelled. The same line with a butt cap draws nothing and is a genuine zero |
| a root `preserveAspectRatio="…slice"` whose crop cuts the ink | `geometry/unresolved-graphics` (`root-slice-clip`) — the model cannot clip a stroked path to a rect, and measuring the cropped-away ink reports a drawing that is not on screen. Ink that fits inside the visible strip is still measured |
| a non-scaling stroke under `preserveAspectRatio="none"` | `geometry/unresolved-graphics` (`non-scaling-stroke-scale`) — the two axes carry different px-per-unit factors, so no single band width describes the stroke |
| a `viewBox` attribute that is not four finite numbers with a positive size | `geometry/unresolved-graphics` (`invalid-viewBox`) — the element does not render, so there is no canvas to measure against |
| no `viewBox` and a relative `width`/`height` | `geometry/unresolved-graphics` (`relative-canvas`) — the canvas is whatever the host gives it |
| a root `width="0"` or `height="0"` | `geometry/unresolved-graphics` (`zero-canvas`) — SVG 1.1 §7.7: zero disables rendering |
| a root `width` / `height` that is negative or not finite (`width="-2"`, `width="1e999"`) | `geometry/unresolved-graphics` (`invalid-canvas`) — the declaration is invalid, so the browser renders at its default 100% and the px-per-unit factor is not in the file. Reading `-2` as a scale flipped the sign of every reported pixel |
| `<style>` rules this pass cannot evaluate (combinators, pseudo-classes, `@media`, geometry properties) | `geometry/unresolved-graphics` (`stylesheet-selector`, `stylesheet-conditional`, `stylesheet-geometry`) |
| `<style>` containing `@import` | `geometry/unresolved-graphics` (`stylesheet-unparsed`) — the imported sheet may paint any element, and it is not in the file |
| a matching rule that declares `animation` / `animation-name` (other than `none`) | `geometry/unresolved-graphics` (`css-animation`) — the paint comes from a `@keyframes` block this pass does not evaluate |
| `fill` / `stroke` set to `var()` or `env()` | `geometry/unresolved-graphics` (`runtime-paint`) — the value is defined outside the file |
| `fill` / `stroke` set to `url(#id)` where `#id` is not a paint server | `geometry/unresolved-graphics` (`paint-server`) — no engine paints it, but calling it "no ink" would delete real ink if the tag were one this pass has not heard of |
| `url(#id)` pointing at an **empty** `<pattern>`, or a gradient with no stops / only transparent stops | no ink. The element exists and covers no pixel — an empty pattern is a hole in the canvas, and a gradient whose stops all read `stop-opacity="0"` paints nothing. Stops inherited through `href` are followed |
| `fill="currentColor"` with a `color` the file sets to transparent | no ink. `currentColor` is a reference to the inherited `color`, not a colour: `color:transparent` (or `#0000`, or `rgba(0,0,0,0)`) makes the shape invisible. When `color` is absent from the file it is assumed opaque — stated in `SKILL.md` |
| `fill-rule` set to anything but `nonzero` / `evenodd` | the declaration is dropped, so the **inherited** rule applies — `<g fill-rule="evenodd"><path fill-rule="nonsense">` still subtracts its hole |
| `fill` / `stroke` whose value CSS cannot parse (`notacolor`, `3`, `3px`, `#12345`, `rgb(1,2`) | the declaration is dropped the way a browser drops it: `fill` keeps its initial **black and still paints**, `stroke` keeps its initial **`none` and paints nothing**. Reading the junk as paint put a 128-unit band on a blank canvas |
| `fill` / `stroke` set to `inherit` / `unset` / `revert` / `initial` | resolved, not measured as a string: the parent's computed value for the first three, `black` (`fill`) or `none` (`stroke`) for `initial` |
| `fill` / `stroke` with a colour function this pass does not model (`futurecolor(…)`) | `geometry/unresolved-graphics` (`unparsed-paint`) — it may paint or it may not |
| a CSS comment inside a declaration value (`fill:/* … */none`) | the value is `none`; comments are whitespace |
| `<style media="print">` — any medium other than `all` or `screen` | `geometry/unresolved-graphics` (`stylesheet-conditional`), and the sheet's declarations are **not** applied |
| `<?xml-stylesheet?>` pointing at an external sheet | `geometry/unresolved-graphics` (`external-stylesheet`) |
| animation that moves ink (`animateTransform`, `animateMotion`, `animate` on a geometry attribute, or on `fill`/`stroke`/an opacity reaching zero paint) | `geometry/unresolved-graphics` (`animated-ink`) — one frame is not the drawing |
| ink that leaves its viewport | `geometry/unresolved-graphics` (`ink-outside-viewport`) — the browser clips it |
| groups nested more than 200 deep | `geometry/unresolved-graphics` (`nesting-too-deep`) |
| two subpaths with the same outline | `geometry/unresolved-graphics` (`overlapping-subpaths`) — they cancel under even-odd and render once under nonzero, so the sum is wrong either way |
| two subpaths that share a region, under either fill rule | `geometry/unresolved-graphics` (`overlapping-subpaths`) — see §1 for why both windings are wrong, and why butted rectangles and corner-touching holes are not this |
| a `clip-path` reached through a rotated or skewed ancestor | `geometry/unresolved-graphics` (`clip-path`) — the bounding box of a rotated rect is a *superset* of the clip, so "the ink fits" would be answered yes for ink the render cuts away |
| a shape whose area is not finite (`scale(1e308)` overflowing the coordinates) | `geometry/unresolved-graphics` (`non-finite-ink`) — `NaN` is not `> 0`, so the shape used to vanish without a word while the rest of the file reported `ok` |
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
  have.
- `currentColor` is a **reference to the inherited `color`**, not a colour in its
  own right. When the file sets `color: transparent` — `<g color="transparent">`,
  `style="color:rgba(0,0,0,0)"`, or a `text-transparent` style class — the shape
  paints nothing, and treating `currentColor` as ink reported `ok` on a blank
  canvas. `color` is tracked in the inheritance chain and through `<style>`,
  including its own `!important` and specificity rules. When `color` is *not* in
  the file the pass assumes it is opaque: that is stated in `SKILL.md`, because
  from the outside it is indistinguishable from painted.

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

The attribute's keywords are **case-sensitive** and its grammar is
`[defer] <align> [<meetOrSlice>]` or `none` alone. Chrome drops
`xMidYMid SLICE`, `xmidymid slice` and `xMidYMid slice defer` wholesale and
renders the default `xMidYMid meet`. Lower-casing the value used to make the
model invent a 2× canvas scale for those files and report a centred icon as
`nudge`. `defer`, when legal, changes no geometry.

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

The **root** viewport clips too, and `preserveAspectRatio="…slice"` makes that
crop bite: `slice` scales by the larger of the two ratios so the viewBox covers
the viewport, then drops the overflow. In a 48×24 viewport over a 24-unit viewBox
only user `y ∈ [6,18]` is on screen, so three bands at `y` 0, 6 and 20 render as
one band 8px above centre — while a model that ignores the crop says "box centred,
mass 2.7px low". The crop can also manufacture a false `ok`: keep only the bands
outside the visible strip and every number describes ink that was never drawn. Ink
that fits inside the strip is measured normally; anything crossing it is refused
(`root-slice-clip`). Cropping a filled polygon to a rect is tractable, but a
*stroked* one is not expressible as `perimeter × width`, and clipping half the
file would be worse than saying so.

The root viewport clips under `meet` and `none` too — `meet` simply letterboxes,
so the visible user-space rect is *larger* than the viewBox. Ink beyond that rect
is refused as `ink-outside-viewport`. A `stroke-width="150%"` band used to be
counted out to 2016px² while Chrome drew only 1344px² inside the canvas, and the
report still said `ok`. The check only runs when the file declares both root
sides; an assumed 24px canvas is a comparison convention, not a viewport.

A flattened Bézier or a `perimeter × width` stroke box can overshoot an edge by
a few thousandths of a unit. That sliver is inside the same tolerance band used
for verdicts (`tol = clamp(0.02 × shortSide, 0.5px, 1.5px)`, converted back to
user units), so it is ignored here rather than reported as clipped ink. Without
that slack the check turned 115 real icons into `unknown`. Ink beyond the band
still refuses.

`overflow="visible"` is the one declaration that turns that clip off, and then
the escaping ink is measured as authored. `auto` and `scroll` still clip (they
add scrollbars), so only the literal `visible` opts out.

A `transform` on the **root** `<svg>` is ignored on purpose. That transform
belongs to the host page's placement of the canvas, not to the artwork's
internal coordinate system, so letting it through would report a `104px` offset
for an icon that is perfectly centred.

`transform` parsing is strict, and there is **one** failure mode, not two: a value
that is not a bare-number transform list is dropped by the engine, so the element
is measured in its untransformed space. That covers units (`translate(2px,0)`,
`rotate(45deg)`), percentages (`translate(10%,8)`), `var()` / `env()` / `calc()`,
an unknown function, trailing junk after the last `)`, the wrong argument count,
and an empty argument (`translate(10,)`). All six spellings were rasterised in
Chrome and none of them moved the element.

Two things follow. The parseable prefix must **not** be applied — splicing the bad
argument out would turn `translate(10%,8)` into `translate(8,0)` and
`translate(10 20)` into `translate(10 20, 0)`, which is a wrong position with no
warning. And the attribute is not the CSS property: `style="transform:rotate(45deg)"`
*is* valid CSS, and lands in the `stylesheet-geometry` refusal instead, because a
stylesheet can move ink in ways this pass does not evaluate.

What counts as a number is the **CSS** `<number-token>`, not SVG 1.1's `<number>`,
and the difference runs both ways. Accepting too little moved nothing that Chrome
moves: `translate(+4,+8)` is valid (the element really does move 4 right and 8
down), and adjacent signed numbers are two tokens, so `translate(6-6)` is
`(6,-6)` and `.5.5` is `(0.5,0.5)`. Accepting too much moved what Chrome leaves
alone: CSS has no trailing dot, so `translate(6.,6.)` is the number `6`, a stray
`.` and an invalid list — the whole attribute is dropped. The same lexer reads
every geometry length, `points` and `viewBox`, which is how `width="16."` (blank
canvas in Chrome) and `viewBox="0 0 0x18 0x18"` (where `Number()` would answer 24
for a canvas the browser does not have) stop being confident numbers.

One caveat worth recording: SVG 2 nominally types the `transform` attribute as a
CSS `<transform-list>`, where units are legal. This pass follows the engine it was
calibrated against (Chrome). On an engine that honours the SVG 2 reading, an
icon using `transform="rotate(45deg)"` turns where the report says it does not.

Commas *between* functions are still accepted (`translate(1,2), rotate(45)`): that
is the one CSS-ism the attribute grammar shares, and it is unambiguous.

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
four as another hole — `576 − 400 − 64` came back `112` where the render paints
`240`.

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

1. Outlines that overlap *within* one shape are refused, not summed — under both
   fill rules. `netShape` groups subpaths by the outline that contains them and
   compares siblings: a shared vertex is the figure-eight case, a shared edge is
   two butted rectangles, and neither is interference, but a genuine overlap is.
   Non-zero makes the two windings wrong in opposite directions. Two solids wound
   the same way paint their union once while the sum counts the overlap twice
   (`M2 2H14V14H2Z M8 8H20V20H8Z`: 252 painted, 288 summed). Two *holes* are
   worse: the overlap comes back to winding −1, so it is painted after all, and
   both holes had been subtracted in full. A 24-unit square with a 10×10 hole at
   `4,4` and another at `4.1,4.1` paints `572` at `(12.02, 12.02)`; the formula
   said `376` at `(13.57, 13.57)` — 35% of the area and 1.5 units of mass. This
   costs 3 of antd's 834 files, and one of them (`outlined/mail`) was `ok` on a
   23%-low area with a centroid 33 units off.
2. Overlap **between shapes**. Each `<path>` is measured on its own and the areas
   are added, so two opaque shapes painted over each other count twice while the
   render paints once. A three-shape shield logo where one path is the same
   silhouette split in two came out 190% over an independent scanline
   measurement. The error is in `ink.area` and, when the overlap is asymmetric,
   in the centroid; `geometry/ink-bbox` is unaffected. Catching it needs the same
   boolean machinery as case 1.
3. The stroke model — joins, caps and dashes are approximated as a swept band,
   `perimeter × width`, scaled by |det|. For a convex polygon with miter joins
   that is exact, not approximate: a 10-unit square with a 2-unit stroke is
   `40 × 2 = 80`, which is also the ring `12² − 8²`. It over-counts where the band
   overlaps *itself* — reflex corners, a shape thinner than its stroke, a spiral —
   and it ignores caps and dashes entirely. And a shape that is both filled and
   stroked counts the band over its own fill, so `fill="#000" stroke="#000"` on a
   16-unit square reports `384` where the union is `324`.

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

The declarations are normalised before matching, so the heuristic also sees
equivalent authoring forms: `margin: 2px 0 0` and `margin-block-start: 2px`,
trailing `!important`, case-insensitive units (`2PX`), and repeated transforms
(`translateY(1px) translateY(2px)` sums to `3px`). Multiple conflicting
declarations use the last one after normalisation, matching CSS cascade order.

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

Let `upem` be units per em, `asc`/`desc` the ascender/descender the text engine
actually uses, `cap` the OS/2 `sCapHeight`, `S` the font size and `L` the
line-height.

**`asc`/`desc` are not always `hhea`.** Chrome on Windows takes OS/2
`sTypoAscender`/`sTypoDescender` when `fsSelection` bit 7 (`USE_TYPO_METRICS`) is
set, and `usWinAscent`/`usWinDescent` otherwise. Calibri's hhea pair is
1536/−512, which predicts −2.109px at 32px; its win pair is 1950/550, predicting
+0.828px, and Chrome renders +0.844px — the sign was reversed. Arial Black and
Cascadia show the same rule; six other Windows fonts happened to have identical
hhea and win pairs, which is why only two fonts exposed the bug. The chosen pair
is reported as `metricSource` (`os2-typo` / `os2-win` / `hhea` when neither OS/2
pair is populated, as in generated test fonts). Values are Chrome-on-Windows
calibrated; other platforms may use another pair.

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
- A stroke on a **filled** shape is added to the fill rather than unioned with it,
  so the band's inside half is counted twice. On a concentric shape that cancels
  in the centroid and only inflates the area; on an off-centre band it pulls the
  reported mass toward the band — `rect` + a wide vertical stroke at its right
  edge reads 2.7px right of centre where the union is centred. Splitting a shape
  into fill and stroke is the fix, and it is deliberate: a boolean union is the
  one operation this pass does not have.
- `stroke-width` is only read when it is a bare number or `px`. Absolute units
  (`pt`, `pc`, `mm`, `cm`, `in`) are refused rather than converted: the px-per-unit
  constants are a second place to get the same number wrong, and real icon files
  write user units.
- A `clip-path` reached through a rotated or skewed ancestor is refused. The
  bounding box of the rotated rect is a superset of the clip, and using it would
  answer "the ink fits" for ink the render cuts away.
- Two subpaths that share a region inside one shape are refused rather than
  unioned. This costs coverage deliberately: 3 of antd's 834 files, one of which
  was `ok` on a 23%-low area.
- Conflicting Tailwind utilities in the same family are resolved by **scale
  order**, not by their order in `className`: Tailwind emits one rule per scale
  step, so `rounded-lg` wins over `rounded-md` and `p-4` over `p-2` whichever is
  written first. Chrome's computed `border-radius` is 8px for both class orders.
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
