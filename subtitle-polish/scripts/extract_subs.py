# -*- coding: utf-8 -*-
"""extract_subs.py — 从片源抽字幕流，作为对齐/翻译的起点。

为什么单独一个脚本：`align_audit` 只负责"对不对"，前提是手里已经有一条
字幕。而真实起点往往是"片源里躺着 4 条不同剪辑版本的字幕流，不知道用哪条"。
抽流 + 判轴是这条流水线的入口，不该靠手敲 ffmpeg（流索引、编码、样式名
三个地方都容易错）。

典型用法（先列后抽）：

  python extract_subs.py --media S06E01.mkv --list
  python extract_subs.py --media S06E01.mkv --out .subtitle-polish/streams --format srt

抽完接 align_audit 判轴：

  python align_audit.py --sub streams/E01.s2.ass --asr-words w.json \
      --compare streams/E01.s3.ass --compare streams/E01.s4.ass

判据见 references/align-audit.md §4：**MAD 最小者才是可信基线**。

注意：抽出的单语流样式名通常不是"英文/中文"，所以 `align_audit --track ""`
才能全取；脚本默认转 srt 就是为了避开这个坑。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CODEC_EXT = {
    "ass": ".ass", "ssa": ".ass", "subrip": ".srt", "srt": ".srt",
    "mov_text": ".srt", "webvtt": ".vtt", "hdmv_pgs_subtitle": ".sup",
    "dvd_subtitle": ".sub",
}


def _need(tool):
    p = shutil.which(tool)
    if not p:
        raise SystemExit("未找到 %s：抽流需要 ffmpeg/ffprobe。" % tool)
    return p


def probe(media):
    """-> [{'index','codec','lang','title','default','forced'}]（只含字幕流）"""
    ffprobe = _need("ffprobe")
    cmd = [ffprobe, "-v", "error", "-select_streams", "s",
           "-show_entries",
           "stream=index,codec_name:stream_tags=language,title:stream_disposition=default,forced",
           "-of", "json", media]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("ffprobe 失败：\n" + (out.stderr or "")[-600:])
    import json
    data = json.loads(out.stdout or "{}")
    streams = []
    for s in data.get("streams", []):
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        streams.append({
            "index": s.get("index"),
            "codec": s.get("codec_name") or "",
            "lang": tags.get("language") or "",
            "title": tags.get("title") or "",
            "default": bool(disp.get("default")),
            "forced": bool(disp.get("forced")),
        })
    return streams


def _slug(text, limit=40):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip()).strip("-")
    return s[:limit] or "sub"


def _tag(title, lang):
    """从标题里提炼能区分的短标签。

    片源标题普遍是 `Original | English (United Kingdom) | (SDH)` 这种长串，
    直接截断会把 UK/US 截成同一个前缀，四条流看起来一模一样。
    """
    t = (title or "").lower()
    parts = []
    if "kingdom" in t or re.search(r"\buk\b", t) or "british" in t:
        parts.append("uk")
    elif "states" in t or re.search(r"\bus\b", t) or "american" in t:
        parts.append("us")
    if "sdh" in t or "hearing" in t:
        parts.append("sdh")
    if "forced" in t:
        parts.append("forced")
    if not parts and lang:
        parts.append(lang)
    return ".".join(parts) or "sub"


def list_streams(media, streams):
    print("%s\n" % os.path.basename(media))
    print("%-5s %-8s %-6s %-4s %-4s %s"
          % ("序号", "编码", "语言", "默认", "强制", "标题"))
    for k, s in enumerate(streams):
        print("%-5s %-8s %-6s %-4s %-4s %s"
              % ("s:%d(#%s)" % (k, s["index"]), s["codec"], s["lang"] or "-",
                 "是" if s["default"] else "", "是" if s["forced"] else "",
                 s["title"] or "(无标题)"))
    if not streams:
        print("（这条片源没有内嵌字幕流）")


def extract(media, streams, out_dir, fmt, only=None):
    ffmpeg = _need("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(media))[0]
    # 片名通常很长，取集号片段做前缀，避免路径过长
    m = re.search(r"(S\d{2}E\d{2})", stem, re.I)
    prefix = m.group(1).upper() if m else _slug(stem, 24)

    picked = []
    for k, s in enumerate(streams):
        if only is not None and k not in only:
            continue
        src_ext = CODEC_EXT.get(s["codec"], ".ass")
        ext = src_ext if fmt == "keep" else (".srt" if fmt == "srt" else ".ass")
        codec_args = (["-c:s", "copy"] if fmt == "keep"
                      else ["-c:s", "srt" if fmt == "srt" else "ass"])
        name = "%s.s%d.%s%s" % (prefix, k, _tag(s["title"], s["lang"]), ext)
        dst = os.path.join(out_dir, name)
        cmd = [ffmpeg, "-y", "-v", "error", "-i", media,
               "-map", "0:%d" % s["index"]] + codec_args + [dst]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 200:
            print("  [skip] s:%d %s -> 抽取失败 %s"
                  % (k, s["codec"], (r.stderr or "").strip()[-160:]))
            continue
        picked.append((k, dst, s))
        print("  [ok]   s:%d  %-8s %-6s  %8d B  -> %s"
              % (k, s["codec"], s["lang"] or "-", os.path.getsize(dst),
                 os.path.basename(dst)))
    return picked


def run_axis(media, picked, out_dir, asr_words=None):
    """抽完直接判轴：一次 ASR，比对全部候选，把结论写进凭据。

    一次而不是 N 次：`--compare` 复用同一份词级时间戳，4 条流也只跑一次模型。
    `--credential-target chosen` 让凭据落在判定出的那条流上——判轴的产出就是
    「这一集的轴定在哪」，凭据必须跟着结论走，而不是跟着第一个候选走。
    """
    primary = picked[0][1]
    cmd = [sys.executable, os.path.join(HERE, "align_audit.py"),
           "--sub", primary, "--media", media,
           "--json", os.path.join(out_dir, "axis.json"),
           "--report", os.path.join(out_dir, "axis.md"),
           "--write-credential", "--credential-target", "chosen"]
    for _k, path, _s in picked[1:]:
        cmd += ["--compare", path]
    if asr_words:
        cmd += ["--asr-words", asr_words]

    print("\n判轴（一次 ASR 比对 %d 条候选）" % len(picked))
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if line.startswith(("[axis]", "  轴族", "    ", "  →", "  [cred]")):
            print(line)
        elif "判定" in line or "MAD" in line:
            print("  " + line.strip())

    jp = os.path.join(out_dir, "axis.json")
    res = None
    if os.path.exists(jp):
        try:
            with open(jp, encoding="utf-8") as f:
                res = json.load(f).get("axis")
        except Exception:
            res = None
    if res:
        print("\n  结论 %s —— %s" % (res["verdict"], res.get("reason", "")))
        if res.get("chosen"):
            print("  用 %s" % res["chosen"])
        return {"code": res["code"], "axis": res}
    print("  [!] 没拿到判定结果，原始输出：\n%s" % out[-1200:])
    return {"code": 3, "axis": None}


def main():
    ap = argparse.ArgumentParser(description="从片源抽字幕流")
    ap.add_argument("--media", required=True, help="MKV/MP4 等容器")
    ap.add_argument("--list", action="store_true", help="只列流，不抽")
    ap.add_argument("--out", default=".subtitle-polish/streams", help="输出目录")
    ap.add_argument("--format", choices=["srt", "ass", "keep"], default="srt",
                    help="输出格式（默认 srt：避开样式名不是『英文』的坑）")
    ap.add_argument("--index", help="只抽指定序号（按 --list 的 s:N，逗号分隔，如 2,3）")
    ap.add_argument("--axis", action="store_true",
                    help="抽完直接判轴并把结论写进 <episode>.ts.json（需要片源音频）")
    ap.add_argument("--asr-words", help="--axis 用：复用已有词级时间戳，跳过模型")
    args = ap.parse_args()

    streams = probe(args.media)
    list_streams(args.media, streams)
    if args.list or not streams:
        return

    only = None
    if args.index:
        only = {int(x.strip()) for x in args.index.split(",") if x.strip() != ""}
    print("\n抽流 -> %s（格式 %s）" % (args.out, args.format))
    picked = extract(args.media, streams, args.out, args.format, only)

    if args.axis and picked:
        if len(picked) == 1:
            print("\n只有一条流，用不着判轴；直接写凭据：")
            print("  python align_audit.py --sub %s --media %s --write-credential"
                  % (picked[0][1], args.media))
            return
        res = run_axis(args.media, picked, args.out, args.asr_words)
        sys.exit(res["code"])

    if len(picked) > 1:
        print("\n下一步：判哪条与音频同轴（不要把第一条当默认）")
        print("  python align_audit.py --sub %s --media %s --compare %s ..."
              % (picked[0][1], args.media,
                 " --compare ".join(p[1] for p in picked[1:])))
        print("  或直接加 --axis 让脚本自己判（--asr-words 可复用缓存）")


if __name__ == "__main__":
    main()
