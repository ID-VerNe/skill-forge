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
]);

/** Properties that would move the ink; unsupported through CSS here. */
const GEOMETRY = new Set(['transform', 'translate', 'scale', 'rotate', 'd', 'x', 'y', 'width', 'height']);

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
    if (IMPORTANT.test(raw)) important.add(prop);
    decls[prop] = stripImportant(raw);
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

function matches(rule, node, classes) {
  const attrs = node.attrs || {};
  if (rule.id && attrs.id !== rule.id) return false;
  if (rule.tag && String(node.tag).toLowerCase() !== rule.tag) return false;
  return rule.classes.every((name) => classes.has(name));
}

function importantFlags(block) {
  const flags = new Set();
  for (const [prop, raw] of block.order) {
    if (IMPORTANT.test(String(raw))) flags.add(prop);
  }
  return flags;
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
      const important = importantFlags(block);
      const decls = [];
      for (const [prop, rawValue] of block.order) {
        if (GEOMETRY.has(prop)) {
          unresolved.add('stylesheet-geometry');
          continue;
        }
        if (!PAINT.has(prop)) continue;
        decls.push([prop, stripImportant(rawValue), important.has(prop)]);
      }
      if (decls.length === 0) continue;
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
      for (const c of compiled) rules.push({ ...c, decls, order: order++ });
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
    const inline = parseStyle(attrs.style);
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
