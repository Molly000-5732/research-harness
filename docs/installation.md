# 安装与运行指南

更新日期为 2026-11-18。本文从下载 DeepSeek Harness 源码开始，完成源码环境准备、Research Harness 安装、首次运行与验收。项目结构和开发路线见[项目文档](project.md)。

## 1. 安装后包含哪些部分

| 部分 | 用途 | 运行方式 |
| --- | --- | --- |
| DeepSeek Harness 源码 | 阅读开发文档、开发插件、运行官方界面 | Node.js、pnpm 和源码构建产物 |
| Research Harness | 本项目的科研工作台，提供项目、会话和聊天界面 | Python HTTP 服务 |
| 官方 Python SDK 与配套运行时 | 驱动 Agent、文件工具、Shell、网页工具和持久会话 | 由 Research Harness 调用，随 Python 依赖安装 |
| 科研项目目录 | 存放论文、数据、实验代码和输出 | 在页面中登记本机绝对路径 |

当前 Research Harness 使用官方 SDK 自带的运行时。源码目录用于开发参考，也可提供已有的 `.env` 文件。源码构建版本和 Python SDK 发布版本分别管理。安装 SDK 会同时安装完全相同版本的运行时包。[官方 Python SDK](https://pypi.org/project/deepseek-harness-sdk/0.2.2rc2/)

建议采用以下目录布局，科研项目目录可按实际情况调整。

```text
research-workbench/
├─ deepseek-harness/       官方源码
├─ research-harness/       本项目
│  ├─ .venv/              应用 Python 环境
│  ├─ .env                本机凭据
│  └─ .research-harness/   应用索引和 Harness 持久数据
└─ projects/
   └─ demo/               示例科研项目
```

## 2. 准备基础环境

| 环境 | 本文使用的要求 |
| --- | --- |
| Git | 能够克隆两个 GitHub 仓库 |
| Node.js | 源码构建要求 `>=24.9.0` |
| pnpm | 本次验证的源码声明 `pnpm@11.28.5` |
| Python | 应用要求 `>=3.10`，本机已验证 Python 3.14 |
| 模型凭据 | 可用的 `DEEPSEEK_API_KEY` |
| 平台 | 官方 Python 运行时提供 Windows x64、Linux x64/arm64 和 macOS 14+ arm64 发行物 |

本文对应的已验证源码提交为 `39163dd30f703a79079e2d2446545cff3c453738`，源码包版本为 `0.2.2-rc.3`。Research Harness 当前固定 SDK 与配套运行时版本为 `0.2.2rc2`。新机器可先复现这组版本，再单独安排升级验证。

安装 Git、Node.js 和 Python 后，重新打开终端并检查版本。Windows 示例使用 PowerShell，直接调用 Python 虚拟环境的可执行文件。

```powershell
git --version
node --version
npm.cmd --version
python --version
```

Linux/macOS 使用以下命令。

```sh
git --version
node --version
npm --version
python3 --version
```

## 3. 下载并构建 DeepSeek Harness 源码

### 3.1 Windows

以下路径是新机器安装示例，可替换为自己的工作目录。

```powershell
New-Item -ItemType Directory -Force -Path D:\research-workbench | Out-Null
Set-Location D:\research-workbench
git clone https://github.com/deepseek-ai/deepseek-harness.git
Set-Location D:\research-workbench\deepseek-harness
git checkout 39163dd30f703a79079e2d2446545cff3c453738
npm.cmd install --global pnpm@11.28.5
pnpm.cmd --version
pnpm.cmd install --frozen-lockfile
pnpm.cmd run build
```

`git checkout` 将这个新克隆固定到已验证提交。已有源码安装可以直接复用，记录其 `git rev-parse HEAD` 和 `package.json` 中的环境要求。全量构建会准备 Host、Client、Web 等产物，并执行类型检查。[官方源码运行说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.zh.md)

### 3.2 Linux/macOS

```sh
mkdir -p "$HOME/research-workbench"
cd "$HOME/research-workbench"
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd "$HOME/research-workbench/deepseek-harness"
git checkout 39163dd30f703a79079e2d2446545cff3c453738
npm install --global pnpm@11.28.5
pnpm --version
pnpm install --frozen-lockfile
pnpm run build
```

如果系统的 npm 全局目录需要额外权限，使用已有的 Node 版本管理器准备用户级 Node/npm 环境，再执行 pnpm 安装。

### 3.3 已下载 ZIP 的处理

将 ZIP 解压为 `deepseek-harness-master`，在解压目录中执行依赖安装。ZIP 构建需要提供原始提交号，GitHub ZIP 的归档注释通常包含该信息。下面示例假设压缩包位于解压目录的上一层。

```powershell
Set-Location D:\research-workbench\deepseek-harness-master
pnpm.cmd install --frozen-lockfile
$archivePath = (Resolve-Path ..\deepseek-harness-master.zip).Path
$env:DSH_CLIENT_COMMIT_HASH = python -c "import sys,zipfile; print(zipfile.ZipFile(sys.argv[1]).comment.decode('utf-8'))" $archivePath
pnpm.cmd run build
```

确认输出的提交号与下载内容匹配。归档注释为空时，从下载链接对应的 GitHub 提交页面取得提交号，手动设置 `DSH_CLIENT_COMMIT_HASH` 后构建。对本文已验证的 ZIP，可使用以下值。

```powershell
$env:DSH_CLIENT_COMMIT_HASH = '39163dd30f703a79079e2d2446545cff3c453738'
```

本机最初使用 ZIP 完成源码安装，已在提供真实提交号后通过完整构建。

### 3.4 检查官方界面

在源码目录中启动官方 Web 应用。

```powershell
pnpm.cmd dsh web --no-open
```

Linux/macOS 使用 `pnpm dsh web --no-open`。访问终端打印的地址，默认端口为 `3080`。完成检查后可按 Ctrl+C 关闭。Research Harness 的本地界面在后续步骤使用 `8001` 端口。

## 4. 下载 Research Harness 并安装 SDK

### 4.1 Windows

```powershell
Set-Location D:\research-workbench
git clone https://github.com/boliQi/research-harness.git
Set-Location D:\research-workbench\research-harness
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pip show deepseek-harness-sdk deepseek-harness-runtime-bin
```

### 4.2 Linux/macOS

```sh
cd "$HOME/research-workbench"
git clone https://github.com/boliQi/research-harness.git
cd "$HOME/research-workbench/research-harness"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m pip show deepseek-harness-sdk deepseek-harness-runtime-bin
```

当前 `requirements.txt` 包含 `deepseek-harness-sdk==0.2.2rc2` 和 `python-dotenv==1.2.1`。SDK 依赖会安装同版本的 `deepseek-harness-runtime-bin`。模型任务启动时，应用选择完整的 `sdk` profile。[SDK 发行说明](https://pypi.org/project/deepseek-harness-sdk/0.2.2rc2/)

## 5. 配置模型凭据

在 Research Harness 根目录创建本机 `.env`。

```powershell
Copy-Item .env.example .env
notepad .env
```

Linux/macOS 使用 `cp .env.example .env`，然后用编辑器填写文件。

```dotenv
DEEPSEEK_API_KEY=填写你自己的密钥
# 使用兼容网关时再填写实际地址
# DEEPSEEK_BASE_URL=https://your-gateway.example/v1
```

应用的模型路由固定为 `deepseek-official`，默认模型为 `deepseek-v4-flash`。可通过 `--model` 选择该路由支持的其他模型。网关还需要支持所用模型的协议，网页工具的端点和凭据也需要单独验证。

已有源码目录的 `.env` 可直接作为启动配置，具体命令见下一节。启动进程中的同名环境变量优先于文件值。修改 `.env` 后重启 Python 服务，使新的运行时读取配置。

## 6. 启动本地工作台

### 6.1 使用应用根目录的 `.env`

Windows 在 Research Harness 根目录执行以下命令。

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py
```

Linux/macOS 使用以下命令。

```sh
.venv/bin/python my-harness-ui/server.py
```

### 6.2 使用源码目录已有的 `.env`

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py --env-file D:\research-workbench\deepseek-harness\.env
```

```sh
.venv/bin/python my-harness-ui/server.py --env-file "$HOME/research-workbench/deepseek-harness/.env"
```

源码解压目录使用 `deepseek-harness-master` 时，将命令中的路径替换为实际目录。旧式位置参数也会读取该目录的 `.env`。

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py D:\research-workbench\deepseek-harness-master
```

### 6.3 端口、数据目录和模型

```powershell
.venv\Scripts\python.exe my-harness-ui/server.py --port 8002 --data-dir D:\research-workbench\research-data --env-file D:\research-workbench\research-harness\.env --model deepseek-v4-flash
```

| 配置 | 默认行为 |
| --- | --- |
| 监听地址 | `127.0.0.1` |
| `--port` | `8001` |
| `--data-dir` | Research Harness 根目录的 `.research-harness` |
| `--env-file` | Research Harness 根目录的 `.env` |
| `--model` | `deepseek-v4-flash` |

看到终端中的启动地址后打开[本地工作台](http://127.0.0.1:8001)。服务需要保持运行，按 Ctrl+C 会关闭 HTTP 服务及其管理的 SDK 运行时。再次启动时使用相同的数据目录。

本机当前检出位于 `D:\code\research_harness`。复用已经安装的环境时，可使用以下命令。

```powershell
Set-Location D:\code\research_harness
.venv\Scripts\python.exe my-harness-ui/server.py --env-file deepseek-harness-master/.env
```

## 7. 创建科研项目并验证

### 7.1 创建示例目录

```powershell
New-Item -ItemType Directory -Force -Path D:\research-workbench\projects\demo | Out-Null
```

Linux/macOS 使用 `mkdir -p "$HOME/research-workbench/projects/demo"`。在页面中点击添加项目，填写名称和这个目录的绝对路径，再点击新建会话。

### 7.2 验证普通对话与记忆

1. 发送“请记住本次实验代号为 MY-TEST-482。只回答已记住”。
2. 在同一会话发送“刚才的实验代号是什么”。
3. 刷新页面，确认消息历史可加载。
4. 等任务结束，按 Ctrl+C 停止服务，再用相同参数启动。
5. 选择原会话，再次询问代号，核对返回结果。
6. 新建另一个会话，确认它具有独立的会话 ID和消息列表。

### 7.3 验证 Python

在科研项目目录放入一个 `sample.csv`，内容如下。

```csv
value
1
2
3
```

向 Agent 发送以下任务。

> 在当前项目目录读取 sample.csv，实际运行 Python 标准库 csv，计算 value 列总和，并写入 python-result.txt。完成后报告结果与文件名。

检查项目目录中的实际输出文件，预期总和为 `6`。执行依赖项目使用的 Python 和已安装的库，后续可在项目内维护独立虚拟环境并向 Agent 指定其解释器路径。

### 7.4 验证网页搜索

> 请实际调用 web_search 搜索 DeepSeek Harness Python SDK 官方文档，返回一条结果的标题和来源链接。

检查结果链接和运行记录。搜索服务的可用性取决于网络、所选提供方和凭据。遇到工具不可用时，按具体诊断检查配置。[官方网页提供方文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/web-deepseek-api/README.zh.md)

## 8. Windows 运行说明

### 8.1 原生模块加载错误

官方 `0.2.2rc2` Windows 运行时从非 C 盘启动时，本机曾出现 `koffi.node` 加载失败。当前 `ProjectRuntime` 将运行时进程的 `runtime_cwd` 设置为 `C:\`，并通过 SDK 的 `cwd` 指定科研项目目录，已验证 D 盘项目的调用和恢复。使用当前应用入口启动会应用这一处理。[上游问题记录](https://github.com/deepseek-ai/deepseek-harness/discussions/10269)

### 8.2 `SetNamedSecurityInfoW` 或 Win32 5

`workspace-write` 沙箱需要当前用户拥有项目目录，并具备包括 `WRITE_OWNER` 在内的完整权限。仅继承 Modify 权限的目录可能在启动 Shell 前失败。可在资源管理器的目录属性、安全、高级页面检查所有者和当前用户权限，对自己管理的科研目录补齐所需权限后重试。[官方 Windows 沙箱要求](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox-windows-acl/README.zh.md)

本机验收时，对应用新建的测试目录补齐当前用户完整权限后，Python 已在 `workspace-write` 下成功执行。

### 8.3 审批和 AI 提问提示

实验验证页支持当前实验 Session 的单次工具审批。取得可审阅的工具参数后，可在页面上批准一次或拒绝。其他会话的审批请求会被拒绝，AI 提问会取消并记录在任务的 `notices` 中。

## 9. 常见问题与检查

| 现象 | 检查方法 |
| --- | --- |
| 提示找不到 SDK 模块 | 用 `.venv` 中的 Python 安装依赖并启动 |
| `MISSING_CREDENTIAL` | 检查选中的 `.env`、密钥和启动环境变量，重启服务 |
| 源码构建报 `git rev-parse HEAD` 失败 | ZIP 安装按第 3.3 节提供真实提交号 |
| SDK 恢复报历史不存在或不可读 | 核对原 `--data-dir`、原项目目录和完整的数据备份 |
| 页面显示项目目录失效 | 恢复登记时的目录，或登记另一个项目开展新工作 |
| 端口已占用 | 使用现有服务，或选择其他 `--port` |
| 数据目录已被占用 | 同一数据目录复用已有服务，独立实例选择其他 `--data-dir` |
| 新任务返回 `409` | 等待当前任务完成，检查是否复用了不同消息的请求 ID |
| 结果待确认 | 上次服务异常退出，先检查文件和实验实际状态，再明确继续 |

本应用的 `completed` 表示 SDK 活动以完成状态结束。科研任务仍应通过输出文件、日志、数值和来源核验是否达到目标。

可执行本项目的无密钥检查。

```powershell
.venv\Scripts\python.exe -m unittest discover -s my-harness-ui/tests -v
.venv\Scripts\python.exe -m pip check
node --check my-harness-ui/app.js
```

Linux/macOS 将 Python 路径换为 `.venv/bin/python`。当前仓库含 17 项回归测试，真实模型验证另按第 7 节进行。

## 10. 更新、备份与另一台电脑

更新应用前结束任务并关闭服务，再执行以下命令。

```powershell
git pull --ff-only
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s my-harness-ui/tests -v
```

备份时关闭服务，将整个实际 `--data-dir` 与科研项目文件一起保存。默认数据目录包含应用 SQLite 数据库、锁文件及 `dsh-home`，其中会有 Harness 设置、凭据存储和持久历史，应按私有数据保存。恢复后保持原项目路径，并验证会话恢复。

另一台电脑克隆 Research Harness、安装依赖、配置自己的 `.env`，再登记该电脑的项目绝对目录即可。GitHub 用于同步应用代码，当前版本各电脑分别保存自己的项目索引和会话。跨电脑历史导入、路径映射与数据迁移属于后续开发阶段。
