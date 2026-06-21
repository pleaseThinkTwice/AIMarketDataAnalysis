# 智能数据分析 Agent ｜ 项目细节与面试预判

> 本文档为简历项目"基于 LLM Agent 的智能数据分析系统（NL2SQL + 自纠错 + 可视化）"的技术细节、设计权衡与高频面试问题预案。组织逻辑与 RAG 电影项目文档保持一致：**先讲清楚是什么 / 怎么做 / 为什么这么做，再针对每个环节给出可能的深挖问题与答法**。

---

## 目录

1. [项目定位与背景](#一项目定位与背景)
2. [整体架构](#二整体架构)
3. [数据层](#三数据层)
4. [Agent 架构选型：Plan-and-Execute](#四agent-架构选型plan-and-execute)
5. [Schema Understanding：Schema-as-RAG](#五schema-understandingschema-as-rag)
6. [SQL 生成层](#六sql-生成层)
7. [Self-Correction 机制](#七self-correction-机制)
8. [可视化与洞察生成](#八可视化与洞察生成)
9. [安全约束](#九安全约束)
10. [评估体系](#十评估体系)
11. [关键设计决策与权衡](#十一关键设计决策与权衡)
12. [局限与改进方向](#十二局限与改进方向)
13. [高频深挖问题与回答](#十三高频深挖问题与回答)

---

## 一、项目定位与背景

### 1.1 为什么做这个项目

业务方面对 BI 工具有三类痛点：

- **拖拽 BI（Tableau / Looker / 帆软）只能做预设维度切片**，"上季度退货率最高的三个 SKU 的退货原因分布"这种复合分析必须靠数据分析师写 SQL。
- **写 SQL 门槛高**：业务方不会写、分析师写不完——典型公司一个分析师 backlog 几十张报表。
- **传统 NL2SQL 方案**（Text2SQL 微调模型如 SQLCoder、Spider 上 SOTA 模型）一旦上到真实生产 schema 就崩——真实库的表名是 `t_ord_dtl_v2_bak`、字段是 `prc_amt_cny_real`，预训练阶段没见过的命名规则。

LLM Agent 范式对应解决：

- **Schema-aware prompting**：用注释/RAG 让 LLM 理解 schema 语义，避开预训练分布偏差。
- **Self-correction loop**：SQL 跑错了能看到 error message 自己修，不靠"一发入魂"。
- **多步规划**：复杂分析（"找异常 → 钻取原因 → 对比时序"）可以拆解为多 SQL + 中间结果传递。
- **可解释**：每一步生成的 SQL 都可审查，比纯端到端模型透明。

### 1.2 和 RAG 电影项目的承接关系

简历两个 LLM 项目不是孤立的，是 LLM 应用工程的两条主线：

| 维度 | RAG 电影推荐 | 数据分析 Agent |
| --- | --- | --- |
| 范式 | 单跳检索-生成 | 多步规划-执行-纠错 |
| 输入 | 自然语言推荐需求 | 自然语言分析问题 |
| 核心难点 | 混合检索 + 重排 | Schema 理解 + 自纠错 |
| 输出 | 排序列表 + 解释 | 数据 + 图表 + 洞察 |
| 工具 | 无（纯生成） | SQL 执行 / 绘图 / Schema 查询 |
| 评估 | Recall@K / NDCG | Execution Accuracy / Task Success |

面试时可以讲一条演进逻辑："做 RAG 电影时发现单轮检索-生成对结构化数据无能为力——'2010 年后评分大于 8 的科幻片'我硬塞了一个 metadata filter 兜底，但真到了 BI 场景必须有真实 SQL 执行 + 错误反馈的闭环，所以做了第二个项目。"

### 1.3 一句话产品形态

用户输入自然语言（如"上季度退货率最高的三个品类是什么，每个品类的主要退货原因分布如何"），系统自动：

1. 拆解为子任务序列；
2. 每个子任务生成 SQL 并执行；
3. 遇到错误自动纠错（最多 3 次）；
4. 综合结果选择合适的可视化形式；
5. 生成文字洞察。

最终输出：图表 + SQL（可审查）+ 文字结论。

### 1.4 项目范围

- 个人项目，单机原型。
- 关注 Agent 工程链路与评估方法论，而不是 NL2SQL 的极限准确率。
- 数据库：本地 PostgreSQL，12 张表，约 10 万订单 / 50 万订单明细 / 2 万 SKU。

---

## 二、整体架构

```
┌────────────────────────────────────────────────────┐
│  User Query (自然语言分析问题)                       │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  I. Planner (LLM)                                  │
│    拆解为子任务序列 [task_1, task_2, ...]          │
│    每个 task 包含 {goal, expected_output_type}     │
└──────────────────────┬─────────────────────────────┘
                       ↓ (per task)
┌────────────────────────────────────────────────────┐
│  II. Schema Retriever                              │
│    用 task description 检索相关表/字段             │
│    (Schema-as-RAG, ChromaDB)                       │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  III. SQL Generator (LLM)                          │
│    输入: task + 相关 schema + few-shot exemplars   │
│    输出: SQL + 解释注释                            │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  IV. Sandbox Executor                              │
│    Read-only DB, 超时 30s, 行数上限 100k           │
│    AST 检查 (禁止 DDL/DML)                         │
└──────────────────────┬─────────────────────────────┘
                       ↓
                  ┌────┴────┐
            执行成功         执行失败
                  │              │
                  ↓              ↓
       ┌──────────────┐  ┌─────────────────────┐
       │  V. Critic   │  │  V'. Self-Correction│
       │  结果合理?    │  │  基于 error message │
       │  (LLM check) │  │  重生成 SQL,最多3次 │
       └──────┬───────┘  └──────────┬──────────┘
              │ ok           失败/超限│
              ↓                       ↓
   ┌──────────────────────┐    标记失败,跳过该 task
   │  汇总到 task 输出     │
   └──────────┬───────────┘
              │
   (所有 task 完成后)
              ↓
┌────────────────────────────────────────────────────┐
│  VI. Visualization Selector                        │
│    根据数据形状选 chart 类型 (rule-based + LLM)    │
│    matplotlib / plotly 渲染                        │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  VII. Narrative Generator (LLM)                    │
│    基于 SQL 结果 + 图表生成文字洞察 (grounded)     │
└──────────────────────┬─────────────────────────────┘
                       ↓
              图表 + SQL + 文字结论
```

**关键设计原则**：

1. **规划与执行分离**：先用一个便宜模型把任务拆好（一次调用），再分别执行子任务。比 ReAct 每步都让 LLM 决策省 token。
2. **Schema 不能整个塞 prompt**：12 张表 DDL ≈ 3000 token，加上 few-shot 和 query 就接近上下文上限，用 RAG 检索相关 schema。
3. **错误反馈是 Agent 的核心信号**：DB error message 是免费的高质量监督信号，必须利用。
4. **Critic 兜底语义错误**：SQL 跑通不等于结果对——SUM 漏 GROUP BY、JOIN 漏条件都会"跑通但错"，需要单独的 Critic 步骤。

---

## 三、数据层

### 3.1 数据库选择

**PostgreSQL**，原因：

- 比 SQLite 更接近真实业务库（支持 window function、CTE、JSON 字段）。
- 比 MySQL 标准 SQL 兼容性更好，LLM 训练数据里 Postgres dialect 也最常见。
- 本地 Docker 起一个就行，不依赖云服务。

### 3.2 业务领域：电商

选电商的理由：

- **schema 复杂度适中**：12 张表，比 Spider 中位数（5 张）复杂，又不至于像金融衍生品那种 50 张表脱离个人项目尺度。
- **业务概念通俗**：面试官不需要解释"什么是 SKU""什么是退货"，节省沟通成本。
- **分析问题样本丰富**：销售、退货、客单价、复购、品类对比、漏斗——都是经典分析题，构造评估集容易。

### 3.3 Schema 设计

12 张表，分四类：

| 类别 | 表名 | 主要字段 |
| --- | --- | --- |
| 主数据 | `users`, `skus`, `categories` | 用户/商品/品类基础信息 |
| 交易 | `orders`, `order_items`, `payments` | 订单、订单明细、支付 |
| 售后 | `returns`, `return_reasons` | 退货单、退货原因（FK 到字典表）|
| 行为 | `page_views`, `add_to_cart`, `reviews`, `customer_service_tickets` | 浏览、加购、评价、客服工单 |

**故意加入的"真实生产噪声"**（不是 toy schema）：

- 部分字段命名不规范：`order_status` 用枚举码（1/2/3/4），需要 JOIN `dim_order_status` 才能拿到中文含义。
- 软删除字段：`is_deleted = 0/1`，不加这个条件会捞到脏数据。
- 时区问题：`created_at` 是 UTC，业务方说"上季度"指的是本地时区季度——LLM 不注意会算错。
- 字段名同义不同义：`amount` 在 `orders` 表是含税总额、在 `payments` 表是实付额，新人/LLM 容易混。

这些噪声是**面试时的故事点**——"我故意在数据里埋了这些坑，因为真实生产库就是这样的，光跑 Spider 看不出 Agent 在真实场景的稳定性"。

### 3.4 数据规模与来源

- 基础数据来自 **Brazilian E-commerce Public Dataset by Olist**（Kaggle 公开）——约 10 万真实订单。
- **Faker 合成增强**：补齐 Olist 缺失的字段（评价文本中文化、退货原因映射、客服工单），保证表关系完整。
- **业务噪声注入**：手工写规则注入软删除、时区、状态码等模式。

最终规模：

| 表 | 行数 |
| --- | --- |
| users | 9.9 万 |
| skus | 3.3 万 |
| orders | 9.9 万 |
| order_items | 11.2 万 |
| returns | 1.2 万 |
| reviews | 4.0 万 |
| 其余 | 1k ~ 5w 不等 |

### 3.5 字段说明字典

每张表的字段都有人工写的 `description`、`example_value`、`notes`（如时区、口径），存在 `schema_metadata.json` 里。这份文档是 **Schema-as-RAG 的检索素材**——LLM 不是看 DDL 学 schema，是看这份带语义注释的文档。

示例：

```json
{
  "table": "orders",
  "columns": [
    {
      "name": "created_at",
      "type": "TIMESTAMP",
      "description": "订单创建时间,UTC 时区",
      "notes": "业务方所说的'季度'通常指 America/Sao_Paulo 时区,查询时需 AT TIME ZONE 转换"
    },
    {
      "name": "amount",
      "type": "NUMERIC(10,2)",
      "description": "订单含税总额",
      "notes": "区别于 payments.amount(实付额,扣除优惠券),分析'销售额'用本字段,分析'实收'用 payments.amount"
    }
  ]
}
```

---

## 四、Agent 架构选型：Plan-and-Execute

### 4.1 为什么不是纯 ReAct

ReAct 是 "Thought → Action → Observation → Thought → ..." 的循环，每一步都让 LLM 重新决策下一步做什么。

**优点**：灵活，适合探索式任务（如"在 Wikipedia 上找某个人的生卒年"——下一步搜什么取决于当前看到了什么）。

**缺点对数据分析任务很致命**：

1. **token 浪费**：每一步都要把完整的 task 描述 + 历史 thought/observation 塞回 prompt，越往后越长。一个 5 步分析任务可能要烧掉 1 万 token 在重复上下文上。
2. **不稳定**：LLM 可能在第 3 步突然"忘了"原始目标，跑去做无关探索。
3. **不可观测**：没法预先估算任务大致要几步，监控/计费/超时都不好做。

数据分析任务的**结构相对确定**——"先理解 schema → 写 SQL → 执行 → 出图 → 解读"，不需要每步重新探索。

### 4.2 Plan-and-Execute 的设计

借鉴 LangChain 的 plan-and-execute agent，但简化：

```python
class AnalysisAgent:
    def run(self, user_query):
        # Step 1: 一次性规划
        plan = self.planner.plan(user_query)
        # plan = [
        #   Task(id=1, goal="找出上季度退货率最高的三个品类", expected="表"),
        #   Task(id=2, goal="对每个品类查询退货原因分布", expected="表", depends_on=[1]),
        #   Task(id=3, goal="可视化", expected="图", depends_on=[1, 2]),
        # ]

        # Step 2: 顺序执行(简化,不做 DAG 并行)
        results = {}
        for task in plan:
            ctx = {dep: results[dep] for dep in task.depends_on}
            results[task.id] = self.executor.execute(task, ctx)

        # Step 3: 汇总
        return self.synthesizer.synthesize(user_query, plan, results)
```

**Planner、Executor、Critic 都是独立的 LLM 调用**，prompt 模板各自专门设计。这种"角色化"结构在 Multi-Agent 文献里叫 "role-based decomposition"，比一个大 prompt 包揽所有职责更稳。

### 4.3 为什么不上 DAG 并行执行

理论上不依赖的 task 可以并行，但本项目没做：

- 多数分析任务有强时序依赖（task_2 需要 task_1 结果作为输入参数）。
- 并行带来调度复杂度，对单机原型 ROI 低。
- 真要并行也是把 LLM 调用并发起来（asyncio）即可，架构不用改。

**面试时如果被问"为什么不并行"**：诚实说"我评估过，本项目的 task 之间依赖强，并行没收益。真要做并行，会用 LangGraph 的 DAG 调度，但当前用 plain Python 顺序执行足够"。

### 4.4 框架选择：LangGraph

- 用 LangGraph 编排 Plan → Execute → Critic 状态机。
- 也评估过 LangChain 的 `AgentExecutor`、AutoGen、CrewAI。
- LangGraph 的优势：**显式 state machine、可暂停/恢复、checkpoint 支持**，适合 self-correction 这种需要回退重试的场景。
- 没用 AutoGen/CrewAI：它们更偏 "多角色对话" 范式，对本项目"流水线 + 错误恢复"过设计了。

---

## 五、Schema Understanding：Schema-as-RAG

### 5.1 问题：完整 schema 塞不进 prompt

- 12 张表 × 平均 8 字段 × 每字段一行 description ≈ 100 行 ≈ 2500-3000 token。
- 再加 few-shot 示例（每个示例 ~200 token × 5 个 = 1000 token）+ user query + Chain-of-Thought 输出空间，单次 SQL 生成 prompt 容易突破 8k token。
- 大 prompt 不仅贵，还会**稀释关键信息**——LLM 在长 prompt 里更容易忽略关键字段说明。

### 5.2 解决方案

把 schema 拆成"文档块"，每个表/字段独立 embed，检索 Top-K 相关的注入 prompt。

**Chunking 策略**（结构化）：

- 每张表一个 chunk：`{table_name} | {table_description} | {主要业务用途}`。
- 每个字段一个 chunk：`{table_name}.{column_name} | {type} | {description} | {notes}`。
- 还有特殊 chunk："表关系图谱"——记录 FK 关系，避免 LLM JOIN 不上。

总 chunk 数 ~150（12 表 + 12 × 8 字段 + 几个特殊 chunk）。

**Embedding**：`bge-large-zh`（和 RAG 电影项目共用一套，schema description 是中文的）。

**检索策略**：

1. 用 task description 检索 Top-15 chunk。
2. 把检索到的 chunk 按表聚合——如果一张表的多个字段都被检中，整张表 schema 全注入（不只注入命中字段，因为 SQL 经常需要 JOIN 旁边字段）。
3. **始终注入主键 + 主要外键**（hard-coded 白名单），避免 RAG miss 导致 JOIN 不上。

### 5.3 这个做法对 NL2SQL 准确率的提升

| Schema 注入方式 | Execution Accuracy |
| --- | --- |
| 完整 schema 全塞 | 0.58 |
| 只塞表名(无 description) | 0.41 |
| **Schema-as-RAG (Top-15)** | **0.71** |

提升 13 个百分点的主要来源：

- **业务 notes 被注入**（"amount 区别于 payments.amount"）让 LLM 选对字段。
- **表关系 chunk 被注入**让 JOIN 条件准确。

### 5.4 一个真实踩过的坑

第一版 schema RAG 没注入 FK 关系，LLM 经常 `JOIN ... ON o.user_id = u.id` 写错（实际字段是 `u.user_uuid`）。加入"表关系图谱"chunk 后这类错误下降一半。

**教训**：RAG 的检索粒度要适配下游 task 的需求——SQL 生成需要"字段语义 + 关系"两类信息，单一字段 chunk 不够。

---

## 六、SQL 生成层

### 6.1 Prompt 结构

```text
你是数据分析助手,生成 PostgreSQL SQL。

## 数据库 schema (与本任务相关的部分)
{schema_chunks}

## 任务历史 (当前任务依赖的上游结果)
{upstream_results_summary}

## 类似任务的成功案例
{few_shot_exemplars}

## 当前任务
{task_description}

## 输出格式
{
  "reasoning": "...先简述思路,例如先 JOIN 哪两张表,GROUP BY 什么",
  "sql": "...",
  "expected_output_shape": "..." // 用于 Critic 检查
}

## 约束
- 只能用 SELECT,不能 DDL/DML。
- 注意软删除字段 is_deleted = 0。
- 时间字段是 UTC,业务'季度'指 America/Sao_Paulo 时区,用 AT TIME ZONE。
- 涉及金额时,'销售额' = orders.amount,'实收' = payments.amount,别混。
```

### 6.2 Few-shot Exemplar 选择

**不是固定示例**——根据当前 task 的语义相似度动态检索。

实现：

- 维护一个 ~80 条的"成功案例库"（自己手写 + 评估迭代中验证过的）。
- 每个案例：`{task_text, sql, output_shape}`。
- task embed 后检索 Top-3。

**为什么动态选**：

- 不同任务依赖的 SQL 模式差很多（聚合、窗口函数、子查询、UNION）。
- 固定 few-shot 要么过度泛化（覆盖不全）、要么偏向某类（其他类失灵）。
- 动态选能让 prompt 里的示例和当前任务**模式相似**，LLM 模仿成本最低。

### 6.3 Constrained Decoding（部分）

完整的 constrained decoding（如 outlines）会限制每个 token 必须是合法 SQL 语法。本项目没上这么重，只做：

- **结构约束**：输出必须是 JSON，用 DeepSeek 的 JSON mode。
- **白名单约束**：在 prompt 里明确列出可用的表/字段，让 LLM 不要凭空想新表名。
- **执行前 AST 检查**：用 `sqlglot` 解析 SQL，拒绝 DDL/DML，拒绝引用不存在的表/字段（这一步会在生成后、执行前做，归类到 self-correction 的输入）。

完整 constrained decoding 留作 future work——目前的"prompt 约束 + 后处理校验"组合在评估集上已经把语法错误降到 < 3%。

### 6.4 模型选择：DeepSeek-V3

- Query 解析、SQL 生成、Critic、Narrative 都用 V3。
- 成本：DeepSeek 比 GPT-4o 便宜 ~10x，端到端跑一次评估集（80 条 × 平均 3-4 个 task × 多步重试）成本可控。
- 性能：V3 在 SQL 生成上的表现接近 GPT-4o，差距小于 5 个百分点（评估集上），考虑成本是合理 tradeoff。
- Planner 用 V3 简化版（更短输出），节省。

---

## 七、Self-Correction 机制

### 7.1 错误类型分类

把执行错误分四类，对应不同的纠错策略：

| 类型 | 例子 | 是否可自动纠错 | 纠错信号源 |
| --- | --- | --- | --- |
| **A. 语法错误** | 缺逗号、关键字拼错、括号不闭合 | ✅ | DB error message |
| **B. Schema 错误** | 表名/字段名不存在或拼错 | ✅ | DB error message + schema RAG 重检索 |
| **C. 类型错误** | VARCHAR 当数字加、JOIN 字段类型不匹配 | ✅ | DB error message |
| **D. 语义错误** | SQL 跑通但结果不对(漏 GROUP BY、JOIN 漏条件、WHERE 条件覆盖错) | ⚠️ 需 Critic | 结果异常（行数为 0、值离谱）|

A/B/C 占执行错误的 ~70%，D 占 ~30%（评估集统计）。

### 7.2 自纠错循环

```python
def execute_with_correction(self, task, ctx, max_attempts=3):
    sql = self.sql_generator.generate(task, ctx)
    for attempt in range(max_attempts):
        result = self.sandbox.execute(sql)

        if result.status == "ok":
            critique = self.critic.check(task, sql, result)
            if critique.is_acceptable:
                return result
            # 语义错误,带 critic 反馈重生成
            sql = self.sql_generator.regenerate(task, ctx, sql, critique.feedback)
        else:
            # A/B/C 类错误,带 error message 重生成
            sql = self.sql_generator.regenerate(task, ctx, sql, result.error)

    return ExecutionFailed(task, last_attempt=sql)
```

### 7.3 为什么限 3 次

- 评估集上的"经过几次纠错才成功"分布：

  | 尝试次数 | 累计成功率 |
  | --- | --- |
  | 1 次（首次成功） | 64% |
  | 2 次 | 79% |
  | 3 次 | 81% |
  | 4 次 | 81% (基本无增量) |
  | 5+ 次 | 81% |

- 3 次后增量已经趋零——说明剩余的失败是**根本性的**（任务本身在 schema 上无法表达、或 LLM 一直在错误模式里打转），多试也没用。
- 限 3 次保住成本和延迟下限。

### 7.4 Critic 的设计

Critic 不直接看 SQL（看 SQL 等于让 LLM 改自己的作业），而是看**结果的结构特征**：

- 行数为 0 → 可能 WHERE 条件错。
- 单值极端（如某列均值远超合理范围）→ 可能漏单位换算或 JOIN 条件。
- 输出 shape 与 `expected_output_shape` 不符（task 说要 N 行 K 列，实际给了别的）→ 直接退回。
- 结果中出现 NaN/NULL 比例 > 30% → 可能 JOIN 类型不对（应该 INNER 写成 LEFT）。

Critic 本身也是 LLM，prompt 是"你是数据分析 reviewer，看这个查询结果是否合理"。

**坦诚的局限**：Critic 漏检率不低——只检"明显异常"的结果，对"看起来合理但实际错"的 case 无能为力。这是 LLM-as-judge 的固有问题。

---

## 八、可视化与洞察生成

### 8.1 图表类型选择

**规则 + LLM 兜底**：

```
if 单变量数值 + 时间维度: line chart
elif 单分类变量 + 数值聚合: bar chart
elif 双分类变量交叉 + 数值: heatmap or stacked bar
elif 单变量分布: histogram
elif 两数值变量相关: scatter
else: 让 LLM 选(传数据形状描述,让它推荐)
```

绝大多数业务分析用规则就能命中（覆盖 ~85% 的 case），剩下复杂的让 LLM 选。

**为什么不全交给 LLM 选**：

- 规则可控、可调试、零成本。
- LLM 选 chart 类型有时会过度发挥（明明 bar chart 够了非要画 sunburst）。
- 规则 + LLM 兜底的组合比纯 LLM 稳。

### 8.2 渲染

- `matplotlib` 静态图（生成 PNG），`plotly` 交互图（生成 HTML）。
- 项目主要用 matplotlib——单机原型不需要交互。
- 中文字体处理：注册 `Noto Sans CJK SC`，避免方框乱码。

### 8.3 Narrative 生成

类似 RAG 电影项目的"推荐解释"，强 grounding：

```text
基于以下数据点生成 2-3 句业务洞察:

## 用户原始问题
{user_query}

## 查询结果(精简形式)
{result_summary}

## 图表说明
{chart_description}

要求:
1. 只能基于上面提供的数据点,不要外推到没有的数据。
2. 用业务语言,不要写"经过分析"这种废话。
3. 如果数据不足以下结论,直接说明。
```

防幻觉同样靠"结构化部分由系统填、主观部分受 grounding 约束"——具体数字直接从查询结果模板渲染，LLM 只生成"为什么这样"的解读。

---

## 九、安全约束

数据分析 Agent 接触真实数据库，安全是个**面试官必问**的点。我做了五道防线：

### 9.1 数据库账号层

- Agent 用的 DB user 是 **read-only role**——`GRANT SELECT ON ALL TABLES`，不给 INSERT/UPDATE/DELETE/DDL。
- 退一万步说 LLM 写出 `DROP TABLE` 也跑不动。

### 9.2 SQL AST 层

用 `sqlglot` 解析 SQL，拒绝：

- 任何 DDL（CREATE/DROP/ALTER）。
- 任何 DML（INSERT/UPDATE/DELETE）。
- `pg_*` 系统表访问（避免泄露系统信息）。
- 反引用执行（`CALL`、`DO`）。

### 9.3 查询资源层

- 超时 30 秒（PostgreSQL `SET statement_timeout`）。
- 行数上限 10 万（在 SQL 外层 wrap `LIMIT 100000`）。
- 内存限制（`SET work_mem`）。

### 9.4 数据脱敏层

- PII 字段（手机号、邮箱、地址）在 schema metadata 标记 `is_sensitive=True`。
- Sensitive 字段不进 schema RAG（LLM 看不到，自然不会查询）。
- 即使 LLM 强行写了 `SELECT phone FROM users`，AST 层会拦截。

### 9.5 注入防护

用户的自然语言 query 不直接进 SQL（这本来就是 NL2SQL，不是 SQL 模板拼接），但仍需注意：

- 用户 query 中的字符不会被插入到生成的 SQL 作为字符串字面量。
- 任何外部传入的参数（如时间范围参数）走参数化绑定，不是字符串拼接。

**面试时如果被问"你怎么防 SQL 注入"**：直接讲这五道防线，重点强调 9.1（DB 账号权限）——SQL 注入的本质防御是 **principle of least privilege**，其他都是辅助。

---

## 十、评估体系

### 10.1 评估数据集

**两个评估集**：

| 评估集 | 来源 | 规模 | 用途 |
| --- | --- | --- | --- |
| **Spider-mini** | Spider dev set 抽样,改写为电商 schema 兼容版 | 200 条 | NL2SQL 单步精度,对比公开 benchmark |
| **业务场景集** | 自建,模拟真实业务方提问 | 80 条 | 端到端 Agent 任务,多步规划+纠错 |

**业务场景集构造**：

- 1/3 单步分析（"上月销售额最高的品类"）—— baseline 对照。
- 1/3 多步分析（"找出退货率最高的品类,再看每个品类的退货原因"）—— 测多步规划。
- 1/3 含陷阱（涉及时区、软删除、字段歧义）—— 测对 schema notes 的利用。

每条标注：
- `query`: 自然语言问题
- `expected_tables`: 预期会用到的表
- `gold_sql_or_result`: 黄金 SQL 或最终聚合数值
- `tags`: 多步/含陷阱/聚合/JOIN 复杂度等

### 10.2 评估指标

| 指标 | 衡量 | 计算 |
| --- | --- | --- |
| **Execution Accuracy (EX)** | 生成 SQL 跑出来和 gold SQL 结果一致 | 在 Spider-mini 上算 |
| **Component Match (CM)** | SQL 关键组件（SELECT/WHERE/GROUP BY 子句）匹配 | Spider 官方脚本 |
| **Task Success Rate (TSR)** | 端到端任务最终输出是否被人工判定为"满足业务问题" | 业务场景集,人工 + LLM judge |
| **Self-Correction Lift** | self-correction 多救回多少 case | 比较关/开 correction loop 的 EX 差值 |
| **Avg Steps to Success** | 平均几次纠错后成功 | 平均 attempt 次数 |
| **Narrative Faithfulness** | 文字洞察是否与数据一致 | LLM judge |

### 10.3 三个版本的指标演进（Spider-mini）

| 版本 | 关键改动 | EX | CM |
| --- | --- | --- | --- |
| **v1** | 朴素 prompt + 整个 schema | 0.58 | 0.61 |
| **v2** | Schema-as-RAG + 动态 few-shot | 0.71 | 0.74 |
| **v3** | v2 + Self-correction loop | 0.79 | 0.80 |

业务场景集（端到端）：

| 版本 | TSR | 平均 attempt 次数 |
| --- | --- | --- |
| v1（单步、无规划） | 0.42 | 1.0（不重试） |
| v2 + Planner（多步） | 0.55 | 1.0 |
| v3 + Self-correction | **0.68** | 1.6 |

**每一步的归因**：

- v1 → v2：Schema RAG 解决"字段不知道"问题，动态 few-shot 解决"复杂 SQL 模式不熟"问题。bad case 分析里"字段名拼错"和"JOIN 不上"几乎消失。
- v2 → v3：Self-correction 是 EX 涨幅最大的一步（+8）。看 bad case：约 60% 的 v2 失败是"第一次写错但 error message 已经指明问题"，self-correction 直接救回。
- 业务集 TSR 比 Spider EX 涨得更明显（0.42 → 0.68），因为多步任务里 self-correction 累积收益更大——单步成功率 0.79 的 3 步任务，naive 串行成功率只有 0.79³ ≈ 0.49，self-correction 把每步打高到 0.85+ 后端到端就上 0.6+。

### 10.4 失败 case 分类（v3 仍失败的 19%）

| 失败原因 | 占比 | 改进方向 |
| --- | --- | --- |
| 复杂多表 JOIN (5+ 表) | 35% | 微调专用 NL2SQL 模型 / 分步拆解 |
| 业务概念歧义("活跃用户"没明确定义) | 25% | Agent 主动反问而不是猜 |
| 时序/窗口函数 | 20% | few-shot 加强,或专门 prompt 引导 |
| 真·语义错误(SQL 跑通但答错) | 15% | Critic 不够强,需要更精细的检查规则 |
| 其他(罕见 SQL 特性) | 5% | / |

### 10.5 LLM-as-judge for Narrative

- Judge：Claude 3.5 Sonnet（避免和 generation 用同模型造成偏差）。
- Prompt：给 query + 数据结果 + AI narrative，判断 (1) 数字一致 (2) 业务结论合理。
- 抽样 50 条评估，Faithfulness ~91%，主要错误是"对数据外推过度"（数据只到 Q3，narrative 说"全年趋势..."）。
- 改进：narrative prompt 加强 "不外推到数据范围外" 后涨到 ~96%。

---

## 十一、关键设计决策与权衡

> 面试拷打区,每个决策都准备好"为什么是这个,不是那个"。

### 11.1 为什么 Plan-and-Execute 不是 ReAct

见 4.1。补一点：数据分析任务的步骤结构相对确定（理解→生成→执行→纠错→可视化），Plan-and-Execute 的"先规划再执行"和这个结构匹配；ReAct 的灵活性在这里反而是 over-engineering。**真正的探索式任务（如 Deep Research）才需要 ReAct**。

### 11.2 为什么 Schema-as-RAG 不是整个 schema 塞 prompt

见 5.1。补一点：12 张表看起来不多，但真实生产库经常是 200+ 张表，本项目用 RAG 的方法可以**直接 scale 到大型库**，不用换架构。如果 demo 时被问"你这只有 12 张表，整个塞也行"，可以回答"是的，但 RAG 方案是 forward-compatible 的，工业部署不需要重做"。

### 11.3 为什么 Self-correction 限 3 次

见 7.3。补一点：限次数比"看 LLM 觉得行不行"更可控——LLM 自我评估能力差，让它判断"还需不需要再试"，它会无脑说"再试一次"，跑到 token 用光。**Hard limit 是工程纪律**。

### 11.4 为什么不微调 NL2SQL 专用模型（SQLCoder 等）

- **数据不够**：我没有大规模的 (NL, SQL, schema) 标注数据。
- **微调模型 schema 泛化差**：SQLCoder 之类的模型在公开 benchmark 强，但换 schema 后掉得很厉害——这正是 LLM Agent + Schema RAG 的优势。
- **ROI 不划算**：80 条业务标注集做不动 SFT,做 LoRA 也只是过拟合到当前 schema。
- **生产部署考虑**：DeepSeek API 比自己部 SQLCoder 简单得多。

如果真要上微调，时机是：业务方使用半年积累了大量(NL, SQL, ✅/❌)反馈后，做 DPO 提升模型对 schema notes 的利用——但这是 v2 阶段的事，v1 应该先把 Agent 链路跑通。

### 11.5 为什么用 LangGraph 不手写 state machine

- **现成的 checkpoint / 持久化**：self-correction 失败后 resume，LangGraph 原生支持。
- **可视化 graph**：调试时能直接看到状态流转。
- **社区生态**：将来要扩展（如加并行执行、加 human-in-the-loop）有现成方案。

**没用的话也行**：手写一个 dict-based state machine 不超过 200 行。选 LangGraph 是"工程上的便利"，不是"必须"。**面试时被问到要诚实**，不要把 LangGraph 吹成必需。

### 11.6 为什么不上 Text-to-Pandas 或 Code Interpreter

- 一种替代方案是不生成 SQL，让 LLM 直接生成 Pandas 代码读 CSV/DataFrame——这是 OpenAI Code Interpreter 的路子。
- 我没选这条路的原因：
  1. **生产场景的数据在 DB 里**，不在内存里。Code Interpreter 路线要先把数据拉到本地，对大表行不通。
  2. **SQL 是标准接口**，DBA 看得懂、能优化、能审计；Python 代码就难审计了。
  3. **安全性**：执行任意 Python 代码 vs 受限的 SELECT-only SQL，前者风险大得多。

工业界的 NL2SQL 路线选择是有道理的，不是"过时"。

### 11.7 为什么用 Olist + Faker 不直接用 Spider

- Spider 是单库 toy schema，复杂度不够。
- Olist 是真实业务数据，有真实业务噪声，更能反映"Agent 在真实场景的稳定性"。
- Spider 还在用——但用法是 Spider-mini 作为对比 benchmark，不是项目主数据。

---

## 十二、局限与改进方向

### 12.1 诚实暴露的局限

1. **复杂多表 JOIN 仍是瓶颈**：5+ 表的 JOIN 准确率明显下降，这是当前 LLM 在结构化推理上的硬伤。
2. **Critic 漏检率高**：对"看起来合理但实际错"的语义错误 detect 不出来。
3. **业务概念依赖人工标注**：什么是"活跃用户"、什么是"高价值客户"，schema metadata 里要手工写清楚，否则 LLM 瞎猜。
4. **无对话上下文**：用户每次都要重发完整 query，不支持"基于刚才的结果再问"。
5. **数据库 dialect 锁定 PostgreSQL**：换 MySQL/ClickHouse 需要重做 prompt 的 SQL syntax 部分。
6. **没考虑数据量爆炸**：本项目 10 万订单单机能算，真实生产 100 亿行的 fact table 要走分布式（presto/trino），SQL 写法也要变。

### 12.2 真要继续做的改进顺序

1. **对话式 refinement**（1-2 天）：保留上一轮的 SQL 和结果作为 context，支持"换成 Q4 数据""加上品类维度"这种增量查询。
2. **Critic 强化**：训一个轻量分类器判断"结果是否异常"，比 LLM 兜底准。
3. **业务术语词典**：把"活跃用户""复购率"等业务概念固化为 SQL 片段，LLM 直接调用而不是重新生成。
4. **多 dialect 支持**：把 SQL 生成 prompt 模板化，按目标 dialect 注入 syntax 规则。
5. **真实生产环境上线**：和 BI 工具集成（Metabase / Superset 插件形式），收集真实反馈。

---

## 十三、高频深挖问题与回答

### A. NL2SQL 基础（6 题）

#### Q13.1 NL2SQL 的主要技术路线有哪些？你为什么选 LLM Agent 路线？

> 主流三条：
>
> 1. **基于语义解析（Semantic Parsing）**：把 NL 解析为中间表示（如 SQL AST 模板），再具化为 SQL。代表是 Spider 时代早期模型。优点是结构化、可解释；缺点是覆盖窄，遇到新 SQL 模式就要扩文法。
> 2. **端到端微调模型**：Seq2Seq 直接生成 SQL。代表是 T5-based、SQLCoder。优点是覆盖宽；缺点是 schema 泛化差，换库性能掉得厉害。
> 3. **LLM Agent + Prompting**：LLM 加 schema context + 工具调用 + 自纠错。优点是开箱即用、schema 泛化好；缺点是单步精度不如专门微调模型、推理成本高。
>
> 我选第 3 条的理由：
> - 个人项目，没有大规模标注数据，微调路线无解。
> - 真实业务的痛点不是"在固定 schema 上精度多高"，而是"换库后还能用"。
> - Agent 范式天然支持自纠错、多步规划，能解决复杂分析任务，不只是简单 NL2SQL。

#### Q13.2 Spider 这种 benchmark 上的 SOTA 模型为什么换到真实业务库会崩？

> 主要三个原因：
>
> 1. **Schema 命名差异**：Spider 的字段名都是干净的 `customer_name`、`order_date`，真实库是 `cust_nm`、`ord_dt_utc`。预训练阶段没见过这种命名分布。
> 2. **业务规则没编码**：Spider 没有"软删除""时区""口径"这些业务知识。真实库里 `is_deleted=1` 的脏数据不过滤会污染所有聚合。
> 3. **Schema 规模**：Spider 单库平均 5 张表，真实业务库 100+ 张表，整个 schema 塞不进 prompt——这就需要 schema RAG，而 SOTA 模型大多没考虑这层。
>
> 学术 benchmark 是必要的（不然没法对比），但**评估"工程上有没有用"必须自己造真实场景的评估集**。

#### Q13.3 Schema linking 是什么？你这套架构里 schema linking 是怎么做的？

> Schema linking 指的是把自然语言里的实体（"销售额""退货"）对应到 schema 里的具体字段。这是 NL2SQL 准确率最关键的瓶颈之一。
>
> 我这套架构里 schema linking 体现在两层：
>
> 1. **Schema-as-RAG 检索层**：用 query embedding 检索相关字段。这是粗粒度 linking。
> 2. **SQL 生成 prompt 层**：在 schema chunk 里写明 description 和 notes（"销售额"→`orders.amount`，"实收"→`payments.amount`），让 LLM 在生成时做细粒度 linking。
>
> 没做的：
> - **Explicit schema linking 步骤**——有些 paper 在 SQL 生成前先单独跑一步 "query 里每个名词对应哪个字段"，再用 linking 结果约束 SQL 生成。我没做这一步，因为 LLM 在合理 schema context 下隐式做了 linking，单独做一步反而增加错误传递风险。

#### Q13.4 你怎么处理 SQL 里的歧义？比如"上季度销售额"用户没说哪个时区

> 当前是**默认+提示**策略：
>
> - 默认按业务方实际时区（schema metadata 里指定为 America/Sao_Paulo）。
> - 在 narrative 里**显式说明假设**——"假设'上季度'指巴西时区的 2024 Q3，销售额为..."。
>
> 用户看到假设不对可以追问，相当于把歧义暴露给用户。
>
> 更好的做法是 **Agent 主动反问**（"您的'上季度'指本地时区还是 UTC?"），但有 tradeoff：反问太多体验差，反问太少错答多。当前选了"先默认 + 透明展示假设"的折中。

#### Q13.5 Few-shot exemplar 怎么选？固定 vs 动态？

> 动态。基于 task description 的 embedding 相似度从案例库检索 Top-3。
>
> **为什么动态优于固定**：
> - 不同 SQL 模式（聚合 / 窗口函数 / 子查询 / UNION）差异很大，固定示例覆盖不全。
> - 动态选让示例和当前 task 模式相似，LLM 模仿成本最低。
>
> **案例库怎么来**：
> - 自己手写 ~30 个种子示例。
> - 评估迭代过程中,把人工标的 gold SQL 加入案例库——这是个**自然滚雪球**的过程。
> - 现在 ~80 条,继续做下去会到几百条。

#### Q13.6 怎么判断 LLM 生成的 SQL 是不是"对的"？

> 三层判断：
>
> 1. **能不能跑**（语法 + schema）：执行不报错就过。
> 2. **结果合理性**：Critic 看输出 shape、空值率、极端值。
> 3. **和 gold result 一致**（评估时）：用 `set` 比较行集合（Execution Accuracy）。
>
> **生产里没法用 gold result 校验**——所以 Critic 是核心防线。Critic 本质是 LLM-as-judge，有漏检；要补，需要业务方反馈循环（用户标"这个回答对/错"，用作 RLHF / DPO 数据）。

### B. Agent 架构（6 题）

#### Q13.7 ReAct、Plan-and-Execute、Reflexion，区别和适用场景？

> - **ReAct**：Thought → Action → Observation 循环，每步 LLM 重新决策。适合**探索式任务**（如开放式搜索）。
> - **Plan-and-Execute**：先一次性规划，再按计划执行。适合**结构相对确定的任务**（如本项目的数据分析）。
> - **Reflexion**：执行后 LLM 反思失败原因，把反思写到 memory，下次执行时参考。适合**需要长期记忆的迭代任务**。
>
> 我这个项目主体是 Plan-and-Execute，self-correction 部分有点 Reflexion 味道（基于 error 反馈重生成）。
>
> 完整的 Reflexion（memory 跨 session 累积）我没做，因为本项目是 stateless 的——每个 user query 独立处理。

#### Q13.8 你说 LangGraph 是 state machine,有什么好处？相比 LangChain 的 AgentExecutor 呢？

> LangGraph 的核心是把 Agent 流程建模为 **directed graph**，每个 node 是个 step，edge 是条件转移：
>
> ```
> [planner] → [executor] → [critic] → if pass → [synthesizer]
>                            ↓ fail
>                       [sql_regenerator] → [executor] (loop)
> ```
>
> 好处：
>
> 1. **显式状态**：State 是个 dataclass，跨 node 传递，调试时直接 print。
> 2. **可暂停/恢复**：每个 node 后 checkpoint，挂了可以从断点恢复。
> 3. **可视化**：能 dump 出 graph 图，看到流转。
> 4. **比 AgentExecutor 灵活**：AgentExecutor 的循环结构是固定的（ReAct loop），自定义流程要改源码；LangGraph 是积木式拼装。
>
> 缺点：API 复杂度比 AgentExecutor 高一截，简单 Agent 用不上。

#### Q13.9 Multi-Agent 协作有哪些模式？你这个项目算不算 Multi-Agent？

> Multi-Agent 主要模式：
>
> 1. **Role-based decomposition**（角色分工）：Planner、Executor、Critic 各司其职。**本项目就是这种**——但每个角色是一次 LLM 调用，不是常驻 Agent。严格说叫 "multi-prompt"，不叫 "multi-agent"。
> 2. **Debate**：多个 Agent 给方案，互相评审。
> 3. **Hierarchical**（层级）：Manager Agent 派任务给 Worker Agent。
> 4. **Communicative**（对话式）：AutoGen 风格，Agent 间像聊天一样交流。
>
> 本项目我**不把它包装成 Multi-Agent**，因为这会给面试官造成"过度营销"的印象。诚实说"我用了 role-based prompt decomposition,角色逻辑各跑一次 LLM"更稳。

#### Q13.10 Agent 怎么处理执行失败？除了 self-correction 还有什么策略？

> 我用的是 **error-driven correction**，即基于 DB 真实 error message 来纠错。
>
> 其他策略：
>
> 1. **Backtracking**：失败时回退到更早的决策点（如 planner 阶段重新规划），不只是改 SQL。
> 2. **Tool fallback**：一个工具失败换另一个（如 SQL 写不出来改用 Pandas）。
> 3. **Human escalation**：连续失败后挂起，等用户介入。
>
> 本项目只做了 1 的简化版（self-correction），2/3 没做。**真要做生产化，3（escalation）必须加**——LLM Agent 永远会失败，关键是失败时给用户一个清晰的"无能为力"提示，而不是死循环或瞎编结果。

#### Q13.11 如果 Agent 在第二个 task 失败了，第一个 task 已经出图了,你怎么处理

> 当前是**降级输出**——已成功的 task 结果照常展示，失败的 task 在最终报告里明确标注："任务 2 [退货原因分析] 执行失败,可能原因是 schema 缺少 reason_code 字段的语义说明。SQL 见附录。"
>
> 不做的：**不删掉已成功的部分**（用户付了等待时间，至少要还点价值）；**不假装失败的 task 也成功**（生成虚假的图，幻觉灾难）。
>
> 这个降级行为我专门做了规则，因为"全有或全无"的 Agent 用户体验很差。

#### Q13.12 LangGraph 的 checkpoint 怎么用？真的有用吗？

> LangGraph 的 checkpoint 会在每个 node 执行后保存 state 到指定 storage（默认 SQLite）。
>
> **场景**：
> - **重试**：第三个 task 失败,不重跑前两个,从 checkpoint 恢复。
> - **Human-in-the-loop**：Agent 跑到一半挂起,等用户审批 SQL 后继续。
> - **审计**：每一步状态都留底,事后排查。
>
> 在本项目里 checkpoint **有用但不必需**——本项目单 query 端到端 ~10-20 秒，从头跑也行。生产化才真用得上，比如长时间任务挂起、人工审批 SQL 后再执行这种 workflow。

### C. 工程实现（5 题）

#### Q13.13 你的 schema RAG 用什么做的？为什么不直接用 SQL 做关键字匹配

> Embedding-based RAG，bge-large-zh + ChromaDB（和 RAG 电影项目共用一套基础设施）。
>
> 不用关键字匹配的原因：
>
> - 用户问 "上季度退货率",字段叫 `returns.return_count` / `orders.order_count`,直接字符串匹配匹不到——需要语义相似度。
> - 关键字匹配对同义词无能为力："销售额" vs "总收入" vs "GMV"。
>
> **但 BM25 仍然有用作为辅助路**——和 RAG 电影一样,做个简化版的混合检索（embedding + BM25）让"字段名出现在 query 里"的精确匹配信号被捕捉。我做了一个简单版本（同时跑 embedding 和 BM25,RRF 融合 Top-15）,小幅提升。

#### Q13.14 你的 sandbox executor 怎么实现的？真用 Docker 隔离吗

> 没用 Docker。本项目的"sandbox"是**应用层 + DB 层的多重限制**：
>
> 1. DB 账号是 read-only role,SQL 注入也只能 SELECT。
> 2. `sqlglot` AST 检查在执行前拒绝危险语句。
> 3. PostgreSQL 设置 `statement_timeout = 30s`、`work_mem` 限制。
> 4. 应用层 wrap `LIMIT 100000` 控制结果集大小。
>
> 真要做生产化才上 Docker——把整个 Agent 进程跑在 container 里,DB 进程隔离,网络隔离。
>
> 当前的方案对 read-only Agent 已经够了。"sandbox" 的本质是 **权限最小化**,Docker 只是包装。

#### Q13.15 LLM API 调用怎么管理？rate limit、超时、重试这些

> 用 `tenacity` 做指数退避重试,3 次重试,base delay 2s。
>
> 超时：每次调用 30s,超时直接抛 exception 不重试（LLM 卡那么久通常说明请求有问题,重试也是卡）。
>
> Rate limit：DeepSeek 的 rate limit 比较宽松,本项目 single user 跑没遇到。生产化要加 token bucket + 排队。
>
> Cost 监控：每次 LLM 调用记录 input/output token,跑评估集时输出总成本。**这是工程必备**——LLM Agent 的"未约束行为"会让单 query 成本爆炸,monitoring 是底线。

#### Q13.16 端到端延迟多长？怎么优化的？

> 端到端 ~12-25 秒/query (单 task 5-8s × 1-3 task)。
>
> 主要时延：
>
> - LLM 调用 80%（每次 3-6s）。
> - SQL 执行 10%（多数 query < 1s,复杂的 5-10s）。
> - Embedding / RAG 检索 < 5%。
>
> 优化方向：
>
> 1. **Planner 用更小的模型**：规划任务输出短,可以用 DeepSeek-V3 简化版,节省 1-2 秒。
> 2. **并行 LLM 调用**：独立 task 的 SQL 生成可以并发（async）。
> 3. **结果缓存**：相同 query 5 分钟内复用。
> 4. **Streaming narrative**：最后的 narrative 走流式输出,用户感知更快。
>
> 本项目没做这些优化,因为单机原型对延迟不敏感。生产化要做。

#### Q13.17 测试怎么写？Agent 的单元测试是什么样的

> 分三层：
>
> 1. **工具层单元测试**：sandbox executor、schema retriever、sqlglot AST 检查——这些是确定性函数,标准 unit test。
> 2. **LLM 调用层 mock 测试**：把 LLM response mock 成固定字符串,测试 graph 流转、状态管理、错误分支。
> 3. **集成测试**：跑评估集,看指标是否退化。**这是 LLM Agent 最重要的"测试"**——传统 assert 测不出 LLM 的语义正确性,必须靠评估集 + 阈值告警。
>
> 没做的：**LLM 输出的属性测试**（如"输出必须是合法 JSON""SQL 必须只含 SELECT"）。这层应该补,用 pytest + hypothesis 比较合适。

### D. 评估方法（4 题）

#### Q13.18 Spider 的 EX 和 EM 区别？为什么 EM 通常不报？

> - **Execution Accuracy (EX)**：执行 SQL 看结果是否和 gold 一致。
> - **Exact Match (EM)**：SQL 字符串/AST 是否和 gold 一致。
>
> EM 通常不报的原因：**SQL 有多种等价写法**——`a JOIN b ON ...` 和 `b JOIN a ON ...` 是等价的,字段 SELECT 顺序换了结果一样,但 EM 都判错。Spider 后来主推 EX 就是因为 EM 太苛刻。
>
> 我项目里两个都报,EM 当辅助参考——EM 高说明 LLM 不只是"碰巧跑对",而是真理解了 schema 结构。

#### Q13.19 你的 80 条业务集为什么不大一点？

> 三个原因：
>
> 1. **标注成本**：每条要写 gold SQL + 业务标签,人工标注 20-30 分钟/条,80 条已经几十小时。
> 2. **质量优先**：80 条覆盖 8 类典型业务问题（销售、退货、用户、复购、漏斗等），每类 10 条,够看分类指标。
> 3. **统计置信度的诚实**：80 条置信区间宽,我在汇报指标时**报区间不报点估计**——"v3 TSR 0.68 ± 0.05" 而不是 "0.68"。
>
> 真做产品级要 500+ 条,分场景分层抽样。

#### Q13.20 LLM-as-judge 自己会不会有偏差？怎么校准

> 有偏差,具体表现：
>
> 1. **Position bias**：A/B 比较时偏向第一个出现的。
> 2. **Length bias**：偏向更长更详细的回答。
> 3. **Self-preference**：用自己家族的模型当 judge 会偏向自家生成的。
>
> 我的应对：
>
> - **Judge 用 Claude 3.5 Sonnet,generation 用 DeepSeek**——跨家族,消除 self-preference。
> - **判断标准结构化**："是否数字一致 / 是否回答 query"分开打分,而不是给个总分。
> - **抽样人工复核**：50 条抽 10 条人工再过,看 judge 和人工一致率。本项目人工-judge 一致率 ~85%,可以接受。

#### Q13.21 怎么知道改进真的有效,而不是评估集过拟合？

> 几个机制：
>
> 1. **评估集分 dev / test**：迭代时只看 dev,test 锁住做 final report。
> 2. **每次迭代后做 bad case 分类**：看新失败的 case 是不是覆盖到了之前没见过的模式。如果改进只在 dev 涨、test 没涨,大概率过拟合。
> 3. **构造对抗集**：故意修改 schema 字段名、加入新的业务概念,看 v3 在新 schema 下还稳不稳。这是检验"是不是真的泛化"的关键。
>
> 坦白说本项目第 3 条做得不够好——只换了一次 schema 命名做对抗,系统化对抗集没建。要做产品级必须补。

### E. 安全与生产化（4 题）

#### Q13.22 你这个系统怎么防止 SQL 注入

见 9.5。**核心防御不是 prompt 提示词,而是 DB 账号最小权限**。

#### Q13.23 用户隐私怎么处理？比如查询里包含手机号

> 三层：
>
> 1. **Schema metadata 标记 sensitive 字段**,RAG 不索引,LLM 看不到这些字段存在。
> 2. **AST 检查拦截**：即使 LLM 强行写 `SELECT phone`,sqlglot 检查到敏感字段会拒。
> 3. **输出脱敏**（生产化需要,本项目没做）：返回行如果包含 PII,做 mask（138****6351）。
>
> 还需要的（本项目没做）：
>
> - **审计日志**：每次 LLM 调用、每次 SQL 执行、每次结果展示都记日志,合规审计追溯。
> - **数据访问权限按用户**：当前是单用户原型,生产环境要 user A 只看 A 的数据,基于 row-level security。

#### Q13.24 LLM 输出的 SQL 直接执行,出问题怎么追责

> 几个角度：
>
> 1. **Audit trail**：每次执行的 SQL、prompt、模型版本、user 全部记录,出问题能复现。
> 2. **Human approval gate（可选）**：高风险查询（涉及金额聚合、跨大表 JOIN）执行前要人工确认。本项目没做,生产化建议加。
> 3. **结果展示时附 SQL**：让用户能看到执行的真实 SQL,自己判断是否合理。这是**让 AI 决策可被监督**的基本设计。
> 4. **明确产品边界**：UI 和文档里说清"AI 生成的 SQL 仅供参考,关键决策需人工复核"。这是法务底线。
>
> 责任分摊：开发方负责 schema metadata 正确 + sandbox 隔离 + 审计完整;使用方负责对结果做业务判断;LLM 厂商负责模型 SLA。

#### Q13.25 如果用户问的问题超出 schema 范围（数据库没这数据），怎么办？

> 两层防御：
>
> 1. **Planner 阶段**：Planner 看到相关字段 RAG 检索结果都不相关时,直接返回"任务无法用现有 schema 完成,需要的字段是 XXX,建议联系数据团队补字段"。
> 2. **执行失败后**：如果 self-correction 三次仍失败,标记任务失败,narrative 里如实说明而不是瞎编。
>
> **绝对不能做的**：LLM 自己编一个看起来合理但实际不在 schema 里的字段名生成 SQL,跑失败也不告诉用户。这是 LLM Agent 最危险的 failure mode——把 hallucination 包装成 confidence。

### F. 灵魂拷问（5 题）

#### Q13.26 这套东西和 ChatGPT Code Interpreter / Claude 的 Analysis Tool 有什么区别？人家不是已经做了吗

> 三点不同：
>
> 1. **数据所在层**：Code Interpreter 把数据拉到 LLM 的 sandbox 里跑 Python——对大表（亿级行）不可行;企业数据也不能往外传。我这套是 SQL 下推到 DB,数据不出库。
> 2. **可审计性**：Code Interpreter 生成的 Python 代码 DBA / 业务方很难审,SQL 是标准接口能审。
> 3. **企业集成**：直接对接企业 DB 权限体系、行级安全,Code Interpreter 不在这个生态里。
>
> 工业界做 BI Agent（Looker AI、ThoughtSpot、各家在做的 NL2SQL 类产品）的真实需求,Code Interpreter 解决不了。**这是个真有产品空间的方向,不是个人项目自嗨**。

#### Q13.27 你这指标 EX 0.79 跟工业系统比怎么样？是高还是低

> 直接对比公开数据：
>
> - Spider dev EX SOTA（2024）：~0.92,但用了 GPT-4 + 微调 + 复杂 pipeline。
> - Spider dev 普通 LLM prompting（GPT-4 zero-shot）：~0.74-0.78。
> - BIRD（更难的 benchmark）EX 普遍 0.5-0.6。
>
> 我的 0.79（在 Spider-mini 上）属于"GPT-4 prompting 这个梯度",和 DeepSeek-V3 + 工程化 prompt 的预期匹配。
>
> **但 Spider 数字不能直接当业务能力的代理**——前面说过,真实业务 schema 复杂度 + 业务规则 + 资源限制,这些 Spider 不考核。**我的业务集 TSR 0.68 是更有意义的数字**,代表"在真实业务问题上能否端到端解决"。

#### Q13.28 如果我让你明天就把这个上生产,你需要补哪几件事

> 优先级排序：
>
> 1. **完整审计日志**（1 天）：每次 LLM 调用、SQL 执行、结果展示全部入库。合规底线。
> 2. **用户权限 + 行级数据隔离**（3-5 天）：当前是 stateless 单用户,生产要按用户隔离数据访问。
> 3. **更大评估集 + CI 集成**（1 周）：把评估集扩到 500+ 条,每次代码改动跑评估,指标退化自动告警。
> 4. **失败兜底 UX**（2 天）：当前失败就标红字,生产要给用户清晰的 next step（"联系数据团队加这个字段""换一种问法"）。
> 5. **Cost 监控告警**（半天）：单 query token 超阈值告警,防止 Agent 失控烧钱。
> 6. **rate limit / 排队**（2 天）：多用户并发场景的流控。
>
> 不做就上线的话,出 incident 是迟早的事——LLM Agent 不是确定性系统,生产化必须先把 observability 和兜底做好。

#### Q13.29 这个项目和 CATL 那个推荐项目相比,哪个工程量更大？哪个学到的多

> 工程量：**数据分析 Agent 更大**——CATL 那个核心是数据治理 + 一个 KNN 模型,链路相对扁平;这个项目链路有 7+ 个组件,涉及 LLM、向量库、DB、可视化多个子系统。
>
> 学到的：
>
> - CATL 学到的是**业务沟通**和**数据治理**——怎么把"老师傅经验"转成可建模问题,怎么洗百万级生产数据。
> - 这个学到的是**LLM Agent 工程化**——Plan-and-Execute 怎么落,self-correction 怎么设计,LLM-as-judge 怎么校准。
>
> 互补性强,不是替代关系。CATL 偏"算法工程师的传统功底",这个偏"算法工程师的新范式"。

#### Q13.30 如果让你重做一遍,会怎么改

> 三点：
>
> 1. **更早搭评估集**：和 RAG 电影项目同样的教训,先有评估再有迭代。这次稍微好一点,但 Spider-mini 的搭建仍然滞后于 v1 几天。
> 2. **更早做 Schema-as-RAG**：v1 我图省事把整个 schema 塞 prompt,结果调 prompt 很痛苦——后来加 RAG 才发现这才是结构性解法。**直觉是"先简单方案再优化",但这次"简单方案"反而是死路,RAG 才是结构正确的起点**。
> 3. **更早跟踪 cost**：v1 没监控 token,跑一次完整评估几十块,后来加 token 监控才发现 prompt 越来越长,加 schema RAG 后单 query token 直接砍掉 60%。

---

## 附：临场提醒清单

- [ ] **数字三件套必背**：
  - Spider-mini EX：**0.58 → 0.71 → 0.79**
  - 业务场景集 TSR：**0.42 → 0.68**
  - 数据规模：**12 张表 / 10 万订单 / 200+80 条评估集**
- [ ] **Plan-and-Execute 流程图要能在白板上画**：Planner → Executor (含 SQL + Sandbox + Critic) → Synthesizer,带 self-correction 回路。
- [ ] **Self-correction 三类错误要能秒答**：语法错、schema 错、类型错（自动修）、语义错（Critic 兜）。
- [ ] **安全五道防线要能背出来**：DB 账号权限 / AST 检查 / 资源限制 / 脱敏 / 注入防护。
- [ ] **和 RAG 电影项目的承接故事要顺**：单跳检索 → 多步规划 + 自纠错的演进逻辑。
- [ ] **被问"代码在哪"**：和 RAG 电影一样,诚实说"本地原型"。
- [ ] **被问"为什么不上 LangGraph 的 XX 高级特性"**：承认本项目用得浅,讲清楚什么时候需要、为什么不需要,不要硬吹。
- [ ] **被问 Spider SOTA 比较**：直接给数据,讲清"benchmark 数字 vs 业务可用性"的区别,显出判断力。
- [ ] **全程关注 tradeoff 表达**：每个选型都用 "为什么是 X 不是 Y" 的句式,显出工程判断力。
