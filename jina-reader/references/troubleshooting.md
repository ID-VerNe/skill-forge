# 排障手册

## 启动类

**`config not found`**
复制 `config/endpoints.example.json` → `config/endpoints.json`，按本机情况填。

**`placeholder values left in config`**
example 里的 `<...>` 没换。填真实主机别名（引用 SSH 配置），不要在对话里贴明文地址。

**`gateway failed to boot in 25s`**
看 `config/gateway.log`。常见：
- 端口被占 → `JINA_GATEWAY_PORT=8768` 或改配置 `port`。
- 配置字段缺失/占位符未填。
- 远端出口 ssh 别名在本机不可用（客户端会跳过失败出口，不至于启动失败）。

**后台网关 pts/会话结束就没了**
按需自启设计本来就不保证常驻：下次请求会重新拉起。若要真正的开机常驻，用系统计划任务调用：

```bash
python <skill-dir>/scripts/jina_gateway.py --serve
```

（这会让进程随登录启动；是否安装由用户决定，不要擅自注册。）

## 请求类

**429 / `all endpoints cooling down`**
所有出口都触发了 20 RPM 限流，网关内部等待最多 75s。用 `--state` 看：
- `cooldown_sec > 0` 表示还在冷却；
- 等一个 60s 窗口自然恢复。

**某出口 `failures` 持续增长**
`--state` 定位到具体出口 → 检查该出口的 ssh 连通性 / 域名可达性 → 临时从 `endpoints.json` 删掉它。

**结果里有登录墙（X / 需要登录的站）**
不是网关故障。匿名 Reader 抓未登录态公开内容；X 推文正文通常能拿到，但私密/登录后内容不行。

**`html` 格式返回体积很大**
正常。HTML 比 Markdown 大数倍；只要 Markdown 就别用 `--format html`。

## 隐私与编码

**日志会不会记我抓了什么？**
不会。`jina_gateway.py` 的 `log_message` 只记 HTTP 方法与状态码；状态接口只返回出口元数据，不含目标 URL 列表。

**Windows 中文乱码**
stdout 先设 UTF-8：`chcp 65001` 或环境变量 `PYTHONIOENCODING=utf-8`。`--save` 写文件不受影响（直接写 bytes）。

## 已知边界

- 匿名调用可能被目标站反爬挡（403/验证码），与限流无关；换个 URL 或等一会。
- 出口是动态 IP 时，重拨后 IP 变化不影响逻辑（Jina 按当前 IP 计数）。
- 网关无缓存：重复 URL 会真实消耗配额。需要缓存请在客户端做。
- 单请求最长 90s（网关侧 curl 超时）；大 PDF/超长页可能超时返回部分内容。
