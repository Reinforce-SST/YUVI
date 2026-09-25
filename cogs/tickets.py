import os
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal

from models.ticket import (
    TicketStatus,
    TicketUser,
    TicketMessage
)
from utils.ticket_manager import TicketManager
from utils.transcript_generator import TranscriptGenerator
from views.ticket_panel import TicketPanelView
from views.ticket_controls import TicketControlView, CloseReasonModal

class TicketsCog(commands.Cog, name="Tickets"):
    """Comprehensive Ticket System for Reinforce Club integrated with Firestore."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent views so buttons & dropdowns work across bot restarts
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketControlView())

    ticket_group = app_commands.Group(name="ticket", description="Ticket management commands")

    @app_commands.command(name="setup-tickets", description="Post the official Reinforce Club Ticket Panel")
    @app_commands.describe(channel="Channel to post the ticket panel into (defaults to current channel)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tickets(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None
    ):
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("❌ Target must be a text channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎫 Reinforce Club Support & Ticket System",
            description=(
                "Welcome to the **Reinforce Club** automated ticket portal.\n\n"
                "Select a category from the dropdown menu below to open a private ticket with our track leads and admin team:\n\n"
                "• **🚀 SPG Registration / Modification**: Register your team, select track (Product, Kaggle, Research), set milestones.\n"
                "• **⚡ Resource Request**: Request GPU/Compute, hardware, API credits, or mentorship (Proof of progress required).\n"
                "• **💬 Support & Inquiries**: Get help with club activities, events, tracks, or guidance.\n"
                "• **💡 Idea Jar & Suggestions**: Submit project ideas for the community or feedback for the club.\n"
                "• **🛡️ Report Issue / Misconduct**: Confidential reports handled directly by core admins.\n"
                "• **📦 General / Misc**: Any other questions or requests."
            ),
            color=0x5865F2 # Reinforce Blurple
        )
        embed.set_footer(text="Reinforce Club SST • All tickets are synced with the Firestore Web Dashboard")
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await target_channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message(f"✅ Ticket panel deployed to {target_channel.mention}!", ephemeral=True)

    @ticket_group.command(name="close", description="Close the current ticket thread")
    @app_commands.describe(reason="Optional reason or resolution summary for closing the ticket")
    async def ticket_close(self, interaction: discord.Interaction, reason: Optional[str] = None):
        if not isinstance(interaction.channel, (discord.Thread, discord.TextChannel)):
            await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)
            return

        ticket = await TicketManager.get_ticket_by_thread_id(str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("❌ This thread is not recognized as an active ticket.", ephemeral=True)
            return

        if ticket.status == TicketStatus.CLOSED:
            await interaction.response.send_message("❌ This ticket is already marked as closed.", ephemeral=True)
            return

        if not reason:
            await interaction.response.send_modal(CloseReasonModal(ticket.id))
            return

        await interaction.response.defer()

        closing_user = TicketUser(
            discord_id=str(interaction.user.id),
            username=interaction.user.name,
            avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
        )

        await TicketManager.close_ticket(ticket.id, closing_user, reason)

        # Generate and send transcript
        messages = await TicketManager.get_ticket_messages(ticket.id)
        transcript_file = TranscriptGenerator.generate_text_transcript(ticket, messages)
        discord_file = discord.File(transcript_file, filename=f"transcript-{ticket.id}.txt")

        close_embed = discord.Embed(
            title="🔒 Ticket Closed",
            description=f"This ticket has been closed by {interaction.user.mention}.\n**Reason:** {reason}",
            color=0xED4245
        )
        close_embed.set_footer(text=f"Ticket ID: {ticket.id} • Reinforce Club")

        await interaction.followup.send(embed=close_embed, file=discord_file)

        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.send("⏳ *This thread will be locked and archived shortly...*")
            await interaction.channel.edit(archived=True, locked=True)

    @ticket_group.command(name="claim", description="Claim the current ticket as an assigned admin/lead")
    async def ticket_claim(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, (discord.Thread, discord.TextChannel)):
            await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)
            return

        ticket = await TicketManager.get_ticket_by_thread_id(str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("❌ Ticket record not found in database.", ephemeral=True)
            return

        admin_user = TicketUser(
            discord_id=str(interaction.user.id),
            username=interaction.user.name,
            avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
        )

        await TicketManager.claim_ticket(ticket.id, admin_user)

        claim_embed = discord.Embed(
            description=f"🙋‍♂️ **Ticket Claimed!**\n{interaction.user.mention} has claimed this ticket and will lead the resolution.",
            color=0xFEE75C
        )
        await interaction.response.send_message(embed=claim_embed)

    @ticket_group.command(name="add", description="Add a member to the current ticket thread")
    @app_commands.describe(member="Member to add into the ticket thread")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ This command only works inside a ticket thread.", ephemeral=True)
            return

        try:
            await interaction.channel.add_user(member)
            await interaction.response.send_message(f"✅ Added {member.mention} to this ticket thread.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add member: {e}", ephemeral=True)

    @ticket_group.command(name="remove", description="Remove a member from the current ticket thread")
    @app_commands.describe(member="Member to remove from the ticket thread")
    async def ticket_remove(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ This command only works inside a ticket thread.", ephemeral=True)
            return

        try:
            await interaction.channel.remove_user(member)
            await interaction.response.send_message(f"✅ Removed {member.mention} from this ticket thread.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to remove member: {e}", ephemeral=True)

    @ticket_group.command(name="transcript", description="Download the full transcript of this ticket")
    async def ticket_transcript(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.channel, (discord.Thread, discord.TextChannel)):
            await interaction.followup.send("❌ Must be used inside a ticket thread/channel.", ephemeral=True)
            return

        ticket = await TicketManager.get_ticket_by_thread_id(str(interaction.channel.id))
        if not ticket:
            await interaction.followup.send("❌ Ticket record not found in database.", ephemeral=True)
            return

        messages = await TicketManager.get_ticket_messages(ticket.id)
        transcript_file = TranscriptGenerator.generate_text_transcript(ticket, messages)
        discord_file = discord.File(transcript_file, filename=f"transcript-{ticket.id}.txt")

        await interaction.followup.send(
            content=f"📑 **Transcript for Ticket `{ticket.id}`** ({len(messages)} messages recorded):",
            file=discord_file,
            ephemeral=True
        )

    @ticket_group.command(name="info", description="View database details and metadata for this ticket")
    async def ticket_info(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, (discord.Thread, discord.TextChannel)):
            await interaction.response.send_message("❌ Must be used inside a ticket thread/channel.", ephemeral=True)
            return

        ticket = await TicketManager.get_ticket_by_thread_id(str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("❌ Ticket record not found in database.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 Ticket Info: `{ticket.id}`",
            color=0x5865F2
        )
        embed.add_field(name="Category", value=ticket.category.label, inline=True)
        embed.add_field(name="Status", value=ticket.status.label, inline=True)
        embed.add_field(name="Priority", value=ticket.priority.value.capitalize(), inline=True)
        
        creator_str = f"{ticket.created_by.username} (<@{ticket.created_by.discord_id}>)" if ticket.created_by else "Unknown"
        embed.add_field(name="Created By", value=creator_str, inline=False)

        assigned_str = f"{ticket.assigned_to.username} (<@{ticket.assigned_to.discord_id}>)" if ticket.assigned_to else "Unassigned"
        embed.add_field(name="Assigned Lead/Admin", value=assigned_str, inline=False)

        if ticket.fields:
            for k, v in ticket.fields.items():
                embed.add_field(name=k, value=str(v)[:1024], inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="list", description="List active tickets from Firestore database")
    @app_commands.describe(category="Filter tickets by category")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_list(
        self,
        interaction: discord.Interaction,
        category: Optional[Literal[
            "spg_registration",
            "resource_request",
            "support",
            "idea_jar",
            "report",
            "misc"
        ]] = None
    ):
        await interaction.response.defer(ephemeral=True)

        tickets = await TicketManager.list_active_tickets(category=category, limit=20)
        if not tickets:
            await interaction.followup.send("🟢 No active tickets found matching criteria.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 Active Reinforce Club Tickets ({len(tickets)})",
            color=0x5865F2
        )

        for t in tickets:
            creator_name = t.created_by.username if t.created_by else "Unknown"
            thread_mention = f"<#{t.discord_meta.thread_id}>" if t.discord_meta and t.discord_meta.thread_id else "N/A"
            assigned_name = t.assigned_to.username if t.assigned_to else "Unassigned"

            field_val = (
                f"**Category:** {t.category.label}\n"
                f"**Status:** {t.status.label} | **Assigned:** {assigned_name}\n"
                f"**User:** {creator_name} | **Thread:** {thread_mention}"
            )
            embed.add_field(
                name=f"🎫 `{t.id}` - {t.title[:50]}",
                value=field_val,
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Sync messages sent in ticket threads to Firestore in real time."""
        # Ignore messages sent by the bot itself or webhooks
        if message.author.bot or message.webhook_id:
            return

        # Check if the channel is a Thread
        if not isinstance(message.channel, discord.Thread):
            return

        # Fetch ticket associated with this thread ID
        ticket = await TicketManager.get_ticket_by_thread_id(str(message.channel.id))
        if not ticket or ticket.status == TicketStatus.CLOSED:
            return

        # Determine sender role
        sender_role = "user"
        if isinstance(message.author, discord.Member):
            admin_role_id = os.getenv("ADMIN_ROLE_ID")
            support_role_id = os.getenv("SUPPORT_ROLE_ID")
            role_ids = [str(r.id) for r in message.author.roles]
            
            if message.author.guild_permissions.administrator or (admin_role_id and admin_role_id in role_ids):
                sender_role = "admin"
            elif support_role_id and support_role_id in role_ids:
                sender_role = "lead"

        # Capture attachment URLs
        attachments = [att.url for att in message.attachments] if message.attachments else []

        ticket_msg = TicketMessage(
            sender_id=str(message.author.id),
            sender_name=message.author.name,
            sender_avatar=message.author.display_avatar.url if message.author.display_avatar else None,
            sender_role=sender_role,
            source="discord",
            content=message.content or "",
            attachments=attachments,
            timestamp=message.created_at,
            discord_message_id=str(message.id)
        )

        try:
            await TicketManager.add_ticket_message(ticket.id, ticket_msg)
        except Exception as e:
            print(f"Error syncing ticket message to Firestore: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
