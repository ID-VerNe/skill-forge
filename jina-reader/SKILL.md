---
name: jina-reader
version: 1.0.0
description: 通过本机 Jina Reader 匿名轮询网关抓取任意 URL（含 PDF），转 Markdown / JSON / HTML。网关按需自启——用户或 agent 只要发一次请求就自动开工，无需手动启动服务。当用户要求"用 jina 网关读这个链接""抓取网页内容""URL 转 markdown""匿名绕过 RPM 限制""读 PDF / X 推文 / 动态站"或明确说"只用网关拉取"时触发。所有网络拉取只经本地网关，不使用其他抓取工具。
---

# Jina Reader 网关

把 URL 转成 LLM 友好的 Markdown。匿名调用按 IP 限流 20 RPM、**无 token 池上限**；网关用多个独立出口轮询，约 60 RPM。

## 核心规则

### 1. 唯一入口

所有请求走 `scripts/jina.py`，**不要用 curl / WebFetch / 浏览器直接抓**：

```bash
python <skill-dir>/scripts/jina.py <URL> [--format md|json|html] [--save FILE]
```

- 用户说"只用网关/不用其他工具"时，这条是硬约束。
- `md`（默认）返回 `Title/URL Source/Markdown Content` 文本；`json` 返回结构化；`html` 返回清洗后的原始 HTML。
- 输出默认到 stdout；`--save FILE` 写到文件并把字节数打到 stderr。

### 2. 请求即开工（无需手动起服务）

`jina.py` 先探测网关 `/health`：
- 通则直接复用；
- 不通则后台拉起网关（pythonw + detached），轮询就绪（≤25s）后发请求。

所以**任何一次调用都可以是第一次**，不要多此一举先去启动服务。

```bash
python jina.py --state    # 看各出口剩余额度 / 冷却 / 累计成功失败
python jina.py --stop     # 停掉后台网关（下次请求会再拉起）
```

### 3. 出口配置（隐私）

- 实际配置在 `config/endpoints.json`，**已 gitignore**。内含出口类型（direct/ssh）、域名、主机别名。
- 仓库里只有 `config/endpoints.example.json`，全是占位符。
- 换机器时：复制 example → 填自己的别名 → 完成。别名从用户现有 SSH 配置取，不要让用户在对话里贴明文地址或凭据。
- 网关日志只记方法 + 状态码 + 出口名，**不记目标 URL**。

### 4. 限流与容错

- 每出口 20 RPM；429 或额度归零 → 该出口冷却 62s，自动切下一个。
- 全部冷却时网关内部等待（≤75s），不把 429 抛给调用方。
- 国内镜像与国际域名**共享同一 IP 配额**：换域名不增量，只有换出口 IP 才增量。
- 本机直连出口必须清代理 + `--noproxy '*'`，否则会与远端出口撞 IP。

## 常用示例

```bash
# 读网页
python jina.py "https://example.com"

# 结构化，存文件
python jina.py "https://example.com" --format json --save /tmp/page.json

# 读 PDF / X 推文 / 动态站（同样直接传 URL）
python jina.py "https://example.com/doc.pdf" --save ./doc.md

# 批量（串行，靠网关自己轮询）
for u in URL1 URL2 URL3; do python jina.py "$u" --save "./out/$(echo $u|md5sum|cut -c1-8).md"; done
```

## 排障

| 现象 | 处理 |
|---|---|
| `config not found` | 复制 `endpoints.example.json` → `endpoints.json` 并填别名 |
| `placeholder values left` | example 里的 `<...>` 没替换 |
| `gateway failed to boot` | 看 `config/gateway.log`；常见是端口被占或配置错 |
| 请求 429 / 全部冷却 | 正常限流，等一个窗口（≤60s）再试；`--state` 看剩余 |
| 某出口一直失败 | `--state` 看 failures；可临时在配置里删掉该出口 |
| 端口冲突 | 设 `JINA_GATEWAY_PORT=其他端口`，客户端与网关自动同步 |

详见 `references/api.md` 与 `references/troubleshooting.md`。

## 隐私红线

- 不把明文公网 IP、token、密钥、SSH 私钥内容写进任何文档/脚本/回复。
- 主机用别名引用；用户需要在外部配置的东西，给精确到字段的步骤，不代填敏感值。
- 日志、状态接口都不返回目标 URL 列表。
