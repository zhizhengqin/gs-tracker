# BridgeIQ 金桥智讯 — 多机构动向情报系统

基于 GStack + Superpowers 双框架的 AI 原生金融情报系统（原 GS-Tracker，已升级为多机构平台）。

## 核心价值

自动追踪**高盛、摩根大通**等外资机构的公开动作：SEC 13F 季度持仓、8-K/13D·13G 申报、机构研究观点、相关新闻、宏观指标，再加上与 A 股直接相关的 **QFII 持仓**和**北向资金**数据。AI 预筛去重后生成每日中文情报日报与可视化仪表盘，手机和电脑浏览器均可使用。

当两家机构同时覆盖同一标的时，系统自动标记**交叉信号**并提升优先级，支持一键 **AI 交叉解读**（共识 / 分歧对比）。

> **重要说明**: 13F 数据有 45 天滞后，精确实时持仓无法公开获取。本系统通过多源间接信号推断动向，不构成投资建议。

## 功能特性

- 🏦 **多机构追踪**：高盛 + 摩根大通独立情报流，左侧栏一键切换「全部 / 单家机构」，选中单家机构时下方显示近 7 天统计
- 📡 **每日情报**：今日视图置顶 AI 日报；信号带机构标签；更早情报折叠收纳；历史日期可回溯
- 🔀 **交叉信号**：跨机构覆盖同一标的自动升级标记，AI 交叉解读对比两家观点的共识与分歧
- 🇨🇳 **A 股数据**：QFII 持仓披露 + 沪深港通北向资金宽度数据，外资 A 股动向直接可见
- 🤖 **AI 解读**：单条信号一键中文解读（带缓存）；日报由流水线自动生成，新情报入库后自动提示可一键重新生成
- ⚙️ **设置页**：大模型管理（Anthropic 兼容接口）、信号源开关、自定义网页/主题源（AI 预筛）
- 📱 **手机适配**：汉堡抽屉导航，全部功能可在手机浏览器使用
- 🔄 **流水线可视化**：每日情报与季度对账均支持 SSE 实时进度面板，逐信号源状态与结果汇总

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/zhizhengqin/gs-tracker.git
cd gs-tracker

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env：Kimi 填 ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN（或官方 ANTHROPIC_API_KEY）；
# 必填 SEC_USER_AGENT（含联系邮箱）；宏观指标源可选 FRED_API_KEY

# 5. 初始化数据库
python -c "from src.storage import init_db; init_db()"

# 6. 生成单份报告
python -m src.main --run-now

# 7. 启动 Web 服务
uvicorn src.web:app --reload
```

## 项目结构

```
gs-tracker/
├── src/          # 源代码（signals/ 为多源信号体系）
├── tests/        # 测试
├── deploy/       # Docker / Nginx / systemd 配置
├── docs/         # 设计文档与计划
├── data/         # SQLite 数据库和原始数据
├── output/       # HTML 报告和图表
├── templates/    # Jinja2 模板
└── scripts/      # 运维脚本
```

## 文档

- [部署手册（小白版）](DEPLOY.md) — 京东云从零部署 + 故障排查
- [AGENTS.md](AGENTS.md) — 项目上下文与开发规范
- [京东云部署设计](docs/superpowers/specs/2026-07-17-jdcloud-deployment-design.md)
- [完整方案](GS-Tracker-Complete-Scheme.md) — 原始方案（历史文档）

## 免责声明

本工具仅用于学习和信息参考，不构成任何投资建议。投资有风险，决策需谨慎。
