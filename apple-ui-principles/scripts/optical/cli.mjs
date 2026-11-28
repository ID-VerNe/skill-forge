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
import { exitCodeFor, summarise, tolFor, buildReport } from './report.mjs';
import { syncInstalls, formatSync } from '../sync-installs.mjs';

const USAGE = `optical — optical alignment checks

Usage
  node cli.mjs check <path...> [options]
  node cli.mjs check --self-heal [--home <dir>] [--skill-dir <dir>]
  node cli.mjs font <font.ttf|.otf> --size <px> [--line-height <n>]

Options
  --mode <auto|standalone|inline|keyline>   default: auto
  --json                                    machine-readable output
  --explain                                 include evidence for every finding
  --policy <file>                           load a custom tolerance policy
  --self-heal                               re-point installed copies (check only)
  --home <dir>                              with --self-heal: the home to repair
  --skill-dir <dir>                         with --self-heal: the copy to sync from

--self-heal repairs the copies other agents installed from this directory.
Junctions resolve by path, so they are live after every "git pull"; the Gemini
CLI install is a tree of hardlinks, and git breaks those silently whenever it
replaces a file. The repair is idempotent, only touches positions that already
exist, and reports on stderr so --json stays parseable. Give it no paths to heal
without running a check; with --json that prints {"version":1,"self_heal":...}.
It exits 2 when it cannot finish, and 64 when it was pointed at a copy instead
of the repository.

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

/** Bare decimal numbers only: `Number('0x10')` is 16 but not a CLI number here. */
function cliNumber(raw, label) {
  const s = String(raw ?? '').trim();
  if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(s)) {
    throw usage(`${label} needs a number`);
  }
  const value = Number(s);
  if (!Number.isFinite(value)) throw usage(`${label} needs a number`);
  return value;
}

/**
 * `--flag value` or `--flag=value`, refusing a value that is really the next
 * option. `--home --skill-dir X` would otherwise bind "home" to a flag name and
 * quietly sync nothing.
 */
function pairValue(argv, index, flag, label) {
  const arg = argv[index];
  if (arg.startsWith(`${flag}=`)) {
    const inline = arg.slice(flag.length + 1);
    if (!inline) throw usage(`${flag} needs ${label}`);
    return { value: inline, consumed: 0 };
  }
  const next = argv[index + 1];
  if (!next || next.startsWith('-')) throw usage(`${flag} needs ${label}`);
  return { value: next, consumed: 1 };
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
    selfHeal: false,
    home: null,
    skillDir: null,
    paths: [],
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === 'check' || arg === 'font') {
      opts.command = arg;
    } else if (arg === '--json') opts.json = true;
    else if (arg === '--explain') opts.explain = true;
    else if (arg === '--self-heal') opts.selfHeal = true;
    else if (arg === '--home' || arg.startsWith('--home=')) {
      const { value, consumed } = pairValue(argv, i, '--home', 'a directory');
      opts.home = value;
      i += consumed;
    } else if (arg === '--skill-dir' || arg.startsWith('--skill-dir=')) {
      const { value, consumed } = pairValue(argv, i, '--skill-dir', 'a directory');
      opts.skillDir = value;
      i += consumed;
    } else if (arg === '--mode') {
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
      opts.size = cliNumber(argv[i + 1], '--size');
      i += 1;
    } else if (arg === '--line-height') {
      opts.lineHeight = cliNumber(argv[i + 1], '--line-height');
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
  // Silently accepting these would let `check x.css --home /tmp` look like it
  // repointed something. They only mean anything alongside --self-heal.
  if (!opts.selfHeal && (opts.home !== null || opts.skillDir !== null)) {
    throw usage('--home and --skill-dir only apply to --self-heal');
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

const FILE_KINDS = { '.svg': 'svg', '.css': 'css', '.tsx': 'tsx', '.jsx': 'jsx' };

/** Reject a file the checker has no reader for, before anything is measured. */
function assertSupported(path) {
  const kind = FILE_KINDS[extname(path).toLowerCase()];
  if (!kind) throw usage(`unsupported file type: ${path}`);
  return kind;
}

/** A directory and a `--mode` that needs a file answer different questions. */
function assertModeFits(info, opts) {
  if (info.isDirectory()) {
    // Only `auto` and `keyline` make sense for a directory; silently running the
    // keyline check for `--mode standalone` would answer a question nobody asked.
    if (opts.mode !== 'auto' && opts.mode !== 'keyline') {
      throw usage(`--mode ${opts.mode} needs a file; a directory only supports keyline`);
    }
    return;
  }
  if (opts.mode === 'keyline') {
    throw usage('--mode keyline needs a directory, not a single file');
  }
}

/**
 * Reject an invocation the checker would refuse anyway, before --self-heal has
 * changed anything. A usage error must not leave the installs half-repaired.
 */
async function validateTargets(opts) {
  for (const path of opts.paths) {
    const resolved = resolve(path);
    let info;
    try {
      info = await stat(resolved);
    } catch (err) {
      if (err && err.code === 'ENOENT') throw usage(`no such file: ${path}`);
      throw err;
    }
    assertModeFits(info, opts);
    if (!info.isDirectory()) assertSupported(resolved);
  }
}

async function checkPath(path, opts) {
  const info = await stat(path);
  assertModeFits(info, opts);
  if (info.isDirectory()) return checkIconSet(path);
  const kind = assertSupported(path);
  if (kind === 'svg') return checkIconFile(path, { mode: opts.mode });
  const text = await readFile(path, 'utf8');
  if (kind === 'css') return checkCss(text, { target: basename(path) });
  return checkTsx(text, { target: basename(path) });
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
      // `value` is px; the paste-able form is the viewBox itself. Printing only
      // the number invites adding it to an origin measured in user units.
      if (f.suggested?.kind === 'viewBox-origin' && f.suggested.viewBox) {
        const delta = f.suggested.delta ? ` (delta ${f.suggested.delta})` : '';
        lines.push(`          paste viewBox="${f.suggested.viewBox}"${delta}`);
      }
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

/**
 * Repair the agent-side installs before doing anything else.
 *
 * A failure here exits 2 (`unknown`) instead of producing a verdict. Half a
 * heal leaves the environment in a state this run cannot characterise, and the
 * one thing this tool must never do is answer `ok` about a copy of itself that
 * is not the one on disk. Cheap to repeat: the repair is idempotent.
 */
function runSelfHeal(opts) {
  let result;
  try {
    result = syncInstalls({ home: opts.home ?? undefined, skillDir: opts.skillDir ?? undefined });
  } catch (err) {
    const wrapped = new Error(`self-heal failed: ${err.message}`);
    // "you ran this from the wrong place" is a usage error (64); anything else
    // is an environment problem the run cannot characterise (2).
    wrapped.usage = Boolean(err && err.usage);
    throw wrapped;
  }
  // stderr, not stdout: `--json` consumers parse stdout and nothing else.
  for (const line of formatSync(result)) process.stderr.write(`${line}\n`);
  return result;
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
    if (opts.help) {
      process.stdout.write(`${USAGE}\n`);
      return 0;
    }
    if (opts.command === 'font') {
      if (opts.selfHeal) throw usage('--self-heal repairs installs; it has nothing to do with `font`');
      if (opts.paths.length === 0) {
        process.stdout.write(`${USAGE}\n`);
        return 64;
      }
      return await runFont(opts);
    }
    // Silently ignoring these would let `check x.svg --size 48` look like it took
    // effect. They belong to the `font` subcommand. Checked before --self-heal so
    // a rejected invocation has no side effects.
    if (opts.size !== null || opts.lineHeight !== null) {
      throw usage('--size and --line-height only apply to `font`; `check` derives size from the file');
    }

    if (opts.selfHeal) {
      await validateTargets(opts);
      const healed = runSelfHeal(opts);
      // No paths means "just heal": a repair pass is a complete answer by itself.
      if (opts.paths.length === 0) {
        if (opts.json) {
          process.stdout.write(`${JSON.stringify({ version: 1, self_heal: healed }, null, 2)}\n`);
        }
        return 0;
      }
    }
    if (opts.paths.length === 0) {
      process.stdout.write(`${USAGE}\n`);
      return 64;
    }

    const policy = await loadPolicy(opts.policy);
    const reports = [];
    for (const path of opts.paths) {
      const resolved = resolve(path);
      try {
        reports.push(applyPolicy(await checkPath(resolved, opts), policy));
      } catch (err) {
        // Usage errors describe the invocation, not the file — they must abort.
        if (err && err.usage) throw err;
        // A path the user typed wrong is a usage error, not a verdict.
        if (err && err.code === 'ENOENT') throw usage(`no such file: ${path}`);
        // One unreadable file must not take the rest of the batch down with it,
        // and `--json` callers need an object for every path they passed. The
        // finding is what keeps the report from reading as `ok`: an empty
        // findings list aggregates to `ok`, which would turn "could not read
        // this" into "nothing wrong here".
        reports.push(
          buildReport({
            target: basename(resolved),
            mode: opts.mode,
            findings: [
              {
                id: 'geometry/input-error',
                layer: 'exact',
                forcedVerdict: 'unknown',
                pixel: false,
                evidence: String(err && err.message),
                suggested: { kind: 'inspect', value: 'the file could not be read or parsed' },
              },
            ],
            policy,
            meta: { error: String(err && err.message) },
          }),
        );
      }
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
