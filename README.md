# Research Harness 科研工作台

版本：**2026.11.18-fulltext**。基于原始research-harness的本地Python + HTML/JavaScript科研工作台，保留四阶段交互与项目文件存储。

- 问题调研：学术技能指导中英文DeepSeek检索，获取公开论文正文并存入本地全文库。
- 痛点定位：基于选定问题检索库内正文片段，每项结果必须引用可定位的原文。
- 方案规划：结构化研究目标、假设、数据、基线、改进、消融、指标、判据和实施步骤。
- 实验验证：固定数字识别协议可自动生成受约束代码、实际训练、计算指标并解读；其他课题支持通用脚本或导入结果。

模型、搜索和链接阅读只调用DeepSeek API。公开网页/PDF由本地程序下载，PDF由pypdf解析，不调用Crossref、OpenAlex等其他文献数据库API。

## 快速开始

需要Python **3.11+**、Node.js **24.9+**（包含npm）与网络。基础网站最低支持Python3.10；可选自动实验依赖要求3.11+。Windows为已验证平台，macOS/Linux脚本未在对应设备实测。

1. 下载或克隆本仓库，放在可写目录。
2. Windows双击`SETUP.cmd`（或`首次安装.cmd`）。脚本创建本目录`.venv`、安装pypdf及固定版本的官方Harness运行时。
3. 提示时输入自己的DeepSeek API Key；输入隐藏，也可回车跳过后运行`CONFIGURE.cmd`补填。使用npm运行时时密钥保存在`runtime/.env`。
4. 双击`START.cmd`（或`启动科研工作台.cmd`），访问 http://127.0.0.1:8001/ 。保持终端运行，Ctrl+C停止。
5. 需要重新运行数字识别实验时，运行`INSTALL-EXPERIMENTS.cmd`，安装到同一个`.venv`中。

macOS/Linux：

```sh
python3 bootstrap.py --setup
python3 bootstrap.py --install-experiments  # 可选
sh start.sh
```

这是需要首次联网安装的源码项目，不是离线EXE；源码不包含模型密钥、个人项目或预下载论文。不配置密钥可打开空白网站，真实检索和生成需要有效密钥及可用额度。

### 已有Harness源码

复制`config.example.json`为`config.json`，设置`harness_root`为已构建源码目录；支持绝对路径或相对本仓库的路径，也可使用`HARNESS_ROOT`环境变量。密钥放在该源码目录的`.env`。无需重新构建或复制整份Harness到本仓库。

Windows JSON路径请使用正斜杠，例如`D:/code/deepseek-harness`。`port`默认8001，端口冲突时可改为8002。已有虚拟环境时启动器优先使用它；实验依赖应安装到实际运行服务的Python环境。

## 全文与学术技能

专用`research-workbench` profile生成于`local-state/harness`，与桌面配置隔离。模型必须实际成功加载相应技能：调研/痛点使用deep-research，规划/实验使用academic-pipeline，结果解读使用academic-paper-reviewer。

联网发现任务仅开放DeepSeek搜索与阅读；其他分析调用关闭web工具。科研模型没有任意shell、文件写入或插件管理工具；它不能依照插件参考材料改用其他数据库API。

文献库支持获取与重试、上传PDF/TXT/Markdown、打开全文文件夹和同步直接加入的文件。系统区分题录、短片段和已解析正文。没有可用正文时阻止普通课题的问题/痛点生成，不用搜索摘要代替全文。

正文按项目分段、本地检索，最多选24段、每篇最多4段；逐字引文、segmentId、文件和可用页码由后端核对。网页不编造PDF页码。获取失败会保留来源与原因，可通过自己的访问权限下载后上传。

已解析正文不保证公式、表格、图像与补充材料完整解析。扫描件需先做OCR；论文版本、题录和科学结论仍需复核。检索和正文覆盖率不保证。

## 实验范围

“新建研究项目”中的数字识别教学项目使用真实sklearn digits数据，三方法×三个随机种子共9组训练。模型只编写分类器工厂，固定评价器控制数据划分、训练、测试、指标和验收。保留负面结果，达到均值阈值不等于统计显著或学术创新。

其他课题保留用户审阅的Python脚本与外部结果导入。通用脚本具有当前用户权限；GPU、设备及其他实验依赖由实际环境提供。上游修改后旧结果标记过期，历史保留。

## 依赖与目录

- `requirements.txt`：基础Python依赖。
- `requirements-experiments.txt`：可选CPU实验依赖。
- `runtime-manifest/`：官方Harness 0.2.2-rc.1的npm清单和锁文件，首次安装时复制到忽略的runtime目录。
- `vendor/academic-research-skills/`：学术插件0.1.0及原始署名、许可。
- `my-harness-ui/`：前端、服务、任务编排、全文库和实验执行模块。
- `tests/`：离线/本地训练测试及显式运行的真实调用验收脚本。
- `docs/`：架构、实验说明、已验证环境与验收范围。

运行后：`data/`保存项目、全文、模型输入输出和实验产物；`local-state/`保存Harness状态；`.venv/`和`runtime/`保存本机依赖。这些目录均不提交Git。

## 验证

```sh
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile bootstrap.py start-workbench.py my-harness-ui/server.py my-harness-ui/workspace.py my-harness-ui/fulltext_library.py
node --check my-harness-ui/app.js
node --check my-harness-ui/library-ui.js
node --check my-harness-ui/experiment-ui.js
```

安装可选实验依赖后28项测试通过；未安装时会跳过涉及实际训练的可选测试。真实模型和搜索验收会产生API用量，不在默认单元测试中自动执行。详见[验收记录](docs/VALIDATION.md)。

## 使用和上传说明

研究领域、所选文献及导入结果会按操作发送到DeepSeek；公开文件下载会访问相应论文网站。项目文件留在本机。不要提交`.env`、`config.json`、`data/`、`local-state/`、运行日志或登录凭据。

下一步GitHub上传流程见[GITHUB_UPLOAD.md](GITHUB_UPLOAD.md)，当前整理没有执行commit或push。

第三方学术插件使用CC-BY-NC-4.0，适用非商业用途并要求保留署名。第三方材料的许可证各自适用；本次整理未为整个项目额外指定统一许可证。详见[第三方说明](THIRD_PARTY_NOTICES.md)。
