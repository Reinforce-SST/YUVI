import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from typing import Optional

from utils.user_manager import UserManager
from utils.auth_links import issue_link
from utils.firestore_client import get_firestore_client

class AuthLinkView(ui.View):
    def __init__(self, auth_url: str):
        super().__init__(timeout=None)
        self.add_item(
            ui.Button(
                label="Sign In with Google (@sst.scaler.com)",
                url=auth_url,
                style=discord.ButtonStyle.link,
                emoji="🔐"
            )
        )


async def send_auth_link(interaction: discord.Interaction):
    """Helper to check verification status and send an ephemeral login link."""
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    # Fresh proof is also required for legacy links and role-grant retries.
    frontend_url = os.getenv("FRONTEND_AUTH_URL", "http://localhost:3000/auth")
    try:
        auth_url = await asyncio.to_thread(issue_link, get_firestore_client(), discord_id, frontend_url)
    except Exception:
        await interaction.followup.send("Verification is temporarily unavailable. Please try /auth again shortly.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔐 Reinforce Club SST Member Verification",
        description=(
            f"Welcome {interaction.user.mention}!\n\n"
            "To unlock full access to the Reinforce Club Discord server, discussion channels, and Student Project Groups (SPGs), "
            "please authenticate using your official college Google account (**`@sst.scaler.com`**).\n\n"
            "Click below within ten minutes. Keep this link private. If your role is missing after signing in, run /auth again to retry."
        ),
        color=0x5865F2 # Blurple
    )
    embed.set_footer(text="Reinforce Club SST • Single Sign-On")
    if interaction.guild and interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    view = AuthLinkView(auth_url)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class AuthPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="Verify with Google (@sst.scaler.com)",
        style=discord.ButtonStyle.primary,
        emoji="🔐",
        custom_id="persistent_auth_button"
    )
    async def auth_button(self, interaction: discord.Interaction, button: ui.Button):
        await send_auth_link(interaction)


class AuthCog(commands.Cog, name="Authentication"):
    """User authentication and Google account linking with Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent view so button works across bot restarts
        self.bot.add_view(AuthPanelView())

    @app_commands.command(name="setup-auth", description="Deploy the official Reinforce Club Member Verification panel")
    @app_commands.describe(channel="Channel to post the verification panel into (defaults to current channel)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_auth(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None
    ):
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("❌ Target must be a text channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔐 Reinforce Club SST — Member Verification",
            description=(
                "Welcome to the official **Reinforce Club** Discord server!\n\n"
                "To unlock access to discussion channels, workshop resources, and Student Project Groups (SPGs), "
                "you must link your official student Google account (**`@sst.scaler.com`**).\n\n"
                "**How to Verify:**\n"
                "1. Click the **Verify with Google** button below.\n"
                "2. Click the unique sign-in link generated for your account.\n"
                "3. Authorize with your `@sst.scaler.com` Google account.\n"
                "4. Your **Verified Member** role will be granted automatically!"
            ),
            color=0x5865F2 # Reinforce Blurple
        )
        embed.set_footer(text="Reinforce Club SST • Automated Verification Portal")
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await target_channel.send(embed=embed, view=AuthPanelView())
        await interaction.response.send_message(f"✅ Verification panel deployed to {target_channel.mention}!", ephemeral=True)

    @app_commands.command(name="auth", description="Link your @sst.scaler.com Google account to get verified member access")
    async def auth_command(self, interaction: discord.Interaction):
        await send_auth_link(interaction)

    @app_commands.command(name="whois", description="Lookup linked Google account info for a member")
    @app_commands.describe(member="Discord member to inspect")
    @app_commands.checks.has_permissions(administrator=True)
    async def whois_command(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        user_data = await UserManager.get_user(str(member.id))
        if not user_data:
            await interaction.followup.send(f"❌ No linked Google account found in database for {member.mention} (`{member.id}`).", ephemeral=True)
            return

        email = user_data.get("email", "N/A")
        full_name = user_data.get("full_name") or user_data.get("name") or "N/A"
        tier = str(user_data.get("tier", "beginner")).capitalize()
        is_member = "✅ Member" if user_data.get("is_member") else "❌ Non-Member"
        is_admin = "🛡️ Admin" if user_data.get("is_admin") else "👤 Student"
        verified_at = user_data.get("verified_at") or user_data.get("created_at") or "N/A"

        points = user_data.get("points") or {}
        if isinstance(points, dict):
            pts_total = points.get("total", 0)
            pts_kaggle = points.get("kaggle", 0)
            pts_product = points.get("product", 0)
            pts_research = points.get("research", 0)
            pts_misc = points.get("misc", 0)
        else:
            pts_total = pts_kaggle = pts_product = pts_research = pts_misc = 0

        skills = user_data.get("skills") or []
        skills_str = ", ".join(skills[:6]) if skills else "None listed"

        embed = discord.Embed(
            title=f"👤 Member Record: {full_name}",
            color=0x5865F2
        )
        embed.add_field(name="Discord User", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="SST Email", value=f"`{email}`", inline=True)
        embed.add_field(name="Tier & Role", value=f"`{tier}` | {is_member} | {is_admin}", inline=True)
        
        points_breakdown = (
            f"🏆 **Total:** `{pts_total}` pts\n"
            f"📊 Kaggle: `{pts_kaggle}` | 🛠️ Product: `{pts_product}`\n"
            f"🔬 Research: `{pts_research}` | 📦 Misc: `{pts_misc}`"
        )
        embed.add_field(name="Points & Standing", value=points_breakdown, inline=False)
        embed.add_field(name="Skills", value=skills_str, inline=True)
        embed.add_field(name="Verified Date", value=str(verified_at)[:19], inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="whois-email", description="Lookup Discord member linked to an SST email")
    @app_commands.describe(email="SST Email address (@sst.scaler.com)")
    @app_commands.checks.has_permissions(administrator=True)
    async def whois_email_command(self, interaction: discord.Interaction, email: str):
        await interaction.response.defer(ephemeral=True)

        user_data = await UserManager.get_user_by_email(email)
        if not user_data:
            await interaction.followup.send(f"❌ No user found in database linked to `{email}`.", ephemeral=True)
            return

        discord_id = user_data.get("discord_id") or user_data.get("id")
        full_name = user_data.get("full_name") or user_data.get("name") or "N/A"
        tier = str(user_data.get("tier", "beginner")).capitalize()
        is_member = "✅ Member" if user_data.get("is_member") else "❌ Non-Member"
        
        points = user_data.get("points") or {}
        pts_total = points.get("total", 0) if isinstance(points, dict) else 0

        embed = discord.Embed(
            title=f"📧 Email Record: {email}",
            color=0x5865F2
        )
        if discord_id and str(discord_id).isdigit():
            embed.add_field(name="Discord ID", value=f"<@{discord_id}> (`{discord_id}`)", inline=False)
        else:
            embed.add_field(name="Discord Link", value="⚠️ Not linked to Discord", inline=False)

        embed.add_field(name="Full Name", value=f"`{full_name}`", inline=True)
        embed.add_field(name="Status & Tier", value=f"{is_member} (`{tier}`)", inline=True)
        embed.add_field(name="Total Points", value=f"🏆 `{pts_total}` pts", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink a member's Google account and strip their verified role")
    @app_commands.describe(member="Member to unlink")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlink_command(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        success = await UserManager.unlink_user(str(member.id))
        
        # Locate verified role via VERIFIED_ROLE_ID or by name
        role_id_str = os.getenv("VERIFIED_ROLE_ID")
        verified_role = None

        if interaction.guild:
            if role_id_str and role_id_str.strip().isdigit():
                verified_role = interaction.guild.get_role(int(role_id_str.strip()))

            if not verified_role:
                for r in interaction.guild.roles:
                    if r.name.lower() in ("verified member", "verified", "member"):
                        verified_role = r
                        break

        role_removed = False
        role_error = None

        if verified_role and verified_role in member.roles:
            try:
                await member.remove_roles(verified_role, reason=f"Unlinked by {interaction.user}")
                role_removed = True
            except discord.Forbidden:
                role_error = f"Bot lacks permission to remove {verified_role.mention} (make sure the Bot's role is positioned higher in Server Settings -> Roles)."
            except Exception as e:
                role_error = f"Error removing role: {e}"

        embed = discord.Embed(
            title="🔗 Member Unlinked",
            color=0x57F287 if success or role_removed else 0xED4245
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        
        db_status = "✅ Removed from database" if success else "⚠️ No database record found or already unlinked"
        embed.add_field(name="Database Status", value=db_status, inline=True)

        if role_removed:
            role_status = f"✅ Removed {verified_role.mention}"
        elif verified_role and verified_role not in member.roles:
            role_status = f"ℹ️ Did not have {verified_role.mention}"
        elif role_error:
            role_status = f"⚠️ {role_error}"
        else:
            role_status = "ℹ️ Verified role not configured in .env"

        embed.add_field(name="Role Status", value=role_status, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuthCog(bot))