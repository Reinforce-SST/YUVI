import os
import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import discord
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field


from utils.firestore_client import get_firestore_client
from utils.ticket_manager import TicketManager
from views.ticket_controls import TicketControlView
from yuvi_bot import YuviBot

bot = YuviBot()
bot_startup_error: Optional[str] = None


class VerifySuccessRequest(BaseModel):
    discord_id: str
    email: str
    name: Optional[str] = None
    secret: Optional[str] = None


class CreateTicketThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    creator_uid: str = Field(min_length=1)
    fields: dict = Field(default_factory=dict)


class RelayTicketMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    sender_uid: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=4000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


def require_internal_secret(provided: Optional[str]) -> None:
    expected = os.getenv("BOT_INTERNAL_SECRET")
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401, detail="Invalid or missing internal secret"
        )


async def ready_guild():
    if not bot.is_ready():
        try:
            await asyncio.wait_for(bot.wait_until_ready(), timeout=10.0)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Discord bot is still starting up"
            ) from exc
    guild_id = os.getenv("GUILD_ID")
    guild = bot.get_guild(int(guild_id)) if guild_id and guild_id.isdigit() else None
    if not guild and bot.guilds:
        guild = bot.guilds[0]
    if not guild:
        raise HTTPException(status_code=503, detail="Discord guild is unavailable")
    return guild


async def user_discord_id(uid: str) -> str:
    def load():
        snapshot = get_firestore_client().collection("users").document(uid).get()
        return (snapshot.to_dict() or {}).get("discord_id") if snapshot.exists else None

    discord_id = await asyncio.to_thread(load)
    if not discord_id:
        raise HTTPException(
            status_code=409, detail="The ticket creator has no linked Discord account"
        )
    return str(discord_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_startup_error
    bot_startup_error = None

    # Startup: Start Discord bot as an asyncio background task
    token = os.getenv("DISCORD_TOKEN")
    if not token or not token.strip():
        bot_startup_error = "DISCORD_TOKEN is missing or empty in environment variables"
        print(f"[Server] ERROR: {bot_startup_error}")
    else:

        async def run_bot():
            global bot_startup_error
            try:
                print("[Server] Starting Discord bot...")
                await bot.start(token.strip())
            except Exception as e:
                bot_startup_error = f"{type(e).__name__}: {e}"
                print(
                    f"[Server] FATAL: Discord bot failed to start: {bot_startup_error}"
                )
                import traceback

                traceback.print_exc()

        bot_task = asyncio.create_task(run_bot())
        print("[Server] Discord bot background task launched.")

    yield

    # Shutdown: Cleanly close Discord bot
    print("[Server] Shutting down Discord bot...")
    await bot.close()
    if "bot_task" in locals() and not bot_task.done():
        try:
            await asyncio.wait_for(bot_task, timeout=5.0)
        except asyncio.TimeoutError:
            print("[Server] Bot task shutdown timed out.")
        except Exception as e:
            print(f"[Server] Error during bot shutdown: {e}")


app = FastAPI(
    title="YUVI Bot & Verification Server",
    description="Internal Webhook and API server for Reinforce Club SST Discord Bot",
    version="0.1.0",
    lifespan=lifespan,
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "bot_ready": bot.is_ready(),
        "bot_user": str(bot.user) if bot.user else None,
        "bot_error": bot_startup_error,
    }


@app.post("/internal/verify-success")
async def verify_success(
    payload: VerifySuccessRequest, x_internal_secret: Optional[str] = Header(None)
):
    """
    Internal endpoint called by the Reinforce backend server when a user
    successfully authenticates with their @sst.scaler.com Google account.
    """
    require_internal_secret(payload.secret or x_internal_secret)

    # 2. Ensure Bot is Ready
    if not bot.is_ready():
        try:
            await asyncio.wait_for(bot.wait_until_ready(), timeout=10.0)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail="Discord bot is still starting up, please retry shortly.",
            )

    # 3. Locate Target Guild
    guild_id_env = os.getenv("GUILD_ID")
    guild = (
        bot.get_guild(int(guild_id_env))
        if (guild_id_env and guild_id_env.isdigit())
        else None
    )

    if not guild and bot.guilds:
        guild = bot.guilds[0]

    if not guild:
        raise HTTPException(
            status_code=500,
            detail="Bot is not in any Discord server / Guild not found.",
        )

    # 4. Locate Discord Member
    try:
        user_id_int = int(payload.discord_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid discord_id format (must be integer string)"
        )

    member = guild.get_member(user_id_int)
    if not member:
        try:
            member = await guild.fetch_member(user_id_int)
        except discord.NotFound:
            raise HTTPException(
                status_code=404,
                detail=f"Member {payload.discord_id} not found in Discord server.",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch member {payload.discord_id}: {e}",
            )

    # 5. Locate & Assign Verified Member Role
    verified_role_id = os.getenv("VERIFIED_ROLE_ID")
    verified_role = None

    if verified_role_id and verified_role_id.isdigit():
        verified_role = guild.get_role(int(verified_role_id))

    if not verified_role:
        # Fallback to search role by name
        for r in guild.roles:
            if r.name.lower() in ("verified member", "verified", "member"):
                verified_role = r
                break

    role_assigned = False
    role_name = "None (Role not configured in .env)"

    if verified_role:
        try:
            await member.add_roles(
                verified_role, reason=f"Google account verified: {payload.email}"
            )
            role_assigned = True
            role_name = verified_role.name
            print(
                f"[Server] Assigned role '{role_name}' to {member.name} ({member.id})"
            )
        except discord.Forbidden:
            print(
                f"[Server] ERROR: Missing permissions to assign role '{verified_role.name}' to {member.id}"
            )
            raise HTTPException(
                status_code=500,
                detail="Bot lacks permission to assign the verified role (ensure bot role is above verified role in server hierarchy).",
            )
        except Exception as e:
            print(f"[Server] ERROR assigning role: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to assign role: {e}")

    # 6. Send Direct Message Confirmation
    try:
        embed = discord.Embed(
            title="🎉 Welcome to Reinforce Club SST!",
            description=(
                f"Hello {member.mention}!\n\n"
                f"Your Google account (**`{payload.email}`**) has been successfully verified.\n"
                f"You have been granted the **{role_name}** role on Discord.\n\n"
                f"You now have access to member discussion channels, showcase forums, and Student Project Groups (SPGs)!"
            ),
            color=0x57F287,
        )
        embed.set_footer(
            text="Reinforce Club SST • Verification System",
            icon_url=guild.icon.url if guild.icon else None,
        )
        await member.send(embed=embed)
    except Exception as e:
        print(
            f"[Server] Note: Could not send DM to user {member.id} (DMs might be closed): {e}"
        )

    return {
        "success": True,
        "discord_id": payload.discord_id,
        "email": payload.email,
        "role_granted": role_name,
        "role_assigned": role_assigned,
    }


@app.post("/tickets/create-thread")
async def create_ticket_thread(
    payload: CreateTicketThreadRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """Create one private Discord thread for a dashboard ticket."""
    require_internal_secret(x_internal_secret)

    reservation = await TicketManager.reserve_thread_creation(payload.ticket_id)
    if reservation["status"] == "missing":
        raise HTTPException(status_code=404, detail="Ticket was not found")
    if reservation["status"] == "busy":
        raise HTTPException(
            status_code=409, detail="Discord thread creation is already in progress"
        )
    if reservation["status"] == "existing":
        meta = reservation["discord_meta"]
        meta["thread_url"] = (
            f"https://discord.com/channels/{meta['guild_id']}/{meta['thread_id']}"
        )
        return {"success": True, "discord_meta": meta, "existing": True}

    guild = await ready_guild()
    discord_id = await user_discord_id(payload.creator_uid)
    member = guild.get_member(int(discord_id))
    if member is None:
        try:
            member = await guild.fetch_member(int(discord_id))
        except discord.NotFound as exc:
            raise HTTPException(
                status_code=404, detail="Linked Discord member was not found"
            ) from exc

    channel_id = os.getenv("TICKETS_CHANNEL_ID")
    channel = (
        guild.get_channel(int(channel_id))
        if channel_id and channel_id.isdigit()
        else None
    )
    if channel is None or not hasattr(channel, "create_thread"):
        raise HTTPException(
            status_code=503, detail="TICKETS_CHANNEL_ID is not a usable text channel"
        )

    safe_category = "".join(
        char for char in payload.category.lower() if char.isalnum() or char == "-"
    )[:20]
    thread_name = f"{safe_category or 'ticket'}-{payload.ticket_id[-8:]}"[:100]
    thread = None
    if reservation["status"] == "resume":
        thread_id = (reservation.get("discord_meta") or {}).get("thread_id")
        if thread_id:
            thread = bot.get_channel(int(thread_id))
            if thread is None:
                try:
                    thread = await bot.fetch_channel(int(thread_id))
                except discord.NotFound:
                    thread = None
    if thread is None:
        thread = next(
            (
                candidate
                for candidate in getattr(channel, "threads", [])
                if candidate.name == thread_name
            ),
            None,
        )
    if thread is None:
        thread = await channel.create_thread(
            name=thread_name,
            auto_archive_duration=10080,
            type=discord.ChannelType.private_thread,
            reason=f"Dashboard ticket {payload.ticket_id}",
        )

    partial_meta = {
        "guild_id": str(guild.id),
        "channel_id": str(channel.id),
        "thread_id": str(thread.id),
        "thread_url": f"https://discord.com/channels/{guild.id}/{thread.id}",
    }
    await TicketManager.update_ticket(
        payload.ticket_id,
        {
            "discord_meta": partial_meta,
            "thread_id": str(thread.id),
            "guild_id": str(guild.id),
            "discord_thread_state": "created",
        },
    )
    await thread.add_user(member)
    embed = discord.Embed(
        title=payload.title,
        description=f"Dashboard ticket `{payload.ticket_id}`\nCreated by {member.mention}",
        color=0xE5B731,
    )
    for key, value in list(payload.fields.items())[:25]:
        embed.add_field(name=str(key)[:256], value=str(value)[:1024], inline=False)
    control_message = await thread.send(embed=embed, view=TicketControlView())

    meta = {
        "guild_id": str(guild.id),
        "channel_id": str(channel.id),
        "thread_id": str(thread.id),
        "control_message_id": str(control_message.id),
        "thread_url": f"https://discord.com/channels/{guild.id}/{thread.id}",
    }
    await TicketManager.update_ticket(
        payload.ticket_id,
        {
            "discord_meta": meta,
            "thread_id": str(thread.id),
            "guild_id": str(guild.id),
            "discord_thread_state": "ready",
        },
    )
    return {"success": True, "discord_meta": meta, "existing": False}


@app.post("/tickets/relay-message")
async def relay_ticket_message(
    payload: RelayTicketMessageRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """Relay a dashboard-authored message into its linked Discord thread."""
    require_internal_secret(x_internal_secret)
    ticket = await TicketManager.get_ticket(payload.ticket_id)
    linked_thread_id = None
    if ticket:
        linked_thread_id = ticket.thread_id or (
            ticket.discord_meta.thread_id if ticket.discord_meta else None
        )
    if not ticket or str(linked_thread_id) != payload.thread_id:
        raise HTTPException(
            status_code=409, detail="Ticket is not linked to that Discord thread"
        )

    channel = bot.get_channel(int(payload.thread_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(payload.thread_id))
        except discord.NotFound as exc:
            raise HTTPException(
                status_code=404, detail="Discord ticket thread was not found"
            ) from exc
    attachment_lines = "\n".join(payload.attachments)
    content = f"**Dashboard message from `{payload.sender_uid}`**\n{payload.content}"
    if attachment_lines:
        content = f"{content}\n{attachment_lines}"
    messages = [
        await channel.send(content[index : index + 1900])
        for index in range(0, len(content), 1900)
    ]
    return {
        "success": True,
        "discord_message_id": str(messages[-1].id),
        "discord_message_ids": [str(message.id) for message in messages],
    }
