# Claude Code 编程框架深度对比报告：Superpowers vs gstack

> **适用对象**：编程小白 / 独立开发者 / 小型技术团队  
> **目标场景**：在 VSCode + Claude Code 环境下进行实际项目开发  
> **报告日期**：2026年5月22日

---

## 目录

1. [框架概览](#一框架概览)
2. [核心流程原理对比](#二核心流程原理对比)
3. [功能维度详细对比](#三功能维度详细对比)
4. [优缺点分析](#四优缺点分析)
5. [选择建议：你该用哪一个](#五选择建议你该用哪一个)
6. [双框架结合使用方案](#六双框架结合使用方案)
7. [实际项目最佳实践](#七实际项目最佳实践)
8. [CLAUDE.md 与 AGENTS.md 编程规范定义](#八claude-md-与-agents-md-编程规范定义)
9. [快速上手路线图](#九快速上手路线图)
10. [常见问题 FAQ](#十常见问题-faq)

---

## 一、框架概览

### 1.1 Superpowers（ obra/superpowers ）

| 属性       | 详情                                                                                  |
| -------- | ----------------------------------------------------------------------------------- |
| **作者**   | Jesse Vincent（Prime Radiant）                                                        |
| **定位**   | Agentic Skills Framework & 软件开发方法论                                                  |
| **核心理念** | 测试驱动开发（TDD）、系统化流程、降低复杂度、证据优先                                                        |
| **工作模式** | 技能自动触发，无需手动调用                                                                       |
| **支持平台** | Claude Code、Codex CLI、Cursor、GitHub Copilot CLI、Gemini CLI、OpenCode、Factory Droid 等 |
| **安装方式** | 通过各 AI Agent 官方插件市场一键安装                                                             |
| **许可证**  | MIT                                                                                 |

**一句话总结**：Superpowers 是一套"嵌入式"开发纪律，它在你开始编码前强制你思考、规划、写测试，然后通过子代理自动执行，确保代码质量。

### 1.2 gstack（ garrytan/gstack ）

| 属性       | 详情                                                                             |
| -------- | ------------------------------------------------------------------------------ |
| **作者**   | Garry Tan（Y Combinator CEO）                                                    |
| **定位**   | 将 Claude Code 变成一支虚拟工程团队                                                       |
| **核心理念** | 模拟真实创业团队的完整 Sprint 流程：Think → Plan → Build → Review → Test → Ship → Reflect    |
| **工作模式** | 通过 23+ 个斜杠命令（/office-hours、/review、/ship 等）主动调用                                |
| **支持平台** | Claude Code、OpenClaw、Codex CLI、Cursor、Hermes、Kiro、Slate、Factory Droid 等 10+ 平台 |
| **安装方式** | Git Clone + Setup 脚本（30秒）                                                      |
| **许可证**  | MIT                                                                            |

**一句话总结**：gstack 是一个"指挥系统"，它给 AI 分配角色（CEO、设计师、QA、安全官等），通过明确的命令触发完整的产品开发流水线，支持并行冲刺和真实浏览器测试。

---

## 二、核心流程原理对比

### 2.1 Superpowers 的工作流原理

Superpowers 采用**"事件驱动 + 自动触发"**模式。当你启动 Claude Code 并开始描述要构建的东西时，框架不会立即开始写代码，而是按照以下**强制流程**推进：

```
┌─────────────────────────────────────────────────────────────┐
│  1. Brainstorming（需求细化）                                │
│     → AI 通过苏格拉底式提问，帮你把模糊想法变成明确需求          │
│     → 输出：设计文档（Design Doc），分块展示供你确认           │
├─────────────────────────────────────────────────────────────┤
│  2. Git Worktrees（隔离工作区）                              │
│     → 自动创建新分支和隔离工作区，确保主分支安全               │
│     → 验证测试基线是否干净                                    │
├─────────────────────────────────────────────────────────────┤
│  3. Writing Plans（任务拆解）                                │
│     → 将设计文档拆分为 2-5 分钟可完成的微任务                  │
│     → 每个任务包含：精确文件路径、完整代码、验证步骤            │
├─────────────────────────────────────────────────────────────┤
│  4. Subagent-Driven Development（子代理开发）                 │
│     → 为每个任务派遣全新子代理，避免上下文污染                   │
│     → 两阶段审查：先验证是否符合规格，再审查代码质量              │
├─────────────────────────────────────────────────────────────┤
│  5. Test-Driven Development（测试驱动开发）                    │
│     → 强制 RED-GREEN-REFACTOR 循环                           │
│     → 先写失败测试 → 写最小代码让测试通过 → 重构               │
│     → 严禁在测试之前写实现代码！                              │
├─────────────────────────────────────────────────────────────┤
│  6. Code Review（代码审查）                                    │
│     → 任务间自动审查，按严重程度报告问题                         │
│     → 严重问题会阻断进度                                      │
├─────────────────────────────────────────────────────────────┤
│  7. Finish Branch（分支收尾）                                │
│     → 验证所有测试通过                                        │
│     → 提供选项：合并/提PR/保留/丢弃                            │
│     → 自动清理工作区                                          │
└─────────────────────────────────────────────────────────────┘
```

**关键原理**：

- **技能自动触发**：你不需要记住命令，AI 检测到当前阶段后自动加载对应技能
- **子代理隔离**：每个任务用新会话，避免"上下文漂移"
- **强制纪律**：TDD 不是建议，是强制规则；不写测试就无法推进

### 2.2 gstack 的工作流原理

gstack 采用**"角色扮演 + 命令触发"**模式。它模拟一家真实创业公司的完整团队，每个斜杠命令对应一个"虚拟员工"：

```
┌─────────────────────────────────────────────────────────────┐
│  THINK（思考阶段）                                            │
├─────────────────────────────────────────────────────────────┤
│  /office-hours     → YC 合伙人角色：6个强制问题拷问产品方向      │
│  /plan-ceo-review  → CEO 角色：挑战假设，寻找10倍产品机会         │
├─────────────────────────────────────────────────────────────┤
│  PLAN（规划阶段）                                             │
├─────────────────────────────────────────────────────────────┤
│  /plan-eng-review  → 工程经理：架构图、数据流、边界情况、测试矩阵 │
│  /plan-design-review→ 设计师：0-10分评分，AI Slop检测           │
│  /plan-devex-review→ DX负责人：开发者体验审查                  │
│  /autoplan         → 自动流水线：CEO→设计→工程→DX 一键执行       │
├─────────────────────────────────────────────────────────────┤
│  BUILD（构建阶段）                                            │
├─────────────────────────────────────────────────────────────┤
│  /design-shotgun   → 设计探索：生成4-6个AI mockup变体           │
│  /design-html      → 设计工程师：mockup转生产级HTML/CSS          │
│  （编码由 Claude Code 原生完成，gstack不接管编辑器）             │
├─────────────────────────────────────────────────────────────┤
│  REVIEW（审查阶段）                                           │
├─────────────────────────────────────────────────────────────┤
│  /review           →  Staff Engineer：找生产环境才会暴露的bug    │
│  /codex            →  第二意见：OpenAI Codex独立交叉审查         │
│  /cso              →  安全官：OWASP Top 10 + STRIDE威胁建模      │
│  /design-review    →  设计师：UI审计 + 修复                     │
├─────────────────────────────────────────────────────────────┤
│  TEST（测试阶段）                                             │
├─────────────────────────────────────────────────────────────┤
│  /qa               →  QA负责人：打开真实浏览器点击测试           │
│                     发现bug→自动修复→生成回归测试→重新验证      │
│  /qa-only          →  纯报告模式，不修改代码                     │
│  /benchmark        →  性能工程师：Core Web Vitals基准测试       │
├─────────────────────────────────────────────────────────────┤
│  SHIP（发布阶段）                                             │
├─────────────────────────────────────────────────────────────┤
│  /ship             →  发布工程师：同步main→运行测试→覆盖率审计   │
│                     → 推送到远程→自动开PR                      │
│  /land-and-deploy  →  合并PR→等待CI→部署→验证生产环境健康       │
│  /canary           →  SRE：部署后监控循环                       │
├─────────────────────────────────────────────────────────────┤
│  REFLECT（反思阶段）                                          │
├─────────────────────────────────────────────────────────────┤
│  /retro            →  工程经理：每周复盘，测试健康度趋势          │
│  /document-release →  技术文档工程师：自动更新所有项目文档        │
│  /learn            →  记忆管理：跨会话积累项目知识                │
└─────────────────────────────────────────────────────────────┘
```

**关键原理**：

- **角色分工**：每个命令是一个专家，有明确的职责边界
- **流水线衔接**：前一个阶段的输出自动成为后一个阶段的输入（如 /office-hours 的设计文档会被 /plan-ceo-review 读取）
- **真实浏览器**：/qa 和 /browse 使用 Playwright 控制真实 Chromium，不是模拟
- **并行冲刺**：通过 Conductor 支持同时运行 10-15 个独立 Sprint
- **跨模型审查**：/codex 让 OpenAI 和 Anthropic 互相审查，发现单一模型的盲点

---

## 三、功能维度详细对比

### 3.1 需求分析 & 产品规划

| 维度       | Superpowers  | gstack                   |
| -------- | ------------ | ------------------------ |
| **触发方式** | 自动触发（开始编码前）  | 手动命令 `/office-hours`     |
| **提问风格** | 苏格拉底式追问，逐步细化 | YC 式 6 个强制问题，直接挑战假设      |
| **输出物**  | 分块设计文档       | 设计文档 + 3 种实现方案 + 工作量估算   |
| **产品洞察** | 中等（聚焦技术实现）   | **强**（模拟 CEO 视角，寻找10倍机会） |
| **适合场景** | 需求相对明确的功能开发  | 从0到1的产品探索、MVP定义          |

### 3.2 架构 & 技术规划

| 维度        | Superpowers     | gstack                                       |
| --------- | --------------- | -------------------------------------------- |
| **架构设计**  | 包含在 Plan 阶段，较简洁 | `/plan-eng-review` 强制 ASCII 架构图、数据流、状态机、错误路径 |
| **测试策略**  | **强制 TDD**，测试先行 | 测试矩阵规划，但不强制 TDD（可在实现阶段补）                     |
| **安全考量**  | 基础（依赖代码审查）      | `/cso` 专门安全官：OWASP + STRIDE + 具体攻击场景         |
| **DX 审查** | 无               | `/plan-devex-review` 专门审查开发者体验               |

### 3.3 编码实现

| 维度         | Superpowers               | gstack                         |
| ---------- | ------------------------- | ------------------------------ |
| **编码方式**   | 子代理驱动，每个任务新会话             | Claude Code 原生编码，gstack 不接管编辑器 |
| **任务粒度**   | 2-5 分钟微任务                 | 不限定，由计划阶段决定                    |
| **TDD 执行** | **强制 RED-GREEN-REFACTOR** | 推荐但不强制（可通过测试覆盖率审计约束）           |
| **代码生成**   | 强调"最小实现"（YAGNI）           | 强调"可交付质量"，有设计-HTML流水线          |
| **并行开发**   | 单线程子代理串行                  | 支持 Conductor 多会话并行             |

### 3.4 代码审查

| 维度        | Superpowers  | gstack                           |
| --------- | ------------ | -------------------------------- |
| **审查时机**  | 每个任务完成后自动审查  | 手动触发 `/review`                   |
| **审查深度**  | 规格符合性 + 代码质量 | Staff Engineer 级别：找生产环境bug、完整性缺口 |
| **跨模型审查** | 不支持          | `/codex` 支持 OpenAI Codex 独立审查    |
| **自动修复**  | 严重问题阻断进度     | 自动修复明显问题，标记需人工确认的问题              |
| **安全审查**  | 无专门技能        | `/cso` 独立安全审查                    |

### 3.5 测试 & QA

| 维度         | Superpowers          | gstack                           |
| ---------- | -------------------- | -------------------------------- |
| **单元测试**   | **强制先行**，框架自带测试反模式参考 | `/ship` 自动引导测试框架，覆盖率审计           |
| **集成测试**   | 依赖计划阶段定义             | `/qa` 真实浏览器端到端测试                 |
| **浏览器测试**  | 不支持                  | **支持**（Playwright + 真实 Chromium） |
| **性能测试**   | 不支持                  | `/benchmark` Core Web Vitals     |
| **回归测试**   | 手动维护                 | `/qa` 自动为每个修复生成回归测试              |
| **iOS 测试** | 不支持                  | `/ios-qa` 真机 USB 测试              |

### 3.6 发布 & 部署

| 维度       | Superpowers    | gstack                         |
| -------- | -------------- | ------------------------------ |
| **发布流程** | 分支收尾时提供合并/PR选项 | `/ship` 一键：测试→推送→开PR           |
| **部署**   | 不涉及            | `/land-and-deploy` 合并→CI→部署→验证 |
| **监控**   | 不涉及            | `/canary` 部署后监控循环              |
| **文档更新** | 不涉及            | `/document-release` 自动更新所有文档   |

### 3.7 设计 & UI

| 维度        | Superpowers | gstack                                   |
| --------- | ----------- | ---------------------------------------- |
| **UI 设计** | 不涉及         | `/design-shotgun` 生成多版本 mockup           |
| **设计转代码** | 不涉及         | `/design-html` 生产级 HTML/CSS（Pretext 布局）  |
| **设计审查**  | 不涉及         | `/plan-design-review` + `/design-review` |
| **设计记忆**  | 不涉及         | `gstack-taste-update` 学习你的审美偏好           |

### 3.8 知识管理 & 记忆

| 维度         | Superpowers | gstack                            |
| ---------- | ----------- | --------------------------------- |
| **跨会话记忆**  | 无           | `/learn` 管理项目知识                   |
| **持久化知识库** | 无           | **GBrain**（Supabase/PGLite 向量数据库） |
| **代码搜索**   | 无           | `gbrain search` 语义代码搜索            |
| **团队共享**   | 无           | gstack 状态可推送到私有 git 仓库            |

### 3.9 安全 & 防护

| 维度         | Superpowers | gstack                            |
| ---------- | ----------- | --------------------------------- |
| **危险操作警告** | 无           | `/careful` 警告 rm -rf、DROP TABLE 等 |
| **编辑范围锁定** | 无           | `/freeze` 锁定仅编辑指定目录               |
| **浏览器安全**  | 不涉及         | 22MB ML 分类器 + 提示词注入防御             |
| **安全审计**   | 无           | `/cso` OWASP + STRIDE             |

### 3.10 安装 & 配置

| 维度        | Superpowers      | gstack                        |
| --------- | ---------------- | ----------------------------- |
| **安装复杂度** | **简单**（插件市场一键安装） | 中等（git clone + setup 脚本）      |
| **依赖**    | 无额外依赖            | 需要 Bun + Node.js + Playwright |
| **配置**    | 几乎零配置            | 需要配置 CLAUDE.md、可选 GBrain      |
| **团队同步**  | 各成员单独安装          | **Team Mode**：仓库内自动同步，无版本漂移   |
| **更新**    | 自动更新             | `/gstack-upgrade` 或自动检查       |

---

## 四、优缺点分析

### 4.1 Superpowers 优缺点

#### ✅ 优点

1. **零学习成本**：技能自动触发，你不需要记住任何命令，像"自动驾驶"一样工作
2. **强制开发纪律**：TDD、YAGNI、DRY 不是建议而是规则，特别适合培养良好习惯
3. **子代理隔离**：每个任务用新会话，避免长上下文导致的"幻觉"和"偏离计划"
4. **安装极简**：通过 Claude Code 插件市场一条命令安装，30秒搞定
5. **跨平台一致**：支持 7+ 种 AI Agent，切换工具时工作流不变
6. **专注编码**：不涉足设计、部署、监控等领域，专注做好"写代码"这一件事
7. **适合小白**：自动化的流程降低了认知负担，你只需回答 AI 的问题即可

#### ❌ 缺点

1. **无产品规划深度**：brainstorming 偏向技术实现，缺乏商业/产品层面的挑战
2. **无真实测试环境**：无法打开浏览器做端到端测试，无法验证 UI 实际效果
3. **无发布管理**：到代码写完就结束了，合并、部署、监控需要手动处理
4. **无安全审计**：没有专门的安全审查流程
5. **无跨会话记忆**：每次新开 Claude Code 都是全新开始，项目知识无法积累
6. **单线程执行**：无法并行推进多个功能，大型项目效率受限
7. **无设计支持**：如果项目需要 UI，Superpowers 完全不涉及

### 4.2 gstack 优缺点

#### ✅ 优点

1. **完整产品流水线**：从想法到生产部署的全流程覆盖，真正的"一人团队"
2. **角色专业化**：23个虚拟专家，每个都有明确职责，模拟真实团队协作
3. **真实浏览器 QA**：/qa 打开 Chromium 真实点击，能发现纯代码审查找不到的 bug
4. **设计-开发一体化**：/design-shotgun → /design-html 流水线，适合有前端界面的项目
5. **并行冲刺**：支持 10-15 个 Sprint 同时运行，大幅提升吞吐量
6. **跨模型审查**：/codex 让 OpenAI 和 Anthropic 互相找茬，减少 AI 盲点
7. **安全内建**：/cso 安全审计 + /careful 危险操作警告 + /freeze 编辑锁定
8. **知识积累**：GBrain 持久知识库 + /learn 跨会话学习，项目越用越聪明
9. **团队自动同步**：Team Mode 让新成员自动获得相同配置，无版本漂移
10. **文档自动化**：/document-release 自动保持 README、ARCHITECTURE 等文档最新

#### ❌ 缺点

1. **学习曲线陡峭**：需要记忆 23+ 个斜杠命令，知道何时用哪个角色
2. **安装较重**：需要 Bun、Node.js、Playwright，首次配置可能遇到问题
3. **需要主动触发**：不像 Superpowers 自动运行，你必须知道"现在该叫哪个专家"
4. **可能过度工程**：对于简单脚本或一次性工具，完整 Sprint 流程显得笨重
5. **依赖外部服务**：GBrain 需要 Supabase（或本地 PGLite），/browse 需要下载浏览器
6. **TDD 不强制**：虽然推荐测试，但不像 Superpowers 那样强制 RED-GREEN-REFACTOR
7. **配置维护**：CLAUDE.md 需要手动维护 gstack 区块，多项目时需要重复配置

---

## 五、选择建议：你该用哪一个

### 5.1 决策矩阵

根据你的**项目特征**和**个人情况**选择：

| 你的情况                      | 推荐选择            | 理由                              |
| ------------------------- | --------------- | ------------------------------- |
| **纯编程小白**，刚接触 Claude Code | **Superpowers** | 自动触发、零配置、强制 TDD 帮你养成好习惯         |
| **做内部工具/后台系统**，无 UI       | **Superpowers** | 不需要设计和浏览器测试，Superpowers 更轻量     |
| **做面向用户的 Web/App 产品**，有界面 | **gstack**      | /design-shotgun + /qa 浏览器测试不可替代 |
| **从0到1创业/MVP探索**          | **gstack**      | /office-hours 的产品拷问能避免方向错误      |
| **已有成熟产品，日常维护迭代**         | **Superpowers** | 轻量级 TDD 迭代，不需要完整 Sprint         |
| **需要并行推进多个功能**            | **gstack**      | Conductor 支持 10-15 个并行 Sprint   |
| **团队多人协作**                | **gstack**      | Team Mode 自动同步，GBrain 共享知识      |
| **对安全要求极高**（金融/医疗）        | **gstack**      | /cso 安全审计 + /careful 危险操作防护     |
| **在柬埔寨网络环境不稳定**           | **Superpowers** | 不依赖外部服务（Supabase、浏览器下载等）        |
| **只想快速写脚本解决问题**           | **都不用**         | 直接让 Claude Code 写，框架反而拖慢        |

### 5.2 针对你的具体建议

结合你的背景（柬埔寨太阳能 PAYGO 项目、编程小白、需要商业文档和系统架构），**我的明确建议是**：

> **以 gstack 为主框架，在编码实现阶段吸收 Superpowers 的 TDD 纪律。**

**理由**：

1. **PAYGO 平台有用户界面**：你需要管理后台、支付界面、设备监控面板，gstack 的 /design-shotgun 和 /qa 能确保 UI 可用性
2. **项目涉及资金和安全**：太阳能设备远程控制 + 支付 = 高风险，gstack 的 /cso 安全审计是必须的
3. **从0到1的产品探索**：/office-hours 能帮你验证"柬埔寨农村太阳能 PAYGO"这个商业模式是否成立
4. **需要并行推进**：硬件对接、支付集成、MFI 合作、移动端 App 可以并行 Sprint
5. **团队未来会扩大**：gstack 的 Team Mode 和 GBrain 为后续团队成员入职做准备
6. **Superpowers 的 TDD 可以手动执行**：在 gstack 的 Build 阶段，你可以要求 Claude 遵循 RED-GREEN-REFACTOR（见下文"结合方案"）

---

## 六、双框架结合使用方案

### 6.1 核心思路：gstack 管流程，Superpowers 管纪律

```
┌─────────────────────────────────────────────────────────────┐
│                    gstack 负责"做什么"                        │
│  /office-hours → /plan-ceo-review → /plan-eng-review        │
│  → /autoplan → /review → /qa → /ship                        │
├─────────────────────────────────────────────────────────────┤
│                    Superpowers 负责"怎么做"                   │
│  在 Build 阶段，要求 Claude 遵循：                           │
│  1. RED-GREEN-REFACTOR（测试先行）                            │
│  2. YAGNI（不做过度设计）                                     │
│  3. 子代理隔离（复杂任务拆分为独立 Claude Code 会话）          │
│  4. 任务级代码审查（每个微任务完成后自检）                     │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 具体结合方案（PAYGO 项目示例）

#### Phase 1：产品定义（gstack 主导）

```bash
# 在 VSCode 终端中打开 Claude Code
$ claude

# 1. 产品拷问 —— 验证 PAYGO 模式是否成立
/office-hours
# → 描述：我想在柬埔寨农村卖太阳能板，用 PAYGO 模式，和 MFI 合作
# → AI 会问：农民痛点是什么？为什么不用电网？MFI 风险如何控制？
# → 输出：DESIGN.md（保存到项目根目录）

# 2. CEO 审查 —— 挑战假设，寻找更好方案
/plan-ceo-review
# → AI 可能说："你做的是太阳能租赁，但农民真正需要的是稳定电力+
#    手机充电+夜间照明，PAYGO 只是支付手段，核心是信任机制"
# → 输出：更新后的 DESIGN.md

# 3. 工程规划 —— 锁定架构
/plan-eng-review
# → 输出：ARCHITECTURE.md（数据流图、API 设计、测试矩阵）
```

#### Phase 2：设计探索（gstack 主导）

```bash
# 4. 生成管理后台的 UI 方案
/design-shotgun
# → 描述：太阳能设备管理后台，显示设备状态、支付记录、告警
# → AI 生成 4-6 个 mockup 变体，打开浏览器对比板
# → 你挑选喜欢的，给出反馈（"更多留白"、"用蓝色主题"）

# 5. 将选中的 mockup 转为生产 HTML
/design-html
# → 输出：React/Vue 组件（自动检测你的技术栈）
```

#### Phase 3：编码实现（gstack + Superpowers 纪律）

```bash
# 6. 自动规划（可选）
/autoplan
# → 自动运行 CEO → 设计 → 工程 → DX 审查
# → 输出：详细实施计划

# 7. 开始编码 —— 这里引入 Superpowers 的 TDD 纪律
# 在 Claude Code 中手动要求：
# "请按照测试驱动开发的方式实现 [功能名]。
#  先写失败的测试，再写最小实现，再重构。
#  每个测试用例控制在 2-5 分钟内完成。
#  完成后进行自我审查。"

# 8. 代码审查
/review
# → Staff Engineer 角色审查代码质量
# → 自动修复明显问题，标记需确认的问题

# 9. 安全审计（PAYGO 项目必须）
/cso
# → OWASP Top 10 + STRIDE 威胁建模
# → 检查支付接口、设备远程控制、用户数据安全
```

#### Phase 4：测试 & 发布（gstack 主导）

```bash
# 10. 端到端测试（关键！）
/qa https://staging.paygo.yourcompany.com
# → 打开真实浏览器，测试：
#   - 用户注册流程
#   - 设备绑定流程
#   - 支付流程（测试环境）
#   - 管理员查看设备状态
# → 发现 bug → 自动修复 → 生成回归测试

# 11. 性能基准
/benchmark
# → 测量页面加载时间、Core Web Vitals
# → 柬埔寨农村网络慢，性能很重要

# 12. 发布
/ship
# → 同步 main → 运行测试 → 覆盖率审计 → 推送 → 开 PR

# 13. 部署验证
/land-and-deploy
# → 合并 PR → 等待 CI → 部署 → 验证生产环境
```

#### Phase 5：知识沉淀（gstack 主导）

```bash
# 14. 文档更新
/document-release
# → 自动更新 README、API 文档、部署指南

# 15. 经验积累
/learn
# → 记录："柬埔寨 Metfone 短信网关的编码要注意..."
# → 记录："PAYGO Token 生成算法在 [文件] 中"
# → 下次会话自动回忆
```

### 6.3 在 gstack 中手动实施 Superpowers 纪律的 Prompt 模板

在编码阶段，你可以通过以下 Prompt 让 Claude 遵循 Superpowers 的核心原则：

```markdown
## 编码纪律（Superpowers 风格）

1. **测试先行（TDD）**：
   - 先写失败的测试（RED）
   - 写最小代码让测试通过（GREEN）
   - 重构优化（REFACTOR）
   - 严禁在测试之前写实现代码

2. **任务拆解**：
   - 将功能拆分为 2-5 分钟可完成的微任务
   - 每个任务明确：修改哪些文件、预期结果、如何验证

3. **YAGNI 原则**：
   - 不实现当前不需要的功能
   - 不提前抽象，等重复出现 3 次再重构

4. **子代理隔离**：
   - 复杂任务（>10分钟）拆分为独立 Claude Code 会话
   - 避免长上下文污染

5. **即时审查**：
   - 每个微任务完成后自我审查
   - 检查：是否符合需求、是否有明显 bug、是否过度设计
```

---

## 七、实际项目最佳实践

### 7.1 项目初始化清单

```bash
# 1. 创建项目目录
mkdir paygo-platform && cd paygo-platform

# 2. 初始化 git
git init

# 3. 安装 gstack（30秒）
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup

# 4. 配置团队模式（推荐）
cd ~/paygo-platform
(cd ~/.claude/skills/gstack && ./setup --team) && ~/.claude/skills/gstack/bin/gstack-team-init required
git add .claude/ CLAUDE.md
git commit -m "require gstack for AI-assisted work"

# 5. 创建基础目录结构
mkdir -p src/{api,models,services,utils} tests/{unit,integration,e2e} docs designs

# 6. 初始化技术栈（根据你的选择）
# FastAPI 示例：
# echo "fastapi==0.115.0\nuvicorn==0.32.0\npytest==8.3.0" > requirements.txt

# 7. 创建初始 CLAUDE.md（见第8章模板）
# 8. 创建 AGENTS.md（如果使用 OpenClaw）
```

### 7.2 日常开发工作流

```bash
# 每天早上：
# 1. 同步 gstack
/gstack-upgrade

# 2. 查看今日计划（如果有并行 Sprint）
# 在 Conductor 中查看各会话状态

# 开发新功能时：
# 3. 如果是大功能（>2小时），先开 /office-hours
/office-hours
# → 确认方向正确后再编码

# 4. 工程规划（如果是架构变更）
/plan-eng-review

# 5. 编码（遵循 Superpowers TDD 纪律）
# 手动要求 Claude："按 TDD 方式实现 [功能]"

# 6. 自测后请求审查
/review

# 7. 安全审计（支付/设备相关代码必须）
/cso

# 8. 浏览器测试（有 UI 的功能）
/qa http://localhost:8000

# 9. 发布
/ship

# 每周五：
# 10. 复盘
/retro
```

### 7.3 柬埔寨网络环境适配建议

由于你在柬埔寨，网络可能不稳定，建议：

1. **使用本地 PGLite 替代 Supabase**：
   
   ```bash
   /setup-gbrain
   # 选择 "PGLite local" 选项
   # 零网络依赖，30秒完成
   ```

2. **浏览器测试缓存**：
   
   ```bash
   # /qa 首次会下载 Chromium（约 100MB）
   # 下载后缓存到 ~/Library/Caches/ms-playwright/
   # 不要清理此目录，避免重复下载
   ```

3. **离线模式**：
   
   ```bash
   # gstack 大部分技能本地运行，不需要持续联网
   # /codex 需要 OpenAI API，可跳过
   # /design-shotgun 需要 GPT Image，可先用文字描述替代
   ```

4. **Team Mode 本地同步**：
   
   ```bash
   # 团队模式通过 git 同步，不依赖外部服务
   # 确保 .claude/ 和 CLAUDE.md 在版本控制中
   ```

### 7.4 与 MFI 合作项目的特殊注意

PAYGO + MFI 模式涉及金融合规，建议：

1. **安全优先**：
   
   - 每次涉及支付/用户数据的 PR 必须运行 `/cso`
   - 使用 `/guard` 开启完整安全模式（/careful + /freeze）

2. **审计追踪**：
   
   - 启用 `gstack-config set checkpoint_mode continuous`
   - 所有修改自动提交为 WIP commit，保留完整审计链

3. **文档同步**：
   
   - MFI 需要技术文档，使用 `/document-release` 保持文档最新
   - 生成合规所需的 API 文档、数据流图

4. **多语言支持**：
   
   - 在 CLAUDE.md 中明确要求支持高棉语（Khmer）
   - /design-review 时检查高棉语字体和排版

---

## 八、CLAUDE.md 与 AGENTS.md 编程规范定义

### 8.1 CLAUDE.md 完整模板（适用于 gstack + Superpowers 混合模式）

```markdown
# CLAUDE.md — PAYGO 太阳能平台

## 项目概述
- **名称**：柬埔寨太阳能 PAYGO 管理平台
- **技术栈**：Python FastAPI + PostgreSQL + React（或你实际使用的）
- **目标用户**：柬埔寨农村家庭、MFI 信贷员、平台管理员
- **核心功能**：设备管理、支付追踪、PAYGO Token 生成、告警系统

## gstack 配置
Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /open-gstack-browser, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /pair-agent, /careful, /freeze,
/guard, /unfreeze, /gstack-upgrade, /learn.

## 编码规范（Superpowers 风格）

### 1. 测试驱动开发（强制）
- **RED**：先写失败的测试，明确预期行为
- **GREEN**：写最小代码让测试通过，不追求完美
- **REFACTOR**：测试通过后优化代码结构
- **严禁**：在测试之前写实现代码（除非是探索性原型，需明确标记）

### 2. 任务拆解原则
- 每个任务控制在 2-5 分钟可完成
- 任务描述必须包含：
  - 修改的文件路径（精确到行号范围）
  - 预期输入/输出
  - 验证方法（运行哪个测试、查看哪个日志）

### 3. YAGNI 原则
- 不实现当前 Sprint 未规划的功能
- 遇到"以后可能用到"的代码：注释标记 TODO，不实现
- 抽象原则：重复出现 3 次才提取为公共函数/类

### 4. 代码质量标准
- 函数长度：不超过 50 行（特殊情况需注释说明）
- 圈复杂度：不超过 10
- 命名：使用英文，语义明确（柬埔寨业务术语保留高棉语拼音注释）
- 注释：解释"为什么"而非"做什么"

### 5. 安全规范（PAYGO 项目特殊要求）
- 所有支付相关代码必须通过 /cso 审查
- 用户密码/PIN 必须使用 bcrypt 哈希，禁止明文存储
- PAYGO Token 生成必须使用加密安全随机数
- 设备远程控制命令必须验证签名
- 所有 API 端点必须验证 JWT 令牌

### 6. 数据库规范
- 使用 PostgreSQL 15+
- 所有表必须有 created_at 和 updated_at 字段
- 外键必须建立索引
- 支付记录表禁止物理删除，使用软删除（deleted_at）
- 敏感字段（手机号、身份证号）加密存储

### 7. API 设计规范
- RESTful 风格，使用名词复数（/devices, /payments）
- 状态码：200（成功）, 201（创建）, 400（客户端错误）, 401（未授权）, 403（禁止）, 404（不存在）, 500（服务器错误）
- 错误响应统一格式：{ "error": "错误代码", "message": "人类可读描述", "details": {} }
- 分页：使用 cursor-based，避免 OFFSET

### 8. 高棉语本地化
- 所有用户-facing 字符串必须支持 i18n
- 高棉语使用 Noto Sans Khmer 字体
- 日期格式：柬埔寨使用佛历或公历，需可配置
- 货币：瑞尔（KHR）和美元（USD）双币种支持

### 9. 文档同步
- 每次 /ship 后运行 /document-release
- README 必须包含：安装步骤、环境变量、API 文档链接
- ARCHITECTURE.md 必须随架构变更更新

### 10. 性能要求
- API 响应时间：P95 < 500ms（柬埔寨网络慢）
- 页面首屏加载：3G 网络下 < 3 秒
- 数据库查询：N+1 查询禁止出现
- 缓存策略：Redis 缓存热点数据，TTL 5 分钟

## 项目结构
```

paygo-platform/
├── src/
│   ├── api/          # FastAPI 路由
│   ├── models/       # SQLAlchemy 模型
│   ├── services/     # 业务逻辑
│   ├── utils/        # 工具函数
│   └── config.py     # 配置管理
├── tests/
│   ├── unit/         # 单元测试（pytest）
│   ├── integration/  # 集成测试
│   └── e2e/          # 端到端测试（Playwright）
├── docs/             # 项目文档
├── designs/          # UI 设计稿
├── migrations/       # Alembic 数据库迁移
├── scripts/          # 运维脚本
├── CLAUDE.md         # 本文件
└── README.md

```
## 环境变量
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/paygo
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=your-secret-key
PAYGO_TOKEN_SECRET=another-secret
METFONE_SMS_API_KEY=xxx
MFI_API_ENDPOINT=https://...
```

## 常用命令

```bash
# 运行测试
pytest

# 运行特定测试
pytest tests/unit/test_payments.py -v

# 数据库迁移
alembic revision --autogenerate -m "description"
alembic upgrade head

# 启动开发服务器
uvicorn src.main:app --reload

# 代码格式化
black src/ tests/
isort src/ tests/

# 类型检查
mypy src/
```

## GBrain Search Guidance

When searching for code patterns, APIs, or implementation details, prefer using gbrain search over grep when GBrain is available. Use gbrain search for semantic queries like "how do we handle PAYGO token generation" or "find the payment retry logic". Fall back to grep for exact string matches or when gbrain is unavailable.

```
### 8.2 AGENTS.md 模板（适用于 OpenClaw 集成）

```markdown
# AGENTS.md — OpenClaw 配置

## 角色定义

### Coding Tasks（编码任务）
When spawning Claude Code sessions for coding work, tell the session to use gstack skills. Include these examples:

- **安全审计**："Load gstack. Run /cso"
- **代码审查**："Load gstack. Run /review"
- **QA 测试 URL**："Load gstack. Run /qa https://..."
- **端到端构建功能**："Load gstack. Run /autoplan, implement the plan, then run /ship"
- **规划前构建**："Load gstack. Run /office-hours then /autoplan. Save the plan, don't implement."
- **日常迭代**："Load gstack. Run /review then /qa http://localhost:8000"
- **部署**："Load gstack. Run /land-and-deploy"

### 简单任务（无需 gstack）
For trivial changes (fix typo, update README, one-line bug fix), spawn Claude Code without gstack to save overhead.

## 决策原则

1. **任何涉及支付、设备控制、用户数据的代码变更** → 必须触发 /cso
2. **任何 UI 变更** → 必须触发 /qa
3. **任何架构变更** → 必须先 /plan-eng-review
4. **任何新功能** → 必须先 /office-hours 或 /plan-ceo-review
5. **周五下班前** → 触发 /retro 记录本周进展

## 跨代理协调

### /pair-agent 使用场景
When you need multiple AI agents to look at the same website:
1. In Claude Code: `/pair-agent`
2. Select the other agent (OpenClaw, Hermes, etc.)
3. Copy the setup block printed by the skill
4. Paste it into the other agent's chat
5. Both agents now share the same browser, each in isolated tabs

### 模型选择策略
- **快速任务**（代码补全、简单重构）：Claude Sonnet（快且便宜）
- **复杂架构**（系统设计、安全审计）：Claude Opus（深度推理）
- **第二意见**（关键 PR 审查）：`/codex` 调用 OpenAI Codex
- **设计探索**：`/design-shotgun` 自动路由到 GPT Image

## 记忆管理

### GBrain 同步
After each significant coding session:
1. Run `/sync-gbrain` to re-index the codebase
2. Key learnings are automatically saved to GBrain
3. Cross-project patterns are shared via gstack-brain-init

### 本地记忆（无 GBrain 时）
If GBrain is not available, maintain a `LEARNINGS.md` file in the project root:
- Record: "Metfone SMS gateway returns 202 but delays delivery by 30s"
- Record: "PAYGO token must be 16 chars to fit on SMS"
- Record: "Khmer font rendering breaks on Android 12 WebView"
```

### 8.3 纯 Superpowers 模式的 CLAUDE.md（轻量版）

如果你决定**只用 Superpowers**，使用以下简化模板：

```markdown
# CLAUDE.md — 轻量项目

## 项目概述
[你的项目描述]

## Superpowers 技能
本仓库使用 Superpowers 框架。技能会自动触发，无需手动调用。
核心流程：Brainstorming → Git Worktrees → Writing Plans → Subagent Development → TDD → Code Review → Finish Branch.

## 编码规范

### 测试驱动开发（强制）
1. 先写失败的测试（RED）
2. 写最小代码让测试通过（GREEN）
3. 重构优化（REFACTOR）
4. 不写测试不实现功能

### YAGNI
- 不提前实现未规划功能
- 重复3次才抽象

### 任务粒度
- 每个任务 2-5 分钟
- 明确文件路径和验证方法

## 项目结构
[你的目录结构]

## 常用命令
[你的命令]
```

---

## 九、快速上手路线图

### Week 1：环境搭建

| 天数      | 任务                | 命令/操作                                          |
| ------- | ----------------- | ---------------------------------------------- |
| Day 1   | 安装 gstack         | `git clone ... && ./setup`                     |
| Day 2   | 配置 CLAUDE.md      | 复制第8章模板，根据项目调整                                 |
| Day 3   | 初始化项目             | `git init` + 创建目录结构 + 安装依赖                     |
| Day 4   | 配置 Team Mode      | `./setup --team` + `gstack-team-init required` |
| Day 5   | 第一次 /office-hours | 描述你的 PAYGO 想法，让 AI 挑战你                         |
| Day 6-7 | 第一次 /autoplan     | 体验完整流水线                                        |

### Week 2：首个 Sprint

| 天数        | 任务               | 目标          |
| --------- | ---------------- | ----------- |
| Day 8-9   | /plan-eng-review | 确定技术架构      |
| Day 10-12 | 编码 + /review     | 实现核心模型和 API |
| Day 13    | /cso             | 安全审计        |
| Day 14    | /qa + /ship      | 测试并发布第一个版本  |

### Week 3：建立节奏

| 天数        | 任务                | 目标             |
| --------- | ----------------- | -------------- |
| Day 15-17 | 并行 Sprint         | 尝试同时推进 2-3 个功能 |
| Day 18    | /retro            | 第一次复盘          |
| Day 19-20 | /document-release | 完善项目文档         |
| Day 21    | /learn            | 整理项目知识         |

### Month 2+：持续优化

- 每周五：/retro
- 每个功能：/office-hours（大功能）或 /review（小功能）
- 每个 PR：/review + /qa（有 UI）或 /review + /codex（纯后端）
- 每月：/cso（全量安全审计）
- 持续：/learn 积累知识

---

## 十、常见问题 FAQ

### Q1：我是编程小白，gstack 23个命令记不住怎么办？

**A**：不需要一次记住全部。先掌握这 6 个核心命令：

1. `/office-hours` — 开始新功能前用
2. `/autoplan` — 一键规划
3. `/review` — 编码后审查
4. `/qa` — 有 UI 时测试
5. `/ship` — 发布
6. `/cso` — 安全审计

其他命令可以等遇到具体场景时再学。gstack 会主动提示你该用哪个命令。

### Q2：Superpowers 和 gstack 会冲突吗？

**A**：不会冲突。Superpowers 是"嵌入式技能"，通过插件市场安装；gstack 是"命令式技能"，通过 git clone 安装。两者可以共存：

- Superpowers 的技能会在适当场景自动触发（如检测到你在写代码时自动启动 TDD）
- gstack 的技能需要你手动调用
- 如果你希望 Superpowers 不自动触发，可以在 CLAUDE.md 中明确禁用

### Q3：柬埔寨网络不好，gstack 哪些功能会受影响？

**A**：以下功能需要稳定网络：

- `/codex`（需要 OpenAI API）
- `/design-shotgun`（需要 GPT Image）
- GBrain Supabase 模式（需要连接 Supabase）
- 首次 `/qa`（需要下载 Chromium，约 100MB）

**替代方案**：

- 跳过 `/codex`，用 `/review` 代替
- 设计阶段用文字描述代替 `/design-shotgun`
- GBrain 使用本地 PGLite 模式
- Chromium 下载一次后缓存，不再重复下载

### Q4：我的项目很简单，需要这么复杂的框架吗？

**A**：如果项目满足以下任一条件，建议用框架：

- 预计开发时间 > 1 周
- 有用户界面（Web/App）
- 涉及资金/用户数据/设备控制
- 需要长期维护

如果是一次性脚本、内部工具、或实验性原型，可以直接用 Claude Code 原生功能，不装任何框架。

### Q5：怎么在 VSCode 中使用这些命令？

**A**：

1. 在 VSCode 中打开终端（Ctrl+`）
2. 运行 `claude` 启动 Claude Code
3. 在 Claude Code 交互界面中输入斜杠命令（如 `/office-hours`）
4. Claude Code 会执行命令并返回结果
5. 你可以继续和 Claude 对话，或输入下一个命令

### Q6：Claude Code 的上下文长度不够怎么办？

**A**：

- gstack 的 `/autoplan` 会自动将大任务拆分为小任务
- Superpowers 的子代理机制每个任务用新会话
- 对于超大项目，使用 Conductor 并行 Sprint，每个 Sprint 专注一个模块
- 定期运行 `/sync-gbrain` 将代码索引到向量数据库，减少上下文依赖

### Q7：怎么让团队成员也用同样的配置？

**A**：

1. 使用 gstack Team Mode：
   
   ```bash
   (cd ~/.claude/skills/gstack && ./setup --team) && ~/.claude/skills/gstack/bin/gstack-team-init required
   git add .claude/ CLAUDE.md
   git commit -m "require gstack for AI-assisted work"
   ```

2. 团队成员 clone 仓库后，Claude Code 会自动检测到 `.claude/` 目录并提示安装 gstack

3. 所有人的技能版本保持一致，自动更新

### Q8：如果我想从 Superpowers 迁移到 gstack，怎么做？

**A**：

1. 保留 Superpowers 插件（不卸载）
2. 按第6章"结合方案"安装 gstack
3. 在 CLAUDE.md 中同时保留 Superpowers 的 TDD 规范
4. 逐步将工作流从"自动触发"转为"命令触发"
5. 一个月后，如果 gstack 完全覆盖你的需求，可以卸载 Superpowers

---

## 附录：命令速查表

### gstack 核心命令（按使用频率排序）

| 命令                  | 用途       | 使用频率      |
| ------------------- | -------- | --------- |
| `/office-hours`     | 产品方向拷问   | 每个大功能前    |
| `/autoplan`         | 自动规划流水线  | 每个大功能前    |
| `/review`           | 代码审查     | 每个功能完成后   |
| `/qa`               | 浏览器端到端测试 | 有 UI 的功能  |
| `/ship`             | 发布 PR    | 功能完成后     |
| `/cso`              | 安全审计     | 支付/安全相关代码 |
| `/land-and-deploy`  | 部署到生产    | 发布日       |
| `/retro`            | 每周复盘     | 每周五       |
| `/learn`            | 知识积累     | 随时        |
| `/document-release` | 文档更新     | 发布后       |

### Superpowers 核心技能（自动触发）

| 技能                               | 触发时机   | 作用     |
| -------------------------------- | ------ | ------ |
| `brainstorming`                  | 开始编码前  | 需求细化   |
| `using-git-worktrees`            | 设计批准后  | 创建隔离分支 |
| `writing-plans`                  | 设计批准后  | 任务拆解   |
| `subagent-driven-development`    | 计划批准后  | 子代理编码  |
| `test-driven-development`        | 编码阶段   | 强制 TDD |
| `requesting-code-review`         | 任务完成后  | 自动审查   |
| `finishing-a-development-branch` | 所有任务完成 | 分支收尾   |

---

> **结语**：AI 编程框架不是银弹，它们是"纪律的外骨骼"。选择适合你当前阶段的框架，建立稳定的工作节奏，比追求完美的工具链更重要。对于你的 PAYGO 项目，建议从 gstack 的 6 个核心命令开始，逐步扩展，同时保持 Superpowers 的 TDD 纪律。祝你在柬埔寨的太阳能事业顺利！

---

*报告生成时间：2026-05-22*  
*基于 superpowers v2026.05 和 gstack v0.19 版本信息*
