# 测试结果报告

> 生成时间: 2026-06-22

## 单元测试: 49/49 全部通过

```
tests/test_ast_checker.py ................ 15 passed
tests/test_chart_selector.py .............  8 passed
tests/test_correction_classifier.py ...... 10 passed
tests/test_metrics.py .................... 16 passed
```

### 测试覆盖

| 测试文件 | 通过 | 说明 |
|----------|------|------|
| test_ast_checker | 15 | SELECT/CTE 允许, DROP/INSERT/UPDATE/DELETE/CREATE 拒绝, 系统表拒绝, PII 拒绝 |
| test_chart_selector | 8 | 折线/柱状/横向柱状/热力图/直方图/散点图/饼图/空结果 |
| test_correction_classifier | 10 | 语法错误/表缺失/字段缺失/类型错误/函数错误/未知错误/实体提取 |
| test_metrics | 16 | EX 集合比较/顺序无关/CM 组件匹配/TSR/纠错提升/平均尝试次数 |

## 端到端评估

### 单步查询

| 查询 | 结果 | 耗时 |
|------|------|------|
| 统计订单总数 | PASS (97,453 条) | 29s |
| 统计用户总数 | PASS | 5s |
| 统计商品总数 | PASS | 5s |
| 计算订单平均金额 | PASS | 5s |
| 计算商品平均价格 | PASS | 5s |

**单步 TSR: 5/5 (100%)**

### JOIN 查询

| 查询 | 结果 | 耗时 |
|------|------|------|
| 各州客户数和平均订单金额 | PASS (27 行, SP: 40,925 客户) | 28s |

### 多步 Plan-and-Execute

| 查询 | 任务数 | 结果 | 耗时 |
|------|--------|------|------|
| 先找销售额最高三个品类 → 再查平均评分 | 2 | PASS (beleza_saude 3.37M, 评分 4.10) | 283s |

### 噪声陷阱测试

| 噪声类型 | 注入 | 说明 |
|----------|------|------|
| 软删除 (is_deleted) | 2% 行标记为删除 | 必须 WHERE is_deleted = 0 |
| UTC 时间戳 | 所有时间存为 UTC | 季度查询需 AT TIME ZONE |
| 枚举码 (order_status) | 整数 1-4 | 需 JOIN dim_order_status |
| 金额歧义 | 15% 订单有折扣 | orders.amount ≠ payments.amount (46.6% 差额) |

## 数据管线

| 表 | 行数 | 来源 |
|------|------|------|
| users | 99,441 | Olist 真实 |
| skus | 32,951 | Olist 真实 + Faker |
| categories | 71 | Olist 真实 |
| orders | 99,441 | Olist 真实 |
| order_items | 112,650 | Olist 真实 |
| payments | 103,886 | Olist 真实 |
| reviews | 99,224 | Olist 真实 + Faker CN |
| returns | 0 | (Olist 无退货数据) |
| return_reasons | 10 | Faker |
| page_views | 500,000 | Faker |
| add_to_cart | 80,000 | Faker |
| customer_service_tickets | 5,000 | Faker |
| dim_order_status | 4 | 手工 |
| **合计** | **~1,137,000** | |
