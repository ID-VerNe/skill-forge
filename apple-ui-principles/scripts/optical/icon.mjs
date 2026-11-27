// Icon-layer checks: #1 ink bounding box, #2 area centroid, #3 keyline set.
//
// The model is deliberately literal: we measure ink, not layout boxes. A path
// that renders outside its own viewBox is a real defect and must not be
// normalised away.
//
// The governing rule is that a missing measurement is never a zero. If any part
// of the drawing cannot be resolved (clip paths, masks, dangling <use>, empty
// canvases), the report says `unknown` instead of producing a number.

import { readFile, readdir } from 'node:fs/promises';
import { basename, join } from 'node:path';
import {
  flattenPath,
  netShape,
  netShapeEvenOdd,
  bboxOfPoints,
  parseTransform,
  applyMatrix,
  multiplyMatrix,
  shapeToPath,
  parseLength,
  viewBoxMatrix,
  IDENTITY,
} from './geom.mjs';
import { buildReport, tolFor } from './report.mjs';
import { cascade, parseStyle } from './stylesheet.mjs';

const round = (n, d = 3) => Math.round(n * 10 ** d) / 10 ** d;
const SHAPES = new Set(['path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line']);
const NON_RENDERING = new Set([
  'defs',
  'clippath',
  'mask',
  'symbol',
  'pattern',
  'marker',
  'lineargradient',
  'radialgradient',
  'filter',
  'style',
  'title',
  'desc',
  'metadata',
]);
const UNRESOLVABLE = ['mask', 'filter'];
// Elements that paint, but not as geometry we can measure.
const UNMEASURABLE_INK = new Set([
  'text',
  'tspan',
  'textpath',
  'image',
  'foreignobject',
  'video',
  'canvas',
  'switch',
]);
const MAX_USE_DEPTH = 3;
/** Group nesting beyond this is a refusal, not a stack overflow. */
const MAX_NESTING = 200;

/** Minimal XML scanner: enough for icon markup, strict enough to fail loudly. */
function parseXml(text) {
  const root = { tag: '#root', attrs: {}, children: [] };
  const stack = [root];
  let i = 0;
  while (i < text.length) {
    const lt = text.indexOf('<', i);
    if (lt === -1) break;
    if (text.startsWith('<!--', lt)) {
      const end = text.indexOf('-->', lt + 4);
      i = end === -1 ? text.length : end + 3;
      continue;
    }
    if (text.startsWith('<![CDATA[', lt)) {
      const end = text.indexOf(']]>', lt + 9);
      i = end === -1 ? text.length : end + 3;
      continue;
    }
    if (text.startsWith('<?', lt) || text.startsWith('<!', lt)) {
      const end = text.indexOf('>', lt);
      i = end === -1 ? text.length : end + 1;
      continue;
    }
    const gt = text.indexOf('>', lt);
    if (gt === -1) break;
    const raw = text.slice(lt + 1, gt).trim();
    if (raw.startsWith('/')) {
      if (stack.length > 1) stack.pop();
      i = gt + 1;
      continue;
    }
    const selfClosing = raw.endsWith('/');
    const body = selfClosing ? raw.slice(0, -1).trim() : raw;
    const space = body.search(/[\s]/);
    const tag = (space === -1 ? body : body.slice(0, space)).toLowerCase();
    const attrText = space === -1 ? '' : body.slice(space);
    const attrs = {};
    const attrRe = /([\w:.-]+)\s*=\s*("([^"]*)"|'([^']*)')/g;
    let m = attrRe.exec(attrText);
    while (m) {
      attrs[m[1]] = m[3] !== undefined ? m[3] : m[4];
      m = attrRe.exec(attrText);
    }
    const node = { tag, attrs, children: [] };
    stack[stack.length - 1].children.push(node);
    if (!selfClosing) stack.push(node);
    i = gt + 1;
  }
  return root;
}

/**
 * Read a `viewBox`, or `null` when the attribute is present but unusable.
 *
 * Two failure modes used to hide here. `" 0 0 512 512"` is legal — the leading
 * space produces an empty first field under a naive split, the parse failed, and
 * the code quietly invented a 24x24 canvas, reporting a perfectly centred icon
 * as 1016% off. And when `viewBox` really is malformed the element does not
 * render at all, so falling back to any canvas is fiction. Absent is the only
 * case that gets a default, and then width/height describe the user space.
 */
function parseViewBox(attrs) {
  if (attrs.viewBox !== undefined) {
    const parts = String(attrs.viewBox)
      .trim()
      .split(/[\s,]+/)
      .filter(Boolean)
      .map(Number);
    if (parts.length === 4 && parts.every(Number.isFinite) && parts[2] > 0 && parts[3] > 0) {
      return { x: parts[0], y: parts[1], w: parts[2], h: parts[3] };
    }
    return null;
  }
  const w = absolutePx(attrs.width);
  const h = absolutePx(attrs.height);
  return { x: 0, y: 0, w: w !== null && w > 0 ? w : 24, h: h !== null && h > 0 ? h : 24 };
}

/**
 * Resolve a length against a percentage basis. Returns `null` when the unit is
 * relative to something we cannot see (em, ch, viewport units). `fallback` is
 * what an absent attribute means — 0 for x/y, the viewport size for width/height.
 */
function resolveLength(value, basis, fallback = basis) {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  const pct = /^(-?\d*\.?\d+)%$/.exec(text);
  if (pct) return (Number.parseFloat(pct[1]) / 100) * basis;
  if (/^-?\d*\.?\d+(px)?$/.test(text)) return Number.parseFloat(text);
  return null;
}

/**
 * Absolute length in px, or null when it depends on external context.
 *
 * `1in` is absolute — CSS pins it to 96px — so it must not fall through to the
 * "no size declared" branch, which would quietly assume a 24px render.
 */
const ABSOLUTE_UNITS = { px: 1, in: 96, cm: 96 / 2.54, mm: 96 / 25.4, pt: 96 / 72, pc: 16 };

function absolutePx(value) {
  if (value === undefined || value === null) return null;
  const m = /^\s*(-?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(px|in|cm|mm|pt|pc)?\s*$/i.exec(String(value));
  if (!m) return null;
  return Number.parseFloat(m[1]) * ABSOLUTE_UNITS[(m[2] || 'px').toLowerCase()];
}

/**
 * Attributes after cascade. `node.effective` is filled in once per document by
 * `applyStylesheets`; nodes outside that pass (a `<use>` clone) fall back to
 * their own presentation attributes plus inline style.
 */
function effectiveAttrs(node) {
  if (node.effective) return node.effective;
  return { ...node.attrs, ...parseStyle(node.attrs.style) };
}

function indexIds(node, map) {
  // Iterative: an exported file can nest thousands of groups, and a recursive
  // walk would blow the stack before any guard could run.
  const stack = [node];
  while (stack.length > 0) {
    const current = stack.pop();
    if (current.attrs && current.attrs.id) map.set(current.attrs.id, current);
    for (const child of current.children || []) stack.push(child);
  }
}

/** `<style>` bodies, with the attributes of the element that carried them. */
function extractSheets(text) {
  const out = [];
  const re = /<style\b([^>]*)>([\s\S]*?)<\/style\s*>/gi;
  const attrRe = /([\w:.-]+)\s*=\s*("([^"]*)"|'([^']*)')/g;
  let m = re.exec(text);
  while (m) {
    const attrs = {};
    let a = attrRe.exec(m[1]);
    while (a) {
      attrs[a[1].toLowerCase()] = a[3] !== undefined ? a[3] : a[4];
      a = attrRe.exec(m[1]);
    }
    attrRe.lastIndex = 0;
    out.push({ css: m[2], type: attrs.type || 'text/css' });
    m = re.exec(text);
  }
  return out;
}

function applyStylesheets(text, root, ctx) {
  const sheets = extractSheets(text);
  if (sheets.length === 0) return;
  const { effective, unresolved } = cascade(sheets, root);
  for (const id of unresolved) ctx.unresolved.add(id);
  for (const [node, attrs] of effective) node.effective = attrs;
}

function matrixFrom(attrs, base, ctx) {
  if (!attrs.transform) return base;
  const parsed = parseTransform(attrs.transform);
  if (!parsed) {
    ctx.unresolved.add('unparsed-transform');
    return base;
  }
  return multiplyMatrix(base, parsed);
}

/**
 * `fill-opacity` accepts a percentage as well as a number, so `parseFloat` reads
 * `50%` as fifty — fully opaque — instead of half. Only zero matters for area,
 * but a wrong opacity flips `filled` in both directions.
 */
function resolveOpacity(raw, fallback) {
  if (raw === undefined || raw === null) return fallback;
  const text = String(raw).trim();
  const pct = /^(-?\d*\.?\d+)%$/.exec(text);
  const value = pct ? Number(pct[1]) / 100 : parseLength(text);
  return value === null || !Number.isFinite(value) ? fallback : value;
}

function fillOpacityOf(attrs, inherited) {
  return resolveOpacity(attrs['fill-opacity'], inherited.fillOpacity ?? 1);
}

/**
 * `stroke-width` is in user units, or a percentage of the viewport diagonal —
 * which needs a rendered viewport we do not have. Refuse the percentage rather
 * than read "10%" as ten units. The same refusal has to apply on ancestors,
 * because `stroke-width` inherits: a `<g stroke-width="10%">` is exactly as
 * unknowable as a `<path stroke-width="10%">`.
 */
function strokeWidthOf(attrs, inherited, ctx) {
  if (attrs['stroke-width'] === undefined) return inherited.strokeWidth;
  const raw = String(attrs['stroke-width']).trim();
  if (/%$/.test(raw)) {
    ctx.unresolved.add('stroke-width-percentage');
    return inherited.strokeWidth;
  }
  const value = parseLength(raw);
  if (value === null) {
    ctx.unresolved.add('stroke-width-relative');
    return inherited.strokeWidth;
  }
  return value;
}

/** Presentation state a node hands to its children. */
function inheritedFor(attrs, inherited, visible, matrix, ctx) {
  return {
    matrix,
    fill: attrs.fill !== undefined ? attrs.fill : inherited.fill,
    stroke: attrs.stroke !== undefined ? attrs.stroke : inherited.stroke,
    strokeWidth: strokeWidthOf(attrs, inherited, ctx),
    fillRule: attrs['fill-rule'] || inherited.fillRule,
    // `fill-opacity` is inherited; `opacity` is not (it composites the group).
    fillOpacity: resolveOpacity(attrs['fill-opacity'], inherited.fillOpacity),
    visible,
    viewport: inherited.viewport,
    level: (inherited.level || 0) + 1,
  };
}

/**
 * Resolve `clip-path: url(#id)` to an axis-aligned rect in root user space, or
 * `null` when the clip is anything other than a plain rectangle. Rotations are
 * folded into an AABB, which is a superset of the clip — conservative in the
 * safe direction (it can only produce more refusals, never a wrong measurement).
 */
function resolveClipRect(raw, ctx, matrix) {
  const m = /^\s*url\(\s*#([^)\s]+)\s*\)\s*$/.exec(raw);
  if (!m) return null;
  const target = ctx.ids.get(m[1]);
  if (!target || String(target.tag).toLowerCase() !== 'clippath') return null;
  const targetAttrs = effectiveAttrs(target);
  if ((targetAttrs.clipPathUnits || 'userSpaceOnUse') !== 'userSpaceOnUse') return null;
  if (targetAttrs.transform) return null;

  const shapes = (target.children || []).filter((c) => c.tag !== '#comment');
  if (shapes.length !== 1) return null;
  const child = shapes[0];
  if (child.tag !== 'rect') return null;
  const a = effectiveAttrs(child);
  if (a.transform) return null;
  // A clip rect that is itself clipped is not the shape it claims to be.
  if (a['clip-path'] && !/^none$/i.test(a['clip-path'].trim())) return null;
  // A rounded clip removes ink at the corners, so it is not a no-op rectangle.
  const rx = a.rx === undefined ? 0 : parseLength(a.rx);
  const ry = a.ry === undefined ? 0 : parseLength(a.ry);
  if (rx === null || ry === null || rx !== 0 || ry !== 0) return null;

  // Percentages here are relative to the clipping element's viewport. Reading
  // `width="80%"` as 80 units produced both false offsets and false refusals —
  // resolve or refuse, never approximate.
  const x = a.x === undefined ? 0 : parseLength(a.x);
  const y = a.y === undefined ? 0 : parseLength(a.y);
  const w = a.width === undefined ? 0 : parseLength(a.width);
  const h = a.height === undefined ? 0 : parseLength(a.height);
  if (x === null || y === null || w === null || h === null) return null;
  if (!(w > 0) || !(h > 0)) return null;

  const corners = [
    applyMatrix(matrix, x, y),
    applyMatrix(matrix, x + w, y),
    applyMatrix(matrix, x + w, y + h),
    applyMatrix(matrix, x, y + h),
  ];
  const box = bboxOfPoints(corners);
  return box;
}

/** Union bbox of already-collected shape records, strokes included. */
function bboxOfShapes(shapes, steps) {
  let box = null;
  for (const shape of shapes) {
    const points = flattenPath(shape.d, steps)
      .flat()
      .map(([x, y]) => applyMatrix(shape.matrix, x, y));
    if (points.length === 0) continue;
    const localBox = bboxOfPoints(points);
    let pad = 0;
    // Under a non-uniform transform the stroke is elliptical; padding by the
    // larger axis keeps the containment test conservative.
    if (shape.stroked) pad = (shape.strokeWidth * maxScale(shape.matrix)) / 2;
    box = bboxUnion(box, bboxExpand(localBox, pad));
  }
  return box;
}

function rectContains(rect, box, eps = 1e-6) {
  return (
    box.minX >= rect.minX - eps &&
    box.minY >= rect.minY - eps &&
    box.maxX <= rect.maxX + eps &&
    box.maxY <= rect.maxY + eps
  );
}

function collect(node, inherited, out, ctx) {
  const tag = String(node.tag).toLowerCase();
  if (NON_RENDERING.has(tag)) return out;

  // Deeply nested groups are legal markup; recursing through thousands of them
  // is not. Refuse the file instead of letting V8 refuse it for us.
  if ((inherited.level || 0) > MAX_NESTING) {
    ctx.unresolved.add('nesting-too-deep');
    return out;
  }

  const attrs = effectiveAttrs(node);
  // `display:none` removes the subtree outright; `visibility:hidden` does not —
  // a descendant may set `visibility:visible` and reappear.
  if (attrs.display === 'none') return out;
  if (attrs.opacity !== undefined && Number.parseFloat(attrs.opacity) === 0) return out;

  const visible =
    attrs.visibility === undefined
      ? inherited.visible
      : attrs.visibility !== 'hidden' && attrs.visibility !== 'collapse';

  // Ink we can see but cannot measure. Silently treating these as empty would
  // report "the canvas has nothing in it", which is a different — and false —
  // statement.
  if (UNMEASURABLE_INK.has(tag)) {
    ctx.unresolved.add(`unsupported-ink:${tag}`);
    return out;
  }

  for (const attr of UNRESOLVABLE) {
    if (attrs[attr] && !/^none$/i.test(attrs[attr])) ctx.unresolved.add(attr);
  }

  // A root <svg> transform is not part of the artwork's coordinate system: the
  // outer canvas is whatever the host draws it into.
  const own = node === ctx.root ? inherited.matrix : matrixFrom(attrs, inherited.matrix, ctx);

  // --- a nested <svg> opens a viewport ------------------------------------
  if (tag === 'svg' && node !== ctx.root) {
    // Percentages resolve against the nearest enclosing viewport, not the root.
    const basisW = inherited.viewport.w;
    const basisH = inherited.viewport.h;
    const vpW = resolveLength(attrs.width, basisW);
    const vpH = resolveLength(attrs.height, basisH);
    const vx = resolveLength(attrs.x, basisW, 0);
    const vy = resolveLength(attrs.y, basisH, 0);
    if (vpW === null || vpH === null || vx === null || vy === null) {
      ctx.unresolved.add('viewport-relative-units');
      return out;
    }
    let matrix = multiplyMatrix(own, [1, 0, 0, 1, vx, vy]);
    if (attrs.viewBox !== undefined) {
      const vb = parseViewBox(attrs);
      if (!vb) {
        ctx.unresolved.add('invalid-viewBox');
        return out;
      }
      matrix = multiplyMatrix(
        matrix,
        viewBoxMatrix(vb, { x: 0, y: 0, w: vpW, h: vpH }, attrs.preserveAspectRatio),
      );
    }
    const local = inheritedFor(attrs, inherited, visible, matrix, ctx);
    local.viewport = { w: vpW, h: vpH };
    // The clip applies in the *inner* coordinate system, after the viewBox map.
    withClip(attrs, [own, matrix], ctx, out, (sink) => {
      for (const child of node.children || []) collect(child, local, sink, ctx);
    });
    return out;
  }

  // --- <use> instantiates its target ---------------------------------------
  if (tag === 'use') {
    const href = attrs.href || attrs['xlink:href'] || '';
    const id = href.startsWith('#') ? href.slice(1) : '';
    const target = id ? ctx.ids.get(id) : null;
    if (!target) {
      ctx.unresolved.add('use-without-target');
      return out;
    }
    if (ctx.depth >= MAX_USE_DEPTH) {
      ctx.unresolved.add('use-nested-too-deep');
      return out;
    }

    const x = resolveLength(attrs.x, inherited.viewport.w, 0);
    const y = resolveLength(attrs.y, inherited.viewport.h, 0);
    if (x === null || y === null) {
      ctx.unresolved.add('use-relative-units');
      return out;
    }
    // `transform` wraps the element; x/y translate its own coordinate system.
    const useMatrix = multiplyMatrix(own, [1, 0, 0, 1, x, y]);
    const targetTag = String(target.tag).toLowerCase();

    // width/height on a <use> only mean anything for viewport-establishing targets.
    if (targetTag !== 'symbol' && targetTag !== 'svg' && (attrs.width !== undefined || attrs.height !== undefined)) {
      ctx.unresolved.add('use-viewport-ignored');
    }

    const inner = { ...ctx, depth: ctx.depth + 1 };
    const local = inheritedFor(attrs, inherited, visible, useMatrix, ctx);

    withClip(attrs, [useMatrix], ctx, out, (sink) => {
      if (targetTag === 'symbol') {
        // <symbol> is non-rendering on its own but renders when instantiated.
        const vpW = resolveLength(attrs.width, inherited.viewport.w);
        const vpH = resolveLength(attrs.height, inherited.viewport.h);
        if (vpW === null || vpH === null) {
          ctx.unresolved.add('use-viewport');
          return;
        }
        const symbolAttrs = effectiveAttrs(target);
        if (symbolAttrs.display === 'none' || resolveOpacity(symbolAttrs.opacity, 1) === 0) return;
        // A symbol carries presentation attributes of its own — sprite sets put
        // `fill`, `stroke` and `fill-rule` there precisely so the children can
        // omit them. Dropping them changed the area of every referenced path.
        const symbolLocal = inheritedFor(symbolAttrs, local, visible, useMatrix, ctx);
        let matrix = matrixFrom(symbolAttrs, useMatrix, ctx);
        if (symbolAttrs.viewBox !== undefined) {
          const vb = parseViewBox(symbolAttrs);
          if (!vb) {
            ctx.unresolved.add('invalid-viewBox');
            return;
          }
          matrix = multiplyMatrix(
            matrix,
            viewBoxMatrix(vb, { x: 0, y: 0, w: vpW, h: vpH }, symbolAttrs.preserveAspectRatio),
          );
        }
        symbolLocal.matrix = matrix;
        symbolLocal.viewport = { w: vpW, h: vpH };
        for (const child of target.children || []) collect(child, symbolLocal, sink, inner);
        return;
      }
      if (targetTag === 'svg') {
        // Let the nested-viewport branch apply the viewBox exactly once. The
        // <use> width/height override the target's own, and x/y are already in
        // `useMatrix`, so the clone is placed at the origin.
        const overrides = { ...effectiveAttrs(target), x: '0', y: '0' };
        if (attrs.width !== undefined) overrides.width = attrs.width;
        if (attrs.height !== undefined) overrides.height = attrs.height;
        // The clone must not carry the target's cached cascade: its attributes
        // are already flattened into `overrides`, and the cache would win.
        collect({ ...target, attrs: overrides, effective: undefined }, local, sink, inner);
        return;
      }
      if (NON_RENDERING.has(targetTag)) {
        ctx.unresolved.add('use-target-not-renderable');
        return;
      }
      collect(target, local, sink, inner);
    });
    return out;
  }

  // --- a shape is ink ------------------------------------------------------
  if (SHAPES.has(tag)) {
    if (visible) {
      if (attrs['clip-path'] && !/^none$/i.test(attrs['clip-path'].trim())) {
        // Clipping a shape to itself needs the intersection of two outlines.
        ctx.unresolved.add('clip-path');
        return out;
      }
      const shape = tag === 'path' ? { d: attrs.d || '', unparsed: false } : shapeToPath(tag, attrs);
      if (shape.unparsed) {
        // A percentage geometry is not a shape at the origin — it is a shape we
        // cannot place. Dropping it silently would shrink the ink box.
        ctx.unresolved.add('unparsed-length');
      } else if (!shape.d && !shape.empty) {
        ctx.unresolved.add('unparsed-shape');
      } else if (shape.d) {
        const strokeWidth = strokeWidthOf(attrs, inherited, ctx);
        out.push({
          d: shape.d,
          matrix: own,
          filled: (attrs.fill ?? inherited.fill) !== 'none' && (fillOpacityOf(attrs, inherited) !== 0),
          stroked: (attrs.stroke ?? inherited.stroke) !== undefined && (attrs.stroke ?? inherited.stroke) !== 'none',
          strokeWidth: Number.isFinite(strokeWidth) ? strokeWidth : 1,
          // Even `fill-rule` is inherited, and an inherited `evenodd` changes the
          // area of every child path.
          fillRule: (attrs['fill-rule'] || inherited.fillRule || 'nonzero').toLowerCase(),
        });
      }
    }
    return out;
  }

  // --- anything else with children is a container --------------------------
  const bound = inheritedFor(attrs, inherited, visible, own, ctx);
  withClip(attrs, [own], ctx, out, (sink) => {
    for (const child of node.children || []) collect(child, bound, sink, ctx);
  });
  return out;
}

/**
 * Resolve `clip-path` when it provably does not remove any ink.
 *
 * Icon exporters wrap everything in a clip the exact size of the canvas, so
 * refusing every clip makes the checker blind on most real icon sets. A clip
 * that would actually cut the drawing still becomes `unknown`: the remainder
 * needs a boolean intersection of arbitrary outlines.
 */
function withClip(attrs, matrices, ctx, out, emit) {
  const clipRaw = attrs['clip-path'];
  if (!clipRaw || /^none$/i.test(String(clipRaw).trim())) {
    emit(out);
    return;
  }
  const rects = [];
  for (const matrix of matrices) {
    const rect = resolveClipRect(clipRaw, ctx, matrix);
    if (!rect) {
      ctx.unresolved.add('clip-path');
      return;
    }
    rects.push(rect);
  }
  const captured = [];
  emit(captured);
  if (captured.length === 0) return;
  const box = bboxOfShapes(captured, ctx.steps);
  // A viewport-establishing element is clipped in one of two plausible spaces
  // (before or after its own viewBox). Passing only when *both* readings contain
  // the ink keeps the decision conservative.
  if (box && !rects.every((rect) => rectContains(rect, box))) {
    ctx.unresolved.add('clip-path-cuts-ink');
    return;
  }
  out.push(...captured);
}

function bboxUnion(a, b) {
  if (!a) return b;
  if (!b) return a;
  return {
    minX: Math.min(a.minX, b.minX),
    minY: Math.min(a.minY, b.minY),
    maxX: Math.max(a.maxX, b.maxX),
    maxY: Math.max(a.maxY, b.maxY),
  };
}

function bboxExpand(box, by) {
  if (!box || by === 0) return box;
  return {
    minX: box.minX - by,
    minY: box.minY - by,
    maxX: box.maxX + by,
    maxY: box.maxY + by,
  };
}

function maxScale(matrix) {
  return Math.max(Math.hypot(matrix[0], matrix[1]), Math.hypot(matrix[2], matrix[3])) || 1;
}

function uniformScale(matrix) {
  const sx = Math.hypot(matrix[0], matrix[1]);
  const sy = Math.hypot(matrix[2], matrix[3]);
  return (sx + sy) / 2 || 1;
}

/**
 * Rendered px per user unit, per axis.
 *
 * `width="100"` with a 24-unit viewBox means every measurement is in 24ths, not
 * pixels — reporting that as `px` inflates or deflates every verdict. The scale
 * is only claimed when *both* dimensions are absolute; a lone `width="48"` or
 * `height="100%"` leaves the rendered box unknowable.
 *
 * When the rendered size is not in the file, the icon is assumed to be **rendered
 * at the nominal 24px** (short side). That keeps verdicts comparable across
 * grids: a 2% imbalance on a 24-unit icon and on a 512-unit Font Awesome glyph
 * are the same optical error, and both should read the same way. Assuming
 * "1 unit = 1px" instead made every 512-unit glyph look catastrophically
 * off-centre, because the tolerance clamp then bit at 0.3% of the canvas.
 *
 * `preserveAspectRatio="none"` stretches the axes independently, so there is no
 * single number: x and y are reported separately and `unitScale` is `null`.
 */
function rootUnitScale(attrs, viewBox) {
  const nominal = 24;
  const par = String(attrs.preserveAspectRatio || '').trim();
  const stretches = par.toLowerCase().startsWith('none');
  // `preserveAspectRatio="none"` has no single scale, and that is true of the
  // assumed branch too: the axes get 24px each rather than sharing one factor.
  const reference = viewBox.w > 0 && viewBox.h > 0 ? nominal / Math.min(viewBox.w, viewBox.h) : 1;
  const assumed = stretches
    ? {
        x: viewBox.w > 0 ? nominal / viewBox.w : reference,
        y: viewBox.h > 0 ? nominal / viewBox.h : reference,
        uniform: null,
        source: 'assumed',
      }
    : { x: reference, y: reference, uniform: reference, source: 'assumed' };
  if (attrs.width === undefined && attrs.height === undefined) return assumed;
  const w = absolutePx(attrs.width);
  const h = absolutePx(attrs.height);
  if (w === null || h === null) return assumed;
  if (!(viewBox.w > 0) || !(viewBox.h > 0)) return assumed;

  const rawX = w / viewBox.w;
  const rawY = h / viewBox.h;
  if (par.toLowerCase().startsWith('none')) {
    const uniform = Math.abs(rawX - rawY) < 1e-9 ? rawX : null;
    return { x: rawX, y: rawY, uniform, source: 'declared' };
  }
  // `slice` fills the viewport (larger ratio wins), `meet` fits inside it.
  const scale = /\bslice\b/i.test(par) ? Math.max(rawX, rawY) : Math.min(rawX, rawY);
  return { x: scale, y: scale, uniform: scale, source: 'declared' };
}

/**
 * @returns {{viewBox: object, ink: object, strokeOnly: boolean, noInk: boolean, unresolved: string[], unitScale: number, unitSource: string}}
 */
export function analyzeSvg(text, { steps = 24 } = {}) {
  const doc = parseXml(text);
  const svg = doc.children.find((c) => c.tag === 'svg') || doc.children[0] || { attrs: {}, children: [] };
  const viewBox = parseViewBox(svg.attrs || {});
  const ids = new Map();
  indexIds(svg, ids);

  // An unparseable viewBox means the element does not render, so there is no
  // canvas to measure against and no honest verdict to give.
  if (!viewBox) {
    return {
      viewBox: { x: 0, y: 0, w: 24, h: 24 },
      ink: { bbox: null, area: 0, centroid: { cx: 0, cy: 0 } },
      strokeOnly: false,
      noInk: true,
      unresolved: ['invalid-viewBox'],
      unitScale: null,
      unitScaleX: null,
      unitScaleY: null,
      unitSource: 'assumed',
    };
  }

  const unit = rootUnitScale(svg.attrs || {}, viewBox);
  const unitScale = unit.uniform;
  const unitScaleX = unit.x;
  const unitScaleY = unit.y;
  const unitSource = unit.source;
  const ctx = { ids, unresolved: new Set(), depth: 0, root: svg, steps };
  // Paint may live in an internal stylesheet, so resolve the cascade before
  // anything reads an attribute.
  applyStylesheets(text, svg, ctx);
  const shapes = collect(
    svg,
    {
      matrix: IDENTITY,
      fill: 'black',
      stroke: undefined,
      strokeWidth: 1,
      fillRule: 'nonzero',
      fillOpacity: 1,
      visible: true,
      viewport: { w: viewBox.w, h: viewBox.h },
    },
    [],
    ctx,
  );

  let filledArea = 0;
  let filledCx = 0;
  let filledCy = 0;
  let bbox = null;

  let strokeArea = 0;
  let strokeMx = 0;
  let strokeMy = 0;
  let strokeBox = null;

  for (const shape of shapes) {
    const subpaths = flattenPath(shape.d, steps).map((sub) =>
      sub.map(([x, y]) => applyMatrix(shape.matrix, x, y)),
    );
    if (subpaths.length === 0) continue;
    const points = subpaths.flat();
    const localBox = bboxOfPoints(points);

    if (shape.filled) {
      const net = shape.fillRule === 'evenodd' ? netShapeEvenOdd(subpaths) : netShape(subpaths);
      if (net.overlapping) {
        // Partially overlapping outlines need a boolean XOR; refuse rather than
        // report a centroid that may sit outside the artwork.
        ctx.unresolved.add('overlapping-subpaths');
      } else if (net.area > 0) {
        filledArea += net.area;
        filledCx += net.cx * net.area;
        filledCy += net.cy * net.area;
        bbox = bboxUnion(bbox, localBox);
      }
    }

    if (shape.stroked) {
      const width = Math.max(shape.strokeWidth * uniformScale(shape.matrix), 0.0001);
      for (const sub of subpaths) {
        for (let i = 1; i < sub.length; i += 1) {
          const [x0, y0] = sub[i - 1];
          const [x1, y1] = sub[i];
          const len = Math.hypot(x1 - x0, y1 - y0);
          const weight = len * width;
          strokeArea += weight;
          strokeMx += ((x0 + x1) / 2) * weight;
          strokeMy += ((y0 + y1) / 2) * weight;
        }
      }
      strokeBox = bboxUnion(strokeBox, bboxExpand(localBox, width / 2));
    }
  }

  const totalArea = filledArea + strokeArea;
  const finalBox = bboxUnion(bbox, strokeBox);

  if (totalArea <= 1e-9 || !finalBox) {
    return {
      viewBox,
      ink: { bbox: null, area: 0, centroid: { cx: 0, cy: 0 } },
      strokeOnly: false,
      noInk: true,
      unitScale,
      unitScaleX,
      unitScaleY,
      unitSource,
      unresolved: [...ctx.unresolved],
    };
  }

  const cx = totalArea > 0 ? (filledCx + strokeMx) / totalArea : 0;
  const cy = totalArea > 0 ? (filledCy + strokeMy) / totalArea : 0;

  // Cheap self-check: a centroid outside its own ink box means the model was fed
  // something it does not understand.
  if (
    finalBox &&
    (cx < finalBox.minX - 1e-3 ||
      cx > finalBox.maxX + 1e-3 ||
      cy < finalBox.minY - 1e-3 ||
      cy > finalBox.maxY + 1e-3)
  ) {
    ctx.unresolved.add('centroid-outside-ink');
  }

  return {
    viewBox,
    ink: {
      bbox: finalBox,
      area: totalArea,
      centroid: { cx, cy },
    },
    strokeOnly: filledArea === 0 && strokeArea > 0,
    noInk: totalArea <= 1e-9 || !finalBox,
    unitScale,
    unitScaleX,
    unitScaleY,
    unitSource,
    unresolved: [...ctx.unresolved],
  };
}

function boxCenter(box) {
  return { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 };
}

/**
 * @param {object} shape result of analyzeSvg
 * @param {{mode?: string, target?: string}} opts
 */
export function checkShape(shape, { mode = 'standalone', target = '<inline>' } = {}) {
  const { viewBox, ink } = shape;
  const findings = [];
  const meta = {
    strokeOnly: shape.strokeOnly,
    ink: shape.ink,
    viewBox: shape.viewBox,
    unitScale: shape.unitScale ?? null,
    unitScaleX: shape.unitScaleX ?? 1,
    unitScaleY: shape.unitScaleY ?? 1,
    unitSource: shape.unitSource || 'assumed',
  };

  // A canvas that failed to parse has no ink for a reason already reported;
  // adding "the canvas may be empty" would point the reader at the wrong thing.
  const canvasInvalid = (shape.unresolved || []).includes('invalid-viewBox');
  if (shape.noInk && !canvasInvalid) {
    findings.push({
      id: 'geometry/no-ink',
      layer: 'exact',
      forcedVerdict: 'unknown',
      pixel: false,
      evidence: 'no renderable ink was found (empty canvas, unresolved shapes, or only non-rendering nodes)',
      suggested: { kind: 'inspect', value: 'check the source; the canvas may be empty or use unsupported syntax' },
    });
  }

  if (shape.unresolved?.length) {
    findings.push({
      id: 'geometry/unresolved-graphics',
      layer: 'exact',
      forcedVerdict: 'unknown',
      pixel: false,
      evidence: `ink cannot be measured while these features are present: ${shape.unresolved.join(', ')}`,
      suggested: {
        kind: 'inspect',
        value: canvasInvalid
          ? 'fix the viewBox; the element does not render as written'
          : 'flatten the artwork (expand clip paths / masks) and re-run',
      },
    });
  }

  if (shape.noInk || shape.unresolved?.length) {
    return buildReport({ target, mode, findings, meta: { ...meta, blocked: true } });
  }

  const vbCenter = { x: viewBox.x + viewBox.w / 2, y: viewBox.y + viewBox.h / 2 };
  const inkCenter = boxCenter(ink.bbox);
  // Measurements are taken in viewBox user units; offsets, tolerance basis and
  // suggestions are reported in rendered px.
  const sx = shape.unitScaleX ?? 1;
  const sy = shape.unitScaleY ?? 1;
  const basis = Math.min((viewBox.w || 24) * sx, (viewBox.h || 24) * sy);
  // The evidence is written in viewBox units; say how they became px.
  const scaleNote =
    sx === 1 && sy === 1
      ? ''
      : sx === sy
        ? ` [user units ×${round(sx, 4)} = ${shape.unitSource === 'assumed' ? '24px nominal' : 'px'}]`
        : ` [user units ×${round(sx, 4)} = px horizontally, ×${round(sy, 4)} vertically]`;

  const dInkX = inkCenter.x - vbCenter.x;
  const dInkY = inkCenter.y - vbCenter.y;

  // `value` is px, but a viewBox origin is in user units. Publish the user-unit
  // figure whenever the two differ and there is something to add.
  const deltaInUserUnits =
    (sx !== 1 || sy !== 1) && (Math.abs(dInkX) > 1e-9 || Math.abs(dInkY) > 1e-9);

  findings.push({
    id: 'geometry/ink-bbox',
    layer: 'exact',
    offset: dInkX * sx,
    offsetY: dInkY * sy,
    basis,
    evidence:
      `ink bbox=(${round(ink.bbox.minX)},${round(ink.bbox.minY)})-` +
      `(${round(ink.bbox.maxX)},${round(ink.bbox.maxY)}) centre=(${round(inkCenter.x)},${round(inkCenter.y)}) ` +
      `viewBox centre=(${round(vbCenter.x)},${round(vbCenter.y)})${scaleNote}`,
    suggested: {
      // The viewBox attribute below is the corrected one; `value` is the same
      // correction sized in px, matching every other reported number. The two only
      // coincide when a user unit happens to be a pixel, so `delta` carries the
      // user-unit figure that actually goes into the origin whenever they differ —
      // adding `value` to a 512-unit origin would move the artwork by half a unit.
      kind: 'viewBox-origin',
      value: `${round(dInkX * sx, 2)}px / ${round(dInkY * sy, 2)}px`,
      ...(deltaInUserUnits ? { delta: `${round(dInkX, 3)} / ${round(dInkY, 3)}` } : {}),
      viewBox: `${round(viewBox.x + dInkX, 3)} ${round(viewBox.y + dInkY, 3)} ${round(viewBox.w, 3)} ${round(viewBox.h, 3)}`,
    },
  });

  const shiftX = inkCenter.x - ink.centroid.cx;
  const shiftY = inkCenter.y - ink.centroid.cy;

  findings.push({
    id: 'geometry/centroid',
    layer: 'exact',
    offset: -shiftX * sx,
    offsetY: -shiftY * sy,
    // A centroid offset is judged against the object's girth, not one axis: a
    // tall thin glyph and a wide flat one of the same mass are equally sensitive
    // to drift, and under `preserveAspectRatio="none"` the two axes have
    // different px scales, so the smaller extent is the honest one.
    basis: Math.max(
      Math.min(
        (ink.bbox.maxX - ink.bbox.minX) * sx,
        (ink.bbox.maxY - ink.bbox.minY) * sy,
      ),
      1,
    ),
    evidence:
      `area=${round(ink.area)} centroid=(${round(ink.centroid.cx)},${round(ink.centroid.cy)}) ` +
      `ink centre=(${round(inkCenter.x)},${round(inkCenter.y)})${scaleNote}`,
    suggested: {
      // Translating the artwork moves the centroid and the box together, so it
      // cannot change this number: the mass distribution itself has to change.
      kind: 'redraw',
      value:
        Math.abs(shiftY * sy) < 0.005
          ? `move the visual mass ${round(shiftX * sx, 2)}px`
          : `move the visual mass ${round(shiftX * sx, 2)}px / ${round(shiftY * sy, 2)}px`,
    },
  });

  if (mode === 'inline') {
    findings.push({
      id: 'geometry/inline-context',
      layer: 'exact',
      forcedVerdict: 'unknown',
      pixel: false,
      evidence: 'inline mode needs a sibling text node to measure the optical gutter; none provided',
      suggested: { kind: 'rerun', value: '--mode standalone' },
    });
  }

  return buildReport({ target, mode, findings, meta });
}

export async function checkIconFile(path, { mode = 'auto' } = {}) {
  const text = await readFile(path, 'utf8');
  const shape = analyzeSvg(text);
  const resolved = mode === 'auto' ? 'standalone' : mode;
  return checkShape(shape, { mode: resolved, target: basename(path) });
}

/**
 * Keyline normalisation across a set. Areas are compared in linear units
 * (sqrt of the fill ratio) so the number reads as "this icon is N px smaller
 * than the set's optical norm".
 */
export async function checkIconSet(dir, { threshold = 0.2 } = {}) {
  const entries = (await readdir(dir)).filter((f) => f.toLowerCase().endsWith('.svg')).sort();
  const rows = [];
  for (const file of entries) {
    const text = await readFile(join(dir, file), 'utf8');
    const shape = analyzeSvg(text);
    const boxArea = (shape.viewBox.w || 1) * (shape.viewBox.h || 1);
    const ratio = shape.ink.area / boxArea;
    const unitX = shape.unitScaleX ?? 1;
    const unitY = shape.unitScaleY ?? 1;
    rows.push({
      file,
      ratio,
      linear: Math.sqrt(Math.max(ratio, 0)),
      // The fill ratio is unitless, but the overshoot below is a length, so the
      // reference size must be in rendered px.
      size: Math.min(shape.viewBox.w * unitX, shape.viewBox.h * unitY),
      strokeOnly: shape.strokeOnly,
      noInk: shape.noInk,
      unresolved: shape.unresolved.length > 0,
    });
  }

  if (rows.length === 0) {
    // An empty directory is not a consistent icon set; answering `ok` would make
    // a mistyped path look like a passing audit.
    return buildReport({
      target: basename(dir),
      mode: 'keyline',
      findings: [
        {
          id: 'geometry/keyline-empty',
          layer: 'heuristic',
          forcedVerdict: 'unknown',
          pixel: false,
          offset: 0,
          evidence: 'no .svg files in this directory, so there is no set to normalise',
          suggested: { kind: 'inspect', value: 'check the path' },
        },
      ],
    });
  }

  const blind = rows.filter((r) => r.noInk || r.unresolved);
  if (blind.length > 0) {
    return buildReport({
      target: basename(dir),
      mode: 'keyline',
      findings: [
        {
          id: 'geometry/keyline-incomplete',
          layer: 'heuristic',
          forcedVerdict: 'unknown',
          pixel: false,
          evidence: `${blind.length}/${rows.length} icons could not be measured (${blind
            .map((r) => r.file)
            .join(', ')}); a norm computed without them would be fiction`,
          suggested: { kind: 'inspect', value: 'fix or flatten the flagged icons first' },
        },
      ],
      meta: { set: rows.map((r) => r.file) },
    });
  }

  // A stroke-only icon's fill ratio is dominated by its line width; comparing it
  // with solid glyphs produces a "norm" that belongs to neither. Refuse instead.
  const stroked = rows.filter((r) => r.strokeOnly).length;
  if (stroked > 0 && stroked < rows.length) {
    return buildReport({
      target: basename(dir),
      mode: 'keyline',
      findings: [
        {
          id: 'geometry/keyline-mixed-set',
          layer: 'heuristic',
          forcedVerdict: 'unknown',
          pixel: false,
          offset: 0,
          evidence:
            `${stroked}/${rows.length} icons are stroke-only and the rest are filled; ` +
            'their fill ratios are not comparable — split the set before normalising',
          suggested: { kind: 'split', value: 'run keyline per icon family' },
        },
      ],
      meta: { set: rows.map((r) => r.file) },
    });
  }

  if (rows.length < 3) {
    return buildReport({
      target: basename(dir),
      mode: 'keyline',
      findings: [
        {
          id: 'geometry/keyline-small-set',
          layer: 'heuristic',
          forcedVerdict: 'unknown',
          pixel: false,
          offset: 0,
          evidence: `${rows.length} icons is not enough to establish a norm (need at least 3)`,
          suggested: { kind: 'extend', value: 'add more icons from the same family' },
        },
      ],
      meta: { set: rows.map((r) => r.file) },
    });
  }

  const sorted = [...rows].map((r) => r.linear).sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;

  const findings = rows.map((row) => {
    const delta = (row.linear - median) * row.size;
    const inside = Math.abs(row.linear - median) <= threshold;
    return {
      id: 'geometry/keyline-overshoot',
      layer: 'heuristic',
      offset: delta,
      basis: row.size,
      forcedVerdict: inside ? 'ok' : 'nudge',
      evidence:
        `${row.file}: fill ratio=${round(row.ratio, 3)} linear=${round(row.linear, 3)} ` +
        `set median=${round(median, 3)} (threshold ±${threshold})`,
      suggested: inside
        ? { kind: 'none', value: 'within set norm' }
        : {
            kind: 'scale',
            value: `${round((median / (row.linear || 1) - 1) * 100, 1)}%`,
          },
    };
  });

  return buildReport({
    target: basename(dir),
    mode: 'keyline',
    findings,
    meta: { set: rows.map((r) => r.file) },
  });
}

export { tolFor };
