# 下一步上传GitHub

当前冻结版本：2026.11.18-fulltext。此步骤由你下一步执行，本次没有执行git add、commit或push。

## 从哪个目录操作

当前电脑的原research-harness目录已经保留Git历史和origin远程。如果你在该原目录操作，无需重新git init或clone。

如果使用GitHub-ready ZIP：先克隆原仓库，再将ZIP内的源码文件复制到克隆目录，保留克隆目录中的.git。ZIP故意不含.git、个人配置和数据。不要用整个科研工作台桌面目录作为上传范围。

```sh
git clone https://github.com/boliQi/research-harness.git
cd research-harness
```

## 建议提交到新分支

在正确的仓库根目录执行，先检查状态和改动内容：

```sh
git status --short
git diff --stat
git switch -c workbench/fulltext-20261118
git add .
git diff --cached --stat
git diff --cached
```

确认待提交文件只包括代码、依赖清单、技能插件及其许可、文档和测试；不包含.env、config.json、data、local-state、node_modules、虚拟环境和日志。然后：

```sh
git commit -m "Integrate academic skills and full-text research workflow"
git push -u origin workbench/fulltext-20261118
```

有原仓库写权限时可推送该分支，再发起Pull Request。没有写权限时，先Fork到自己的账号，在自己的Fork中推送后向原仓库发起Pull Request。不要强制推送或直接覆盖main。

## 合并说明可写什么

- 保留本地Python+HTML架构，新增四阶段科研界面与项目存储。
- 学术插件实际接入Harness，联网API仅使用DeepSeek。
- 公开全文获取、项目全文库检索与逐字引用核对，问题/痛点需有正文依据。
- 结构化方案、固定协议真实实验、产物下载与结果版本绑定。
- 通用安装脚本、官方npm运行时锁文件、第三方署名和28项测试。

当前不保证全文全部可得，不支持扫描PDF的内置OCR；自动实验只支持固定数字识别教学协议。不要把这些功能写成已经实现。
