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
  // svgpath reports a lossy parse instead of throwing: `M0 0 L` yields one point
  // and an error message. Keeping that fragment would measure part of a path,
  // so the caller needs to know.
  const parseError = path.err || null;

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

  const kept = subpaths.filter((sub) => sub.length > 0);
  // `filter` returns a fresh array, so the flag has to move to it.
  if (parseError) Object.defineProperty(kept, 'parseError', { value: parseError, enumerable: false });
  return kept;
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
/**
 * How much a single outline's self-crossings can disturb its shoelace area.
 *
 * A bowtie (`M0 0 L8 8 L8 0 L0 8 Z`) has a shoelace area of exactly zero while
 * painting two triangles. Dropping it as "no area" loses ink silently, and any
 * other shape on the canvas keeps the report looking fine. A pentagram is the
 * opposite lie: shoelace counts the centre twice and reports 40% too much.
 *
 * The size of the lie is the area painted with winding ≥ 2, which the shoelace
 * formula folds in once per extra wrap. That region sits next to the crossing
 * point, so the bounding box of the two crossing segments bounds it. Returned
 * as a sum over crossings — an upper bound, which is the safe direction: the
 * caller refuses only when the disturbance could matter.
 *
 * Curves arrive here already flattened, so the polygon is implicitly closed and
 * its last vertex often lands a few ULPs away from its first. That sliver would
 * read as a genuine crossing against the opening edge, so coincident vertices
 * are collapsed before the sweep.
 */
function selfCrossingArea(poly) {
  const box = bboxOfPoints(poly);
  if (!box) return 0;
  const extent = Math.max(box.maxX - box.minX, box.maxY - box.minY, 1);
  const eps = 1e-9 * extent;

  const pts = [];
  for (const point of poly) {
    const last = pts[pts.length - 1];
    if (last && Math.hypot(point[0] - last[0], point[1] - last[1]) <= eps) continue;
    pts.push(point);
  }
  while (
    pts.length > 1 &&
    Math.hypot(pts[0][0] - pts[pts.length - 1][0], pts[0][1] - pts[pts.length - 1][1]) <= eps
  ) {
    pts.pop();
  }
  const n = pts.length;
  if (n < 4) return 0;

  let area = 0;
  for (let i = 0; i < n; i += 1) {
    const a1 = pts[i];
    const a2 = pts[(i + 1) % n];
    for (let j = i + 2; j < n; j += 1) {
      if (i === 0 && j === n - 1) continue; // adjacent through the closing edge
      const b1 = pts[j];
      const b2 = pts[(j + 1) % n];
      if (!properlyCrosses([a1, a2], [b1, b2])) continue;
      const minX = Math.min(a1[0], a2[0], b1[0], b2[0]);
      const maxX = Math.max(a1[0], a2[0], b1[0], b2[0]);
      const minY = Math.min(a1[1], a2[1], b1[1], b2[1]);
      const maxY = Math.max(a1[1], a2[1], b1[1], b2[1]);
      area += (maxX - minX) * (maxY - minY);
    }
  }
  return area;
}

/**
 * Is a self-crossing big enough to change the verdict?
 *
 * A subpath drawn with a 0.04-unit doubling-back inside a 350-unit canvas paints
 * an area the shoelace formula misses by one part in 10⁸. Refusing that would
 * throw away most real icon artwork for a rounding error. One part in a thousand
 * is the line.
 */
const SELF_CROSSING_TOLERANCE = 1e-3;

function selfCrossingMatters(poly, area) {
  const disturbed = selfCrossingArea(poly);
  if (disturbed === 0) return false;
  return disturbed > SELF_CROSSING_TOLERANCE * Math.max(area, 0);
}

/**
 * A subpath whose shoelace area cancels to zero while it still spans an area.
 *
 * `M12 12 L4 2 L2 12 L12 12 L20 2 L22 12 Z` is a figure-eight: two triangles
 * joined at (12,12) with opposite windings, so the shoelace sum is exactly zero
 * while both paint. Treating that as "no area" dropped a whole glyph and left
 * the report saying `ok` about whatever else was on the canvas.
 *
 * A truly empty fragment (`M4 4z`) also has zero area, but it spans nothing, so
 * the bounding box separates the two. Splitting the outline into loops at the
 * shared vertex would be exact, but arcs flatten to polylines that revisit their
 * own start, and telling a genuine pinch from ordinary curve noise needs more
 * than a vertex-position check. Refusing is the cheap honest answer.
 */
function cancelsToNothing(poly, sceneArea) {
  if (Math.abs(subpathSignedArea(poly)) >= 1e-12) return false;
  const box = bboxOfPoints(poly);
  if (!box) return false;
  const span = (box.maxX - box.minX) * (box.maxY - box.minY);
  if (span <= 1e-9) return false; // an empty `M4 4z` fragment spans nothing
  // Exporters leave hair-thin wiggles that cancel to zero area on their own —
  // antd's outlined Chrome has a 1.98-unit² over-and-back on an 832-unit canvas.
  // Refusing those would drop the whole logo for a rounding error.
  return span > SELF_CROSSING_TOLERANCE * Math.max(sceneArea, 1e-9);
}

/** Union bbox area of a set of subpaths — the scale a cancellation is judged on. */
function sceneAreaOf(subpaths) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const sub of subpaths) {
    const box = bboxOfPoints(sub);
    if (!box) continue;
    if (box.minX < minX) minX = box.minX;
    if (box.minY < minY) minY = box.minY;
    if (box.maxX > maxX) maxX = box.maxX;
    if (box.maxY > maxY) maxY = box.maxY;
  }
  if (!Number.isFinite(minX)) return 0;
  return (maxX - minX) * (maxY - minY);
}

export function netShape(subpaths) {
  // Two subpaths with the same outline are one region, not two. Summing them
  // doubles the area and drags the centroid towards it, so refuse instead.
  const boxes = subpaths.map((sub) => bboxOfPoints(sub));
  const areas = subpaths.map((sub) => Math.abs(subpathSignedArea(sub)));
  const sceneArea = sceneAreaOf(subpaths);
  for (let i = 0; i < subpaths.length; i += 1) {
    if (cancelsToNothing(subpaths[i], sceneArea)) {
      return { area: 0, cx: 0, cy: 0, selfIntersecting: true };
    }
  }
  // A subpath crossing itself has no shoelace area at all. The formula returns
  // the integral of the winding number, not the painted area, so a pentagram
  // comes back 2×its centre pentagon too large and a bowtie comes back zero
  // while painting two triangles. Both are silent lies — but only when the
  // doubled region is big enough to move the number.
  for (let i = 0; i < subpaths.length; i += 1) {
    if (selfCrossingMatters(subpaths[i], areas[i])) {
      return { area: 0, cx: 0, cy: 0, selfIntersecting: true };
    }
  }
  for (let i = 0; i < subpaths.length; i += 1) {
    for (let j = i + 1; j < subpaths.length; j += 1) {
      // Two fragments that paint nothing are not one outline drawn twice. Empty
      // `M4 4z` runs share a degenerate box and an area of zero, so the outline
      // test below called them duplicates and threw the whole shape away.
      if (areas[i] <= 1e-9 || areas[j] <= 1e-9) continue;
      if (sameOutline(boxes[i], boxes[j], areas[i], areas[j])) {
        return { area: 0, cx: 0, cy: 0, overlapping: true };
      }
    }
  }

  // Winding only carries meaning *inside* another outline. Count it properly:
  // the winding number just outside a subpath is the sum of its ancestors'
  // directions, and just inside it is that plus its own. A region is painted
  // when its winding is non-zero, so a subpath contributes its area exactly when
  // crossing its own boundary flips the paint on or off.
  //
  //   weight = fill(winding inside) − fill(winding outside)
  //
  // Two levels same-direction: outside 0 → inside +1 gives +1, and the inner one
  // adds zero. Two levels opposite: +1 then 0 gives −1, a hole. Three levels
  // (hole inside hole inside island) comes out +1 again, which a rule that only
  // compares against the immediate parent gets backwards.
  const signed = subpaths.map((sub) => subpathSignedArea(sub));
  const parentOf = subpaths.map((sub, i) => {
    let nearest = -1;
    for (let j = 0; j < subpaths.length; j += 1) {
      if (i === j) continue;
      if (!boxContainsBox(boxes[j], boxes[i], 1e-6)) continue;
      // "No vertex outside" is not enough: a notch that sits in a concavity with
      // every vertex on the boundary is not inside. Require one strict interior
      // vertex, the same test even-odd uses.
      let strictInside = false;
      let outside = false;
      for (const vertex of sub) {
        const where = classifyPoint(vertex, subpaths[j], 1e-6);
        if (where === 'inside') strictInside = true;
        else if (where === 'outside') {
          outside = true;
          break;
        }
      }
      if (outside || !strictInside) continue;
      if (nearest === -1 || areas[j] < areas[nearest]) nearest = j;
    }
    return nearest;
  });

  const fill = (winding) => (winding !== 0 ? 1 : 0);
  // Iterative on purpose: the chain is as deep as the artwork nests, and a
  // recursive walk turns a legal 6000-ring file into a stack overflow.
  const outsideWinding = new Array(subpaths.length).fill(null);
  const windingAt = (index) => {
    if (outsideWinding[index] !== null) return outsideWinding[index];
    const chain = [];
    let cursor = index;
    while (cursor !== -1 && outsideWinding[cursor] === null) {
      chain.push(cursor);
      cursor = parentOf[cursor];
    }
    let value = cursor === -1 ? 0 : outsideWinding[cursor];
    for (let i = chain.length - 1; i >= 0; i -= 1) {
      const node = chain[i];
      const parent = parentOf[node];
      // Containment is strictly by area, so this chain always terminates.
      if (parent !== -1) value += Math.sign(signed[parent]);
      outsideWinding[node] = value;
    }
    return outsideWinding[index];
  };

  let area = 0;
  let mx = 0;
  let my = 0;
  for (const [index, sub] of subpaths.entries()) {
    const { cx, cy } = subpathCentroid(sub);
    const outer = windingAt(index);
    const weight = fill(outer + Math.sign(signed[index])) - fill(outer);
    if (weight === 0) continue;
    area += weight * areas[index];
    mx += cx * weight * areas[index];
    my += cy * weight * areas[index];
  }
  if (Math.abs(area) < 1e-12) {
    // Outlines that cancel each other exactly — a container and a hole the same
    // size — paint nothing, which is a real (and reported) `no-ink` case. Reach
    // here only after every subpath was individually representable.
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

/** Orientation sign of the triplet p→q→r (0 for collinear). */
/**
 * Two subpaths that describe the same region.
 *
 * Comparing outlines vertex by vertex would need a curve-aware equality test;
 * equal bounding box plus equal absolute area is a cheap, deliberately
 * conservative stand-in. A false positive costs a refusal, never a wrong number.
 */
function sameOutline(a, b, areaA, areaB) {
  if (!a || !b) return false;
  const eps = 1e-6;
  if (Math.abs(a.minX - b.minX) > eps || Math.abs(a.maxX - b.maxX) > eps) return false;
  if (Math.abs(a.minY - b.minY) > eps || Math.abs(a.maxY - b.maxY) > eps) return false;
  return Math.abs(areaA - areaB) <= 1e-6 * Math.max(1, areaA);
}

function boxesIntersect(a, b) {
  if (!a || !b) return false;
  return a.minX <= b.maxX && b.minX <= a.maxX && a.minY <= b.maxY && b.minY <= a.maxY;
}

function boxContainsBox(outer, inner, eps) {
  if (!outer || !inner) return false;
  return (
    inner.minX >= outer.minX - eps &&
    inner.minY >= outer.minY - eps &&
    inner.maxX <= outer.maxX + eps &&
    inner.maxY <= outer.maxY + eps
  );
}

function orientation([px, py], [qx, qy], [rx, ry]) {  const value = (qy - py) * (rx - qx) - (qx - px) * (ry - qy);
  if (Math.abs(value) < 1e-9) return 0;
  return Math.sign(value);
}

/** True only for a proper crossing; touching endpoints do not count. */
function properlyCrosses([a1, a2], [b1, b2]) {
  const o1 = orientation(a1, a2, b1);
  const o2 = orientation(a1, a2, b2);
  const o3 = orientation(b1, b2, a1);
  const o4 = orientation(b1, b2, a2);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

function outlinesCross(a, b) {
  for (let i = 0; i < a.length; i += 1) {
    const a1 = a[i];
    const a2 = a[(i + 1) % a.length];
    for (let j = 0; j < b.length; j += 1) {
      const b1 = b[j];
      const b2 = b[(j + 1) % b.length];
      if (properlyCrosses([a1, a2], [b1, b2])) return true;
    }
  }
  return false;
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
    box: bboxOfPoints(sub),
  }));
  const eps = 1e-6;

  // Even-odd has the same blind spot: it counts boundary crossings, and a
  // subpath that crosses itself produces crossings the containment test never
  // sees. A bowtie is the cheap case (zero shoelace area, non-zero paint).
  const sceneArea = sceneAreaOf(subpaths);
  for (const item of items) {
    if (selfCrossingMatters(item.sub, item.area) || cancelsToNothing(item.sub, sceneArea)) {
      return { area: 0, cx: 0, cy: 0, overlapping: false, selfIntersecting: true };
    }
  }

  const containers = items.map(() => 0);
  let overlapping = false;

  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      // Identical outlines cancel to nothing under even-odd, but they leave every
      // vertex `boundary` and no containment, so the nesting pass below would
      // count both at full weight. Catch them first — but only when both paint
      // something, or a pair of empty `M…z` runs at one point looks identical.
      if (items[i].area > 1e-9 && items[j].area > 1e-9 &&
          sameOutline(items[i].box, items[j].box, items[i].area, items[j].area)) {
        overlapping = true;
        continue;
      }
      // Cheap reject: disjoint bounding boxes cannot cross and cannot nest.
      if (!boxesIntersect(items[i].box, items[j].box)) continue;
      // Crossing outlines are never a nesting relation, even when no vertex of
      // one lands inside the other (a plus sign, for instance).
      if (outlinesCross(items[i].sub, items[j].sub)) overlapping = true;
    }
  }

  for (let i = 0; i < items.length; i += 1) {
    for (let j = 0; j < items.length; j += 1) {
      if (i === j) continue;
      // A vertex of `i` can only be inside `j` if `i`'s box is inside `j`'s.
      if (!boxContainsBox(items[j].box, items[i].box, eps)) continue;
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

  // Exact cancellation here is the container-and-hole case, same as nonzero.
  if (Math.abs(area) < 1e-12) return { area: 0, cx: 0, cy: 0, overlapping: false };  return { area: Math.abs(area), cx: mx / area, cy: my / area, overlapping: false };
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

/**
 * Parse an SVG transform list into a single matrix.
 * @returns {number[]|null} `null` when any argument cannot be resolved to a
 *   number. Dropping the bad argument would shift the rest left — `translate(10%,8)`
 *   would silently become `translate(8,0)` — so the whole transform is refused.
 */
export function parseTransform(value) {
  if (!value) return IDENTITY;
  let result = IDENTITY;
  const re = /([a-zA-Z]+)\s*\(([^)]*)\)/g;
  // Anything the function list does not consume is not a transform. Splicing
  // it out silently kept `translate(10,10) garbage` looking like a clean
  // translation, which is a wrong position with no warning. Commas *between*
  // functions are legal in the CSS form (`translate(1px,2px), rotate(45deg)`),
  // so they are the one separator allowed to survive.
  if (
    String(value)
      .replace(re, '')
      .replace(/,/g, ' ')
      .trim() !== ''
  ) {
    return null;
  }
  re.lastIndex = 0;
  let match = re.exec(value);
  while (match) {
    const name = match[1];
    const args = [];
    for (const raw of match[2].split(/[\s,]+/).filter((part) => part !== '')) {
      if (name === 'rotate' || name === 'skewX' || name === 'skewY') {
        const m = /^(-?\d*\.?\d+)(deg|grad|rad|turn)?$/.exec(raw);
        if (!m) return null;
        let angle = Number.parseFloat(m[1]);
        if (m[2] === 'rad') angle = (angle * 180) / Math.PI;
        else if (m[2] === 'grad') angle = angle * 0.9;
        else if (m[2] === 'turn') angle = angle * 360;
        args.push(angle);
      } else {
        // The CSS form writes lengths with a unit. On an SVG element `1px` is
        // one user unit (`transform-origin` is the origin), so the number is
        // the same either way; `em` and `%` are not, and stay refused.
        const m = /^(-?\d*\.?\d+)(px)?$/.exec(raw);
        if (!m) return null;
        args.push(Number.parseFloat(m[1]));
      }
    }
    let m = IDENTITY;
    switch (name) {
      case 'matrix':
        if (args.length === 6) m = args;
        else return null;
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
        return null;
    }
    result = multiplyMatrix(result, m);
    match = re.exec(value);
  }
  return result;
}

/**
 * Parse a geometry length. Returns `null` for anything this static pass cannot
 * turn into user units.
 *
 * The important case is `%`: a percentage is relative to the nearest viewport,
 * and `parseFloat("100%")` is `100` — a number indistinguishable from a real
 * 100-unit rectangle once it reaches the area integral. That turns a background
 * rect into ink at the canvas corner and reports a centred icon as 158% off.
 * `em`, `pt` and friends depend on a context we do not have either. Absent is
 * also `null`; callers apply their own default.
 */
export function parseLength(raw) {
  if (raw === undefined || raw === null) return null;
  const s = String(raw).trim();
  if (s === '') return null;
  const match = /^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(px)?$/i.exec(s);
  return match ? Number(match[1]) : null;
}

const SHAPE_LENGTH_ATTRS = {
  rect: ['x', 'y', 'width', 'height', 'rx', 'ry'],
  circle: ['cx', 'cy', 'r'],
  ellipse: ['cx', 'cy', 'rx', 'ry'],
  line: ['x1', 'y1', 'x2', 'y2'],
  polygon: [],
  polyline: [],
};

/**
 * Convert SVG primitive shapes into path data so there is one ink pipeline.
 *
 * Returns `{ d, unparsed }` rather than a string: a length this pass cannot
 * resolve has to surface as "no measurement" upstream, not as a shape that
 * silently collapses to zero or, worse, to a wrong number.
 */
export function shapeToPath(tag, attrs) {
  for (const name of SHAPE_LENGTH_ATTRS[tag] || []) {
    if (attrs[name] !== undefined && parseLength(attrs[name]) === null) {
      return { d: '', unparsed: true };
    }
  }
  const num = (name, fallback = 0) => {
    const parsed = parseLength(attrs[name]);
    return parsed === null ? fallback : parsed;
  };

  switch (tag) {
    case 'rect': {
      const x = num('x');
      const y = num('y');
      const w = num('width');
      const h = num('height');
      if (w <= 0 || h <= 0) return { d: '', unparsed: false, empty: true };
      const rx = Math.min(num('rx', num('ry', 0)), w / 2);
      const ry = Math.min(num('ry', num('rx', 0)), h / 2);
      if (rx > 0 || ry > 0) {
        const r = Math.max(rx, 0);
        const r2 = Math.max(ry, 0);
        return {
          d: [
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
          ].join(' '),
          unparsed: false,
        };
      }
      return { d: `M${x} ${y} H${x + w} V${y + h} H${x} Z`, unparsed: false };
    }
    case 'circle':
    case 'ellipse': {
      const cx = num('cx');
      const cy = num('cy');
      const rx = tag === 'circle' ? num('r') : num('rx');
      const ry = tag === 'circle' ? num('r') : num('ry');
      if (rx <= 0 || ry <= 0) return { d: '', unparsed: false, empty: true };
      return {
        d: [
          `M${cx - rx} ${cy}`,
          `A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}`,
          `A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}`,
          'Z',
        ].join(' '),
        unparsed: false,
      };
    }
    case 'polygon':
    case 'polyline': {
      const raw = (attrs.points || '').trim();
      if (!raw) return { d: '', unparsed: false, empty: true };
      const nums = raw.split(/[\s,]+/).map(Number);
      if (nums.length < 4) return { d: '', unparsed: false, empty: true };
      if (!nums.every(Number.isFinite)) return { d: '', unparsed: true };
      const parts = [`M${nums[0]} ${nums[1]}`];
      for (let i = 2; i + 1 < nums.length; i += 2) parts.push(`L${nums[i]} ${nums[i + 1]}`);
      if (tag === 'polygon') parts.push('Z');
      return { d: parts.join(' '), unparsed: false };
    }
    case 'line': {
      const x1 = num('x1');
      const y1 = num('y1');
      const x2 = num('x2');
      const y2 = num('y2');
      // A zero-length line paints nothing with butt caps; saying so keeps it out
      // of the "could not parse" bucket, which would refuse the whole file.
      if (x1 === x2 && y1 === y2) return { d: '', unparsed: false, empty: true };
      return { d: `M${x1} ${y1} L${x2} ${y2}`, unparsed: false };
    }
    default:
      return { d: '', unparsed: false, empty: true };
  }
}

/**
 * viewBox -> viewport mapping (SVG 1.1 §7.7).
 *
 * Icons routinely nest `<svg viewBox>` or instantiate `<symbol viewBox>` through
 * `<use>`. Children of such a node are expressed in the *inner* user space, so
 * without this matrix every measurement inside it is in the wrong units — which
 * reads as a large offset in the report and as "the artwork is off-centre" in
 * the fix. `preserveAspectRatio` defaults to `xMidYMid meet`.
 */
export function viewBoxMatrix(vb, rect, preserveAspectRatio = '') {
  const w = rect.w;
  const h = rect.h;
  if (!(vb.w > 0) || !(vb.h > 0)) return [1, 0, 0, 1, rect.x, rect.y];

  const par = String(preserveAspectRatio || '').trim();
  if (par.toLowerCase().startsWith('none')) {
    const sx = w / vb.w;
    const sy = h / vb.h;
    return [sx, 0, 0, sy, rect.x - vb.x * sx, rect.y - vb.y * sy];
  }

  const parts = par.split(/\s+/);
  const align = parts[0] && /^(x(Min|Mid|Max))(Y(Min|Mid|Max))$/.test(parts[0]) ? parts[0] : 'xMidYMid';
  const meetOrSlice = (parts[1] || 'meet').toLowerCase();

  const scale =
    meetOrSlice === 'slice'
      ? Math.max(w / vb.w, h / vb.h)
      : Math.min(w / vb.w, h / vb.h);

  const fx = align.startsWith('xMin') ? 0 : align.startsWith('xMax') ? 1 : 0.5;
  const fy = align.endsWith('YMin') ? 0 : align.endsWith('YMax') ? 1 : 0.5;

  const tx = rect.x + (w - vb.w * scale) * fx - vb.x * scale;
  const ty = rect.y + (h - vb.h * scale) * fy - vb.y * scale;
  return [scale, 0, 0, scale, tx, ty];
}
