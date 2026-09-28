import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union
import discord

logger = logging.getLogger("yuvi.queue")

TaskType = Literal["role_grant", "direct_message", "thread_message"]


@dataclass
class DiscordTask:
    task_type: TaskType
    payload: Dict[str, Any]
    retries: int = 0
    max_retries: int = 3
    future: Optional[asyncio.Future] = None
    dedup_key: Optional[str] = None


class DiscordQueueManager:
    """
    Manages asynchronous, rate-aware Discord operations.
    Uses separate queues for high-priority guild actions and throttled user DMs
    to avoid Head-of-Line (HoL) blocking.
    """
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.action_queue: asyncio.Queue[DiscordTask] = asyncio.Queue()
        self.dm_queue: asyncio.Queue[DiscordTask] = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._in_flight: set[str] = set()

    def start(self):
        """Start worker loops inside FastAPI lifespan or application startup."""
        # Filter out dead workers if any
        self._workers = [w for w in self._workers if not w.done()]
        if not self._workers:
            loop = asyncio.get_running_loop()
            self._workers = [
                loop.create_task(self._action_worker(), name="discord-action-worker"),
                loop.create_task(self._dm_worker(), name="discord-dm-worker"),
            ]
            logger.info("[DiscordQueue] Background workers started.")

    async def stop(self, timeout: float = 5.0):
        """Gracefully drain queues before canceling workers."""
        logger.info("[DiscordQueue] Waiting for pending tasks to finish...")
        try:
            await self.drain(timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[DiscordQueue] Timed out waiting for tasks to drain.")
        finally:
            workers = self._workers
            for w in workers:
                if not w.done():
                    w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            self._workers.clear()
            # asyncio.Queue binds to the event loop that waited on it. A new
            # lifespan must use fresh queues after the previous loop stops.
            self.action_queue = asyncio.Queue()
            self.dm_queue = asyncio.Queue()
            self._in_flight.clear()
            logger.info("[DiscordQueue] Background workers stopped.")

    async def drain(self, timeout: float = 5.0):
        """Wait until all current items in both queues have been processed."""
        # Ensure workers are alive to process items
        self._ensure_workers_started()
        await asyncio.wait_for(
            asyncio.gather(self.action_queue.join(), self.dm_queue.join()),
            timeout=timeout
        )

    def _ensure_workers_started(self):
        """Auto-start workers if an event loop is running and workers are not active."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running() and not any(not w.done() for w in self._workers):
                self.start()
        except RuntimeError:
            pass

    async def enqueue(self, task: DiscordTask) -> bool:
        """
        Enqueues task into the appropriate queue.
        Returns False if skipped due to deduplication, True otherwise.
        """
        if task.dedup_key:
            if task.dedup_key in self._in_flight:
                logger.info(f"[DiscordQueue] Skipping duplicate task: {task.dedup_key}")
                if task.future and not task.future.done():
                    task.future.set_result(None)
                return False
            self._in_flight.add(task.dedup_key)

        self._ensure_workers_started()

        if task.task_type == "direct_message":
            await self.dm_queue.put(task)
        else:
            await self.action_queue.put(task)
        return True

    async def _action_worker(self):
        """Worker for guild member updates and channel/thread messages (pacing ~0.1s)."""
        await self._run_worker(self.action_queue, interval=0.1)

    async def _dm_worker(self):
        """Worker dedicated to User DMs (Discord strictly throttles DMs to 5/sec; pacing ~0.25s)."""
        await self._run_worker(self.dm_queue, interval=0.25)

    async def _run_worker(self, queue: asyncio.Queue[DiscordTask], interval: float):
        while True:
            try:
                task = await queue.get()
            except asyncio.CancelledError:
                break

            try:
                result = await self._execute(task)
                if task.future and not task.future.done():
                    task.future.set_result(result)
            except discord.RateLimited as e:
                retry_after = getattr(e, "retry_after", 1.0)
                logger.warning(f"[DiscordQueue] Rate limited on {task.task_type}. Retrying after {retry_after}s")
                await asyncio.sleep(retry_after)
                await self._retry_or_fail(queue, task, e)
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = getattr(e, "retry_after", 1.0)
                    logger.warning(f"[DiscordQueue] HTTP 429 on {task.task_type}. Retrying after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    await self._retry_or_fail(queue, task, e)
                elif e.status == 403 and task.task_type == "direct_message":
                    # Cannot send messages to this user (DMs disabled / bot blocked)
                    logger.info(f"[DiscordQueue] DM skipped (user has DMs closed/blocked): {task.payload.get('user_id') or task.payload.get('member')}")
                    if task.future and not task.future.done():
                        task.future.set_result(None)
                else:
                    logger.error(f"[DiscordQueue] HTTPException on {task.task_type}: {e}")
                    if task.future and not task.future.done():
                        task.future.set_exception(e)
            except Exception as e:
                logger.exception(f"[DiscordQueue] Unexpected error processing {task.task_type}: {e}")
                if task.future and not task.future.done():
                    task.future.set_exception(e)
            finally:
                if task.dedup_key:
                    self._in_flight.discard(task.dedup_key)
                queue.task_done()
                await asyncio.sleep(interval)

    async def _retry_or_fail(self, queue: asyncio.Queue[DiscordTask], task: DiscordTask, exc: Exception):
        if task.retries < task.max_retries:
            task.retries += 1
            logger.info(f"[DiscordQueue] Retrying {task.task_type} (attempt {task.retries}/{task.max_retries})")
            await queue.put(task)
        else:
            logger.error(f"[DiscordQueue] Max retries reached for {task.task_type}. Dropping task.")
            if task.future and not task.future.done():
                task.future.set_exception(exc)

    async def _execute(self, task: DiscordTask) -> Any:
        p = task.payload
        if task.task_type == "role_grant":
            guild = self.bot.get_guild(p["guild_id"])
            if not guild:
                raise ValueError(f"Guild {p['guild_id']} not found or bot not ready")

            member = p.get("member")
            if not member:
                member = guild.get_member(p["user_id"]) or await guild.fetch_member(p["user_id"])

            if not member:
                raise ValueError(f"Member {p.get('user_id')} not found in guild")

            roles_to_assign = p.get("roles")
            if not roles_to_assign and "role_id" in p:
                role = guild.get_role(p["role_id"])
                if role:
                    roles_to_assign = [role]

            if roles_to_assign:
                missing_roles = [r for r in roles_to_assign if r not in member.roles]
                if missing_roles:
                    await member.add_roles(*missing_roles, reason=p.get("reason", "Verification"))
            return True

        elif task.task_type == "direct_message":
            target = p.get("member") or p.get("user")
            if not target and "user_id" in p:
                uid = int(p["user_id"])
                target = self.bot.get_user(uid) or await self.bot.fetch_user(uid)

            if target:
                embed = p.get("embed")
                content = p.get("content")
                await target.send(content=content, embed=embed)
            return True

        elif task.task_type == "thread_message":
            channel = p.get("channel") or p.get("thread")
            if not channel and "thread_id" in p:
                tid = int(p["thread_id"])
                channel = self.bot.get_channel(tid) or await self.bot.fetch_channel(tid)

            if channel:
                embed = p.get("embed")
                content = p.get("content")
                await channel.send(content=content, embed=embed)
            return True

        else:
            raise ValueError(f"Unknown task type: {task.task_type}")
