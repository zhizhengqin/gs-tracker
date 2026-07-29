# GS-Tracker · 现代杂志风设计系统

> 适用范围：登录页、每日情报、季度报告、设置页、使用指南全部后台界面。

## 1. 设计理念

将金融情报后台重新包装为一份「每日出版的编辑杂志」。强调：

- **可读性优先**：大标题、清晰层次、充足留白；
- **编辑质感**：衬线标题 + 无衬线正文、斜体强调、点状分隔线；
- **纸感背景**：暖 cream 底色 + 白色内容卡片，替代原本的冷灰企业风；
- **克制点缀**：单一珊瑚色（coral）作为强调，避免多色噪音。

## 2. 色彩系统

| Token | 色值 | 用途 |
|---|---|---|
| `--paper` | `#f7f5f0` | 页面底色 |
| `--paper-dark` | `#efeae2` | masthead 渐变、悬浮背景 |
| `--surface` | `#ffffff` | 卡片、面板、表单背景 |
| `--ink` | `#1c1c1c` | 主文字、按钮填充 |
| `--ink-muted` | `#6b6560` | 次要文字、标签、辅助信息 |
| `--rule` | `#d9d3c8` | 边框、分隔线 |
| `--accent` | `#e05a45` | 强调色：活跃态、高优先级、 terminating dot |
| `--accent-soft` | `#f7e3df` | 浅珊瑚背景：badge、hover |

所有颜色通过 `oklch()` 或十六进制实现，禁用渐变背景 wash。

## 3. 字体系统

| Token | 字体栈 | 用途 |
|---|---|---|
| `--serif` | `'Noto Serif SC', serif` | 大标题、章节标题、斜体强调、报头 |
| `--sans` | `'Inter Tight', 'Noto Sans SC', sans-serif` | 正文、导航、标签、按钮、数据 |

**字号规模（桌面 1440px）**

| 元素 | 字号 | 字重 | 备注 |
|---|---|---|---|
| 报头标题 | `2.8rem` | 600 | 衬线，字距 `0.06em` |
| 页面 H1 | `2.4rem` | 600 | 衬线，行高 1.15 |
| 章节 H2 | `1.3rem` | 600 | 衬线 |
| 卡片标题 | `1.15rem` | 600 | 衬线 |
| 正文 | `0.88rem` | 400 | 无衬线，行高 1.7 |
| 小字/标签 | `0.7rem` | 600 | 无衬线，大写或字距加宽 |
| 数据/等宽 | `JetBrains Mono` | 500 | 数值、日期、状态 |

**标题终止符**：每个主要标题末尾加珊瑚色圆点 `●`（`width: 8px; height: 8px; border-radius: 50%`），强化杂志感。

## 4. 布局网格

- 最大容器宽度：`1280px`，水平居中；
- 桌面两栏：`sidebar 240px` + `main 1fr`，间距 `40px`；
- 内容区卡片：白色背景、1px `--rule` 边框、`border-radius: 4px`、阴影 `0 2px 12px rgba(0,0,0,.03)`；
- 移动端（≤1000px）：单栏，侧边栏变为抽屉或顶部折叠。

## 5. 组件规范

### 5.1 Masthead / 报头

```
┌─────────────────────────────────────┐
│  ◉                                  │  ← mark glyph
│  GS-Tracker                         │  ← title, serif, 2.8rem
│  高盛动向情报系统 · Goldman Sachs Intelligence │  ← sub
│  2026年7月29日 · 星期三 · 第 026 期          │  ← date
└─────────────────────────────────────┘
背景：linear-gradient(180deg, #f7f5f0 0%, #efeae2 100%)
下边框：1px solid --rule
```

### 5.2 导航条

- 水平居中排列，链接间距 `36px`；
- 默认：`--ink-muted`，下划线透明；
- 活跃态：`--ink`，下划线 `1px solid --accent`；
- 下边界：`1px dotted --rule`。

### 5.3 侧边栏

- 宽度 `240px`，右边界为点状竖线；
- 分组标题：小写大写、字距 `0.08em`、颜色 `--ink-muted`；
- 菜单项：衬线或非衬线 `0.82rem`，active 态加粗 + 颜色变深；
- 筛选复选框：使用 `--accent` 作为 accent-color。

### 5.4 按钮

- 主按钮：珊瑚色填充、白色文字、`border-radius: 24px`、全宽；
- 次按钮：白色填充、`--ink` 边框、`border-radius: 24px`；
- hover：主按钮加深，次按钮反色。

### 5.5 卡片

- 白色背景、1px `--rule` 边框、`border-radius: 4px`；
- 内边距 `24px–28px`；
- 阴影：`0 2px 12px rgba(0,0,0,.03)`。

### 5.6 信号卡片

- 两栏布局：内容 + 日期；
- 来源 badge：`0.65rem`、大写、圆角 `3px`；
  - High：`background: --accent-soft; color: --accent`
  - Medium：`background: #f0ede7; color: --ink-muted`
  - Low：`background: #f5f5f5; color: #999`
- 标题：衬线 `1.05rem`；
- 摘要：无衬线 `0.84rem`、行高 1.65。

### 5.7 表单 / 输入框

- 输入框：`border: 1px solid --rule`、`border-radius: 4px`、内边距 `10px 12px`；
- focus：`border-color: --accent`；
- 标签：`0.75rem`、字距加宽、`--ink-muted`。

### 5.8 表格

- 表头：`--surface` 背景、`0.7rem` 大写标签；
- 行分隔：`1px solid --rule`；
- 数字使用等宽字体右对齐。

### 5.9 章节标题

```
高优先级信号  ·········································  4 条
(衬线 H2)    (点状延伸线)                            (计数 badge)
```

## 6. 页面清单

| 页面 | 文件 | 核心模块 |
|---|---|---|
| 登录页 | `gs-tracker-magazine-login.html` | 报头、登录卡片、免责声明 |
| 每日情报 | `gs-tracker-magazine-daily.html` | Hero、KPI、AI 日报、信号流、日期选择 |
| 季度报告 | `gs-tracker-magazine-quarter.html` | 季度选择、标签页、概览、AI 分析、持仓变化、持仓明细 |
| 设置页 | `gs-tracker-magazine-settings.html` | LLM 模型、信号源开关、自定义源 |
| 使用指南 | `gs-tracker-magazine-guide.html` | TOC、章节、提示框、警告框 |

## 7. 响应式策略

- **桌面（≥1000px）**：完整两栏布局；
- **平板（768px–999px）**：侧边栏收缩为图标或折叠，内容区保持卡片网格；
- **手机（≤767px）**：
  - masthead 字号缩小；
  - 导航变为汉堡菜单或横向滚动；
  - 侧边栏变为抽屉；
  - 卡片堆叠为单栏；
  - 统计行变为 2×2 网格。

## 8. 动效与交互

- 卡片 hover：`box-shadow` 轻微加深、`transform: translateY(-2px)`；
- 按钮 hover：颜色反转或加深；
- 页面进入：内容区 fade-in + translateY(12px)；
- 尊重 `prefers-reduced-motion`。

## 9. 交付文件

所有 mockup 位于项目根目录，均为独立 HTML 文件，可直接在浏览器打开：

- `gs-tracker-design-system.md`
- `gs-tracker-magazine-login.html`
- `gs-tracker-magazine-daily.html`
- `gs-tracker-magazine-quarter.html`
- `gs-tracker-magazine-settings.html`
- `gs-tracker-magazine-guide.html`

---
*本设计系统为前端实现提供像素级参考；后续可将 CSS 抽离为模板级样式表并注入 FastAPI Jinja2 模板。*
