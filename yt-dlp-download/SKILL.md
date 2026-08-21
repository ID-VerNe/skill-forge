---
name: yt-dlp-download
description: >-
  YouTube 视频下载专家。使用 yt-dlp 下载视频和字幕，支持 480p/1080p、英文自动字幕(json3/srt)、单/批量下载、并行加速、PO token 生成。当用户说"下载视频"、"下这个视频"、"yt-dlp"、"youtube"、"批量下载"、"字幕"、"1080p"、"480p"时触发。使用前必须检查 CLAUDE.md 的 Web Intelligence 部分，优先使用 wigolo 工具进行搜索和查询。
---

# YouTube 视频下载 (yt-dlp)

## 环境依赖

| 依赖 | 用途 | 检查命令 |
|------|------|----------|
| yt-dlp (nightly) | 核心下载工具 | `yt-dlp --version` |
| Node.js >= 22 | EJS challenge solver、BgUtils PO token server | `node --version` |
| ffmpeg | mp4 合并/转换 | `ffmpeg -version` |
| bgutil-ytdlp-pot-provider | PO token 生成(自动字幕必须) | `pip show bgutil-ytdlp-pot-provider` |
| BgUtils server | 常驻 PO token 生成服务 | 见 `references/po-token-server.md` |

## 关键参数速查

### 格式选择

```
分辨率     格式参数
480p       bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]/b
1080p      bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b
```

### 字幕

```
# 英文自动字幕(json3)
--write-auto-subs --sub-langs en --sub-format json3

# 英文自动字幕(srt)
--write-auto-subs --sub-langs en --sub-format srt

# 多语言字幕(如英文+中文)
--write-auto-subs --sub-langs en,zh-Hans
```

### 其他常用

```
# 只下载字幕(不下载视频)
--skip-download --write-auto-subs --sub-langs en --sub-format json3

# 合并输出为 mp4
--merge-output-format mp4

# 批量下载(从文件读取 URL)
-a batch_urls.txt

# 并行下载多个视频
# 每个视频启动一个独立的 yt-dlp 进程
```

## 完整工作流

### 1. 单视频下载

```bash
cd C:/Users/VerNe/Downloads/Videos
yt-dlp --js-runtimes node --cookies cookies.txt \
  -f "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]/b" \
  --merge-output-format mp4 \
  --write-auto-subs --sub-langs en --sub-format json3 \
  -o "%(title)s.%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

### 2. 批量并行下载

```bash
# 1. 创建 URL 列表文件
# (每行一个 URL, 去掉 &t= 等额外参数)

# 2. 逐个启动后台进程(每个间隔 1-2 秒,避免限流)
while IFS= read -r url; do
  id=$(echo "$url" | sed -E 's/.*v=([A-Za-z0-9_-]+).*/\1/')
  yt-dlp --js-runtimes node --cookies cookies.txt \
    -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b" \
    --merge-output-format mp4 \
    --write-auto-subs --sub-langs en --sub-format json3 \
    -o "%(title)s.%(ext)s" "$url" > "dl_$id.log" 2>&1 &
  sleep 2
done < batch_urls.txt
```

### 3. 补齐字幕(视频已下载,只补字幕)

```bash
yt-dlp --js-runtimes node --cookies cookies.txt \
  --skip-download \
  --write-auto-subs --sub-langs en --sub-format json3 \
  -o "%(title)s.%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

## 常见问题与排查

### PO token 缺失(自动字幕下不了)
**症状**: `There are missing subtitles languages because a PO token was not provided`

**原因**: cookies.txt 是静态导出,不含 PO token。PO token 是浏览器运行时 JS 生成的动态令牌。

**解决**: 安装 bgutil-ytdlp-pot-provider 插件 + 启动 BgUtils server。

操作步骤:
1. `pip install bgutil-ytdlp-pot-provider` (已完成)
2. 启动 BgUtils server: `cd ~/bgutil-ytdlp-pot-provider/server && node build/main.js` (需常驻)
3. 验证: `yt-dlp -v --skip-download --write-auto-subs --sub-langs en --sub-format json3 "URL"` 日志中出现 `[pot:bgutil:http] Generating a gvs PO Token` 即为成功

**注意**: BgUtils server 必须常驻运行,重启/关机后需重新启动。

### EJS n-challenge 失败
**症状**: `n challenge solving failed: Some formats may be missing`

**原因**: yt-dlp 2026+ 版本需要 JavaScript runtime 解决 YouTube 的 n 参数。

**解决**: 本地有 Node.js 22+ 时,加 `--js-runtimes node` 参数。

### 速度慢/限流
**症状**: 下载速度降到 KB/s 级别,或报 `HTTP Error 403: Forbidden`

**原因**: YouTube 对单 IP 有速率限制,多连接并行或短时间内大量请求会触发。

**应对**:
- 单视频慢: 加 `--concurrent-fragments 4` 加速分片并行
- 多视频并行: 每个进程间隔 1-2 秒启动,避免同时触发限流
- 被限流 403: 等 1-2 小时冷却后再试,或换 cookies

### Edge cookies 读取失败
**症状**: `Could not copy Chrome cookie database` 或 `Failed to decrypt with DPAPI`

**原因**:
- Edge 开着: SQLite 数据库被进程锁住
- Edge 关着: Windows DPAPI 无法解密 cookie

**解决**: 更可靠的方式是走 BgUtils PO token server,不需要读浏览器 cookie。

### cookies.txt 失效
**症状**: `Sign in to confirm you're not a bot`

**原因**: YouTube 定期轮换 cookie,旧的会失效。

**解决**: 在浏览器中重新登录 YouTube,用 "Get cookies.txt LOCALLY" 扩展导出新的 cookies.txt。

## 输出目录

所有下载文件均在 `C:\Users\VerNe\Downloads\Videos\`。

## 输出文件命名

- 视频: `%(title)s.%(ext)s` → `视频标题.mp4`
- 字幕: `%(title)s.%(ext)s` → `视频标题.en.json3` / `视频标题.en.srt`