import os
import discord
from discord import ui
from typing import Dict, Any, Optional

from models.ticket import (
    Ticket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    TicketUser,
    DiscordMeta,
    TicketMessage
)
from utils.ticket_manager import TicketManager

async def create_ticket_thread_and_doc(
    interaction: discord.Interaction,
    category: TicketCategory,
    title: str,
    description: str,
    fields: Dict[str, Any]
):
    """Helper to create a private Discord thread and save the ticket to Firestore."""
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This action must be performed in a Discord server.", ephemeral=True)
        return

    # Defer interaction response early to prevent timeout
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Determine channel for thread creation (configured channel or interaction channel)
    configured_channel_id = os.getenv("TICKETS_CHANNEL_ID")
    target_channel = guild.get_channel(int(configured_channel_id)) if configured_channel_id else interaction.channel
    
    if not isinstance(target_channel, (discord.TextChannel, discord.ForumChannel)):
        target_channel = interaction.channel

    if not isinstance(target_channel, (discord.TextChannel, discord.ForumChannel)):
        await interaction.followup.send("❌ Tickets channel must be a text or forum channel.", ephemeral=True)
        return

    # Clean username for thread name
    clean_username = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c in ("-", "_"))[:15]
    thread_name = f"{category.emoji}-{category.short_name}-{clean_username}"

    try:
        # Create private thread
        # discord.ChannelType.private_thread requires private thread permissions
        thread = await target_channel.create_thread(
            name=thread_name,
            auto_archive_duration=10080, # 7 days
            type=discord.ChannelType.private_thread,
            reason=f"Support Ticket for {interaction.user} ({category.value})"
        )
    except discord.Forbidden:
        # Fallback to public thread if private thread permission isn't available
        try:
            thread = await target_channel.create_thread(
                name=thread_name,
                auto_archive_duration=10080,
                reason=f"Support Ticket for {interaction.user} ({category.value})"
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create ticket thread: {e}", ephemeral=True)
            return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to create ticket thread: {e}", ephemeral=True)
        return

    # Add user to the thread
    try:
        await thread.add_user(interaction.user)
    except Exception:
        pass

    # Build Ticket model
    ticket_user = TicketUser(
        discord_id=str(interaction.user.id),
        username=interaction.user.name,
        discriminator=getattr(interaction.user, "discriminator", None),
        avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
    )

    discord_meta = DiscordMeta(
        guild_id=str(guild.id),
        channel_id=str(target_channel.id),
        thread_id=str(thread.id)
    )

    ticket = Ticket(
        category=category,
        title=title,
        description=description,
        fields=fields,
        status=TicketStatus.OPEN,
        priority=TicketPriority.MEDIUM,
        created_by=ticket_user,
        discord_meta=discord_meta,
        thread_id=str(thread.id),
        guild_id=str(guild.id)
    )

    try:
        # Save to Firestore
        ticket_id = await TicketManager.create_ticket(ticket)
        ticket.id = ticket_id

        # Add initial creation message to the Firestore messages subcollection
        initial_msg = TicketMessage(
            sender_id=str(interaction.user.id),
            sender_name=interaction.user.name,
            sender_avatar=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            sender_role="user",
            source="discord",
            content=f"**[{category.label}] {title}**\n\n{description}"
        )
        await TicketManager.add_ticket_message(ticket_id, initial_msg)
    except Exception as e:
        print(f"[TicketCreation] Error saving ticket to Firestore: {e}")
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"⚠️ Thread created, but encountered a database error: {e}", ephemeral=True)
        ticket_id = str(thread.id)

    # Build rich embed for the ticket thread header
    embed = discord.Embed(
        title=f"{category.emoji} {title}",
        description=f"Welcome {interaction.user.mention}! Support team and track leads will assist you shortly.\n\nUse the buttons below to manage this ticket.",
        color=0x5865F2 # Discord Blurple / Reinforce Blue
    )
    embed.add_field(name="📋 Category", value=category.label, inline=True)
    embed.add_field(name="🆔 Ticket ID", value=f"`{ticket_id}`", inline=True)
    embed.add_field(name="🚦 Status", value="🟢 Open", inline=True)
    embed.add_field(name="👤 Opened By", value=interaction.user.mention, inline=True)
    embed.add_field(name="⏰ Priority", value="Medium", inline=True)
    
    # Add custom fields if any
    for k, v in fields.items():
        if v and len(str(v)) > 0:
            embed.add_field(name=f"📌 {k}", value=str(v)[:1024], inline=False)

    embed.set_footer(text="Reinforce Club Ticket System • Synced with Firestore Dashboard", icon_url=guild.icon.url if guild.icon else None)

    # Import controls view here to avoid circular imports
    from views.ticket_controls import TicketControlView
    control_view = TicketControlView()

    # Ping admin/support role if configured
    admin_role_id = os.getenv("ADMIN_ROLE_ID") or os.getenv("SUPPORT_ROLE_ID")
    admin_mention = f"<@&{admin_role_id}>" if admin_role_id else ""

    control_msg = await thread.send(
        content=f"{interaction.user.mention} {admin_mention}",
        embed=embed,
        view=control_view
    )

    # Update control message ID in Firestore
    await TicketManager.update_ticket(ticket_id, {
        "discord_meta.control_message_id": str(control_msg.id)
    })

    await interaction.followup.send(f"✅ Your ticket has been created: {thread.mention}", ephemeral=True)


class SPGModal(ui.Modal, title="🚀 SPG Registration / Modification"):
    project_name = ui.TextInput(
        label="Project Name & Track",
        placeholder="e.g., Project Phoenix (Product / Kaggle / Research)",
        max_length=100,
        required=True
    )
    team_members = ui.TextInput(
        label="Leader & Team Members",
        placeholder="Leader: @username (Club member), Members: @user1, @user2",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )
    duration = ui.TextInput(
        label="Estimated Duration & Report Frequency",
        placeholder="e.g., 3 Months • Bi-weekly progress updates",
        max_length=100,
        required=True
    )
    objectives = ui.TextInput(
        label="Project Summary & Next Steps",
        placeholder="Describe the problem, milestones, goals, and current blockers...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "project_name": self.project_name.value,
            "team_members": self.team_members.value,
            "duration": self.duration.value,
            "goals": self.objectives.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.SPG_REGISTRATION,
            title=f"SPG: {self.project_name.value}",
            description=self.objectives.value,
            fields=fields
        )


class ResourceRequestModal(ui.Modal, title="⚡ Resource Request (SPGs Only)"):
    project_name = ui.TextInput(
        label="Registered SPG Project Name",
        placeholder="e.g., Project Phoenix",
        max_length=100,
        required=True
    )
    resources_needed = ui.TextInput(
        label="Resources Required",
        placeholder="e.g., Kaggle GPU / Cloud Compute / API Credits / Hardware / Mentorship",
        max_length=200,
        required=True
    )
    progress_proof = ui.TextInput(
        label="Proof of Existing Progress & Links",
        placeholder="GitHub repo link, demo URL, research draft, or past milestone report...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )
    justification = ui.TextInput(
        label="Purpose & Resource Justification",
        placeholder="Why are these resources needed and how will they accelerate your milestones?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "project_name": self.project_name.value,
            "resources_needed": self.resources_needed.value,
            "progress_proof_url": self.progress_proof.value,
            "justification": self.justification.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.RESOURCE_REQUEST,
            title=f"Resource Request: {self.project_name.value}",
            description=self.justification.value,
            fields=fields
        )


class SupportInquiryModal(ui.Modal, title="💬 Support & General Inquiries"):
    subject = ui.TextInput(
        label="Subject / Topic",
        placeholder="e.g., Question about upcoming Kaggle Datathon",
        max_length=100,
        required=True
    )
    details = ui.TextInput(
        label="Details & Question",
        placeholder="Explain what you need assistance with...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "subject": self.subject.value,
            "details": self.details.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.SUPPORT,
            title=self.subject.value,
            description=self.details.value,
            fields=fields
        )


class IdeaJarModal(ui.Modal, title="💡 Idea Jar & Suggestions"):
    idea_title = ui.TextInput(
        label="Idea / Suggestion Title",
        placeholder="e.g., Automated Kaggle Notebook Benchmark Bot",
        max_length=100,
        required=True
    )
    track = ui.TextInput(
        label="Target Track / Category",
        placeholder="e.g., Product / Kaggle / Research / Club Events",
        max_length=100,
        required=True
    )
    overview = ui.TextInput(
        label="Idea Description & Learning Objectives",
        placeholder="What is the concept, skill requirements, and learning objectives for someone building this?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "idea_title": self.idea_title.value,
            "track": self.track.value,
            "overview": self.overview.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.IDEA_JAR,
            title=f"Idea Jar: {self.idea_title.value}",
            description=self.overview.value,
            fields=fields
        )


class FeedbackModal(ui.Modal, title="📝 Feedback & Suggestions"):
    topic = ui.TextInput(
        label="Feedback Topic",
        placeholder="e.g., Workshop pacing, Discord channels, Website UX",
        max_length=100,
        required=True
    )
    comments = ui.TextInput(
        label="Feedback & Details",
        placeholder="Share what worked well and what we can improve...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "topic": self.topic.value,
            "comments": self.comments.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.FEEDBACK,
            title=f"Feedback: {self.topic.value}",
            description=self.comments.value,
            fields=fields
        )


class ReportModal(ui.Modal, title="🛡️ Report Issue / Misconduct (Confidential)"):
    summary = ui.TextInput(
        label="Incident Summary",
        placeholder="Brief summary of the issue or concern",
        max_length=100,
        required=True
    )
    description = ui.TextInput(
        label="Detailed Report",
        placeholder="Provide all relevant details, names, dates, or context. This is visible only to core admins.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "incident_summary": self.summary.value,
            "confidential_details": self.description.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.REPORT,
            title=f"Report: {self.summary.value}",
            description=self.description.value,
            fields=fields
        )


class MiscModal(ui.Modal, title="📦 General Ticket"):
    subject = ui.TextInput(
        label="Subject",
        placeholder="Brief subject of your ticket",
        max_length=100,
        required=True
    )
    details = ui.TextInput(
        label="Description",
        placeholder="Please describe your request...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "subject": self.subject.value,
            "details": self.details.value
        }
        await create_ticket_thread_and_doc(
            interaction=interaction,
            category=TicketCategory.MISC,
            title=self.subject.value,
            description=self.details.value,
            fields=fields
        )
