# GS-Tracker — 高盛动向情报系统

## 项目概述
- **名称**: GS-Tracker
- **技术栈**: Python 3.11, httpx, pandas, anthropic, jinja2, matplotlib, sqlite3, FastAPI, Docker
- **目标**: 自动抓取 SEC 13F 与多源每日情报（8-K/13D·13G/高盛研究/新闻/宏观/自定义源），AI 分析并生成每日情报日报，部署为京东云 Web 服务
- **架构**: 数据采集 → 数据处理 → AI 分析 → 报告生成 → Web 服务 → 通知推送

## 目录结构
```
gs-tracker/
├── src/              # 源代码（signals/ 为多源信号体系：聚合/评分/AI 预筛 + 各信号源）
├── tests/            # 测试（镜像 src 结构）
├── docs/             # 设计文档、计划、审查报告
│   ├── superpowers/  # Superpowers specs/plans
│   ├── gstack/       # GStack 设计/审查输出
│   └── plan/         # GStack 工程计划
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
- API 密钥只从环境变量或数据库（设置页 llm_models 表）读取，禁止硬编码

## 关键依赖
- httpx, pandas, anthropic, jinja2, matplotlib, apscheduler, feedparser
- fastapi, gunicorn, uvicorn
- pytest, pytest-asyncio, black, flake8, mypy

## 数据规范
- 13F value 单位为美元（SEC 2023 年起新规：XML 原始值已是美元，禁止再 ×1000；仅 2023 年前的历史申报为千美元）
- 季度格式: `YYYY-QN`，如 `2026-Q1`
- Goldman Sachs CIK: `0000886982`
- 13F 截止日: Q1(5/15), Q2(8/14), Q3(11/14), Q4(2/14)
- 信号去重指纹: 有 URL 按 (source,title,url)，无 URL 按 (source,title,日期)；同一 URL 跨天重现只更新原行，不产生新行
- 日期分组按北京时间（UTC+8）：`get_signals_by_date` 用 `DATE(published_at, '+8 hours')` 归组，日报"今日"判断同理，勿回退到 UTC

## 语言规范
- **所有用户可见的输出必须使用中文**：HTML 报告、通知消息、邮件/飞书/钉钉文案、Web 界面、CLI 提示
- **AI 分析输出（Claude API 返回）必须使用中文**：分析文本、信号解释、风险提示、投资建议
- **错误信息对用户展示时使用中文**，日志中可同时保留英文技术细节便于排查
- **代码内部**（变量名、函数名、注释、commit message、技术文档）保持英文

## 常用命令
```bash
pytest -v
uvicorn src.web:app --reload
python -m src.main --run-now
docker compose -f deploy/docker-compose.yml up -d --build
node scripts/verify_today_view.js http://127.0.0.1:8770 /tmp/verify  # 页面结构回归（另有 verify_mobile.js）
```

## API 端点
- 认证：`GET /login`（登录页）；`POST /api/auth/login`；`POST /api/auth/logout`；`GET /api/auth/me`。除 /login、/api/auth/login、/api/health 外所有页面与 API 需登录（HttpOnly Cookie 会话，7 天）；`/api/settings/**` 仅管理员（内置 gsadmin/admin123 首次启动自动创建）
- 用户管理（管理员）：`GET/POST /api/settings/users`；`PUT/DELETE /api/settings/users/{username}`（gsadmin 不可删除/降角色，改密码或角色会使该用户所有会话失效）
- 季度/报告：`GET /api/signals/{quarter}`（404=该季度未跑过，422=格式错误）；`GET /api/quarters/comparison`；`GET /api/reports`；`GET /reports/{quarter}.html`；`GET /api/health`
- 每日情报：`GET /api/signals/recent?days=N`；`GET /api/signals/date/{date}`；`POST /api/signals/{signal_id}/analyze` + `GET /api/signals/{signal_id}/analysis`；`GET /api/daily-report/{date}`（无缓存则自动生成）；`POST /api/daily-report/{date}/regenerate`（强制重生成）；`POST /api/quarter-insight/{quarter}/regenerate`（季度洞察重生成）
- 流水线：`POST /api/pipeline/run`（季度对账）；`POST /api/pipeline/run-daily`；`GET /api/pipeline/run/stream` 与 `GET /api/pipeline/run-daily/stream`（SSE 实时进度）；`GET /api/pipeline/status`、`GET /api/pipeline/run-daily/status`
- 设置：`GET/PUT /api/settings`；`GET/POST/DELETE /api/settings/llm-models` + `POST .../llm-models/test` + `PUT .../llm-models/{model_id}/default`；`GET/PUT /api/settings/sources` + 自定义源 `POST/PUT/DELETE .../sources/custom[/{name}]` + `POST .../sources/test`
- 信号由流水线写入 `signals` / `signal_runs` 表（WAL 模式），日报缓存于 `daily_reports` 表；仪表盘信号页走 API 不再解析 HTML

## 沟通风格
- 我是技术小白，请用通俗语言解释
- 先做计划再写代码，不要直接开始实现
- 每完成一个模块，主动运行测试验证
- 遇到报错，先分析根因再修复，不要猜
- 优先使用 gstack 做阶段把关（/office-hours、/plan-eng-review、/review、/qa、/ship）
- 在 Build 阶段遵循 Superpowers 的 TDD、YAGNI、子代理隔离纪律
- 任何代码进入 /review 前，必须先经过测试验证
