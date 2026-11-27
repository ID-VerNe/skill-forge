#!/usr/bin/env node
// optical — deterministic checks for the optical alignment rules in SKILL.md.
//
// Exit codes are part of the contract:
//   0  ok / nudge        nothing must change
//   1  off               a certain defect
//   2  unknown           could not be verified (missing context, font, parser)
//   64 usage error

import { stat, readFile } from 'node:fs/promises';
import { basename, extname, resolve } from 'node:path';
import { checkIconFile, checkIconSet } from './icon.mjs';
import { checkCss, checkTsx } from './rule.mjs';
import { capMidpointDelta, readFontMetrics } from './font.mjs';
import { exitCodeFor, summarise, tolFor } from './report.mjs';

const USAGE = `optical — optical alignment checks

Usage
  node cli.mjs check <path...> [options]
  node cli.mjs font <font.ttf|.otf> --size <px> [--line-height <n>]

Options
  --mode <auto|standalone|inline|keyline>   default: auto
  --json                                    machine-readable output
  --explain                                 include evidence for every finding
  --policy <file>                           load a custom tolerance policy

Exit codes
  0 ok/nudge   1 off   2 unknown   64 usage error

Tolerances are deliberately not a CLI flag. If a project genuinely needs a
different curve, pass --policy and the report will say so.`;

const MODES = new Set(['auto', 'standalone', 'inline', 'keyline']);
const SEVERITY = { ok: 0, nudge: 1, unknown: 2, off: 3 };

function usage(message) {
  const err = new Error(message);
  err.usage = true;
  return err;
}

function parseArgs(argv) {
  const opts = {
    command: 'check',
    mode: 'auto',
    json: false,
    explain: false,
    policy: null,
    size: null,
    lineHeight: null,
    paths: [],
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === 'check' || arg === 'font') {
      opts.command = arg;
    } else if (arg === '--json') opts.json = true;
    else if (arg === '--explain') opts.explain = true;
    else if (arg === '--mode') {
      const value = argv[i + 1];
      if (!MODES.has(value)) throw usage(`unknown --mode: ${value}`);
      opts.mode = value;
      i += 1;
    } else if (arg.startsWith('--mode=')) {
      const value = arg.slice(7);
      if (!MODES.has(value)) throw usage(`unknown --mode: ${value}`);
      opts.mode = value;
    } else if (arg === '--policy') {
      opts.policy = argv[i + 1];
      if (!opts.policy) throw usage('--policy needs a file');
      i += 1;
    } else if (arg === '--size') {
      opts.size = Number.parseFloat(argv[i + 1]);
      if (!Number.isFinite(opts.size)) throw usage('--size needs a number');
      i += 1;
    } else if (arg === '--line-height') {
      opts.lineHeight = Number.parseFloat(argv[i + 1]);
      if (!Number.isFinite(opts.lineHeight)) throw usage('--line-height needs a number');
      i += 1;
    } else if (arg === '--tolerance') {
      throw usage('--tolerance is not a thing: thresholds are fixed. Use --policy <file>.');
    } else if (arg === '--help' || arg === '-h') {
      opts.help = true;
    } else if (arg.startsWith('-')) {
      throw usage(`unknown option: ${arg}`);
    } else {
      opts.paths.push(arg);
    }
  }
  return opts;
}

async function loadPolicy(path) {
  if (!path) return undefined;
  let raw;
  try {
    raw = await readFile(path, 'utf8');
  } catch {
    throw usage(`--policy file cannot be read: ${path}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw usage(`--policy is not valid JSON: ${path}`);
  }
  if (parsed.toleranceScale !== undefined) {
    const scale = Number(parsed.toleranceScale);
    if (!Number.isFinite(scale) || scale <= 0) {
      throw usage(`--policy toleranceScale must be a positive number, got: ${parsed.toleranceScale}`);
    }
  }
  return {
    source: 'custom',
    path: basename(path),
    toleranceScale: Number(parsed.toleranceScale ?? 1),
  };
}

async function checkPath(path, opts) {
  const info = await stat(path);
  if (info.isDirectory()) {
    // Only `auto` and `keyline` make sense for a directory; silently running the
    // keyline check for `--mode standalone` would answer a question nobody asked.
    if (opts.mode !== 'auto' && opts.mode !== 'keyline') {
      throw usage(`--mode ${opts.mode} needs a file; a directory only supports keyline`);
    }
    return checkIconSet(path);
  }
  if (opts.mode === 'keyline') {
    throw usage('--mode keyline needs a directory, not a single file');
  }
  const ext = extname(path).toLowerCase();
  if (ext === '.svg') return checkIconFile(path, { mode: opts.mode });
  const text = await readFile(path, 'utf8');
  if (ext === '.css') return checkCss(text, { target: basename(path) });
  if (ext === '.tsx' || ext === '.jsx') return checkTsx(text, { target: basename(path) });
  throw usage(`unsupported file type: ${path}`);
}

/**
 * A policy may only rescale pixel comparisons. Categorical verdicts (`unknown`,
 * and `off` produced by a rule rather than a measurement) are statements about
 * the evidence, not numbers to be widened.
 */
function applyPolicy(report, policy) {
  if (!policy) return report;
  const scale = policy.toleranceScale ?? 1;
  const findings = report.findings.map((f) => {
    if (f.forced || f.categorical || f.layer !== 'exact' || !f.relative) return f;
    const base = f.relative.basis || 24;
    const tol = tolFor(base) * scale;
    const severity =
      Math.abs(f.measured.dx) >= Math.abs(f.measured.dy) ? f.measured.dx : f.measured.dy;
    const verdict =
      Math.abs(severity) <= tol ? 'ok' : Math.abs(severity) <= 3 * tol ? 'nudge' : 'off';
    return { ...f, verdict };
  });
  const verdict = findings.reduce(
    (worst, f) => (SEVERITY[f.verdict] > SEVERITY[worst] ? f.verdict : worst),
    'ok',
  );
  return { ...report, findings, verdict, policy_source: 'custom', policy_path: policy.path };
}

function amountFor(f) {
  if (f.categorical || !f.relative) return '—';
  const { dx, dy } = f.measured;
  const useX = Math.abs(dx) >= Math.abs(dy);
  const dominant = useX ? dx : dy;
  const pct = useX ? f.relative.dx_pct : f.relative.dy_pct;
  const sign = (n) => `${n > 0 ? '+' : ''}${n}`;
  // Both axes are printed when both carry signal: a suggestion of
  // "0px / 1.67px" next to a measured "-1.67px" reads like a contradiction.
  const pair = Math.abs(dx) >= 0.005 && Math.abs(dy) >= 0.005 ? `${sign(dx)}px / ${sign(dy)}px` : null;
  const amount = pair ?? `${sign(dominant)}px`;
  return `${amount} (${pct}%)`;
}

function printText(reports, explain) {
  const lines = [];
  for (const report of reports) {
    lines.push(summarise(report));
    for (const f of report.findings) {
      if (f.verdict === 'ok' && !explain) continue;
      lines.push(
        `  ${f.verdict.padEnd(7)} ${f.id.padEnd(30)} ${amountFor(f).padEnd(16)} ${f.suggested?.value ?? ''}`,
      );
      if (explain) lines.push(`          ${f.evidence}`);
    }
  }
  if (reports.some((r) => r.policy_source === 'custom')) {
    lines.push('note: thresholds came from a custom policy file');
  }
  return lines.join('\n');
}

async function runFont(opts) {
  if (opts.paths.length !== 1) throw usage('font needs exactly one font file');
  if (!(opts.size > 0)) throw usage('font needs --size <px>');
  const buffer = await readFile(resolve(opts.paths[0]));
  const metrics = readFontMetrics(buffer);
  const delta = capMidpointDelta(metrics, {
    fontSize: opts.size,
    lineHeight: opts.lineHeight ?? 1.5,
  });
  const direction = delta < 0 ? 'above' : 'below';
  const out = {
    target: basename(opts.paths[0]),
    metrics,
    fontSize: opts.size,
    cap_midpoint_delta_px: Math.round(delta * 1000) / 1000,
    reading: `letters sit ${Math.abs(delta).toFixed(2)}px ${direction} the line box centre`,
  };
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
  } else {
    process.stdout.write(
      `${out.target}: cap midpoint ${out.cap_midpoint_delta_px}px — ${out.reading}\n`,
    );
  }
  return 0;
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
    if (opts.help) {
      process.stdout.write(`${USAGE}\n`);
      return 0;
    }
    if (opts.paths.length === 0) {
      process.stdout.write(`${USAGE}\n`);
      return 64;
    }
    if (opts.command === 'font') return await runFont(opts);

    // Silently ignoring these would let `check x.svg --size 48` look like it took
    // effect. They belong to the `font` subcommand.
    if (opts.size !== null || opts.lineHeight !== null) {
      throw usage('--size and --line-height only apply to `font`; `check` derives size from the file');
    }

    const policy = await loadPolicy(opts.policy);
    const reports = [];
    for (const path of opts.paths) {
      reports.push(applyPolicy(await checkPath(resolve(path), opts), policy));
    }

    if (opts.json) {
      process.stdout.write(`${JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2)}\n`);
    } else {
      process.stdout.write(`${printText(reports, opts.explain)}\n`);
    }

    const worst = reports.reduce(
      (w, r) => (SEVERITY[r.verdict] > SEVERITY[w] ? r.verdict : w),
      'ok',
    );
    return exitCodeFor(worst);
  } catch (err) {
    process.stderr.write(`optical: ${err.message}\n`);
    return err.usage ? 64 : 2;
  }
}

main().then((code) => {
  process.exitCode = code;
});
