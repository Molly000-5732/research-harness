# 本地 Harness 页面

使用 Python 标准库提供 HTML 页面，通过 Harness 官方 headless profile 执行单次任务。每次请求启动一个独立进程，任务内容通过 stdin 传入，返回最终文本。

## 准备

需要 Python 3.10+、Node.js 24.9+，以及已安装依赖并完成构建的 DeepSeek Harness 源码目录。在 Harness 目录的 `.env` 文件中设置 `DEEPSEEK_API_KEY`，自定义模型网关可设置 `DEEPSEEK_BASE_URL`。已有 Harness 安装可以直接通过启动参数指定。

## 启动

在本目录执行以下命令。

```powershell
python server.py
```

默认使用旁边的 `deepseek-harness-master` 目录，也可传入绝对路径。

```powershell
python server.py D:\code\research_harness\deepseek-harness-master
```

打开 http://127.0.0.1:8001 输入任务并发送。API Key 保存在 Harness 的 `.env` 中。服务监听本机回环地址，任务工作目录为 Harness 源码目录，工具调用遵循 headless 的权限策略，`--approval-policy never` 会拒绝需要人工批准的操作。每次请求单独创建会话，最多运行 300 秒，并发请求会返回忙碌提示。按 Ctrl+C 停止服务。
