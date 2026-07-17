# GS-Tracker — 高盛动向情报系统

## 项目概述
- **名称**: GS-Tracker
- **技术栈**: Python 3.11, httpx, pandas, anthropic, jinja2, matplotlib, sqlite3, FastAPI, Docker
- **目标**: 自动抓取 SEC 13F 数据，AI 分析持仓变化，生成可视化报告，部署为京东云 Web 服务
- **架构**: 数据采集 → 数据处理 → AI 分析 → 报告生成 → Web 服务 → 通知推送

## 目录结构
```
gs-tracker/
├── src/              # 源代码
├── tests/            # 测试（镜像 src 结构）
├── docs/             # 设计文档、计划、审查报告
│   ├── superpowers/  # Superpowers specs/plans
│   ├── design/       # GStack 设计输出
│   ├── plan/         # GStack 工程计划
│   └── review/       # GStack 审查报告
├── deploy/           # Docker Compose / Nginx / systemd 配置
├── output/           # 生成的 HTML 报告和图表
├── data/             # 本地数据库和原始数据
├── templates/        # Jinja2 报告模板
└── scripts/          # 工具脚本
```

## 开发框架

**gstack 主框架 + Superpowers Build 阶段编码纪律**

- gstack 决定阶段：/office-hours → /plan-eng-review → /review → /qa → /ship
- Superpowers 约束 Build 质量：brainstorming → writing-plans → TDD → 完成前验证
- 任何 /review 前必须先测试；任何 /ship 前必须 /review 和 /qa

## 开发规范
- Python 3.11+，类型注解，PEP 8
- 异步用 httpx + asyncio
- 每个模块对应 tests/ 下的测试文件
- 标准 logging，参数化 SQL 防注入
- SEC EDGAR 请求必须带 User-Agent（含联系方式），否则 403
- API 密钥只从环境变量读取，禁止硬编码

## 关键依赖
- httpx, pandas, anthropic, jinja2, matplotlib, apscheduler
- fastapi, gunicorn, uvicorn
- pytest, pytest-asyncio, black, flake8, mypy

## 数据规范
- 13F value 单位为美元（XML 原始为千美元，需 ×1000）
- 季度格式: `YYYY-QN`，如 `2026-Q1`
- Goldman Sachs CIK: `0000886982`
- 13F 截止日: Q1(5/15), Q2(8/14), Q3(11/14), Q4(2/14)

## 常用命令
```bash
pytest -v
uvicorn src.web:app --reload
python src/main.py --run-now
docker compose -f deploy/docker-compose.yml up -d --build
```

## 沟通风格
- 我是技术小白，请用通俗语言解释
- 先做计划再写代码，不要直接开始实现
- 每完成一个模块，主动运行测试验证
- 遇到报错，先分析根因再修复，不要猜
- 优先使用 gstack 做阶段把关（/office-hours、/plan-eng-review、/review、/qa、/ship）
- 在 Build 阶段遵循 Superpowers 的 TDD、YAGNI、子代理隔离纪律
- 任何代码进入 /review 前，必须先经过测试验证
