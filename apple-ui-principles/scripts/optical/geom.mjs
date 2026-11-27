// Geometry primitives for optical alignment.
//
// Everything here is pure arithmetic on already-flattened polygons so that a
// reviewer can re-derive any number by hand. Curve flattening is delegated to
// the vendored svgpath parser (see ./vendor/svgpath) because path grammar and
// arc conversion are the one place where a hand-rolled parser silently lies.

import svgpath from './vendor/svgpath/index.js';

const DEFAULT_STEPS = 24;

/**
 * Flatten an SVG path into polygons.
 * @param {string} d path data
 * @param {number} steps segments per curve
 * @returns {Array<Array<[number, number]>>}
 */
export function flattenPath(d, steps = DEFAULT_STEPS) {
  const subpaths = [];
  if (!d || typeof d !== 'string') return subpaths;

  let current = null; // active polygon
  let start = null; // subpath start point

  const push = (x, y) => {
    if (!current) {
      current = [];
      subpaths.push(current);
    }
    current.push([x, y]);
  };

  const cubic = (x0, y0, x1, y1, x2, y2, x3, y3) => {
    for (let i = 1; i <= steps; i += 1) {
      const t = i / steps;
      const u = 1 - t;
      const a = u * u * u;
      const b = 3 * u * u * t;
      const c = 3 * u * t * t;
      const e = t * t * t;
      push(a * x0 + b * x1 + c * x2 + e * x3, a * y0 + b * y1 + c * y2 + e * y3);
    }
  };

  const quad = (x0, y0, x1, y1, x2, y2) => {
    for (let i = 1; i <= steps; i += 1) {
      const t = i / steps;
      const u = 1 - t;
      push(u * u * x0 + 2 * u * t * x1 + t * t * x2, u * u * y0 + 2 * u * t * y1 + t * t * y2);
    }
  };

  let path;
  try {
    path = svgpath(d).abs().unshort().unarc();
  } catch {
    return subpaths;
  }

  path.iterate((segment, index, x, y) => {
    switch (segment[0]) {
      case 'M':
        current = null;
        push(segment[1], segment[2]);
        start = [segment[1], segment[2]];
        break;
      case 'L':
        push(segment[1], segment[2]);
        break;
      case 'H':
        push(segment[1], y);
        break;
      case 'V':
        push(x, segment[1]);
        break;
      case 'C':
        if (!current) push(x, y);
        cubic(x, y, segment[1], segment[2], segment[3], segment[4], segment[5], segment[6]);
        break;
      case 'Q':
        if (!current) push(x, y);
        quad(x, y, segment[1], segment[2], segment[3], segment[4]);
        break;
      case 'Z':
        if (current && start) current.push([start[0], start[1]]);
        current = null;
        break;
      default:
        break;
    }
  });

  return subpaths.filter((sub) => sub.length > 0);
}

/** Signed shoelace area. Positive for clockwise-in-screen-space paths. */
export function subpathSignedArea(points) {
  if (!points || points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

/** Polygon centroid, using the signed area as the weight. */
export function subpathCentroid(points) {
  const signedArea = subpathSignedArea(points);
  if (Math.abs(signedArea) < 1e-12 || !points || points.length < 3) {
    return { cx: 0, cy: 0, signedArea };
  }
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    const cross = x1 * y2 - x2 * y1;
    cx += (x1 + x2) * cross;
    cy += (y1 + y2) * cross;
  }
  const factor = 1 / (6 * signedArea);
  return { cx: cx * factor, cy: cy * factor, signedArea };
}

/**
 * Net fill of a set of subpaths under the non-zero winding rule. Holes must be
 * wound opposite to their container to subtract, which is what non-zero fill
 * relies on.
 */
export function netShape(subpaths) {
  let area = 0;
  let mx = 0;
  let my = 0;
  for (const sub of subpaths) {
    const { cx, cy, signedArea } = subpathCentroid(sub);
    area += signedArea;
    mx += cx * signedArea;
    my += cy * signedArea;
  }
  if (Math.abs(area) < 1e-12) {
    return { area: 0, cx: 0, cy: 0 };
  }
  return { area: Math.abs(area), cx: mx / area, cy: my / area };
}

/** Ray-casting containment test for a single point. */
export function pointInPolygon([px, py], polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const straddles = yi > py !== yj > py;
    if (straddles && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** True when the point lies on the segment within `eps` (perpendicular distance). */
function pointOnSegment([px, py], [ax, ay], [bx, by], eps = 1e-6) {
  const len = Math.hypot(bx - ax, by - ay);
  if (len < eps) return Math.hypot(px - ax, py - ay) <= eps;
  const cross = Math.abs((bx - ax) * (py - ay) - (by - ay) * (px - ax));
  if (cross / len > eps) return false;
  const dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay);
  return dot >= -eps && dot <= len * len + eps;
}

/** 'inside' | 'outside' | 'boundary' — boundary is ignored by the classifier. */
function classifyPoint(point, polygon, eps) {
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    if (pointOnSegment(point, polygon[j], polygon[i], eps)) return 'boundary';
  }
  return pointInPolygon(point, polygon) ? 'inside' : 'outside';
}

/**
 * Net fill under the even-odd rule. Winding direction is irrelevant: a subpath
 * nested an odd number of levels deep is a hole, two levels deep is solid
 * again. Needed because `fill-rule="evenodd"` icons routinely draw holes with
 * the same winding as their container.
 *
 * Containment is only well defined for strictly nested or disjoint subpaths.
 * Partially overlapping outlines (an XOR shape) need a boolean polygon
 * operation, which this module does not implement — it reports `overlapping`
 * so the caller can degrade to `unknown` instead of inventing a centroid that
 * lands outside the artwork.
 */
export function netShapeEvenOdd(subpaths) {
  const items = subpaths.map((sub) => ({
    sub,
    area: Math.abs(subpathSignedArea(sub)),
    centroid: subpathCentroid(sub),
  }));
  const eps = 1e-6;

  const containers = items.map(() => 0);
  let overlapping = false;
  for (let i = 0; i < items.length; i += 1) {
    for (let j = 0; j < items.length; j += 1) {
      if (i === j) continue;
      let inside = 0;
      let outside = 0;
      for (const vertex of items[i].sub) {
        const where = classifyPoint(vertex, items[j].sub, eps);
        if (where === 'inside') inside += 1;
        else if (where === 'outside') outside += 1;
      }
      if (inside > 0 && outside > 0) overlapping = true;
      if (inside > 0 && outside === 0) containers[i] += 1;
    }
  }

  if (overlapping) {
    return { area: 0, cx: 0, cy: 0, overlapping: true };
  }

  let area = 0;
  let mx = 0;
  let my = 0;
  for (let i = 0; i < items.length; i += 1) {
    const weight = containers[i] % 2 === 0 ? 1 : -1;
    area += weight * items[i].area;
    mx += weight * items[i].area * items[i].centroid.cx;
    my += weight * items[i].area * items[i].centroid.cy;
  }

  if (Math.abs(area) < 1e-12) return { area: 0, cx: 0, cy: 0, overlapping: false };
  return { area: Math.abs(area), cx: mx / area, cy: my / area, overlapping: false };
}

export function bboxOfPoints(points) {
  if (!points || points.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

export const IDENTITY = [1, 0, 0, 1, 0, 0];

/** m1 ∘ m2 — m2 is applied to the point first. */
export function multiplyMatrix(m1, m2) {
  return [
    m1[0] * m2[0] + m1[2] * m2[1],
    m1[1] * m2[0] + m1[3] * m2[1],
    m1[0] * m2[2] + m1[2] * m2[3],
    m1[1] * m2[2] + m1[3] * m2[3],
    m1[0] * m2[4] + m1[2] * m2[5] + m1[4],
    m1[1] * m2[4] + m1[3] * m2[5] + m1[5],
  ];
}

export function applyMatrix(m, x, y) {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/** Parse an SVG transform list into a single matrix. */
export function parseTransform(value) {
  if (!value) return IDENTITY;
  let result = IDENTITY;
  const re = /([a-zA-Z]+)\s*\(([^)]*)\)/g;
  let match = re.exec(value);
  while (match) {
    const name = match[1];
    const args = match[2]
      .split(/[\s,]+/)
      .map(Number)
      .filter((n) => !Number.isNaN(n));
    let m = IDENTITY;
    switch (name) {
      case 'matrix':
        if (args.length === 6) m = args;
        break;
      case 'translate':
        m = [1, 0, 0, 1, args[0] || 0, args[1] || 0];
        break;
      case 'scale': {
        const sx = args[0] ?? 1;
        const sy = args[1] ?? sx;
        m = [sx, 0, 0, sy, 0, 0];
        break;
      }
      case 'rotate': {
        const rad = ((args[0] || 0) * Math.PI) / 180;
        const cos = Math.cos(rad);
        const sin = Math.sin(rad);
        const rot = [cos, sin, -sin, cos, 0, 0];
        if (args.length >= 3) {
          const [, cx, cy] = args;
          m = multiplyMatrix(
            multiplyMatrix([1, 0, 0, 1, cx, cy], rot),
            [1, 0, 0, 1, -cx, -cy],
          );
        } else {
          m = rot;
        }
        break;
      }
      case 'skewX':
        m = [1, 0, Math.tan(((args[0] || 0) * Math.PI) / 180), 1, 0, 0];
        break;
      case 'skewY':
        m = [1, Math.tan(((args[0] || 0) * Math.PI) / 180), 0, 1, 0, 0];
        break;
      default:
        break;
    }
    result = multiplyMatrix(result, m);
    match = re.exec(value);
  }
  return result;
}

/** Convert SVG primitive shapes into path data so there is one ink pipeline. */
export function shapeToPath(tag, attrs) {
  const num = (name, fallback = 0) => {
    const raw = attrs[name];
    if (raw === undefined) return fallback;
    const parsed = Number.parseFloat(raw);
    return Number.isNaN(parsed) ? fallback : parsed;
  };

  switch (tag) {
    case 'rect': {
      const x = num('x');
      const y = num('y');
      const w = num('width');
      const h = num('height');
      if (w <= 0 || h <= 0) return '';
      const rx = Math.min(num('rx', num('ry', 0)), w / 2);
      const ry = Math.min(num('ry', num('rx', 0)), h / 2);
      if (rx > 0 || ry > 0) {
        const r = Math.max(rx, 0);
        const r2 = Math.max(ry, 0);
        return [
          `M${x + r} ${y}`,
          `H${x + w - r}`,
          `A${r} ${r2} 0 0 1 ${x + w} ${y + r2}`,
          `V${y + h - r2}`,
          `A${r} ${r2} 0 0 1 ${x + w - r} ${y + h}`,
          `H${x + r}`,
          `A${r} ${r2} 0 0 1 ${x} ${y + h - r2}`,
          `V${y + r2}`,
          `A${r} ${r2} 0 0 1 ${x + r} ${y}`,
          'Z',
        ].join(' ');
      }
      return `M${x} ${y} H${x + w} V${y + h} H${x} Z`;
    }
    case 'circle':
    case 'ellipse': {
      const cx = num('cx');
      const cy = num('cy');
      const rx = tag === 'circle' ? num('r') : num('rx');
      const ry = tag === 'circle' ? num('r') : num('ry');
      if (rx <= 0 || ry <= 0) return '';
      return [
        `M${cx - rx} ${cy}`,
        `A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}`,
        `A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}`,
        'Z',
      ].join(' ');
    }
    case 'polygon':
    case 'polyline': {
      const raw = (attrs.points || '').trim();
      if (!raw) return '';
      const nums = raw.split(/[\s,]+/).map(Number);
      if (nums.length < 4) return '';
      const parts = [`M${nums[0]} ${nums[1]}`];
      for (let i = 2; i + 1 < nums.length; i += 2) parts.push(`L${nums[i]} ${nums[i + 1]}`);
      if (tag === 'polygon') parts.push('Z');
      return parts.join(' ');
    }
    case 'line':
      return `M${num('x1')} ${num('y1')} L${num('x2')} ${num('y2')}`;
    default:
      return '';
  }
}
