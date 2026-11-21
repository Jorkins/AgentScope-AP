"""AgentScope-AP 后端入口。

以 AgentScope `create_app` 为运行时内核，装配：
storage(PostgreSQL) / message_bus(Redis) / vector_store(Qdrant) /
workspace(本地) / 知识库，并注入平台壳（认证 + 多租户 + 平台路由）。
"""

import sys

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.hub import ClawSkillHub, GitHubMCPHub
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.rag import (
    ApproxTokenChunker,
    ExcelParser,
    ImageParser,
    PDFParser,
    PPTParser,
    TextParser,
    WordParser,
)

from .config import settings
from .platform import build_platform
from .runtime import build_runtime

# ---- 共享运行时：API 与 Worker 使用同一套装配规则 ----
runtime = build_runtime(settings)

# ---- 服务级团队：SubAgent 角色蓝图 ----
EXPLORER_TEMPLATE = SubAgentTemplate(
    type="explorer",
    description=(
        "只读探索者：可读取文件与代码库，用于调研、理解结构、收集信息，"
        "但不能修改/创建/删除。适合代码勘察、资料收集类任务。"
    ),
    system_prompt_template="""You are {member_name}, a read-only explorer in \
team '{team_name}' led by {leader_name}.

Team purpose: {team_description}
Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the leader: inspect files, \
understand the codebase, gather information.
- You are read-only: never modify, create, or delete anything.

## Reporting
- Always report the result back to {leader_name} via the TeamSay tool, on \
success or failure.
- Share only conclusions and findings; keep private reasoning private.

Note: TeamSay is your ONLY channel to {leader_name} and the other members. \
Anything you want them to see MUST be sent through TeamSay.""",
    permission_context=PermissionContext(mode=PermissionMode.EXPLORE),
    # 固定只读，不被 leader 的运行模式覆盖
    override_leader_mode=True,
)

CODER_TEMPLATE = SubAgentTemplate(
    type="coder",
    description=(
        "编码执行者：可读写/修改文件、运行命令，用于实现功能、修复缺陷、"
        "重构等执行任务。继承 leader 已授权的权限。"
    ),
    system_prompt_template="""You are {member_name}, a coder in team \
'{team_name}' led by {leader_name}.

Team purpose: {team_description}
Your role: {member_description}

## Responsibilities
- Implement the coding tasks assigned by the leader: write/modify code, run \
commands, fix bugs, refactor.
- Follow the leader's plan; ask {leader_name} via TeamSay when blocked.

## Reporting
- Always report the result back to {leader_name} via the TeamSay tool, on \
success or failure.

Note: TeamSay is your ONLY channel to {leader_name} and the other members. \
Anything you want them to see MUST be sent through TeamSay.""",
    # 继承 leader 的权限模式与工作目录（默认可写）
)

# ---- 平台壳 ----
platform = build_platform(
    settings,
    storage=runtime.storage,
    workspace_manager=runtime.workspace_manager,
)

# ---- 组装应用 ----
app = create_app(
    storage=runtime.storage,
    message_bus=runtime.message_bus,
    workspace_manager=runtime.workspace_manager,
    knowledge_base_manager=runtime.knowledge_base_manager,
    blob_store=runtime.blob_store,
    enable_index_worker=runtime.role_flags.enable_index_worker,
    enable_channel_worker=runtime.role_flags.enable_channel_worker,
    enable_scheduler=runtime.role_flags.enable_scheduler,
    knowledge_parsers=[
        TextParser(),
        PDFParser(),
        WordParser(),
        ExcelParser(),
        PPTParser(),
        ImageParser(),
    ],
    knowledge_chunkers=[ApproxTokenChunker],
    # 市场：MCP / Skill Hub（前端 /mcp、/skill 浏览安装）
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[ClawSkillHub(api_token=settings.CLAWHUB_API_TOKEN or None)],
    # 服务级团队：SubAgent 角色蓝图
    custom_subagent_templates=[EXPLORER_TEMPLATE, CODER_TEMPLATE],
    resource_access_policy=platform.resource_access_policy,
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=settings.cors_method_list,
            allow_headers=settings.cors_header_list,
            allow_credentials=False,
        ),
        *platform.asgi_middlewares,
    ],
    download_secret=settings.JWT_SECRET,
    title="AgentScope-AP",
)

platform.register_routes(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=sys.platform != "win32",
    )
