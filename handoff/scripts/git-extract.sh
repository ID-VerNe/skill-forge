#!/usr/bin/env bash
# git-extract.sh — 提取 handoff 交接文档所需的数据
# 输出: 项目元数据、技术栈、git 基线、commit 日志、变更文件列表
# 用法: bash scripts/git-extract.sh

set -euo pipefail

#############################################
# 1. 项目元数据检测
#############################################
echo "=== 项目元数据 ==="

# package.json
if [ -f package.json ]; then
  echo "存在 package.json"
  echo "  项目名: $(node -e "console.log(require('./package.json').name || 'unknown')" 2>/dev/null || echo '读取失败')"
  echo "  描述: $(node -e "console.log(require('./package.json').description || '无')" 2>/dev/null || echo '读取失败')"
  echo "  scripts: $(node -e "try{console.log(Object.keys(require('./package.json').scripts||{}).join(', '))}catch(e){console.log('无')}" 2>/dev/null || echo '无')"
  echo "  依赖框架: $(node -e "const p=require('./package.json');const d={...p.dependencies,...p.devDependencies};console.log(Object.entries(d).filter(([k])=>/react|vue|svelte|next|nuxt|express|fastify|koa|solid/.test(k)).map(([k,v])=>k+'@'+v).join(', ')||'通用Node项目')" 2>/dev/null || echo '无法解析')"
fi

# 锁文件 → 包管理器
echo "-- 包管理器 --"
if [ -f pnpm-lock.yaml ]; then echo "pnpm"; fi
if [ -f package-lock.json ]; then echo "npm"; fi
if [ -f yarn.lock ]; then echo "yarn"; fi
if [ -f bun.lockb ]; then echo "bun"; fi
if [ -f pyproject.toml ]; then echo "python (pyproject.toml)"; fi
if [ -f go.mod ]; then echo "go"; fi
if [ -f Cargo.toml ]; then echo "rust"; fi
if [ -f composer.json ]; then echo "php"; fi

# 技术栈
echo "-- 技术栈标志 --"
[ -f pyproject.toml ] && head -20 pyproject.toml
[ -f go.mod ] && head -5 go.mod
[ -f Cargo.toml ] && head -10 Cargo.toml
[ -f docker-compose.yml ] && echo "有 docker-compose.yml"
[ -f Dockerfile ] && echo "有 Dockerfile"
[ -f Makefile ] && echo "有 Makefile"

# 目录结构提示
echo "-- 目录结构 --"
for d in src app client frontend backend server components pages apps packages tools lib core api admin web mobile worker; do
  [ -d "$d" ] && echo "  有 $d/ 目录"
done

#############################################
# 2. Git 信息
#############################################
echo ""
echo "=== Git 信息 ==="

if [ ! -d .git ]; then
  echo "当前目录不是 git 仓库，跳过 git 信息提取。"
  exit 0
fi

echo "当前分支: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '无')"
echo "当前 HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo '无')"

# 检测基线：找上一份 handoff 的最后 commit
echo ""
echo "=== 基线检测 ==="
BASELINE=""
if [ -d .handoffs ]; then
  # 取文件名排序最大的 handoff（最新的）
  LATEST_HANDOFF=$(ls .handoffs/handoff-*.md 2>/dev/null | sort -V | tail -1)
  if [ -n "$LATEST_HANDOFF" ]; then
    echo "找到上一份 handoff: $LATEST_HANDOFF"
    # 在上一份 handoff 中找最后一个 commit hash（Git 节点记录表格中的 `hash` 格式）
    # 优先匹配表格行中的 `xxx` 格式，取最后一行
    BASELINE=$(grep -oE '\`[a-f0-9]{7,40}\`' "$LATEST_HANDOFF" 2>/dev/null | tr -d '`' | tail -1 || echo "")
    if [ -n "$BASELINE" ]; then
      echo "检测到基线 commit: $BASELINE（来自上一份 handoff 的 Git 节点记录）"
    else
      # fallback: 匹配任意独立 hex 序列（兼容旧版 handoff 格式）
      BASELINE=$(grep -oE '\b[a-f0-9]{7,40}\b' "$LATEST_HANDOFF" 2>/dev/null | tail -1 || echo "")
      if [ -n "$BASELINE" ]; then
        echo "检测到基线 commit: $BASELINE（来自 handoff 正文匹配）"
      fi
    fi
  fi
fi

# 如果没有基线，检查是否已有该 handoff 同名的文件记录基线
if [ -z "$BASELINE" ]; then
  # 用 git log 找最近 20 条，提示用户选择范围
  echo "未检测到基线 commit。最近提交如下："
fi

echo ""
echo "=== Commit 日志 ==="
if [ -n "$BASELINE" ]; then
  echo "从基线 $BASELINE 到 HEAD 的提交："
  git log --oneline --decorate "$BASELINE"..HEAD 2>/dev/null || echo "（基线之后无新提交或基线不可达）"
  echo ""
  echo "=== Commit 详情（基线到 HEAD） ==="
  git log --format="---%nHASH:%h%nDATE:%ad%nAUTHOR:%an%nDESC:%s%n" --date=format:'%Y-%m-%d %H:%M' "$BASELINE"..HEAD 2>/dev/null || echo "（基线之后无新提交）"
else
  echo "最近 30 条提交："
  git log --oneline --decorate -30 2>/dev/null || echo "无提交记录"
  echo ""
  echo "=== Commit 详情（最近 10 条） ==="
  git log --format="---%nHASH:%h%nDATE:%ad%nAUTHOR:%an%nDESC:%s%n" --date=format:'%Y-%m-%d %H:%M' -10 2>/dev/null || echo "无"
fi

echo ""
echo "=== 未提交的改动 ==="
git status --short 2>/dev/null || echo "无"

echo ""
echo "=== git 身份 ==="
echo "user.name: $(git config user.name 2>/dev/null || echo '未设置')"
echo "user.email: $(git config user.email 2>/dev/null || echo '未设置')"