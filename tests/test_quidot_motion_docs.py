# -*- coding: utf-8 -*-
"""回归测试: quidot-motion-choreography 的文档断言与其代码一致（issue #69）。

## 为什么要单开一个文件

issue #69 的发现全部来自**可运行实测**：把 `references/recipes-web-motion.md`
的六段食谱搭成 React + motion 测试床逐帧采样，把 `recipes-compose.md` 的六段
Kotlin 放进 AGP 8.7.3 模块编译。结论是 `SKILL.md` 写下的绝对约束与它自己给出
的食谱代码互相矛盾——一个照 `SKILL.md` 做无障碍验收的 agent 会被误导。

这类缺陷的共同点是：**单看文字看不出来，要读了文字再去读代码**。D1-D7 是跨
文件的结构性核对；D8 更进一步，把文档里的 tsx 代码块抽出来交给真实解析器，
因为「文字说得对但代码不能编译」是本次要防的同类缺陷。

D8 在缺 esbuild/typescript 时**跳过并打印原因**，不假装通过——本仓库的测试
环境不保证有 Node 工具链，但拿不到工具时静默变绿比不跑更糟。

## 锁住的八件事

  D1 SKILL.md 的 reduced-motion 条款写清了两端差异（Compose 自动、Web 只覆盖
     transform/opacity/layout），且不再把 "bends" 当作框架能抑制的东西
  D2 两个 recipes 文件里不存在裸 `setTimeout` 驱动的形变
  D3 Web recipe 1 同时具备：恒定目标的自终止脉冲、内层反向缩放、reduce 分支、
     脉冲在飞时的重入守卫
  D4 Web recipe 5 不再用 `boxShadow` 作为形变载体
  D5 Web recipe 3 写明了 flexGrow 与 scale 叠加后的有效比值
  D6 Compose recipe 1 有内层反向缩放；recipe 3 写明了 weight 不是宽度比；
     Compose 侧不出现手工 reduced-motion 分支
  D7 Web 文件头有 MotionConfig 载体覆盖矩阵
  D8 文档里的 tsx 代码块能被真实解析（链条语法错误 / JSX 注释位置写错）

跑法:
  cd <skill-forge>
  python tests/test_quidot_motion_docs.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quidot-motion-choreography")
)

PASS = 0
FAIL = 0
SKIP = 0
FAILED_NAMES: list = []


def read(*parts: str) -> str:
    path = os.path.join(SKILL_ROOT, *parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        result = fn()
    except AssertionError as exc:
        FAIL += 1
        FAILED_NAMES.append(name)
        print("  FAIL  %s\n        %s" % (name, exc))
    except SkipTest as exc:
        SKIP += 1
        print("  SKIP  %s\n        %s" % (name, exc))
    except Exception as exc:  # noqa: BLE001 - 测试要如实报，不要吞
        FAIL += 1
        FAILED_NAMES.append(name)
        print("  ERROR %s\n        %s: %s" % (name, type(exc).__name__, exc))
    else:
        PASS += 1
        extra = "" if result is None else "  " + str(result)
        print("  ok    %s%s" % (name, extra))


class SkipTest(Exception):
    """环境不具备，无法执行——必须打印原因，不能静默通过。"""


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def code_blocks(text: str) -> list:
    """抽出所有 fenced code block 的正文（用于把断言限定在代码里）。"""
    return re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S)


# ---------------------------------------------------------------- D1
def t_d1_reduced_motion_split():
    """SKILL.md 必须把 Compose 与 Web 的 reduced-motion 差异写清楚。"""
    skill = read("SKILL.md")
    require("Respect Reduced Motion" in skill, "SKILL.md 缺少 Respect Reduced Motion 条款")

    solo = skill[skill.index("Respect Reduced Motion"):]
    solo = solo[:solo.index("\n\n## ")] if "\n\n## " in solo else solo

    require(
        "Compose" in solo and ("自动" in solo or "automatically" in solo),
        "SKILL.md 未写明 Compose 侧自动响应 animator scale",
    )
    for carrier in ("transform", "opacity", "layout"):
        require(carrier in solo, "SKILL.md 未点名 MotionConfig 只覆盖 %s" % carrier)
    require(
        "boxShadow" in solo or "attribute" in solo or "属性动画" in solo,
        "SKILL.md 未指出属性动画（boxShadow / SVG d）不受 MotionConfig 抑制",
    )
    require(
        ("instant" in solo or "瞬时" in solo) and ("worse" in solo or "更" in solo),
        "SKILL.md 未说明 reduce 下瞬时跳变尺寸的代价",
    )


def t_d1b_bends_not_promised():
    """'bends' 是 SVG path 属性动画，不能仍被当作框架自动抑制的对象。"""
    skill = read("SKILL.md")
    line = [ln for ln in skill.splitlines() if "Respect Reduced Motion" in ln][0]
    require(
        "bends into gentle fades" not in line,
        "SKILL.md 仍在承诺把 bends 塌陷成 fade——bends 是 SVG d 属性动画，"
        "MotionConfig 抑制不到，必须由 recipe 自己分支",
    )


# ---------------------------------------------------------------- D2
def t_d2_no_bare_timer_in_web_recipes():
    """Web 食谱里不允许出现 setTimeout 驱动的形变。"""
    text = read("references", "recipes-web-motion.md")
    hits = []
    for block in code_blocks(text):
        code = "\n".join(ln for ln in block.splitlines()
                         if not ln.strip().startswith("//"))
        if re.search(r"\bsetTimeout\s*\(", code):
            hits.append(code.strip().splitlines()[0][:60])
    require(not hits, "recipes-web-motion.md 仍有 setTimeout 驱动形变: %s" % hits)


def t_d2b_recipe2_releases_on_pointer_up():
    """recipe 2 必须用 pointerup/leave/cancel 归零，不能用定时器。"""
    text = read("references", "recipes-web-motion.md")
    sec = text[text.index("## 2. Interruptible Force-Vector"):]
    sec = sec[:sec.index("\n## 3.")]
    require("onPointerUp" in sec, "recipe 2 未在 onPointerUp 归零")
    require("onPointerLeave" in sec, "recipe 2 未处理 drag-off（onPointerLeave）")
    require("onPointerCancel" in sec, "recipe 2 未处理 scroll-cancel（onPointerCancel）")


# ---------------------------------------------------------------- D3
def t_d3_web_recipe1_impulse():
    """recipe 1 必须是恒定目标的自终止脉冲 + 反向缩放 + reduce + 重入守卫。"""
    text = read("references", "recipes-web-motion.md")
    sec = text[text.index("## 1. Transient Axis Elongation"):]
    sec = sec[:sec.index("\n## 2.")]
    body = "\n".join(code_blocks(sec))

    require(
        re.search(r"animate\(\s*stretch\s*,\s*1\s*,", body),
        "recipe 1 的 animate 目标不是静止值 1（不是自终止脉冲）",
    )
    require("velocity:" in body, "recipe 1 没有用初速度造脉冲，峰值无法解析地控制")
    require(
        not re.search(r"setPulse\s*\(", body),
        "recipe 1 仍在用 pulse 布尔量翻转目标（会叠加第二条动画）",
    )
    require(
        re.search(r"1\s*/\s*s", body) or "useTransform(stretch" in body,
        "recipe 1 缺少内层反向缩放",
    )
    require("counter" in body, "recipe 1 缺少 counter-scale 变量")
    require("useReducedMotion" in body, "recipe 1 缺少 useReducedMotion 分支")
    require(
        re.search(r"stretch\.get\(\)\s*>", body),
        "recipe 1 缺少脉冲进行中的重入守卫（连点会累积速度）",
    )


def t_d3b_recipe1_peak_documented():
    """峰值解析式必须写进文档，否则没人能重算参数。"""
    text = read("references", "recipes-web-motion.md")
    sec = text[text.index("## 1. Transient Axis Elongation"):]
    sec = sec[:sec.index("\n## 2.")]
    require("√k" in sec or "sqrt" in sec, "recipe 1 未给出峰值解析式 v/(sqrt(k)*e)")


# ---------------------------------------------------------------- D4
def t_d4_recipe5_no_boxshadow():
    """recipe 5 不能用 boxShadow 作为形变载体。"""
    text = read("references", "recipes-web-motion.md")
    sec = text[text.index("## 5. Synchronous Extrusion"):]
    sec = sec[:sec.index("\n## 6.")]
    body = "\n".join(code_blocks(sec))
    require(
        "boxShadow" not in body,
        "recipe 5 仍以 boxShadow 作为形变载体——属性动画，MotionConfig 抑制不到",
    )
    require("lip" in body, "recipe 5 缺少独立的静态唇层（lip）")
    require(
        re.search(r"whileTap=\{\{\s*y:", body),
        "recipe 5 的按下反馈不是 transform(y)",
    )


# ---------------------------------------------------------------- D5
def t_d5_recipe3_ratio_comment():
    text = read("references", "recipes-web-motion.md")
    sec = text[text.index("## 3. Aspect-Ratio"):]
    sec = sec[:sec.index("\n## 4.")]
    require(
        "1.85" in sec or "1.851" in sec,
        "recipe 3 未写明 flexGrow × scale 叠加后的有效比值",
    )


# ---------------------------------------------------------------- D6
def t_d6_compose_recipe1_counter_scale():
    text = read("references", "recipes-compose.md")
    sec = text[text.index("## 1. Transient Axis Elongation"):]
    sec = sec[:sec.index("\n## 2.")]
    body = "\n".join(code_blocks(sec))
    require(
        re.search(r"1f\s*/\s*stretch\.value", body),
        "Compose recipe 1 缺少内层 graphicsLayer { scaleX = 1f / stretch.value }",
    )


def t_d6b_compose_recipe3_weight_semantics():
    text = read("references", "recipes-compose.md")
    sec = text[text.index("## 3. Aspect-Ratio"):]
    sec = sec[:sec.index("\n## 4.")]
    require(
        "weight" in sec and ("不是宽度比" in sec or "not a width ratio" in sec),
        "Compose recipe 3 未说明 1.6f 是 weight 而非宽度比",
    )


def t_d6c_compose_no_manual_reduce_branch():
    """Compose 侧不该出现手工 reduced-motion 分支（框架已自动处理）。"""
    text = read("references", "recipes-compose.md")
    body = "\n".join(code_blocks(text))
    require(
        "useReducedMotion" not in body,
        "recipes-compose.md 出现 useReducedMotion——Compose 侧应由框架自动处理",
    )


# ---------------------------------------------------------------- D7
def t_d7_web_header_boundary_table():
    """文件头必须写明 MotionConfig 覆盖不到的载体。"""
    text = read("references", "recipes-web-motion.md")
    head = text[:text.index("## 1. Transient Axis")]
    require("MotionConfig" in head, "文件头未提 MotionConfig")
    for carrier in ("boxShadow", "SVG", "filter"):
        require(carrier in head, "文件头未列出不受抑制的载体: %s" % carrier)
    require("No" in head, "文件头未给出覆盖矩阵")


# ---------------------------------------------------------------- D8
def _find_esbuild() -> str | None:
    """找可直接执行的 esbuild。

    查找顺序：
      1. 环境变量 QUIDOT_ESBUILD（CI 或自定义安装位置）
      2. PATH 上的 esbuild
      3. 仓库根及其各级祖先的 experiments/*/node_modules/@esbuild/<platform>/
         逐级向上是因为本仓库常在 worktree 里跑测试，而 node_modules 只装在
         主检出目录。

    Windows 上 `node_modules/.bin/esbuild` 是 sh 脚本，subprocess 无法直接执行，
    所以直接找平台包装里的二进制。
    """
    env = os.environ.get("QUIDOT_ESBUILD")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("esbuild")
    if found:
        return found

    platform_pkgs = (
        ("win32-x64", "esbuild.exe"),
        ("linux-x64", os.path.join("bin", "esbuild")),
        ("darwin-x64", os.path.join("bin", "esbuild")),
        ("darwin-arm64", os.path.join("bin", "esbuild")),
        ("linux-arm64", os.path.join("bin", "esbuild")),
    )
    start = os.path.dirname(SKILL_ROOT)
    cur = start
    for _ in range(6):  # 最多向上 6 级，够覆盖 .claude/worktrees/<name>/ 的深度
        exp = os.path.join(cur, "experiments")
        if os.path.isdir(exp):
            for name in sorted(os.listdir(exp)):
                nm = os.path.join(exp, name, "node_modules", "@esbuild")
                for pkg, rel in platform_pkgs:
                    cand = os.path.join(nm, pkg, rel)
                    if os.path.isfile(cand):
                        return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def t_d8_documented_tsx_parses():
    """文档里的 tsx 片段必须能被真实解析器接受。

    只做语法检查，不要求依赖可解析：把片段包进函数体，用 esbuild 的
    transform 接口（不解析 import）验证。JSX 注释写成 `//`、标签闭合错误
    这类问题会在此暴露。
    """
    esbuild = _find_esbuild()
    if not esbuild:
        raise SkipTest("找不到 esbuild（PATH 与 experiments/*/node_modules 均无），"
                       "无法做语法验证；这是跳过，不是通过")

    text = read("references", "recipes-web-motion.md")
    blocks = [b for b in code_blocks(text) if _looks_like_tsx(b)]
    require(blocks, "没有找到任何 tsx 代码块，测试失效")

    prelude = (
        "import { AnimatePresence, animate, motion, MotionConfig,"
        " useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react';\n"
        "import React, { useState } from 'react';\n"
        "declare const dir: number, value: any, setValue: any, onSelect: any,"
        " id: any, isActive: boolean, lip: number, setDir: any, reduce: boolean,"
        " stretch: any, counter: any, scaleY: any, force: any, dim: any,"
        " setDim: any, trayPath: any, arrowY: any, socketX: any, socketY: any,"
        " x: any, y: any, press: any, release: any, onChange: any;\n"
    )

    failures = []
    for i, block in enumerate(blocks):
        # 文档片段有两种形态：语句型（const / function / JSX 赋值）与裸 JSX。
        # 语句型直接作为函数体；裸 JSX 必须包进 return。
        # 判据：去掉注释行后是否出现顶层声明关键字。
        code_lines = [ln for ln in block.splitlines() if not ln.strip().startswith("//")]
        code = "\n".join(code_lines)
        is_statement_form = bool(re.search(r"^\s*(const|let|var|function|export)\b", code, re.M))
        if is_statement_form:
            body = "export function Probe() {\n" + block + "\n}\n"
        else:
            body = "export function Probe() {\n  return (\n<>\n" + block + "\n</>\n  );\n}\n"
        wrapped = prelude + body
        with tempfile.NamedTemporaryFile("w", suffix=".tsx", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(wrapped)
            tmp = fh.name
        try:
            proc = subprocess.run(
                [esbuild, tmp, "--loader:.tsx=tsx", "--format=esm"],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                first = (proc.stderr or "").strip().splitlines()
                failures.append("第 %d 个 tsx 块: %s" % (
                    i + 1, next((ln for ln in first if "ERROR" in ln), first[0] if first else "?")))
        finally:
            os.unlink(tmp)
    require(not failures, "文档中的 tsx 片段无法解析:\n        " + "\n        ".join(failures))
    return "%d 个 tsx 块全部可解析" % len(blocks)


def _looks_like_tsx(block: str) -> bool:
    """判断代码块是不是 tsx（web recipes 的块都含 JSX 或 React API）。

    这层过滤是为了把 '```text' 之类的说明块排除在外；web 文件里所有食谱块
    都含 motion.* 或 use* 调用或裸 JSX 标签。
    """
    if "<" in block and ">" in block and ("motion." in block or "</" in block or "<svg" in block or "<div" in block):
        return True
    return bool(re.search(r"\b(useMotionValue|useSpring|useTransform|useReducedMotion|animate)\s*\(", block))


def main():
    print("=" * 70)
    print("quidot-motion-choreography 文档一致性回归测试 (issue #69)")
    print("=" * 70)
    test("D1 SKILL.md 分端写明 reduced motion", t_d1_reduced_motion_split)
    test("D1b SKILL.md 不再承诺 bends 被框架抑制", t_d1b_bends_not_promised)
    test("D7 Web 文件头有载体覆盖矩阵", t_d7_web_header_boundary_table)
    test("D2 Web 食谱无 setTimeout 驱动形变", t_d2_no_bare_timer_in_web_recipes)
    test("D2b recipe 2 在 pointerup 归零", t_d2b_recipe2_releases_on_pointer_up)
    test("D3 recipe 1 是自终止脉冲", t_d3_web_recipe1_impulse)
    test("D3b recipe 1 峰值解析式", t_d3b_recipe1_peak_documented)
    test("D4 recipe 5 不用 boxShadow", t_d4_recipe5_no_boxshadow)
    test("D5 recipe 3 有效比值", t_d5_recipe3_ratio_comment)
    test("D6 Compose recipe 1 反向缩放", t_d6_compose_recipe1_counter_scale)
    test("D6b Compose recipe 3 weight 语义", t_d6b_compose_recipe3_weight_semantics)
    test("D6c Compose 无手工 reduce 分支", t_d6c_compose_no_manual_reduce_branch)
    test("D8 文档 tsx 片段可解析", t_d8_documented_tsx_parses)
    print()
    if FAILED_NAMES:
        print("失败项: %s" % ", ".join(FAILED_NAMES))
    print(f"通过 {PASS} / 失败 {FAIL}" + (f"（跳过 {SKIP}）" if SKIP else ""))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
