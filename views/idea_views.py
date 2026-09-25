import os
import discord
from discord import ui
from typing import Optional

from models.idea import Idea, IdeaTrack, IdeaDifficulty, normalize_items_list
from models.ticket import TicketUser
from utils.idea_manager import IdeaManager

def format_track_badge(track_str: str) -> str:
    t = track_str.lower().strip()
    badges = {
        "research": "🔬 Research Track",
        "product": "🛠️ Product Track",
        "kaggle": "📊 Kaggle Track",
        "other": "📦 Other / Cross-Track"
    }
    return badges.get(t, f"📌 {track_str.capitalize()}")


def format_difficulty_badge(diff_str: str) -> str:
    d = diff_str.lower().strip()
    badges = {
        "beginner": "🟢 Beginner",
        "intermediate": "🟡 Intermediate",
        "advanced": "🔴 Advanced"
    }
    return badges.get(d, diff_str.capitalize())


def build_idea_embed(idea: Idea) -> discord.Embed:
    """Build a clean, structured embed for displaying an Idea."""
    track_badge = format_track_badge(idea.track)
    diff_badge = format_difficulty_badge(idea.difficulty)

    upvotes = (idea.stats or {}).get("upvote_count", 0)
    views = (idea.stats or {}).get("views_count", 0)
    claims = (idea.stats or {}).get("claims_count", 0)

    embed = discord.Embed(
        title=f"💡 {idea.title}",
        description=idea.description,
        color=0xFEE75C # Gold / Idea Jar Yellow
    )
    embed.add_field(name="Track", value=track_badge, inline=True)
    embed.add_field(name="Difficulty", value=diff_badge, inline=True)
    embed.add_field(name="Engagement", value=f"👍 `{upvotes}` upvotes • 👀 `{views}` views", inline=True)

    if idea.prerequisites:
        prereq_text = "\n".join(f"• {p}" for p in idea.prerequisites)
        embed.add_field(name="Prerequisites", value=prereq_text[:1024], inline=False)

    if idea.learning_outcomes:
        outcomes_text = "\n".join(f"• {o}" for o in idea.learning_outcomes)
        embed.add_field(name="Learning Outcomes", value=outcomes_text[:1024], inline=False)

    if idea.rough_roadmap or idea.roadmap:
        roadmap_items = idea.rough_roadmap or idea.roadmap
        roadmap_text = "\n".join(f"• {r}" for r in roadmap_items)
        embed.add_field(name="Rough Roadmap / Milestones", value=roadmap_text[:1024], inline=False)

    creator_name = idea.created_by.username if idea.created_by else "Reinforce Community"
    embed.set_footer(text=f"ID: {idea.id} • Submitted by {creator_name} • Reinforce Idea Jar")
    return embed


class SubmitIdeaModal(ui.Modal):
    idea_title = ui.TextInput(
        label="Idea Title",
        placeholder="e.g., Automated Kaggle Competition Benchmark Bot",
        max_length=100,
        required=True
    )
    description = ui.TextInput(
        label="Description & Concept",
        placeholder="Explain what the project is, the problem it solves, and how it should work...",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=True
    )
    prerequisites = ui.TextInput(
        label="Prerequisites (1 item per line)",
        placeholder="python\nflask\nnumpy",
        style=discord.TextStyle.paragraph,
        max_length=800,
        required=False
    )
    learning_outcomes = ui.TextInput(
        label="Learning Outcomes (1 item per line)",
        placeholder="REST API Design\nAsync Task Processing\nModel Evaluation",
        style=discord.TextStyle.paragraph,
        max_length=800,
        required=False
    )
    roadmap = ui.TextInput(
        label="Roadmap (1 item per line)",
        placeholder="Phase 1: Setup & EDA\nPhase 2: Core Algorithm\nPhase 3: Deployment",
        style=discord.TextStyle.paragraph,
        max_length=800,
        required=False
    )

    def __init__(self, track: str = "other", difficulty: str = "intermediate"):
        track_label = format_track_badge(track).split(" ")[1] if " " in format_track_badge(track) else track.capitalize()
        super().__init__(title=f"💡 Submit Idea ({track_label})")
        self.track = track
        self.difficulty = difficulty

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ticket_user = TicketUser(
            discord_id=str(interaction.user.id),
            username=interaction.user.name,
            discriminator=getattr(interaction.user, "discriminator", None),
            avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
        )

        idea = Idea(
            title=self.idea_title.value,
            description=self.description.value,
            track=self.track,
            difficulty=self.difficulty,
            prerequisites=normalize_items_list(self.prerequisites.value),
            learning_outcomes=normalize_items_list(self.learning_outcomes.value),
            roadmap=normalize_items_list(self.roadmap.value),
            is_approved=False,
            created_by=ticket_user
        )

        try:
            idea_id = await IdeaManager.create_idea(idea)
            idea.id = idea_id

            await interaction.followup.send(
                f"✅ **Idea Submitted Successfully!**\n"
                f"Your submission (`{idea_id}`) for **{format_track_badge(self.track)}** ({format_difficulty_badge(self.difficulty)}) "
                f"is now pending review by the track leads. Once approved, it will be added to the public Idea Jar.",
                ephemeral=True
            )

            # Notify admin channel
            admin_channel_id = os.getenv("TRANSCRIPTS_CHANNEL_ID") or os.getenv("TICKETS_CHANNEL_ID")
            if admin_channel_id and interaction.guild:
                channel = interaction.guild.get_channel(int(admin_channel_id))
                if isinstance(channel, discord.TextChannel):
                    review_embed = build_idea_embed(idea)
                    review_embed.title = f"📝 Pending Idea Submission: {idea.title}"
                    review_embed.add_field(name="Status", value="⏳ Pending Review", inline=False)
                    await channel.send(
                        content=f"🔔 **New Idea Submitted by {interaction.user.mention}** (Use `/idea approve {idea_id}` to approve):",
                        embed=review_embed
                    )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to save idea: {e}", ephemeral=True)


class IdeaSubmissionSelectorView(ui.View):
    """Ephemeral selection view containing Track and Difficulty dropdowns."""
    def __init__(self):
        super().__init__(timeout=180)
        self.selected_track = "product"
        self.selected_difficulty = "intermediate"

    @ui.select(
        placeholder="📂 Select Project Track...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Product Track", value="product", description="Software apps, full-stack, developer tools", emoji="🛠️", default=True),
            discord.SelectOption(label="Kaggle Track", value="kaggle", description="Data science, ML models, competition pipelines", emoji="📊"),
            discord.SelectOption(label="Research Track", value="research", description="Papers, novel architectures, experimentation", emoji="🔬"),
            discord.SelectOption(label="Other / Cross-Track", value="other", description="General community projects, utilities, misc", emoji="📦"),
        ]
    )
    async def track_select(self, interaction: discord.Interaction, select: ui.Select):
        self.selected_track = select.values[0]
        # Update default markers
        for opt in select.options:
            opt.default = (opt.value == self.selected_track)
        await interaction.response.edit_message(view=self)

    @ui.select(
        placeholder="⚡ Select Difficulty Level...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Beginner", value="beginner", description="Accessible for newcomers & foundational learning", emoji="🟢"),
            discord.SelectOption(label="Intermediate", value="intermediate", description="Moderate complexity, standard stack familiarity", emoji="🟡", default=True),
            discord.SelectOption(label="Advanced", value="advanced", description="High complexity, research depth, or large scale", emoji="🔴"),
        ]
    )
    async def difficulty_select(self, interaction: discord.Interaction, select: ui.Select):
        self.selected_difficulty = select.values[0]
        # Update default markers
        for opt in select.options:
            opt.default = (opt.value == self.selected_difficulty)
        await interaction.response.edit_message(view=self)

    @ui.button(label="Fill Idea Details ✍️", style=discord.ButtonStyle.primary)
    async def fill_details_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            SubmitIdeaModal(
                track=self.selected_track,
                difficulty=self.selected_difficulty
            )
        )


class RandomIdeaRerollView(ui.View):
    def __init__(self, track: Optional[str] = None, difficulty: Optional[str] = None):
        super().__init__(timeout=180)
        self.track = track
        self.difficulty = difficulty

    @ui.button(label="Draw Another Idea", style=discord.ButtonStyle.primary, emoji="🎲")
    async def reroll_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        idea = await IdeaManager.get_random_idea(track=self.track, difficulty=self.difficulty)
        if not idea:
            await interaction.followup.send("No more approved ideas found matching your criteria.", ephemeral=True)
            return

        embed = build_idea_embed(idea)
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)


class IdeaPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="Get Random Idea",
        style=discord.ButtonStyle.success,
        emoji="🎲",
        custom_id="persistent_idea_random"
    )
    async def random_idea_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        idea = await IdeaManager.get_random_idea()
        if not idea:
            await interaction.followup.send(
                "🏺 The Idea Jar is currently empty or has no approved ideas yet! Be the first to submit an idea.",
                ephemeral=True
            )
            return

        embed = build_idea_embed(idea)
        await interaction.followup.send(embed=embed, view=RandomIdeaRerollView(), ephemeral=True)

    @ui.button(
        label="Submit an Idea",
        style=discord.ButtonStyle.primary,
        emoji="💡",
        custom_id="persistent_idea_submit"
    )
    async def submit_idea_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="💡 Submit a Project Idea",
            description=(
                "Please select the target **Track** and **Difficulty** from the dropdown menus below, "
                "then click **Fill Idea Details** to open the submission form."
            ),
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, view=IdeaSubmissionSelectorView(), ephemeral=True)
