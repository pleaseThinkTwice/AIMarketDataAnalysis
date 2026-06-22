# CLAUDE.md — 项目级 System Prompt

> 以下规则适用于本项目的所有对话，无需反复提醒。

## 核心规则

### 成本控制
- **默认用 DeepSeek-V3**，不要自动升级到更贵的模型
- 每次 LLM 调用记录 token 消耗，任务结束时汇报总成本
- Prompt 模板复用，避免每次都重新生成大段 system prompt
- 大文件读取用 offset/limit 分段，不要全量加载到上下文
- 不要重复读取已读过的文件（上下文中有就不要重新 Read）

### Git 自动化
- **每次任务完成或阶段性成果产出后，自动 commit + push**
- Commit message 用中文简述改动
- Push 到 origin master
- 示例：`feat: 添加 SQL 生成器` / `fix: 修复 schema 检索空值问题`
- 不要等我提醒才 push

### 代码风格
- 匹配已有代码风格（注释密度、命名习惯、中文/英文）
- 用 Pydantic v2 风格（`model_validate`、`Field(default_factory=...)`）
- 用 `from __future__ import annotations` 保持类型提示简洁
- `pathlib.Path` 优于 `os.path`

### 项目上下文
- 这是 NL2SQL + Self-Correction + Visualization 项目
- 技术栈：DeepSeek-V3、ChromaDB、bge-large-zh、LangGraph、PostgreSQL/SQLite
- 数据：Olist 电商数据集（12 张表，~110 万行）
- 测试：pytest，测试文件在 `tests/`
- 运行：`py -3.11 -m src.cli.analyze "查询"`
- 包安装：`py -3.11 -m pip install <package>`

### 对话风格
- 中文回复
- 先做再说，不要"让我先分析一下"
- 结果用表格展示
- 文件引用用 `[filename](path)` markdown 链接
- 不要用 "您"，用 "你"
