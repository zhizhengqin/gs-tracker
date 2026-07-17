# GS-Tracker — 高盛动向情报系统

基于 GStack + Superpowers 双框架的 AI 原生金融情报系统。

## 核心价值

自动抓取 SEC 13F 季度持仓，叠加高盛研究报告、宏观策略、交易信号等多源信息，通过 Claude AI 推断高盛方向性意图，生成可视化 HTML 情报板。

> **重要说明**: 13F 数据有 45 天滞后，精确实时持仓无法公开获取。本系统通过多源间接信号推断动向，不构成投资建议。

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/yourname/gs-tracker.git
cd gs-tracker

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 和 SEC_USER_AGENT

# 5. 初始化数据库
python -c "from src.storage import init_db; init_db()"

# 6. 生成单份报告
python src/main.py --run-now

# 7. 启动 Web 服务
uvicorn src.web:app --reload
```

## 项目结构

```
gs-tracker/
├── src/          # 源代码
├── tests/        # 测试
├── deploy/       # Docker / Nginx / systemd 配置
├── docs/         # 设计文档与计划
├── data/         # SQLite 数据库和原始数据
├── output/       # HTML 报告和图表
├── templates/    # Jinja2 模板
└── scripts/      # 运维脚本
```

## 文档

- [完整方案](GS-Tracker-Complete-Scheme.md)
- [京东云部署设计](docs/superpowers/specs/2026-07-17-jdcloud-deployment-design.md)
- [CLAUDE.md](CLAUDE.md) — 项目上下文与开发规范

## 免责声明

本工具仅用于学习和信息参考，不构成任何投资建议。投资有风险，决策需谨慎。
