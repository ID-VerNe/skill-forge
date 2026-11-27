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
import { exitCodeFor, summarise } from './report.mjs';

const USAGE = `optical — optical alignment checks

Usage
  node cli.mjs check <path...> [options]

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

function usage(message) {
  const err = new Error(message);
  err.usage = true;
  return err;
}

function parseArgs(argv) {
  const opts = { mode: 'auto', json: false, explain: false, policy: null, paths: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === 'check') continue;
    else if (arg === '--json') opts.json = true;
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
  const raw = await readFile(path, 'utf8');
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw usage(`--policy is not valid JSON: ${path}`);
  }
  const scale = Number(parsed.toleranceScale);
  return {
    source: 'custom',
    path: basename(path),
    toleranceScale: Number.isFinite(scale) && scale > 0 ? scale : 1,
  };
}

async function checkPath(path, opts, policy) {
  const info = await stat(path);
  if (info.isDirectory()) {
    const report = await checkIconSet(path);
    return applyPolicy(report, policy);
  }
  const ext = extname(path).toLowerCase();
  if (ext === '.svg') return applyPolicy(await checkIconFile(path, { mode: opts.mode }), policy);
  const text = await readFile(path, 'utf8');
  if (ext === '.css') return applyPolicy(checkCss(text, { target: basename(path) }), policy);
  if (ext === '.tsx' || ext === '.jsx') {
    return applyPolicy(checkTsx(text, { target: basename(path) }), policy);
  }
  throw usage(`unsupported file type: ${path}`);
}

function applyPolicy(report, policy) {
  if (!policy) return report;
  const scale = policy.toleranceScale ?? 1;
  const findings = report.findings.map((f) => {
    if (f.layer !== 'exact' || !f.relative) return f;
    const base = f.relative.basis || 24;
    const tol = Math.min(1.5, Math.max(0.5, 0.02 * base)) * scale;
    const severity = Math.abs(f.measured.dx) >= Math.abs(f.measured.dy) ? f.measured.dx : f.measured.dy;
    const verdict = Math.abs(severity) <= tol ? 'ok' : Math.abs(severity) <= 3 * tol ? 'nudge' : 'off';
    return { ...f, verdict };
  });
  const order = { ok: 0, nudge: 1, unknown: 2, off: 3 };
  const verdict = findings.reduce(
    (worst, f) => (order[f.verdict] > order[worst] ? f.verdict : worst),
    'ok',
  );
  return { ...report, findings, verdict, policy_source: 'custom', policy_path: policy.path };
}

function printText(reports, explain) {
  const lines = [];
  for (const report of reports) {
    lines.push(summarise(report));
    for (const f of report.findings) {
      if (f.verdict === 'ok' && !explain) continue;
      const px = Math.abs(f.measured.dx) >= Math.abs(f.measured.dy) ? f.measured.dx : f.measured.dy;
      const pct = Math.abs(f.measured.dx) >= Math.abs(f.measured.dy) ? f.relative?.dx_pct : f.relative?.dy_pct;
      const amount = `${px > 0 ? '+' : ''}${px}px${pct === undefined ? '' : ` (${pct}%)`}`;
      lines.push(`  ${f.verdict.padEnd(7)} ${f.id.padEnd(28)} ${amount.padEnd(18)} ${f.suggested?.value ?? ''}`);
      if (explain) lines.push(`          ${f.evidence}`);
    }
  }
  if (reports.some((r) => r.policy_source === 'custom')) {
    lines.push('note: thresholds came from a custom policy file');
  }
  return lines.join('\n');
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
    if (opts.help || opts.paths.length === 0) {
      process.stdout.write(`${USAGE}\n`);
      return opts.help ? 0 : 64;
    }
    const policy = await loadPolicy(opts.policy);
    const reports = [];
    for (const path of opts.paths) {
      reports.push(await checkPath(resolve(path), opts, policy));
    }

    if (opts.json) {
      process.stdout.write(`${JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2)}\n`);
    } else {
      process.stdout.write(`${printText(reports, opts.explain)}\n`);
    }

    const order = { ok: 0, nudge: 1, unknown: 2, off: 3 };
    const worst = reports.reduce((w, r) => (order[r.verdict] > order[w] ? r.verdict : w), 'ok');
    return exitCodeFor(worst);
  } catch (err) {
    process.stderr.write(`optical: ${err.message}\n`);
    return err.usage ? 64 : 2;
  }
}

main().then((code) => {
  process.exitCode = code;
});
