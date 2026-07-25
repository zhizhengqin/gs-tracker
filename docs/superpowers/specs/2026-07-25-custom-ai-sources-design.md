# 自定义信息源 + AI 预筛 — 设计文档

**日期**：2026-07-25
**状态**：已确认（用户逐节批准）
**范围**：P1（RSS 型自定义源 + AI 预筛）为本次实施目标；P2/P3 为后续阶段

---

## 背景与目标

用户（中国 A 股个人投资者）用本系统跟踪高盛观点来指导 A 股交易的"趋势和大方向"。现有 6 个内置信号源是硬编码的，用户无法自己扩展。用户原话诉求：

> "我的想法是可以自定义信息源，然后用 AI 去自动抓取，还有抓回来的信息 AI 也解读"

**已确认的需求决策**（brainstorming 阶段逐项确认）：

1. **源形态**：分阶段都要 —— P1: RSS 订阅源；P2: AI 读指定网页；P3: AI 按主题自动搜索
2. **内容范围**：每个源自己定 —— 添加源时选择"仅高盛相关"(`gs_only`) 或"全部保留"(`all`)
3. **AI 介入时机**：入库前 AI 预筛 —— 抓取时 AI 先判断"这条值不值得留"，垃圾直接不入库；单条解读仍按需点击（现状保留）

**方案**：统一自定义源框架（方案 A）。三种源类型共用一个配置框架和一条"抓取 → AI 预筛 → 入库"管道，分阶段交付。不引入重型浏览器内核（无 Playwright），Docker 镜像不膨胀。

---

## 总体架构

```
设置页表单 → 自定义源配置(sources_config in SQLite) → 每日情报流水线
                                                          │
                                    ┌─────────────────────┼──────────────────┐
                                 RSS 型(P1)            网页型(P2)          主题型(P3)
                                 抓订阅地址            抓网页+AI按          AI按主题
                                                      用户说明挑重点        自行搜索
                                    └────────────┬────┴─────────────────────┘
                                              AI 预筛器
                                       （批量判断 keep/drop；
                                        失败自动回退关键词过滤）
                                                  │
                                              信号入库 → 每日情报页
```

设计要点：

- 每个启用的自定义源是流水线上与内置源平等的一员，SSE 进度面板逐源亮灯
- AI 预筛是框架级组件，三种源类型共用；AI 不可用时有确定性回退路径
- P2/P3 只预留类型枚举和接口形状，本次不实现

---

## 数据模型

自定义源与内置源共存于现有 `app_settings` 表的 `sources_config` JSON 字段（不新建表）。自定义源条目结构：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 英文标识，小写字母/数字/下划线，全配置唯一 |
| `label` | string | 中文显示名（每日情报来源标签、筛选器勾选框） |
| `type` | string | `rss`（P1）/ `webpage`（P2 预留）/ `topic`（P3 预留） |
| `url` | string | RSS 或网页地址，必须 http(s) |
| `filter_policy` | string | `gs_only`（仅高盛相关）或 `all`（全部保留） |
| `instruction` | string | 一句话说明（仅 `webpage` 型使用，P1 不填） |
| `enabled` | bool | 启用开关 |
| `builtin` | bool | 自定义源恒为 `false` |
| `created_at` | string | ISO 时间戳 |

内置源条目保持不变（无 `type`/`url`/`filter_policy` 字段，视为 `builtin: true`）。

**校验规则**（API 层强制）：
- `name`：必填，匹配 `^[a-z0-9_]+$`，全配置唯一（含内置源名）
- `label`：必填，≤30 字
- `url`：必填，`http://` 或 `https://` 开头
- `type`：P1 阶段仅接受 `rss`
- `filter_policy`：缺省 `gs_only`

---

## 组件设计

### 1. CustomRssSource（`src/signals/custom_rss_source.py`，新增）

按源实例化的 RSS 抓取器。复用 `NewsSource` 的抓取/解析/清洗逻辑，按实例配置覆盖过滤行为：

- `filter_policy="gs_only"`：沿用现 news_source 的高盛关键词过滤（词边界正则）
- `filter_policy="all"`：跳过关键词过滤（HTML 清洗、时间窗口、去重仍然生效）
- 保留条目的强度：`gs_only` 沿用观点词 HIGH / 提及 MEDIUM；`all` 一律 LOW（避免淹没高盛情报，用户可按优先级筛选）
- `fetch_since(watermark)` 接口与现有源一致，水印按源名独立存储（`source_state` 表，key = 源 `name`）
- 抓取失败返回空列表，不抛异常（与现有源一致）

实现方式：抽出 `NewsSource` 中可复用的抓取/清洗为基类或组合，`CustomRssSource` 与 `NewsSource` 共用，避免复制粘贴。

### 2. AiTriage（`src/signals/ai_triage.py`，新增）

框架级 AI 预筛器，三种源类型共用：

```python
class AiTriage:
    def __init__(self, llm_config: dict, daily_budget: int = 20): ...

    async def triage(
        self, items: list[CandidateItem], source_label: str, filter_policy: str
    ) -> TriageResult  # keep 的条目 + 每项一句理由; fallback_used 标记
```

行为规则：

1. **批量**：候选条目按 ≤20 条一批，每批一次 LLM 调用。Prompt 含：用户投资背景（"中国 A 股投资者，关注高盛观点以判断市场趋势"）+ 源过滤策略 + 编号条目列表（标题+摘要前 150 字）；要求返回 JSON：`{"keep": [1, 4, 7], "reasons": {"1": "…"}}`
2. **预算**：每天调用上限（默认 20 次，`app_settings` 的 `ai_triage_daily_budget` 可调）；当日计数存 `app_settings`（键含日期，跨天自动重置）。预算耗尽 → 后续源直接走回退路径，不再调用
3. **回退**（`fallback_used=True` 并说明原因）：
   - LLM 超时（30s）/ 报错 / 返回 JSON 无法解析 → `gs_only` 源回退到现 news_source 关键词过滤；`all` 源回退为全保留
   - 预算耗尽 → 同上
4. **LLM 配置来源**：与现有 AI 解读一致 —— DB 默认模型优先，环境变量兜底（复用 `web._llm_client_kwargs` 的解析逻辑，抽到共用位置如 `src/llm_config.py`）
5. 预筛结果（keep/drop + 理由 + 是否回退）写入运行日志 `signal_runs.errors` 字段（JSON 扩展），供排障

### 3. 流水线集成（`src/main.py` 改动）

- `_build_daily_sources()` 扩展：内置源之后，为每个 `enabled` 的自定义源追加 `(name, CustomRssSource(...))`；SSE 进度面板自动逐源亮灯（现有机制）
- 抓取完成后、入库前插入预筛步骤：按源分组候选条目 → `AiTriage.triage()` → 仅 keep 条目进入评分/入库
- **预筛适用范围**：仅新闻类源（内置 `news` + 全部自定义源）。`8-K` / `13D/13G` / `research_view` 是权威一手来源，直接入库，不经 AI 丢弃
- AI 预筛的回退/预算事件作为独立 SSE 事件 `{"event": "triage_note", "source": ..., "note": ...}` 推送，前端进度面板显示黄灯提示
- `_all_rss_feeds()` 的旧合并逻辑移除（被 CustomRssSource 按源实例取代；内置 `news` 源行为不变）

### 4. 设置 API（`src/web.py` 新增端点）

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/settings/sources/custom` | 添加自定义源（校验规则见数据模型） |
| `PUT` | `/api/settings/sources/custom/{name}` | 编辑（label/url/filter_policy/enabled） |
| `DELETE` | `/api/settings/sources/custom/{name}` | 删除（仅限 `builtin=false`） |
| `POST` | `/api/settings/sources/test` | 测试源：抓取一次，返回 `{ok, count, sample_titles[:3]}` 或中文错误；不跑 AI、不入库 |

现有 `GET/PUT /api/settings/sources` 保持不变（前端启停开关继续用）。

### 5. 设置页 UI（`templates/dashboard.html` 改动）

- "信号源"区块下方新增"自定义信息源"区块：列表（label + 类型标签 + 过滤策略标签 + 启停状态 + 编辑/删除）+ "➕ 添加自定义源"表单（名称/标识/类型/地址/过滤策略单选 + 🔍 测试源 + 💾 保存）
- 类型下拉含 `网页地址`、`主题搜索` 选项但置灰，标注"即将上线"
- 每日情报页来源筛选器自动包含自定义源（读取 sources_config 动态生成勾选框，`srcClass()` 为未知源分配默认颜色）
- 进度面板支持 `triage_note` 事件的黄灯展示

---

## 错误处理

| 故障 | 系统行为 | 用户可见 |
|---|---|---|
| RSS 地址抓取失败 | 该源跳过，其他源照常 | 进度面板红灯 + 原因 |
| AI 超时/报错/JSON 乱码 | 该源回退关键词过滤（`all` 全保留） | 黄灯 "AI 预筛不可用，已用基础过滤" |
| AI 预算耗尽 | 后续源回退基础过滤 | 黄灯 "AI 预算已用完" |
| 测试源地址无效 | —（不入库） | 表单内中文错误提示 |
| 自定义源配置非法 | API 422 | 表单内中文错误提示 |

单源任何失败不得影响其他源和整体流水线（沿用现有 `_fetch_one` 隔离模式）。

---

## 测试策略

| 组件 | 测试内容 |
|---|---|
| CustomRssSource | 两种过滤策略行为、HTML 清洗、水印递增、抓取失败返回空 |
| AiTriage | 25 条分 2 批、JSON 乱回容错、预算上限截断、超时回退、跨天预算重置 |
| 流水线 | 自定义源出现在 SSE 事件流、`triage_note` 事件、单源失败隔离 |
| 设置 API | CRUD 全路径、name/url 校验、重复 name 拒绝、删内置源拒绝 |
| 测试源端点 | 活地址返回 count+标题、死地址返回中文错误、不入库 |

**回归要求**：现有 215 个测试保持全绿。

---

## 阶段划分

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1（本次实施） | 数据模型 + 设置 API + 设置页 UI + CustomRssSource + AiTriage + 流水线集成 + 测试源按钮 | 本 spec 实施目标 |
| P2 | `webpage` 型（httpx 抓正文 + 按 instruction 让 AI 提取要点）+ 预筛效果预览（测试源按钮展示 AI keep/drop） | 本 spec 仅留接口 |
| P3 | `topic` 型（AI 按主题自行搜索整理） | 本 spec 仅留类型枚举 |

## 不变更 / 非目标

- 内置 6 源的抓取逻辑不变（news_source 的高盛聚焦策略刚按用户反馈修好，保持）
- 单条 AI 解读、每日汇总报告的按需模式不变
- 不引入 Playwright/headless 浏览器；P2 网页型用 httpx + 正文提取
- 不做多用户/权限；不做自定义源的独立调度频率（统一跟随每日情报）
- 合规红线不变：AI 预筛只做相关性判断，不生成投资建议；解读类输出仍须署名来源
