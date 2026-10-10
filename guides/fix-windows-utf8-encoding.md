# Windows 中文乱码修复：Claude Code 子进程 UTF-8 编码配置

## 问题

在 Windows 上使用 Claude Code 时，传递给 bash 子进程的中文字符变成乱码（如 `研究` → `оһ`、`论文` → `һҵ`），导致场景关键词匹配（scenario routing）、中文搜索、中文文件处理等功能全部失效。

**根因**：Windows 默认代码页是 CP936（GBK）或 CP437，而 Python/Node.js 等子进程从 C locale 继承编码，不是 UTF-8。`BASH_ENV` 脚本只在特定条件下加载，覆盖不全。

---

## 修复方案（共 3 个文件）

### 文件 1：`~/.claude/settings.json` ← **最核心，必须修改**

在 `env` 块中添加三个环境变量。Claude Code 会在每次启动子进程时注入它们，不依赖 shell 初始化流程：

```json
{
  "env": {
    "LANG": "en_US.UTF-8",
    "LC_ALL": "en_US.UTF-8",
    "PYTHONIOENCODING": "utf-8"
  }
}
```

**各变量作用**：
| 变量 | 影响范围 | 作用 |
|---|---|---|
| `LANG=en_US.UTF-8` | 所有 POSIX 兼容工具（git, grep, awk, sed, Node.js, Go, Rust 等） | 告诉 C 运行时库用 UTF-8 编解码 stdin/stdout/stderr |
| `LC_ALL=en_US.UTF-8` | 同上（优先级更高） | 强制覆盖所有 locale 分类为 UTF-8 |
| `PYTHONIOENCODING=utf-8` | 仅 Python | 显式告诉 Python 用 UTF-8 而非从 locale 推断 |

**覆盖范围**：Python、Node.js、Go、Rust、git、grep/sed/awk、bash 管道 —— 所有走 C locale 的工具。

---

### 文件 2：`~/.claude_init.sh` ← `BASH_ENV` 指向的脚本（冗余保险）

当 Claude Code 通过 `bash -c "..."` 启动子进程时，`BASH_ENV` 指向的脚本会被 source。添加同样的三行：

```bash
# ~/.claude_init.sh
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
chcp.com 65001 > /dev/null 2>&1
```

> `chcp 65001` 切换 Windows 控制台代码页，对原生 Windows 工具（findstr、cmd.exe 内建命令）有效。

---

### 文件 3：`~/.bashrc` ← 交互式 bash 的冗余保险

当 Git Bash 以交互模式启动时（如用户手动打开终端），`BASH_ENV` 不触发，但 `.bashrc` 会被 `.bash_profile` source。同样加三行：

```bash
# ~/.bashrc
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
chcp.com 65001 > /dev/null 2>&1
```

---

## 执行步骤（给 agent 用）

### 步骤 1：修改 `settings.json`

```bash
# 读取当前 settings.json
cat ~/.claude/settings.json
```

在 `"env"` 块中插入三个变量（如果已存在则跳过）。确保 `BASH_ENV` 指向正确的路径：

```json
"BASH_ENV": "C:\\Users\\VerNe\\.claude_init.sh",
"LANG": "en_US.UTF-8",
"LC_ALL": "en_US.UTF-8",
"PYTHONIOENCODING": "utf-8"
```

### 步骤 2：创建/更新 `.claude_init.sh`

```bash
cat > ~/.claude_init.sh << 'EOF'
# Claude Code bash init: ensure UTF-8 encoding throughout the toolchain
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
chcp.com 65001 > /dev/null 2>&1
EOF
```

### 步骤 3：更新 `.bashrc`

```bash
# 如果文件存在，检查是否已有这三行；如果不存在则创建
grep -q "LANG=en_US.UTF-8" ~/.bashrc 2>/dev/null || cat >> ~/.bashrc << 'EOF'

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
chcp.com 65001 > /dev/null 2>&1
EOF
```

### 验证

```bash
# 测试 Python 编码
echo '研究一下深度学习' | python -c "import sys; print(sys.stdin.encoding)"
# 应输出：utf-8

# 测试中文关键词匹配（模拟场景路由）
python -c "
text = '写一篇论文综述'
keywords = {'paper-review': ['论文', '综述', '文献']}
matched = [k for k, v in keywords.items() if any(kw in text for kw in v)]
print(f'matched: {matched[0] if matched else \"default\"}')"
# 应输出：matched: paper-review

# 测试 Node.js 编码
echo '研究' | node -e "process.stdin.on('data', d => console.log(d.toString().length))" 2>/dev/null || echo "node not available"
```

---

## OpenCode + Windows PowerShell 适配（2026-10 补充）

### 与 Claude Code 方案的差异

| 项 | Claude Code | OpenCode（Windows） |
|---|---|---|
| 环境变量注入 | `settings.json` 的 `env` 块，spawn 子进程时自动带上 | **无等价机制**。opencode.json 只有 `shell` / `model` / `agents` 等字段，没有 `env` |
| shell 工具 | 通常是 Git Bash | Windows 默认 `pwsh`，非交互模式：`BASH_ENV`、`.bashrc`、`$PROFILE` **都不加载** |
| 编码症状 | 中文关键词匹配失败 | 其实是三个不同的坑叠在一起（见下） |

### 实测会踩的三个坑（互相独立，别混淆）

**坑 1：`git status` 把中文路径显示成八进制转义**

```
 D "legacy_flask/\347\234\213\345\233\276.cmd"
```

`\347\234\213` 是 `截` 的 UTF-8 字节。这**不是乱码**，是 git 的 `core.quotepath` 默认 `true`，故意转义非 ASCII 字符。修复：

```powershell
git config --global core.quotepath false
```

**坑 2：pwsh 输出编码是 GBK（CP936）**

pwsh 的 `[Console]::OutputEncoding` 跟随控制台代码页，中文 Windows 默认为 936，于是所有非 ASCII 输出（含 PowerShell 自己的本地化错误信息）都变成 GBK 字节， Terminal 按 UTF-8 解码后显示为 `????`。每条命令加前缀：

```powershell
chcp.com 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
```

**坑 3：pwsh 不是 bash，bash 语法直接报错**

`ls -la .plan .glue 2>$null | head -40` 在 pwsh 下会报"无法将 head 识别为 cmdlet"（且报错信息本身还是 GBK，乱码套乱码）。`ls`/`-la`/`2>$null` 的语义也和 bash 不同。PowerShell 等价写法：

```powershell
ls -la .plan .glue 2>$null | head -40
# →
Get-ChildItem -Force -Path .plan, .glue -ErrorAction SilentlyContinue |
  Select-Object -First 40
```

### OpenCode 下的持久化修复（替代原方案的文件 1/2/3）

Claude 三件套（settings.json env / .claude_init.sh / .bashrc）在 OpenCode 下用不了，改为：

```powershell
# 1) locale 环境变量（用户级，对所有新进程生效）
setx LANG "en_US.UTF-8"
setx LC_ALL "en_US.UTF-8"
setx PYTHONIOENCODING "utf-8"

# 2) 新控制台默认 UTF-8 代码页：修复 pwsh 输出 GBK 的根
New-Item -Path 'HKCU:\Console' -Force | Out-Null
Set-ItemProperty -Path 'HKCU:\Console' -Name 'CodePage' -Value 65001 -Type DWord

# 3) git 中文路径直接显示
git config --global core.quotepath false
```

**关键**：OpenCode 是客户端–后台 service 架构，shell 工具由**后台 service** 派生。`setx` 只影响之后启动的进程，所以必须重启 service 才生效：

```
opencode service restart
```

（或完全退出重开 OpenCode。对已经启动的会话，上述注册表项对它已持有的控制台无效，靠每条命令的前缀兜底。）

### 验证（2026-10-10 于本机实测通过）

```powershell
"测试-中文-路径"        # 中文回写正常
git log --oneline -5    # 中文提交信息正常，无乱码
git status --short      # 中文文件名直接显示，无 \347 转义
```

---

## 原理：为什么这三个变量就够了

Windows 上的编码问题链路：

```
Claude Code 启动子进程
  └─ bash（或直接 spawn）
      └─ 子进程（python / node / git / ...）
           └─ C 运行时库决定 stdin/stdout 编码
              └─ 从 locale 获取 → 默认 CP936/GBK → 中文乱码
```

修复后的链路：

```
settings.json env 注入
  └─ LC_ALL=en_US.UTF-8 强制 C 运行时用 UTF-8
  └─ LANG=en_US.UTF-8    兜底 fallback
  └─ PYTHONIOENCODING=utf-8  Python 不走 locale，直接 UTF-8
```

`settings.json` 里的 `env` 块是 **Claude Code 原生支持的环境变量注入机制**，每次 spawn 子进程都会带上，**不依赖 .bashrc / .bash_profile / BASH_ENV 等任何 shell 初始化流程**。这是最可靠的一层。`BASH_ENV` 和 `.bashrc` 只是冗余保险，确保无论子进程以什么方式启动，UTF-8 都能生效。

---

## 注意事项

1. **需要重启 Claude Code 会话** 才能生效（settings.json 只在启动时读取）。
2. 如果使用代理/转发器，确保代理端也正确处理 UTF-8 编码。
3. 这三个变量只影响 **子进程的文本编码**，不影响 Claude Code 本身与 API 的通信。
4. 如果遇到 `LC_ALL: cannot change locale` 警告，可忽略或在系统中安装 `en_US.UTF-8` locale。Windows Git Bash 通常不报此警告。