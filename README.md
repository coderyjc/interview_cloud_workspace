# 云端 Agent 助手工作台

把 **Claude Code** 这类 Agent CLI 的能力搬进浏览器：打开一个云端工作台，新建会话、交办任务，实时看到助手的执行进展，查看/下载产出的文件；关掉页面再回来仍能找回并继续对话。支持多个会话并行切换（例如一边开发代码，一边分析材料）。

> 这是一个面向演示的可运行实现，追求"真实 Agent CLI + 浏览器多会话工作台"的完整闭环，而非生产级系统。已知限制见文末。

## 它能做什么

- **真实 Agent CLI**：后端为每条用户消息启动一次真实的 `claude`（Claude Code headless），支持读写文件、执行命令、跑测试。
- **流式进展**：通过 WebSocket 实时推送助手的文本分片、工具调用（含输入/输出）、本轮结果。
- **多会话**：会话列表可新建/切换/删除，按「开发 / 日常」分组；不同会话彼此隔离（各自独立工作目录 + 独立 CLI 会话上下文）。
- **持久化与续聊**：会话、消息、文件都落盘；重启后历史仍在，继续发消息会以 `--resume` 续接同一 CLI 会话。
- **文件工作区**：上传材料、浏览/下载助手产出（面板中的文件直接来自该会话工作目录）。
- **异常处理**：任务可取消、超时可兜底、CLI 报错会在界面提示、断线自动重连并补齐消息。

## 技术方案（图文）

架构图（SVG）+ 时序图 + 设计说明见 **[`docs/tech-solution.html`](docs/tech-solution.html)** —— 单文件，浏览器直接打开。

## 架构

```
浏览器 (React SPA)
  │  REST: 会话/文件 CRUD        WebSocket: 每会话一条，收发消息/流式事件/取消
  ▼
FastAPI (Python, asyncio)
  │  每条消息 → asyncio.create_subprocess_exec 起一次 claude(headless 单轮)
  ▼
claude -p --output-format stream-json --verbose --include-partial-messages --dangerously-skip-permissions
  │  cwd = 该会话工作目录,  ANTHROPIC_BASE_URL 指向本地 LiteLLM
  ▼
LiteLLM 代理 (容器内 127.0.0.1:4000，Anthropic ↔ OpenAI 协议转换)
  ▼
考试平台 OpenAI 兼容端点 (EXAM_BASE_URL)
```

**协议适配**：考试端点只提供 OpenAI 协议（`/v1/chat/completions`），而 Claude Code 只说 Anthropic 协议（`/v1/messages`）。容器启动时用 `EXAM_*` 生成 LiteLLM 配置并拉起本地代理，把 Anthropic 请求（含工具调用/流式）双向翻译成 OpenAI 协议。这是题目所说的"协议兼容、必要适配"部分。

```
/data/workspaces/<session-id>/    /data/app.db (SQLite)    /data/claude (CLAUDE_CONFIG_DIR, 供 --resume)
```

**进程模型**：一条用户消息 = 一次 `claude -p` 单轮进程。首轮用 `--session-id <uuid>` 建立会话，之后用 `--resume <uuid>` 续接。这样崩溃只影响单轮、并发天然成立、关页/重启不会残留僵尸进程。

**数据职责**：SQLite 是前端 transcript 的唯一真源（带单调 `seq`，供断线补齐）；Claude 自己的会话存储（挂在数据卷）只负责模型侧上下文，用于 `--resume`。两者解耦——即便 CLI 存储丢失，聊天历史依旧在，只是续聊上下文会断。

## 目录结构

```
backend/app/main.py      FastAPI：会话/文件 REST + WebSocket + 静态托管 + SQLite
backend/app/runner.py    启动 claude 子进程并解析 stream-json 为归一化事件
backend/entrypoint.sh    容器入口：起 LiteLLM 转换层 → 指向本地代理 → 起 FastAPI
frontend/src/App.jsx     React 单页：三栏（会话列表 / 聊天流 / 文件面板）
demo/smoke.py            无 UI 的端到端冒烟脚本
demo/evidence_run.txt    一次真实运行的证据输出（由 smoke.py 生成）
docs/tech-solution.html  技术方案（SVG 架构图 + 时序图 + 文字，单文件）
Dockerfile               多阶段：构建前端 → runtime(node+python+claude+litellm)
docker-compose.yml       一键启动，数据卷 + 环境变量
```

## 配置

凭据只通过环境变量注入，**不要提交 `.env`**。

```bash
cp .env.example .env
# 编辑 .env，填入考试平台提供的地址/凭据/模型
```

| 变量 | 说明 |
| --- | --- |
| `EXAM_BASE_URL` | 考试平台的 OpenAI 兼容地址（平台提供） |
| `EXAM_API_KEY` | 考试平台密钥（平台提供） |
| `EXAM_MODEL` | 使用的模型名（如 `linext-5.3-luna`） |
| `LITELLM_MASTER_KEY` | Claude Code ↔ 本地代理之间的内部密钥（任意值，默认 `sk-workbench`） |
| `MAX_CONCURRENT_RUNS` | 全局并发任务上限（默认 4） |
| `RUN_TIMEOUT_SECONDS` | 单轮任务超时秒数（默认 1800） |

## 启动（Docker，推荐）

```bash
cp .env.example .env      # 填入凭据
docker compose up --build
# 打开 http://localhost:8000
```

数据存放在命名卷 `workbench-data`（会话、工作区文件、Claude 会话存储）。容器以非 root 的 `node` 用户（uid 1000，`node:20-slim` 自带）运行——这是必须的，因为 `--dangerously-skip-permissions` 拒绝以 root 运行。

> 想直接在宿主机目录查看产物？把 `docker-compose.yml` 的 volume 换成 `- ./data:/data`，并确保宿主 `./data` 对 uid 1000 可写。

## 本地开发（可选）

需要本机已安装 Node 20+、Python 3.10+ 与 `claude` CLI。若要连考试端点（OpenAI 协议），同样需要先起 LiteLLM 转换层；直接用 Docker 最省事。

```bash
# 终端 0（可选）：协议转换代理，见 backend/entrypoint.sh 里的 litellm 启动方式
# 若你的端点原生支持 Anthropic，可跳过，直接设 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL

# 终端 1：后端
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000

# 终端 2：前端（Vite dev server，已配置 /api 与 /ws 代理到 8000）
cd frontend && npm install && npm run dev
# 打开 http://localhost:5173
```

## 使用

1. 点「+ 开发会话」或「+ 日常会话」新建会话。
2. 在输入框描述任务，回车发送。右侧实时显示助手文本与工具调用（点击工具卡片可展开输入/输出）。
3. 助手完成后，右侧「工作区文件」列出产出，点击即可下载；也可「上传材料」供助手分析。
4. 继续提修改意见即可续聊；切换会话或刷新/重开页面后再回来，历史与上下文都在。
5. 任务进行中可点「取消」。

### 演示材料建议

- **代码开发**：让助手「写一个 CSV→Markdown 转换小工具并加测试，运行确认通过」。观察工具卡片、产出文件与测试输出；随后提意见（如「再加一个 `--delimiter` 参数」）验证续聊。
- **日常任务**：上传一份会议记录/CSV，让助手「整理成结构化报告 report.md」，下载成果。
- **多会话**：两个会话来回切换；关闭浏览器重开、或重启容器后继续对话。

### 无 UI 冒烟

容器/后端起来后：

```bash
python3 demo/smoke.py
```

它会自动新建开发会话与日常会话、上传样例材料、等待完成，并打印每个会话的 transcript 与产出文件，可作为可复现的运行证据。

### 验证证据

- `demo/evidence_run.txt`：在 Docker 容器内、经考试端点真实跑通的一次完整输出（会话 transcript + 产出文件清单）。
- `docs/tech-solution.html`：架构与时序图，说明各组件如何协作。
- 容器健康：`curl http://localhost:8000/api/health` → `{"ok": true, "model": "<EXAM_MODEL>"}`。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 新建 `{kind:"dev"\|"daily"}` |
| GET | `/api/sessions/{id}` | 会话详情 + 全部消息 |
| DELETE | `/api/sessions/{id}` | 删除会话/消息/工作目录 |
| GET | `/api/sessions/{id}/messages?after=seq` | 增量消息 |
| POST | `/api/sessions/{id}/messages` | 发送 `{content}`，触发一轮任务 |
| POST | `/api/sessions/{id}/cancel` | 取消当前任务 |
| GET/POST | `/api/sessions/{id}/files` | 列出 / 上传文件 |
| GET | `/api/sessions/{id}/files/download?path=` | 下载文件 |
| WS | `/ws/{id}` | 订阅事件；发送 `{type:"subscribe",after_seq}`、`{type:"cancel"}` |

## 已知限制

- **单用户、无鉴权**：请在本地或受信网络使用，不要暴露到公网。
- **`--dangerously-skip-permissions` 全自动执行**：助手可自由读写工作目录、执行命令，存在安全风险；仅限演示/受控环境。
- **续聊依赖 Claude 会话存储**：已挂数据卷持久化；若被清除，历史仍在但上下文会断。
- **内置协议转换层**：考试端点仅 OpenAI 协议，项目内置 LiteLLM 做 Anthropic↔OpenAI 翻译；这会带来少量额外延迟，且转换层对少数边缘字段可能不完全保真。
- **每轮新起进程**：单轮开销略高，换取更好的隔离与崩溃恢复。
- **并发/超时**为工程兜底，非严格配额控制。

## 安全

- 凭据仅经环境变量传入容器，`.env` 已被 `.gitignore` 排除。
- 会话/文件操作限定在对应 `workspaces/<id>` 内（下载接口做了路径穿越校验）。
- 前端渲染为纯文本（`white-space: pre-wrap`），不执行模型返回的 HTML。
