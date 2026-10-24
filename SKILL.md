---
name: kindle-token-panel
description: 将闲置 Kindle（未越狱，含国际版与 Kindle X 咪咕版）改造为实时 AI Token 用量与在途多智能体任务墨水屏监控面板的完整技能与零依赖服务套件。
---

# 📟 Kindle 实时 AI Token 与任务监控面板 (Kindle Panel Skill)

本技能为 AI Agent 提供了自动化将各类闲置 Kindle 电子书阅读器（未越狱，全面支持国际版 Paperwhite / Oasis / Voyage / Scribe 以及定制版 **Kindle X 咪咕版 `KFBJWI`**）改造为桌面级实时 AI 监控墨水屏的完整自动化标准作业程序 (SOP)。

---

## 🎯 核心架构与功能特性

1. **零第三方依赖**：纯 Python 3 标准库实现 (`server.py`, `kpanel`, `make_launcher_books.py`)，无需 `pip install` 任何额外库。
2. **绝对安全只读**：以 URI 只读模式 (`mode=ro`) 连接 Token Monitor 与 Antigravity 本地 SQLite，绝不写脏任何数据库。
3. **四通道在途任务聚合**：
   - **Antigravity 主会话与子代理**（实时解析 `task.md` 进度百分比与步数）；
   - **Token Monitor 外部客户端**（Claude / Codex / Devin / OpenCode 活跃会话）；
   - **本地长耗时脚本进程**（`ps` 智能识别爬虫、Remotion 渲染、FFmpeg 等，过滤 Chrome 子进程）；
   - **自定义任务队列**（支持任何外部脚本通过 `kpanel push` 上报）。
4. **Kindle 硬件极致适配**：
   - 100% 严格 ES5 原生语法，老旧 WebKit 零脚本报错；
   - HTTP 304 增量校验，数据无变化时**屏幕零刷新**；
   - 强制 600px 视口并自动做宽视口比例补偿，破除 Android 980px 缩小问题；基准 `28px` 超粗巨字，支持 `[字-]`/`[字+]`（`16px~72px`）动态调阶；
   - 全宽巨型 12 格墨水屏进度条，审批阻塞时纯黑反色高亮强提醒；
   - 2 小时自动内存防泄漏刷新，GC16 软全刷防残影。
5. **官方隐藏浏览器一键唤醒**：内置专用电子书生成器，为隐藏了浏览器的 Kindle X 咪咕版注入带超链接的跳板电子书。

---

## 🤖 AI Agent 自动化执行 SOP

当用户需要配置、部署或维护 Kindle 监控面板时，Agent 遵循以下步骤执行：

### 步骤 1：探测本机数据源与运行环境
检查本机是否存在支持的数据源：
```bash
# 检查 Token Monitor 数据归档
ls -la "$HOME/Library/Application Support/Token Monitor"

# 检查 Antigravity 会话数据库
ls -la "$HOME/.gemini/antigravity/conversation_summaries.db"
```

### 步骤 2：部署 macOS 开机常驻守护服务 (LaunchAgent)
执行一键部署脚本，将服务安全部署至 `~/Library/Application Support/KindlePanel`（避开 macOS 对 Documents 目录的 TCC 后台拦截）：
```bash
cd kindle-panel
./install_launchd.sh
```
部署完成后，终端会打印本机访问地址与局域网 IP（例如 `http://192.168.1.x:8765`）。

### 步骤 3：识别 USB 连接的 Kindle 类型并注入跳板书
判断当前连接的 Kindle 机型模式：
1. **普通国际版 Kindle (USB 大容量存储模式)**：
   - 系统会自动挂载为 `/Volumes/Kindle`。
   - 直接运行脚本生成跳板书并拷入：
     ```bash
     python3 make_launcher_books.py --out-dir /Volumes/Kindle/documents
     ```
2. **Kindle X 咪咕版 (Android MTP 模式)**：
   - 咪咕版官方在系统层面隐藏了体验版浏览器入口，且采用 MTP 协议。
   - 确保安装 `libmtp`（`brew install libmtp`），然后直接使用 `--push-mtp` 参数一键推送：
     ```bash
     python3 make_launcher_books.py --push-mtp
     ```

### 步骤 4：真机唤醒与常亮防休眠指引
协助用户在 Kindle 真机上进行首次唤醒：
1. **唤醒浏览器**：
   - 在 Kindle 书架上打开名为 **《⚡ Token 实时任务面板》**（`.mobi` 或 `.pdf`）。
   - 点击书中的巨大按钮 `[👉 点击此处一键打开实时监控面板 👈]`，Kindle 将立即唤醒内置隐藏的 WebKit 浏览器并载入面板！
   - 点击右上角菜单将该页面**加入书签**，下次可直接从书签进入。
2. **开启防休眠常亮 (Keep-Awake)**：
   - 在 Kindle 顶栏搜索框中输入：
     ```text
     ~ds
     ```
     （部分机型需先输入 `;debugOn` 回车，再输入 `~ds` 回车）。
   - 此时 Kindle 屏幕将完全禁用休眠超时，搭配 USB 常插电即可化身为永不熄灭的桌面极客监控副屏！

### 步骤 5：使用 `kpanel` 推送自定义任务进度
任何本地 Python 脚本、Shell 流水线均可通过 `kpanel` 命令行工具一行代码推送任务状态至 Kindle：
```bash
# 推送任务进行中
./kpanel push "数据挖掘流水线" --step 3 --total 10 --detail "正在抓取第3批次" --source "Pipeline"

# 推送需要人工干预/审批的任务（Kindle 屏幕上整卡反色为纯黑底白字高亮警报！）
./kpanel push "生产部署确认" --detail "等待审核批准" --approval

# 标记完成任务并从面板移除
./kpanel done "数据挖掘流水线"

# 终端随时查看仪表盘状态
./kpanel status
```

---

## 🛠️ 故障排查与维护 (Troubleshooting)

- **查看实时日志**：
  ```bash
  tail -f "$HOME/Library/Application Support/KindlePanel/server.log"
  ```
- **重启守护服务**：
  ```bash
  launchctl unload "$HOME/Library/LaunchAgents/io.github.kindlepanel.plist"
  launchctl load "$HOME/Library/LaunchAgents/io.github.kindlepanel.plist"
  ```
- **卸载常驻服务**：
  ```bash
  ./install_launchd.sh uninstall
  ```
