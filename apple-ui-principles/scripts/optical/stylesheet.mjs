// Internal stylesheets (`<style>` inside an SVG).
//
// Exported icons routinely paint through a class instead of a presentation
// attribute: `<style>.cls-1{fill:none}</style><rect class="cls-1" .../>`. Ignoring
// that block does not make the file ambiguous — it makes the checker *wrong*,
// because the element it measures as a solid background is in fact invisible.
//
// The scope is deliberately narrow: simple selectors only (tag, `.class`,
// `#id`, `*`, in any order, plus comma lists of those), no combinators, no
// pseudo-classes, no conditional at-rules. Anything else that would change paint
// becomes `unresolved` rather than a guess, which is the same contract the rest
// of the checker follows.

import { parseCss } from './cssdom.mjs';

/** Properties that decide what ink exists, where, and whether it is visible. */
const PAINT = new Set([
  'fill',
  'fill-rule',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-opacity',
  'display',
  'visibility',
  'opacity',
  'clip-path',
  // These do not have an attribute-only life: a class is the usual way to hang
  // a mask, a filter or a marker on a shape, and dropping the declaration here
  // made the element look unmasked — a confident `ok` on ink nobody can measure.
  'mask',
  'filter',
  // `marker` is the shorthand for all three; without it a class that sets
  // `marker: url(#arrow)` looked like a class that sets nothing.
  'marker',
  'marker-start',
  'marker-mid',
  'marker-end',
]);

/** Properties that would move the ink; unsupported through CSS here. */
const GEOMETRY = new Set(['transform', 'translate', 'scale', 'rotate', 'd', 'x', 'y', 'width', 'height']);

/**
 * Declarations that hand a property's value to something this module cannot
 * read — a running animation, or a custom property defined elsewhere. Both mean
 * "the paint at rest is not what the sheet says".
 */
const DEFERRED = new Set(['animation', 'animation-name']);

const IMPORTANT = /!\s*important\s*$/i;

const stripImportant = (value) => String(value).replace(IMPORTANT, '').trim();

/**
 * `style="fill:none;stroke:#000"` is presentation attributes by another name.
 *
 * Importance is kept per declaration: `style="fill:none!important"` has to beat
 * a stylesheet rule, while `style="fill:none"` does not. Treating the whole
 * attribute as one unit made the first case impossible to express and the second
 * case wrong.
 */
export function parseStyle(value) {
  const decls = {};
  const important = new Set();
  if (!value) return { decls, important };
  for (const part of String(value).split(';')) {
    const colon = part.indexOf(':');
    if (colon === -1) continue;
    const prop = part.slice(0, colon).trim().toLowerCase();
    const raw = part.slice(colon + 1).trim();
    if (!prop || !raw) continue;
    // Importance belongs to the declaration, not to the property name. In
    // `fill:none !important; fill:#000` the later normal declaration must lose,
    // and in `fill:#000; fill:#f00 !important` the earlier flag must not leak
    // forward. Track it per declaration and let the winner carry it.
    const isImportant = IMPORTANT.test(raw);
    if (important.has(prop) && !isImportant) continue;
    decls[prop] = stripImportant(raw);
    if (isImportant) important.add(prop);
    else important.delete(prop);
  }
  return { decls, important };
}

/**
 * Compile one compound selector, accepting `tag`, `#id`, `.class` and `*` in any
 * order. Returns `null` for anything this module will not evaluate — descendant
 * combinators, `:hover`, `[attr=…]`, `:nth-child()` — because a rule that might
 * match and is not applied is a silent wrong answer.
 */
function compound(token) {
  if (!token) return null;
  if (token === '*') return { tag: null, id: null, classes: [], spec: 0 };

  let rest = token;
  let id = null;
  let tag = null;
  let universal = false;
  const classes = [];
  while (rest.length > 0) {
    let m;
    if ((m = /^#([-\w]+)/.exec(rest))) {
      if (id) return null;
      id = m[1];
    } else if ((m = /^\.([-\w]+)/.exec(rest))) {
      classes.push(m[1]);
    } else if ((m = /^([A-Za-z_][-\w]*)/.exec(rest))) {
      if (tag || universal) return null;
      tag = m[1].toLowerCase();
    } else if (rest.startsWith('*')) {
      if (tag || universal) return null;
      universal = true;
      m = ['*'];
    } else {
      return null;
    }
    rest = rest.slice(m[0].length);
  }
  return { tag, id, classes, spec: (id ? 100 : 0) + classes.length * 10 + (tag ? 1 : 0) };
}

/**
 * A paint value that resolves at runtime.
 *
 * `fill: var(--x)` and `fill: env(...)` name a value defined somewhere this
 * module does not read, so the paint at rest is unknown. `currentColor` is fine:
 * whatever colour it resolves to, it paints, and the ink *area* does not depend
 * on which colour that is.
 */
const RUNTIME_PAINT = /^(var|env)\s*\(/i;

export function isRuntimePaint(value) {
  return RUNTIME_PAINT.test(String(value ?? '').trim());
}

/**
 * Paint that covers nothing.
 *
 * `fill="transparent"` is a real declaration of zero ink: the shape is there and
 * paints nothing. Measuring it as a solid region invents ink the render does not
 * have. `rgba(0,0,0,0)` and the 8-digit `#rrggbb00` form say the same thing.
 */
export function isInvisiblePaint(value) {
  const s = String(value ?? '').trim().toLowerCase();
  if (s === '') return false;
  if (s === 'transparent') return true;
  const functional = /^(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(\s*([^)]*)\)$/.exec(s);
  if (functional) {
    const [channels, slash] = functional[1].split('/');
    let alpha = slash === undefined ? null : slash.trim();
    if (alpha === null) {
      const parts = channels.split(',').map((p) => p.trim()).filter(Boolean);
      // Legacy comma syntax carries alpha as a fourth channel.
      if (parts.length >= 4) alpha = parts[3];
    }
    if (alpha === null || alpha === '') return false;
    const n = alpha.endsWith('%') ? Number(alpha.slice(0, -1)) / 100 : Number(alpha);
    return Number.isFinite(n) && n <= 0;
  }
  const hex = /^#([0-9a-f]{4}|[0-9a-f]{8})$/.exec(s);
  if (hex) {
    const digits = hex[1];
    const alpha = digits.length === 4 ? digits.slice(3) : digits.slice(6);
    return /^0+$/.test(alpha);
  }
  return false;
}

function matches(rule, node, classes) {
  const attrs = node.attrs || {};
  if (rule.id && attrs.id !== rule.id) return false;
  if (rule.tag && String(node.tag).toLowerCase() !== rule.tag) return false;
  return rule.classes.every((name) => classes.has(name));
}

/**
 * Reduce a block's declarations to one winner per property.
 *
 * Both halves matter: a later normal declaration must not displace an earlier
 * `!important` one, and an earlier normal one must not inherit a later flag.
 * Pushing every declaration into the candidate list and flagging them all by
 * property name got both backwards.
 */
function winningDecls(block) {
  const winners = new Map();
  for (const [prop, raw] of block.order) {
    const isImportant = IMPORTANT.test(String(raw));
    const previous = winners.get(prop);
    // Within a block an important declaration beats every normal one that
    // follows it; two importants resolve to the later of the two.
    if (previous && previous.important && !isImportant) continue;
    winners.set(prop, { value: stripImportant(raw), important: isImportant });
  }
  return winners;
}

/**
 * Apply internal stylesheets to a parsed tree.
 *
 * @param {Array<{css: string, type: string}>} sheets
 * @param {object} root parsed SVG root
 * @returns {{effective: Map<object, object>, unresolved: string[]}}
 *   `effective` maps each node to its cascaded attributes; nodes missing from
 *   the map keep their presentation attributes.
 */
export function cascade(sheets, root) {
  const unresolved = new Set();
  const rules = [];
  let order = 0;

  for (const sheet of sheets) {
    const type = String(sheet.type || 'text/css').toLowerCase();
    if (!type.includes('css')) {
      unresolved.add('stylesheet-type');
      continue;
    }
    const parsed = parseCss(sheet.css);
    if (parsed.unresolved) {
      // A mis-split rule is exactly the case where a guess becomes a wrong
      // verdict; refuse the whole sheet instead.
      unresolved.add('stylesheet-unparsed');
      continue;
    }
    for (const block of parsed.blocks) {
      const decls = [];
      let animates = false;
      for (const [prop, { value, important }] of winningDecls(block)) {
        if (DEFERRED.has(prop)) {
          // A CSS animation drives paint or geometry from a `@keyframes` block
          // this module deliberately does not evaluate. The static declarations
          // still look complete, which is exactly how an animated icon came back
          // `ok`. `animation: none` is the one value that leaves the element at
          // rest.
          if (!/^none$/i.test(String(value).trim())) animates = true;
          continue;
        }
        if (GEOMETRY.has(prop)) {
          unresolved.add('stylesheet-geometry');
          continue;
        }
        if (!PAINT.has(prop)) continue;
        decls.push([prop, value, important]);
      }
      // A block that only animates still has to reach the node: it decides that
      // the element has no resting state, even though it declares no paint.
      if (decls.length === 0 && !animates) continue;
      if ((block.context || []).length > 0) {
        // `@media` / `@supports` / `@layer` choose between paint sets at runtime.
        unresolved.add('stylesheet-conditional');
        continue;
      }
      const compiled = String(block.selector)
        .split(',')
        .map((part) => compound(part.trim()));
      if (compiled.some((c) => c === null)) {
        unresolved.add('stylesheet-selector');
        continue;
      }
      for (const c of compiled) rules.push({ ...c, decls, animates, order: order++ });
    }
  }

  const effective = new Map();
  // Iterative: nesting depth is the input's business, not the stack's.
  const stack = [root];
  while (stack.length > 0) {
    const node = stack.pop();
    const attrs = node.attrs || {};
    const classes = new Set(String(attrs.class || '').split(/\s+/).filter(Boolean));
    const matching = rules.filter((rule) => matches(rule, node, classes));

    // A CSS animation drives paint or geometry from a `@keyframes` block that
    // this module deliberately does not evaluate. The static declarations still
    // look complete, which is exactly how an animated icon used to come back
    // `ok`. `animation: none` is the one value that leaves the element at rest.
    const inline = parseStyle(attrs.style);
    const inlineAnimates = ['animation', 'animation-name'].some(
      (prop) => inline.decls[prop] !== undefined && !/^none$/i.test(inline.decls[prop]),
    );
    if (inlineAnimates || matching.some((rule) => rule.animates)) {
      unresolved.add('css-animation');
    }

    // One candidate list, sorted the way the cascade resolves it:
    // sheet normal < inline normal < sheet important < inline important,
    // then specificity, then source order. Inline style is *not* simply applied
    // last — a stylesheet `!important` outranks it.
    const candidates = [];
    for (const rule of matching) {
      for (const [prop, value, important] of rule.decls) {
        candidates.push({ prop, value, important, inline: 0, spec: rule.spec, order: rule.order });
      }
    }
    for (const [prop, value] of Object.entries(inline.decls)) {
      candidates.push({
        prop,
        value,
        important: inline.important.has(prop) ? 1 : 0,
        inline: 1,
        spec: 0,
        order: Number.MAX_SAFE_INTEGER,
      });
    }

    if (candidates.length > 0) {
      candidates.sort(
        (a, b) =>
          a.important - b.important || a.inline - b.inline || a.spec - b.spec || a.order - b.order,
      );
      const cascaded = {};
      for (const c of candidates) cascaded[c.prop] = c.value;
      // Presentation attributes lose to any stylesheet rule.
      effective.set(node, { ...attrs, ...cascaded });
    }
    for (const child of node.children || []) stack.push(child);
  }

  return { effective, unresolved: [...unresolved] };
}
