# 架构与数据边界

浏览器HTML/JS → Python HTTP后端 → research-workbench Harness profile → 学术技能/DeepSeek模型与web工具。

后端独立负责公开文献下载、PDF/网页文本解析、项目全文片段检索、逐字引用核对、项目状态和实验执行。Harness负责技能加载、模型与工具循环；四阶段顺序和用户选择由后端控制。

分析阶段关闭web，仅加载当前技能与已提供的全文证据。发现阶段web provider固定为DeepSeek Search和Fetch；科研模型不获得shell、文件写入或插件安装工具。插件参考文档中的其他API方法不会因此自动成为可执行能力。

## 关键文件

| 文件 | 职责 |
|---|---|
| server.py | 本地HTTP、静态页面、项目与文件接口 |
| workspace.py | 后台任务、模型调用、状态与选择、结果提交和引用校验 |
| harness_runtime.py | 源码/npm双入口、专用profile、环境与供应商约束 |
| fulltext_library.py | 来源核对、公开下载、正文解析、分段、相关性检索与定位 |
| research_experiments.py | 结构化方案、固定数字协议、代码生成与独立评价 |
| app.js / library-ui.js / experiment-ui.js | 四阶段交互、全文库、指标和产物展示 |
| research_profile.patch.yml | 技能运行配置、DeepSeek provider及工具限制 |
| research_analysis.patch.yml | 分析阶段关闭web |

表中的Python/JS文件均位于my-harness-ui/。评价器、协议和代码提示词在experiment_assets/。

## 数据

所有项目在data/<id>/project.json；literature/放原始文献和提取文本，runs/放模型输入/输出与工具记录，experiments/放代码/协议/指标/日志，exports/放报告。local-state/harness是工作台自己的运行状态，和桌面profile隔离。

这些目录不上传。正文会按用户操作发送到DeepSeek；文件留存在本机并不意味着模型分析过程完全离线。

模型回复必须实际加载指定技能才能接受。格式修复有次数限制；不能用模板顶替模型失败。问题与痛点必须有全文片段引用，无正文则阻止生成。已解析正文不等于已经完整识别图像/表格或核实论文版本。

上游输入变更会使下游方案与实验过期；实验结果绑定输入指纹。旧运行保留以便追溯，不能被自动套用到新假设。教学示例使用预设假设，不能冒充从文献发现的研究结论。
