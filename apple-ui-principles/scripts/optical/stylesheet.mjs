// Internal stylesheets (`<style>` inside an SVG).
//
// Exported icons routinely paint through a class instead of a presentation
// attribute: `<style>.cls-1{fill:none}</style><rect class="cls-1" .../>`. Ignoring
// that block does not make the file ambiguous — it makes the checker *wrong*,
// because the element it measures as a solid background is in fact invisible.
//
// The scope is deliberately narrow: simple selectors only (tag, `.class`,
// `#id`, `*`, and comma lists of those), no combinators, no pseudo-classes, no
// conditional at-rules. Anything else that would change paint becomes
// `unresolved` rather than a guess, which is the same contract the rest of the
// checker follows.

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

/** `style="fill:none;stroke:#000"` is presentation attributes by another name. */
export function parseStyle(value) {
  if (!value) return {};
  const out = {};
  for (const part of String(value).split(';')) {
    const colon = part.indexOf(':');
    if (colon === -1) continue;
    const prop = part.slice(0, colon).trim().toLowerCase();
    const val = part.slice(colon + 1).trim();
    if (prop && val) out[prop] = val;
  }
  return out;
}

/**
 * Compile one compound selector. Returns `null` for anything this module will
 * not evaluate — descendant combinators, `:hover`, `[attr=…]`, `:nth-child()` —
 * because a rule that might match and is not applied is a silent wrong answer.
 */
function compound(token) {
  if (!token) return null;
  if (token === '*') return { tag: null, id: null, classes: [], spec: 0 };
  if (!/^[.#]?[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)*$/.test(token)) return null;

  const classes = [];
  let id = null;
  let tag = null;
  const re = /([.#]?)([A-Za-z_][\w-]*)/g;
  let m = re.exec(token);
  let cursor = 0;
  while (m) {
    if (m.index !== cursor) return null;
    cursor = re.lastIndex;
    if (m[1] === '.') classes.push(m[2]);
    else if (m[1] === '#') {
      if (id) return null;
      id = m[2];
    } else if (m[2] !== '*') {
      if (tag) return null;
      tag = m[2].toLowerCase();
    }
    m = re.exec(token);
  }
  if (cursor !== token.length) return null;
  return { tag, id, classes, spec: (id ? 100 : 0) + classes.length * 10 + (tag ? 1 : 0) };
}

function matches(rule, node, classes) {
  const attrs = node.attrs || {};
  if (rule.id && attrs.id !== rule.id) return false;
  if (rule.tag && String(node.tag).toLowerCase() !== rule.tag) return false;
  return rule.classes.every((name) => classes.has(name));
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
      let important = false;
      for (const [prop, rawValue] of block.order) {
        if (GEOMETRY.has(prop)) {
          unresolved.add('stylesheet-geometry');
          continue;
        }
        if (!PAINT.has(prop)) continue;
        const value = String(rawValue);
        if (/!\s*important\s*$/i.test(value)) important = true;
        decls.push([prop, value.replace(/!\s*important\s*$/i, '').trim()]);
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
      for (const c of compiled) rules.push({ ...c, decls, important, order: order++ });
    }
  }

  const effective = new Map();
  // Iterative: nesting depth is the input's business, not the stack's.
  const stack = [root];
  while (stack.length > 0) {
    const node = stack.pop();
    const attrs = node.attrs || {};
    const classes = new Set(String(attrs.class || '').split(/\s+/).filter(Boolean));
    // Sort ascending by cascade weight so the last write wins: normal before
    // important, then specificity, then source order.
    const matching = rules
      .filter((rule) => matches(rule, node, classes))
      .sort((a, b) => a.important - b.important || a.spec - b.spec || a.order - b.order);
    if (matching.length > 0) {
      const cascaded = {};
      for (const rule of matching) for (const [prop, value] of rule.decls) cascaded[prop] = value;
      // Presentation attributes lose to any stylesheet rule; inline `style`
      // beats both.
      effective.set(node, { ...attrs, ...cascaded, ...parseStyle(attrs.style) });
    }
    for (const child of node.children || []) stack.push(child);
  }

  return { effective, unresolved: [...unresolved] };
}
