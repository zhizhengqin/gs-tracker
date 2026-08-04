# 工程计划：JPM 季度报告（13F 持仓）

## 目标
季度报告页支持机构切换：选摩根大通时展示 JPM 的 13F 持仓、AI 分析、季度报告，与高盛视图完全独立。

## 实施变更
1. `analyzer.py`：GSAnalyzer 构造函数加 `institution_label`（默认"高盛(Goldman Sachs)"），AI 提示词使用它
2. `reporter.py` + `report.html`：`generate_report` 加 `institution_id/institution_label`；模板标题参数化；JPM 报告输出到 `output/reports/jpm/{quarter}.html`（GS 保持原路径兼容）
3. `main.py`：`run_pipeline_stream(institution_id="gs")`——从 institutions 表取 CIK/显示名，参数化 fetcher/analyzer/8-K 源/报告器
4. `web.py`：
   - `/api/holdings/{quarter}?institution=` 按机构解析 CIK（默认 GS）
   - `/api/reports?institution=` 列出对应机构报告
   - 新增 `/reports/{institution}/{quarter}.html` 路由（机构 id 白名单校验）
   - `POST /api/pipeline/run` + SSE stream 加 institution 参数
5. `dashboard.html`：季度报告 Tab 加机构切换；JPM 无报告时显示"尚未生成"空状态

## 明确不做
- JPM 季度信号聚合（季度管道里的 8-K/news 信号面板首期留空，每日管道已覆盖 JPM）
- quarter-insight / ticker-profiles 的 JPM 版（前端对 JPM 隐藏这两个面板）
- 重命名 GSAnalyzer 类（只加参数，避免大范围 ripple）

## 测试计划
- analyzer/reporter 机构标签参数化单测
- `/api/holdings` institution 参数测试（未知机构 422）
- `/api/reports?institution=jpm` 子目录列表测试
- 全量回归 + 浏览器验证双机构季度页切换
