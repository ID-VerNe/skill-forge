# BgUtils PO Token Server 维护手册

> 本手册记录 BgUtils PO token server 的安装、启动、故障排查步骤。
> 2026-08-20 完成首次安装，版本 1.3.1。

## 背景

YouTube 从 2026 年起对自动字幕(尤其 web client)强制要求 PO token。
PO token 是浏览器运行时由 JS 现场生成的动态令牌，**无法从静态 cookies.txt 导出**。

两种解决方案:
1. **BgUtils PO token server**(本方案, 已采用)
   - yt-dlp 维护者 Brainicism 开发, yt-dlp 官方推荐
   - Node.js 原生运行, 不需要 Docker
   - 一旦启动, 之后所有 yt-dlp 下载自动带 PO token
2. yt-dlp-getpot-wpc (未采用, 需要 headless 浏览器, 更重)

## 已安装组件

| 组件 | 位置 |
|------|------|
| yt-dlp 插件 | `/c/Users/VerNe/AppData/Local/Programs/Python/Python310/Lib/site-packages/yt_dlp_plugins/extractor/getpot_bgutil*.py` |
| BgUtils server 源码 | `C:\Users\VerNe\bgutil-ytdlp-pot-provider\server\` |

## 启动 BgUtils server

```bash
cd C:/Users/VerNe/bgutil-ytdlp-pot-provider/server
node build/main.js
```

server 监听 `127.0.0.1:4416`。**必须常驻运行**。

### 以后台方式启动 (推荐)

```bash
cd C:/Users/VerNe/bgutil-ytdlp-pot-provider/server
# 后台运行, 日志写入文件
nohup node build/main.js > pot_server.log 2>&1 &
```

### 开机自启 (Windows)

1. 创建 `pot_server.bat`:
   ```bat
   @echo off
   cd C:\Users\VerNe\bgutil-ytdlp-pot-provider\server
   node build/main.js
   ```
2. 放入 `shell:startup` 目录:
   `Win+R` → `shell:startup` → 放入 bat 文件

## 验证 server 是否正常

**方法 1: 直接 ping**
```bash
curl http://127.0.0.1:4416/ping
# 期望: pong / 200 OK
```

**方法 2: 用 yt-dlp 实测**

```bash
cd C:/Users/VerNe/Downloads/Videos
yt-dlp --js-runtimes node --skip-download --write-auto-subs \
  --sub-langs en --sub-format json3 \
  -o "test_%(id)s.%(ext)s" \
  "https://www.youtube.com/watch?v=aEWSx8I94vk"
```

成功标志: 日志中出现
```
[youtube] [pot:bgutil:http] Generating a gvs PO Token for web client via bgutil HTTP server
```
随后正常写出 `.en.json3` 文件。

## 依赖变更checklist

如果未来 yt-dlp 或 bgutil 插件升级:

1. **升级 yt-dlp**: `pip install -U --pre "yt-dlp[default]"`
2. **升级插件**: `pip install -U bgutil-ytdlp-pot-provider`
3. **同步升级 server**: server 必须与插件版本匹配!
   ```bash
   cd C:/Users/VerNe/bgutil-ytdlp-pot-provider/server
   git fetch --tags
   git checkout <新版本标签>
   npm ci
   npx tsc
   node build/main.js  # 重启
   ```

## 故障排查

### server 没起来 / 端口占用
```bash
netstat -ano | grep 4416   # 检查端口
# 如果被占用, 找到 PID 并查看是什么进程
```

### PO token 仍然报错
检查:
1. server 是否在跑: `curl http://127.0.0.1:4416/ping`
2. 插件是否安装: `pip show bgutil-ytdlp-pot-provider`
3. 日志中是否出现 `[pot:bgutil:http]`:
   ```bash
   yt-dlp -v --skip-download "URL" 2>&1 | grep -i "pot"
   ```

### 服务器返回 5xx
通常是 YouTube 风控加强, 等待 5-10 分钟重试。

## 相关文件

- 插件源码: `/c/Users/VerNe/AppData/Local/Programs/Python/Python310/Lib/site-packages/yt_dlp_plugins/extractor/`
- server 源码: `C:\Users\VerNe\bgutil-ytdlp-pot-provider\server\src\`