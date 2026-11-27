// Rule-layer checks: #4 text-box inside a flex/grid container, #5 hard-coded
// vertical nudges, #6 non-concentric radii.
//
// The evidence rule from the plan applies throughout: a finding is only emitted
// when the input closes the loop by itself. Anything that would need the live
// DOM tree becomes `unknown` instead of a guess.

import { parseCss } from './cssdom.mjs';
import { buildReport } from './report.mjs';

export { parseCss };

const FLEXY = /^(inline-)?(flex|grid)$/;
const RADIUS_SCALE = {
  none: 0,
  sm: 2,
  '': 4,
  md: 6,
  lg: 8,
  xl: 12,
  '2xl': 16,
  '3xl': 24,
  '4xl': 32,
};
const PADDING_SCALE = {
  0: 0,
  '0.5': 2,
  1: 4,
  '1.5': 6,
  2: 8,
  '2.5': 10,
  3: 12,
  '3.5': 14,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
};

const px = (n) => `${Math.round(n * 100) / 100}px`;

/** `text-box` / `text-box-trim` actually trim. `text-box-edge-cap` does not. */
function isBoxTrim(token) {
  if (!token.includes('text-box')) return false;
  if (token === 'text-box') return true;
  return token.includes('trim');
}

function mergeBySelector(blocks) {
  const merged = new Map();
  for (const block of blocks) {
    const key = `${block.context.join('>')}||${block.selector}`;
    if (!merged.has(key)) {
      merged.set(key, {
        selector: block.selector,
        context: block.context,
        decls: { ...block.decls },
      });
    } else {
      Object.assign(merged.get(key).decls, block.decls);
    }
  }
  return [...merged.values()];
}

function textBoxFindings(blocks) {
  const findings = [];
  for (const block of mergeBySelector(blocks)) {
    const raw = block.decls['text-box'] ?? block.decls['text-box-trim'];
    if (!raw || /^none\b/i.test(raw.trim())) continue;
    const display = (block.decls.display || '').trim().toLowerCase();
    const where = block.context.length
      ? `${block.selector} (in ${block.context.join(' > ')})`
      : block.selector;

    if (!display) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `${where} sets text-box but never declares display; container context is not in this file`,
        suggested: { kind: 'inspect', value: 'check the parent container for display:flex/grid' },
      });
      continue;
    }

    if (FLEXY.test(display)) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'off',
        pixel: false,
        evidence: `${where}: display:${display} + text-box:${raw} — trimming has no effect on flex/grid containers`,
        suggested: {
          kind: 'hoist',
          value: `apply text-box on the inline child of ${block.selector}`,
        },
      });
    }
  }
  return findings;
}

function nudgeFindings(blocks) {
  const findings = [];
  for (const block of blocks) {
    const marginTop = (block.decls['margin-top'] || '').trim();
    let nudge = null;
    if (/^-?\d*\.?\d+px$/.test(marginTop)) {
      nudge = Number.parseFloat(marginTop);
    } else if (block.decls.transform) {
      const m = /translateY\(\s*(-?\d*\.?\d+)px\s*\)/.exec(block.decls.transform);
      if (m) nudge = Number.parseFloat(m[1]);
    }
    if (!nudge || Math.abs(nudge) > 3) continue;

    const isText = ['line-height', 'font-size', 'letter-spacing', 'font-family'].some(
      (prop) => block.decls[prop],
    );
    if (!isText) continue;

    const fontSize = Number.parseFloat(block.decls['font-size'] || '16') || 16;
    findings.push({
      id: 'rule/hardcoded-vertical-nudge',
      layer: 'heuristic',
      offset: nudge,
      basis: fontSize,
      evidence: `${block.selector}: ${nudge}px vertical nudge on text (line-height ${block.decls['line-height'] || 'inherited'})`,
      suggested: { kind: 'replace', value: 'text-box: trim-both cap alphabetic' },
    });
  }
  return findings;
}

export function checkCss(text, { target = '<css>' } = {}) {
  const { blocks, unresolved } = parseCss(text);
  if (unresolved) {
    return buildReport({
      target,
      mode: 'rule',
      findings: [
        {
          id: 'rule/unparsed-css',
          layer: 'exact',
          forcedVerdict: 'unknown',
          pixel: false,
          evidence: `cannot tokenise this stylesheet: ${unresolved}`,
          suggested: { kind: 'inspect', value: 'fix the syntax or pass the compiled output instead' },
        },
      ],
    });
  }

  return buildReport({
    target,
    mode: 'rule',
    findings: [...textBoxFindings(blocks), ...nudgeFindings(blocks)],
    meta: { blocks: blocks.length },
  });
}

// ---------------------------------------------------------------------------
// JSX / TSX
//
// A real JSX parser is out of scope, but a regex is not enough: attribute
// values may contain `=>`, nested objects and generic-looking angle brackets.
// The scanner below tracks brace depth and string state so those cases do not
// silently re-parent elements.
// ---------------------------------------------------------------------------

function readBalanced(text, start, open, close) {
  let depth = 0;
  let quote = null;
  let i = start;
  while (i < text.length) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') {
        i += 2;
        continue;
      }
      if (ch === quote) quote = null;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
      i += 1;
      continue;
    }
    if (ch === open) depth += 1;
    else if (ch === close) {
      depth -= 1;
      if (depth === 0) return { body: text.slice(start + 1, i), end: i };
    }
    i += 1;
  }
  return null;
}

function extractClassName(attrText) {
  const at = attrText.indexOf('className');
  if (at === -1) return null;
  let i = at + 'className'.length;
  while (i < attrText.length && /\s/.test(attrText[i])) i += 1;
  if (attrText[i] !== '=') return null;
  i += 1;
  while (i < attrText.length && /\s/.test(attrText[i])) i += 1;
  const ch = attrText[i];
  if (ch === '"' || ch === "'") {
    const end = attrText.indexOf(ch, i + 1);
    return end === -1 ? null : attrText.slice(i, end + 1);
  }
  if (ch === '{') {
    const balanced = readBalanced(attrText, i, '{', '}');
    return balanced ? attrText.slice(i, balanced.end + 1) : null;
  }
  return null;
}

/**
 * Pull class tokens out of a className expression. Static strings, template
 * literals and `clsx('a', 'b')` wrappers are all just quoted literals, so
 * extracting every literal covers the common dynamic forms without pretending
 * to evaluate them. Template interpolations are dropped.
 */
export function classNames(expr) {
  if (!expr) return [];
  const literals = [];
  const re = /"([^"]*)"|'([^']*)'|`([^`]*)`/g;
  let m = re.exec(expr);
  while (m) {
    const raw = m[1] ?? m[2] ?? m[3] ?? '';
    literals.push(raw.replace(/\$\{[^}]*\}/g, ' '));
    m = re.exec(expr);
  }
  return literals
    .join(' ')
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

export function parseJsx(text) {
  const elements = [];
  const stack = [];
  let i = 0;

  while (i < text.length) {
    const lt = text.indexOf('<', i);
    if (lt === -1) break;

    const next = text[lt + 1];
    if (next === '!') {
      const gt = text.indexOf('>', lt);
      i = gt === -1 ? text.length : gt + 1;
      continue;
    }
    if (next === '/') {
      const gt = text.indexOf('>', lt);
      if (gt === -1) break;
      stack.pop();
      i = gt + 1;
      continue;
    }

    // opening tag: find the '>' that is not inside an expression or a string
    let j = lt + 1;
    let braceDepth = 0;
    let quote = null;
    while (j < text.length) {
      const ch = text[j];
      if (quote) {
        if (ch === '\\') {
          j += 2;
          continue;
        }
        if (ch === quote) quote = null;
        j += 1;
        continue;
      }
      if (ch === '"' || ch === "'" || ch === '`') {
        quote = ch;
        j += 1;
        continue;
      }
      if (ch === '{') braceDepth += 1;
      else if (ch === '}') braceDepth = Math.max(0, braceDepth - 1);
      else if (ch === '>' && braceDepth === 0) break;
      j += 1;
    }
    if (j >= text.length) break;

    const raw = text.slice(lt + 1, j);
    const selfClosing = raw.trimEnd().endsWith('/');
    const body = selfClosing ? raw.trimEnd().slice(0, -1) : raw;
    const tagMatch = /^([A-Za-z][\w.:-]*)/.exec(body.trimStart());

    if (!tagMatch) {
      // fragment: keep depth for parent bookkeeping, emit nothing
      if (!selfClosing) stack.push({ tag: '<>', className: null, parent: stack.at(-1) ?? null });
      i = j + 1;
      continue;
    }

    const tag = tagMatch[1];
    const attrText = body.trimStart().slice(tag.length);
    const node = {
      tag,
      className: extractClassName(attrText),
      parent: stack.at(-1) ?? null,
    };
    elements.push(node);
    if (!selfClosing) stack.push(node);
    i = j + 1;
  }

  return elements;
}

function tailwindRadius(token) {
  if (!token.startsWith('rounded')) return null;
  const suffix = token.slice('rounded'.length);
  if (suffix !== '' && !suffix.startsWith('-')) return null;
  const key = suffix.replace(/^-/, '');
  if (key.includes('-')) return null; // side-specific radii are out of scope
  if (!(key in RADIUS_SCALE)) return null;
  return RADIUS_SCALE[key];
}

function tailwindPadding(token, axis = '') {
  const re = new RegExp(`^p${axis}-([\\w.]+)$`);
  const m = re.exec(token);
  if (!m) return null;
  return m[1] in PADDING_SCALE ? PADDING_SCALE[m[1]] : null;
}

function firstRadius(tokens) {
  for (const token of tokens) {
    const value = tailwindRadius(token);
    if (value !== null) return value;
  }
  return undefined;
}

export function checkTsx(text, { target = '<tsx>' } = {}) {
  const elements = parseJsx(text);
  const findings = [];

  for (const el of elements) {
    const tokens = classNames(el.className);
    const hasBoxTrim = tokens.some(isBoxTrim);
    const flexy = tokens.find((t) => FLEXY.test(t));
    if (hasBoxTrim && flexy) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'off',
        pixel: false,
        evidence: `<${el.tag} className="${tokens.join(' ')}">: ${flexy} + text-box — trimming is a no-op inside a flex/grid container`,
        suggested: { kind: 'hoist', value: `move text-box to the text child of <${el.tag}>` },
      });
    }
  }

  for (const el of elements) {
    const tokens = classNames(el.className);
    const outerRadius = firstRadius(tokens);
    if (outerRadius === undefined) continue;

    const uniform = tokens.map((t) => tailwindPadding(t)).find((p) => p !== null && p !== undefined);
    const padX = tokens.map((t) => tailwindPadding(t, 'x')).find((p) => p !== null && p !== undefined);
    const padY = tokens.map((t) => tailwindPadding(t, 'y')).find((p) => p !== null && p !== undefined);

    let padding;
    if (uniform !== undefined) {
      padding = uniform;
    } else if (padX !== undefined && padY !== undefined) {
      if (padX !== padY) {
        findings.push({
          id: 'rule/non-concentric-radius',
          layer: 'heuristic',
          forcedVerdict: 'unknown',
          pixel: false,
          evidence: `<${el.tag}> has unequal insets (padding-inline ${px(padX)}, padding-block ${px(padY)}); the concentric radius is elliptical and cannot be expressed as a single calc()`,
          suggested: { kind: 'inspect', value: `rx = ${px(outerRadius)} − ${px(padX)}, ry = ${px(outerRadius)} − ${px(padY)}` },
        });
        continue;
      }
      padding = padX;
    } else {
      continue;
    }

    for (const child of elements) {
      if (child.parent !== el) continue;
      const childRadius = firstRadius(classNames(child.className));
      if (childRadius === undefined) continue;

      if (padding >= outerRadius) {
        findings.push({
          id: 'rule/non-concentric-radius',
          layer: 'heuristic',
          forcedVerdict: 'nudge',
          radius: 'exceeds',
          pixel: false,
          evidence: `<${el.tag}> has ${px(outerRadius)} radius inside ${px(padding)} padding; the inner radius resolves to 0 and the outer curve is lost — the outer radius is too small for its padding`,
          suggested: {
            kind: 'outer-radius',
            value: `raise the outer radius above ${px(padding)} or reduce the padding`,
          },
        });
        continue;
      }

      const expected = outerRadius - padding;
      const delta = childRadius - expected;
      if (Math.abs(delta) <= 0.5) continue;

      findings.push({
        id: 'rule/non-concentric-radius',
        layer: 'heuristic',
        offset: delta,
        basis: Math.max(outerRadius, 1),
        evidence:
          `<${el.tag}> radius ${px(outerRadius)} with padding ${px(padding)} expects an inner radius of ` +
          `${px(expected)}, found ${px(childRadius)} on <${child.tag}>`,
        suggested: {
          kind: 'radius',
          value: `calc(${px(outerRadius)} - ${px(padding)})`,
        },
      });
    }
  }

  return buildReport({
    target,
    mode: 'rule',
    findings,
    meta: { elements: elements.length },
  });
}
