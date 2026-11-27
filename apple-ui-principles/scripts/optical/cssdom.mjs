// A deliberately small CSS tokeniser.
//
// It is not a CSS parser and does not try to be. Its only contract is: return
// declaration blocks it is *certain* about, and refuse the rest. A checker that
// mis-splits a rule produces confidently wrong evidence, which is worse than
// having no checker at all — hence `unresolved` instead of best-effort guessing.

const GROUPING_AT_RULES = new Set([
  '@media',
  '@supports',
  '@layer',
  '@container',
  '@scope',
  '@document',
]);

class Unresolved extends Error {}

function skipString(src, i) {
  const quote = src[i];
  let j = i + 1;
  while (j < src.length) {
    if (src[j] === '\\') {
      j += 2;
      continue;
    }
    if (src[j] === quote) return j + 1;
    j += 1;
  }
  throw new Unresolved('unterminated string');
}

function skipComment(src, i) {
  const end = src.indexOf('*/', i + 2);
  if (end === -1) throw new Unresolved('unterminated comment');
  return end + 2;
}

/** Split a declaration body on semicolons that are not inside strings or parens. */
function splitDeclarations(body) {
  const out = [];
  let depth = 0;
  let start = 0;
  let i = 0;
  while (i < body.length) {
    const ch = body[i];
    if (ch === '/' && body[i + 1] === '*') {
      i = skipComment(body, i);
      continue;
    }
    if (ch === '"' || ch === "'") {
      i = skipString(body, i);
      continue;
    }
    if (ch === '(') depth += 1;
    else if (ch === ')') depth = Math.max(0, depth - 1);
    else if (ch === ';' && depth === 0) {
      out.push(body.slice(start, i));
      start = i + 1;
    }
    i += 1;
  }
  if (start < body.length) out.push(body.slice(start));
  return out;
}

function toDecls(chunk) {
  const colon = chunk.indexOf(':');
  if (colon === -1) return null;
  const prop = chunk.slice(0, colon).trim().toLowerCase();
  const value = chunk.slice(colon + 1).trim();
  if (!prop || !value) return null;
  if (!/^[-a-z][-a-z0-9]*$/.test(prop)) return null;
  return [prop, value];
}

/**
 * @param {string} src
 * @returns {{blocks: Array<{selector:string, decls:Record<string,string>, order:Array<[string,string]>, context:string[]}>, unresolved: string|null}}
 */
export function parseCss(src) {
  const blocks = [];
  try {
    walk(src, 0, src.length, [], blocks);
    return { blocks, unresolved: null };
  } catch (err) {
    if (err instanceof Unresolved) {
      return { blocks: [], unresolved: err.message };
    }
    throw err;
  }
}

function walk(src, from, to, context, blocks) {
  let i = from;
  while (i < to) {
    // skip whitespace and comments
    while (i < to && /\s/.test(src[i])) i += 1;
    if (i >= to) break;
    if (src[i] === '/' && src[i + 1] === '*') {
      i = skipComment(src, i);
      continue;
    }

    // read prelude up to '{' or ';'
    let start = i;
    let depth = 0;
    while (i < to) {
      const ch = src[i];
      if (ch === '/' && src[i + 1] === '*') {
        i = skipComment(src, i);
        continue;
      }
      if (ch === '"' || ch === "'") {
        i = skipString(src, i);
        continue;
      }
      if (ch === '(') depth += 1;
      else if (ch === ')') depth = Math.max(0, depth - 1);
      else if (depth === 0 && (ch === '{' || ch === ';' || ch === '}')) break;
      i += 1;
    }

    const prelude = src.slice(start, i).trim();
    if (i >= to) {
      if (prelude) throw new Unresolved(`dangling prelude: ${prelude.slice(0, 40)}`);
      break;
    }

    if (src[i] === ';') {
      // at-statement such as @import / @charset — nothing to check
      i += 1;
      continue;
    }

    if (src[i] === '}') {
      if (prelude) throw new Unresolved('declaration outside a block');
      return i;
    }

    // src[i] === '{'
    const close = findMatchingBrace(src, i, to);
    const inner = src.slice(i + 1, close);

    if (prelude.startsWith('@')) {
      const name = prelude.split(/\s+/)[0].toLowerCase();
      if (GROUPING_AT_RULES.has(name)) {
        walk(src, i + 1, close, [...context, prelude], blocks);
      }
      // other at-rules with bodies (@font-face, @keyframes) are irrelevant here
      i = close + 1;
      continue;
    }

    if (prelude) {
      const { decls, order, nested } = splitBlock(inner);
      const own = prelude.replace(/\s+/g, ' ');
      blocks.push({ selector: own, decls, order, context });
      for (const child of nested) emitNested(child, own, context, blocks);
    }

    i = close + 1;
  }
  return i;
}

/**
 * Flatten one nested entry into blocks.
 *
 * A nested selector (`& .child`) names a *different* element, so it keeps its
 * own selector. A nested at-rule names the *same* element under a condition, so
 * it inherits the parent selector and only extends the context — `@media` inside
 * `.btn` must not become a selector called `.btn @media …`.
 */
function emitNested(entry, parentSelector, context, blocks) {
  if (entry.selector.startsWith('@')) {
    const innerContext = [...context, entry.selector];
    blocks.push({
      selector: parentSelector,
      decls: entry.decls,
      order: entry.order,
      context: innerContext,
    });
    for (const child of entry.nested || []) emitNested(child, parentSelector, innerContext, blocks);
    return;
  }

  const merged = (
    entry.selector.includes('&')
      ? entry.selector.replace(/&/g, parentSelector)
      : `${parentSelector} ${entry.selector}`
  ).replace(/\s+/g, ' ');
  blocks.push({ selector: merged, decls: entry.decls, order: entry.order, context });
  for (const child of entry.nested || []) emitNested(child, merged, context, blocks);
}

function findMatchingBrace(src, openIndex, limit) {  let depth = 0;
  let i = openIndex;
  while (i < limit) {
    const ch = src[i];
    if (ch === '/' && src[i + 1] === '*') {
      i = skipComment(src, i);
      continue;
    }
    if (ch === '"' || ch === "'") {
      i = skipString(src, i);
      continue;
    }
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return i;
    }
    i += 1;
  }
  throw new Unresolved('unbalanced braces');
}

/** Separate own declarations from nested rules inside a single block body. */
function splitBlock(body) {
  const decls = {};
  // Source order is kept separately: `decls` is a map, so `text-box` followed by
  // `text-box-trim` and the reverse collapse to the same two keys with different
  // meanings. Shorthand/longhand resolution needs the sequence.
  const order = [];
  const nested = [];
  let cursor = 0;
  let i = 0;
  while (i < body.length) {
    const ch = body[i];
    if (ch === '/' && body[i + 1] === '*') {
      i = skipComment(body, i);
      continue;
    }
    if (ch === '"' || ch === "'") {
      i = skipString(body, i);
      continue;
    }
    if (ch === '{') {
      const close = findMatchingBrace(body, i, body.length);
      const chunk = body.slice(cursor, i);
      // CSS nesting puts declarations *before* a nested rule. Split at the last
      // semicolon so those declarations are not swallowed into the selector.
      const lastSemi = chunk.lastIndexOf(';');
      const declPart = lastSemi === -1 ? '' : chunk.slice(0, lastSemi + 1);
      const selector = (lastSemi === -1 ? chunk : chunk.slice(lastSemi + 1)).trim();
      for (const piece of splitDeclarations(declPart)) {
        const entry = toDecls(piece);
        if (entry) {
          decls[entry[0]] = entry[1];
          order.push(entry);
        }
      }
      if (selector) {
        const sub = splitBlock(body.slice(i + 1, close));
        nested.push({ selector, decls: sub.decls, order: sub.order, nested: sub.nested });
      }
      i = close + 1;
      cursor = i;
      continue;
    }
    i += 1;
  }
  const tail = body.slice(cursor);
  for (const chunk of splitDeclarations(tail)) {
    const entry = toDecls(chunk);
    if (entry) {
      decls[entry[0]] = entry[1];
      order.push(entry);
    }
  }
  return { decls, order, nested };
}
