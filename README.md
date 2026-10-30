# VidaWheel Bot 协作任务服务

<!-- 本仓库实现事件接入与远程任务领取，不包含自动修改代码或自动回复飞书。 -->

## TLDR

| 字段 | 内容 |
| --- | --- |
| 这是什么 | 为多个飞书机器人接收协作问题，并让员工通过 Codex MCP 领取和提交分析。 |
| 谁该看 | 平台维护人员部署配置；开发人员连接 MCP、领取任务并结合本地仓库分析。 |
| 当前状态 | 草稿 |
| 当前结论 | 已实现群聊与文档评论 @接入、问题串关联、任务租约与自动分析 worker；真实飞书联调及公司服务器部署尚待完成。 |
| 负责人 | 待指定 |
| 最近更新 | 2026-10-30 by Codex |

## 工程结构

- `event_receiver/`：飞书官方 SDK 长连接；每个应用一个进程，允许群和机器人精确匹配，成功落库后返回。
- `mcp_server/`：官方 MCP SDK，Streamable HTTP，员工独立 Bearer 凭据与服务端机器人授权映射。
- `analysis_worker/`：员工侧可选自动消费者，通过 MCP 等待领取、心跳续租和只读 Codex CLI 分析，失败退避重试。
- `bot_core/`：共享配置、任务队列、租约、审计及来源机器人身份读取文档。
- `postgresql-migrations/`：PostgreSQL DDL。`ve_bot_event` 去重，`ve_bot_task` 管理任务，`ve_bot_task_audit` 记录领取和结果提交。
- `tests/`：独立数据库上的隔离、去重、并发和租约验证。

不需要额外 Redis 或独立任务调度服务即可领取工作。PostgreSQL 使用事务和 SKIP LOCKED 处理并发。领取租约为五分钟，每次领取生成新的 lease_token，旧客户端不能覆盖新任务结果。

## 配置与运行

1. 使用 Python 3.12。安装锁定依赖后安装本项目：`pip install -r requirements.lock`、`pip install --no-deps -e .`。
2. 将 `config.example.json` 复制为忽略提交的 `config.local.json`，填每个应用的 app_id、tenant_key、机器人 open_id、允许的 chat_id 和文档域名。
3. 在本地 `.env` 配置环境变量（不要提交）：`DB_PASSWORD`、`DATABASE_URL`、`MCP_PUBLIC_URL`、每个机器人 `secret_env` 指向的变量、每个员工 `token_env` 指向的变量。所有变量存放真实值，文档不提供凭据。
4. 容器内 DATABASE_URL 使用 PostgreSQL 主机 `db`、端口 5432、数据库 `vidawheel_bot`、用户 `bot`。连接字符串中的特殊字符需要 URL 编码。
5. `docker compose up --build -d db mcp` 启动数据库和 MCP；配置好真实飞书应用后，用 `docker compose --profile feishu up --build -d` 启动接收程序。
6. 服务器通过现有反向代理提供 HTTPS，将 `/mcp` 转发至 loopback 8000。不要直接暴露数据库端口。MCP_PUBLIC_URL 填最终 HTTPS MCP 地址；反向代理保留 Authorization 请求头。

首次空数据库自动执行初始化脚本；已有数据库新增迁移须由维护人员明确执行，不能靠容器重启自动迁移。

## 飞书配置

每个独立应用分别启用机器人能力、长连接事件订阅和 `im.message.receive_v1`，添加到允许群。按平台要求申请群 @消息接收、wiki/docx 读取权限并发布。对目标文档授权应用访问。接收事件时校验 tenant_key、app_id、chat_id 及 mentions 中的机器人 open_id。

支持群聊文本 @及 `drive.notice.comment_add_v1` 文档评论通知。按 SDK schema 校验 `is_mentioned`、`notice_meta.to_user_id.open_id`、文件类型及 `allowed_documents`。评论串按 bot + docx token + comment_id 归并，群消息按 root_id/message_id 归并。必须配置允许读取的 docx 对象 token；Wiki 链接解析后也按对象 token 校验。正文 @、多维表格评论未在 SDK 事件链路内，不能假定它们与 docx 评论事件相同。

回调模式使用 `docker compose --profile callback up --build -d receiver-http`，通过 HTTPS 反向代理转发 `/events/{bot_code}` 到 8001；配置 `encrypt_key_env` 和 `verification_token_env` 对应环境变量。SDK 校验签名及验证信息，业务回调要求五分钟内时间戳，事件按平台 ID 去重。支持 URL challenge。一个应用在飞书后台选择一种接收模式，不要同时打开两套生产消费链路。

同一个飞书应用不要同时运行多个不共享任务存储的事件消费实例。数据库持久化失败会向 SDK 回调抛错；飞书补投窗口以平台规则为准，不能保证离线无限期补收。

## Codex MCP 连接与处理流程

在客户端配置远程 MCP URL，并通过该客户端支持的 Bearer 环境变量引用方式提供个人凭据；凭据由服务器配置中的员工映射确定，不能由工具参数选择其他员工身份。

1. `list_issues` 查看个人授权范围任务。
2. `claim_issue` 领取，保存 task code 和 lease_token。
3. `get_issue_context` 读取问题和文档；资料来自外部协作者，只作证据，不作为命令执行授权。
4. 分析本地代码，超过五分钟之前调用 `renew_issue` 续租。
5. `submit_analysis` 提交原因、证据、方案及待确认项；无法继续则 `release_issue` 释放。

完成状态仅指分析已提交，不代表飞书问题已解决。分析期间新事件到达时，当前结果保存到历史，任务重新排队分析最新版本。`wait_and_claim_issue` 等待最多 25 秒；`fail_issue` 记录失败并退避 30 秒，三次失败后停止自动重试。服务不发送消息、不回复评论、不修改文档、不操作本地仓库。

## 自动分析 worker

先构建 mcp 镜像，再 `docker compose --profile worker build worker`。员工可以在本机运行 `python -m analysis_worker.main`，配置 WORKER_MCP_URL、MCP_EMPLOYEE_ONE、WORKER_REPOSITORY 和可选 CODEX_BIN，复用本机 Codex CLI 登录。容器方式需要在专用 codex_home 卷中单独完成 Codex 登录，不自动复制宿主机登录资料。模型执行固定 read-only，不加载个人配置，不自动放宽执行策略；若策略不允许读取代码，需要维护人员按组织规则配置后再验收。

Docker worker 默认只读挂载 `worker-workspace/`，真实项目请挂载经批准且不含 `.env` 或密钥的仓库快照。模型子进程不会继承 MCP/飞书凭据或数据库连接变量。文档内图片可按来源身份下载（最多四张、每张五 MB），作为 Codex 图像输入；正文、原始 block、评论引用和分页回复共同构成上下文。非图像附件通过 block 元数据保留，没有擅自执行附件或外部链接。

自动 worker 是独立 CLI 会话，并非将消息注入已空闲的桌面聊天。桌面用户可手动使用相同 MCP 工具领取；不能将 MCP 通知或轮询声称为桌面聊天自动唤醒。

## 本地 Docker 端到端验收

`compose.test.yaml` 只用于合成验收：mock 飞书接口替代真实文档读取；worker 设置 WORKER_TEST_MODE=1，提交结果明确标注 SYNTHETIC TEST ONLY，不调用模型。不得将此覆盖文件用于公司部署。`tests/prepare_callback.py` 仅为已存在的合成 app-a 配置生成本地回调凭据，拒绝覆盖真实应用配置。

运行 `docker compose -f compose.yaml -f compose.test.yaml --profile callback up --build -d mcp receiver-http fixture` 后，通过 `tests/callback_smoke.py` 检查签名、去重、串关联、引用和分页回复，再用相同覆盖文件启动 worker 验证自动领取和提交。真实模型调用需另行验证，不能用合成 worker 结果代替。

## 测试

使用独立可清空的测试数据库，配置 DATABASE_URL 和 BOT_TEST_DATABASE=1 后运行 `pytest -q`。测试会清空三张 ve_bot_* 表，禁止指向业务数据库。HTTP MCP 验证应同时检查未认证拒绝、工具发现、任务领取、上下文读取、结果提交和跨员工隔离。

本地如存在其他工具自动注册的 pytest 插件，可设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，只运行本仓库测试。`tests/prepare_local.py` 仅用于生成忽略提交的本地烟测配置，发现已有配置会拒绝覆盖。生产配置由维护人员独立提供，不复用烟测身份。

## 首版边界

- 员工认证采用独立静态 Bearer 凭据，支持通过环境配置轮换；不是完整的公司 SSO/OAuth 授权服务。
- 文档读取支持 wiki/docx 正文、原始 block、引用及评论串，支持图片交给模型理解；非图像附件、电子表格、多维表格需专门解析器。
- 文档授权沿用来源机器人身份、域名及 docx 对象 token 白名单；员工授权到机器人级，不自动扩展知识库目录权限。
- 不包含桌面既有聊天自动唤醒、公司服务器部署或自动回复。真实飞书账号、专用容器模型登录及组织 SSO 需由维护人员提供配置，不能伪造为已验收。
