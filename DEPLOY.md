# GS-Tracker 京东云部署手册（小白版）

> **最终效果**：你在自己电脑上改代码 → `git push` 到 GitHub → GitHub 自动登录你的京东云服务器 → 自动拉代码、重建、重启。和 Railway 体验一样，push 完什么都不用管。
>
> **你的服务器**：Ubuntu 24.04，4 核 16G，公网 IP `111.228.23.109`
>
> **全程约 30~40 分钟**，每一步都是复制粘贴命令，不需要懂原理。遇到问题先翻最后的「故障排查」。

---

## 准备东西（先确认都有）

| 物品 | 说明 |
|---|---|
| 京东云控制台账号 | 能登录 jdcloud.com，能看到这台实例 |
| 服务器 root 密码 | 创建实例时设的那个；忘了的话在控制台「重置密码」 |
| 你本机的终端 | Mac 用「终端」App（你已经有了） |
| Kimi 的 token | 就是你本机 shell 里 `ANTHROPIC_AUTH_TOKEN` 的值，第 4 步会教你怎么查 |

手册里所有 `root@服务器#` 开头的命令都是在**服务器上**执行；`本机$` 开头的是在**你自己的 Mac 上**执行。

---

## 第 1 步：登录服务器

打开 Mac 的「终端」，输入（把密码换成你的 root 密码）：

```bash
本机$ ssh root@111.228.23.109
```

- 第一次连接会问 `Are you sure you want to continue connecting?` → 输入 `yes` 回车
- 然后输入 root 密码（**输入时屏幕什么都不显示，是正常的**，输完回车）
- 看到 `root@lavm-xxxxx:~#` 就说明进去了

> 如果 ssh 连不上：去京东云控制台 → 云主机 → 实例详情 →「远程连接」（VNC 网页版），在网页里登录也一样，只是粘贴不方便。

**后面第 2~6 步的命令全都在服务器上执行。**

---

## 第 2 步：安装 Docker

复制下面整段，粘贴到服务器终端，回车：

```bash
apt update && apt install -y docker.io docker-compose-v2 git curl
```

装完启动 Docker 并设置开机自启：

```bash
systemctl enable --now docker
```

**再配一个国内镜像加速器**（不配的话，从京东云拉 Docker 官方镜像大概率卡死或超时）：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
EOF
systemctl restart docker
```

验证安装成功：

```bash
docker --version
docker compose version
```

看到类似 `Docker version 26.x.x` 和 `Docker Compose version v2.x.x` 就 OK。

---

## 第 3 步：把代码拉到服务器

**3.1 先配 GitHub 镜像加速**（必做！国内云服务器直连 GitHub 经常 TLS 断连。配这一次，以后克隆和**每次自动部署拉代码**都会自动走镜像）：

```bash
git config --global url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"
```

**3.2 克隆代码**：

```bash
cd ~
git clone https://github.com/zhizhengqin/gs-tracker.git
cd gs-tracker
```

> 仓库是公开的，不需要账号密码。看到 `README.md`、`src/`、`deploy/` 这些文件就对了。
> 如果 clone 还是报 `GnuTLS recv error` 或超时，换备用镜像再试一次：
> ```bash
> git config --global url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"
> git clone https://github.com/zhizhengqin/gs-tracker.git
> ```

---

## 第 4 步：创建配置文件 .env（最关键的一步）

`.env` 是存放密钥的配置文件，**不会**上传到 GitHub，只在服务器上。

**4.1 先在你自己的 Mac 上找到 Kimi token**（另开一个终端窗口，别关服务器那个）：

token 存在 Claude Code 的配置文件里（注意：`echo $ANTHROPIC_AUTH_TOKEN` 在你自己的终端是空的，因为变量是 Claude Code 启动时注入的，不在你的 shell 里）。运行：

```bash
本机$ cat ~/.claude/settings.json
```

在输出里找到 `"ANTHROPIC_AUTH_TOKEN": "sk-kimi-......"` 这一行，**复制引号里面那串 `sk-kimi-` 开头的值**（这是你的密钥，别发给任何人、别截图发到群里）。

**4.2 回到服务器窗口**，创建配置文件：

```bash
cp .env.example .env
nano .env
```

进入 nano 编辑器后，用方向键移动光标，**只需要改两处**：

1. 找到 `ANTHROPIC_AUTH_TOKEN=sk-kimi-...` 这一行，把 `sk-kimi-...` 整段删掉，粘贴你刚才复制的那串密钥
2. 找到 `SEC_USER_AGENT="GS-Tracker your-email@example.com"`，把 `your-email@example.com` 改成你的真实邮箱（SEC 官方要求留联系方式，否则可能拒绝数据请求）

> nano 里粘贴：Mac 终端直接用 `Cmd+V`。
> 保存退出：按 `Ctrl+O` → 回车 → `Ctrl+X`。

改完检查一下（token 只显示前几位确认没贴错就行）：

```bash
head -c 200 .env
```

---

## 第 5 步：给网页设置访问密码

你的仪表盘会暴露在公网，必须加密码，否则谁都能访问、还能点你的「手动跑数据」按钮。

在服务器上执行：

```bash
printf "gsadmin:$(openssl passwd -apr1)\n" > .htpasswd
```

- 它会提示 `Password:` → 输入你想设的密码（屏幕不显示）→ 回车 → 再输一次
- 这样登录名就是 `gsadmin`，密码是你刚设的那个
- 想换登录名就把命令里的 `gsadmin` 改掉

---

## 第 6 步：首次启动！

**6.1 先给数据目录放权**（容器里的程序以非 root 用户运行，写不了 root 克隆下来的目录，不放权会启动崩溃、浏览器显示 502）：

> 💡 每条命令都以 `cd ~/gs-tracker` 开头——如果你是新打开的 SSH 窗口，默认在家目录，直接 chmod 会提示找不到目录。

```bash
cd ~/gs-tracker
chmod -R 777 data output
```

**6.2 启动**：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

**第一次要 5~15 分钟**（下载系统依赖和 Python 包），看到一堆 `DONE` 和 `Started` 就是好了。

检查三个容器都在运行：

```bash
docker compose -f deploy/docker-compose.yml ps
```

应该看到 `gs-tracker-app`、`gs-tracker-scheduler`、`gs-tracker-nginx` 三个都是 `running`（healthy）。

> 调度器（scheduler）启动时会**自动跑第一次完整流水线**（抓 SEC 数据 → Kimi AI 分析 → 生成报告），需要几分钟。想看进度：
> ```bash
> docker compose -f deploy/docker-compose.yml logs -f scheduler
> ```
> 看到报告生成的日志后按 `Ctrl+C` 退出日志界面（容器不会停）。

**浏览器验证**：打开 `http://111.228.23.109`

- 弹出登录框 → 输入 `gsadmin` + 你第 5 步设的密码
- 看到「高盛动向情报系统」仪表盘 = 部署成功 🎉

---

## 第 7 步：京东云安全组放行 80 端口

如果上一步浏览器打不开，多半是安全组没放行 80 端口：

1. 京东云控制台 → 云主机 → 找到实例 `lavm-yoq1xkpkvx`
2. 点实例名进去 → 「安全组」标签 → 点安全组名 → 「入站规则」→「添加规则」
3. 协议 `TCP`，端口 `80`，源 IP `0.0.0.0/0` → 保存
4. （建议）把 `22` 端口的源 IP 从 `0.0.0.0/0` 改成你家宽带 IP，更安全

---

## 第 8 步：配置自动部署（实现 Railway 体验）

原理一句话：GitHub 帮你保管一把「专用钥匙」，每次你 push 代码，GitHub 就用这把钥匙登录服务器执行更新脚本。

**8.1 在服务器上生成专用钥匙**（和登录密码无关，是一对密钥）：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/github_actions -N ""
cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys
```

然后显示私钥内容：

```bash
cat ~/.ssh/github_actions
```

- 输出是 `-----BEGIN OPENSSH PRIVATE KEY-----` 开头、`-----END OPENSSH PRIVATE KEY-----` 结尾的**一大段**
- **整段复制**（包括 BEGIN 和 END 两行），这就是要交给 GitHub 的钥匙

**8.2 把钥匙存进 GitHub**（网页操作）：

1. 浏览器打开 `https://github.com/zhizhengqin/gs-tracker`
2. 点 **Settings**（仓库页面上方菜单）→ 左侧 **Secrets and variables** → **Actions**
3. 点 **New repository secret**，添加下面 3 个（一个一个加）：

| Name | Secret（值） |
|---|---|
| `DEPLOY_HOST` | `111.228.23.109` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | 刚才复制的那一大段私钥（全选粘贴） |

**8.3 不用做任何其他配置** —— 自动部署流水线文件 `.github/workflows/deploy.yml` 我已经写好放在仓库里了，跟着代码一起推上去就自动生效。

> ⚠️ 注意：流水线文件第一次推上去时，那次自动部署**会失败（红色叉）**，因为当时还没有配 Secrets，这是正常的，配完 Secrets 重新跑一次就绿了（第 9 步）。

---

## 第 9 步：验证自动部署

**9.1 重新跑那次失败的部署**：仓库页面 → **Actions** 标签 → 点那条失败的运行记录 → 右上角 **Re-run all jobs**。等 1~2 分钟变成绿色 ✅，说明 GitHub 已经成功登录服务器并完成部署。

**9.2 做一次真实的 push 验证**（在你自己 Mac 上）：

```bash
本机$ cd ~/Desktop/GS-Tracker
本机$ echo "" >> DEPLOY.md   # 随便改一点
本机$ git add DEPLOY.md && git commit -m "test: verify auto deploy" && git push
```

然后去仓库 **Actions** 页面，看到新的运行记录变绿 → 说明以后**每次 push 都会自动更新服务器**，和 Railway 一样。

---

## 日常使用（部署完之后你只需要知道这些）

| 我想… | 怎么做 |
|---|---|
| 更新系统功能 | 在 Mac 上改代码 → `git push`，完事（全自动） |
| 看仪表盘 | 浏览器开 `http://111.228.23.109`，输入 gsadmin + 密码 |
| 手动跑一次数据 | 仪表盘侧边栏点「▶️ 手动运行流水线」按钮 |
| 看运行日志 | 服务器上 `docker compose -f deploy/docker-compose.yml logs -f app`（把 `app` 换成 `scheduler` / `nginx` 看对应日志，`Ctrl+C` 退出） |
| 重启服务 | 服务器上 `docker compose -f deploy/docker-compose.yml restart` |
| 改密钥/配置 | 服务器上 `nano .env`，改完 `docker compose -f deploy/docker-compose.yml up -d` |
| 手动触发一次部署（不 push） | GitHub 仓库页 → Actions → Deploy to JD Cloud → **Run workflow** |

---

## 故障排查

| 症状 | 原因和解决 |
|---|---|
| `ssh: connect to host ... port 22: Operation timed out` | 安全组没放行 22 端口，或 IP 输错 → 检查第 7 步 |
| git clone 报 `GnuTLS recv error` 或超时 | 国内直连 GitHub 不稳 → 第 3.1 步镜像没配或失效，按第 3 步换一个备用镜像地址再 clone |
| 浏览器一直转圈打不开 | 安全组没放行 80 → 第 7 步；或容器没起来 → 服务器上 `docker compose -f deploy/docker-compose.yml ps` 看状态 |
| 浏览器显示 `502 Bad Gateway` | 最常见：data/output 目录权限（容器内非 root 用户写不了）→ `chmod -R 777 data output` 然后 `docker compose -f deploy/docker-compose.yml restart`；仍不好就 `docker compose -f deploy/docker-compose.yml logs --tail=50 app` 看报错 |
| 第 6 步 build 卡在下载镜像十几分钟不动 | 镜像加速没生效 → 重做第 2 步的 daemon.json 那段；还不行就把地址换成 `https://docker.1ms.run` 或 `https://docker.xuanyuan.me`，改完 `systemctl restart docker` |
| 打开页面显示 401/登录框密码总错 | 重新跑第 5 步生成密码，然后 `docker compose -f deploy/docker-compose.yml restart nginx` |
| nginx 容器起不来，日志说 `.htpasswd` 是目录 | 第 5 步没做就先启动了 → 补做第 5 步，`rm -rf .htpasswd` 如果它是目录，重新生成，再 `up -d` |
| 报告里 AI 分析全是「服务暂不可用」 | `.env` 里 token 没贴对 → `nano .env` 检查 `ANTHROPIC_AUTH_TOKEN`，改完 `up -d` 重启 |
| Actions 显示红色失败 | 点进去看日志：Secrets 名拼错 / 私钥没复制全（必须有 BEGIN 和 END 行）/ 服务器 IP 变了 |
| SEC 数据抓取报 503 | SEC 官网临时故障，等几小时点「手动运行流水线」重试，不是系统问题 |
| 服务器重启后服务没了 | 不用管，docker-compose 配了 `restart: unless-stopped`，会自动拉起 |

### 还是解决不了？一键收集诊断信息

在服务器上**整段复制**下面命令块执行（会自动隐去密钥内容，输出可以放心发给开发者/AI 排查）：

```bash
cd ~/gs-tracker
echo "===== 1. 容器状态 ====="
docker compose -f deploy/docker-compose.yml ps
echo "===== 2. app 容器最近 50 行日志 ====="
docker compose -f deploy/docker-compose.yml logs --tail=50 app
echo "===== 3. nginx 容器最近 20 行日志 ====="
docker compose -f deploy/docker-compose.yml logs --tail=20 nginx
echo "===== 4. 关键文件与配置检查（密钥只显示长度） ====="
ls -la .env .htpasswd 2>&1
python3 -c "
for line in open('.env'):
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    if 'TOKEN' in k or 'KEY' in k or 'PASS' in k:
        print(f'{k} = 已设置(长度{len(v)})' if v else f'{k} = 【空！需要填】')
    else:
        print(f'{k} = {v}')
" 2>&1
echo "===== 5. 数据目录权限 ====="
ls -ld data output data/db output/reports 2>&1
echo "===== 6. 绕过 nginx 直连 app 健康检查 ====="
docker compose -f deploy/docker-compose.yml exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())" 2>&1
```

**怎么看结果（自查）**：

- 第 1 节里 `app` 不是 `running` 而是 `Restarting`/`Exited` → app 崩了，原因在第 2 节日志里（常见：`Permission denied` = 权限没放好，重做第 6.1 步）
- 第 4 节里 `.htpasswd` 显示为**目录**（行首是 `d`）→ 先启动后建密码导致的，执行：`docker compose -f deploy/docker-compose.yml down && rm -rf .htpasswd`，然后重做第 5 步和第 6 步
- 第 4 节里 `ANTHROPIC_AUTH_TOKEN = 【空！需要填】` → `.env` 没改对，重做第 4 步
- 第 6 节输出 `{"status":"ok"}` 但浏览器还是 502 → app 正常、nginx 网络异常，执行 `docker compose -f deploy/docker-compose.yml down && docker compose -f deploy/docker-compose.yml up -d` 重建网络
- 自己看不出就把**全部输出**发给我

---

## 附录 A：不想配 GitHub Secrets？备选方案（服务器定时自动拉取）

如果第 8 步嫌麻烦，可以让服务器自己每 5 分钟检查一次 GitHub 有没有新代码（效果一样，最多慢 5 分钟）：

```bash
crontab -e
```

在打开的文件最后加一行（nano 编辑器，保存方式同第 4 步）：

```
*/5 * * * * cd /root/gs-tracker && bash deploy/update.sh >> /var/log/gs-tracker-deploy.log 2>&1
```

> 两种方案选一个就行，不要同时用。

---

## 附录 B：命令速查卡

```bash
# 进服务器
ssh root@111.228.23.109

# 看三个容器状态
docker compose -f deploy/docker-compose.yml ps

# 手动更新部署（和 GitHub Actions 执行的是同一个脚本）
cd ~/gs-tracker && bash deploy/update.sh

# 看日志（实时）
docker compose -f deploy/docker-compose.yml logs -f app

# 全部重启
docker compose -f deploy/docker-compose.yml restart
```
