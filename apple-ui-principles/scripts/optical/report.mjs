// Verdict contract.
//
// Three things are enforced here and nowhere else:
//   1. tolerance is a function of size, never a CLI flag
//   2. heuristic findings can never block (they cap at `nudge`)
//   3. `unknown` is a first-class verdict with its own exit code
//
// See references/optical-model.md for the derivation of the tolerance curve.

export const OK = 'ok';
export const NUDGE = 'nudge';
export const OFF = 'off';
export const UNKNOWN = 'unknown';

// off outranks unknown on purpose: a certain defect must be fixed first, while
// an unverifiable check stays visible in the findings list on every run.
const SEVERITY = { ok: 0, nudge: 1, unknown: 2, off: 3 };
const EXIT = { ok: 0, nudge: 0, off: 1, unknown: 2 };

/** tol = clamp(0.02 * size, 0.5px, 1.5px) */
export function tolFor(size) {
  const s = Number.isFinite(size) ? Math.abs(size) : 0;
  return Math.min(1.5, Math.max(0.5, 0.02 * s));
}

/**
 * @param {number} deltaAbs absolute offset in CSS px
 * @param {number} tol tolerance for this element's size
 * @param {'exact'|'heuristic'} layer
 */
export function verdictFor(deltaAbs, tol, layer = 'exact') {
  const d = Math.abs(deltaAbs);
  let verdict;
  if (d <= tol) verdict = OK;
  else if (d <= 3 * tol) verdict = NUDGE;
  else verdict = OFF;
  if (layer === 'heuristic' && verdict === OFF) verdict = NUDGE;
  return verdict;
}

/**
 * A certain defect (`off`) outranks an unverifiable check (`unknown`): the fix
 * is mandatory either way, and the gap stays visible in the findings list.
 */
export function aggregateVerdict(findings = []) {
  let worst = OK;
  for (const f of findings) {
    const verdict = f.verdict || OK;
    if ((SEVERITY[verdict] ?? 0) > (SEVERITY[worst] ?? 0)) worst = verdict;
  }
  return worst;
}

export function exitCodeFor(verdict) {
  return EXIT[verdict] ?? 2;
}

function round(n, digits = 3) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

function normaliseFinding(raw, policyScale) {
  if (raw.measured) {
    // Already in report shape (used by the rule layer, which measures directly).
    return {
      ...raw,
      measured: {
        dx: round(raw.measured.dx ?? 0),
        dy: round(raw.measured.dy ?? 0),
        unit: raw.measured.unit || 'px',
      },
      relative: raw.relative || null,
      verdict: raw.verdict || OK,
    };
  }

  const dx = raw.offset ?? 0;
  const dy = raw.offsetY ?? 0;
  const basis = raw.basis && raw.basis > 0 ? raw.basis : 24;
  const tol = tolFor(basis) * policyScale;
  const primary = Math.max(Math.abs(dx), Math.abs(dy));
  const layer = raw.layer || 'exact';

  return {
    id: raw.id,
    layer,
    verdict: raw.forcedVerdict || verdictFor(primary, tol, layer),
    measured: { dx: round(dx), dy: round(dy), unit: 'px' },
    relative: {
      dx_pct: round((dx / basis) * 100, 2),
      dy_pct: round((dy / basis) * 100, 2),
      basis,
    },
    suggested: raw.suggested || { kind: 'nudge', value: `${round(-dx, 2)}px` },
    evidence: raw.evidence || '',
    ...(raw.meta || {}),
  };
}

/**
 * @param {object} args
 * @param {string} args.target
 * @param {string} args.mode
 * @param {Array} args.findings raw findings (offset/basis) or report-shape ones
 * @param {object} [args.policy] {source,path,toleranceScale}
 * @param {object} [args.meta] extra top-level fields (strokeOnly, ink, ...)
 */
export function buildReport({ target, mode, findings = [], policy, meta = {} }) {
  const scale = policy?.toleranceScale && policy.toleranceScale > 0 ? policy.toleranceScale : 1;
  const normalised = findings.map((f) => normaliseFinding(f, scale));
  const report = {
    version: 1,
    target,
    mode,
    verdict: aggregateVerdict(normalised),
    findings: normalised,
    policy_source: policy?.source || 'builtin',
    ...meta,
  };
  if (policy?.path) report.policy_path = policy.path;
  return report;
}

/** One-line human summary, used by the CLI when --json is absent. */
export function summarise(report) {
  const counts = report.findings.reduce((acc, f) => {
    acc[f.verdict] = (acc[f.verdict] || 0) + 1;
    return acc;
  }, {});
  const parts = Object.entries(counts)
    .map(([k, v]) => `${v} ${k}`)
    .sort();
  const detail = parts.length ? ` (${parts.join(', ')})` : '';
  return `${report.verdict.toUpperCase()} ${report.target}${detail}`;
}
