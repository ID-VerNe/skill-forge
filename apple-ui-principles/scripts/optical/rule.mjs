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
    const where = block.context.length ? `${block.selector} (in ${block.context.join(' > ')})` : block.selector;

    if (!display) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        offset: 0,
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
        offset: 1,
        basis: 24,
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
          offset: 0,
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
// ---------------------------------------------------------------------------

function classTokens(raw) {
  if (!raw) return [];
  return raw
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function extractClassName(attrText) {
  const quoted = /className\s*=\s*"([^"]*)"/.exec(attrText);
  if (quoted) return quoted[1];
  const single = /className\s*=\s*'([^']*)'/.exec(attrText);
  if (single) return single[1];
  const template = /className\s*=\s*\{`([^`]*)`\}/.exec(attrText);
  if (template) return template[1];
  const braced = /className\s*=\s*\{'([^']*)'\}/.exec(attrText);
  if (braced) return braced[1];
  return null;
}

/**
 * Recover the element tree. Not a JSX parser: it only keeps tags that carry a
 * static className, which is all the checks need.
 */
export function parseJsx(text) {
  const elements = [];
  const stack = [];
  const tagRe = /<(\/?)([A-Za-z][\w.:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  let m = tagRe.exec(text);
  while (m) {
    const [, closing, tag, attrText, selfClosing] = m;
    if (closing) {
      stack.pop();
    } else {
      const className = extractClassName(attrText);
      const node = {
        tag,
        className,
        parent: stack.length ? stack[stack.length - 1] : null,
      };
      if (className) elements.push(node);
      if (!selfClosing) stack.push(node);
    }
    m = tagRe.exec(text);
  }
  return elements;
}

function tailwindRadius(token) {
  if (!token.startsWith('rounded')) return null;
  const suffix = token.slice('rounded'.length).replace(/^-/, '');
  const key = suffix.replace(/^-(?:t|r|b|l|s|e|tl|tr|br|bl)-/, '');
  if (suffix !== key) return null; // side-specific radii are out of scope
  if (!(key in RADIUS_SCALE)) return null;
  return RADIUS_SCALE[key];
}

function tailwindPadding(token) {
  const m = /^p-(.+)$/.exec(token);
  if (!m) return null;
  return m[1] in PADDING_SCALE ? PADDING_SCALE[m[1]] : null;
}

export function checkTsx(text, { target = '<tsx>' } = {}) {
  const elements = parseJsx(text);
  const findings = [];

  for (const el of elements) {
    const tokens = classTokens(el.className);
    const hasBoxTrim = tokens.some((t) => t === 'text-box' || t.startsWith('text-box-'));
    const flexy = tokens.find((t) => FLEXY.test(t));
    if (hasBoxTrim && flexy) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'off',
        offset: 1,
        basis: 24,
        evidence: `<${el.tag} className="${el.className}">: ${flexy} + text-box — trimming is a no-op inside a flex/grid container`,
        suggested: { kind: 'hoist', value: `move text-box to the text child of <${el.tag}>` },
      });
    }
  }

  for (const el of elements) {
    const tokens = classTokens(el.className);
    const outerRadius = tokens.map(tailwindRadius).find((r) => r !== null && r !== undefined);
    const padding = tokens.map(tailwindPadding).find((p) => p !== null && p !== undefined);
    if (outerRadius === undefined || padding === undefined) continue;

    for (const child of elements) {
      if (child.parent !== el) continue;
      const childRadius = classTokens(child.className)
        .map(tailwindRadius)
        .find((r) => r !== null && r !== undefined);
      if (childRadius === undefined) continue;

      const expected = Math.max(outerRadius - padding, 0);
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
          value:
            padding === 0
              ? `${px(outerRadius)}`
              : `calc(${px(outerRadius)} - ${px(padding)})`,
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
