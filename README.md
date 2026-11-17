# Research Harness

本地 AI 科研工作台，使用官方 DeepSeek Harness Python SDK 的完整 `sdk` profile。支持按项目组织会话、多轮交流、历史展示和服务重启后的会话恢复。

## 完整文档

- [安装与运行指南](docs/installation.md) 从下载官方源码开始，覆盖环境准备、SDK 安装、配置、验收和故障排查。
- [项目文档](docs/project.md) 说明代码框架、当前功能、数据与接口，以及完整版开发路线。

## 安装

需要 Python 3.10+，支持官方运行时提供的 Windows x64、Linux x64/arm64 和 macOS arm64 平台。SDK 会安装匹配版本的运行时。

在 Windows PowerShell 中执行以下命令。

```powershell
git clone https://github.com/boliQi/research-harness.git
cd research-harness
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux 和 macOS 可用以下命令创建环境。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

复制 `.env.example` 为本机 `.env`，填写 `DEEPSEEK_API_KEY`。也可以使用已有的 Harness 凭据文件启动。

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py --env-file "D:\path\to\deepseek-harness\.env"
```

使用仓库根目录的 `.env` 时，可以直接启动。

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py
```

Linux 或 macOS 使用 `.venv/bin/python my-harness-ui/server.py`。打开 [本地页面](http://127.0.0.1:8001)。服务监听 `127.0.0.1`，按 Ctrl+C 关闭服务和其 SDK 运行时。

## 使用

1. 点击添加项目，填写项目名称和已存在的本机绝对目录。
2. 点击新建会话，发送研究问题或任务。
3. 在同一会话继续交流，历史自动保存在本机。
4. 切换项目或会话可查看各自历史。重启服务后选择原会话即可继续。

项目目录是 Agent 的工作目录，文件工具和 Shell 在该目录执行任务。运行 Python 时，使用本机或项目已配置的 Python 环境和依赖。网页搜索需要搜索提供方可用的凭据、网络和服务支持。模型调用、文件操作和工具执行均由官方 Harness 完成。

当前采用 `workspace-write` 权限预设。需要人工批准的操作由后台审批线程明确拒绝，AI 提问由回调取消，原因会保存在任务记录并显示在页面中。完整交互界面可在现有 SDK 管理层上继续扩展。

Windows 沙箱需要项目目录由当前用户拥有，并具备包括 `WRITE_OWNER` 在内的完整权限。仅继承 Modify 权限的目录可能出现 `SetNamedSecurityInfoW` 错误。验证中为应用新建的验收目录补齐当前用户完整权限后，Python 已在 `workspace-write` 下成功执行。参考[Windows 沙箱要求](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox-windows-acl/README.zh.md)。

## 配置

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--port` | `8001` | 本机 HTTP 端口 |
| `--data-dir` | 仓库根目录下的 `.research-harness` | 数据库及 Harness home |
| `--env-file` | 仓库根目录的 `.env` | 本机环境配置文件 |
| `--model` | `deepseek-v4-flash` | `deepseek-official` 路由中的模型 ID |

启动环境中的变量优先于 `--env-file`。可选的 `DEEPSEEK_BASE_URL` 用于兼容网关。旧的位置参数 `python server.py <Harness目录>` 仍可用于读取该目录的 `.env`；执行采用 SDK 配套运行时。

Windows `0.2.2rc2` 运行时存在非 C 盘启动时原生模块加载失败的问题。本应用将运行时进程目录设置为 `C:\`，SDK 的 `cwd` 仍明确指定项目目录。该处理已用于验证 D 盘项目的真实调用。参考[上游问题](https://github.com/deepseek-ai/deepseek-harness/discussions/10269)。

## 代码与数据

```text
my-harness-ui/
  server.py       HTTP 接口、参数和数据目录锁
  harness.py      官方 SDK、项目运行时、Session、后台任务与交互回调
  storage.py      SQLite 项目索引、展示消息和任务状态
  index.html      页面结构
  app.js          项目切换、会话加载、发送与任务轮询
  styles.css      页面样式
  tests/          无密钥回归测试
.research-harness/
  app.sqlite3     应用索引和页面历史
  dsh-home/       Harness profile、凭据存储及持久化会话
```

应用索引与 Harness home 共同组成可恢复的数据。固定 `--data-dir`，并保持项目原目录可用。SDK 恢复的是会话历史，Python 进程、Shell 和浏览器等外部状态需要任务重新建立。旧 Headless Demo 的历史保留在原存储中，本应用从新的项目索引开始登记。

各项目按需持有长驻 SDK 实例。首期同时执行一个用户任务，切换页面与刷新浏览器时任务继续执行。请求 ID用于幂等提交，已接受的请求可用同一 ID查询或重新提交。服务异常退出后，未完成任务标记为结果待确认，后续输入由用户明确发起。

`.research-harness/`、`.env`、虚拟环境、源码版 Harness 和 ZIP 已由 `.gitignore` 排除。两台电脑通过 Git 同步应用代码，各自配置目录、凭据和历史。

## HTTP 接口

| 方法与路径 | 功能 |
| --- | --- |
| `GET /api/projects` | 获取项目列表 |
| `POST /api/projects` | 用 `name` 和 `directory` 创建项目 |
| `GET /api/projects/{id}/sessions` | 获取项目会话列表 |
| `POST /api/projects/{id}/sessions` | 创建空会话，正文为 `{}` |
| `GET /api/sessions/{id}` | 获取会话、消息和任务 |
| `POST /api/chat` | 用 `session_id`、`request_id`、`message` 提交任务，返回 `202` 和 `run` |
| `GET /api/runs/{id}` | 获取任务状态、结果、错误及交互说明 |

任务状态为 `queued`、`running`、`completed`、`error` 或 `interrupted`。同一请求 ID用于不同消息返回 `409`，其他任务执行期间的新请求也返回 `409`。页面每秒轮询当前任务，最终回复在写入 SQLite 后可读取。

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s my-harness-ui/tests -v
node --check my-harness-ui/app.js
```

无密钥测试覆盖存储、路径校验、多轮及隔离、恢复、请求幂等、忙碌拒绝、交互说明、运行时失败和 HTTP 接口。真实模型验收应另外验证重启召回、Python 输出文件和网页搜索结果。
