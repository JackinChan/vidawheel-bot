# [待评审] Codex 桌面连接插件本地验收报告

<!-- Installation, transport tests and actual desktop model execution are separate acceptance levels. -->

## TLDR

| 字段 | 内容 |
| --- | --- |
| 这是什么 | VidaWheel Bot 0.1.1 本地插件与 Git 插件源实现及验收记录。 |
| 谁该看 | 维护人员和参与 Mac/Windows 试用的开发同事。 |
| 当前状态 | 待评审，内部试用 |
| 当前结论 | 插件清单、本地安装、stdio 工具、关闭清理、九项测试及真实 Docker HTTP MCP 只读连接通过；桌面既有聊天自动执行与 Mac 生命周期未验收。 |
| 负责人 | 待指定 |
| 最近更新 | 2026-10-30 by Codex |

## 结构与实现

现有 Git 仓库同时保存服务器工程和本地插件。根目录 .agents/plugins/marketplace.json 定义 vidawheel 插件源，指向 plugins/vidawheel-bot；无需拆分仓库。Git 插件源安装只获取已提交文件，个人配置和依赖安装目录不提交。

本次不修改 event_receiver、mcp_server、bot_core 或数据库结构。连接器复用原有 claim_issue、get_issue_context、renew_issue、release_issue、submit_analysis、fail_issue 接口，身份与机器人授权继续由服务器控制。Docker 构建上下文排除本地插件。

连接器为 Node.js/TypeScript 编写的本地 stdio MCP 进程，预构建单文件随 Git 分发。默认暂停。提供状态、诊断、聊天列表、绑定、启停、歧义投递恢复及过期投递清理七个工具。凭据由用户个人文件提供，不放入聊天或插件源。

领取前检查 GUI 进程及已有 app-server 中的目标聊天和工程目录，不启动新 daemon、不创建新聊天。个人目录锁控制单消费者，其他实例等待接替。对同一任务持有原服务租约并续租；投递前记录 dispatching，确认 turn ID 后记录 running。歧义投递不自动重发；最终结果与服务器历史核对，用于恢复提交响应丢失。所有模型任务只请求只读分析，不自动回复飞书。

## 已验证

- TypeScript 类型检查通过。
- 九项测试通过：远端端点限制与聊天范围；FastMCP 多文本块列表；最终答案识别；进程锁；投递前日志/租约提交；歧义投递不重放；上下文失败退避；提交响应丢失核对；过期租约不提交。
- 实际构建产物通过官方 MCP SDK 的 stdio 初始化，发现七个工具，bridge_status 调用及关闭后 stopped 状态通过。
- 使用本地 Docker 的真实 HTTP MCP，以现有个人身份读取任务列表与一个任务上下文成功，没有领取或完成真实任务。真实接口发现 FastMCP list_issues 按每行一个 text block 返回，已修复客户端解析并补充测试。
- 依赖安装审计为零已知漏洞。dist/bridge.mjs 由 esbuild 生成，运行不依赖插件目录内的 node_modules；用户仍需 Node.js。
- 已通过 CLI 注册本地插件源并安装。Git SSH 插件源的最终安装复核在提交后执行，结果以实际命令输出为准。

## 未验收与限制

本机 Codex CLI 版本 0.165.0-alpha.1.2。桌面 GUI 实际进程名为 ChatGPT.exe。CLI 的 app-server proxy 及 daemon version 均无法连接默认控制套接字，报 Windows OS error 10050；桌面提供的内置聊天工具可列出聊天，不证明本地插件拥有同一接口。未修改桌面启动方式、未直接读写其 SQLite/会话文件、未以另建 daemon 冒充已有桌面聊天执行成功。

因此没有投递真实模型请求，也没有自动消费用户的待处理任务。需在提供可连接共享入口的桌面版本/环境中，验证绑定聊天投递、桌面实时显示、最终答案回传。Mac 尚无真机环境，GUI 退出与休眠恢复须另行验收。插件 MCP 按宿主需要加载，不能承诺仅打开软件首页就开始领取。关闭窗口和退出软件需区分。

突发断电或进程被杀可能留下投递日志和未完成 turn；租约到期由服务器回收，需人工核对再恢复。当前每个个人配置绑定一个工程/聊天，文本上下文已实现，图像输入尚未移植。只读文件策略不保证限制宿主已经授予的所有外部工具，应使用只启用必要读取工具的分析聊天。

## 实际变更文件

| 文件 | 调整 |
| --- | --- |
| [.agents/plugins/marketplace.json](/D:/projects/vidawheel-bot/.agents/plugins/marketplace.json) | Git 插件源及子目录映射。 |
| [plugin.json](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/plugin.json)、[mcp.json](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/mcp.json) | 插件清单与本地进程入口。 |
| [package.json](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/package.json)、[package-lock.json](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/package-lock.json)、[tsconfig.json](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/tsconfig.json) | 依赖锁定、构建与类型检查。 |
| [config.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/src/config.ts)、[app-server.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/src/app-server.ts)、[remote.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/src/remote.ts) | 个人配置、既有会话连接、任务 MCP 客户端。 |
| [bridge.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/src/bridge.ts)、[main.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/src/main.ts) | 任务处理、恢复、生命周期和本地工具。 |
| [SKILL.md](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/skills/vidawheel-tasks/SKILL.md) | 配置和只读分析工作流。 |
| [bridge.test.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/test/bridge.test.ts)、[smoke.ts](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/test/smoke.ts) | 逻辑与实际 MCP 传输验收。 |
| [bridge.mjs](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/dist/bridge.mjs) | 随 Git 分发的构建产物。 |
| [插件 README](/D:/projects/vidawheel-bot/plugins/vidawheel-bot/README.md)、[仓库 README](/D:/projects/vidawheel-bot/README.md) | 安装配置步骤与准确边界。 |
| [.gitignore](/D:/projects/vidawheel-bot/.gitignore)、[.dockerignore](/D:/projects/vidawheel-bot/.dockerignore) | 排除本机依赖和服务器不需要的插件。 |
| [本报告](/D:/projects/vidawheel-bot/docs/test-reports/plugin-local-verification-20261030.md) | 验收证据与未完成项。 |
