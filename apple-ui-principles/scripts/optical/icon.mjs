// Icon-layer checks: #1 ink bounding box, #2 area centroid, #3 keyline set.
//
// The model is deliberately literal: we measure ink, not layout boxes. A path
// that renders outside its own viewBox is a real defect and must not be
// normalised away.

import { readFile, readdir } from 'node:fs/promises';
import { basename, join } from 'node:path';
import {
  flattenPath,
  netShape,
  bboxOfPoints,
  parseTransform,
  applyMatrix,
  multiplyMatrix,
  shapeToPath,
  IDENTITY,
} from './geom.mjs';
import { buildReport, tolFor } from './report.mjs';

const round = (n, d = 3) => Math.round(n * 10 ** d) / 10 ** d;
const SHAPES = new Set(['path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line']);

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

function strokeWidthOf(value, fallback) {
  if (value === undefined) return fallback;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : fallback;
}

function collect(node, inherited, out) {
  const attrs = node.attrs || {};
  const matrix = attrs.transform
    ? multiplyMatrix(inherited.matrix, parseTransform(attrs.transform))
    : inherited.matrix;
  const fill = attrs.fill !== undefined ? attrs.fill : inherited.fill;
  const stroke = attrs.stroke !== undefined ? attrs.stroke : inherited.stroke;
  const strokeWidth = strokeWidthOf(attrs['stroke-width'], inherited.strokeWidth);

  if (SHAPES.has(node.tag)) {
    const d = node.tag === 'path' ? attrs.d || '' : shapeToPath(node.tag, attrs);
    if (d) {
      out.push({
        d,
        matrix,
        filled: fill !== 'none',
        stroked: stroke !== 'none' && stroke !== undefined,
        strokeWidth,
      });
    }
  }

  for (const child of node.children || []) {
    collect(child, { matrix, fill, stroke, strokeWidth }, out);
  }
  return out;
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

/**
 * @returns {{viewBox: object, ink: {bbox: object, area: number, centroid: {cx:number,cy:number}}, strokeOnly: boolean}}
 */
export function analyzeSvg(text, { steps = 24 } = {}) {
  const doc = parseXml(text);
  const svg = doc.children.find((c) => c.tag === 'svg') || doc.children[0] || { attrs: {} };
  const viewBox = parseViewBox(svg.attrs || {});
  const shapes = collect(svg, { matrix: IDENTITY, fill: 'black', stroke: undefined, strokeWidth: 1 }, []);

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
      const net = netShape(subpaths);
      if (net.area > 0) {
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

  let cx = 0;
  let cy = 0;
  if (totalArea > 0) {
    cx = (filledCx + strokeMx) / totalArea;
    cy = (filledCy + strokeMy) / totalArea;
  }

  const finalBox = bboxUnion(bbox, strokeBox) || {
    minX: viewBox.x,
    minY: viewBox.y,
    maxX: viewBox.x + viewBox.w,
    maxY: viewBox.y + viewBox.h,
  };

  return {
    viewBox,
    ink: {
      bbox: finalBox,
      area: totalArea,
      centroid: { cx, cy },
    },
    strokeOnly: filledArea === 0 && strokeArea > 0,
  };
}

function uniformScale(matrix) {
  const sx = Math.hypot(matrix[0], matrix[1]);
  const sy = Math.hypot(matrix[2], matrix[3]);
  return (sx + sy) / 2 || 1;
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
  const vbCenter = { x: viewBox.x + viewBox.w / 2, y: viewBox.y + viewBox.h / 2 };
  const inkCenter = boxCenter(ink.bbox);
  const basis = Math.min(viewBox.w, viewBox.h) || 24;
  const findings = [];

  findings.push({
    id: 'geometry/ink-bbox',
    layer: 'exact',
    offset: inkCenter.x - vbCenter.x,
    offsetY: inkCenter.y - vbCenter.y,
    basis,
    evidence:
      `ink bbox=(${round(ink.bbox.minX)},${round(ink.bbox.minY)})-` +
      `(${round(ink.bbox.maxX)},${round(ink.bbox.maxY)}) centre=(${round(inkCenter.x)},${round(inkCenter.y)}) ` +
      `viewBox centre=(${round(vbCenter.x)},${round(vbCenter.y)})`,
    suggested: {
      kind: 'viewBox-origin',
      value: `${round(vbCenter.x - inkCenter.x, 2)}px / ${round(vbCenter.y - inkCenter.y, 2)}px`,
    },
  });

  findings.push({
    id: 'geometry/centroid',
    layer: 'exact',
    offset: ink.centroid.cx - inkCenter.x,
    offsetY: ink.centroid.cy - inkCenter.y,
    basis: Math.max(ink.bbox.maxX - ink.bbox.minX, 1),
    evidence:
      `area=${round(ink.area)} centroid=(${round(ink.centroid.cx)},${round(ink.centroid.cy)}) ` +
      `ink centre=(${round(inkCenter.x)},${round(inkCenter.y)})`,
    suggested: {
      kind: 'optical-shift',
      value: `${round(inkCenter.x - ink.centroid.cx, 2)}px`,
    },
  });

  if (mode === 'inline') {
    findings.push({
      id: 'geometry/inline-context',
      layer: 'exact',
      forcedVerdict: 'unknown',
      offset: 0,
      basis,
      evidence: 'inline mode needs a sibling text node to measure the optical gutter; none provided',
      suggested: { kind: 'rerun', value: '--mode standalone' },
    });
  }

  return buildReport({
    target,
    mode,
    findings,
    meta: { strokeOnly: shape.strokeOnly, ink: shape.ink, viewBox: shape.viewBox },
  });
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
    rows.push({
      file,
      ratio,
      linear: Math.sqrt(Math.max(ratio, 0)),
      size: Math.min(shape.viewBox.w, shape.viewBox.h),
      strokeOnly: shape.strokeOnly,
    });
  }

  if (rows.length === 0) {
    return buildReport({ target: basename(dir), mode: 'keyline', findings: [] });
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
            value: `${round(((median / (row.linear || 1)) - 1) * 100, 1)}%`,
          },
    };
  });

  return buildReport({ target: basename(dir), mode: 'keyline', findings, meta: { set: rows.map((r) => r.file) } });
}

export { tolFor };
