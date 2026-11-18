# 第三方来源与许可说明

## 原始项目

本项目在 https://github.com/boliQi/research-harness 的HTML/Python本地入口上扩展。本次整理不改变原有代码权利归属，也未擅自为整个仓库添加统一开源许可证。上传源码不代表获得或授予任何未声明的第三方使用权。

## Academic Research Skills插件

目录：vendor/academic-research-skills。

- DSH移植：https://github.com/nullptr-DZF/dsh-academic-research-skills ，插件版本0.1.0。
- 原始ARS：https://github.com/Imbad0202/academic-research-skills ，作者Cheng-I Wu（Imbad0202）。
- 许可：CC-BY-NC-4.0。遵守非商业使用范围与署名要求。
- 原始LICENSE、NOTICE.md、README.md及插件代码均保留。本应用通过自己的profile限制工具和外部API使用，没有改写插件的学术材料。

## 同门实验模块

experiment_assets/evaluate_digits.py、digits_protocol.json、code_prompt.md来自协作交接包SciPilot-2026-11-17-afternoon-handoff，分别对应原evaluate-digits.py、归档实验协议及experiment-code.v1.md。经项目用户要求整合，保留独立评价器与固定协议的设计。交接包未附独立许可证，本次未将其改署他人姓名或重新许可为MIT；原始贡献归属由项目协作者维护。

## 运行时与Python依赖

DeepSeek Harness官方运行时通过npm安装；pypdf、numpy、scikit-learn及其依赖通过pip安装。其源码、二进制依赖和个人凭据不随本源码包分发，使用各自上游许可。
