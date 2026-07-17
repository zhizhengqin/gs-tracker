# GS-Tracker 京东云生产部署设计

> **日期**: 2026-07-17  
> **版本**: v1.0  
> **目标**: 将 GS-Tracker 从本地脚本升级为京东云服务器上的长期 Web 服务 + 定时任务  
> **适用服务器**: 京东云 ECS 4 核 16G / 100GB SSD / 5Mbps 带宽 / 1000GB 月流量

---

## 1. 设计目标

1. **Web 化访问**: 通过浏览器查看生成的 HTML 报告和历史报告列表。
2. **自动化运行**: 每季度 13F 截止日后自动抓取、分析、生成报告并推送通知。
3. **稳定可靠**: 服务异常自动重启，日志集中管理，数据持久化不丢。
4. **安全合规**: 最小化攻击面，API 密钥不落地容器镜像，HTTPS 可选。
5. **便于运维**: 一键启动/停止/更新，支持 CI/CD 对接 GStack `/ship` 流程。

---

## 2. 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                        京东云 ECS                            │
│              4C16G / 100GB SSD / Ubuntu 24.04 LTS           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   用户 / CDN / 域名 ──→  Nginx (Docker) :80 / :443          │
│                              │                               │
│                              ▼                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              gs-tracker-app (Docker)                 │   │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │   │
│   │  │ Gunicorn     │  │ FastAPI/     │  │ 定时任务  │  │   │
│   │  │ (WSGI服务器) │  │ Flask Web    │  │ APScheduler│  │   │
│   │  └──────────────┘  └──────────────┘  └──────────┘  │   │
│   │                                                      │   │
│   │  挂载卷: ./data  → SQLite + 原始 XML                │   │
│   │          ./output/reports → HTML 报告               │   │
│   │          ./templates → Jinja2 模板                  │   │
│   │          .env → 环境变量（宿主机挂载，不打包进镜像）│   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              Watchtower (可选，Docker)               │   │
│   │  自动检测镜像更新并重启应用容器                       │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
│   systemd: docker-compose.service → 开机自动拉起所有容器    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 操作系统与组件选型

### 3.1 操作系统

- **推荐**: **Ubuntu Server 24.04 LTS (amd64)**
- **理由**:
  - 5 年长期支持（至 2029 年 4 月），安全补丁稳定
  - Python 3.12 预装，apt 生态完善
  - Docker 官方仓库原生支持，文档丰富
  - GStack/Superpowers 社区示例多基于 Ubuntu

### 3.2 必装系统组件

| 组件 | 版本/方式 | 用途 |
|------|-----------|------|
| Docker CE | 27.x | 容器运行时 |
| Docker Compose Plugin | v2.x | 多容器编排 |
| ufw / iptables | 系统自带 | 防火墙，仅开放 22/80/443 |
| fail2ban | 最新 apt 版 | SSH 暴力破解防护 |
| unattended-upgrades | 系统自带 | 自动安装安全更新 |
| logrotate | 系统自带 | 日志轮转 |
| cron | 系统自带 | 系统级兜底定时任务 |

### 3.3 应用组件

| 组件 | 用途 |
|------|------|
| Python 3.11/3.12 | 运行环境（容器内固定版本，避免宿主机污染） |
| FastAPI + Gunicorn | Web 服务与 WSGI 服务器 |
| APScheduler | 季度报告自动检测与任务调度 |
| SQLite | 轻量持久化（当前阶段，未来可切 PostgreSQL） |
| Nginx | 反向代理、静态报告托管、HTTPS 终止 |
| Jinja2 + Matplotlib | 报告模板与图表 |

---

## 4. 数据流

### 4.1 正常请求流（查看报告）

```
用户浏览器
    │
    ▼
Nginx :80/:443
    │
    ├── 静态 HTML 报告 → 直接返回 ./output/reports/*.html
    │
    └── 动态请求 /api/* → 转发到 gs-tracker-app:8000
                              │
                              ▼
                         FastAPI 路由处理
                              │
                              ▼
                         SQLite 查询 / 文件系统读取
```

### 4.2 季度分析任务流

```
APScheduler 触发 (每季度截止后 + 每周轮询)
    │
    ▼
SEC EDGAR 抓取 → 解析 XML → 写入 SQLite
    │
    ▼
季度对比计算
    │
    ▼
调用 Claude API 生成分析
    │
    ▼
生成 HTML 报告 + 图表
    │
    ▼
推送通知（邮件/飞书/钉钉）
    │
    ▼
写入 analysis_reports 表并记录日志
```

---

## 5. 错误处理与可靠性

| 场景 | 策略 |
|------|------|
| 容器崩溃 | Docker `restart: unless-stopped` + systemd 开机自启 |
| SEC EDGAR 429/超时 | 指数退避重试 3 次，失败后记录并下次调度重试 |
| Claude API 失败 | 重试 3 次，失败时生成"分析暂不可用"占位报告 |
| 磁盘满 | logrotate 轮转日志；监控阈值 80% 告警 |
| 密钥泄露 | `.env` 不提交 git，不打包进镜像，宿主机只读挂载 |
| 服务启动失败 | `docker compose up` 日志输出到 journald，便于排查 |

---

## 6. 安全策略

1. **防火墙**: ufw 仅开放 22(SSH)、80(HTTP)、443(HTTPS)。
2. **SSH 加固**: 禁用密码登录，使用密钥对；修改默认端口（可选）。
3. **HTTPS**: 推荐使用京东云免费 SSL 证书或 Let's Encrypt + Nginx。
4. **容器最小化**: 使用 `python:3.11-slim` 镜像，不安装无用包。
5. **密钥管理**: 环境变量从宿主机 `.env` 挂载，版本控制中保留 `.env.example`。
6. **备份**: 每日压缩备份 `data/` 到对象存储或本地另一目录。

---

## 7. 运维 SOP

| 操作 | 命令 |
|------|------|
| 查看日志 | `docker compose logs -f app` |
| 重启服务 | `docker compose restart app` |
| 手动触发分析 | `docker compose exec app python src/main.py --run-now` |
| 更新部署 | `git pull && docker compose up -d --build` |
| 备份数据 | `tar czf backup-$(date +%F).tar.gz data/` |
| 查看定时任务 | `docker compose exec app python src/scheduler.py --list` |

---

## 8. 成功标准

1. 浏览器访问 `http://<服务器IP>/` 能看到报告列表。
2. 访问 `http://<服务器IP>/reports/2026-Q1.html` 能看到完整 HTML 报告。
3. 手动触发 `docker compose exec app python src/main.py --run-now` 能成功生成新报告。
4. 服务器重启后所有容器自动恢复。
5. `.env` 中的 API 密钥不暴露在镜像或代码仓库中。

---

*本设计基于 GStack + Superpowers 双框架：Superpowers 负责代码编写，GStack 负责评审与发布流程。*
