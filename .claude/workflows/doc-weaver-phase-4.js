export const meta = {
  name: 'doc-weaver-phase-4',
  description: '并行在源码中添加 @lat 注解（docs/modules/<module>.md → source code）',
  phases: [
    { title: '读取 manifest', detail: '确定需要添加 @lat 注解的模块' },
    { title: '添加 @lat 注解', detail: '每个模块一个并行 agent' },
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
  log('[phase-4] All modules are up to date. Nothing to do.')
  log(JSON.stringify({ verdict: 'skipped', count: 0, modules: [] }))
  return
}

log(`[phase-4] ${needUpdate.length} module(s) need @lat annotations`)

// ── Agent prompt template ──────────────────────────────────────────────────
phase('添加 @lat 注解')

const results = await parallel(needUpdate.map(([name, mod]) => () => {
  const sourceFiles = (mod.source_paths || []).join('\n')
  const prompt = `You are a documentation annotation specialist for the doc-weaver system.

## Task
Add @lat annotations to source code files for the module "${name}".

@lat annotations are special comments that link source code to documentation sections.
Format: \`# @lat: [[docs/modules/${name}#Section#Subsection]]\` (Python) or \`// @lat: [[...]]\` (JS/TS/Rust/Go)

## Module Context
- Module name: ${name}
- Source files:
${sourceFiles}

- Doc file: ${mod.doc_path || `docs/modules/${name}.md`}

## Rules
1. Read the doc file at ${mod.doc_path || `docs/modules/${name}.md`} to understand all section IDs
2. For each leaf section in the doc, find the corresponding code in the source files
3. Add the @lat annotation on the line BEFORE the function/class/block the section describes
4. Comment style per file extension:
   - .py, .rb, .sh → "# @lat: [[...]]"
   - .js, .ts, .tsx, .jsx, .rs, .go, .java, .kt, .c, .cpp, .h, .hpp, .swift → "// @lat: [[...]]"
   - .php → "// @lat: [[...]]" (PHP also supports "#" but prefer "//")
5. Do NOT add annotations to:
   - Simple getters/setters
   - Trivial boilerplate (__init__.py, index files)
   - Generated code
6. Do NOT duplicate existing annotations — check if the file already has @lat comments
7. One section → one annotation. Don't repeat the same section ID.

## Section ID Format
The section ID format is: docs/modules/${name}#Heading#Subheading
For example: docs/modules/${name}#Key Concepts#Some Concept

Read the doc file, read the source files, then add appropriate annotations.`
  return agent(prompt, {
    label: `lat:${name}`,
    phase: '添加 @lat 注解',
  })
}))

const succeeded = results.filter(Boolean).length
const failed = results.length - succeeded

log(`[phase-4] Done: ${succeeded} succeeded, ${failed} failed`)
log(JSON.stringify({
  verdict: failed > 0 ? 'partial' : 'passed',
  count: results.length,
  succeeded,
  failed,
  modules: needUpdate.map(([name]) => name),
}))