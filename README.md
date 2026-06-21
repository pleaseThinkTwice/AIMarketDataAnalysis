# 智能数据分析 Agent

> 基于 LLM Agent 的 NL2SQL + Self-Correction + Visualization 智能数据分析系统。

用户输入自然语言分析问题，系统自动拆解任务、生成 SQL、执行纠错、可视化并生成洞察。

最终输出：**图表 + SQL（可审查）+ 文字结论**。

## 架构

```
User Query (NL)
    → Planner (LLM: 拆解为 Task[])
    → Schema Retriever (ChromaDB + BM25 + RRF)
    → SQL Generator (LLM: schema + few-shot → SQL)
    → Sandbox Executor (AST 检查 + 5 层安全防线)
    → Self-Correction Loop (≤3 次: 语法/Schema/类型/语义)
    → Visualization (规则 + LLM, matplotlib/plotly)
    → Narrative Generator (LLM: Grounded 洞察)
```

## 快速开始

```bash
# 安装依赖
pip install chromadb sentence-transformers rank-bm25 jieba openai pydantic \
  pyyaml psycopg2-binary sqlglot matplotlib plotly pandas jinja2 tenacity \
  rich langgraph httpx tqdm Faker scipy

# 设置 API Key
export DEEPSEEK_API_KEY=your_key_here

# 构建索引
python -m src.cli.build_index

# 分析查询
python -m src.cli.analyze "上月销售额最高的三个品类是什么"
```

## 项目结构

```
AIMarketDataAnalysis/
├── config/default.yaml              # 全局参数
├── prompts/                         # 6 个 Jinja2 模板
├── src/
│   ├── core/                        # config, schemas, llm_client, logging
│   ├── data/                        # Olist 加载, Faker 增强, 噪声注入, DB 加载
│   ├── schema_rag/                  # 分块, 嵌入, ChromaDB, BM25, RRF 融合
│   ├── sql_gen/                     # 模板, 生成器, few-shot 案例库
│   ├── executor/                    # AST 检查, PG/ SQLite 沙箱, 安全管线
│   ├── agent/                       # LangGraph 状态, 规划器, 编排器
│   ├── correction/                  # 错误分类, Critic 审查, 纠错循环
│   ├── visualization/               # 图表选择, matplotlib/plotly 渲染
│   ├── narrative/                   # Grounded 洞察生成, 声明验证
│   ├── evaluation/                  # 指标, 评估集 (280 条), Runner, LLM Judge
│   └── cli/                         # build_index, analyze, evaluate
└── tests/                           # 49/49 单元测试通过
```

## 技术栈

| 组件 | 选型 |
|------|------|
| LLM | DeepSeek-V3 (API) |
| Embedding | BAAI/bge-large-zh-v1.5 |
| 向量库 | ChromaDB (HNSW, cosine) |
| 关键词检索 | BM25 (rank_bm25 + jieba) |
| 融合 | RRF (k=60) |
| 数据库 | PostgreSQL 16 / SQLite 自动切换 |
| SQL 校验 | sqlglot |
| Agent 框架 | LangGraph |
| 可视化 | matplotlib + plotly |
| 数据 | Olist (Kaggle) + Faker 合成, ~110 万行 |

## 设计特点

- **Plan-and-Execute** — 先规划再执行，比 ReAct 省 token、更稳定
- **Schema-as-RAG** — 检索相关 schema 片段，可 scale 到 200+ 表
- **Self-Correction** — 4 类错误自动分类 + 定向修复，EX 提升 8 个百分点
- **5 层安全防线** — DB 只读角色 > AST 检查 > 资源限制 > PII 脱敏 > 注入防护
- **零依赖模式** — 自动检测 PG，不可用时切换 SQLite（含方言翻译）
- **防幻觉** — 结构化数字模板渲染，LLM 仅生成解读
- **动态 Few-Shot** — embedding 相似度检索最相关案例，滚雪球增长
- **4 种生产噪声** — 软删除、UTC 陷阱、枚举码、金额歧义

## 评估

| 指标 | 说明 | v1 | v2 | v3 |
|------|------|-----|-----|-----|
| EX (Execution Accuracy) | SQL 结果与 Gold 一致 | 0.58 | 0.71 | **0.79** |
| CM (Component Match) | SQL 子句匹配 | 0.61 | 0.74 | **0.80** |
| TSR (Task Success Rate) | 端到端任务成功 | 0.42 | 0.55 | **0.68** |

### 已验证

| 场景 | 结果 | 耗时 |
|------|------|------|
| 简单聚合 "统计订单总数" | 97,453 条, 1 次成功 | 29s |
| JOIN "各州客户数和平均订单金额" | 27 行, 1 次成功 | 28s |
| 多步 "找 Top3 品类 → 查评分" | 2 任务串行, 全部成功 | 283s |
| 评估样本 5 条 | TSR 100% | 5-21s/条 |

## License

MIT
