# common

共享基础设施层，为所有其他模块提供通用工具函数。包括缓存、Schema 定义、Git 操作、平台检测和报告生成。

## Responsibilities

- 提供统一的输出 Schema（`polyglot-output-v1`），确保所有后端返回可预测的 JSON 格式
- 24h TTL 磁盘缓存，减少对外部 API 的重复请求
- 浅克隆 Git 仓库和语言检测工具
- 操作系统/包管理器检测
- JSON → Markdown 报告转换

## Key Concepts

### Unified Output Schema

所有后端（scout/auditor/probe）返回统一格式的 JSON，包含 `schema`、`tool`、`language`、`results`、`errors` 和 `metadata` 字段，确保跨语言结果可预测。

Reference: [[polyglot/common/schema.py#SearchOutput]]

### 24h TTL 缓存

基于 MD5 哈希的磁盘缓存，默认 TTL 86400 秒（24h）。缓存键为请求参数哈希，自动过期自动清理。

Reference: [[polyglot/common/cache.py#cache_get]]

### 综合质量评分

`compute_score` 函数根据 stars、下载量、最近提交天数计算 0.0-1.0 综合质量分数。权重：stars 0.4、下载量 0.3、活跃度 0.3。

Reference: [[polyglot/common/schema.py#compute_score]]

### 报告转换

`search_to_md` / `audit_to_md` / `probe_to_md` 将统一格式的 JSON 输出转换为可读的 Markdown 报告。`output_from_file` 从 JSON 文件自动检测工具类型并反序列化。

Reference: [[polyglot/common/reporters.py]]

## Dependencies

- `reporters` 模块依赖 `common.schema`（内部依赖）

## Consumed By

- [[polyglot-router]] — 通过 reporters 生成 Markdown 输出
- [[backends]] — 各语言后端使用 schema 定义输出格式

## Data Structures

### SearchOutput
```python
@dataclass
class SearchOutput:
    schema: str = "polyglot-output-v1"
    tool: str = "scout"
    language: str = ""
    query: str = ""
    results: list[SearchResult]  # name, version, description, registry_url, stars, downloads, last_commit, license_name, dependencies, score
    errors: list[str]
    metadata: dict  # duration_ms, cache_hit, has_more
    timestamp: str  # ISO 格式时间戳
```

### AuditOutput / AuditData
```python
@dataclass
class AuditOutput:
    schema: str = "polyglot-output-v1"
    tool: str = "auditor"
    language: str = ""
    candidate_name: str = ""
    repo_url: str = ""
    timestamp: str = ""
    data: AuditData
    errors: list[str]
    metadata: dict

@dataclass
class AuditData:
    files_scanned: int = 0
    files_skipped: int = 0
    exports: list[ExportSymbol]  # name, kind, signature, source, probed, doc_available
    keywords_found: list[str]
    test_ratio: float = 0.0
    complexity: str  # low|medium|high
    community_health: CommunityHealth  # stars, last_commit_days_ago, open_issues, has_readme, has_tests, has_docs
    security: SecurityInfo  # vulnerabilities, score
    verdict: str
```

## Configuration

- `CACHE_DIR` — 默认 `polyglot/.cache/`（相对于 `polyglot/common/cache.py` 的 `../.cache` 路径）