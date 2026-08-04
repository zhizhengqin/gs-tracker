# 跨机构 AI 分歧解读（Phase 3 核心）

日期: 2026-08-04  状态: 进行中

## 目标
当高盛和摩根大通在 7 天窗口内覆盖同一标的（交叉信号）时，
用户可一键生成 AI 对比解读：两家观点的一致点、分歧点、对 A 股的启示。
分歧才是信号 —— 这是多机构平台的核心差异化价值。

## 现状
- 规则层已完成：scorer 打 cross_institutional 标记 + 强度 +1 级，前端显示"跨机构共识"徽章和 ↔ 交叉引用标题
- 日报提示词已含跨机构一致/分歧段落
- 缺的：针对单条交叉信号的逐条 AI 深度对比

## 方案
1. storage: 新表 `cross_analysis(signal_id PK, analysis_text, generated_at)`；
   新增 `get_signal_by_id`、`get_signals_in_range`（复用行转换）
2. 新模块 `src/cross_analysis.py`（契约对齐 signal_analysis.py）：
   - `find_counterparts(signal, candidates)`: 不同真实机构、共享 ≥1 公司、排除机构自指词
   - `generate_cross_analysis(signal_id)`: 无对手方→提示文本（不缓存）；
     LLM 成功→合规检查→缓存；失败→不缓存可重试
3. web: `POST/GET /api/signals/{id}/cross-analysis`（模式同现有 /analyze）
4. 前端: "跨机构共识"信号卡片上显示「AI 交叉解读」按钮，结果渲染在交叉引用下方

## 测试
- storage: 新表读写、get_signal_by_id、范围查询
- cross_analysis: find_counterparts 纯函数用例（机构自指排除、大小写、窗口过滤）；生成路径 mock LLM
- web: 端点委托、404

## 不做（YAGNI）
- 管道自动生成交叉解读（交叉信号目前稀有，手动点击即可；量大后再加）
- 分歧方向的量化打分
