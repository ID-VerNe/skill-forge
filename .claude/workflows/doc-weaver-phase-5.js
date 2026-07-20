export const meta = {
  name: 'doc-weaver-phase-5',
  description: '并行验证所有模块文档的准确性（源码级比对）',
  phases: [
    { title: '读取 manifest', detail: '确定需要验证的模块' },
    { title: '验证', detail: '每个模块一个并行验证 agent' },
    { title: '汇总', detail: '收集所有验证结果并报告' },
  ],
}

// ── 读取 manifest ──────────────────────────────────────────────────────────
phase('读取 manifest')

const manifest = args.manifest || (() => {
  const fs = require('fs')
  const path = require('path')
  const manifestPath = path.join(args.projectRoot, 'docs/schema/manifest.json')
  return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'))
})()

const allModules = Object.entries(manifest.modules || {})
  .filter(([, m]) => m.doc_status !== 'needs_delete')

if (allModules.length === 0) {
  log('[phase-5] No modules to verify.')
  log(JSON.stringify({ verdict: 'skipped', count: 0, modules: [] }))
  return
}

log(`[phase-5] ${allModules.length} module(s) to verify`)

// ── Agent prompt template ──────────────────────────────────────────────────
// Schema for structured output from verification agents
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    module: { type: 'string' },
    verdict: { type: 'string', enum: ['passed', 'needs_fix', 'failed'] },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['error', 'warning'] },
          category: {
            type: 'string',
            enum: [
              'doc_claim_not_in_code',
              'code_feature_not_documented',
              'wrong_dependency',
              'incorrect_error',
              'behavior_mismatch',
              'broken_symbol_ref',
            ],
          },
          docLocation: { type: 'string' },
          codeLocation: { type: 'string' },
          description: { type: 'string' },
          suggestion: { type: 'string' },
        },
        required: ['severity', 'category', 'description'],
      },
    },
  },
  required: ['module', 'verdict', 'issues'],
}

phase('验证')

const results = await parallel(allModules.map(([name, mod]) => () => {
  const prompt = `You are a doc-weaver verification agent.
Your task: compare \`${mod.doc_path}\` with the actual source code and find all inconsistencies.

## Module
${name}

## Source Files
${(mod.source_paths || []).join('\n')}

## Doc File
${mod.doc_path}

## Checks Required

1. **Interface completeness**: Do the exports, function signatures, parameters, and return values in the doc match the source code?
   - Doc claims something the code doesn't have → \`doc_claim_not_in_code\`
   - Code has something the doc doesn't mention → \`code_feature_not_documented\`

2. **Dependency accuracy**: Are the dependencies/consumers listed in the doc correct?
   - Source imports something the doc doesn't mention → missing dependency
   - Doc lists a dependency but source doesn't import it → stale dependency

3. **Error conditions**: Do the error codes and recovery paths described in the doc actually exist in the source?
   - Doc mentions an error that's never thrown → fictitious error
   - Source throws an error the doc doesn't record → missing error

4. **Behavior accuracy**: Does the business logic description match the actual implementation?
   - Doc says "uses JWT" but source uses sessions → wrong description
   - Doc describes a flow that differs from the code → inaccurate description

5. **Symbol references**: Do all \`[[src/path#symbol]]\` references in the doc point to real symbols?

## Output
Return a JSON object with module, verdict (passed/needs_fix/failed), and issues array.`
  return agent(prompt, {
    label: `verify:${name}`,
    phase: '验证',
    schema: VERIFY_SCHEMA,
  })
}))

// ── 汇总 ───────────────────────────────────────────────────────────────────
phase('汇总')

const validResults = results.filter(Boolean)
const passed = validResults.filter(r => r.verdict === 'passed').length
const needsFix = validResults.filter(r => r.verdict === 'needs_fix').length
const failed = validResults.filter(r => r.verdict === 'failed').length

const allIssues = validResults.flatMap(r => r.issues || [])
const errors = allIssues.filter(i => i.severity === 'error')
const warnings = allIssues.filter(i => i.severity === 'warning')

log(`[phase-5] Verification complete:`)
log(`  Passed: ${passed} | Needs fix: ${needsFix} | Failed: ${failed}`)
log(`  Total issues: ${allIssues.length} (${errors.length} errors, ${warnings.length} warnings)`)

// Print issues by module
for (const result of validResults) {
  if (result.issues && result.issues.length > 0) {
    log(`--- ${result.module} (${result.verdict}) ---`)
    for (const issue of result.issues) {
      log(`  [${issue.severity}] ${issue.description}`)
      if (issue.suggestion) log(`    → ${issue.suggestion}`)
    }
  }
}

log(JSON.stringify({
  verdict: failed > 0 || needsFix > 0 ? 'needs_fix' : 'passed',
  count: validResults.length,
  passed,
  needsFix,
  failed,
  totalIssues: allIssues.length,
  errors: errors.length,
  warnings: warnings.length,
  issues: allIssues,
}))