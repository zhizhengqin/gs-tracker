# 机构详情页（机构档案）

日期: 2026-08-04  状态: 进行中  方法: Superpowers TDD

## 目标
点选某个机构后，可以看到这个机构的完整档案视图：基本信息、数据源状态、
最新季度报告、近 7 天情报、以及它参与的跨机构交叉信号。
首页的机构切换是"过滤器"，机构详情页是"档案"。

## API（先写测试，红→绿）
`GET /api/institutions/{inst_id}/overview`
- 200: { institution, latest_report, stats: {signals_7d, high_7d, last_signal_at},
        recent_signals(7天), cross_signals(30天, 跨机构) }
- 422: 未知机构

## 前端
- 机构选择区加「详情 ›」入口，打开当前选中机构的档案视图
- 档案视图渲染：机构头部（名称/CIK/数据源开关状态）、统计条、最新季度报告卡片、
  近 7 天情报卡片（复用 renderSignalCard + addAiToggles）、交叉信号区

## 测试
- web: overview 端点 200/422、字段结构、只含本机构信号、交叉信号过滤
- 复用现有 storage 函数，不新增 SQL

## 不做
- 机构自定义封面/Logo、编辑机构信息（设置页已有机构管理）
- 北向资金数据源优化（等用户定提供商）
