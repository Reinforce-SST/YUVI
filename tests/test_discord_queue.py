import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
import discord

from utils.discord_queue import DiscordQueueManager, DiscordTask


class DiscordQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = MagicMock()
        self.queue = DiscordQueueManager(self.bot)
        self.queue.start()

    async def asyncTearDown(self):
        await self.queue.stop(timeout=1.0)

    async def test_enqueue_and_process_dm(self):
        member = MagicMock()
        member.send = AsyncMock()
        embed = MagicMock()

        task = DiscordTask(
            task_type="direct_message",
            payload={"member": member, "embed": embed}
        )
        enqueued = await self.queue.enqueue(task)
        self.assertTrue(enqueued)

        await self.queue.drain(timeout=1.0)
        member.send.assert_awaited_once_with(content=None, embed=embed)

    async def test_deduplication_skips_duplicate_in_flight(self):
        member = MagicMock()
        slow_event = asyncio.Event()

        async def slow_send(**kwargs):
            await slow_event.wait()

        member.send = AsyncMock(side_effect=slow_send)

        task1 = DiscordTask(
            task_type="direct_message",
            payload={"member": member, "content": "Hello 1"},
            dedup_key="user_123"
        )
        task2 = DiscordTask(
            task_type="direct_message",
            payload={"member": member, "content": "Hello 2"},
            dedup_key="user_123"
        )

        res1 = await self.queue.enqueue(task1)
        res2 = await self.queue.enqueue(task2)

        self.assertTrue(res1)
        self.assertFalse(res2)

        # Release slow send
        slow_event.set()
        await self.queue.drain(timeout=1.0)
        member.send.assert_awaited_once()

    async def test_handles_forbidden_dm_gracefully(self):
        member = MagicMock()
        response = MagicMock()
        response.status = 403
        response.reason = "Forbidden"
        # Simulate user closed DMs
        member.send = AsyncMock(side_effect=discord.HTTPException(response, "Cannot send messages to this user"))

        task = DiscordTask(
            task_type="direct_message",
            payload={"member": member, "content": "Welcome!"}
        )
        await self.queue.enqueue(task)
        # Should not raise exception
        await self.queue.drain(timeout=1.0)
        member.send.assert_awaited_once()

    async def test_rate_limited_retry(self):
        channel = MagicMock()
        channel.send = AsyncMock()

        # Fail once with 429, then succeed
        call_count = 0
        async def send_with_ratelimit(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = MagicMock()
                resp.status = 429
                resp.reason = "Too Many Requests"
                exc = discord.HTTPException(resp, "Rate limited")
                exc.retry_after = 0.05
                raise exc
            return MagicMock()

        channel.send.side_effect = send_with_ratelimit

        task = DiscordTask(
            task_type="thread_message",
            payload={"channel": channel, "content": "Test"}
        )
        await self.queue.enqueue(task)
        await self.queue.drain(timeout=2.0)

        self.assertEqual(call_count, 2)

    async def test_role_grant_execution(self):
        guild = MagicMock()
        member = MagicMock()
        role = MagicMock()
        member.roles = []
        member.add_roles = AsyncMock()
        guild.get_member.return_value = member
        guild.get_role.return_value = role
        self.bot.get_guild.return_value = guild

        task = DiscordTask(
            task_type="role_grant",
            payload={
                "guild_id": 123,
                "user_id": 456,
                "role_id": 789,
                "reason": "Test grant"
            }
        )
        await self.queue.enqueue(task)
        await self.queue.drain(timeout=1.0)

        member.add_roles.assert_awaited_once_with(role, reason="Test grant")


class DiscordQueueLifecycleTests(unittest.TestCase):
    def test_restart_in_a_new_event_loop_processes_messages(self):
        queue = DiscordQueueManager(MagicMock())
        member = MagicMock()
        member.send = AsyncMock()
        channel = MagicMock()
        channel.send = AsyncMock()

        async def first_run():
            queue.start()
            await asyncio.sleep(0)
            await queue.stop(timeout=1.0)

        async def second_run():
            queue.start()
            try:
                await asyncio.sleep(0)
                self.assertTrue(all(not worker.done() for worker in queue._workers))
                await queue.enqueue(DiscordTask(
                    task_type="direct_message",
                    payload={"member": member, "content": "Hello after restart"},
                ))
                await queue.enqueue(DiscordTask(
                    task_type="thread_message",
                    payload={"channel": channel, "content": "Thread after restart"},
                ))
                await queue.drain(timeout=1.0)
            finally:
                await queue.stop(timeout=1.0)

        asyncio.run(first_run())
        asyncio.run(second_run())
        member.send.assert_awaited_once_with(content="Hello after restart", embed=None)
        channel.send.assert_awaited_once_with(content="Thread after restart", embed=None)
