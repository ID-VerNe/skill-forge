---
name: commit-message-writing
version: 1.1.0
description: 专门用于写 commit message、执行 git commit 和 git push 的 skill。只要用户提及 git、commit、push、提交、暂存、stage、add、推送、PR 准备、或者任何与代码提交相关的操作，都必须触发此 skill。每次调用 git commit 和 git push 都必须走这个 skill 的工作流。
---

# Commit Message Writer

你已激活 **Commit Message Writer Skill**。你的职责是帮助用户完成从「查看变更 → 确认追踪 → 写 message → commit → push」的完整流程。

## 核心规则

### 1. 你负责扫描并建议追踪文件
- 激活 skill 后你主动去发现变更，而不是等用户告诉你
- **严禁**使用 `git add .`、`git add -A`、`git add --all` 或任何批量添加命令
- **正确做法**：逐个 `git add <file>` 添加文件
- 工作流：`git status` 查看状态 → 列出 untracked/modified 文件给用户确认 → 你逐个 `git add` 执行

### 2. 如果没有 git 仓库
如果当前目录没有 `.git`，你需要：
1. 检查当前目录下有哪些文件
2. 列出文件列表给用户确认
3. 用户确认后执行 `git init`
4. 然后逐个 `git add` 用户确认的文件

### 3. 每次操作前先检查状态
```bash
git status
```
- 查看哪些文件已暂存（staged）
- 查看哪些文件未追踪（untracked）
- 查看哪些文件有修改未暂存

### 4. 身份信息强制覆盖
每次 commit 前，必须执行：
```bash
git config user.name "ID-VerNe"
git config user.email "yuu_seeing@foxmail.com"
```
并设置环境变量：
```bash
export GIT_COMMITTER_NAME="ID-VerNe"
export GIT_COMMITTER_EMAIL="yuu_seeing@foxmail.com"
```

### 5. 禁止 Co-Authored-By
Commit message 中**禁止**出现任何 `Co-Authored-By:` 行。如果自动生成的 message 中包含此类内容，必须手动移除。

### 6. Commit message 格式

严格遵循 `references/commit-message-conventions.md` 中的格式：

```
<type>: <short summary (max 72 chars)>

ADD:
- <itemized list of additions>

FIX:
- <itemized list of fixes>
```

**类型前缀对照：**
| 前缀 | 含义 |
|------|------|
| `feat:` | 新功能 |
| `fix:` | 修复 Bug |
| `docs:` | 文档变更 |
| `style:` | 格式调整（不改变代码行为） |
| `refactor:` | 重构（既不是新功能也不是修 Bug） |
| `perf:` | 性能优化 |
| `test:` | 添加测试 |
| `chore:` | 构建/工具链变更 |

**可选 Scope（影响范围）：** 类型后可加 `(<scope>)` 标明改动涉及模块，如 `feat(auth):`、`fix(ui):`。
**可选 Footer（页脚）：** 正文后可加 `Closes #123` 关联 Issue，或 `BREAKING CHANGE:` 标记不兼容变更。

**原则：** 摘要行使用小写前缀，冒号后有空格。ADD/FIX 部分是英文单词 + 冒号，子项用 dash bullet。**多行示例（标准格式）：**
```
fix(auth): 修复第三方登录令牌过期未刷新的问题

原因是在请求拦截器中漏掉了对 401 状态码的判断。
现在已补上拦截逻辑，并会自动触发 token 刷新请求。

Closes #123
```

## 工作流程

### Step 1: 检查仓库状态
```bash
git status 2>/dev/null || echo "NOT_A_REPO"
```
- 如果没有 git 仓库，列出目录文件给用户确认是否要 `git init` 并追踪
- 如果是已有仓库，查看 staged / unstaged / untracked 文件

### Step 2: 列出变更文件并让用户确认追踪
根据 `git status` 的结果，展示三类文件给用户：
- **Untracked 文件**（新建还未追踪的）
- **Modified 未暂存文件**（已有修改但没加进暂存区的）
- **已删除的文件**

用简洁列表呈现，问用户："这些文件要追踪并提交吗？" 如果有不想提交的让用户排除。

### Step 3: 执行 git add
用户确认后，逐个执行：
```bash
git add <file1>
git add <file2>
```

### Step 4: 分析 diff 自动生成 message 草案
```bash
git diff --cached
```
根据暂存区 diff 生成 commit message：
- **摘要行**：最合适的 type 前缀（可选加 scope，如 `feat(auth):`）+ 不超过 72 字的英文摘要
- **ADD 部分**：新增的功能/文件
- **FIX 部分**：修复的问题
- **REMOVE 部分**：删除了什么内容/文件（当有文件被删除时使用）
- **CHANGE 部分**：重构、修改了什么行为（当变更不属于新增或修复时使用）
- **STYLE 部分**：代码格式、命名调整等不影响逻辑的变更
- **DOCS 部分**：文档相关的变更
- **CHORE 部分**：构建配置、依赖、工具链变更
- **Footer（可选）**：如果 diff 涉及修复某个 Issue，在末尾加 `Closes #xxx`；如果有不兼容变更，加 `BREAKING CHANGE: <说明>`
- 没有某个部分就省略，只列出有内容的部分

**注：** 对于简单变更，单行摘要即可。对于复杂变更，建议提供多行正文说明**为什么这么改**，而不只是改了什么东西。

### Step 5: 展示 message 给用户确认（不可跳过）
**写完 commit message 后，必须先展示给用户看，用户说OK才能继续。** 这一步不能跳过，不能默认确认。

展示格式示例：
```
📝 Commit message 草案：

feat: add commit-message-writing skill

ADD:
- SKILL.md with full workflow instructions
- references/commit-message-conventions.md
- references/git-commit-identity.md

这个 message 可以吗？需要修改的话告诉我就行。
```

用户确认后再执行 Step 6。

### Step 6: 执行 commit
用户确认后执行：
```bash
git config user.name "ID-VerNe" && git config user.email "yuu_seeing@foxmail.com"
export GIT_COMMITTER_NAME="ID-VerNe"
export GIT_COMMITTER_EMAIL="yuu_seeing@foxmail.com"
git commit -m "$MESSAGE"
```

### Step 7: 执行 push
commit 成功后：
```bash
git push
```
输出 push 结果给用户。

## 参考文件

- `references/commit-message-conventions.md` — Commit message 格式规范详情
- `references/git-commit-identity.md` — 身份信息配置规则

## 常见差错

1. **不要猜测 diff 中没有的变更** — 只根据 `git diff --cached` 的内容写 message
2. **不要批量 add** — 永远一个一个文件 `git add <file>`
3. **push 失败时说明错误信息** — 如果是 remote 相关错误，检查 remote URL 并提示用户
4. **如果用户说"全提交"但暂存区为空** — 走 Step 1→2 流程，先扫描再确认
5. **不要代替用户做排除决定** — 列出所有变更文件让用户选，你自己不判断哪些该提交哪些不该
