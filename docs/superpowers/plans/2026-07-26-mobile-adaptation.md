# 手机浏览器适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 GS-Tracker 仪表盘在手机浏览器（≤768px）上完整可用：汉堡抽屉导航 + 全部页面响应式适配，桌面端像素级不变。

**Architecture:** 单一改动文件 `templates/dashboard.html`：收编现有 2 条散乱手机样式为一个统一 `@media (max-width: 768px)` 区块；新增 2 个 DOM 元素（手机顶栏、遮罩层）+ ~25 行新 JS（抽屉开关，不改任何现有函数）；另加 2 个一次性验证脚本（`scripts/`，不进测试套件、无新依赖）。

**Tech Stack:** 纯 CSS + 原生 JS；验证用 Node + 全局已装 Playwright（`npm root -g` 引用，不新增依赖）。

**设计文档:** `docs/superpowers/specs/2026-07-26-mobile-adaptation-design.md`

## Global Constraints

- 桌面端（>768px）任何像素不变：新样式全部关在媒体查询内，新 DOM 桌面端 `display:none`
- 不改动任何现有 JS 函数；只新增（进度面板用 `!important` 覆盖内联样式，连 JS 字符串都不碰）
- 所有用户可见文字用中文
- 后端零改动；每次任务结束 `pytest -q` 必须全绿（当前 273 个）
- 无新增 Python/npm 依赖；验证脚本通过 `npm root -g` 引用全局 playwright
- 提交信息格式：`feat(mobile): ...`，中文描述可跟在后面

**与 spec 的三处有意偏差（已核准方向，实施时以此为准）：**
1. spec 第 4 节"页内标签横向可滑动"取消——模块标签（概览/AI分析/多源信号/持仓明细）实际位于侧栏"模块"区（`#navTabs`），手机上已在抽屉内，无需额外处理
2. 进度面板不把样式搬出 JS 字符串，改为媒体查询内 `!important` 覆盖——零 JS 改动、桌面端完全一致
3. 验证脚本为 `scripts/verify_mobile.js`（非 .py）——系统 Python 无 playwright 模块，Node 全局 playwright 已装，零新依赖

**关于 TDD 的说明：** 本次是纯前端 CSS/JS 改动，无单元测试框架可挂。验证方式为：截图对比 + DOM 断言脚本（Task 5 的 verify_mobile.js，先用 `git stash` 对旧代码跑出 RED，再对新代码跑出 GREEN）+ pytest 后端回归。每个任务内仍遵循"改动 → 验证 → 提交"的小循环。

---

### Task 1: 基线截图 + 收编媒体查询 + 汉堡抽屉导航

**Files:**
- Create: `scripts/ui_snapshot.js`
- Modify: `templates/dashboard.html`（DOM 新增 2 元素 ~第 219 行后；CSS 删第 174 行、替换第 211-216 行；JS 在第 1466 行 `// ====== Boot ======` 前新增）

**Interfaces:**
- Produces: `.mobile-topbar`（含 `.menu-btn`、`#mobilePageTitle`）、`.mobile-mask#mobileMask`、`toggleDrawer(force)` 全局函数、`.sidebar.open`/`.mobile-mask.open` 类约定、`scripts/ui_snapshot.js <url> <w> <h> <outdir>` 用法——后续全部任务依赖

- [ ] **Step 1: 确认本地服务在跑，创建截图工具**

服务检查（若 200 跳过启动）：
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8770/api/health || (nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3)
```

创建 `scripts/ui_snapshot.js`：
```js
// scripts/ui_snapshot.js — snapshot dashboard views at a given viewport.
// Usage: node scripts/ui_snapshot.js <url> <width> <height> <outdir>
// Drawer-aware: opens the hamburger drawer first when the mobile topbar exists.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

async function navTo(pg, view) {
    const btn = await pg.$('.mobile-topbar .menu-btn');
    if (btn && await btn.isVisible()) { await btn.click(); await pg.waitForTimeout(400); }
    await pg.click(`li[data-view="${view}"]`);
    await pg.waitForTimeout(1200);
}

(async () => {
    const [url, w, h, outdir] = process.argv.slice(2);
    fs.mkdirSync(outdir, { recursive: true });
    const b = await pw.chromium.launch();
    const pg = await b.newPage({ viewport: { width: +w, height: +h } });
    await pg.goto(url, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(800);
    await pg.screenshot({ path: path.join(outdir, '1_daily.png'), fullPage: true });
    await navTo(pg, 'settings');
    await pg.screenshot({ path: path.join(outdir, '2_settings.png'), fullPage: true });
    await navTo(pg, 'quarter');
    await pg.screenshot({ path: path.join(outdir, '3_quarter.png'), fullPage: true });
    await b.close();
    console.log('saved to ' + outdir);
})();
```

- [ ] **Step 2: 拍改动前基线（手机 + 桌面）**

```bash
node scripts/ui_snapshot.js http://127.0.0.1:8770 390 844 /tmp/gs_m_before
node scripts/ui_snapshot.js http://127.0.0.1:8770 1280 900 /tmp/gs_d_before
```
Expected: 两个目录各 3 张图。`/tmp/gs_d_before/` 是 Task 5 桌面回归对比的基准，**不要删**。

- [ ] **Step 3: DOM——`<body>` 后插入顶栏和遮罩**

old_string（第 219-221 行）：
```html
<body>

<!-- ====== SIDEBAR ====== -->
```
new_string：
```html
<body>

<!-- Mobile topbar + drawer mask (desktop: display:none) -->
<div class="mobile-topbar">
    <button class="menu-btn" onclick="toggleDrawer()" aria-label="菜单">☰</button>
    <span class="page-title" id="mobilePageTitle">📡 每日情报</span>
</div>
<div class="mobile-mask" id="mobileMask" onclick="toggleDrawer(false)"></div>

<!-- ====== SIDEBAR ====== -->
```

- [ ] **Step 4: CSS——删除旧的散乱规则**

删除第 174 行整行：
```css
        @media (max-width: 768px) { .daily-stats { grid-template-columns: repeat(2, 1fr); } }
```

- [ ] **Step 5: CSS——替换第 211-216 行为统一手机区块（本任务只含抽屉部分，后续任务在锚点注释处追加）**

old_string：
```css
        /* Responsive */
        @media (max-width: 768px) {
            .sidebar { width: 100%; position: relative; height: auto; }
            .main { margin-left: 0; }
            .stats-row { grid-template-columns: repeat(2, 1fr); }
        }
```
new_string：
```css
        /* ====== Mobile (<=768px) ====== */
        .mobile-topbar, .mobile-mask { display: none; }

        @media (max-width: 768px) {
            /* --- Topbar + drawer navigation --- */
            .mobile-topbar {
                display: flex; align-items: center; gap: 8px;
                position: fixed; top: 0; left: 0; right: 0; height: 52px;
                background: var(--sidebar-bg); color: #fff; padding: 0 12px; z-index: 150;
            }
            .mobile-topbar .menu-btn {
                background: none; border: none; color: #fff; font-size: 1.3em;
                cursor: pointer; min-width: 44px; min-height: 44px;
            }
            .mobile-topbar .page-title { font-weight: 600; font-size: 0.95em; }
            .mobile-mask {
                display: block; position: fixed; inset: 0; background: rgba(0,0,0,.45);
                opacity: 0; pointer-events: none; transition: opacity .25s; z-index: 180;
            }
            .mobile-mask.open { opacity: 1; pointer-events: auto; }
            .sidebar {
                width: min(78vw, 300px);
                transform: translateX(-105%); transition: transform .25s ease; z-index: 200;
            }
            .sidebar.open { transform: none; box-shadow: 4px 0 24px rgba(0,0,0,.35); }
            .main { margin-left: 0; padding: 68px 16px 16px; }

            /* --- Daily intel (Task 2) --- */
            /* --- Settings (Task 3) --- */
            /* --- Quarter + tables (Task 4) --- */
            /* --- Touch targets (Task 4) --- */
            /* --- Progress panel (Task 4) --- */
        }
```

- [ ] **Step 6: JS——新增抽屉开关（不改任何现有函数）**

在 `// ====== Boot ======`（第 1466 行）之前插入：
```js
// ====== Mobile drawer ======
function toggleDrawer(force) {
    const sb = document.querySelector('.sidebar');
    const mask = document.getElementById('mobileMask');
    if (!sb || !mask) return;
    const open = typeof force === 'boolean' ? force : !sb.classList.contains('open');
    sb.classList.toggle('open', open);
    mask.classList.toggle('open', open);
}

// Delegated listener survives renderQuarterList() re-renders; additive, no
// changes to switchMainView/switchTab.
(function bindMobileNav() {
    const sb = document.querySelector('.sidebar');
    if (!sb) return;
    sb.addEventListener('click', (e) => {
        const item = e.target.closest('#mainNav li, #navTabs li, #quarterList li');
        if (!item) return;
        toggleDrawer(false);
        const titleEl = document.getElementById('mobilePageTitle');
        if (!titleEl) return;
        if (item.closest('#quarterList') || item.dataset.view === 'quarter') {
            titleEl.textContent = '📅 季度报告';
        } else if (item.dataset.view) {
            titleEl.textContent = item.textContent.trim();
        }
    });
})();

```

- [ ] **Step 7: 重启服务，验证抽屉开合 + 桌面未变**

```bash
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node -e "const path=require('path');const pw=require(path.join(require('child_process').execSync('npm root -g').toString().trim(),'playwright'));(async()=>{const b=await pw.chromium.launch();const p=await b.newPage({viewport:{width:390,height:844}});await p.goto('http://127.0.0.1:8770',{waitUntil:'networkidle'});await p.click('.menu-btn');await p.waitForTimeout(400);const open=await p.evaluate(()=>document.querySelector('.sidebar').classList.contains('open'));await p.click('.mobile-mask');await p.waitForTimeout(400);const closed=await p.evaluate(()=>!document.querySelector('.sidebar').classList.contains('open'));console.log(open&&closed?'DRAWER OK':'DRAWER FAIL');await b.close();process.exit(open&&closed?0:1);})()"
```
Expected: `DRAWER OK`

再拍手机+桌面快照对比：
```bash
node scripts/ui_snapshot.js http://127.0.0.1:8770 390 844 /tmp/gs_m_t1
node scripts/ui_snapshot.js http://127.0.0.1:8770 1280 900 /tmp/gs_d_t1
```
肉眼检查：手机 `1_daily.png` 顶部有深色顶栏（☰ + 📡 每日情报）、左侧不再有竖条；桌面 3 张图与 `/tmp/gs_d_before/` 对应图完全一致（无顶栏、侧栏原样）。

- [ ] **Step 8: pytest 回归**

```bash
pytest -q
```
Expected: 273 passed（数量如有新增测试以实际为准，但必须全绿）

- [ ] **Step 9: Commit**

```bash
git add templates/dashboard.html scripts/ui_snapshot.js
git commit -m "feat(mobile): hamburger drawer navigation + consolidate media queries"
```

---

### Task 2: 每日情报页适配

**Files:**
- Modify: `templates/dashboard.html`（媒体查询内 `/* --- Daily intel (Task 2) --- */` 锚点处）

**Interfaces:**
- Consumes: Task 1 的统一媒体查询与锚点注释
- Produces: 无新约定，纯样式

- [ ] **Step 1: CSS——锚点替换为每日情报规则**

old_string：
```css
            /* --- Daily intel (Task 2) --- */
```
new_string：
```css
            /* --- Daily intel --- */
            .daily-header { gap: 8px; }
            .daily-header h2 { font-size: 1.25em; }
            .daily-stats { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .stat-card { padding: 14px; }
            .date-picker-row { flex-wrap: wrap; width: 100%; }
            .date-picker-row input[type=date] { flex: 1; min-width: 0; font-size: 16px; }
            .signal-card { padding: 12px 14px; }
            .signal-card h4, .signal-card .sig-summary, .signal-card .sig-meta { overflow-wrap: anywhere; }
```
（`font-size: 16px` 是 iOS 防自动放大的硬性要求；`overflow-wrap` 防长英文标题/URL 撑破卡片）

- [ ] **Step 2: 重启 + 快照 + 检查**

```bash
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node scripts/ui_snapshot.js http://127.0.0.1:8770 390 844 /tmp/gs_m_t2
```
肉眼检查 `1_daily.png`：日期行自然换行、按钮正常大小不竖排、统计卡片 2 列、信号卡片不溢出。

- [ ] **Step 3: pytest + Commit**

```bash
pytest -q && git add templates/dashboard.html && git commit -m "feat(mobile): daily intel page responsive rules"
```

---

### Task 3: 设置页适配

**Files:**
- Modify: `templates/dashboard.html`（`/* --- Settings (Task 3) --- */` 锚点处）

**Interfaces:**
- Consumes: Task 1 锚点；`.source-row`/`.model-row` 结构（`.info` + 匿名按钮 div，见第 1074-1080、1129-1138 行）
- Produces: 无新约定，纯样式

- [ ] **Step 1: CSS——锚点替换为设置页规则**

old_string：
```css
            /* --- Settings (Task 3) --- */
```
new_string：
```css
            /* --- Settings --- */
            .source-row, .model-row { flex-direction: column; align-items: stretch; gap: 10px; }
            .source-row > div:not(.info), .model-row > div:not(.info) { display: flex; gap: 6px; flex-wrap: wrap; }
            .add-form input, .add-form select { flex: 1 1 100% !important; min-width: 0 !important; width: 100%; font-size: 16px; }
            .add-form label { display: flex; align-items: center; gap: 6px; min-height: 44px; }
```
（`!important` 用于覆盖 `#csUrl`/`#csInstruction` 的内联 `flex:1;min-width:260px`——内联样式保留，桌面端不受影响）

- [ ] **Step 2: 重启 + 快照 + 检查**

```bash
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node scripts/ui_snapshot.js http://127.0.0.1:8770 390 844 /tmp/gs_m_t3
```
肉眼检查 `2_settings.png`：源卡片上下两区、按钮横排不竖排、输入框每行一个占满整行、单选按钮间距正常。

- [ ] **Step 3: pytest + Commit**

```bash
pytest -q && git add templates/dashboard.html && git commit -m "feat(mobile): settings page responsive rules"
```

---

### Task 4: 季度页表格 + 进度面板 + 全局触控细节

**Files:**
- Modify: `templates/dashboard.html`（3 个锚点处 CSS + `renderHoldingsPanel` 模板 ~第 903-907 行）

**Interfaces:**
- Consumes: Task 1 锚点
- Produces: `.table-wrap` / `.table-scroll` 表格滚动容器约定（桌面端无视觉影响）

- [ ] **Step 1: CSS——季度页 + 表格滚动**

old_string：
```css
            /* --- Quarter + tables (Task 4) --- */
```
new_string：
```css
            /* --- Quarter + tables --- */
            .stats-row { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .page-header { flex-wrap: wrap; }
            .card { padding: 16px; }
            .table-wrap { position: relative; }
            .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
            .table-wrap::after {
                content: ''; position: absolute; top: 0; right: 0; bottom: 0; width: 24px;
                background: linear-gradient(to right, rgba(255,255,255,0), rgba(26,35,126,.08));
                pointer-events: none;
            }
            .main img { max-width: 100%; height: auto; }
```

- [ ] **Step 2: CSS——触控目标**

old_string：
```css
            /* --- Touch targets (Task 4) --- */
```
new_string：
```css
            /* --- Touch targets --- */
            .run-btn, .toggle-btn, .btn-sm, .day-btn { min-height: 44px; }
            .toggle-btn, .btn-sm { display: inline-flex; align-items: center; justify-content: center; }
            .main-nav li, .nav-tabs li, .quarter-list li { padding-top: 12px; padding-bottom: 12px; }
            .signal-filter label { min-height: 44px; }
```

- [ ] **Step 3: CSS——进度面板（`!important` 覆盖第 535 行内联样式，JS 字符串不动）**

old_string：
```css
            /* --- Progress panel (Task 4) --- */
```
new_string：
```css
            /* --- Progress panel --- */
            #progressPanel { min-width: 0 !important; max-width: 420px !important; width: calc(100vw - 32px); max-height: 85vh; overflow-y: auto; }
```

- [ ] **Step 4: 模板——持仓表格外套滚动容器（`renderHoldingsPanel`）**

old_string（第 903-907 行）：
```js
        <div class="card">
            <table>
                <thead><tr><th style="width:40px;">#</th><th>公司名称</th><th style="text-align:right;">持仓价值（美元）</th></tr></thead>
                <tbody>${rows || '<tr><td colspan="3" style="text-align:center;color:#999;">暂无持仓数据</td></tr>'}</tbody>
            </table>
        </div>
```
new_string：
```js
        <div class="card">
            <div class="table-wrap"><div class="table-scroll">
            <table>
                <thead><tr><th style="width:40px;">#</th><th>公司名称</th><th style="text-align:right;">持仓价值（美元）</th></tr></thead>
                <tbody>${rows || '<tr><td colspan="3" style="text-align:center;color:#999;">暂无持仓数据</td></tr>'}</tbody>
            </table>
            </div></div>
        </div>
```
（桌面端这两个 wrapper 无样式、无视觉影响；手机上表格超出时可左右滑，右缘有渐隐提示）

- [ ] **Step 5: 重启 + 快照 + 检查**

```bash
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node scripts/ui_snapshot.js http://127.0.0.1:8770 390 844 /tmp/gs_m_t4
```
肉眼检查 `3_quarter.png`：概览统计 2 列、卡片不溢出。再验证进度面板宽度：
```bash
node -e "const path=require('path');const pw=require(path.join(require('child_process').execSync('npm root -g').toString().trim(),'playwright'));(async()=>{const b=await pw.chromium.launch();const p=await b.newPage({viewport:{width:390,height:844}});await p.goto('http://127.0.0.1:8770',{waitUntil:'networkidle'});await p.evaluate(()=>showProgressPanel());await p.waitForTimeout(300);const r=await p.evaluate(()=>{const x=document.getElementById('progressPanel').getBoundingClientRect();return{left:x.left,right:x.right}});const ok=r.left>=0&&r.right<=390;console.log(ok?'PANEL OK':'PANEL FAIL',JSON.stringify(r));await b.close();process.exit(ok?0:1);})()"
```
Expected: `PANEL OK`

- [ ] **Step 6: pytest + Commit**

```bash
pytest -q && git add templates/dashboard.html && git commit -m "feat(mobile): quarter tables, progress panel, touch targets"
```

---

### Task 5: 全量验证脚本 + 桌面回归对比 + 部署

**Files:**
- Create: `scripts/verify_mobile.js`

**Interfaces:**
- Consumes: 前 4 个任务全部成果（`.menu-btn`、`.sidebar.open`、`.mobile-mask`、`showProgressPanel()` 全局函数）
- Produces: `node scripts/verify_mobile.js <url> <outdir>` —— 退出码 0 = 全部通过

- [ ] **Step 1: 创建验证脚本**

`scripts/verify_mobile.js`：
```js
// scripts/verify_mobile.js — mobile layout assertions at 390x844 (iPhone-ish).
// Usage: node scripts/verify_mobile.js <url> <outdir>
// Exit 0 = all checks pass. Screenshots saved to <outdir> for eyeball review.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

const URL_ = process.argv[2] || 'http://127.0.0.1:8770';
const OUT = process.argv[3] || '/tmp/gs_mobile_verify';
const failures = [];
function check(name, ok) {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) failures.push(name);
}
process.on('unhandledRejection', e => {
    console.log('FAIL  exception: ' + e.message);
    process.exit(1);
});

(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const b = await pw.chromium.launch();
    const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
    await pg.goto(URL_, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(800);
    const noX = () => pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    const drawerOpen = () => pg.evaluate(() => document.querySelector('.sidebar').classList.contains('open'));

    check('daily: no horizontal overflow', await noX());

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    check('drawer opens', await drawerOpen());
    await pg.screenshot({ path: path.join(OUT, 'drawer_open.png') });

    await pg.click('.mobile-mask'); await pg.waitForTimeout(400);
    check('mask closes drawer', !(await drawerOpen()));

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    await pg.click('li[data-view="settings"]'); await pg.waitForTimeout(1200);
    check('drawer auto-closes after nav', !(await drawerOpen()));
    check('settings: no horizontal overflow', await noX());
    await pg.screenshot({ path: path.join(OUT, 'settings.png'), fullPage: true });

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    await pg.click('li[data-view="quarter"]'); await pg.waitForTimeout(1200);
    check('quarter: no horizontal overflow', await noX());
    await pg.screenshot({ path: path.join(OUT, 'quarter.png'), fullPage: true });

    await pg.evaluate(() => showProgressPanel());
    await pg.waitForTimeout(300);
    const r = await pg.evaluate(() => {
        const x = document.getElementById('progressPanel').getBoundingClientRect();
        return { left: x.left, right: x.right };
    });
    check('progress panel within viewport', r.left >= 0 && r.right <= 390);
    await pg.screenshot({ path: path.join(OUT, 'progress.png') });

    await b.close();
    console.log(failures.length ? `\n${failures.length} FAIL` : '\nALL PASS');
    process.exit(failures.length ? 1 : 0);
})();
```

- [ ] **Step 2: GREEN——对新代码跑验证**

```bash
node scripts/verify_mobile.js http://127.0.0.1:8770 /tmp/gs_mobile_verify
```
Expected: 6 个 PASS + `ALL PASS`，退出码 0

- [ ] **Step 3: RED——对旧代码验证脚本必然失败（证明断言有效）**

```bash
git stash && sleep 1
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node scripts/verify_mobile.js http://127.0.0.1:8770 /tmp/gs_mobile_red; echo "exit=$?"
git stash pop
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
```
Expected: `exit=1`（旧代码没有 `.menu-btn`，第一步点击即抛异常 → FAIL）。`git stash` 只暂存已跟踪文件（dashboard.html），`scripts/` 下未跟踪的新脚本不受影响。stash pop 后重启服务恢复新代码。

- [ ] **Step 4: 桌面端回归对比**

```bash
node scripts/ui_snapshot.js http://127.0.0.1:8770 1280 900 /tmp/gs_d_after
```
逐张对比 `/tmp/gs_d_before/` 与 `/tmp/gs_d_after/` 的 1/2/3 号图：必须完全一致（无顶栏、侧栏原样、表单布局不变）。

- [ ] **Step 5: 全量 pytest**

```bash
pytest -q
```
Expected: 全绿

- [ ] **Step 6: Commit + 部署**

```bash
git add scripts/verify_mobile.js
git commit -m "feat(mobile): mobile layout verification script"
git push origin main
```
GitHub Actions 部署约 26s。生产验证（401 = 在线，basic auth 保护）：
```bash
curl -s -o /dev/null -w "%{http_code}" http://111.228.23.109/
```
Expected: `401`

- [ ] **Step 7: 真机验证（用户手动）**

给用户操作步骤：手机浏览器打开 `http://111.228.23.109`，输入 basic auth 账号密码，逐项过一遍：抽屉开合、每日情报、设置页表单、跑进度面板。用户在手机上确认后本任务完成。

---

## Self-Review 记录

- **Spec 覆盖**：spec 组件 1（抽屉）→Task 1；组件 2（每日情报）→Task 2；组件 3（设置页）→Task 3；组件 4（季度/进度面板）→Task 4；组件 5（触控）→Task 4；测试策略→Task 5。spec 第 4 节"页内标签"已在头部偏差说明中取消（模块标签在侧栏抽屉内）。
- **占位符扫描**：无 TBD/TODO；每步含完整代码与预期输出。
- **类型/命名一致性**：`.mobile-topbar`/`.mobile-mask`/`#mobileMask`/`#mobilePageTitle`/`toggleDrawer`/`.table-wrap`/`.table-scroll` 在 Task 1/4/5 间一致；锚点注释字符串逐字匹配。
