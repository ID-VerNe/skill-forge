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
  viewBoxMatrix,
  IDENTITY,
} from './geom.mjs';
import { buildReport, tolFor } from './report.mjs';

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

function parseViewBox(attrs) {
  if (attrs.viewBox) {
    const parts = attrs.viewBox.split(/[\s,]+/).map(Number);
    if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
      return { x: parts[0], y: parts[1], w: parts[2], h: parts[3] };
    }
  }
  const w = Number.parseFloat(attrs.width || '24');
  const h = Number.parseFloat(attrs.height || '24');
  return { x: 0, y: 0, w: Number.isFinite(w) ? w : 24, h: Number.isFinite(h) ? h : 24 };
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

/** Absolute length in px, or null when it depends on external context. */
function absolutePx(value) {
  if (value === undefined || value === null) return null;
  const m = /^\s*(-?\d*\.?\d+)(px)?\s*$/.exec(String(value));
  return m ? Number.parseFloat(m[1]) : null;
}

/** `style="fill:none;stroke:#000"` is presentation attributes by another name. */
function parseStyle(value) {
  if (!value) return {};
  const out = {};
  for (const part of value.split(';')) {
    const colon = part.indexOf(':');
    if (colon === -1) continue;
    const prop = part.slice(0, colon).trim().toLowerCase();
    const val = part.slice(colon + 1).trim();
    if (prop && val) out[prop] = val;
  }
  return out;
}

function effectiveAttrs(node) {
  return { ...node.attrs, ...parseStyle(node.attrs.style) };
}

function indexIds(node, map) {
  if (node.attrs && node.attrs.id) map.set(node.attrs.id, node);
  for (const child of node.children || []) indexIds(child, map);
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

function fillOpacityOf(attrs, inherited) {
  if (attrs['fill-opacity'] === undefined) return inherited.fillOpacity ?? 1;
  const value = Number.parseFloat(attrs['fill-opacity']);
  return Number.isFinite(value) ? value : 1;
}

/**
 * `stroke-width` is in user units, or a percentage of the viewport diagonal —
 * which needs a rendered viewport we do not have. Refuse the percentage rather
 * than read "10%" as ten units.
 */
function strokeWidthOf(attrs, inherited, ctx) {
  if (attrs['stroke-width'] === undefined) return inherited.strokeWidth;
  const raw = String(attrs['stroke-width']).trim();
  if (/%$/.test(raw)) {
    ctx.unresolved.add('stroke-width-percentage');
    return inherited.strokeWidth;
  }
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : inherited.strokeWidth;
}

/** Presentation state a node hands to its children. */
function inheritedFor(attrs, inherited, visible, matrix) {
  return {
    matrix,
    fill: attrs.fill !== undefined ? attrs.fill : inherited.fill,
    stroke: attrs.stroke !== undefined ? attrs.stroke : inherited.stroke,
    strokeWidth:
      attrs['stroke-width'] !== undefined
        ? Number.parseFloat(attrs['stroke-width'])
        : inherited.strokeWidth,
    fillRule: attrs['fill-rule'] || inherited.fillRule,
    // `fill-opacity` is inherited; `opacity` is not (it composites the group).
    fillOpacity:
      attrs['fill-opacity'] !== undefined
        ? Number.parseFloat(attrs['fill-opacity'])
        : inherited.fillOpacity,
    visible,
    viewport: inherited.viewport,
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
  if ((a.rx && Number.parseFloat(a.rx) !== 0) || (a.ry && Number.parseFloat(a.ry) !== 0)) return null;

  const x = Number.parseFloat(a.x || '0') || 0;
  const y = Number.parseFloat(a.y || '0') || 0;
  const w = Number.parseFloat(a.width || '0');
  const h = Number.parseFloat(a.height || '0');
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
    if (attrs.viewBox) {
      matrix = multiplyMatrix(
        matrix,
        viewBoxMatrix(parseViewBox(attrs), { x: 0, y: 0, w: vpW, h: vpH }, attrs.preserveAspectRatio),
      );
    }
    const local = inheritedFor(attrs, inherited, visible, matrix);
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
    const local = inheritedFor(attrs, inherited, visible, useMatrix);

    withClip(attrs, [useMatrix], ctx, out, (sink) => {
      if (targetTag === 'symbol') {
        // <symbol> is non-rendering on its own but renders when instantiated.
        const vpW = resolveLength(attrs.width, inherited.viewport.w);
        const vpH = resolveLength(attrs.height, inherited.viewport.h);
        if (vpW === null || vpH === null) {
          ctx.unresolved.add('use-viewport');
          return;
        }
        let matrix = useMatrix;
        // The referenced tree's own transform is part of the instantiation.
        matrix = matrixFrom(effectiveAttrs(target), matrix, ctx);
        if (effectiveAttrs(target).viewBox) {
          matrix = multiplyMatrix(
            matrix,
            viewBoxMatrix(
              parseViewBox(effectiveAttrs(target)),
              { x: 0, y: 0, w: vpW, h: vpH },
              effectiveAttrs(target).preserveAspectRatio,
            ),
          );
        }
        const childLocal = { ...local, matrix, viewport: { w: vpW, h: vpH } };
        for (const child of target.children || []) collect(child, childLocal, sink, inner);
        return;
      }
      if (targetTag === 'svg') {
        // Let the nested-viewport branch apply the viewBox exactly once. The
        // <use> width/height override the target's own, and x/y are already in
        // `useMatrix`, so the clone is placed at the origin.
        const overrides = { ...effectiveAttrs(target), x: '0', y: '0' };
        if (attrs.width !== undefined) overrides.width = attrs.width;
        if (attrs.height !== undefined) overrides.height = attrs.height;
        collect({ ...target, attrs: overrides }, local, sink, inner);
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
      const d = tag === 'path' ? attrs.d || '' : shapeToPath(tag, attrs);
      if (!d) {
        ctx.unresolved.add('unparsed-shape');
      } else {
        const strokeWidth = strokeWidthOf(attrs, inherited, ctx);
        out.push({
          d,
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
  const bound = inheritedFor(attrs, inherited, visible, own);
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
  const reference = viewBox.w > 0 && viewBox.h > 0 ? nominal / Math.min(viewBox.w, viewBox.h) : 1;
  const assumed = { x: reference, y: reference, uniform: reference, source: 'assumed' };
  if (attrs.width === undefined && attrs.height === undefined) return assumed;
  const w = absolutePx(attrs.width);
  const h = absolutePx(attrs.height);
  if (w === null || h === null) return assumed;
  if (!(viewBox.w > 0) || !(viewBox.h > 0)) return assumed;

  const rawX = w / viewBox.w;
  const rawY = h / viewBox.h;
  const par = String(attrs.preserveAspectRatio || '').trim();
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

  const unit = rootUnitScale(svg.attrs || {}, viewBox);
  const unitScale = unit.uniform;
  const unitScaleX = unit.x;
  const unitScaleY = unit.y;
  const unitSource = unit.source;
  const ctx = { ids, unresolved: new Set(), depth: 0, root: svg, steps };
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

  if (shape.noInk) {
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
      suggested: { kind: 'inspect', value: 'flatten the artwork (expand clip paths / masks) and re-run' },
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
    basis: Math.max((ink.bbox.maxX - ink.bbox.minX) * sx, 1),
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
    return buildReport({ target: basename(dir), mode: 'keyline', findings: [] });
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
