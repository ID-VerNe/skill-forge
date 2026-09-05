#!/usr/bin/env python3
"""add-license.py — 把内置 license 模板拷贝到目标目录并替换占位符。

用法:
  python.bat add-license.py --license mit --dir <目标目录> \
      --year 2026 --name "ID-VerNe" [--filename LICENSE] [--dry-run]

行为:
  - 模板来自本脚本同级的 ../references/<key>.txt，不依赖当前目录。
  - 替换占位符: [year] [fullname]（mit/bsd-2/bsd-3 版权行）,
    [yyyy] [name of copyright owner]（apache-2.0 附录）,
    <year>  <name of author>（gpl-3.0 附录）。
  - 输出统一 LF 行尾。
  - --dry-run 只打印将要写入的内容，不落盘。
  仅标准库，无第三方依赖。
"""

import argparse
import os
import re
import sys
from pathlib import Path


def resolve_template(key: str) -> Path:
    """模板文件固定在本脚本 ../references/ 下。"""
    return Path(__file__).resolve().parent.parent / "references" / f"{key}.txt"


AVAILABLE = sorted(
    p.stem
    for p in (Path(__file__).resolve().parent.parent / "references").glob("*.txt")
)


def fill(copyright_text: str, year: str, name: str) -> str:
    """按许可证实际使用的占位符风格依次替换。

    GitHub API licenses 文本中:
      - mit / bsd-2-clause / bsd-3-clause:  '[year] [fullname]' 或 '[year], [fullname]'
      - apache-2.0 附录:                      '[yyyy] [name of copyright owner]'
      - gpl-3.0 HOW TO APPLY 示例:            'Copyright (C) <year>  <name of author>'
    """
    text = copyright_text
    # [year] 型（放在 [yyyy] 之前替换，避免 yyyy 里的 "year" 误伤——正则锚定 '[' 开头所以无碍）
    text = re.sub(r"\[year\]", year, text)
    text = re.sub(r"\[fullname\]", name, text)
    # [yyyy] / [name of ...] 型
    text = re.sub(r"\[yyyy\]", year, text)
    text = re.sub(r"\[name of copyright owner\]", name, text)
    # <year> <name of author> 型（GPL 附注）
    text = re.sub(r"<year>", year, text)
    text = re.sub(r"<name of author>", name, text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="拷贝并定制开源许可证")
    parser.add_argument("--license", required=True, help="许可证 key，如 mit / apache-2.0")
    parser.add_argument("--dir", required=True, help="目标目录（不存在则创建）")
    parser.add_argument("--filename", default="LICENSE", help="输出文件名，默认 LICENSE")
    parser.add_argument("--year", default=str(__import__("datetime").datetime.now().year))
    parser.add_argument("--name", default="", help="版权持有者，缺省会尝试从 git 读取")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = parser.parse_args()

    if args.license not in AVAILABLE:
        sys.exit(
            f"未知 license: {args.license}\n可选: {', '.join(AVAILABLE)}"
        )

    if not args.name:
        args.name = git_name(Path(args.dir))
    if not args.name:
        sys.exit("未提供版权持有者（--name），且当前 git 配置里没有 user.name。")

    template = resolve_template(args.license)
    result = fill(template.read_text(encoding="utf-8"), args.year, args.name)

    if args.dry_run:
        sys.stdout.write(result)
        return 0

    target_dir = Path(args.dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / args.filename
    if target.exists():
        print(f"警告: {target} 已存在,将覆盖", file=sys.stderr)
    target.write_text(result, encoding="utf-8", newline="\n")
    print(f"已写入 {target}")
    return 0


def git_name(path: Path) -> str:
    """取 git user.name，回退顺序: 目标目录 -> 当前目录 -> 全局配置。

    目标目录可能尚未创建（名字解析发生在 mkdir 之前），且 git -C 指向
    不存在的目录会报错，所以逐级回退到能用的范围。
    """
    import subprocess

    candidates = [str(path), os.getcwd()]
    for c in candidates:
        try:
            out = subprocess.run(
                ["git", "-C", c, "config", "user.name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            continue
    # 全局配置兜底
    try:
        out = subprocess.run(
            ["git", "config", "--global", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    sys.exit(main())