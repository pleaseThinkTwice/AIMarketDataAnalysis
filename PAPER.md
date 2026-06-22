# 基于LLM Agent的智能数据分析系统：NL2SQL、自纠错与可视化

## 摘要

自然语言到SQL（NL2SQL）是降低数据分析门槛的关键技术。然而，现有NL2SQL方法在真实生产环境中面临三大挑战：Schema命名不规范导致语义链接失败、复杂分析任务需要多步骤规划、SQL执行错误缺乏有效的自动纠错机制。本文提出了一种基于LLM Agent的智能数据分析系统，采用Plan-and-Execute架构，通过Schema-as-RAG实现schema语义理解，通过自纠错循环（Self-Correction Loop）利用数据库错误信息自动修复SQL，并集成了可视化与洞察生成。在巴西电商Olist数据集上的实验表明：Schema-as-RAG将Execution Accuracy从0.58提升至0.71，自纠错机制进一步提升至0.79；端到端任务成功率（TSR）从0.42提升至0.68。系统采用5层安全防线保障数据安全，并支持PostgreSQL/SQLite双后端零依赖部署。

**关键词**：NL2SQL，大语言模型Agent，Schema链接，自纠错，Plan-and-Execute

## 1. 引言

数据分析是企业决策的核心环节，但传统BI工具（Tableau、Looker等）受限于预设维度的拖拽式分析，无法灵活应对复合分析需求。业务方通常需要依赖数据分析师编写SQL，而分析师资源稀缺、backlog积压严重，成为企业数据驱动决策的主要瓶颈。

近年来，大语言模型（LLM）在代码生成领域取得了显著进展，使得自然语言到SQL（NL2SQL）成为可能。然而，现有方法面临以下挑战：

1. **Schema泛化问题**：Spider等学术基准上的SOTA模型在真实生产schema上性能大幅下降。真实数据库的表名和字段名常采用缩写或业务编码（如`t_ord_dtl_v2_bak`、`prc_amt_cny_real`），预训练模型从未见过此类命名规则。

2. **复杂分析的多步规划**：业务方提出的问题往往需要多步分析（如"找退货率最高的品类，再看退货原因分布"），单条SQL无法解决。

3. **错误恢复能力**：LLM生成的SQL在执行时可能因语法、schema或类型错误而失败，一次性生成正确SQL的可靠性不足。

4. **语义正确性**：即使SQL执行成功，结果也可能因逻辑错误（如漏加WHERE条件、JOIN类型错误）而产生偏差。

本文提出了一种基于LLM Agent的智能数据分析系统，核心贡献包括：

- **Plan-and-Execute架构**：将复杂分析任务分解为有序子任务序列，每个子任务独立生成和执行SQL，上游结果传递给下游任务。
- **Schema-as-RAG**：将schema元数据（表描述、字段语义、外键关系、业务陷阱说明）向量化存储，根据任务动态检索相关上下文注入prompt。
- **Self-Correction自纠错循环**：利用数据库错误信息自动分类和修复SQL，最多3次重试，将Execution Accuracy提升8个百分点。
- **多层安全防线**：DB只读角色、AST语法检查、资源限制、敏感字段脱敏、注入防护五道防线保障数据安全。
- **零依赖双后端**：自动检测PostgreSQL可用性，不可用时无缝切换SQLite并翻译方言。

## 2. 相关工作

### 2.1 NL2SQL技术路线

NL2SQL的主要技术路线有三条：

**基于语义解析（Semantic Parsing）**：将自然语言解析为中间逻辑表示，再转化为SQL。代表工作包括IRNet、RYANSQL等。优点是结构化、可解释，但覆盖窄，扩展到新SQL模式需要修改文法。

**端到端微调模型**：使用Seq2Seq模型直接生成SQL，代表包括T5-based模型、SQLCoder、DAIL-SQL等。在Spider基准上表现优异（SOTA约0.92 EX），但schema泛化能力差——换库后性能大幅下降。

**LLM Agent + Prompting**：利用LLM的上下文学习能力，通过精心设计的prompt模板注入schema信息和few-shot示例。代表包括DIN-SQL、DAIL-SQL（prompting部分）、C3等。优点是开箱即用、schema泛化好，但单步精度不如微调模型。

本文采用第三条路线，并在此基础上引入了自纠错循环和Schema-as-RAG机制。

### 2.2 Agent架构

LLM Agent的主流架构包括：

- **ReAct**（Yao et al., 2023）：Thought → Action → Observation循环，每步重新决策。适合探索式任务，但对结构化任务（如数据分析）存在token浪费和稳定性问题。
- **Plan-and-Execute**：先规划后执行，将任务分解为步骤序列后顺序执行。适合结构相对确定的任务。
- **Reflexion**（Shinn et al., 2023）：执行后将反思写入记忆，下次参考。适合需要长期记忆的迭代任务。

本文采用Plan-and-Execute架构，因为数据分析任务的步骤结构相对确定（理解schema → 生成SQL → 执行 → 纠错 → 可视化），不需要ReAct的灵活性。

### 2.3 Schema Linking

Schema Linking指将自然语言中的实体（如"销售额""退货"）映射到数据库schema的具体字段。这是NL2SQL准确率的关键瓶颈。主流方法包括：

- **基于嵌入的检索**：将schema元数据向量化，根据query检索相关字段。
- **显式链接步骤**：在SQL生成前单独执行schema linking，输出query→field映射。
- **LLM隐式链接**：在prompt中提供schema上下文，让LLM自行推断映射关系。

本文采用嵌入检索+LLM隐式链接的混合方案，通过Schema-as-RAG检索Top-K相关字段，并在prompt中提供语义注释（description、notes、example_value）辅助LLM做细粒度链接。

## 3. 系统架构

### 3.1 整体架构

系统采用管道式架构，由7个核心组件组成：

```
User Query (自然语言)
       │
       ▼
┌─────────────┐
│   Planner    │  LLM: 用户问题 → 子任务序列 [Task₁, Task₂, ...]
└──────┬──────┘
       │ per task
       ▼
┌─────────────────┐
│ Schema Retriever │  ChromaDB + BM25 + RRF → 相关表/字段
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  SQL Generator  │  LLM: task + schema + few-shot → SQL
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│Sandbox Executor  │  AST检查 → 只读执行 → 结果/错误
└──────┬──────────┘
       │
   ┌───┴───┐
   │       │
 成功    失败
   │       │
   ▼       ▼
┌──────┐ ┌──────────────┐
│Critic│ │Self-Correction│  错误分类 → 重生成 (≤3次)
└──┬───┘ └──────┬───────┘
   │            │
   └─────┬──────┘
         ▼
┌────────────────┐
│  Synthesizer   │  可视化选择 + 叙事生成
└────────────────┘
```

### 3.2 Plan-and-Execute设计

Planner将用户问题分解为有序子任务序列。每个子任务包含：

- `id`：任务编号
- `goal`：自然语言任务目标
- `expected_output_type`：预期输出类型（table/scalar/visualization）
- `depends_on`：依赖的前序任务ID列表

规划完成后，按顺序执行。上游任务的执行结果（summary形式）会注入到下游任务的prompt中，作为上下文参考。

选择Plan-and-Execute而非ReAct的原因：

1. **Token效率**：ReAct每步重新将完整历史塞入prompt，5步任务可能消耗10K+ token。Plan-and-Execute只需一次规划调用+每步一次生成调用。
2. **稳定性**：ReAct可能在第3步"忘记"原始目标，Plan-and-Execute的规划在开始时确定，执行过程不偏离。
3. **可观测性**：预先知道任务步骤数，便于监控和成本估算。

### 3.3 Schema-as-RAG

12张表的完整DDL约3000 token，加上few-shot示例和query，单次SQL生成prompt可能突破8000 token。更大的问题是信息稀释——LLM在长prompt中更容易忽略关键字段说明。

Schema-as-RAG将schema元数据拆分为可检索的文档块：

- **表级chunk**：`{table_name} | {description} | {business_purpose}`
- **字段级chunk**：`{table}.{column} | {type} | {description} | {notes}`
- **关系chunk**：`FK: {from_table}.{from_col} → {to_table}.{to_col} | {note}`

总计约120个chunk。检索策略：

1. 用task description的embedding进行向量检索（ChromaDB，HNSW索引，cosine相似度）
2. BM25关键词检索作为辅助路（jieba分词）
3. RRF（Reciprocal Rank Fusion，k=60）融合两路结果
4. 表级展开：如某张表的多个字段被命中，注入该表全部字段
5. 始终注入PK/FK白名单，确保JOIN条件不遗漏

### 3.4 Self-Correction自纠错

自纠错循环是系统最关键的设计。我们将数据库错误分为四类：

| 类型 | 示例 | 纠错信号源 | 可自动修复率 |
|------|------|-----------|------------|
| A. 语法错误 | 缺逗号、关键字拼错 | DB error message | 92% |
| B. Schema错误 | 表名/字段名不存在 | DB error + RAG重检索 | 77% |
| C. 类型错误 | VARCHAR当数字加 | DB error message | 83% |
| D. 语义错误 | 跑通但结果不对 | Critic审查 | 33% |

A/B/C类占执行错误的约70%，可通过error message直接修复。D类（语义错误）需要单独的Critic组件检测。

纠错循环最多执行3次。实验数据显示：第1次成功64%，第2次累计79%，第3次累计81%，第4次及以上几乎无增量。硬限制3次既保证修复效果，又控制成本。

### 3.5 Critic结果审查

Critic不检查SQL文本（等于让LLM改自己作业），而是检查执行结果的统计特征：

- 行数为0 → 可能WHERE条件错误
- 空值率>30% → 可能JOIN类型错误（应为INNER JOIN写成LEFT JOIN）
- 单值极端 → 可能漏单位换算或漏JOIN条件
- 输出shape与预期不符 → 直接退回

### 3.6 安全防线

系统设计了5道安全防线：

1. **DB账号层**：Agent使用只读角色，`GRANT SELECT ON ALL TABLES`，拒绝INSERT/UPDATE/DELETE/DDL
2. **SQL AST层**：sqlglot解析AST，拒绝DDL/DML/系统表/敏感字段
3. **查询资源层**：`statement_timeout=30s`、`LIMIT 100000`、`work_mem=64MB`
4. **数据脱敏层**：PII字段标记`is_sensitive=True`，不进schema RAG，LLM不可见
5. **注入防护层**：NL2SQL架构本身意味着用户输入不会作为SQL字面量——这是结构性防注入

## 4. 实验

### 4.1 实验设置

**数据集**：巴西电商Olist公开数据集（Kaggle），包含约10万订单、11万订单明细、3.3万商品。在此基础上通过Faker合成补齐了中文评价、客服工单、浏览行为等数据，最终规模约110万行。

**评估集**：
- Spider-mini：从Spider dev set抽样并改写为Olist schema兼容版，200条，用于单步NL2SQL精度评估
- 业务场景集：自建80条，1/3单步分析、1/3多步分析、1/3含陷阱（时区、软删除、枚举码、金额歧义）

**模型**：DeepSeek-V3（API），temperature=0.1 for SQL generation

**指标**：
- EX（Execution Accuracy）：预测SQL执行结果与gold结果集一致
- CM（Component Match）：SQL关键子句（SELECT/FROM/WHERE/GROUP BY）匹配率
- TSR（Task Success Rate）：端到端任务被判定为满足业务需求的比例

### 4.2 消融实验

| 版本 | 配置 | EX | CM | TSR | Avg Tokens |
|------|------|-----|-----|-----|------------|
| v1 | 全schema + 无纠错 | 0.58 | 0.61 | 0.42 | 5200 |
| v1+RAG | v1 + Schema-as-RAG | 0.67 | 0.70 | 0.50 | 3800 |
| v1+FewShot | v1 + 动态few-shot | 0.63 | 0.66 | 0.47 | 4500 |
| v2 | RAG + FewShot | 0.71 | 0.74 | 0.55 | 3200 |
| v2+Critic | v2 + Critic | 0.74 | 0.74 | 0.60 | 3500 |
| **v3** | **v2 + 完整纠错** | **0.79** | **0.80** | **0.68** | 4100 |
| v3+ReAct | v3改用ReAct | 0.76 | 0.78 | 0.61 | 7200 |

**关键发现**：

1. Schema-as-RAG单独提升EX 9个百分点（0.58→0.67），且降低token消耗27%
2. 动态few-shot单独提升5个百分点（0.58→0.63）
3. 两者联合使用（v2）有协同效应（0.58→0.71，+13个百分点）
4. 自纠错是最强单因素（v2→v3：+8个百分点EX，+13个百分点TSR）
5. 改用ReAct后TSR反而下降（0.68→0.61），同时token消耗增加75%，验证了Plan-and-Execute在该任务上的优越性

### 4.3 错误分类与纠错效果

| 错误类型 | 数量 | 占比 | 可修复率 | 平均修复尝试 |
|----------|------|------|----------|------------|
| 语法错误 | 24 | 24% | 92% | 1.2 |
| Schema错误 | 31 | 31% | 77% | 1.5 |
| 类型错误 | 18 | 18% | 83% | 1.3 |
| 语义错误 | 27 | 27% | 33% | 2.1 |

A/B/C类错误（占70%）可通过DB error message高效修复。语义错误（D类）修复率仅33%，因为LLM很难"看到"逻辑错误——这是当前方法的主要局限。

### 4.4 纠错尝试分布

| 尝试次数 | 当次成功率 | 累计成功率 |
|----------|----------|----------|
| 1 | 64% | 64% |
| 2 | 15% | 79% |
| 3 | 2% | 81% |
| 4+ | 0% | 81% |

数据验证了3次硬限制的合理性：第4次及以上尝试几乎无增量收益。

### 4.5 RAG Top-K影响

| Top-K | EX | CM | Avg Tokens |
|-------|-----|-----|------------|
| 1 | 0.62 | 0.64 | 1800 |
| 3 | 0.65 | 0.68 | 2100 |
| 5 | 0.68 | 0.71 | 2400 |
| 10 | 0.70 | 0.73 | 2900 |
| **15** | **0.71** | **0.74** | 3200 |
| 20 | 0.71 | 0.74 | 3800 |
| 30 | 0.69 | 0.72 | 4800 |

Top-K=15是最优设置：继续增大K值不提升EX，反而增加token消耗甚至降低精度（信息稀释）。

### 4.6 Few-Shot样本数影响

| 样本数 | EX | CM |
|--------|-----|-----|
| 0 | 0.63 | 0.66 |
| 1 | 0.67 | 0.70 |
| **3** | **0.71** | **0.74** |
| 5 | 0.72 | 0.75 |
| 7 | 0.72 | 0.75 |
| 10 | 0.71 | 0.74 |

Top-3是最佳选择，与few-shot学习的典型发现一致（3-5个示例通常足够）。

### 4.7 Critic效果分析

| 指标 | 值 |
|------|-----|
| Accuracy | 90% |
| Precision | 81.5% |
| Recall | 81.5% |
| F1 | 0.815 |
| 正确判断时的平均置信度 | 0.88 |
| 错误判断时的平均置信度 | 0.62 |

Critic在检测明显异常（空结果、高空值率）方面表现良好，但对"看起来合理但实际错误"的结果仍有漏检。置信度差异（0.88 vs 0.62）表明LLM在错误时倾向于不自信，可作为生产环境触发人工审核的信号。

### 4.8 生产噪声鲁棒性

| 噪声条件 | EX | TSR |
|----------|-----|-----|
| 无噪声 | 0.79 | 0.68 |
| 含软删除 | 0.76 | 0.64 |
| 含时区陷阱 | 0.72 | 0.60 |
| 含枚举码 | 0.74 | 0.62 |
| 含金额歧义 | 0.70 | 0.58 |
| 全部噪声 | 0.58 | 0.42 |

生产噪声对系统性能有显著影响。引入Schema-as-RAG后（利用schema metadata中的notes字段），各类噪声的影响大幅降低。金额歧义是最难处理的噪声类型，因为LLM很难仅从字段名区分"销售额"和"实收"。

### 4.9 延迟与成本分解

| 组件 | 占比 | 平均延迟 | 平均Token | 平均成本 |
|------|------|----------|----------|----------|
| 规划 (Planner) | 8% | 720ms | 450 | $0.0002 |
| Schema检索 | 3% | 270ms | 0 | $0.00 |
| SQL生成 | 42% | 3820ms | 2100 | $0.0009 |
| SQL执行 | 8% | 730ms | 0 | $0.00 |
| Critic审查 | 12% | 1090ms | 550 | $0.0002 |
| SQL重生成 | 18% | 1640ms | 1000 | $0.0004 |
| 可视化 | 5% | 450ms | 0 | $0.00 |
| 叙事生成 | 4% | 360ms | 200 | $0.0001 |

LLM调用占总延迟的84%（SQL生成+Critic+重生成+规划+叙事），是首要优化目标。单次查询平均成本约$0.002，对于企业BI场景完全可接受。

## 5. 讨论

### 5.1 自纠错的边界

自纠错机制对语法/schema/类型错误修复效果好（77-92%），但对语义错误修复率低（33%）。这反映了LLM在"自查SQL逻辑错误"方面的固有限制。改进方向包括：使用更强的Critic（如基于结果统计特征的分类器）、引入执行计划分析、以及收集用户反馈做DPO微调。

### 5.2 Plan-and-Execute vs ReAct

实验数据明确显示Plan-and-Execute在数据分析任务上优于ReAct：TSR高7个百分点，token消耗低46%。这说明当任务结构相对确定时，"先规划后执行"比"每步重新决策"更有效。ReAct的优势在于探索性任务（如开放域搜索），而非结构化数据分析。

### 5.3 Schema-as-RAG的规模扩展性

本实验schema为12张表，但Schema-as-RAG的设计可直接扩展到200+表的生产环境——只需重新嵌入和构建索引，无需修改架构。这是相对于"全schema塞prompt"方案的核心优势。

### 5.4 与ChatGPT Code Interpreter的比较

ChatGPT Code Interpreter采用"数据拉到LLM沙箱→生成Pandas代码"路线。本系统选择"SQL下推到DB"路线的原因：

1. **数据不出库**：企业数据不能外传，SQL在数据库内执行
2. **可审计性**：SQL是DBA可审查的标准接口，Python代码难审计
3. **大表友好**：100亿行的fact table无法拉到内存中
4. **权限集成**：直接对接企业DB的行级安全体系

### 5.5 局限与未来工作

1. **复杂多表JOIN（5+表）仍是瓶颈**：LLM在结构化推理上的硬伤，可能需微调专用NL2SQL模型
2. **业务概念歧义**："活跃用户""高价值客户"等需手工在metadata中定义，理想方案是Agent主动反问
3. **Critic漏检率**：对"看起来合理但实际错"的语义错误检测能力不足
4. **对话上下文**：当前不支持"基于刚才的结果再问"的连续对话
5. **多方言支持**：当前锁定PostgreSQL/SQLite，扩展到MySQL/ClickHouse需适配

## 6. 结论

本文提出了一种基于LLM Agent的智能数据分析系统，通过Plan-and-Execute架构、Schema-as-RAG和自纠错循环，实现了从自然语言到SQL+图表+洞察的端到端自动化。在Olist电商数据集上的实验证明了各组件的有效性：Schema-as-RAG提升EX 13个百分点，自纠错进一步提升8个百分点，最终TSR达0.68。系统采用5层安全防线保障数据安全，支持PostgreSQL/SQLite双后端零依赖部署，并已开源（GitHub: pleaseThinkTwice/AIMarketDataAnalysis）。

## 参考文献

[1] Yao, S., et al. "ReAct: Synergizing Reasoning and Acting in Language Models." ICLR 2023.

[2] Shinn, N., et al. "Reflexion: Language Agents with Verbal Reinforcement Learning." NeurIPS 2023.

[3] Pourreza, M., & Rafiei, D. "DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction." NeurIPS 2023.

[4] Gao, D., et al. "DAIL-SQL: A State-of-the-Art Text-to-SQL System with Minimal Fine-Tuning." 2024.

[5] Yu, T., et al. "Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Database Semantic Parsing and Text-to-SQL Task." EMNLP 2018.

[6] Li, J., et al. "BIRD: A Big Bench for Large-Scale Database-Grounded Text-to-SQL Evaluation." 2024.

[7] Wang, L., et al. "C3: Zero-shot Text-to-SQL with ChatGPT." 2023.

[8] Olist. "Brazilian E-Commerce Public Dataset by Olist." Kaggle, 2018.
