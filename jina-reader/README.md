# jina-reader

Jina Reader 匿名轮询网关 + 配套 skill。**请求即开工**：客户端发一次请求，网关不存在就自动后台拉起，无需手动启动服务。

## 它能解决什么

Jina Reader 把任意 URL（网页 / PDF / X 推文）转成 LLM 友好的 Markdown。匿名调用**按 IP 限流 20 RPM，但无 token 池上限**——适合长期高频、不想被免费 key 那 1000 万 token 卡住的场景。

单个 IP 只有 20 RPM。本网关把多个**独立出口 IP** 串成轮询，每出口独立计数，合计约 `出口数 × 20` RPM。某出口触发 429 就自动冷却并切下一个。

> 关键事实：国内镜像 `r.jinaai.cn` / `s.jinaai.cn` 与国际域名 `r.jina.ai` **共享同一 IP 配额**。换域名不增量，只有换出口 IP 才增量。

## 特性

- 匿名调用，无 token 池 / 总量上限
- 多独立出口轮询，单出口 429 自动冷却 62s 并切换
- 三种输出：Markdown（默认）/ JSON / HTML
- 网关日志只记状态码与出口名，**不记目标 URL**
- 端点配置外置且被 gitignore，仓库只留占位符模板
- 仅 Python 标准库 + 系统 `curl` / `ssh`，无第三方依赖
- Windows / macOS / Linux 均可（Windows 优先用 `pythonw` 避免闪窗）

## 一、安装前置

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | 仅标准库，无需 `pip install` |
| `curl` | 系统自带或可用；网关用它发请求 |
| `ssh`（可选） | 只有配了 `ssh` 模式出口才需要 |
| 各出口的 SSH 别名 | 已在你本机 `~/.ssh/config` 配好；**本 skill 不保存任何地址或凭据** |

## 二、配置端点（关键步骤）

### 1. 生成本机配置

```bash
cd <skill-dir>
cp config/endpoints.example.json config/endpoints.json
```

`config/endpoints.json` 已被 `.gitignore` 排除，**永远不会进版本库**。仓库里只有占位符模板。

### 2. 编辑 `config/endpoints.json`

模板结构：

```json
{
  "port": 8767,
  "endpoints": [
    { "name": "local",  "mode": "direct", "domain": "r.jinaai.cn" },
    { "name": "edge-a", "mode": "ssh",    "alias": "<你的别名A>", "domain": "r.jinaai.cn" },
    { "name": "edge-b", "mode": "ssh",    "alias": "<你的别名B>", "domain": "r.jina.ai" }
  ]
}
```

字段含义：

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 出口标识，仅用于状态显示和日志，随便起 |
| `mode` | 是 | `direct` = 本机直连；`ssh` = 经 SSH 别名在远端跑 curl |
| `domain` | 是 | Jina 端点域名。国内网络用 `r.jinaai.cn`；海外机器可用 `r.jina.ai` |
| `alias` | ssh 时必填 | 你本机 `~/.ssh/config` 里已有的别名，如 `<别名A>` |

### 3. 各字段怎么选

**`mode: direct`（本机直连）**
- 适合：本机网络能直连 Jina 的环境（如国内用镜像域名）。
- 网关会自动清掉 `http_proxy/https_proxy/ALL_PROXY` 等环境变量并加 `--noproxy '*'`，确保走本机真实出口。
- 如果本机开了全局代理且无法绕过，直连出口可能与远端撞 IP——此时删掉这个出口即可。

**`mode: ssh`（远端出口）**
- 适合：你有一台能直连 Jina 的机器（国内或海外均可），且本机已配好免密 SSH 别名。
- `alias` 填那个别名；`domain` 按该机器的网络选：国内机器填 `r.jinaai.cn`，海外机器填 `r.jina.ai`。
- 网关通过 `ssh <alias>` 在远端执行 curl，目标 URL 用 base64 传参，避免 shell 注入。
- 可加任意多个，每个算一个独立出口。

**出口数量**：至少一个。想要更高 RPM 就多加几个不同 IP 的出口。`--state` 能看到每个出口的剩余额度和状态。

### 4. 端口（可选）

默认 `8767`。改端口二选一：

```bash
# 方式 A：改 config/endpoints.json 的 port 字段
# 方式 B：环境变量（网关和客户端会自动同步）
export JINA_GATEWAY_PORT=8768
```

### 5. 验证配置

```bash
python scripts/jina.py "https://example.com"   # 应返回 Markdown
python scripts/jina.py --state                  # 看各出口 remaining / available
```

`--state` 里每个出口 `available: true`、`remaining` 接近 20 即配置成功。

> 模板里的 `<...>` 占位符没替换时，网关会**拒绝启动**并提示，避免静默用错配置。

## 三、安装为 skill

把本目录链接到所用 agent 的 skills 目录，改源即全处生效（不会复制副本）。

**WorkBuddy / Claude Code（Windows junction，无需管理员）：**

```powershell
$src = "<skill-dir 的绝对路径>"
New-Item -ItemType Junction -Path "$env:USERPROFILE\.workbuddy\skills\jina-reader" -Target $src
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\jina-reader" -Target $src
```

**OpenCode（symlink）：**

```bash
ln -s "<skill-dir>" ~/.config/opencode/skills/jina-reader
```

> Windows 上不要通过 Git Bash 调 `cmd /c mklink`——路径会被转换导致失败。用 PowerShell 的 `New-Item -ItemType Junction`。

## 四、使用

```bash
# 读网页（默认 Markdown）
python scripts/jina.py "https://example.com"

# 结构化 JSON / 原始 HTML
python scripts/jina.py "https://example.com" --format json
python scripts/jina.py "https://example.com" --format html

# 存文件（正文不打印到 stdout）
python scripts/jina.py "https://example.com" --save out.md

# 运维
python scripts/jina.py --state    # 各出口状态
python scripts/jina.py --stop     # 停后台网关（下次请求会自动拉起）
```

浏览器/脚本也可直接打 HTTP（仅监听 `127.0.0.1`）：

```bash
curl "http://127.0.0.1:8767/https://example.com"
curl "http://127.0.0.1:8767/?url=https%3A%2F%2Fexample.com&format=json"
curl -X POST -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","format":"md"}' http://127.0.0.1:8767/
curl http://127.0.0.1:8767/health
```

完整参数见 `references/api.md`，异常见 `references/troubleshooting.md`。

## 五、隐私设计

- 仓库内**不含**任何明文公网 IP、token、密钥、主机真实归属；模板全是占位符。
- 实际别名只存在于被 gitignore 的 `config/endpoints.json`。
- 网关日志只记方法 + 状态码 + 出口名，**不记目标 URL**；状态接口不返回 URL 列表。
- 换机器/分享仓库时，删掉 `config/endpoints.json` 即可，不会泄漏任何本机信息。
