# 演示材料与操作脚本（Demo Guide）

> 本文件给出可直接照做的演示流程：一次**代码开发任务**、一次**日常工作/材料整理任务**，以及**后续交流、多会话、关页/重启续聊、文件预览、文件修改审批（HITL）**。
> 当前版本只有「＋ 新聊天」（不再区分开发/日常），下面两个场景就是分别新建的两个聊天。
>
> 所有素材（示例材料、截图等）统一放在仓库根目录的 **`./assets/`** 下。每张截图都给了 **alt 文本**与**拍摄要点**，截好后放到 `assets/` 并在本文件中替换路径即可。

---

## 0. 演示前准备

```bash
# 1) 配置凭据（只填 EXAM_API_KEY，其余示例已有默认值）
cp .env.example .env

# 2) 启动
docker compose up --build
# 浏览器打开 http://localhost:8000
```

演示时可用两个浏览器标签页，分别对应两个聊天，便于展示「多会话」。

---

## 1. 演示总览（建议 6–8 分钟）

| 步骤 | 内容 | 预计 |
| --- | --- | --- |
| A | 代码开发任务 + 续聊 | 2–3 min |
| B | 日常材料整理任务 + 续聊 | 2 min |
| C | 多会话切换、关页/重启后续聊 | 1 min |
| D | 文件预览（语法高亮） | 30 s |
| E | 文件修改审批（HITL，含 Bash） | 1–2 min |
| F | 日间/夜间主题切换 | 10 s |

---

## 2. 场景 A：代码开发任务（新聊天 #1）

### 操作
1. 点「＋ 新聊天」。

   ![image-20261126160433930](E:\code\github\interview_cloud_workspace\assets\image-20261126160433930.png)

1. 在输入框发送：

```text
请用 Write 工具在当前目录写一个 Python 小工具 csv2md.py，把 CSV 文件转换成 Markdown 表格；
再写 test_csv2md.py 覆盖主要情况，最后运行测试确认全部通过。
```

3. 首次触发 `Write` 时会弹出**文件修改审批**模态框，可点「允许本次」；后续再次弹出时点「本次会话都允许」，让任务连续完成。

   ![image-20261126160509778](E:\code\github\interview_cloud_workspace\assets\image-20261126160509778.png)

4. 观察中间栏：助手文本流式输出、工具卡片（Write / Edit / Read / Bash）逐个出现并可展开输入/输出。

   ![image-20261126160533523](E:\code\github\interview_cloud_workspace\assets\image-20261126160533523.png)

5. 完成后右侧文件面板出现 `csv2md.py`、`test_csv2md.py`（截图 S3）。

![image-20261126160845379](E:\code\github\interview_cloud_workspace\assets\image-20261126160845379.png)

### 预期结果
- 助手用 `Write/Edit/Bash` 从零实现工具并自测；
- 最终报告「All 32 tests pass」；
- 产物：`csv2md.py`（约 6.4 KB）、`test_csv2md.py`（约 9.2 KB）。

### 续聊
发送：

```text
再加一个 --delimiter 参数（默认逗号），并补充对应测试，重新跑一遍测试。
```

预期：助手在**同一会话**里继续修改 `csv2md.py` 与测试并重跑（走 `--resume`）。

> 可选：仓库内 `assets/sample.csv` 是一份小样例，可用于人工验证转换结果。

---

## 3. 场景 B：日常工作 / 材料整理任务（新聊天 #2）

### 准备材料
使用仓库内的 **`assets/meeting.txt`**（内容见下），在右侧「上传材料」直接上传；也可自建同类文件。

```text
会议记录
- 项目 A 延期两周
- 预算增加 10%
- 下周五安排评审
- 负责人：张三、李四
```

### 操作
1. 点「＋ 新聊天」，上传 `assets/meeting.txt`。
2. 发送：

```text
阅读当前目录下的 meeting.txt，整理成一份结构化的中文报告 report.md，
包含：概述、关键结论、待办事项（表格）。写完后确认文件已生成。
```

3. 完成后右侧出现 `meeting.txt` 与 `report.md`。

![image-20261126160648760](E:\code\github\interview_cloud_workspace\assets\image-20261126160648760.png)

![image-20261126160658967](E:\code\github\interview_cloud_workspace\assets\image-20261126160658967.png)



![image-20261126160703423](E:\code\github\interview_cloud_workspace\assets\image-20261126160703423.png)



### 预期结果
- 助手读取材料、换算日期（如「下周五」→具体日期）、生成结构化 `report.md`（约 2.7 KB / 63 行），含概述、关键结论、待办表格、附录。

### 续聊
发送：

```text
把待办事项按负责人分组，并补充一个「风险与待补充信息」小节，更新 report.md。
```

预期：在原报告基础上更新（续聊 + 再次修改文件）。

---

## 4. 场景 C：多会话与持久化

1. 左右点击切换聊天 #1 与聊天 #2，展示各自独立的工作目录与完整历史。

   ![image-20261126160720421](E:\code\github\interview_cloud_workspace\assets\image-20261126160720421.png)

2. **关闭浏览器标签页**，重新打开 `http://localhost:8000`：会话列表与历史仍在。

3. 进入聊天 #1，继续发送：

```text
继续：给测试再加一个「空输入」的用例，并说明你加了什么。
```

4. **重启服务**（`docker compose restart`，或测试容器用 `docker restart <容器名>`）后再打开页面：历史依旧，继续发消息可正常续接。

预期：两次「离开再回来」都能找回并进行后续交流。

---

## 5. 场景 D：文件预览（语法高亮）

1. 在聊天 #1 的右侧文件面板**点击** `csv2md.py` → 弹出预览模态框，Python 语法高亮。

   ![image-20261126160730335](E:\code\github\interview_cloud_workspace\assets\image-20261126160730335.png)

2. 在聊天 #2 点击 `report.md` → Markdown 高亮预览。

3. 模态框右上角「下载」仍可下载原文件。

---

## 6. 场景 E：文件修改审批（Human-in-the-loop）

### E1. 文件工具审批
1. 新建聊天，发送：

```text
请使用 Write 工具（不要用 bash）创建文件 hitl_demo.txt，内容只写一行：hello human。
```

2. 弹出审批模态框：标题「需要确认：Write 修改文件」，展示 **diff**（绿色 `+hello human`），按钮 **拒绝 / 允许本次 / 本次会话都允许**。
   ![image-20261126160648760](E:\code\github\interview_cloud_workspace\assets\image-20261126160648760.png)
3. 先点「拒绝」→ 助手收到拒绝原因，`hitl_demo.txt` **不会生成**。
4. 再发送一次同样/类似的写文件指令，点「允许本次」→ 文件生成。

### E2. Bash 写操作审批
1. 发送：

```text
请用 bash 工具执行且只执行这条命令：echo hi > bash_demo.txt
```

2. 弹出审批模态框：标题「需要确认：执行命令」，内容 `$ echo hi > bash_demo.txt`（截图 S9）。

   ![image-20261126160823491](E:\code\github\interview_cloud_workspace\assets\image-20261126160823491.png)

3. 点「本次会话都允许」→ 放行，文件生成；**此后**该会话的文件修改与 Bash 写操作都不再弹窗。

> 说明：只读命令（如 `ls`）不会弹窗；仅「疑似写操作」的 Bash 会被拦截。

---

## 7. 场景 F：日间 / 夜间主题

- 点左侧标题右侧的「☀ 日间 / ☾ 夜间」切换主题；选择会被记住（刷新后保持）。
- 展示 `.messages` 等滚动条也随主题变色。

---

## 8. 真实运行证据（见 `assets/evidence_run.txt`）

| 项目 | 结果 |
| --- | --- |
| 代码开发任务 | 生成 `csv2md.py`、`test_csv2md.py`，测试「All 32 tests pass」 |
| 材料整理任务 | 读取 `meeting.txt`，生成 `report.md`（约 2.7 KB / 63 行） |
| 文件审批-允许 | 审批通过后 `hitl_demo.txt` 生成 |
| 文件审批-拒绝 | 拒绝后 `denied_demo.txt` 未生成，任务正常结束 |
| 「本次会话都允许」 | 后续审批立即放行（后端直接返回 allow） |
| Bash 写操作 | `echo hi > bash_write.txt` 被拦截并审批，允许后文件生成（16B） |
| 只读 Bash | `ls -la` 直接放行，无弹窗 |

---

## 9. 截图清单（需手动截取 → 放入 `assets/`）

> 建议浏览器全屏、隐藏书签栏；界面不展示任何密钥，可放心截图。

| 编号 | 文件名 | 拍摄要点 | alt 文本（可直接用于 `![...]()`） |
| --- | --- | --- | --- |
| S1 | `assets/s1-new-chat.png` | 点击「＋ 新聊天」后的空状态：左侧会话列表、中间空提示、右侧文件面板 | `S1 新建聊天后的空工作台，左侧会话列表与中间空状态提示` |
| S2 | `assets/s2-code-streaming.png` | 代码任务执行中：助手文本流式输出 + 多张工具卡片（Write/Bash） | `S2 代码开发任务执行中，助手流式输出并显示工具调用卡片` |
| S3 | `assets/s3-code-artifacts.png` | 代码任务完成后：中间「All 32 tests pass」，右侧列出 csv2md.py / test_csv2md.py | `S3 代码任务完成，测试通过且右侧文件面板列出产出文件` |
| S4 | `assets/s4-daily-report.png` | 材料整理任务完成：右侧 meeting.txt 与 report.md，助手确认已生成 | `S4 日常材料整理任务完成，右侧出现上传材料与生成的 report.md` |
| S5 | `assets/s5-multi-session.png` | 左侧同时存在多个「新聊天」会话，其中一个运行中（蓝色圆点） | `S5 左侧会话列表展示多个并行聊天及运行状态` |
| S6 | `assets/s6-permission-write.png` | 文件修改审批模态框：标题「需要确认：Write 修改文件」、绿色新增行 diff、三个按钮 | `S6 文件修改审批弹窗，展示 Write 的 diff 与允许/拒绝/本次会话都允许按钮` |
| S7 | `assets/s7-preview-hl.png` | 文件预览模态框：csv2md.py 的 Python 语法高亮 | `S7 点击文件后弹出预览模态框，显示带语法高亮的 Python 代码` |
| S8 | `assets/s8-permission-deny.png` | 拒绝后助手回复被拒绝、目标文件未出现在文件面板 | `S8 拒绝文件修改后，助手收到拒绝原因且文件未生成` |
| S9 | `assets/s9-permission-bash.png` | Bash 审批模态框：标题「需要确认：执行命令」、`$ echo hi > bash_demo.txt` | `S9 Bash 写操作审批弹窗，展示待执行的 shell 命令` |
| S10 | `assets/s10-theme.png` | 并排或先后展示日间与夜间界面（含滚动条颜色） | `S10 日间与夜间主题切换效果对比` |

### 可选：录屏脚本（约 60–90 秒）
1. 新建聊天 → 发代码任务 → 审批「允许本次」→ 「本次会话都允许」→ 测试通过；
2. 新建聊天 → 上传材料 → 生成报告 → 续聊更新；
3. 切换两个聊天 → 关闭页面重开 → 继续对话；
4. 点文件预览（高亮）→ 触发 Bash 写审批 → 主题切换。

---

## 10. 讲解要点（口播提纲）

- **真实 CLI**：助手不是 mock，容器内跑的是官方 `claude`，我们按轮 `spawn` 它并解析 `stream-json`。
- **协议适配**：考试端点只支持 OpenAI 协议，内置 LiteLLM 做 Anthropic↔OpenAI 转换。
- **多会话与持久化**：SQLite 存 transcript、工作区存文件、CLI 会话存上下文；关页/重启可续聊。
- **HITL**：写文件与 Bash 写操作前暂停，diff/命令可视、可拒绝、可「本次会话都允许」。
- **体验细节**：流式输出、工具卡片、文件语法高亮预览、日间/夜间主题。
