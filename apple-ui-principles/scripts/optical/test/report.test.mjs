import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tolFor, verdictFor, aggregateVerdict, exitCodeFor, buildReport } from '../report.mjs';

test('tolerance scales with size and clamps at both ends', () => {
  assert.equal(tolFor(10), 0.5); // 0.2 -> floor 0.5
  assert.equal(tolFor(24), 0.5); // 0.48 -> floor 0.5
  assert.equal(tolFor(48), 0.96);
  assert.equal(tolFor(120), 1.5); // 2.4 -> ceiling 1.5
  assert.equal(tolFor(0), 0.5);
});

test('verdict thresholds are tol and 3x tol', () => {
  assert.equal(verdictFor(0.4, 0.5, 'exact'), 'ok');
  assert.equal(verdictFor(0.5, 0.5, 'exact'), 'ok');
  assert.equal(verdictFor(0.51, 0.5, 'exact'), 'nudge');
  assert.equal(verdictFor(1.5, 0.5, 'exact'), 'nudge');
  assert.equal(verdictFor(1.51, 0.5, 'exact'), 'off');
});

test('heuristic findings never escalate past nudge', () => {
  assert.equal(verdictFor(9, 0.5, 'heuristic'), 'nudge');
  assert.equal(verdictFor(0.1, 0.5, 'heuristic'), 'ok');
});

test('aggregate takes the most severe verdict, a definite bug outranks a gap', () => {
  assert.equal(aggregateVerdict([{ verdict: 'ok' }, { verdict: 'nudge' }]), 'nudge');
  assert.equal(aggregateVerdict([{ verdict: 'nudge' }, { verdict: 'off' }]), 'off');
  assert.equal(
    aggregateVerdict([{ verdict: 'unknown' }, { verdict: 'off' }]),
    'off',
    'a certain defect must not be hidden behind an unverifiable check; the unknown still shows in findings',
  );
  assert.equal(aggregateVerdict([{ verdict: 'ok' }, { verdict: 'unknown' }]), 'unknown');
  assert.equal(aggregateVerdict([]), 'ok');
});

test('exit codes separate clean from broken from unverifiable', () => {
  assert.equal(exitCodeFor('ok'), 0);
  assert.equal(exitCodeFor('nudge'), 0);
  assert.equal(exitCodeFor('off'), 1);
  assert.equal(exitCodeFor('unknown'), 2);
});

test('report carries policy provenance so overrides are visible', () => {
  const builtin = buildReport({ target: 'x.svg', mode: 'standalone', findings: [] });
  assert.equal(builtin.policy_source, 'builtin');
  assert.equal(builtin.version, 1);

  const custom = buildReport({
    target: 'x.svg',
    mode: 'standalone',
    findings: [],
    policy: { source: 'custom', path: 'a11y.policy.json', toleranceScale: 2 },
  });
  assert.equal(custom.policy_source, 'custom');
  assert.equal(custom.policy_path, 'a11y.policy.json');
});

test('findings keep absolute and relative measurements side by side', () => {
  const report = buildReport({
    target: 'x.svg',
    mode: 'standalone',
    findings: [
      {
        id: 'geometry/centroid',
        layer: 'exact',
        offset: 1.2,
        basis: 48,
        evidence: 'synthetic',
      },
    ],
  });
  const [f] = report.findings;
  assert.equal(f.measured.dx, 1.2);
  assert.equal(f.relative.dx_pct, 2.5);
  assert.equal(f.verdict, 'nudge');
  assert.match(f.suggested.value, /px/);
});
