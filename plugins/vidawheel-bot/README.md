# VidaWheel Bot 桌面插件（0.1.1）

<!-- This is a local connector, not a new model service or a Feishu event receiver. -->

本插件连接已有的公司任务 MCP 和本机 Codex 会话服务，将飞书协作问题投递到用户明确绑定的现有聊天。服务器的 event_receiver、mcp_server、数据库继续独立运行，不需要将业务服务放入插件。

当前为内部试用版本。Windows 本机 CLI 的共享控制套接字连接失败，尚未验证真实桌面聊天投递；Mac 尚待真机验收。连接失败时不领取任务，不启动新的 Codex daemon 或临时模型会话。不能把下述安装成功等同于完整自动分析验收。

## 同事安装

需要已登录的 Codex 桌面版、支持 `app-server proxy` 的 Codex CLI，以及 Node.js 22 或更新的受支持版本。首版不内置 Node；如果桌面启动环境找不到 `node` 或 `codex`，需要将它们配置为实际绝对路径。不要假定终端中的 PATH 与桌面进程相同。

仓库同时包含服务器工程和插件；根目录 `.agents/plugins/marketplace.json` 将插件指向 `plugins/vidawheel-bot`。只使用一个 Git 仓库即可。

```sh
codex plugin marketplace add git@github.com:JackinChan/vidawheel-bot.git
codex plugin add vidawheel-bot@vidawheel
```

私有仓库需先具备对应 Git SSH 访问权限。安装后重启桌面版或新开聊天，在插件目录确认 VidaWheel Bot 已启用。已打开的聊天不保证立即加载新工具。构建后的 dist/bridge.mjs 已提交，安装者不需要 npm install。

首次在个人配置目录创建凭据文件，填入维护人员分配的个人 MCP 凭据，不要在聊天中粘贴。Mac 建议 `~/.vidawheel-bot/credential`，文件权限设为 600；Windows 使用仅当前用户可读的位置。不要使用机器人 App Secret，不要放进项目 Git 仓库。

找到插件安装路径后执行一次（CLI 安装输出会给出 installedPath）：

```sh
node /absolute/plugin/path/dist/bridge.mjs setup https://your-company-host/mcp /absolute/personal/credential
```

命令会生成 `~/.vidawheel-bot/config.json`，默认暂停，拒绝覆盖已有配置。服务器尚未部署时只能使用本机测试端点；示例域名不是可用服务。运行状态及投递日志同样保存在个人目录，不在插件安装缓存中。可用 VIDAWHEEL_BRIDGE_HOME 指定独立配置目录。

随后在启用插件的聊天里要求：

1. 调用 bridge_chats 查找本人要绑定的现有聊天，按聊天 ID 区分同名会话。
2. 明确选择目标聊天及工程绝对路径，调用 bridge_bind。插件不会新建聊天。
3. 调用 bridge_doctor 验证桌面进程、既有会话服务、目标目录和公司 MCP。
4. 确认 ready=true 后，要求调用 bridge_enable(enabled=true) 开始接收。

个人 config.json 可设置 codexBin 的绝对路径、已有服务的 socketPath，以及 desktopProcess。默认识别 Codex 或 ChatGPT 桌面 GUI 进程；如果使用其他名称的桌面宿主，应按本机实际 GUI 主进程名配置。不要填写 CLI 或后台 daemon 进程名，否则无法区分桌面是否退出。进程存在只证明 GUI 在运行，不证明它已提供共享控制入口；doctor 仍需验证后者。

## 运行与停止

连接器是 Codex 启动的 stdio MCP 子进程，不注册 launchd、登录项、系统服务或独立常驻 daemon。MCP 尚未加载时不接收任务；不能承诺仅打开应用首页就开始监听。可通过 bridge_status 查看状态。

MCP 输入关闭、SIGTERM/SIGINT 时关闭本机代理和远程 MCP；此外每轮领取前检查 GUI 主进程，GUI 不在时不请求任务。只关闭 Mac 窗口通常不等于退出应用。即使宿主保留 MCP 进程，桌面不存在时也不会拉取。多聊天启动多个插件实例时，通过个人目录进程锁仅保留一个消费者。工作电脑休眠时无法处理任务；服务器保存待处理任务。

bridge_enable(enabled=false) 暂停领取。正在运行的本插件分析会尝试中断对应 turn 并释放任务。进程突然被杀死时无法保证立即清理；服务器租约到期后回收任务，插件保留日志供人工复核。

每个个人配置绑定一个目标聊天，处理该员工凭据授权的机器人任务。需要不同工程分流时应分别配置员工授权/独立连接配置，目前没有按文档模块自动选择聊天的功能。凭据权限仍由服务器决定。

## 投递与恢复

每次任务使用原 MCP 租约，定期续租。任务上下文包含正文和完整评论引用；当前桌面连接器投递文本/blocks，不将图片转换为模型图像输入，旧 Python worker 的图像能力未宣称移植。分析 turn 请求 readOnly 和 never 自动审批策略，提示明确只读分析，最终答案写回 submit_analysis，不发送飞书消息。只读文件策略不等于能拦截宿主已提供的所有外部写入工具；应在专用分析聊天中仅启用必要的读取工具。

delivery.json 在投递前写入 dispatching，收到 turn ID 后写入 running，再记录 completed/submitted。进程在发送与确认之间中断时不自动重发，状态为 ambiguous_dispatch_manual_recovery_required。暂停后检查聊天历史，再用 bridge_recover 指定具有同一任务/版本标记的 turn ID。恢复只接管该 turn，不重复发送提示。

已收到最终答案但提交响应丢失时，通过服务器分析历史核对原版本/结果，避免重复提交。租约已过期时拒绝继续提交；需要人工确认模型已停止、服务器任务不在运行后，调用 bridge_clear_delivery(taskCode=...) 归档本地记录，再启用。不能保证跨机器和任意崩溃情形下模型执行严格恰好一次。

## 更新与开发验证

```sh
codex plugin marketplace upgrade vidawheel
```

然后在插件目录更新/重新安装插件并重启相关聊天。发布时同步 plugin.json、package.json 版本并重新构建提交；不要编辑 Codex 安装缓存。

维护人员在本目录执行 npm ci、npm run check、npm test、npm run build。dist 是 esbuild 生成的可分发产物，修改 src 后必须重新生成。`node --import tsx test/smoke.ts /absolute/installed/dist/bridge.mjs` 验证实际安装产物的 stdio 工具发现及关闭；设置 MCP_EMPLOYEE_ONE 后还会对本地真实 HTTP MCP 做只读连接验收，不领取任务。
