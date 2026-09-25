import discord
from discord import ui
from models.ticket import TicketCategory
from views.ticket_modals import (
    SPGModal,
    ResourceRequestModal,
    SupportInquiryModal,
    IdeaJarModal,
    ReportModal,
    MiscModal
)

class TicketCategorySelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="SPG Registration / Modification",
                value=TicketCategory.SPG_REGISTRATION.value,
                description="Register team, select track (Product/Kaggle/Research), duration, milestones",
                emoji="🚀"
            ),
            discord.SelectOption(
                label="Resource Request",
                value=TicketCategory.RESOURCE_REQUEST.value,
                description="Request GPU/Compute, hardware, API credits, mentorship (SPGs)",
                emoji="⚡"
            ),
            discord.SelectOption(
                label="Support & Inquiries",
                value=TicketCategory.SUPPORT.value,
                description="Questions regarding club activities, events, tracks, or guidance",
                emoji="💬"
            ),
            discord.SelectOption(
                label="Idea Jar & Suggestions",
                value=TicketCategory.IDEA_JAR.value,
                description="Submit project ideas or suggest improvements for the club",
                emoji="💡"
            ),
            discord.SelectOption(
                label="Feedback & Suggestions",
                value=TicketCategory.FEEDBACK.value,
                description="Share feedback or suggestions to improve the club",
                emoji="📝"
            ),
            discord.SelectOption(
                label="Report Issue / Misconduct",
                value=TicketCategory.REPORT.value,
                description="Confidential report for server/club misconduct or disputes",
                emoji="🛡️"
            ),
            discord.SelectOption(
                label="General / Misc",
                value=TicketCategory.MISC.value,
                description="Anything else not covered by the above categories",
                emoji="📦"
            ),
        ]
        super().__init__(
            placeholder="📂 Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="persistent_ticket_category_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]

        if selected_value == TicketCategory.SPG_REGISTRATION.value:
            await interaction.response.send_modal(SPGModal())
        elif selected_value == TicketCategory.RESOURCE_REQUEST.value:
            await interaction.response.send_modal(ResourceRequestModal())
        elif selected_value == TicketCategory.SUPPORT.value:
            await interaction.response.send_modal(SupportInquiryModal())
        elif selected_value == TicketCategory.IDEA_JAR.value:
            await interaction.response.send_modal(IdeaJarModal())
        elif selected_value == TicketCategory.FEEDBACK.value:
            from views.ticket_modals import FeedbackModal
            await interaction.response.send_modal(FeedbackModal())
        elif selected_value == TicketCategory.REPORT.value:
            await interaction.response.send_modal(ReportModal())
        else:
            await interaction.response.send_modal(MiscModal())

        # Reset the dropdown menu so the same option can be selected again immediately
        try:
            if interaction.message:
                await interaction.message.edit(view=TicketPanelView())
        except Exception as e:
            print(f"[TicketPanel] Note: Could not reset dropdown state: {e}")


class TicketPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())
