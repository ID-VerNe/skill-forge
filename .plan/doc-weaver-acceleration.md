# doc-weaver 加速优化方案

> 目标：3 万行项目文档生成从 30 分钟 → 10-15 分钟，质量不降
> 日期：2026-07-20
> 状态：需求已确认，待实现

---

## 问题诊断

### 当前瓶颈分布

| 阶段 | 耗时占比 | 原因 |
|------|---------|------|
| Phase 0 扫描 | ~10% | Agent 手动读源码文件推断结构，50+ 文件需数分钟 |
| Phase 1 入口文档 | ~5% | 一次生成，后续增量更新 |
| Phase 2 写模块文档 | ~35% | 串行逐个模块写，每个模块都要重新扫描代码 |
| Phase 3 结构化数据 | ~10% | 串行生成 schema |
| Phase 4 添加 @lat 注解 | ~15% | 串行逐个模块加注解 |
| Phase 5 源码验证 | ~25% | 串行验证，发现问题后还要修复 |

### 根因

1. **串行执行**：每个阶段一个模块一个模块地处理，N 个模块耗时 = N × 单模块耗时
2. **重复扫描**：Phase 0 扫完代码，Phase 2/5 每个 agent 又重新读一遍
3. **无缓存机制**：改了其中一个模块，下次全量重跑

---

## 架构方案

```
主 agent（协调者）
├── Phase 0: 扫描项目
│   ├── 读取或生成 docs/schema/manifest.json
│   ├── 对比文件 hash / mtime 识别变更模块（不依赖 git）
│   └── 输出：变更模块列表 + 项目全景上下文
│
├── Phase 1: 生成 Tier 1 入口文档（首次全量，后续增量）
│   ├── docs/index.md
│   ├── docs/project/index.md
│   ├── docs/project/architecture.md
│   └── docs/project/glossary.md
│
├── Phase 2: 写模块文档 — Workflow fan-out ⭐
│   └── N 个并行 agent，每个独立写一个模块的 docs/modules/<module>.md
│
├── Phase 3: 结构化数据 — Workflow fan-out ⭐
│   └── N 个并行 agent，每个独立生成 docs/schema/<module>.schema.json
│
├── Phase 4: 添加 @lat 注解 — Workflow fan-out ⭐
│   └── N 个并行 agent，每个独立给对应源码加 @lat 注解
│
├── Phase 5: 源码验证 — Workflow fan-out ⭐
│   └── N 个并行 agent，每个独立验证一个模块的文档准确性
│
└── 主 agent 汇总
    ├── 修复 Phase 5 报告的问题
    ├── 更新 manifest.json（hash + mtime）
    ├── 生成 docs/graph.json
    ├── 运行 lat index 重建双向索引
    └── 报告结果给用户
```

---

## 关键设计

### 1. manifest.json — 增量变更检测

**核心原则：不依赖 git。** 文件可能未 staged、未 committed，甚至不在 git 仓库中。变更检测基于文件系统层的 hash + mtime 对比。

**位置**：`docs/schema/manifest.json`

```json
{
  "version": "1.0.0",
  "generated_at": "2026-07-20T10:00:00Z",
  "modules": {
    "polyglot-router": {
      "source_paths": ["polyglot/router.py"],
      "hash": "sha256_of_router.py",
      "mtime": "2026-07-20T09:00:00Z",
      "doc_status": "up_to_date",
      "doc_path": "docs/modules/polyglot-router.md",
      "schema_path": "docs/schema/polyglot-router.schema.json",
      "exports": ["main", "import_backend", "LANGUAGES"],
      "dependencies": ["common", "backends"],
      "consumers": ["__main__"]
    },
    "common": {
      "source_paths": [
        "polyglot/common/cache.py",
        "polyglot/common/schema.py",
        "polyglot/common/reporters.py"
      ],
      "hash": "sha256_of_common_files",
      "mtime": "2026-07-20T09:00:00Z",
      "doc_status": "up_to_date",
      "doc_path": "docs/modules/common.md",
      "exports": ["DiskCache", "ReportGenerator"],
      "dependencies": [],
      "consumers": ["polyglot-router", "glue"]
    }
  }
}
```

**变更检测逻辑**：

1. `manifest.json` 不存在 → 首次全量生成
2. 存在 → 遍历 manifest 中每个模块的 `source_paths`：
   - 读文件当前 hash + mtime
   - 对比 manifest 中存的值
   - **hash 相同 + mtime 没变 → 跳过**
   - **hash 或 mtime 变了 → 标记为 `needs_update`**
   - **manifest 有但文件不存在 → 标记为 `needs_delete`**
3. 扫描项目源码目录，发现 manifest 中未记录的新文件 → 尝试归入已有模块或标记为新模块
4. 新模块 → 标记为 `needs_create`

**为什么不用 git**：
- 文件改了但没 `git add` → `git diff` 能检测到，但 `git diff HEAD` 不行
- 文件改了但没 `git commit` → `git diff --cached` 不行
- 新项目还没 `git init` → 无 git 可用
- 始终用实际文件 hash 对比，和 git 状态无关

### 2. Workflow fan-out — 并行执行

**执行模式**：

```
Workflow("Phase 2: 写模块文档")
  ├── 读取 manifest → 找出所有 needs_update / needs_create 的模块
  ├── 对每个模块，启动一个独立 agent：
  │   Agent("写 polyglot-router.md", {label: "doc:polyglot-router"})
  │   Agent("写 common.md", {label: "doc:common"})
  │   Agent("写 backends.md", {label: "doc:backends"})
  │   ...
  ├── 等待所有完成
  └── 返回成功/失败列表
```

**每个子 agent 的 prompt 结构**：
- 项目全景上下文（从 manifest 读取）
- 该模块的源码文件路径
- 该模块的 exports / dependencies（从 manifest 读取）
- 模板要求（格式规范、前文规则、wiki link 语法）
- 保存路径

**子 agent 互不知情**：不依赖其他模块的文档内容，只依赖 manifest 中的框架信息。交叉引用用 `[[wiki/link]]` 占位，Phase 1 确保目标文件存在即可。

### 3. `lat` CLI — 文档 ↔ 源码双向定位工具 ⭐

这是一个独立的 CLI 工具，将 @lat 注解从静态注释升级为**可编程的导航接口**。AI agent 和人类都可以调用它快速定位文档和代码的对应关系。

#### 为什么需要它

- 当前 @lat 注解只是静态注释，AI agent 无法程序化地查询
- 一个 agent 编辑 `router.py` 时，想知道"哪些文档描述了这个文件？"——需要手动 grep
- 一个 agent 更新 `docs/modules/common.md` 时，想知道"哪些源码引用了这个 section？"——需要手动查找
- 没有工具化的索引，Phase 5 的验证也无法自动检查 @lat 的完整性

#### 数据结构

`lat` 工具在 `docs/schema/lat-index.json` 维护一个双向索引：

```json
{
  "version": "1.0.0",
  "indexed_at": "2026-07-20T10:00:00Z",
  "sections": {
    "docs/modules/polyglot-router#Key Concepts#动态后端导入": {
      "doc_path": "docs/modules/polyglot-router.md",
      "heading_chain": ["Key Concepts", "动态后端导入"],
      "code_refs": [
        {
          "file": "polyglot/router.py",
          "line": 22,
          "annotation": "# @lat: [[docs/modules/polyglot-router#Key Concepts#动态后端导入]]"
        }
      ]
    }
  },
  "files": {
    "polyglot/router.py": {
      "module": "polyglot-router",
      "annotations": [
        { "line": 22, "section_id": "docs/modules/polyglot-router#Key Concepts#动态后端导入" },
        { "line": 45, "section_id": "docs/modules/polyglot-router#Language Alias Mapping" }
      ]
    }
  }
}
```

#### CLI 命令

| 命令 | 功能 | 使用场景 |
|------|------|---------|
| `lat index` | 扫描所有源码中的 @lat 注解 + 所有文档中的 section ID，重建索引 | Phase 4 完成后、CI 中 |
| `lat lookup <file>[:<line>]` | 给定源码文件 + 可选行号，返回关联的 doc section 列表 | Agent 编辑代码时想快速看相关文档 |
| `lat locate <section-id>` | 给定 doc section ID，返回所有关联的源码位置 | Agent 更新文档时想找所有相关代码 |
| `lat context <file>` | 读取该文件所属模块的完整文档 | Agent 需要理解整个模块时 |
| `lat check` | 验证所有 @lat 注解的有效性（每个注解指向真实 section，每个 section 有对应注解） | CI 检查、Phase 5 辅助 |
| `lat suggest <file>` | 建议该文件应该添加哪些 @lat 注解（基于 section ID 匹配函数名/类名） | 辅助 Phase 4 |

#### 实现方式

- Python 脚本，零依赖（只用 stdlib）
- 扫描 `docs/modules/*.md` 提取所有 section ID（用正则匹配 `# ` 标题 + `<a id="...">`）
- 扫描源码中所有 `@lat:` 注释
- 构建双向索引并写入 `docs/schema/lat-index.json`
- 查询命令读索引，不重新扫描

#### 对 AI agent 的价值

```
Agent 正在编辑 polyglot/router.py
→ 执行 lat lookup polyglot/router.py
→ 返回：该文件关联的文档是 docs/modules/polyglot-router.md
→ Agent 直接读这篇文档，不需要自己 grep

Agent 正在更新 docs/modules/common.md
→ 执行 lat locate docs/modules/common#DiskCache
→ 返回：polyglot/common/cache.py:42 引用了这个 section
→ Agent 知道改完文档后要同步更新源码注解

Agent 需要理解 glue 模块
→ 执行 lat context polyglot/glue/aggregator.py
→ 返回：完整的 docs/modules/glue.md 内容
→ Agent 不需要手动找哪个文档对应哪个模块
```

### 4. verify_refs.py — CI 引用完整性检查

**位置**：`scripts/verify_refs.py`

**功能**（纯机械检查，无 AI 调用）：
- 检查 `[[modules/xxx]]` wiki link 对应的 `.md` 文件是否存在
- 检查 `[[project/xxx]]` 对应的 `.md` 文件是否存在
- 检查 `[[schema/xxx]]` 对应的 `.json` 文件是否存在
- 检查 `[[src/path#symbol]]` 格式是否正确
- 检查 manifest 中声明的模块是否都有对应的文档
- 检查 docs 中存在的模块文档是否在 manifest 中有声明

**输出**：JSON 报告 + 退出码（0 = 通过，1 = 有问题）

---

## 完整工作流

### 首次全量生成

```
[状态：manifest.json 不存在]

Phase 0: Agent 扫描所有源码
  → 识别模块结构、exports、依赖关系
  → 写入 docs/schema/manifest.json（doc_status: "needs_create"）

Phase 1: 主 agent 生成入口文档
  → docs/index.md, project/index.md, architecture.md, glossary.md

Phase 2: Workflow fan-out 写模块文档
  → 对每个 doc_status=="needs_create" 的模块，并行写

Phase 3: Workflow fan-out 生成 schema
  → 并行生成 JSON schema

Phase 4: Workflow fan-out 添加 @lat 注解
  → 并行在源码中添加 @lat 注释

Phase 5: Workflow fan-out 验证
  → 并行验证每个模块的文档准确性
  → 报告问题 → 主 agent 修复

汇总: 更新 manifest（doc_status: "up_to_date"）
  → 运行 lat index 重建双向索引
```

### 增量更新（修改了一个文件）

```
[状态：manifest.json 存在，polyglot/router.py 的 hash 变了]

Phase 0: 检测变更
  → manifest 中的 hash vs 当前文件 hash → 发现 router.py 变了
  → 标记 polyglot-router 模块为 "needs_update"
  → 重新扫描该模块的 exports/dependencies

Phase 1: 增量更新入口文档
  → 只更新 docs/project/index.md 中 polyglot-router 的条目

Phase 2: 只重写 polyglot-router 模块的文档
  → 其他模块不处理

Phase 3: 只更新 polyglot-router 的 schema

Phase 4: 只更新 router.py 的 @lat 注解

Phase 5: 只验证 polyglot-router 模块

汇总: 更新 manifest 中 polyglot-router 的 hash/mtime
  → 运行 lat index 重建双向索引
```

---

## Workflow 脚本设计

### Phase 2 示例（写模块文档）

```javascript
export const meta = {
  name: 'doc-weaver-phase-2',
  description: '并行生成所有模块的 Tier 2 文档',
  phases: [
    { title: '写模块文档', detail: '每个模块一个并行 agent' },
  ],
}

phase('写模块文档')

const manifest = readManifest() // 从 manifest.json 读取
const needUpdate = Object.entries(manifest.modules)
  .filter(([_, m]) => m.doc_status !== 'up_to_date')

const results = await parallel(needUpdate.map(([name, mod]) => () =>
  agent(`为模块 ${name} 生成文档。\n
    源码路径：${mod.source_paths.join(', ')}
    Exports: ${mod.exports.join(', ')}
    Dependencies: ${mod.dependencies.join(', ')}
    按 docs/modules/ 模板写，保存到 ${mod.doc_path}`, {
    label: `doc:${name}`,
    phase: '写模块文档',
  })
))
```

### Phase 5 示例（验证）

```javascript
export const meta = {
  name: 'doc-weaver-phase-5',
  description: '并行验证所有模块文档的准确性',
  phases: [
    { title: '验证', detail: '每个模块一个并行验证 agent' },
  ],
}

phase('验证')

const results = await parallel(manifest.modules.map(([name, mod]) => () =>
  agent(`验证 ${name} 的文档。\n
    比对 ${mod.doc_path} 和源码 ${mod.source_paths.join(', ')}，
    检查 exports、dependencies、行为描述、错误条件是否一致。`, {
    label: `verify:${name}`,
    phase: '验证',
  })
))
```

---

## 实现计划

### Step 1：定义 manifest.json 格式（1 天）
- 确定 JSON schema
- 写一个 `scripts/init_manifest.py` 生成空白 manifest
- 更新 SKILL.md 的 Phase 0 说明

### Step 2：实现 `lat` CLI 工具（3 天）⭐
- 实现 `lat index` — 扫描 @lat 注解 + doc section ID，构建双向索引
- 实现 `lat lookup` — 源码 → 文档定位
- 实现 `lat locate` — 文档 → 源码定位
- 实现 `lat context` — 读取模块完整文档
- 实现 `lat check` — 注解完整性验证

### Step 3：实现 Phase 0 结构化缓存（2 天）
- 修改 Phase 0 prompt，要求输出 manifest.json
- 实现变更检测逻辑（hash 对比，不依赖 git）
- 写 `scripts/update_manifest.py` 更新 manifest

### Step 4：实现 Workflow fan-out 脚本（3 天）
- 写 Phase 2 Workflow 脚本（并行写模块文档）
- 写 Phase 3 Workflow 脚本（并行生成 schema）
- 写 Phase 4 Workflow 脚本（并行加 @lat 注解）
- 写 Phase 5 Workflow 脚本（并行验证）

### Step 5：实现 verify_refs.py（1 天）
- 引用完整性检查
- CI 集成说明

### Step 6：测试 + 调优（2 天）
- 用 glue-engineer 测试全流程（3 万行）
- 统计耗时，对比优化前后的瓶颈
- 调优 prompt 质量

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 并行 agent 输出风格不一致 | 文档质量参差不齐 | 统一模板 + 项目全景上下文 + Phase 5 验证修复 |
| manifest 框架信息不准 | 下游 agent 写错文档 | Agent 可选读源码确认，不强制依赖 manifest |
| Workflow 100 个模块并行超限 | 部分 agent 被限流 | 用 pipeline 控制并发数（默认 ~10 并行） |
| 文件 hash 对比不够快（大文件） | Phase 0 变慢 | 只 hash 文件头 + 大小 + mtime，不读全文件 |
| 没有 git 时无法做文件级 diff | 增量检测不精确 | 用 hash + mtime 对比，不依赖 git 的任何功能 |
| 并行 agent 的 token 消耗暴涨 | 成本增加 | 但总耗时下降 50%+，token 总量不变（分散到 N 个 agent） |

---

## 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 3 万行项目全量生成 | ~30 min | 10-15 min |
| 单模块增量更新 | ~30 min（全量重跑） | 1-2 min |
| 文档质量 | 已验证 | 不降（Phase 5 兜底） |
| 首次生成 | 30 min | 10-15 min |
| 第二次（无变更） | 30 min（重跑） | <1 min（跳过） |
| @lat 双向定位 | 手动 grep | `lat lookup` / `lat locate` 秒级返回 |