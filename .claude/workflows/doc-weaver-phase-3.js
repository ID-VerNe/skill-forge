export const meta = {
  name: 'doc-weaver-phase-3',
  description: '并行生成所有模块的 Tier 3 结构化数据（docs/schema/<module>.schema.json）',
  phases: [
    { title: '读取 manifest', detail: '读取 docs/schema/manifest.json 确定需要生成 schema 的模块' },
    { title: '生成 schema', detail: '每个模块一个并行 agent' },
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

const needUpdate = Object.entries(manifest.modules || {})
  .filter(([, m]) => m.doc_status === 'needs_create' || m.doc_status === 'needs_update')

if (needUpdate.length === 0) {
  log('[phase-3] All modules are up to date. Nothing to do.')
  log(JSON.stringify({ verdict: 'skipped', count: 0, modules: [] }))
  return
}

log(`[phase-3] ${needUpdate.length} module(s) need schema generation`)

// ── Agent prompt template ──────────────────────────────────────────────────
phase('生成 schema')

const results = await parallel(needUpdate.map(([name, mod]) => () => {
  const prompt = `You are a structured data generator for the doc-weaver system.

## Task
Generate a machine-readable JSON schema for the module "${name}".

## Module Context
- Module name: ${name}
- Source files: ${(mod.source_paths || []).join(', ')}
- Languages: ${(mod.languages || []).join(', ')}
- Doc path: ${mod.doc_path || `docs/modules/${name}.md`}

## Output Path
${mod.schema_path || `docs/schema/${name}.schema.json`}

## Schema Format
\`\`\`json
{
  "module": "${name}",
  "version": "1.0.0",
  "exports": [
    { "name": "exportName", "kind": "function|class|interface|type|constant", "params": [], "returns": "type" }
  ],
  "dependencies": {
    "internal": ["module-name"],
    "external": ["package-name"]
  },
  "consumers": ["other-module-name"],
  "errors": {
    "ERROR_CODE": { "code": 400, "recovery": "How to recover" }
  },
  "entryPoints": ["src/main/file.ext"],
  "configKeys": ["CONFIG_KEY"]
}
\`\`\`

## Rules
1. Read the actual source files to extract accurate exports, function signatures, and error codes
2. Do NOT fabricate — if you're unsure about an export, skip it
3. Read the doc file (${mod.doc_path || `docs/modules/${name}.md`}) to understand the module's responsibilities
4. Use the manifest to cross-reference dependencies and consumers
5. Output ONLY valid JSON — no markdown, no explanation

Write the JSON file now.`
  return agent(prompt, {
    label: `schema:${name}`,
    phase: '生成 schema',
  })
}))

const succeeded = results.filter(Boolean).length
const failed = results.length - succeeded

log(`[phase-3] Done: ${succeeded} succeeded, ${failed} failed`)
log(JSON.stringify({
  verdict: failed > 0 ? 'partial' : 'passed',
  count: results.length,
  succeeded,
  failed,
  modules: needUpdate.map(([name]) => name),
}))