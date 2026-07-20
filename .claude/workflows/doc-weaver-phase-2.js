export const meta = {
  name: 'doc-weaver-phase-2',
  description: '并行生成所有模块的 Tier 2 模块文档（docs/modules/<module>.md）',
  phases: [
    { title: '读取 manifest', detail: '读取 docs/schema/manifest.json 确定需要写的模块' },
    { title: '写模块文档', detail: '每个模块一个并行 agent' },
  ],
}

// ── 读取 manifest ──────────────────────────────────────────────────────────
phase('读取 manifest')

// Use args to accept project root path
// args = { projectRoot: '...', manifest: { modules: {...} }, projectContext: '...' }
// When called from doc-weaver, the coordinator passes the manifest and project context

const manifest = args.manifest || (() => {
  log('[phase-2] No manifest provided via args — reading from docs/schema/manifest.json')
  const fs = require('fs')
  const path = require('path')
  const manifestPath = path.join(args.projectRoot, 'docs/schema/manifest.json')
  return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'))
})()

// Filter modules that need doc creation or update
const needUpdate = Object.entries(manifest.modules || {})
  .filter(([, m]) => m.doc_status === 'needs_create' || m.doc_status === 'needs_update')

if (needUpdate.length === 0) {
  log('[phase-2] All modules are up to date. Nothing to do.')
  log(JSON.stringify({ verdict: 'skipped', count: 0, modules: [] }))
  return
}

log(`[phase-2] ${needUpdate.length} module(s) need doc updates`)

// ── Agent prompt template ──────────────────────────────────────────────────
phase('写模块文档')

const results = await parallel(needUpdate.map(([name, mod]) => () => {
  const prompt = `You are a technical documentation writer for the doc-weaver system.

## Task
Write a Tier 2 module documentation file for the module "${name}".

## Project Context
${args.projectContext || 'No project context provided.'}

## Module Context
- Module name: ${name}
- Source files: ${(mod.source_paths || []).join(', ')}
- Languages: ${(mod.languages || []).join(', ')}
- Exports (from manifest): ${(mod.exports || []).join(', ') || 'unknown — scan to discover'}
- Dependencies (from manifest): ${(mod.dependencies || []).join(', ') || 'unknown — scan to discover'}
- Consumers (from manifest): ${(mod.consumers || []).join(', ') || 'unknown — scan to discover'}

## Output Path
${mod.doc_path || `docs/modules/${name}.md`}

## Template
Follow this exact markdown structure:

\`\`\`markdown
# ${name}

One-sentence overview: what this module does and why it exists.

## Responsibilities

- Core responsibility 1
- Core responsibility 2

## Key Concepts

### Concept Name

Explanation of the concept. Brief description of internal mechanism.

Reference: [[src/path/to/file#SymbolName]]

### Another Concept

...

## Dependencies

Other modules this depends on and why:

- [[modules/dep-name]] — reason

## Consumed By

Which modules use this module:

- [[modules/consumer-name]] — how they use it

## Error Conditions

Machine-readable error codes and recovery paths (see [[schema/${name}.schema.json]])
\`\`\`

## Rules
1. Each section MUST have a leading paragraph ≤250 characters (excluding wiki link syntax)
2. Every reference to another module MUST use [[wiki/link]] syntax
3. Every reference to source code symbols MUST use [[src/path#symbol]] syntax
4. Read the actual source files to verify exports, function signatures, and behavior
5. Do NOT fabricate features or behavior — if you're unsure, state it explicitly
6. Use the section ID format: docs/modules/${name}#Heading#Subheading
7. Write in Chinese for concept explanations, keep technical terms in English

Write the file now.`
  return agent(prompt, {
    label: `doc:${name}`,
    phase: '写模块文档',
  })
}))

// Collect results
const succeeded = results.filter(Boolean).length
const failed = results.length - succeeded

log(`[phase-2] Done: ${succeeded} succeeded, ${failed} failed`)
log(JSON.stringify({
  verdict: failed > 0 ? 'partial' : 'passed',
  count: results.length,
  succeeded,
  failed,
  modules: needUpdate.map(([name]) => name),
}))