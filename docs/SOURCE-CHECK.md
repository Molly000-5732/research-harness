# 源码交付检查

冻结版本：2026.11.18-fulltext。仅准备代码和文档，没有执行Git提交或推送。

- 明确文件白名单打包；无.git、实际.env、config.json、data、local-state、runtime、node_modules、虚拟环境和运行日志。
- 实际密钥/令牌/私钥模式及发送方个人路径检查通过。
- 原仓库Git忽略边界已验证；.env.example、配置模板、vendor许可和runtime-manifest允许提交。
- 28项测试、Python编译及前端JS语法检查通过。
- 通用启动器不含个人路径；本机私人路径只存在于忽略的config.json中。
- 第三方许可与来源说明保留，未对未知权利代码另加统一许可证。
- 依赖锁文件和已测试环境版本已整理；新设备首次安装仍需网络和自己的DeepSeek密钥。

SOURCE_MANIFEST.json列出逐文件SHA256；不包含自身哈希。源码压缩包解压后已逐文件核对。
