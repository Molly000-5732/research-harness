# 本地接口简表

默认服务：http://127.0.0.1:8001，仅绑定本机回环地址；前端与API同源。接口错误使用error字段。异步任务接口返回jobId，通过项目的jobs轮询进度。

| 方法与路径 | 用途/请求 |
|---|---|
| GET /api/health | 本地服务与Harness目录 |
| GET /api/capabilities | 可选实验依赖与协议状态 |
| GET /api/projects | 项目列表、状态和覆盖情况 |
| POST /api/projects | 创建项目，JSON {field} |
| GET /api/projects/:id | 项目详情与任务进度 |
| POST /api/projects/:id/start | JSON {stage}，questions/painpoints/plan/experiment/validation |
| POST /api/projects/:id/select | JSON {stage,itemId}，保存选择 |
| POST /api/projects/:id/cancel | 取消当前项目任务 |
| POST /api/projects/:id/upload | JSON {name,base64,kind,paperId?}；kind为literature/results |
| POST /api/projects/:id/fetch-fulltext | JSON {paperId?}；重试单篇或获取项目文献 |
| POST /api/projects/:id/sync-library | 导入直接加入全文文件夹的新文件 |
| GET /api/projects/:id/library | 覆盖数量与检索片段 |
| GET /api/projects/:id/library-files/:fileId | 查看已入库文件 |
| POST /api/projects/:id/folder | JSON {section?}；literature表示全文目录，Windows打开目录，其他平台返回路径 |
| GET /api/projects/:id/export | Markdown研究报告 |
| POST /api/examples/digits | 新建固定数字识别教学项目 |
| POST /api/projects/:id/auto-run | 模型代码生成与固定协议训练 |
| POST /api/projects/:id/script | JSON {script}，保存用户脚本 |
| POST /api/projects/:id/run | 执行已保存并经用户审阅的通用Python脚本 |
| GET /api/projects/:id/artifacts/:runId/:filename | 白名单实验产物下载及完整性核对 |

API不会提供模型密钥。上传、自动下载和通用脚本有大小/时限约束；通用脚本以当前用户权限运行，并非通用安全沙箱。异步任务失败以jobs中的status/error为准，不能仅凭创建任务时的HTTP200判断研究成功。
