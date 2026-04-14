from __future__ import annotations

import asyncio


class MessageNotifier:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._versions: dict[tuple[str, str], int] = {}

    def snapshot(self, *, workspace_id: str, agent_name: str) -> int:
        return self._versions.get((workspace_id, agent_name), 0)

    async def publish(self, *, workspace_id: str, agent_name: str) -> int:
        key = (workspace_id, agent_name)
        async with self._condition:
            next_version = self._versions.get(key, 0) + 1
            self._versions[key] = next_version
            self._condition.notify_all()
            return next_version

    async def wait_for_update(
        self,
        *,
        workspace_id: str,
        agent_name: str,
        since_version: int,
        timeout_seconds: float,
    ) -> int | None:
        key = (workspace_id, agent_name)

        def has_update() -> bool:
            return self._versions.get(key, 0) > since_version

        async with self._condition:
            if has_update():
                return self._versions[key]
            try:
                await asyncio.wait_for(self._condition.wait_for(has_update), timeout_seconds)
            except TimeoutError:
                return None
            return self._versions.get(key)


_message_notifier = MessageNotifier()


def get_message_notifier() -> MessageNotifier:
    return _message_notifier
