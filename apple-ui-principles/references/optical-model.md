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
  `display:none`, `visibility:hidden` or `opacity:0`.
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
| `clip-path`, `mask`, `filter` present | `geometry/unresolved-graphics` |
| `<use>` pointing at a missing id, nested deeper than 3, carrying `width`/`height`, or targeting a non-renderable node | `geometry/unresolved-graphics` |
| a shape whose `d` failed to parse | `geometry/unresolved-graphics` |
| even-odd outlines that partially overlap | `geometry/unresolved-graphics` (`overlapping-subpaths`) |
| a computed centroid outside its own ink box | `geometry/unresolved-graphics` (`centroid-outside-ink`) |

`<use>` is resolved when the target exists: the referenced node is re-walked
with `x`/`y` and its own `transform` folded into the matrix, and `<symbol>`
targets contribute their children (a symbol only renders when instantiated).
Anything more dynamic — a viewport, a nested sprite reference — is a gap, not a
guess.

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
no-ops in the exact place it is most needed. The checker only reports `off` when
the same declaration block (or same selector, same context) also declares
`display: flex|grid`. When `display` is absent, the parent is unknowable from
that file → `unknown`.

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
- CSS is tokenised, not parsed. Unbalanced braces, unterminated strings and
  declaration-less preludes degrade to `unknown` rather than a best guess.
- `<use>` resolution is single-target and single-pass; viewport-carrying or
  nested sprite references degrade to `unknown`.
- JSX class names are read as *literal sets*: `clsx('flex', 'text-box-trim')`
  is understood. A conditional expression (`a ? 'flex' : 'block'`) describes
  two mutually exclusive worlds, so any finding it would produce is downgraded
  to `unknown`; a class name assembled entirely at runtime produces no finding
  at all. `{/* … */}` comments are skipped, fragments and `<React.Fragment>` are
  transparent in the element tree.
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
