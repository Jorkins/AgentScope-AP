# -*- coding: utf-8 -*-
"""SOP 示例种子：一键创建演示 Agent + 软件研发标准流程 SOP。

通过平台 HTTP API 操作（不直连存储），与后端进程解耦。

用法（后端已启动、且账号下至少配置了一个聊天模型凭证）：

    .venv/Scripts/python scripts/seed_sop_demo.py
    .venv/Scripts/python scripts/seed_sop_demo.py --username sop_demo --password sop_demo123

完成后在左侧导航「SOP」中即可看到「软件研发标准流程」，
点击「运行」启动一次流程执行；最后一步为人工验收节点。
"""

import argparse
import sys

import httpx

EXPLORER_PROMPT = (
    "你是一名需求探索者。根据输入的需求，调研并输出一份简明的实现方案："
    "目标拆解、关键步骤、风险点。只做分析与方案，不编写代码。"
    "输出使用中文，控制在 300 字以内。"
)

CODER_PROMPT = (
    "你是一名编码工程师。根据上游给出的实现方案，编写最小可运行的代码实现"
    "（默认 Python），并给出简要说明。输出使用中文。"
)

SOP_NAME = "软件研发标准流程"


def login_or_register(client: httpx.Client, username: str, password: str) -> str:
    """登录；账号不存在时注册。返回 access_token。"""
    resp = client.post(
        "/api/platform/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code != 200:
        resp = client.post(
            "/api/platform/auth/register",
            json={
                "username": username,
                "password": password,
                "display_name": username,
            },
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


def pick_chat_model(client: httpx.Client) -> dict:
    """取账号下第一个可用聊天模型，组成 ChatModelConfig。"""
    credentials = client.get("/credential/").raise_for_status().json()[
        "credentials"
    ]
    for credential in credentials:
        provider = credential["data"].get("type")
        if not provider:
            continue
        try:
            models = client.get(
                "/model/", params={"provider": provider}
            ).raise_for_status().json()["models"]
        except httpx.HTTPError:
            continue
        if models:
            model = models[0]
            return {
                "type": provider,
                "credential_id": credential["id"],
                "model": model["name"],
                "model_class": model["model_class"],
                "parameters": {},
            }
    raise SystemExit(
        "未找到可用聊天模型：请先在「凭证」页配置模型 API Key 后再运行本脚本。"
    )


def ensure_agent(client: httpx.Client, name: str, prompt: str) -> str:
    """按名字复用或创建 Agent，返回 agent_id。"""
    agents = client.get("/agent/").raise_for_status().json()["agents"]
    for agent in agents:
        if agent["data"]["name"] == name:
            return agent["id"]
    resp = client.post(
        "/agent/", json={"name": name, "system_prompt": prompt}
    ).raise_for_status()
    return resp.json()["agent_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--username", default="sop_demo")
    parser.add_argument("--password", default="sop_demo123")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        token = login_or_register(client, args.username, args.password)
        client.headers["Authorization"] = f"Bearer {token}"
        print(f"[1/4] 登录成功：{args.username}")

        model_config = pick_chat_model(client)
        print(f"[2/4] 使用模型：{model_config['model']}")

        explorer_id = ensure_agent(client, "需求探索者", EXPLORER_PROMPT)
        coder_id = ensure_agent(client, "编码工程师", CODER_PROMPT)
        print(f"[3/4] Agent 就绪：需求探索者={explorer_id} 编码工程师={coder_id}")

        existing = client.get("/sop/").raise_for_status().json()["sops"]
        for sop in existing:
            if sop["data"]["name"] == SOP_NAME:
                print(f"SOP 已存在：{sop['id']}（不重复创建）")
                return

        sop_data = {
            "name": SOP_NAME,
            "description": (
                "需求探索者先输出实现方案，编码工程师据此完成代码实现，"
                "最后由人工验收；验收打回会自动携带修改意见重试，最多 3 次。"
            ),
            "steps": [
                {
                    "subject": "调研与方案",
                    "description": (
                        "分析输入的需求，输出实现方案：目标拆解、关键步骤、风险点。"
                    ),
                    "executor": {
                        "agent_id": explorer_id,
                        "session_key": "explore",
                    },
                    "verifier": None,
                },
                {
                    "subject": "编码实现",
                    "description": (
                        "根据上一步的实现方案编写最小可运行代码，并附简要说明。"
                    ),
                    "executor": {
                        "agent_id": coder_id,
                        "session_key": "coding",
                    },
                    "verifier": {
                        "type": "human",
                        "question": (
                            "实现是否满足需求？通过则流程完成；"
                            "打回请写明修改点，将自动重试。"
                        ),
                    },
                    "max_attempts": 3,
                },
            ],
            "session_settings": {
                "explore": {"chat_model_config": model_config},
                "coding": {"chat_model_config": model_config},
            },
        }
        sop_id = client.post(
            "/sop/", json={"data": sop_data}
        ).raise_for_status().json()["sop_id"]
        print(f"[4/4] SOP 创建成功：{sop_id}")
        print("完成。打开前端「SOP」页，选中「软件研发标准流程」即可启动运行。")


if __name__ == "__main__":
    sys.exit(main())
