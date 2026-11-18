# Jina Reader 网关 API

## 客户端 CLI（推荐）

```bash
python scripts/jina.py <URL> [--format md|json|html] [--save FILE]
python scripts/jina.py --state
python scripts/jina.py --stop
```

| 参数 | 说明 |
|---|---|
| `--format md` | 默认，`Title / URL Source / Markdown Content` 文本 |
| `--format json` | Jina 结构化 JSON（`code/status/data.title/data.content` 等） |
| `--format html` | 清洗后的 HTML（Jina `X-Return-Format: html`） |
| `--save FILE` | 写文件，不打印正文 |
| `--state` | 各出口 `remaining / cooldown_sec / available / successes / failures` |
| `--stop` | 停后台网关；下次请求自动拉起 |

环境变量 `JINA_GATEWAY_PORT` 覆盖端口，网关与客户端同步读取。

## HTTP 接口（仅监听回环）

基址 `http://127.0.0.1:<port>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | `{"ok":true}`，存活探测 |
| GET | `/state` | 出口状态 JSON |
| GET | `/<target-url>?format=md\|json\|html` | 抓取；URL 直接放 path |
| GET | `/?url=<encoded>&format=md` | 抓取；URL 放 query（更稳） |
| POST | `/` | body `{"url":"...","format":"md"}` |

- 成功 200；全部出口冷却时返回 429（客户端一般不会走到这，会在网关内等）。
- 响应 Content-Type：`text/markdown` / `application/json` / `text/html`（均 UTF-8）。
- 日志只记方法 + 状态码，不记 path/query。

## 配置 `config/endpoints.json`

```json
{
  "port": 8767,
  "endpoints": [
    {"name": "local",  "mode": "direct", "domain": "r.jinaai.cn"},
    {"name": "edge-a", "mode": "ssh",    "alias": "<YOUR_ALIAS_A>", "domain": "r.jinaai.cn"},
    {"name": "edge-b", "mode": "ssh",    "alias": "<YOUR_ALIAS_B>", "domain": "r.jina.ai"}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `name` | 出口标识，只用于状态显示/日志 |
| `mode` | `direct`=本机直连（清代理）；`ssh`=经主机别名在远端跑 curl |
| `domain` | Jina 端点域名；国内镜像与国际域名共享配额 |
| `alias` | `ssh` 模式必填，引用本机 SSH 配置里的别名 |

该文件被 `config/.gitignore` 排除。占位符 `<...>` 未替换时网关拒绝启动。

## 限流模型（事实）

- 匿名：`20 RPM`，按来源 IP 计；**无 token 池/总量上限**。
- 免费 key：500 RPM，但 1000 万 token 池会耗尽 → 长期高频不选。
- 国内镜像 `r.jinaai.cn` / `s.jinaai.cn` 为官方提供，接口与鉴权同国际域名。
- 换域名不增加配额，换出口 IP 才增加 → 多出口轮询的本质。
- 平均延迟官方标称 ~7.9s；简单页实测 0.1–8s 波动。
