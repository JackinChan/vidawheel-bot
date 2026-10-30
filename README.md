# VidaWheel Bot 协作任务服务

<!-- 本仓库实现事件接入与远程任务领取，不包含自动修改代码或自动回复飞书。 -->

## TLDR

| 字段 | 内容 |
| --- | --- |
| 这是什么 | 为多个飞书机器人接收协作问题，并让员工通过 Codex MCP 领取和提交分析。 |
| 谁该看 | 平台维护人员部署配置；开发人员连接 MCP、领取任务并结合本地仓库分析。 |
| 当前状态 | 草稿 |
| 当前结论 | 首版实现群聊文本 @事件和任务闭环；飞书真实联调及公司服务器部署尚待完成。 |
| 负责人 | 待指定 |
| 最近更新 | 2026-10-30 by Codex |

## 工程结构

- `event_receiver/`：飞书官方 SDK 长连接；每个应用一个进程，允许群和机器人精确匹配，成功落库后返回。
- `mcp_server/`：官方 MCP SDK，Streamable HTTP，员工独立 Bearer 凭据与服务端机器人授权映射。
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

第一版只处理群聊文本 @机器人。正文 @、文档评论 @、多维表格评论均未宣称支持；需要后续获取官方事件 schema 和真实事件样本后单独实现及验收。群文本中可以附 wiki/docx 链接，领取后按来源应用读取文档。

同一个飞书应用不要同时运行多个不共享任务存储的事件消费实例。数据库持久化失败会向 SDK 回调抛错；飞书补投窗口以平台规则为准，不能保证离线无限期补收。

## Codex MCP 连接与处理流程

在客户端配置远程 MCP URL，并通过该客户端支持的 Bearer 环境变量引用方式提供个人凭据；凭据由服务器配置中的员工映射确定，不能由工具参数选择其他员工身份。

1. `list_issues` 查看个人授权范围任务。
2. `claim_issue` 领取，保存 task code 和 lease_token。
3. `get_issue_context` 读取问题和文档；资料来自外部协作者，只作证据，不作为命令执行授权。
4. 分析本地代码，超过五分钟之前调用 `renew_issue` 续租。
5. `submit_analysis` 提交原因、证据、方案及待确认项；无法继续则 `release_issue` 释放。

完成状态仅指分析已提交，不代表飞书问题已解决。服务不发送消息、不回复评论、不修改文档、不操作本地仓库。接入 MCP 不会自动唤醒桌面 Codex；自动领取需要客户端调度能力，后续再验证。

## 测试

使用独立可清空的测试数据库，配置 DATABASE_URL 和 BOT_TEST_DATABASE=1 后运行 `pytest -q`。测试会清空三张 ve_bot_* 表，禁止指向业务数据库。HTTP MCP 验证应同时检查未认证拒绝、工具发现、任务领取、上下文读取、结果提交和跨员工隔离。

本地如存在其他工具自动注册的 pytest 插件，可设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，只运行本仓库测试。`tests/prepare_local.py` 仅用于生成忽略提交的本地烟测配置，发现已有配置会拒绝覆盖。生产配置由维护人员独立提供，不复用烟测身份。

## 首版边界

- 员工认证采用独立静态 Bearer 凭据，支持通过环境配置轮换；不是完整的公司 SSO/OAuth 授权服务。
- 文档读取支持 wiki 中的 docx 和直接 docx 原始文本；图片 OCR、附件、表格和评论引用段落未包含。
- 文档授权沿用来源机器人权限与域名白名单；员工授权到机器人级，尚未实现单文档目录级 ACL。
- 不包含自动模型调用、桌面聊天唤醒、公司服务器部署或自动回复。
