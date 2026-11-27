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
// Tailwind v3 scale (rem * 4). v4 derives every value from `--radius-*` custom
// properties, so these numbers are wrong for a v4 project whose theme overrides
// them: `rounded-lg` is 8px here but whatever `--radius-lg` says there. The
// checker cannot see the theme, so a non-concentric-radius finding is advisory
// (`heuristic`, capped at `nudge`) rather than a hard failure.
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

/**
 * `text-box: normal` is the initial value, not a request to trim, and
 * `!important` does not change what the value means.
 */
function trimValue(raw) {
  if (!raw) return null;
  const value = raw.replace(/!\s*important\s*$/i, '').trim().toLowerCase();
  if (!value) return null;
  if (/^none\b/.test(value)) return null;
  if (value === 'normal') return null;
  if (value.startsWith('var(') || value.startsWith('env(')) return 'dynamic';
  return value;
}

/**
 * Resolve the effective trim state from declarations *in source order*.
 *
 * `text-box` is a shorthand for `text-box-trim` + `text-box-edge`, and the two
 * declarations below mean opposite things despite producing the same map:
 *
 *   text-box: trim-both; text-box-trim: none;   -> no trimming
 *   text-box-trim: none; text-box: trim-both;   -> trimming
 *
 * Omitted components in a shorthand reset to their initial value, so
 * `text-box: cap alphabetic` also turns trimming off.
 */
function effectiveTrim(order = []) {
  let state = null;
  for (const [prop, raw] of order) {
    if (prop === 'text-box-trim') {
      state = trimValue(raw);
      continue;
    }
    if (prop !== 'text-box') continue;
    const value = trimValue(raw);
    if (!value) {
      state = null;
    } else if (value === 'dynamic') {
      state = value;
    } else {
      const trimmed = /trim-(both|start|end)\b/.exec(value);
      // The shorthand only requests trimming when it names a trim value.
      state = trimmed ? value : null;
    }
  }
  return state;
}

/**
 * Rules are merged per selector, not per selector-and-at-rule: `@media` and
 * `@supports` add declarations to the base rule rather than replacing it, so
 * `display` in one block and `text-box` in another describe the same element.
 * When two contexts disagree about a property, the merge is not a fact and the
 * caller must answer `unknown`.
 */
function mergeBySelector(blocks) {
  const merged = new Map();
  for (const block of blocks) {
    const key = block.selector;
    let entry = merged.get(key);
    if (!entry) {
      entry = { selector: block.selector, decls: {}, order: [], seen: {}, conflicts: new Set() };
      merged.set(key, entry);
    }
    for (const [prop, value] of Object.entries(block.decls)) {
      if (prop in entry.decls && entry.decls[prop] !== value) entry.conflicts.add(prop);
      if (!(prop in entry.decls)) entry.seen[prop] = block.context;
      entry.decls[prop] = value;
    }
    entry.order.push(...(block.order || Object.entries(block.decls)));
  }
  return [...merged.values()];
}

/** `display: flex !important` still lays out as a flex container. */
function displayKind(raw) {
  if (!raw) return { kind: 'absent' };
  const value = raw.replace(/!\s*important\s*$/i, '').trim().toLowerCase();
  if (!value) return { kind: 'absent' };
  if (value.includes('var(') || value.includes('env(')) return { kind: 'dynamic' };
  return { kind: 'static', value };
}

function textBoxFindings(blocks) {
  const findings = [];
  for (const block of mergeBySelector(blocks)) {
    const trim = effectiveTrim(block.order);
    if (!trim) continue;
    const display = displayKind(block.decls.display);
    const where = block.selector;

    if (trim === 'dynamic') {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `${where} sets text-box through a var(); the resulting trim value is not in this file`,
        suggested: { kind: 'inspect', value: 'inline the token value and re-run' },
      });
      continue;
    }

    if (block.conflicts.has('display')) {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `${where} declares display differently in separate contexts; the container type depends on which applies`,
        suggested: { kind: 'inspect', value: 'check each @media/@supports branch separately' },
      });
      continue;
    }

    if (display.kind === 'dynamic') {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `${where} sets text-box but display comes from a var(); the container type is not in this file`,
        suggested: { kind: 'inspect', value: 'inline the display value and re-run' },
      });
      continue;
    }

    if (display.kind === 'absent') {
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `${where} sets text-box but no rule for this selector in this file declares display; the container type is not in this file`,
        suggested: { kind: 'inspect', value: 'check the parent container for display:flex/grid' },
      });
      continue;
    }

    if (FLEXY.test(display.value)) {
      const context = block.seen['text-box'] || block.seen.display || [];
      const inContext = context.length ? ` (declared in ${context.join(' > ')})` : '';
      findings.push({
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'off',
        pixel: false,
        evidence: `${where}: display:${display.value} + text-box:${trim}${inContext} — trimming has no effect on flex/grid containers`,
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
    // A sub-pixel nudge sits inside the tolerance band by definition; flagging it
    // would be noise. The documented window is 1px <= |nudge| <= 3px.
    if (!nudge || Math.abs(nudge) < 1 || Math.abs(nudge) > 3) continue;

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

/** Collect every string literal, including literals nested inside `${...}`. */
function extractLiterals(expr, out = []) {
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i];
    if (ch === '"' || ch === "'") {
      let j = i + 1;
      let s = '';
      while (j < expr.length && expr[j] !== ch) {
        if (expr[j] === '\\') {
          s += expr[j + 1] ?? '';
          j += 2;
          continue;
        }
        s += expr[j];
        j += 1;
      }
      out.push(s);
      i = j + 1;
      continue;
    }
    if (ch === '`') {
      let j = i + 1;
      let s = '';
      while (j < expr.length && expr[j] !== '`') {
        if (expr[j] === '\\') {
          s += expr[j + 1] ?? '';
          j += 2;
          continue;
        }
        if (expr[j] === '$' && expr[j + 1] === '{') {
          out.push(s);
          s = '';
          let depth = 1;
          let k = j + 2;
          while (k < expr.length && depth > 0) {
            if (expr[k] === '{') depth += 1;
            else if (expr[k] === '}') depth -= 1;
            k += 1;
          }
          extractLiterals(expr.slice(j + 2, k - 1), out);
          j = k;
          continue;
        }
        s += expr[j];
        j += 1;
      }
      out.push(s);
      i = j + 1;
      continue;
    }
    i += 1;
  }
  return out;
}

const STRIP_LITERALS = /'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`/g;
const CLASS_HELPERS = /\b(?:clsx|cn|classnames|classNames|twMerge|twJoin|cva)\b/g;

/**
 * Class tokens plus whether the set is conditional.
 *
 * Deciding ambiguity by blacklist is a losing game (`?:` then `&&` then `+`…),
 * so this works the other way round: strip everything that is provably static —
 * string literals, Tailwind arbitrary values, known class helpers, punctuation —
 * and if anything that looks like code remains, the set is conditional.
 */
export function classInfo(expr) {
  if (!expr) return { tokens: [], ambiguous: false };
  const tokens = extractLiterals(expr)
    .join(' ')
    .split(/\s+/)
    .map((t) => t.trim())
    // Tailwind's important modifier is `!flex` in v3 and `flex!` in v4. Neither
    // changes which declaration wins in a class list, only its priority, so the
    // prefix/suffix is not part of the token's identity.
    .map((t) => t.replace(/^!/, '').replace(/!$/, ''))
    .filter(Boolean);

  const interpolated = expr.includes('${');
  const residual = expr
    .replace(STRIP_LITERALS, ' ')
    .replace(/\[[^\]]*\]/g, ' ')
    .replace(CLASS_HELPERS, ' ')
    .replace(/[\s(),.[\]]/g, '');

  const ambiguous = interpolated || /[?&|+]|[\w$]/.test(residual);
  return { tokens, ambiguous };
}

/** Back-compat helper for callers that only need the token list. */
export function classNames(expr) {
  return classInfo(expr).tokens;
}

function nearestParent(stack) {
  for (let k = stack.length - 1; k >= 0; k -= 1) {
    if (!stack[k].fragment) return stack[k];
  }
  return null;
}

/** `<` only starts a tag when what follows looks like one. */
function isTagStart(text, lt) {
  const ch = text[lt + 1];
  if (ch === undefined) return false;
  if (!/[A-Za-z/!>]/.test(ch)) return false;
  // `a < b`, `1 < 2`, `'x' < y` — a comparison, not markup
  const prev = text[lt - 1];
  if (prev && /[\w$)\]'"]/.test(prev)) return false;
  return true;
}

function nextTagStart(text, from) {
  let i = from;
  for (;;) {
    const lt = text.indexOf('<', i);
    if (lt === -1) return -1;
    if (isTagStart(text, lt)) return lt;
    i = lt + 1;
  }
}

/** Expressions whose whole content cannot contain live JSX. */
function isOpaqueExpression(body) {
  const t = body.trim();
  return (
    t.startsWith('/*') ||
    t.startsWith('//') ||
    t.startsWith("'") ||
    t.startsWith('"') ||
    t.startsWith('`')
  );
}

export function parseJsx(text) {
  const elements = [];
  const stack = [];
  let i = 0;

  while (i < text.length) {
    const brace = text.indexOf('{', i);
    const lt = nextTagStart(text, i);

    // A text expression (`{'<div>'}`) or a comment never opens a tag.
    if (brace !== -1 && (lt === -1 || brace < lt)) {
      const balanced = readBalanced(text, brace, '{', '}');
      if (balanced && isOpaqueExpression(text.slice(brace + 1, balanced.end))) {
        i = balanced.end + 1;
        continue;
      }
    }
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

    // opening tag: find the '>' that is not inside an expression, a string or
    // a generic parameter list such as `<List<Item>>`
    let j = lt + 1;
    let braceDepth = 0;
    let angle = 0;
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
      else if (ch === '<' && braceDepth === 0) angle += 1;
      else if (ch === '>' && braceDepth === 0) {
        if (angle > 0) angle -= 1;
        else break;
      }
      j += 1;
    }
    if (j >= text.length) break;

    const raw = text.slice(lt + 1, j);
    const selfClosing = raw.trimEnd().endsWith('/');
    const body = selfClosing ? raw.trimEnd().slice(0, -1) : raw;
    const tagMatch = /^([A-Za-z][\w.:-]*)/.exec(body.trimStart());

    if (!tagMatch) {
      // fragment: transparent in the DOM tree, keep depth for pop bookkeeping
      if (!selfClosing) stack.push({ fragment: true });
      i = j + 1;
      continue;
    }

    const tag = tagMatch[1];
    const attrText = body.trimStart().slice(tag.length);
    const isFragmentTag = tag === 'React.Fragment' || tag === 'Fragment';
    const node = {
      tag,
      className: isFragmentTag ? null : extractClassName(attrText),
      parent: nearestParent(stack),
      fragment: isFragmentTag,
    };
    if (!isFragmentTag) elements.push(node);
    if (!selfClosing) stack.push(node);
    i = j + 1;
  }

  return elements;
}

function tailwindRadius(token) {
  if (!token.startsWith('rounded')) return null;
  const suffix = token.slice('rounded'.length);
  if (suffix === '') return RADIUS_SCALE[''];
  if (!suffix.startsWith('-')) return null;
  const key = suffix.slice(1);
  // `rounded-` (an interpolated class) and side-specific radii are not a
  // uniform corner radius.
  if (!key || key.includes('-')) return null;
  return key in RADIUS_SCALE ? RADIUS_SCALE[key] : null;
}

function tailwindPadding(token, axis = '') {
  const re = new RegExp(`^p${axis}-([\\w.]+)$`);
  const m = re.exec(token);
  if (!m) return null;
  return m[1] in PADDING_SCALE ? PADDING_SCALE[m[1]] : null;
}

/** Tailwind's layout-display utilities, used to tell "not a flex container" from "unknown". */
const DISPLAY_TOKEN = /^(block|inline|inline-block|flow-root|contents|hidden|table|table-row|table-cell|list-item)$/;

function firstRadius(tokens) {
  for (const token of tokens) {
    const value = tailwindRadius(token);
    if (value !== null) return value;
  }
  return undefined;
}

/** A conditional class list describes several worlds; never assert one of them. */
function degradeIfConditional(info, finding) {
  if (!info.ambiguous) return finding;
  return {
    ...finding,
    forcedVerdict: 'unknown',
    pixel: false,
    offset: 0,
    offsetY: 0,
    evidence: `${finding.evidence} — the class list is conditional, so the container type depends on runtime state`,
    suggested: { kind: 'inspect', value: 'make the class list static, or verify both branches' },
  };
}

export function checkTsx(text, { target = '<tsx>' } = {}) {
  const elements = parseJsx(text);
  const findings = [];

  for (const el of elements) {
    const info = classInfo(el.className);
    const hasBoxTrim = info.tokens.some(isBoxTrim);
    if (!hasBoxTrim) continue;
    const flexy = info.tokens.find((t) => FLEXY.test(t));
    if (flexy) {
      findings.push(
        degradeIfConditional(info, {
          id: 'rule/text-box-in-flex',
          layer: 'exact',
          forcedVerdict: 'off',
          pixel: false,
          evidence: `<${el.tag} className="${info.tokens.join(' ')}">: ${flexy} + text-box — trimming is a no-op inside a flex/grid container`,
          suggested: { kind: 'hoist', value: `move text-box to the text child of <${el.tag}>` },
        }),
      );
      continue;
    }
    // No layout-display utility at all: the container type lives outside this
    // element (parent, stylesheet, inline style), so it cannot be asserted.
    if (info.tokens.some((t) => DISPLAY_TOKEN.test(t))) continue;
    findings.push(
      degradeIfConditional(info, {
        id: 'rule/text-box-in-flex',
        layer: 'exact',
        forcedVerdict: 'unknown',
        pixel: false,
        evidence: `<${el.tag} className="${info.tokens.join(' ')}"> sets text-box but declares no display; the container type is not in this file`,
        suggested: { kind: 'inspect', value: 'check the element and its stylesheet for display:flex/grid' },
      }),
    );
  }

  for (const el of elements) {
    const info = classInfo(el.className);
    const outerRadius = firstRadius(info.tokens);
    if (outerRadius === undefined) continue;

    const uniform = info.tokens.map((t) => tailwindPadding(t)).find((p) => p !== null && p !== undefined);
    const padX = info.tokens.map((t) => tailwindPadding(t, 'x')).find((p) => p !== null && p !== undefined);
    const padY = info.tokens.map((t) => tailwindPadding(t, 'y')).find((p) => p !== null && p !== undefined);

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
      const childInfo = classInfo(child.className);
      const childRadius = firstRadius(childInfo.tokens);
      if (childRadius === undefined) continue;

      const conditional = info.ambiguous || childInfo.ambiguous;

      if (padding >= outerRadius) {
        findings.push(
          degradeIfConditional(
            conditional ? { ambiguous: true } : { ambiguous: false },
            {
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
            },
          ),
        );
        continue;
      }

      const expected = outerRadius - padding;
      const delta = childRadius - expected;
      if (Math.abs(delta) <= 0.5) continue;

      findings.push(
        degradeIfConditional(
          conditional ? { ambiguous: true } : { ambiguous: false },
          {
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
          },
        ),
      );
    }
  }

  return buildReport({
    target,
    mode: 'rule',
    findings,
    meta: { elements: elements.length },
  });
}
