import os
import asyncio
import secrets
from weakref import WeakValueDictionary
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import discord
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel


from utils.firestore_client import get_firestore_client
from yuvi_bot import YuviBot
from utils.auth_links import require_verified_link

# Initialize Firestore
get_firestore_client()

bot = YuviBot()
bot_startup_error: Optional[str] = None
# Keep retries for the same member ordered without retaining idle locks forever.
verification_locks = WeakValueDictionary()


class VerifySuccessRequest(BaseModel):
    discord_id: str
    email: str
    name: Optional[str] = None
    secret: Optional[str] = None


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
                print(f"[Server] FATAL: Discord bot failed to start: {bot_startup_error}")
                import traceback
                traceback.print_exc()

        bot_task = asyncio.create_task(run_bot())
        print("[Server] Discord bot background task launched.")
    
    yield

    # Shutdown: Cleanly close Discord bot
    print("[Server] Shutting down Discord bot...")
    await bot.close()
    if 'bot_task' in locals() and not bot_task.done():
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
    lifespan=lifespan
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
        "bot_error": bot_startup_error
    }


@app.post("/internal/verify-success")
async def verify_success(
    payload: VerifySuccessRequest,
    x_internal_secret: Optional[str] = Header(None)
):
    """
    Internal endpoint called by the Reinforce backend server when a user
    successfully authenticates with their @sst.scaler.com Google account.
    """
    expected_secret = os.getenv("BOT_INTERNAL_SECRET", "").strip()
    if not expected_secret:
        raise HTTPException(status_code=503, detail="Internal verification is not configured.")
    if not secrets.compare_digest(x_internal_secret or "", expected_secret):
        raise HTTPException(status_code=401, detail="Invalid internal secret.")
    if not payload.discord_id.isdigit() or not 5 <= len(payload.discord_id) <= 25:
        raise HTTPException(status_code=400, detail="Invalid Discord ID.")
    await asyncio.to_thread(require_verified_link, get_firestore_client(), payload.discord_id, payload.email)

    # 2. Ensure Bot is Ready
    if not bot.is_ready():
        try:
            await asyncio.wait_for(bot.wait_until_ready(), timeout=10.0)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=503, detail="Discord bot is still starting up, please retry shortly.")

    # 3. Locate Target Guild
    guild_id_env = os.getenv("GUILD_ID")
    guild = bot.get_guild(int(guild_id_env)) if (guild_id_env and guild_id_env.isdigit()) else None
    
    if not guild and bot.guilds:
        guild = bot.guilds[0]

    if not guild:
        raise HTTPException(status_code=500, detail="Bot is not in any Discord server / Guild not found.")

    lock = verification_locks.setdefault((guild.id, payload.discord_id), asyncio.Lock())
    async with lock:
        # Proof may have been unlinked while this callback waited behind a retry.
        await asyncio.to_thread(require_verified_link, get_firestore_client(), payload.discord_id, payload.email)
        return await _assign_verified_role(guild, payload)


async def _assign_verified_role(guild, payload):
    # 4. Locate Discord Member
    try:
        user_id_int = int(payload.discord_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid discord_id format (must be integer string)")

    # The gateway cache can lag a successful REST role grant. Read fresh roles
    # inside the lock so overlapping callbacks cannot send duplicate welcomes.
    try:
        member = await guild.fetch_member(user_id_int)
    except discord.NotFound:
        raise HTTPException(status_code=404, detail=f"Member {payload.discord_id} not found in Discord server.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch member {payload.discord_id}: {e}")

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

    already_assigned = verified_role is not None and verified_role in member.roles
    if verified_role:
        try:
            if not already_assigned:
                await member.add_roles(verified_role, reason=f"Google account verified: {payload.email}")
            role_assigned = True
            role_name = verified_role.name
            print(f"[Server] Assigned role '{role_name}' to {member.name} ({member.id})")
        except discord.Forbidden:
            print(f"[Server] ERROR: Missing permissions to assign role '{verified_role.name}' to {member.id}")
            raise HTTPException(status_code=500, detail="Bot lacks permission to assign the verified role (ensure bot role is above verified role in server hierarchy).")
        except Exception as e:
            print(f"[Server] ERROR assigning role: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to assign role: {e}")

    # Do not claim a role was granted when it is not configured, and avoid
    # repeated DMs when a request is retried after a network failure.
    if not role_assigned or already_assigned:
        return {"success": True, "role_assigned": role_assigned, "role_granted": role_name if role_assigned else None}

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
            color=0x57F287
        )
        embed.set_footer(text="Reinforce Club SST • Verification System", icon_url=guild.icon.url if guild.icon else None)
        await member.send(embed=embed)
    except Exception as e:
        print(f"[Server] Note: Could not send DM to user {member.id} (DMs might be closed): {e}")

    return {
        "success": True,
        "discord_id": payload.discord_id,
        "email": payload.email,
        "role_granted": role_name,
        "role_assigned": role_assigned
    }


class RelayMessageRequest(BaseModel):
    ticket_id: str
    thread_id: str
    sender_uid: Optional[str] = None
    sender_name: Optional[str] = None
    content: str
    attachments: Optional[list[str]] = None
    secret: Optional[str] = None


@app.post("/internal/tickets/relay-message")
@app.post("/internal/tickets/message-out")
async def relay_ticket_message(
    payload: RelayMessageRequest,
    x_internal_secret: Optional[str] = Header(None)
):
    """Internal webhook called when a user or admin posts a message on the Web Dashboard."""
    expected_secret = os.getenv("BOT_INTERNAL_SECRET")
    if expected_secret:
        provided = payload.secret or x_internal_secret
        if provided != expected_secret:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal secret")

    if not bot.is_ready():
        raise HTTPException(status_code=503, detail="Discord bot not ready")

    try:
        thread_id_int = int(payload.thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    channel = bot.get_channel(thread_id_int)
    if not channel:
        try:
            channel = await bot.fetch_channel(thread_id_int)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Thread channel not found: {e}")

    if not isinstance(channel, (discord.Thread, discord.TextChannel)):
        raise HTTPException(status_code=400, detail="Target channel is not a text thread")

    sender = payload.sender_name or "Web Member"
    embed = discord.Embed(
        description=payload.content,
        color=0x5865F2
    )
    embed.set_author(name=f"{sender} (via Dashboard)", icon_url="https://cdn.discordapp.com/embed/avatars/0.png")

    if payload.attachments:
        for idx, att_url in enumerate(payload.attachments, 1):
            embed.add_field(name=f"Attachment {idx}", value=f"[Download / View File]({att_url})", inline=False)

    await channel.send(embed=embed)
    return {"success": True, "ticket_id": payload.ticket_id}


class CreateThreadRequest(BaseModel):
    ticket_id: str
    category: str
    title: str
    creator_uid: Optional[str] = None
    fields: Optional[dict] = None
    secret: Optional[str] = None


@app.post("/internal/tickets/create-thread")
@app.post("/internal/tickets/thread-create")
async def create_ticket_thread(
    payload: CreateThreadRequest,
    x_internal_secret: Optional[str] = Header(None)
):
    """Internal webhook called when a ticket is created from the Web Dashboard."""
    expected_secret = os.getenv("BOT_INTERNAL_SECRET")
    if expected_secret:
        provided = payload.secret or x_internal_secret
        if provided != expected_secret:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal secret")

    if not bot.is_ready():
        raise HTTPException(status_code=503, detail="Discord bot not ready")

    guild_id_env = os.getenv("GUILD_ID")
    guild = bot.get_guild(int(guild_id_env)) if (guild_id_env and guild_id_env.isdigit()) else None
    if not guild and bot.guilds:
        guild = bot.guilds[0]

    if not guild:
        raise HTTPException(status_code=500, detail="Guild not found")

    tickets_ch_id = os.getenv("TICKETS_CHANNEL_ID")
    target_channel = guild.get_channel(int(tickets_ch_id)) if (tickets_ch_id and tickets_ch_id.isdigit()) else None
    if not target_channel:
        target_channel = guild.text_channels[0] if guild.text_channels else None

    if not target_channel:
        raise HTTPException(status_code=500, detail="No valid text channel found for thread creation")

    thread_name = f"ticket-{payload.category[:6]}-{payload.ticket_id[:6]}"
    try:
        thread = await target_channel.create_thread(
            name=thread_name,
            auto_archive_duration=10080,
            type=discord.ChannelType.private_thread,
            reason=f"Web Ticket: {payload.ticket_id}"
        )
    except Exception:
        thread = await target_channel.create_thread(
            name=thread_name,
            auto_archive_duration=10080,
            reason=f"Web Ticket: {payload.ticket_id}"
        )

    # Post initial header embed
    from views.ticket_controls import TicketControlView
    embed = discord.Embed(
        title=f"🎫 {payload.title}",
        description=f"Ticket opened via Web Dashboard.\n**Category:** `{payload.category}`\n**Ticket ID:** `{payload.ticket_id}`",
        color=0x5865F2
    )
    if payload.fields:
        for k, v in payload.fields.items():
            embed.add_field(name=f"📌 {k}", value=str(v)[:1024], inline=False)

    await thread.send(embed=embed, view=TicketControlView())

    return {
        "success": True,
        "ticket_id": payload.ticket_id,
        "discord_meta": {
            "guild_id": str(guild.id),
            "channel_id": str(target_channel.id),
            "thread_id": str(thread.id),
            "thread_url": f"https://discord.com/channels/{guild.id}/{thread.id}"
        }
    }
