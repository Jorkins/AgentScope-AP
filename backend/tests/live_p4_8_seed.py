"""为真实 P4-8 验收播种用户级 Skill 记录，不删除或覆盖既有数据。"""

import asyncio
import sys

from agentscope.app.storage import AsyncSQLAlchemyStorage, SkillRecord

from app.config import Settings


async def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: live_p4_8_seed.py USER SKILL DISPLAY USER SKILL DISPLAY",
        )
    storage = AsyncSQLAlchemyStorage(
        url=Settings().DATABASE_URL,
        create_tables=False,
        auto_migrate=False,
    )
    async with storage:
        for offset in (1, 4):
            user_id, name, display_name = sys.argv[offset : offset + 3]
            if await storage.get_skill_by_name(user_id, name) is not None:
                raise RuntimeError(f"验收 Skill 已存在: {user_id}/{name}")
            await storage.upsert_skill(
                user_id,
                SkillRecord(
                    user_id=user_id,
                    name=name,
                    display_name=display_name,
                    description="P4-8 live acceptance skill",
                ),
            )


if __name__ == "__main__":
    asyncio.run(main())
