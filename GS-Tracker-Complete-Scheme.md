# 高盛动向情报系统 (GS-Tracker) 完整方案
## 基于 GStack + Superpowers 双框架的 AI 原生软件工程实践

> **版本**: v3.0 | 2026-07-17  
> **作者**: AI Assistant + Garry Tan's GStack + Superpowers  
> **目标**: 从 0 到 1 打造高盛动向情报系统：整合 13F 季度持仓、研究报告、交易信号与宏观策略，辅助投资决策  
> **仓库**: https://github.com/garrytan/gstack

---

## 目录

1. [项目概述与价值主张](#一项目概述与价值主张)
2. [功能设计（完整版）](#二功能设计完整版)
3. [智能体架构设计](#三智能体架构设计)
4. [数据层设计](#四数据层设计)
5. [AI 分析引擎设计](#五ai-分析引擎设计)
6. [报告与可视化设计](#六报告与可视化设计)
7. [进阶迭代路线图](#七进阶迭代路线图)
8. [GStack + Superpowers 双框架指导手册](#八gstack--superpowers-双框架指导手册)
9. [实战开发记录](#九实战开发记录)
10. [部署与运维](#十部署与运维)
11. [附录](#十一附录)

---

## 一、项目概述与价值主张

### 1.1 项目背景

高盛（Goldman Sachs）是全球最大的投资银行之一，其季度 13F 持仓报告（截至 2026 年 Q1，持仓总价值约 **8,709 亿美元**，共 **6,431 个持仓标的**）是机构投资者和个人投资者关注的重要风向标。

然而，传统 13F 数据存在以下痛点：
- **数据滞后 45 天**：季度结束后 45 天内才提交
- **数据格式复杂**：XML 信息表，需要专业解析
- **不含空仓**：只披露多头持仓，看不到对冲策略
- **分析门槛高**：需要金融专业知识才能解读调仓信号
- **手动追踪低效**：每季度手动下载、对比、分析耗时数小时

### 1.2 为什么精确实时持仓不可获取？

很多用户的第一个问题是："能不能追踪高盛的实时持仓？" 答案是 **不能公开获取**，原因如下：

1. **监管不要求实时披露** — 13F 季度报告是监管机构（SEC）唯一强制公开的持仓文件，有 45 天滞后。
2. **Volcker Rule（沃尔克规则）** — 高盛作为银行控股公司，自营交易已大幅受限，其"持仓"大量是客户订单的对冲仓位，变化极快。
3. **做市商库存** — 高盛每天处理数千亿交易量，盘中持仓可能几分钟就翻转。
4. **商业机密** — 实时持仓泄露会直接影响其交易执行价格和市场竞争优势。

因此，GS-Tracker 的定位不是"复制高盛实时持仓"，而是构建一个 **多维度动向情报系统**：把 13F 季度持仓作为"基准仓位"，再叠加研究报告、交易信号、宏观策略、财报电话会议等间接信号，推断其方向性意图。

### 1.3 价值主张

**GS-Tracker** 是一个 AI 驱动的高盛动向情报系统，核心价值：

| 价值维度 | 传统方式 | GS-Tracker |
|----------|----------|------------|
| 数据获取 | 手动下载 XML，解析困难 | 自动抓取 13F + 研究报告 + 交易信号 |
| 分析深度 | 简单统计（前10大持仓） | AI 多源信号聚合、意图推断、行业轮动 |
| 报告生成 | Excel 手动整理 | 自动 HTML 可视化情报板 |
| 更新频率 | 每季度手动检查 | 季度持仓 + 实时/日频信号持续监控 |
| 信号聚合 | 单一数据源 | 13F + 研报 + 大宗交易 + 期权异动 + ETF 流向 |
| 决策辅助 | 盲跟持仓 | 多源置信度评分 + 风险提示 |

### 1.4 目标用户

1. **个人投资者**：跟踪聪明钱动向，辅助投资决策
2. **基金经理**：监控竞争对手持仓，发现行业趋势
3. **量化研究员**：获取结构化 13F 数据用于模型训练
4. **金融自媒体**：自动生成持仓分析内容
5. **宏观交易者**：跟踪高盛宏观策略观点和行业轮动信号

---

## 二、功能设计（完整版）

### 2.1 功能全景图

```
┌─────────────────────────────────────────────────────────────────┐
│                     GS-Tracker 动向情报全景图                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     多源信号采集层                        │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │   │
│  │  │ SEC 13F  │  │ 高盛研报  │  │ 大宗交易  │  │ 期权异动│ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │   │
│  │  │ ETF流向  │  │ 财报电话  │  │ 新闻舆情  │  │宏观策略 │ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     数据处理与聚合层                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │   │
│  │  │ 数据清洗  │  │ 季度对比  │  │ 信号对齐  │  │异常检测│ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      AI 分析层                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │   │
│  │  │ 持仓分析  │  │ 意图推断  │  │ 信号评分  │  │风险预警│ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     报告与输出层                        │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │   │
│  │  │ HTML情报板│  │ 信号看板  │  │ 数据导出  │  │ API接口 │ │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     通知与推送层                        │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐  │   │
│  │  │ 邮件   │  │ 飞书   │  │ 钉钉   │  │ Telegram   │  │   │
│  │  └────────┘  └────────┘  └────────┘  └────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     系统管理层                          │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐  │   │
│  │  │ 定时任务│  │ 配置管理│  │ 日志监控│  │ 数据备份   │  │   │
│  │  └────────┘  └────────┘  └────────┘  └────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**核心设计思想**：
- **13F 季度持仓** 是不可替代的"基准仓位"（100% 准确但滞后 45 天）
- **研究报告 / 宏观策略** 提供高可信度的方向性判断
- **交易信号 / 期权异动 / ETF 流向** 提供日频/实时验证
- **AI 信号评分引擎** 聚合多源信息，输出置信度和意图推断

### 2.2 核心功能模块

#### 模块 1: SEC 13F 数据抓取 (Data Fetcher)

**功能描述**:
- 自动从 SEC EDGAR 抓取指定机构（默认高盛）的最新 13F-HR 报告
- 解析 XML 信息表，提取持仓明细
- 支持增量更新（只抓取新季度数据）
- 支持多机构（可配置追踪多个 CIK）

**输入**: 
- 机构 CIK（Goldman Sachs: 0000886982）
- 季度标识（如 2026-Q1）

**输出**:
- 结构化 DataFrame（columns: nameOfIssuer, cusip, titleOfClass, value, shares, investmentDiscretion, votingAuthority）
- 原始 XML 文件（归档）

**技术实现**:
```python
# 核心接口
class SEC13FFetcher:
    def fetch_latest_holdings(self, cik: str = "0000886982") -> pd.DataFrame
    def fetch_historical_holdings(self, cik: str, quarters: List[str]) -> pd.DataFrame
    def parse_13f_infotable(self, xml_url: str) -> pd.DataFrame
    def get_filing_detail_url(self, filing_url: str) -> str
```

**数据来源**: SEC EDGAR 官方 API（免费）或 sec-api.io（付费，更稳定）

> **⚠️ 重要**: SEC EDGAR 要求所有请求必须包含 `User-Agent` 头，且建议包含联系方式，否则会被 403 拒绝。示例：
> ```python
> headers = {"User-Agent": "GS-Tracker your-email@example.com"}
> response = httpx.get(url, headers=headers)
> ```
> 另外，SEC 建议请求频率不要超过每秒 10 次，生产环境请加上指数退避重试。
citeweb_search:10#0

#### 模块 2: 季度持仓对比 (Quarter Comparison)

**功能描述**:
- 对比当前季度与上一季度的持仓变化
- 识别：新增持仓、清仓持仓、大幅增持、大幅减持
- 计算变化百分比和绝对值

**输出**:
- 变化清单（新增/清仓/增持/减持各 Top 20）
- 集中度变化（HHI 指数）
- 行业分布变化

#### 模块 3: AI 分析引擎 (AI Analyzer)

**功能描述**:
- 调用 Claude API 对持仓数据进行深度分析
- 生成多维度洞察报告

**分析维度**:
1. **持仓集中度分析**: 前10大占比、HHI 指数、行业分散度
2. **重点标的解读**: 前5大持仓的战略意义
3. **行业偏好**: 从持仓看高盛看好哪些板块
4. **调仓信号**: 季度变化中的前瞻性判断
5. **风险提示**: 集中度风险、流动性风险
6. **对散户的启示**: 可跟随的投资信号

**技术实现**:
```python
class GSAnalyzer:
    def analyze_holdings(self, holdings_df: pd.DataFrame) -> str  # 返回中文分析文本
    def compare_quarters(self, current_df: pd.DataFrame, previous_df: pd.DataFrame) -> str
    def generate_trading_signals(self, holdings_df: pd.DataFrame) -> str
    def analyze_sector_rotation(self, holdings_df: pd.DataFrame) -> dict
```

#### 模块 4: 新闻舆情监控 (News Monitor)

**功能描述**:
- 监控 Bloomberg、Reuters、CNBC、WSJ 等来源的高盛相关新闻
- 提取与持仓标的相关的新闻
- 用于辅助分析（如某只股票被增持的同时是否有利好消息）

**输入**: RSS 源列表、关键词（Goldman Sachs, 高盛, GS）
**输出**: 结构化新闻列表（标题、来源、时间、摘要、链接）

#### 模块 5: 报告生成 (Report Generator)

**功能描述**:
- 生成精美的 HTML 可视化报告
- 包含：持仓分布图、行业饼图、变化对比表、AI 分析文本

**报告组件**:
- 统计卡片（总持仓价值、标的数、集中度）
- 前15大持仓柱状图
- 持仓价值分布饼图
- 季度变化对比表
- AI 分析洞察（带格式化排版）
- 相关新闻列表
- 完整持仓明细表（前30）

**技术实现**:
- Jinja2 模板引擎
- Matplotlib 图表生成
- 响应式 CSS 样式

#### 模块 6: Web 服务 (Web Server)

**功能描述**:
- 提供浏览器可访问的报告列表页和单份报告页
- 支持 REST API 查询历史报告和持仓数据
- 生产环境通过 Nginx 反向代理对外服务

**技术实现**:
```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="GS-Tracker")

@app.get("/", response_class=HTMLResponse)
def list_reports() -> str:
    """返回报告列表 HTML"""
    ...

@app.get("/reports/{quarter}.html", response_class=HTMLResponse)
def get_report(quarter: str) -> str:
    """返回单季度报告 HTML"""
    ...

@app.get("/api/reports")
def api_reports() -> list:
    """返回报告元数据 JSON"""
    ...
```

**部署方式**: Gunicorn + Uvicorn Worker + Nginx

#### 模块 7: 通知推送 (Notifier)

**功能描述**:
- 报告生成后自动推送到指定渠道
- 支持：邮件（SMTP）、飞书（Webhook）、钉钉（Webhook）

**通知触发条件**:
- 新季度报告发布时（自动检测）
- 重大持仓变化（单只股票变化超过阈值，如 20%）
- 手动触发

#### 模块 8: 数据持久化 (Data Storage)

**功能描述**:
- SQLite 数据库存储历史持仓数据
- 支持按季度、按机构查询
- 支持数据导出（CSV、Excel、JSON）

**数据库 Schema**:
```sql
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY,
    cik TEXT NOT NULL,
    quarter TEXT NOT NULL,  -- e.g., "2026-Q1"
    nameOfIssuer TEXT,
    cusip TEXT,
    titleOfClass TEXT,
    value REAL,  -- 美元
    shares INTEGER,
    investmentDiscretion TEXT,
    votingAuthority TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE quarters (
    id INTEGER PRIMARY KEY,
    cik TEXT NOT NULL,
    quarter TEXT NOT NULL,
    total_value REAL,
    num_holdings INTEGER,
    filing_date TEXT,
    UNIQUE(cik, quarter)
);
```

#### 模块 9: 定时任务调度 (Scheduler)

**功能描述**:
- 自动检测新季度报告发布
- 13F 报告截止日期：每季度结束后 45 天
  - Q1: 5月15日前
  - Q2: 8月14日前
  - Q3: 11月14日前
  - Q4: 2月14日前
- 在截止日期后自动运行抓取和分析

**技术实现**:
- Python `schedule` 库或系统 `cron`
- 或 APScheduler（更灵活）

#### 模块 10: 高盛研究报告采集器 (GS Research Monitor)

**功能描述**:
- 采集高盛研究部公开报告、策略观点和行业轮动观点
- 关注高盛首席策略师（如 David Kostin）的 S&P 500 目标位和行业配置建议
- 提取个股评级、行业偏好、战术资产配置、风险警示

**数据源**:
- 高盛官网公开研究摘要
- 高盛研究部 RSS/媒体发布
- 第三方聚合（如 Seeking Alpha、Bloomberg、Reuters 转载）

**技术实现**:
```python
class GSResearchMonitor:
    def fetch_public_research(self) -> List[ResearchReport]
    def extract_views(self, report: ResearchReport) -> dict  # 行业/个股/观点
    def build_view_timeline(self) -> pd.DataFrame
```

#### 模块 11: 宏观策略追踪器 (Macro Strategy Tracker)

**功能描述**:
- 汇总高盛全球经济、市场观点和战术资产配置建议
- 跟踪利率路径、美联储政策预期、地缘政治风险报告
- 与 13F 持仓做交叉验证（例如：报告看好科技 → 13F 是否增持科技）

**输出**:
- 高盛宏观观点摘要
- 行业配置建议矩阵
- 与季度持仓的一致性/背离分析

#### 模块 12: 交易信号监控 (Trading Signal Monitor)

**功能描述**:
- 监控与高盛 13F 持仓相关的大宗交易（Block Trade）
- 识别相关股票的期权异常成交量
- 追踪核心 ETF（SPY、QQQ、GLD 等）资金流向

**数据源**:
- FINRA ADF 大宗交易数据（付费/半公开）
- CBOE / Unusual Whales 期权异动数据
- Bloomberg / ETF.com ETF 资金流向

**输出**:
- 持仓相关股票的大宗交易告警
- 期权异常开仓信号
- ETF 申赎流量与行业配置关联

**技术实现**:
```python
class TradingSignalMonitor:
    def fetch_block_trades(self, tickers: List[str]) -> pd.DataFrame
    def fetch_options_unusual_volume(self, tickers: List[str]) -> pd.DataFrame
    def fetch_etf_flows(self, etfs: List[str]) -> pd.DataFrame
```

#### 模块 13: 财报与电话会议摘要 (Earnings & Call Analyzer)

**功能描述**:
- 解析高盛季度财报电话会议 transcript
- 提取 VaR 水平、FICC/Equities 业务方向、风险敞口变化
- 与 13F 持仓变化做关联分析

**数据源**:
- SEC 8-K / 10-Q / 10-K
- 财报电话会议 transcript（需订阅或公开来源）

**输出**:
- 管理层观点摘要
- 风险敞口变化趋势
- 业务板块方向性判断

#### 模块 14: 多源信号评分引擎 (Signal Scoring Engine)

**功能描述**:
- 聚合 13F 持仓变化、研究报告观点、交易信号、宏观策略、ETF 流向
- 对每只股票/行业输出综合评分和意图推断
- 支持可配置的权重和置信度校准

**评分模型**:
```
综合信号 = w1 × 13F持仓变化
         + w2 × 研究报告观点
         + w3 × 大宗交易方向
         + w4 × 期权异动
         + w5 × ETF资金流向
         + w6 × 宏观策略一致性
```

**输出**:
- 信号强度：bullish / neutral / bearish
- 置信度分数：0-1
- 信号依据溯源（可解释性）

**技术实现**:
```python
class SignalScoringEngine:
    def score_ticker(self, ticker: str, signals: dict) -> SignalScore
    def score_sector(self, sector: str, signals: dict) -> SignalScore
    def explain(self, score: SignalScore) -> str
```

#### 模块 15: 实时告警系统 (Real-time Alert)

**功能描述**:
- 13F 持仓股票出现大宗交易时告警
- 相关股票期权成交量异常时告警
- 高盛发布新的行业观点或宏观策略时告警
- ETF 资金流向与 13F 行业配置方向一致/背离时告警

**触发条件**:
- 大宗交易金额超过阈值（如 100 万美元）
- 期权成交量超过历史均值 N 倍
- 研究报告/宏观观点更新
- 综合信号评分变化超过阈值

**通知渠道**:
- 邮件、飞书、钉钉、Telegram

### 2.3 功能优先级矩阵

| 功能 | 优先级 | 阶段 | 说明 |
|------|--------|------|------|
| SEC 13F 数据抓取 | P0 | MVP | 核心功能，无此则无产品 |
| AI 持仓分析 | P0 | MVP | 核心价值，差异化竞争力 |
| HTML 报告生成 | P0 | MVP | 输出载体 |
| 季度持仓对比 | P0 | MVP | 基础分析能力 |
| Web 服务 | P1 | Phase 2 | 报告浏览器访问、API 接口 |
| 数据持久化 | P1 | Phase 2 | 支持历史查询和对比 |
| 高盛研究报告采集 | P1 | Phase 2 | 高价值免费信号，方向性判断 |
| 宏观策略追踪 | P1 | Phase 2 | 与 13F 交叉验证 |
| 新闻监控 | P1 | Phase 2 | 增强分析维度 |
| 邮件通知 | P1 | Phase 2 | 自动化闭环 |
| 飞书/钉钉通知 | P2 | Phase 3 | 国内用户友好 |
| 交易信号监控 | P2 | Phase 3 | 大宗交易/期权/ETF 流向 |
| 财报电话会议摘要 | P2 | Phase 3 | 验证管理层观点 |
| 多机构追踪 | P2 | Phase 3 | 扩展性 |
| 多源信号评分引擎 | P2 | Phase 3 | 信号聚合与意图推断 |
| 实时告警系统 | P2 | Phase 3 | 关键信号即时推送 |
| 日频/实时信号接入 | P3 | Phase 4 | 补充 13F 滞后性（非精确持仓） |

---

## 三、智能体架构设计

### 3.1 整体架构

```
┌────────────────────────────────────────────────────────────────────┐
│                        GS-Tracker 系统架构                          │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────┐                                                  │
│   │   用户层     │                                                  │
│   │  (你本人)   │                                                  │
│   └──────┬──────┘                                                  │
│          │                                                          │
│          ▼                                                          │
│   ┌──────────────────────────────────────────────────────────┐     │
│   │              gstack 产品/工程流程层（主框架）              │     │
│   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │     │
│   │  │ THINK   │ │  PLAN   │ │  BUILD  │ │ REVIEW  │        │     │
│   │  │/office- │ │/plan-   │ │(编码实现)│ │ /review │        │     │
│   │  │ hours   │ │eng-rev  │ │         │ │ /cso    │        │     │
│   │  └─────────┘ └─────────┘ └────┬────┘ └─────────┘        │     │
│   │  ┌─────────┐ ┌─────────┐ ┌────┴────┐ ┌─────────┐        │     │
│   │  │  TEST   │ │  SHIP   │ │ REFLECT │ │ /qa     │        │     │
│   │  │ /qa     │ │ /ship   │ │ /retro  │ │/land-and│        │     │
│   │  │/bench-  │ │/land-   │ │ /learn  │ │ -deploy │        │     │
│   │  │ mark    │ │deploy   │ │         │ │         │        │     │
│   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │     │
│   └──────────────────────────────────────────────────────────┘     │
│                              │                                      │
│          ┌───────────────────┘                                      │
│          ▼                                                          │
│   ┌──────────────────────────────────────────────────────────┐     │
│   │        Superpowers 编码纪律层（嵌入 gstack BUILD）         │     │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │     │
│   │  │Brainstorm│  │ Writing  │  │Subagent  │  │    TDD   │  │     │
│   │  │  -ing    │  │  Plans   │  │Driven Dev│  │RED-GREEN │  │     │
│   │  │(设计思考)│  │(任务拆解)│  │(子代理隔离)│  │-REFACTOR │  │     │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │     │
│   │  ┌──────────┐  ┌──────────┐                              │     │
│   │  │   YAGNI  │  │Verification│                            │     │
│   │  │(不做过度设计)│ │Before Completion│                      │     │
│   │  └──────────┘  └──────────┘                              │     │
│   └──────────────────────────────────────────────────────────┘     │
│                              │                                      │
│                              ▼                                      │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │                    业务逻辑层 (Business Logic)              │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │ SEC 13F  │  │ Quarter  │  │ GS       │  │ Macro    │ │    │
│   │  │ Fetcher  │  │ Compare  │  │ Research │  │ Strategy │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │ Trading  │  │ Earnings │  │ AI       │  │ Signal   │ │    │
│   │  │ Signal   │  │ & Call   │  │ Analyzer │  │ Scoring  │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │ Report   │  │ Real-time│  │ Notifier │  │ Storage  │ │    │
│   │  │ Generator│  │ Alert    │  │          │  │          │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   │  ┌──────────┐  ┌──────────┐                              │    │
│   │  │ News     │  │ Scheduler│                              │    │
│   │  │ Monitor  │  │          │                              │    │
│   │  └──────────┘  └──────────┘                              │    │
│   └──────────────────────────────────────────────────────────┘    │
│                              │                                      │
│                              ▼                                      │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │                    数据接入层 (Data Access)                 │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │ SEC      │  │ GS       │  │ Block    │  │ Options  │ │    │
│   │  │ EDGAR    │  │ Research │  │ Trade    │  │ Flow     │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │ ETF      │  │ Earnings │  │ RSS      │  │ Claude   │ │    │
│   │  │ Flows    │  │ Calls    │  │ Feeds    │  │ API      │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   │  ┌──────────┐  ┌──────────┐                              │    │
│   │  │ SQLite   │  │ External │                              │    │
│   │  │ DB       │  │ APIs     │                              │    │
│   │  └──────────┘  └──────────┘                              │    │
│   └──────────────────────────────────────────────────────────┘    │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

**框架关系说明**：
- **gstack 是主框架**：负责完整产品/工程流程，通过斜杠命令触发各阶段（Think → Plan → Build → Review → Test → Ship → Reflect）。
- **Superpowers 是嵌入在 gstack Build 阶段的编码纪律**：自动约束如何高质量地完成编码实现，包括先规划再实现、TDD、子代理隔离、YAGNI、完成前验证。
- **两者不是并列关系，而是主从嵌套**：gstack 决定"做什么阶段"，Superpowers 决定"Build 阶段怎么高质量完成"。

**具体分工**：

| 层级 | 框架 | 主要职责 |
|------|------|----------|
| **产品/工程流程层** | **gstack** | 阶段把关：需求澄清、架构锁定、代码审查、浏览器 QA、安全审计、发布部署、周期复盘 |
| **编码纪律层** | **Superpowers** | 实现规范：设计思考、任务拆解、子代理隔离、TDD、YAGNI、完成前验证 |
| **执行原则** | **gstack + Superpowers** | gstack 触发 Build 阶段后，Superpowers 自动约束该阶段的实现质量 |

### 3.2 模块间交互设计

```
用户输入: "分析高盛最新持仓"
    │
    ▼
[Agent Orchestrator] 接收指令
    │
    ├──→ /office-hours (如果需要澄清需求)
    │
    ├──→ [Data Fetcher] 抓取最新 13F
    │       ├──→ SEC EDGAR API
    │       ├──→ 解析 XML
    │       └──→ 存入 SQLite
    │
    ├──→ [Quarter Compare] 对比上一季度
    │       ├──→ 读取 SQLite 历史数据
    │       └──→ 计算变化
    │
    ├──→ [News Monitor] 获取相关新闻
    │       ├──→ RSS 聚合
    │       └──→ 关键词过滤
    │
    ├──→ [AI Analyzer] 生成分析
    │       ├──→ 构建 prompt
    │       ├──→ 调用 Claude API
    │       └──→ 解析返回文本
    │
    ├──→ [Report Generator] 生成报告
    │       ├──→ Jinja2 模板渲染
    │       ├──→ Matplotlib 图表
    │       └──→ 输出 HTML
    │
    ├──→ [Notifier] 推送通知
    │       ├──→ 邮件 SMTP
    │       └──→ 飞书 Webhook
    │
    └──→ 返回报告路径给用户 / 通过 Web 服务访问
```

**两种使用模式**：
1. **手动模式**: 用户在 Claude Code 中输入"分析高盛最新持仓"，完成分析后返回报告路径。
2. **自动模式（生产）**: APScheduler 每季度自动触发完整流程，生成的报告通过 Nginx + FastAPI 对外提供 Web 访问。

**多源信号聚合流程示例**：

```
数据源层
    │
    ├──→ [SEC EDGAR] 13F 季度持仓（基准仓位）
    ├──→ [GS Research] 高盛研报观点（方向性判断）
    ├──→ [Block Trade] 大宗交易数据（交易动向）
    ├──→ [Options Flow] 期权异常成交量（波动率/方向押注）
    ├──→ [ETF Flows] ETF 申赎资金流向（行业配置）
    └──→ [Earnings Calls] 财报电话会议摘要（管理层观点）
            │
            ▼
    [Signal Scoring Engine] 聚合多源信号
            │
            ├──→ 对齐时间窗口
            ├──→ 去重与冲突检测
            ├──→ 加权评分
            └──→ 生成 bullish/neutral/bearish 信号
            │
            ▼
    [AI Analyzer] 解释信号、生成投资洞察
            │
            ▼
    [Report Generator] 输出多源信号情报板
            │
            ▼
    [Real-time Alert] 推送关键信号变化
```

### 3.3 错误处理与重试机制

```python
# 数据抓取重试策略
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_with_retry(url: str) -> str:
    """SEC EDGAR 请求重试，指数退避"""
    response = httpx.get(url, headers=headers, timeout=30)
    if response.status_code == 429:  # Rate Limit
        raise RetryError("Rate limited")
    response.raise_for_status()
    return response.text

# 错误分类处理
try:
    holdings = fetcher.fetch_latest_holdings()
except NetworkError:
    # 网络问题，通知用户稍后重试
    notifier.send_alert("网络异常，SEC 数据抓取失败")
except ParseError:
    # XML 解析失败，尝试备用解析器
    holdings = fetcher.parse_with_fallback(xml_url)
except RateLimitError:
    # 触发频率限制，切换备用数据源（sec-api.io）
    holdings = backup_fetcher.fetch_latest_holdings()
```

---

## 四、数据层设计

### 4.1 数据源矩阵

| 数据源 | 类型 | 频率 | 成本 | 可靠性 | 用途 |
|--------|------|------|------|--------|------|
| SEC EDGAR 官方 | 原始 XML | 季度 | 免费 | 高 | 主要数据源 / 基准仓位 |
| sec-api.io | JSON API | 实时 | 付费 | 高 | 备用/增强 |
| 高盛公开研究 | 报告/PDF/HTML | 周/日 | 免费/半公开 | 中高 | 方向性判断 |
| 财报电话会议 | Transcript | 季度 | 免费/订阅 | 高 | 管理层观点验证 |
| FINRA ADF | 大宗交易 | 日频 | 付费 | 中 | 交易动向 |
| CBOE / Unusual Whales | 期权流 | 实时 | 付费 | 中 | 方向/波动率押注 |
| Bloomberg/ETF.com | ETF 资金流 | 日频 | 付费 | 中 | 行业配置推断 |
| Bloomberg RSS | 新闻 | 实时 | 免费 | 中 | 舆情监控 |
| Reuters RSS | 新闻 | 实时 | 免费 | 中 | 舆情监控 |
| 13F.info | 聚合数据 | 季度 | 免费 | 高 | 交叉验证 |
| WhaleWisdom | 可视化/估算 | 季度 | 免费 | 中 | 人工验证、持仓估算 |

**数据源优先级**：
1. **P0**: SEC EDGAR 13F（唯一免费且 100% 准确的持仓数据源）
2. **P1**: 高盛公开研究、财报电话会议（高价值、低成本）
3. **P2**: 大宗交易、期权流、ETF 资金流（需要付费订阅，信号噪音较大）
4. **P3**: 新闻舆情、WhaleWisdom 估算（辅助验证）

### 4.2 数据模型

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass
class Holding:
    """单条持仓记录"""
    cusip: str
    name_of_issuer: str
    title_of_class: str
    value: float  # 美元
    shares: int
    investment_discretion: str
    voting_authority_sole: int
    voting_authority_shared: int
    voting_authority_none: int

@dataclass
class QuarterlyReport:
    """单季度报告"""
    cik: str
    quarter: str  # "2026-Q1"
    filing_date: datetime
    period_of_report: datetime
    total_value: float
    num_holdings: int
    holdings: List[Holding]

@dataclass
class QuarterComparison:
    """季度对比结果"""
    quarter_current: str
    quarter_previous: str
    new_positions: List[Holding]
    sold_positions: List[Holding]
    increased_positions: List[dict]  # 含变化量
    decreased_positions: List[dict]
    concentration_change: float  # HHI 变化

@dataclass
class ResearchReport:
    """高盛研究报告"""
    title: str
    source: str
    published_at: datetime
    url: str
    summary: str
    sentiment: str  # bullish / neutral / bearish
    sectors: List[str]
    tickers: List[str]

@dataclass
class MacroView:
    """宏观策略观点"""
    published_at: datetime
    theme: str
    summary: str
    asset_classes: List[str]
    sectors: List[str]
    sentiment: str

@dataclass
class TradingSignal:
    """交易信号"""
    ticker: str
    signal_type: str  # block_trade / options_flow / etf_flow
    direction: str  # bullish / bearish / neutral
    volume: Optional[float]
    value: Optional[float]
    timestamp: datetime
    source: str

@dataclass
class SignalScore:
    """多源信号评分结果"""
    ticker: str
    sector: Optional[str]
    overall_sentiment: str  # bullish / neutral / bearish
    confidence: float  # 0-1
    contributing_signals: List[dict]
    explanation: str
```

### 4.3 数据库设计（SQLite）

> **设计说明**: 当前阶段使用 SQLite，零配置、便于本地开发和单服务器部署。当数据量增长、需要多实例读写或复杂查询时，可平滑迁移到 PostgreSQL（如京东云 RDS），迁移时只需替换 `DATABASE_URL` 并保持 SQLAlchemy/参数化查询接口不变。

```sql
-- 机构信息表
CREATE TABLE institutions (
    cik TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,  -- hedge_fund, mutual_fund, bank, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 季度报告元信息表
CREATE TABLE quarterly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik TEXT NOT NULL,
    quarter TEXT NOT NULL,  -- "2026-Q1"
    filing_date TEXT,
    period_of_report TEXT,
    total_value REAL,
    num_holdings INTEGER,
    xml_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cik, quarter)
);

-- 持仓明细表
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    cusip TEXT NOT NULL,
    name_of_issuer TEXT,
    title_of_class TEXT DEFAULT 'COM',
    value REAL,  -- 美元
    shares INTEGER,
    investment_discretion TEXT,
    voting_authority_sole INTEGER DEFAULT 0,
    voting_authority_shared INTEGER DEFAULT 0,
    voting_authority_none INTEGER DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES quarterly_reports(id)
);

-- 新闻表
CREATE TABLE news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT,
    link TEXT,
    published_at TEXT,
    summary TEXT,
    keywords TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 分析报告表
CREATE TABLE analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik TEXT NOT NULL,
    quarter TEXT NOT NULL,
    analysis_text TEXT,
    report_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 研究报告表
CREATE TABLE research_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT,
    url TEXT,
    published_at TEXT,
    summary TEXT,
    sentiment TEXT,  -- bullish / neutral / bearish
    sectors TEXT,  -- JSON array
    tickers TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 宏观策略观点表
CREATE TABLE macro_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at TEXT,
    theme TEXT,
    summary TEXT,
    asset_classes TEXT,  -- JSON array
    sectors TEXT,  -- JSON array
    sentiment TEXT,  -- bullish / neutral / bearish
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 交易信号表
CREATE TABLE trading_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    signal_type TEXT,  -- block_trade / options_flow / etf_flow
    direction TEXT,  -- bullish / bearish / neutral
    volume REAL,
    value REAL,
    timestamp TEXT,
    source TEXT,
    raw_data TEXT,  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 信号评分表
CREATE TABLE signal_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    sector TEXT,
    overall_sentiment TEXT,  -- bullish / neutral / bearish
    confidence REAL,
    contributing_signals TEXT,  -- JSON array
    explanation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引优化
CREATE INDEX idx_holdings_report ON holdings(report_id);
CREATE INDEX idx_holdings_cusip ON holdings(cusip);
CREATE INDEX idx_quarterly_cik_quarter ON quarterly_reports(cik, quarter);
CREATE INDEX idx_news_published ON news(published_at);
```

---

## 五、AI 分析引擎设计

### 5.1 分析 Pipeline

#### 5.1.1 持仓分析 Pipeline

```
输入: holdings_df (当前季度) + previous_df (上一季度) + news_items
    │
    ├──→ [统计计算层]
    │       ├──→ 集中度指标 (HHI, Top10占比, Top50占比)
    │       ├──→ 行业分布 (GICS 分类映射)
    │       ├──→ 市值分布 (Large/Mid/Small Cap)
    │       └──→ 变化指标 (新增/清仓/增持/减持)
    │
    ├──→ [Prompt 构建层]
    │       ├──→ 数据摘要 (前20大持仓 + 关键指标)
    │       ├──→ 变化摘要 (Top 10 变化)
    │       ├──→ 新闻摘要 (Top 10 相关新闻)
    │       └──→ 分析指令 (6 维度分析要求)
    │
    ├──→ [Claude API 调用层]
    │       ├──→ 模型选择: claude-sonnet-4-20250514 或更新版本（推荐 claude-sonnet-5-20251022）
    │       ├──→ 参数: temperature=0.3, max_tokens=4000
    │       └──→ 重试: 3 次指数退避
    │
    └──→ [结果解析层]
            ├──→ 文本清洗
            ├──→ Markdown 格式化
            └──→ 关键指标提取
```

#### 5.1.2 多源信号聚合 Pipeline

```
输入: holdings_df + research_reports + macro_views + trading_signals + etf_flows + earnings_summary
    │
    ├──→ [信号对齐层]
    │       ├──→ 按 ticker / sector / 时间窗口对齐
    │       ├──→ 去重（同一事件多次信号）
    │       └──→ 冲突检测（ bullish vs bearish）
    │
    ├──→ [信号评分层]
    │       ├──→ 13F 持仓变化权重
    │       ├──→ 研报观点权重
    │       ├──→ 交易信号权重
    │       ├──→ 宏观一致性权重
    │       └──→ 生成综合 confidence
    │
    ├──→ [Prompt 构建层]
    │       ├──→ 13F 持仓摘要
    │       ├──→ 研报观点摘要
    │       ├──→ 交易信号摘要
    │       ├──→ 宏观策略摘要
    │       └──→ 推断指令
    │
    ├──→ [Claude API 调用层]
    │       ├──→ 模型选择: claude-sonnet-4-20250514 或更新版本
    │       ├──→ 参数: temperature=0.2, max_tokens=3000
    │       └──→ 重试: 3 次指数退避
    │
    └──→ [结果解析层]
            ├──→ 提取 bullish/neutral/bearish 信号
            ├──→ 提取关键 ticker 和行业
            ├──→ 生成可解释说明
            └──→ 输出 SignalScore
```

### 5.2 Prompt 工程

#### 持仓分析 Prompt

```
你是一位顶级对冲基金分析师，专精于机构持仓分析。请基于以下数据提供专业分析。

【数据摘要】
- 报告日期: {date}
- 机构: Goldman Sachs (CIK: 0000886982)
- 总持仓标的数: {num_holdings}
- 总持仓价值: ${total_value}B
- 前10大持仓占比: {top10_concentration}%
- HHI 集中度指数: {hhi}

【前20大持仓】
{top20_table}

【季度变化摘要】
{changes_summary}

【相关新闻】
{news_summary}

请提供以下分析（用中文输出，专业但易懂）：

1. **持仓集中度分析**
   - 前10大持仓占比、HHI 指数解读
   - 与上一季度对比，集中度是上升还是下降？
   - 风险 implication

2. **重点标的解读**
   - 前5大持仓各自的战略意义
   - 为什么重仓这些股票？

3. **行业偏好**
   - 从持仓看 Goldman Sachs 看好哪些行业/板块
   - 与上一季度相比，行业配置有何变化？

4. **调仓信号**
   - 最重要的调仓信号（3个以内）
   - 这些调仓反映了什么宏观判断？

5. **风险提示**
   - 持仓集中度过高的风险
   - 潜在调仓方向
   - 45天滞后的影响

6. **对散户投资者的启示**
   - 从 Goldman Sachs 持仓中能获得什么投资信号？
   - 哪些标的值得关注？
   - 哪些需要谨慎？

要求：
- 每个观点尽量有数据支撑
- 总字数控制在 1500 字以内
- 适合有一定投资经验的读者
```

#### 多源信号聚合分析 Prompt

```
你是一位顶级对冲基金分析师，擅长从多个信息源推断机构投资意图。
请基于以下多维度信号，对 Goldman Sachs 的动向进行综合判断。

【13F 季度持仓摘要】
- 最近报告季度: {quarter}
- 总持仓价值: ${total_value}B
- 前10大持仓: {top10_table}
- 季度变化 Top 10: {changes_summary}

【高盛研究报告观点】
{research_summary}

【宏观策略观点】
{macro_summary}

【交易信号】
- 大宗交易: {block_trade_summary}
- 期权异常成交量: {options_flow_summary}
- ETF 资金流向: {etf_flow_summary}

【财报电话会议摘要】
{earnings_summary}

请输出以下内容（用中文，专业但易懂）：

1. **综合信号判断**
   - 对 Goldman Sachs 整体动向的判断：bullish / neutral / bearish
   - 置信度：0-1，并说明理由

2. **重点行业/板块**
   - 哪些行业被一致看好？
   - 哪些行业存在信号冲突？

3. **重点标的**
   - 哪些股票的多源信号最强？
   - 哪些股票的信号出现背离？

4. **风险与不确定性**
   - 信号中的矛盾点
   - 13F 滞后的影响
   - 做市商库存干扰

5. **对散户投资者的启示**
   - 值得关注的方向
   - 需要谨慎的方向

要求：
- 明确区分"事实"（13F 持仓）和"推断"（研报/交易信号）
- 对每个判断说明依据来源
- 总字数控制在 1200 字以内
```

### 5.3 分析结果结构化

```python
class AnalysisResult:
    """AI 持仓分析结果结构化"""
    summary: str  # 一句话摘要
    concentration_analysis: str
    top_holdings_analysis: str
    sector_preference: str
    trading_signals: str
    risk_warnings: str
    retail_insights: str
    key_tickers: List[str]  # 提到的关键股票代码
    sentiment: str  # bullish / neutral / bearish
    confidence: float  # 0-1


class MultiSourceAnalysisResult:
    """多源信号聚合分析结果结构化"""
    summary: str
    overall_sentiment: str  # bullish / neutral / bearish
    confidence: float
    strong_sectors: List[dict]  # 含方向和置信度
    conflict_sectors: List[dict]
    key_tickers: List[dict]  # 含信号强度和来源
    risk_notes: str
    retail_insights: str
    signal_sources: List[str]  # 用到的数据源
```

### 5.4 关于 LangChain / LangGraph 的技术选型

**当前阶段（Phase 1-3）：不使用 LangChain**

GS-Tracker 当前阶段的核心数据流是线性的：

```text
多源数据采集 → 数据清洗对齐 → 信号评分 → 调用 Claude API → 生成报告
```

这套流程使用现有技术栈（`httpx` + `pandas` + `anthropic` SDK）完全可以优雅实现：

| 需求 | 当前方案 | LangChain 是否必要 |
|------|----------|-------------------|
| 多源数据采集 | `httpx` / `feedparser` / 各数据源 SDK | 否 |
| 数据清洗与对齐 | `pandas` + Python 函数 | 否 |
| 多源信号加权评分 | Python 配置 + 数学计算 | 否 |
| 调用 Claude API | `anthropic` SDK | 否 |
| Prompt 管理 | Python 字符串 / Jinja2 模板 | 否（LangChain Prompt 模板是可选增强） |
| 输出结构化 | Pydantic / 正则提取 | 否（LangChain Output Parser 是可选增强） |

引入 LangChain 会增加依赖、学习成本和调试复杂度，但当前并不能显著简化开发或提升能力。

**未来阶段（Phase 4+）：考虑使用 LangGraph**

当系统进入智能化阶段，如果出现以下需求，LangChain 生态（特别是 **LangGraph**）值得考虑：

| 场景 | LangGraph 价值 |
|------|---------------|
| 多模型共识分析 | 同时调用 Claude、GPT-4、Gemini，再聚合判断 |
| 复杂 Agent 工作流 | 研究 Agent → 信号分析 Agent → 风险检查 Agent → 报告生成 Agent |
| RAG 增强分析 | 把历史报告、研报、财报构建向量库作为上下文 |
| 自然语言查询 | "高盛最近看好什么行业？" → 路由到不同工具/数据库 |
| 生产可观测性 | LangSmith 监控每个 Agent 步骤的成本、延迟、输出质量 |

**决策结论**：
- Phase 1-3 坚持使用原生技术栈，保持简单可控。
- Phase 4 若需要多模型、复杂 Agent 或 RAG，再评估引入 LangGraph。
- 即使引入，也应只使用 LangGraph 做工作流编排，而非整个 LangChain 全家桶。

---

## 六、报告与可视化设计

### 6.1 报告结构

```
高盛动向情报板 — 2026年Q1
├── 头部信息
│   ├── 报告标题
│   ├── 生成时间
│   └── 数据来源声明（13F + 研报 + 交易信号）
├── 综合信号概览（4 张卡片）
│   ├── 整体动向：bullish / neutral / bearish
│   ├── 综合置信度
│   ├── 信号源数量
│   └── 最后更新时间
├── 13F 持仓基准
│   ├── 总持仓价值 / 标的数
│   ├── 前15大持仓柱状图
│   └── 行业分布饼图
├── 多源信号对比表
│   ├── 信号源（13F / 研报 / 大宗交易 / 期权 / ETF）
│   ├── 方向
│   ├── 强度
│   └── 时间窗口
├── AI 持仓分析洞察
│   └── 6 维度分析文本
├── AI 多源信号推断
│   └── 重点行业、重点标的、风险与启示
├── 季度持仓对比（如有历史数据）
│   └── 变化分析文本
├── 研究报告摘要
│   └── 高盛最新观点列表
├── 交易信号列表
│   ├── 大宗交易
│   ├── 期权异动
│   └── ETF 资金流向
├── 相关新闻
│   └── 新闻列表（标题+摘要+链接）
├── 完整持仓明细
│   └── 前30大持仓表格
└── 免责声明
```

### 6.2 视觉设计规范

```css
/* 颜色系统 */
--primary: #1a237e;        /* 深蓝 - 主色 */
--primary-light: #3949ab;  /* 浅蓝 - 渐变 */
--accent: #ff9800;         /* 橙色 - 强调/警告 */
--success: #4caf50;        /* 绿色 - 正面信号 */
--danger: #f44336;         /* 红色 - 风险/负面 */
--bg: #f5f7fa;             /* 背景灰 */
--card: #ffffff;           /* 卡片白 */
--text: #333333;           /* 正文 */
--text-secondary: #666666; /* 次要文字 */

/* 字体 */
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

/* 布局 */
max-width: 1200px;
margin: 0 auto;
padding: 20px;

/* 卡片 */
border-radius: 10px;
box-shadow: 0 2px 8px rgba(0,0,0,0.08);

/* 图表 */
--chart-primary: #3949ab;
--chart-secondary: #5c6bc0;
--chart-tertiary: #7986cb;
```

### 6.3 图表类型

| 图表 | 用途 | 库 |
|------|------|-----|
| 水平柱状图 | 前15大持仓 | Matplotlib |
| 饼图 | 持仓价值分布 | Matplotlib |
| 堆叠面积图 | 行业分布变化 | Matplotlib/Plotly |
| 热力图 | 多季度持仓变化 | Seaborn |
| 桑基图 | 资金流向 | Plotly |

---

## 七、进阶迭代路线图

### Phase 1: 基础持仓追踪（第 1-2 周）

**目标**: 跑通 13F 核心流程，生成第一份持仓报告

- [x] SEC 13F 数据抓取（单机构：Goldman Sachs）
- [x] XML 解析为 DataFrame
- [x] AI 持仓分析（Claude API）
- [x] HTML 报告生成（含图表）
- [x] 命令行手动触发

**验收标准**:
- 运行 `python main.py` 能生成完整 HTML 报告
- 报告包含前10大持仓、AI 分析、图表
- 不依赖外部数据库，纯文件存储

### Phase 2: 自动化与情报基础设施（第 3-5 周）

**目标**: 自动化运行，数据持久化，接入公开免费信号

- [ ] SQLite 数据库持久化
- [ ] 季度持仓对比功能
- [ ] Web 服务（FastAPI + Nginx）
- [ ] 定时任务调度（APScheduler）
- [ ] 高盛研究报告采集器（公开来源）
- [ ] 宏观策略追踪器
- [ ] 邮件/飞书通知
- [ ] Docker 容器化
- [ ] 京东云 ECS 部署

**验收标准**:
- 数据库能存储多季度历史数据
- 浏览器可访问报告列表和单份报告
- 能自动对比当前季度与上一季度
- 能采集并展示高盛研报观点
- 部署到京东云并稳定运行

### Phase 3: 交易信号与告警（第 6-8 周）

**目标**: 接入日频/实时交易信号，实现关键事件告警

- [ ] 大宗交易监控（FINRA ADF 或付费数据源）
- [ ] 期权异常成交量监控
- [ ] ETF 资金流向监控
- [ ] 财报电话会议摘要
- [ ] 实时告警系统（持仓相关股票异动）
- [ ] 持仓变化预警（阈值触发）
- [ ] 多机构追踪（Berkshire, Bridgewater 等）

**验收标准**:
- 报告中包含交易信号列表
- 相关股票出现大宗交易/期权异动时自动告警
- 能追踪至少 3 个机构

### Phase 4: 多源信号聚合与智能化（第 9-12 周）

**目标**: AI 驱动的多源信号聚合与意图推断

- [ ] 多源信号评分引擎
- [ ] 信号冲突检测与可解释性
- [ ] 多源信号情报板
- [ ] 行业轮动趋势预测
- [ ] 与宏观经济指标关联分析
- [ ] 自然语言查询（"高盛最近看好什么行业？"）
- [ ] 智能问答机器人
- [ ] 评估引入 LangGraph（复杂 Agent / RAG / 多模型共识）

**验收标准**:
- 能对每只股票/行业输出 bullish/neutral/bearish 综合信号
- 能解释信号来源和权重
- 能回答自然语言问题
- 共识分析准确率 > 70%

### Phase 5: 产品化与商业化（第 13-16 周）

**目标**: 从脚本升级为可持续运营的产品

- [ ] 用户认证与权限管理
- [ ] 付费订阅模式（Tier 1/2/3）
- [ ] 信号 API 对外开放
- [ ] 移动端适配
- [ ] 社区功能（讨论、分享）
- [ ] 白标解决方案（为机构定制）

**验收标准**:
- 有注册/登录系统
- 有付费订阅流程
- 有稳定的 API 供第三方调用
- 社区能讨论信号和观点

---

## 八、GStack + Superpowers 双框架指导手册

### 8.1 双框架定位

本项目采用 **gstack 为主框架 + Superpowers 为编码纪律** 的混合模式：

| 维度 | gstack | Superpowers |
|------|--------|-------------|
| **定位** | 主框架：完整产品/工程流程 | 嵌入纪律：约束 Build 阶段实现质量 |
| **交互方式** | 手动调用 Slash 命令 | 自动触发 Skill |
| **核心职责** | Think / Plan / Review / Test / Ship / Reflect | Build 阶段的 TDD、规划、子代理隔离、YAGNI |
| **典型场景** | 需求澄清、架构锁定、代码审查、浏览器 QA、发布部署 | 任务拆解、先写测试、最小实现、完成前验证 |

**为什么这样结合？**

根据框架对比分析，这种组合最符合 GS-Tracker 的特点：

1. **gstack 覆盖完整产品流水线**
   - 从 0 到 1 的产品探索：`/office-hours`、`/plan-ceo-review`
   - 工程架构锁定：`/plan-eng-review`
   - 生产级代码审查：`/review`、`/cso`
   - 真实浏览器验证：`/qa`、`/browse`
   - 发布与部署：`/ship`、`/land-and-deploy`
   - 周期复盘：`/retro`、`/learn`

2. **Superpowers 强化 Build 阶段纪律**
   - `brainstorming` + `writing-plans`：确保编码前有明确设计
   - `test-driven-development`：强制 RED-GREEN-REFACTOR
   - `subagent-driven-development`：复杂任务用子代理隔离
   - `verification-before-completion`：每个任务完成前必须验证
   - `using-git-worktrees`：多任务并行时隔离工作区

3. **避免职责重叠**
   - gstack 的 `/office-hours` 和 `/plan-eng-review` 负责产品/工程决策
   - Superpowers 的 `brainstorming` 负责实现前的需求细化
   - gstack 的 `/review` 负责阶段把关
   - Superpowers 的 TDD 负责代码质量内建

**一句话总结**：
> **gstack 决定"做什么阶段"，Superpowers 决定"Build 阶段怎么高质量完成"。**

### 8.2 Superpowers 核心 Skill 速查表

#### 设计与规划

| Skill | 用途 | 使用时机 |
|-------|------|----------|
| `superpowers:brainstorming` | 把想法变成经过审批的设计文档 | 任何新功能/模块开始前 |
| `superpowers:writing-plans` | 把设计文档拆分为可执行的 bite-sized 任务 | 设计文档批准后 |
| `superpowers:executing-plans` | 在当前会话中按计划一步步执行 | 计划批准后_inline 执行 |
| `superpowers:subagent-driven-development` | 为每个任务派生子代理并行/串行执行 | 计划批准后_subagent 执行 |

#### 代码质量

| Skill | 用途 | 使用时机 |
|-------|------|----------|
| `superpowers:verification-before-completion` | 在标记任务完成前验证代码确实工作 | 每个任务完成前 |
| `superpowers:receiving-code-review` | 处理代码审查反馈 | 收到 review 后 |
| `superpowers:requesting-code-review` | 发起代码审查 | 功能开发完成后 |

#### 工程流程

| Skill | 用途 | 使用时机 |
|-------|------|----------|
| `superpowers:test-driven-development` | 先写测试再写实现 | 需要高可靠性模块 |
| `superpowers:systematic-debugging` | 系统性定位 bug 根因 | 遇到顽固 bug |
| `superpowers:finishing-a-development-branch` | 完成分支收尾、合并、部署 | 开发分支结束时 |
| `superpowers:using-git-worktrees` | 使用 git worktree 隔离并行工作 | 多任务并行时 |

### 8.3 GStack 23 个角色速查表

GStack 是 YC CEO Garry Tan 开源的 Claude Code 配置框架，通过 **23 个专家角色**（slash 命令）把 Claude Code 升级为"完整虚拟工程团队"。

**安装**（30 秒）：
```bash
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup
```

#### 思考阶段（Think）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/office-hours` | YC 创业导师 | "我想做 X，请用 6 个强制问题帮我理清需求" |
| `/plan-ceo-review` | CEO | "请从 CEO 视角审视这个方案，找出 10 星产品的隐藏机会" |
| `/plan-eng-review` | 工程经理 | "请锁定架构，画出数据流图，列出边界情况" |
| `/plan-design-review` | 高级设计师 | "请给每个设计维度打分，告诉我 10 分长什么样" |
| `/plan-devex-review` | 开发体验负责人 | "请评审开发者上手体验，找出摩擦点" |
| `/autoplan` | 自动规划 | "请自动运行 CEO→设计→工程评审流水线" |

#### 设计阶段（Design）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/design-consultation` | 设计合伙人 | "请帮我研究竞品，提出创意风险，生成产品 mockup" |
| `/design-shotgun` | 设计探索者 | "请生成 4-6 个变体，打开对比板让我挑选" |
| `/design-html` | 设计工程师 | "请将这个 mockup 转为生产级 HTML" |

#### 构建阶段（Build）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/careful` | 安全模式 | "请启用安全模式，警告破坏性命令" |
| `/freeze` | 编辑锁定 | "请锁定编辑范围到 src/ 目录" |
| `/guard` | 完全安全 | "请同时启用 careful 和 freeze" |
| `/unfreeze` | 解除锁定 | "请解除编辑锁定" |

#### 审查阶段（Review）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/review` | 资深工程师 | "请审查代码，找出生产环境隐患" |
| `/codex` | 第二意见 | "请用 OpenAI Codex 独立审查这个 diff" |
| `/cso` | 安全官 | "请运行 OWASP + STRIDE 威胁建模" |
| `/design-review` | 设计师+工程师 | "请审查设计实现，然后修复问题" |
| `/devex-review` | DX 测试员 | "请真实测试 onboarding 流程，计时上手时间" |

#### 测试阶段（Test）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/qa` | QA 负责人 | "请打开真实浏览器测试，发现 bug 并修复" |
| `/qa-only` | QA 报告员 | "请测试但不修改代码，只输出 bug 报告" |
| `/browse` | 浏览器 QA | "请用浏览器访问这个页面并截图" |
| `/open-gstack-browser` | 浏览器管理 | "请启动 GStack 浏览器，带侧边栏" |
| `/benchmark` | 性能工程师 | "请基准测试页面加载时间和 Core Web Vitals" |

#### 发布阶段（Ship）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/ship` | 发布工程师 | "请同步 main、运行测试、推送、开 PR" |
| `/land-and-deploy` | 发布工程师 | "请合并 PR、等待 CI、验证生产环境" |
| `/canary` | SRE | "请监控生产环境，检查控制台错误" |
| `/document-release` | 技术文档 | "请更新所有项目文档匹配最新代码" |

#### 复盘阶段（Reflect）

| 命令 | 角色 | 小白提示词 |
|------|------|------------|
| `/retro` | 工程经理 | "请运行本周复盘，统计贡献和测试健康度" |
| `/investigate` | 调试专家 | "请系统性调试，找到根因，3 次失败就停止" |
| `/learn` | 记忆管理 | "请记录这次学到的模式，供下次使用" |

### 8.4 双框架协作流程（推荐）

```
┌─────────────────────────────────────────────────────────────────┐
│                   GS-Tracker 推荐开发流程                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   THINK（gstack）                                                │
│   ├── /office-hours                                              │
│   │      → YC 式 6 个强制问题，验证产品方向                       │
│   │      → 输出：DESIGN.md                                       │
│   └── /plan-ceo-review                                           │
│          → CEO 视角挑战假设，寻找隐藏机会                         │
│                                                                  │
│   PLAN（gstack）                                                 │
│   ├── /plan-eng-review                                           │
│   │      → 锁定架构、数据流、错误路径、安全顾虑                   │
│   │      → 输出：ARCHITECTURE.md / 测试矩阵                       │
│   └── /plan-design-review（如需 UI）                             │
│          → 设计维度评分，避免 AI Slop                            │
│                                                                  │
│   BUILD（gstack 触发 + Superpowers 纪律约束）                     │
│   ├── superpowers:brainstorming                                  │
│   │      → 实现前细化需求，输出设计文档                           │
│   ├── superpowers:writing-plans                                  │
│   │      → 把设计拆分为 bite-sized 任务                          │
│   ├── superpowers:test-driven-development                        │
│   │      → RED → GREEN → REFACTOR                                │
│   ├── superpowers:executing-plans / subagent-driven-development  │
│   │      → 按任务写测试 → 写实现 → 验证 → 提交                   │
│   └── superpowers:verification-before-completion                 │
│          → 每个任务完成前必须验证通过                             │
│                                                                  │
│   REVIEW（gstack）                                               │
│   ├── /review                                                    │
│   │      → Staff Engineer 审查生产环境隐患                        │
│   └── /cso                                                       │
│          → OWASP + STRIDE 安全审计                               │
│                                                                  │
│   TEST（gstack）                                                 │
│   ├── /qa                                                        │
│   │      → 真实浏览器测试 SEC 页面、报告页面                      │
│   └── /benchmark                                                 │
│          → 页面加载性能基准测试                                  │
│                                                                  │
│   SHIP（gstack）                                                 │
│   ├── /ship                                                      │
│   │      → 同步 main、运行测试、推送、开 PR                       │
│   └── /land-and-deploy                                           │
│          → 合并 PR、等待 CI、部署、验证生产环境                   │
│                                                                  │
│   REFLECT（gstack）                                              │
│   ├── /retro                                                     │
│   │      → 统计贡献、测试健康度、学到什么                         │
│   └── /learn                                                     │
│          → 记录模式、更新 CLAUDE.md                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**关键原则**：
- **gstack 是方向盘**：决定每个阶段该做什么，由你主动调用斜杠命令触发。
- **Superpowers 是安全带**：在 Build 阶段自动约束实现质量，确保先规划、先测试、再实现。
- **阶段关口不能跳过**：任何代码进入 `/review` 前，必须经过 Superpowers 的 TDD 验证；任何 `/ship` 前，必须经过 `/review` 和 `/qa`。
- **复杂任务拆分子代理**：当某个 Superpowers 任务预计超过 10 分钟或涉及多个文件时，使用 `subagent-driven-development` 派生子代理独立执行，避免上下文污染。

### 8.5 项目目录结构（双框架风格）

```
gs-tracker/
├── .claude/
│   ├── skills/              # GStack 技能库（自动安装）
│   ├── CLAUDE.md            # 项目记忆（核心）
│   └── settings.json        # Claude Code 项目级设置（可选）
├── .mcp.json                # MCP 服务器配置（可选）
├── docs/
│   ├── superpowers/
│   │   ├── specs/           # Superpowers brainstorming 设计文档
│   │   └── plans/           # Superpowers writing-plans 执行计划
│   ├── design/              # GStack /office-hours 输出
│   ├── plan/                # GStack /plan-eng-review 输出
│   └── review/              # GStack /review 输出
├── src/                     # 源代码
│   ├── __init__.py
│   ├── data_fetcher.py      # SEC 13F 数据抓取
│   ├── analyzer.py          # AI 分析引擎
│   ├── quarter_compare.py   # 季度对比
│   ├── news_monitor.py      # 新闻监控
│   ├── reporter.py          # 报告生成
│   ├── notifier.py          # 通知推送
│   ├── storage.py           # 数据持久化
│   ├── scheduler.py         # 定时任务
│   ├── web.py               # FastAPI Web 服务与报告列表
│   └── main.py              # 主入口（CLI + 调度器）
├── tests/                   # 测试（镜像 src 结构）
│   ├── __init__.py
│   ├── test_data_fetcher.py
│   ├── test_analyzer.py
│   ├── test_reporter.py
│   ├── test_web.py
│   └── conftest.py          # pytest 共享配置
├── output/                  # 生成的报告
│   ├── reports/             # HTML 报告
│   └── charts/              # 图表文件
├── data/                    # 本地数据
│   ├── raw/                 # 原始 XML
│   └── db/                  # SQLite 数据库
├── deploy/                  # 生产部署配置
│   ├── docker-compose.yml   # Docker Compose 编排
│   ├── Dockerfile           # 应用镜像
│   ├── nginx.conf           # Nginx 反向代理配置
│   └── systemd/             # systemd 自启服务
├── scripts/                 # 工具脚本
│   ├── setup.sh             # 环境初始化
│   ├── run.sh               # 一键运行
│   └── backup.sh            # 数据备份脚本
├── templates/               # Jinja2 模板
│   ├── report.html          # 报告模板
│   └── index.html           # 报告列表页模板
├── .env.example             # 环境变量模板
├── .dockerignore
├── .gitignore
├── requirements.txt
├── pyproject.toml           # Python 项目配置
├── README.md
└── CHANGELOG.md
```

### 8.6 小白专用提示词模板

#### 模板 1: 从零开始新项目（Superpowers + GStack）

```
# 步骤 1: 创建项目目录
mkdir ~/gs-tracker && cd ~/gs-tracker
git init

# 步骤 2: 安装 gstack
Install gstack: run git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup

# 步骤 3: 配置团队模式
(cd ~/.claude/skills/gstack && ./setup --team) && ~/.claude/skills/gstack/bin/gstack-team-init required

# 步骤 4: 启动 Superpowers brainstorming
superpowers:brainstorming

请帮我设计 GS-Tracker 项目：
- 项目概述：自动抓取 SEC 13F 数据，AI 分析持仓变化，生成可视化报告
- 技术栈：Python 3.11, httpx, pandas, anthropic, jinja2, matplotlib, sqlite3
- 部署目标：京东云 ECS 4C16G，Docker Compose + Nginx

# 步骤 5: 工程评审
/plan-eng-review

请基于设计文档锁定技术方案：
1. 画出 ASCII 数据流图
2. 定义模块接口
3. 列出错误路径和测试矩阵
4. 标识安全顾虑（API 密钥、SEC 请求频率、容器权限）

# 步骤 6: 提交初始配置
git add .
git commit -m "init: project setup with gstack and superpowers"
```

#### 模板 2: 开发新功能（完整流程）

```
# 1. Superpowers: 设计思考
superpowers:brainstorming

我想开发 SEC 13F 数据抓取模块，功能包括：
1. 从 SEC EDGAR 自动抓取 Goldman Sachs 的最新 13F 报告
2. 解析 XML 信息表为 pandas DataFrame
3. 处理网络超时、频率限制等错误
4. 支持历史数据归档

# 2. GStack: CEO 与工程评审
/plan-ceo-review
"请基于设计文档做 CEO 评审：这是 10 星产品吗？最小可发布版本是什么？"

/plan-eng-review
"请锁定技术方案：数据流图、模块接口、错误路径、安全顾虑。"

# 3. Superpowers: 生成执行计划
superpowers:writing-plans

请基于已批准的设计文档，生成 bite-sized 实现计划，每个任务包含：
- 创建/修改的文件路径
- 测试代码
- 验证步骤
- 提交命令

# 4. Superpowers: 执行任务
superpowers:executing-plans

请按顺序执行计划中的任务，每个任务完成后运行测试验证。

# 5. GStack: 代码审查
/review

请审查 src/data_fetcher.py：
1. 检查生产环境隐患
2. 自动修复明显问题
3. 检查测试覆盖率
4. 对照设计文档检查一致性

# 6. GStack: QA
/qa

请测试数据抓取模块：
1. 用 /browse 访问 SEC EDGAR 网站
2. 验证 Goldman Sachs 13F 页面可访问
3. 测试 XML 解析逻辑
4. 验证错误处理（断网、超时、无效 XML）

# 7. GStack: 发布
/ship
"请执行发布：同步 main、运行测试、推送、开 PR。"

/land-and-deploy
"PR 已批准，请合并到 main，验证生产环境。"

# 8. 复盘
/retro
"请运行本次开发复盘：统计贡献、测试健康度、学到什么。"
```

#### 模板 3: 快速修复 Bug

```
superpowers:systematic-debugging

请系统性调查这个 bug：
- 症状：[描述现象]
- 复现步骤：[步骤]
- 预期行为：[应该发生什么]
- 实际行为：[实际发生什么]

请追踪数据流，测试假设，如果 3 次修复失败就停止并报告。
```

#### 模板 4: 安全审查

```
/cso

请对这个仓库运行安全审查：
1. OWASP Top 10 检查
2. STRIDE 威胁建模
3. 检查密钥泄露（API Key、密码、数据库连接串）
4. 检查注入漏洞（SQL、XML、命令、路径遍历）
5. 检查 Docker 与容器安全（非 root 运行、最小镜像、Secrets 管理）

只报告置信度 8/10+ 的问题，排除已知误报。
```

#### 模板 5: 部署到京东云

```
superpowers:writing-plans

请基于 docs/superpowers/specs/2026-07-17-jdcloud-deployment-design.md，
生成部署实施计划，包括：
1. 服务器初始化（Ubuntu 24.04、Docker、防火墙）
2. 编写 deploy/docker-compose.yml 和 deploy/nginx.conf
3. 配置 systemd 开机自启
4. 部署应用并验证 Web 访问
5. 配置定时任务和备份脚本

superpowers:executing-plans

请按顺序执行部署计划。
```

### 8.7 CLAUDE.md 模板（双框架 + 京东云部署）

```markdown
# GS-Tracker — 高盛动向情报系统

## 项目概述
- **名称**: GS-Tracker
- **技术栈**: Python 3.11, httpx, pandas, anthropic, jinja2, matplotlib, sqlite3, FastAPI, Docker
- **目标**: 自动抓取 SEC 13F 数据，AI 分析持仓变化，生成可视化报告，部署为京东云 Web 服务
- **架构**: 模块化数据采集 → 数据处理 → AI 分析 → 报告生成 → Web 服务 → 通知推送

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

本项目采用 **gstack 为主框架 + Superpowers 为 Build 阶段编码纪律** 的混合模式。

### gstack（主框架）

负责完整产品/工程流程，通过斜杠命令触发各阶段：

- **THINK**: `/office-hours` — 产品方向拷问，输出 DESIGN.md
- **PLAN**: `/plan-eng-review` — 架构锁定、数据流、测试矩阵
- **BUILD**: 编码实现（此阶段由 Superpowers 约束质量）
- **REVIEW**: `/review`, `/cso` — 代码审查与安全审计
- **TEST**: `/qa`, `/browse`, `/benchmark` — 真实浏览器与性能测试
- **SHIP**: `/ship`, `/land-and-deploy` — 发布、合并、部署、验证
- **REFLECT**: `/retro`, `/learn` — 复盘与知识沉淀

### Superpowers（Build 阶段编码纪律）

在 gstack 的 BUILD 阶段自动触发，约束实现质量：

- `superpowers:brainstorming` — 实现前细化需求，输出设计文档
- `superpowers:writing-plans` — 把设计拆分为 bite-sized 任务
- `superpowers:test-driven-development` — 强制 RED-GREEN-REFACTOR
- `superpowers:executing-plans` 或 `superpowers:subagent-driven-development` — 执行任务
- `superpowers:verification-before-completion` — 每个任务完成前验证

### 执行原则

- gstack 决定"做什么阶段"，Superpowers 决定"Build 阶段怎么高质量完成"。
- 任何代码进入 `/review` 前，必须经过 Superpowers 的 TDD 验证。
- 任何 `/ship` 前，必须经过 `/review` 和 `/qa`。

## 开发规范
- 所有代码遵循 PEP 8
- 使用类型注解（Type Hints）
- 异步操作优先使用 httpx + asyncio
- 每个模块必须有对应的测试文件
- 日志使用标准 logging 模块
- 数据库操作使用参数化查询（防 SQL 注入）
- SEC EDGAR 请求必须设置 `User-Agent`（含联系方式），否则会被 403
- API 密钥通过环境变量读取，禁止硬编码

## 关键依赖
- httpx: 异步 HTTP 请求（SEC EDGAR、Claude API）
- pandas: 数据处理和分析
- anthropic: Claude API 调用
- jinja2: HTML 模板渲染
- matplotlib: 图表生成
- apscheduler: 定时任务调度
- fastapi + gunicorn: Web 服务与 WSGI 服务器
- langgraph (Phase 4+ 可选): 复杂 Agent 工作流编排

## 环境变量
- ANTHROPIC_API_KEY: Claude API 密钥（必填）
- DATABASE_URL: 数据库路径，默认 `sqlite:///data/db/gs_tracker.db`
- REPORT_OUTPUT_DIR: HTML 报告输出目录，默认 `output/reports`
- SMTP_*: 邮件通知配置（可选）
- FEISHU_WEBHOOK: 飞书机器人（可选）
- DINGTALK_WEBHOOK: 钉钉机器人（可选）
- SEC_API_KEY: sec-api.io 备用数据源（可选）
- FINRA_API_KEY: 大宗交易数据（可选，付费）
- CBOE_API_KEY: 期权流数据（可选，付费）
- BLOOMBERG_API_KEY: ETF 资金流数据（可选，付费）
- SIGNAL_SCORING_WEIGHTS: 多源信号评分权重 JSON（可选）

## 数据规范
- 13F 数据单位: value 为美元（原始 XML 是千美元，需 ×1000）
- 季度标识格式: "YYYY-QN"（如 "2026-Q1"）
- 机构 CIK: Goldman Sachs = "0000886982"
- 13F 截止日期: Q1(5/15), Q2(8/14), Q3(11/14), Q4(2/14)

## 部署规范
- 生产环境使用 Docker Compose 部署在京东云 ECS
- Nginx 作为反向代理和静态文件服务器
- SQLite 数据通过命名卷持久化
- `.env` 文件不上传 git，生产环境通过宿主机挂载
- 推荐开启 ufw 防火墙、fail2ban、unattended-upgrades

## 沟通风格
- 我是技术小白，请用通俗语言解释
- 先做计划再写代码，不要直接开始实现
- 每完成一个模块，主动运行测试验证
- 遇到报错，先分析根因再修复，不要猜
- 优先使用 gstack 做阶段把关（/office-hours、/plan-eng-review、/review、/qa、/ship）
- 在 Build 阶段遵循 Superpowers 的 TDD、YAGNI、子代理隔离纪律
- 任何代码进入 /review 前，必须先经过测试验证

## GStack 技能
Use /browse from GStack for all web browsing. Never use mcp__claude-in-chrome__* tools.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /open-gstack-browser, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /pair-agent, /careful, /freeze,
/guard, /unfreeze, /gstack-upgrade, /learn.
```

---

## 九、实战开发记录

> 本节记录从 0 到 1 的真实开发过程，包含 Superpowers 设计实现与 GStack 评审发布的双框架协作，以及实际踩坑点。

### 9.1 项目初始化

**目标**: 搭建项目骨架，安装双框架，创建 CLAUDE.md

**执行命令**:
```bash
mkdir ~/gs-tracker && cd ~/gs-tracker
git init
```

**Claude Code 中**:
```
# 1. 安装 GStack
Install gstack: run git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup

# 2. 配置团队模式
(cd ~/.claude/skills/gstack && ./setup --team) && ~/.claude/skills/gstack/bin/gstack-team-init required

# 3. 创建 CLAUDE.md
请帮我创建项目的 CLAUDE.md，参考项目模板，适配 GS-Tracker：
- 技术栈 Python 3.11 + FastAPI + Docker
- 部署目标京东云 ECS
- 开发框架：gstack 为主框架负责完整流程，Superpowers 为 Build 阶段编码纪律

# 4. 提交
git add .
git commit -m "init: project setup with gstack and superpowers"
```

### 9.2 产品澄清（gstack /office-hours）

**Claude Code 中**:
```
/office-hours

我想开发一个"高盛动向情报系统"。
核心功能：从 SEC EDGAR 自动抓取高盛季度 13F 持仓报告，
叠加高盛研究报告、宏观策略、交易信号等多源信息，
用 Claude AI 推断其方向性意图，生成可视化 HTML 情报板，
部署到京东云作为长期 Web 服务，支持邮件和飞书通知。

请用 6 个强制问题帮我理清需求，然后生成设计文档。
```

**关键追问**:
1. "13F 数据有 45 天滞后，你接受这个延迟，还是也需要实时信号？"
2. "目标用户是谁？个人投资者、基金经理，还是你自己？"
3. "AI 分析要深度到什么程度？"
4. "通知触发条件是什么？"
5. "Web 服务形态是只读报告浏览，还是需要管理后台？"
6. "成功标准是什么？"

**输出**: 产品方向澄清后，再进入 Superpowers brainstorming 做实现前细化，最终设计文档保存到 `docs/superpowers/specs/YYYY-MM-DD-gs-tracker-design.md`

### 9.3 工程锁定（GStack /plan-eng-review）

**Claude Code 中**:
```
/plan-eng-review

请基于 Superpowers 设计文档，锁定技术方案：
1. 画出 ASCII 数据流图
2. 定义模块接口
3. 列出错误路径和测试矩阵
4. 标识安全顾虑（API 密钥、SEC 请求频率、Docker 权限）
```

**输出**: `docs/plan/eng-review.md`

### 9.4 Build 阶段实现计划（Superpowers writing-plans）

在 gstack 的 BUILD 阶段，由 Superpowers 自动生成实现计划并约束编码质量。

**Claude Code 中**:
```
superpowers:writing-plans

请基于 gstack 工程评审锁定的技术方案，生成 GS-Tracker 的 bite-sized 实现计划。
每个任务需要包含：文件路径、测试代码、验证步骤、提交命令。
要求遵循 TDD：先写失败测试，再写最小实现，最后重构。
优先实现：数据抓取、AI 分析、HTML 报告、Web 服务、京东云部署。
```

**输出**: `docs/superpowers/plans/YYYY-MM-DD-gs-tracker-plan.md`

### 9.5 构建（gstack BUILD + Superpowers TDD 纪律）

**Claude Code 中**:
```
superpowers:executing-plans

请按顺序执行 Superpowers 生成的实现计划。
严格遵守以下纪律：
1. 先写失败的测试（RED）
2. 写最小代码让测试通过（GREEN）
3. 重构优化（REFACTOR）
4. 每个任务完成后运行测试验证
5. 复杂任务（>10分钟或多文件）拆分为子代理独立执行
重点关注：
1. src/data_fetcher.py — SEC 13F 数据抓取（必须设置 User-Agent）
2. src/analyzer.py — AI 分析引擎
3. src/reporter.py — HTML 报告生成
4. src/web.py — FastAPI Web 服务与报告列表
5. src/scheduler.py — APScheduler 定时任务
6. deploy/docker-compose.yml + deploy/nginx.conf
```

### 9.6 代码审查（GStack /review）

**Claude Code 中**:
```
/review

请审查所有代码变更：
1. 检查生产环境隐患
2. 自动修复明显问题
3. 检查测试覆盖率
4. 对照设计文档检查一致性
5. 检查 .env 和密钥是否意外提交
```

### 9.7 QA 与发布（GStack /qa + /ship）

**Claude Code 中**:
```
/qa

请测试 GS-Tracker：
1. 用 /browse 访问 SEC EDGAR 网站，验证 Goldman Sachs 13F 页面可访问
2. 测试 XML 解析逻辑
3. 测试 Web 服务首页和报告页
4. 验证错误处理（断网、超时、无效 XML、API 密钥缺失）

/ship

请执行发布：同步 main、运行测试、推送、开 PR。
```

### 9.8 真实踩坑记录

#### 坑 1: SEC EDGAR 403 — 缺少 User-Agent

**现象**: `requests.get("https://www.sec.gov/...")` 返回 403
**原因**: SEC 要求所有请求必须包含 `User-Agent`，且建议包含联系方式
**修复**:
```python
headers = {
    "User-Agent": "GS-Tracker your-email@example.com"
}
response = httpx.get(url, headers=headers)
```

#### 坑 2: Docker 容器内 SQLite 数据丢失

**现象**: 容器重建后历史数据消失
**原因**: 数据写在容器内，没有挂载到宿主机
**修复**: docker-compose.yml 中使用命名卷或 bind mount
```yaml
volumes:
  - ./data:/app/data
  - ./output:/app/output
```

#### 坑 3: 定时任务在容器内时区不对

**现象**: APScheduler 按 UTC 运行，而不是北京时间
**修复**: Dockerfile 中设置 `TZ=Asia/Shanghai`，或在 docker-compose.yml 中挂载 `/etc/localtime`

#### 坑 4: Claude API 调用超时导致报告生成失败

**现象**: 大报告生成时偶尔超时
**修复**:
- 设置合理的 timeout（如 120 秒）
- 对 Claude API 调用做重试和降级（生成占位分析文本）
- 将报告生成拆分为"数据准备"和"AI 分析"两步

---

## 十、部署与运维

### 10.1 部署目标与服务器规格

- **云服务商**: 京东云
- **实例规格**: 4 核 16G / 100GB 通用型 SSD / 5Mbps 带宽 / 1000GB 月流量
- **操作系统**: Ubuntu Server 24.04 LTS (amd64)
- **部署方式**: Docker Compose + Nginx
- **应用形态**: 长期 Web 服务 + 后台定时任务

### 10.2 操作系统推荐

**推荐 Ubuntu Server 24.04 LTS**，理由：
1. 5 年长期支持，安全补丁稳定
2. Python 3.12 预装，apt 生态完善
3. Docker 官方仓库原生支持
4. GStack/Superpowers 社区示例多基于 Ubuntu

### 10.3 服务器初始化

```bash
# 1. SSH 登录后更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装基础工具
sudo apt install -y curl wget vim git ufw fail2ban logrotate unzip

# 3. 自动安全更新
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# 4. 配置防火墙（仅开放 22/80/443）
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 5. SSH 加固（可选但推荐）
sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

### 10.4 安装 Docker 与 Docker Compose

```bash
# 1. 卸载旧版本
sudo apt remove -y docker docker-engine docker.io containerd runc

# 2. 安装依赖
sudo apt install -y ca-certificates gnupg lsb-release

# 3. 添加 Docker 官方 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. 添加 Docker apt 源
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. 安装 Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 6. 把当前用户加入 docker 组
sudo usermod -aG docker $USER
newgrp docker

# 7. 验证
docker --version
docker compose version
```

### 10.5 项目部署

```bash
# 1. 克隆项目
mkdir -p /opt/gs-tracker
cd /opt/gs-tracker
git clone https://github.com/yourname/gs-tracker.git .

# 2. 创建环境变量文件
cp .env.example .env
vim .env
# 填入：
# ANTHROPIC_API_KEY=sk-ant-...
# DATABASE_URL=sqlite:///data/db/gs_tracker.db
# REPORT_OUTPUT_DIR=output/reports
# FEISHU_WEBHOOK=https://open.feishu.cn/...
# DINGTALK_WEBHOOK=https://oapi.dingtalk.com/...
# SMTP_HOST=smtp.example.com
# SMTP_USER=your-email@example.com
# SMTP_PASS=your-password
# SEC_API_KEY=xxx  # 备用数据源（可选）
# FINRA_API_KEY=xxx  # 大宗交易数据（可选，付费）
# CBOE_API_KEY=xxx  # 期权数据（可选，付费）
# BLOOMBERG_API_KEY=xxx  # ETF 资金流（可选，付费）

# 3. 创建数据目录
mkdir -p data/raw data/db output/reports

# 4. 启动服务
docker compose -f deploy/docker-compose.yml up -d --build

# 5. 查看日志
docker compose -f deploy/docker-compose.yml logs -f app
```

### 10.6 Docker Compose 配置

`deploy/docker-compose.yml`:
```yaml
services:
  app:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: gs-tracker-app
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
    env_file:
      - ../.env
    volumes:
      - ../data:/app/data
      - ../output:/app/output
      - ../templates:/app/templates
    networks:
      - gs-tracker
    command: gunicorn src.web:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

  scheduler:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: gs-tracker-scheduler
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
    env_file:
      - ../.env
    volumes:
      - ../data:/app/data
      - ../output:/app/output
      - ../templates:/app/templates
    networks:
      - gs-tracker
    command: python src/scheduler.py

  nginx:
    image: nginx:1.27-alpine
    container_name: gs-tracker-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ../output/reports:/usr/share/nginx/html/reports:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      # - ./ssl:/etc/nginx/ssl:ro  # 如果使用 HTTPS
    depends_on:
      - app
    networks:
      - gs-tracker

networks:
  gs-tracker:
    driver: bridge
```

### 10.7 Dockerfile

`deploy/Dockerfile`:
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

WORKDIR /app

# 安装系统依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY src/ ./src/
COPY templates/ ./templates/

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
```

### 10.8 Nginx 配置

`deploy/nginx.conf`:
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # 静态报告目录
    location /reports/ {
        alias /usr/share/nginx/html/reports/;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
        try_files $uri $uri/ =404;
    }

    # 首页：报告列表
    location = / {
        proxy_pass http://app:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API 与动态页面
    location /api/ {
        proxy_pass http://app:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 静态资源缓存
    location ~* \.(html|css|js|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 10.9 systemd 开机自启

创建 `/etc/systemd/system/gs-tracker.service`:
```ini
[Unit]
Description=GS-Tracker Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/gs-tracker
ExecStart=/usr/bin/docker compose -f deploy/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose -f deploy/docker-compose.yml down

[Install]
WantedBy=multi-user.target
```

启用：
```bash
sudo systemctl daemon-reload
sudo systemctl enable gs-tracker.service
sudo systemctl start gs-tracker.service
sudo systemctl status gs-tracker.service
```

### 10.10 HTTPS / SSL（可选）

如果有域名，推荐两种方式：

**方式 A：京东云免费 SSL 证书**
1. 在京东云控制台申请 SSL 证书
2. 下载 Nginx 格式证书到 `/opt/gs-tracker/deploy/ssl/`
3. 在 `deploy/nginx.conf` 中启用 443 监听和证书路径
4. 开放 ufw 的 443 端口

**方式 B：Let's Encrypt**
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 10.11 备份策略

创建 `scripts/backup.sh`:
```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/gs-tracker"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

cd /opt/gs-tracker
tar czf "$BACKUP_DIR/gs-tracker-backup-$DATE.tar.gz" data/ output/reports/ .env deploy/

# 保留最近 30 天备份
find "$BACKUP_DIR" -name "gs-tracker-backup-*.tar.gz" -mtime +30 -delete
```

加入 crontab：
```bash
# 每天凌晨 3 点备份
0 3 * * * /opt/gs-tracker/scripts/backup.sh >> /var/log/gs-tracker-backup.log 2>&1
```

### 10.12 监控与日志

| 操作 | 命令 |
|------|------|
| 查看应用日志 | `docker compose -f deploy/docker-compose.yml logs -f app` |
| 查看定时任务日志 | `docker compose -f deploy/docker-compose.yml logs -f scheduler` |
| 查看 Nginx 日志 | `docker compose -f deploy/docker-compose.yml logs -f nginx` |
| 手动触发分析 | `docker compose -f deploy/docker-compose.yml exec scheduler python src/main.py --run-now` |
| 重启服务 | `docker compose -f deploy/docker-compose.yml restart` |
| 更新部署 | `git pull && docker compose -f deploy/docker-compose.yml up -d --build` |

### 10.13 本地开发部署

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
# 编辑 .env，填入 ANTHROPIC_API_KEY

# 5. 初始化数据库
python -c "from src.storage import init_db; init_db()"

# 6. 运行 Web 服务（开发模式）
uvicorn src.web:app --reload --host 0.0.0.0 --port 8000
```

### 10.14 部署检查清单

- [ ] Ubuntu 24.04 LTS 已安装并更新
- [ ] Docker 和 Docker Compose 已安装
- [ ] ufw 仅开放 22/80/443
- [ ] fail2ban 已启用
- [ ] 项目代码已克隆到 /opt/gs-tracker
- [ ] `.env` 已配置且不包含在 git 中
- [ ] `docker compose up -d --build` 成功启动
- [ ] 浏览器访问 `http://<服务器IP>/` 能看到报告列表
- [ ] 手动触发 `--run-now` 能生成新报告
- [ ] systemd 服务已启用，重启后自动恢复
- [ ] 备份脚本已配置并测试


## 十一、附录

### 11.1 常用命令速查

```bash
# === Superpowers ===
superpowers:brainstorming              # 设计思考与方案审批
superpowers:writing-plans              # 生成 bite-sized 实现计划
superpowers:executing-plans            # 当前会话执行任务
superpowers:subagent-driven-development # 子代理执行任务
superpowers:verification-before-completion # 完成前验证
superpowers:systematic-debugging       # 系统性调试
superpowers:test-driven-development    # 测试驱动开发

# === GStack ===
/office-hours              # 产品澄清
/plan-ceo-review          # CEO 评审
/plan-eng-review          # 工程评审
/review                   # 代码审查
/qa [url]                 # 浏览器测试
/ship                     # 发布 PR
/land-and-deploy          # 合并部署
/retro                    # 周复盘
/cso                      # 安全审查
/careful                  # 安全模式
/freeze [path]            # 编辑锁定
/guard                    # 完全安全

# === Docker ===
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f app
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml exec scheduler python src/main.py --run-now

# === Claude Code ===
claude                    # 启动
claude /skills            # 查看技能
/skills                   # 同上

# === Git Worktree ===
git worktree list         # 查看 worktree
git worktree add ../wt    # 创建 worktree

# === Python ===
pytest -v                 # 运行测试
pytest --cov=src          # 覆盖率
black src/                # 格式化
flake8 src/               # 风格检查
mypy src/                 # 类型检查
```

### 11.2 资源链接

#### 框架与工具
- **GStack 仓库**: https://github.com/garrytan/gstack
- **Claude Code 文档**: https://docs.anthropic.com/claude-code
- **Superpowers 流程**: https://github.com/garrytan/gstack (相关 skill 随 Claude Code 加载)

#### 核心数据源
- **SEC EDGAR**: https://www.sec.gov/edgar/searchedgar/companysearch.html
- **sec-api.io**: https://sec-api.io（付费 API，更稳定）
- **13F.info**: https://13f.info（可视化参考）
- **WhaleWisdom**: https://whalewisdom.com（可视化参考、持仓估算）

#### 高盛研究与宏观
- **高盛全球投资研究部公开观点**: https://www.goldmansachs.com/intelligence
- **高盛 Marcus Insights / 市场观点**: https://www.goldmansachs.com/insights

#### 交易信号与另类数据
- **FINRA ADF**: https://www.finra.org/filing-reporting/alternative-display-facility
- **CBOE LiveVol**: https://livevol.cboe.com（期权数据）
- **Unusual Whales**: https://unusualwhales.com（期权异常流）
- **ETF.com**: https://www.etf.com（ETF 资金流）
- **Bloomberg Terminal / Refinitiv**: 机构级付费数据源

### 11.3 免责声明

本工具仅用于学习和信息参考，不构成任何投资建议。

**重要限制**:
- 13F 数据存在 45 天滞后，且不含空仓和非美股资产。
- 精确实时持仓无法公开获取，系统通过间接信号推断方向性意图，存在误判可能。
- 研究报告、交易信号、ETF 流向等数据可能受噪声、滞后、来源可靠性影响。
- 高盛作为做市商，其公开持仓大量是客户对冲仓位，不一定代表其方向性押注。

投资有风险，决策需谨慎。

---

*本方案基于 Garry Tan 开源的 gstack 框架（MIT 协议）、Superpowers 开发流程和 SEC 公开数据整理。*
