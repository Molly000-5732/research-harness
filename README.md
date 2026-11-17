# Research Harness

通过本地 HTML 页面调用 DeepSeek Harness，使用 Python 标准库提供 HTTP 服务。输入任务后，后端启动 Harness 官方 Headless profile，并将最终答案显示在页面中。

## 环境

- Python 3.10 或更高版本。
- Node.js 24.9 或更高版本。
- 已安装依赖并完成构建的 DeepSeek Harness 源码目录。
- 在 Harness 根目录的 `.env` 或启动环境中配置 `DEEPSEEK_API_KEY`。

## 在另一台电脑运行

克隆本仓库后，将启动命令的最后一个参数替换为该电脑已有的 Harness 源码目录。

```powershell
git clone https://github.com/boliQi/research-harness.git
cd research-harness
python my-harness-ui/server.py "D:\path\to\deepseek-harness"
```

Linux 或 macOS 可以使用以下启动命令。

```sh
python3 my-harness-ui/server.py /path/to/deepseek-harness
```

打开 [本地页面](http://127.0.0.1:8001)，输入任务并发送。按 Ctrl+C 停止服务。可使用 `--port 8002` 更改端口。

如果 Harness 位于本仓库根目录下的 `deepseek-harness-master` 文件夹，可以省略启动命令的目录参数。

## 执行方式

页面调用 `/api/chat`，Python 通过 stdin 将任务文本交给 `dsh --profile headless --approval-policy never -` 对应的源码入口。任务工作目录为传入的 Harness 目录，工具使用 Headless 的权限策略，需要人工批准的操作会被拒绝。

每次发送创建独立会话，最多运行 300 秒。同一时间运行一个任务，页面在任务结束后显示最终回复。

## 文件

- `my-harness-ui/index.html` 提供输入框、发送状态及结果展示。
- `my-harness-ui/server.py` 提供本地服务并调用 Harness。

本仓库的 `.gitignore` 排除本地 Harness 源码目录、压缩包、密钥、依赖和运行缓存。每台电脑使用各自已有的 Harness 安装与凭据。
