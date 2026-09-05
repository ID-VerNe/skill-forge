---
name: license-add
version: 1.0.0
description: 把常见的开源许可证（MIT/Apache-2.0/GPL-3.0/LGPL-3.0/MPL-2.0/BSD-2-Clause/BSD-3-Clause/CC0-1.0）从本 skill 的 references/ 拷贝到目标项目，并用脚本自动替换 [year] [fullname] 等占位符。用户说"加 license"、"copy license"、"添加许可证"、"license 拷过来"、"这个项目要加 MIT" 时触发。默认复制到当前项目根目录的 LICENSE 文件。
---

# License Add

把常用开源许可证加到目标项目根目录。模板源文件内置在本 skill 的 `references/` 目录（来自 GitHub API licenses 接口的官方标准文本），不依赖网络，不依赖已装项目。

## 核心规则

### 1. 选哪个 license —— 按用户场景
默认偏好（无特殊要求时按此顺序建议）：

| key | 许可证 | 类型 | 一句话 |
|-----|--------|------|--------|
| `mit` | MIT | permissive | 个人项目默认，最简最短 |
| `apache-2.0` | Apache 2.0 | permissive | 含明确专利授权，大厂 / 需要专利保护时用 |
| `gpl-3.0` | GPL-3.0 | copyleft | 要求衍生作品同许可开源 |
| `lgpl-3.0` | LGPL-3.0 | weak copyleft | 库可以用在闭源项目里 |
| `mpl-2.0` | MPL-2.0 | weak copyleft | 文件级 copyleft，混合项目友好 |
| `bsd-2-clause` | BSD 2-Clause | permissive | 类 MIT，去掉"不可署名担保"措辞 |
| `bsd-3-clause` | BSD 3-Clause | permissive | BSD-2 加上"禁止背书"条款 |
| `cc0-1.0` | CC0 1.0 | public domain | 放弃版权，公共领域 |

- 用户指定就用指定的；没说就默认 MIT 并说明原因（最简单、最常见、无需额外义务）。
- GPL 系的 `lgpl-3.0`、`mpl-2.0`、`cc0-1.0` 是 GitHub API 的收窄版正文，不含 FSF/CC 官方的完整附注段落，标准做法下够用。

### 2. 占位符 —— 必须替换
以下模板里带占位符，copy 后**必须**替换，不许原样留着：

| 许可证 | 占位符 | 位置 |
|--------|--------|------|
| `mit` | `[year] [fullname]` | 第 3 行版权行 |
| `bsd-2-clause` | `[year], [fullname]` | 第 3 行版权行 |
| `bsd-3-clause` | `[year], [fullname]` | 第 3 行版权行 |
| `apache-2.0` | `[yyyy] [name of copyright owner]` | 仅附录（正文无占位符） |
| `gpl-3.0` | `<year>  <name of author>` | 仅 HOW TO APPLY 附注（正文无占位符） |
| `lgpl-3.0` / `mpl-2.0` / `cc0-1.0` | 无 | 正文无版权行，无需替换 |

- **year**：默认当前年份（如 2026）。用户给了年份（或版权起始年份如 "2024-2026"）就用用户的。
- **fullname**：默认优先用 git 全局配置 `git config user.name`，取不到再问用户。用户给了就用用户的。
- **apache-2.0 附录**：`[yyyy] [name of copyright owner]` 在 `APPENDIX: How to apply the Apache License to your work.` 段的示例里，可替换可保留（这是给"如何附加声明"的示例，不是必须改的正文）。默认不动，除非用户要求。
- **gpl-3.0 附录**：`<year>  <name of author>` 同理，是 HOW TO APPLY 示例，默认不动。

### 3. 拷贝位置与文件名
- 默认目标：当前工作目录根下的 `LICENSE`。
- 用户指定目录就用指定目录（先确认存在，不存在则创建）。
- 文件名默认 `LICENSE`；用户可指定 `LICENSE.txt` / `COPYING` / `LICENSE.md` 等。
- 目标已存在 `LICENSE` 时：先读出来给用户看是什么，**确认覆盖才写**，不许静默覆盖。

## 工作流

1. **确认参数**：license key（默认 mit）、目标目录（默认当前目录）、year（默认当前年）、fullname（默认 git user.name）、文件名（默认 LICENSE）。
   - 缺哪个问哪个；用户在原始请求里已给的不要重复问。
2. **执行**：运行
   ```bash
   python "C:\Users\VerNe\Downloads\Documents\skill-forge\license-add\scripts\add-license.py" \
     --license mit --dir "<目标目录>" \
     --year 2026 --name "ID-VerNe" [--filename LICENSE] [--dry-run]
   ```
   - 用 `--dry-run` 先预览将要写的内容（脚本打印替换后的文本且不落盘）。
   - 脚本内部从 `scripts/../references/` 定位模板，不依赖当前目录。
3. **验证**：写完后读目标文件确认：
   - 内容是所选许可证正文；
   - 版权行占位符已替换为真实 year/fullname（适用于有占位符的许可证）；
   - 行尾是 LF（脚本统一输出 LF，Windows 下不要让它变 CRLF）。
4. **报告**：告知用户写到了哪个文件、哪个许可证、版权行内容。**不要**修改目标项目里的其它文件（比如不要顺手改 README 或加 CITATION.cff，除非用户要求）。

## 环境要求

- `python`（用户环境已全局可用；任意 Python 3 亦可，仅标准库、无第三方依赖）。

## 常见问题

- **用户没给 fullname**：先试 `git config user.name`（在目标目录里跑）。拿不到就问："版权行写谁的名字？"
- **目标目录不存在**：创建（脚本 `os.makedirs`）。
- **想把 license 加进仓库再提交**：本 skill 只负责拷贝文件，commit 交给 `commit-message-writing` skill。
