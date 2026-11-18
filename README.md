# Research Harness 科研工作台

基于官方 DeepSeek Harness Python SDK 的本地科研工作台。当前版本保留研究总览、问题调研、痛点定位、方案规划、实验验证、文献库和研究记录，采用暖米色与深绿色界面。

## 安装与启动

需要 Python 3.10+、网络连接及可用的 DeepSeek API 密钥。发布验证环境为 Windows x64、Python 3.14。浏览器运行无需 Node.js，也不依赖 CDN。

1. 下载本仓库 ZIP 并解压，或克隆仓库。
2. Windows 双击 `SETUP.cmd` 安装虚拟环境与固定版本的依赖。
3. 复制 `.env.example` 为 `.env`，填写 `DEEPSEEK_API_KEY`。可选设置 `DEEPSEEK_BASE_URL`。
4. 双击 `START.cmd`，在浏览器打开 <http://127.0.0.1:8003/>。运行期间保持服务进程开启。

也可以手动启动：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe my-harness-ui/server.py --port 8003
```

macOS / Linux 使用 `.venv/bin/python` 替代 Windows 的 Python 路径。服务支持 `--port`、`--data-dir`、`--env-file` 和 `--model`；默认模型为 `deepseek-v4-flash`。模型可用性和费用由账号与官方服务决定。

## 使用流程

1. **新建项目**：填写项目名称和已经存在的工作区绝对路径。在研究总览填写并保存研究背景，包括领域、目标、限制和已有材料。
2. **问题调研**：SDK 搜索并读取文献，输出带说明与文献依据的候选问题。展开“文献依据”可查看原文片段、章节位置、来源和核对状态，选择一个问题进入下一阶段。
3. **痛点定位**：基于选定问题和文献生成可选痛点卡片，确认一项交给方案规划。
4. **方案规划**：查看实施流程概览，点击“打开完整方案文档”，在本地应用中修改并保存。点击“刷新文档并提交到实验验证”，服务端读取磁盘最新全文，保存为最终方案；此操作不会自动运行实验。
5. **实验验证**：通过对话规划实验、生成代码、运行和读取结果。需要审批的工具操作可查看参数并批准一次或拒绝。也可上传已有结果进行分析。

四个阶段均保留追加需求输入框。只有点击发送才提交输入；模型结合当前主题、上游已确认内容和当前成果进行修订。历史对话与文献依据默认折叠。重新确认上游成果会使下游旧结果过期，需要重新生成或确认。

## 正文与证据说明

搜索、正文读取、模型及文件 / Shell 工具调用统一通过官方 SDK，不另接独立模型或搜索 API。SDK 访问的网页、论文站点和工具服务取决于官方运行时与网站可访问性。

“原文片段已核对”表示引文在实际成功读取的工具返回中匹配，且来源相符；搜索摘要不作为核对依据。该标记不表示整篇论文已完整下载或读完。付费墙、PDF 格式及长网页截断仍可能造成正文缺失；可上传合法获取的材料，再要求模型补充读取。证据不足的候选条目不能选择。

## 本地数据与文档

项目工作区由用户指定；附件位于该工作区的 `research-files/literature` 与 `research-files/results`。默认应用数据目录是仓库根目录下 `.research-harness`，其中 `app.sqlite3` 与 `dsh-home` 共同保存项目索引、任务、对话和 SDK 会话。备份时请先正常停止服务，并同时备份数据目录及各项目工作区。

附件上传上限 10 MB，下载上限 25 MB，最多列出 300 个常见类型文件。完整方案支持 UTF-8 Markdown / TXT，最多 60000 字符、512 KB；只读取登记工作区内的文件。任务刷新页面后继续运行；异常退出的未完成任务会标记为待核对，请检查实际产物后再继续。

密钥、虚拟环境、缓存和个人研究数据不在发布包中，每台设备需自行安装和配置。此版本不自动迁移旧版数据。

## 开发与验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s my-harness-ui/tests -q
.venv\Scripts\python.exe -m pip check
node --check my-harness-ui/app.js
npm ci --prefix dev/markdown-renderer --ignore-scripts
node my-harness-ui/tests/test_conversation.cjs "$PWD/dev/markdown-renderer/node_modules/jsdom"
node my-harness-ui/tests/test_markdown.cjs "$PWD/dev/markdown-renderer/node_modules/jsdom"
node my-harness-ui/tests/test_plan_document.cjs "$PWD/dev/markdown-renderer/node_modules/jsdom"
```

前端回归测试建议使用 Node.js 24+；Node.js 仅用于开发检查。详见 [架构说明](docs/ARCHITECTURE.md) 和 [发布验证](docs/VALIDATION.md)。第三方库许可随源码保留在 `my-harness-ui/vendor`。
