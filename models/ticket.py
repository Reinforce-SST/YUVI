from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from firebase_admin import firestore

class TicketCategory(str, Enum):
    SPG_REGISTRATION = "spg_registration"
    RESOURCE_REQUEST = "resource_request"
    SUPPORT = "support"
    IDEA_JAR = "idea_jar"
    FEEDBACK = "feedback"
    REPORT = "report"
    MISC = "misc"

    @property
    def label(self) -> str:
        labels = {
            TicketCategory.SPG_REGISTRATION: "🚀 SPG Registration / Modification",
            TicketCategory.RESOURCE_REQUEST: "⚡ Resource Request",
            TicketCategory.SUPPORT: "💬 Support & General Inquiries",
            TicketCategory.IDEA_JAR: "💡 Idea Jar & Suggestions",
            TicketCategory.FEEDBACK: "📝 General Feedback & Suggestions",
            TicketCategory.REPORT: "🛡️ Report Issue / Misconduct",
            TicketCategory.MISC: "📦 General / Misc"
        }
        return labels.get(self, self.value)

    @property
    def short_name(self) -> str:
        shorts = {
            TicketCategory.SPG_REGISTRATION: "spg",
            TicketCategory.RESOURCE_REQUEST: "resource",
            TicketCategory.SUPPORT: "support",
            TicketCategory.IDEA_JAR: "idea",
            TicketCategory.FEEDBACK: "feedback",
            TicketCategory.REPORT: "report",
            TicketCategory.MISC: "misc"
        }
        return shorts.get(self, "ticket")

    @property
    def emoji(self) -> str:
        emojis = {
            TicketCategory.SPG_REGISTRATION: "🚀",
            TicketCategory.RESOURCE_REQUEST: "⚡",
            TicketCategory.SUPPORT: "💬",
            TicketCategory.IDEA_JAR: "💡",
            TicketCategory.FEEDBACK: "📝",
            TicketCategory.REPORT: "🛡️",
            TicketCategory.MISC: "📦"
        }
        return emojis.get(self, "🎫")

    @property
    def description(self) -> str:
        descriptions = {
            TicketCategory.SPG_REGISTRATION: "Register or update a Student Project Group (Product, Kaggle, Research)",
            TicketCategory.RESOURCE_REQUEST: "Request GPU/Compute, hardware, API credits, or mentorship (SPG only)",
            TicketCategory.SUPPORT: "Get help with club activities, roles, events, or tracks",
            TicketCategory.IDEA_JAR: "Submit project ideas or suggest improvements for the club",
            TicketCategory.FEEDBACK: "Share feedback or suggestions to improve the club",
            TicketCategory.REPORT: "Confidential reports regarding rule violations or misconduct",
            TicketCategory.MISC: "Other questions or inquiries"
        }
        return descriptions.get(self, "Support Ticket")


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        labels = {
            TicketStatus.OPEN: "🟢 Open",
            TicketStatus.IN_PROGRESS: "🟡 In Progress",
            TicketStatus.RESOLVED: "🔵 Resolved",
            TicketStatus.CLOSED: "🔴 Closed"
        }
        return labels.get(self, self.value)


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class TicketUser:
    discord_id: str
    username: str
    discriminator: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    uid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "discord_id": self.discord_id,
            "username": self.username,
            "discriminator": self.discriminator,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "uid": self.uid
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["TicketUser"]:
        if not data:
            return None
        return cls(
            discord_id=str(data.get("discord_id", "")),
            username=data.get("username", "Unknown"),
            discriminator=data.get("discriminator"),
            email=data.get("email"),
            avatar_url=data.get("avatar_url"),
            uid=data.get("uid")
        )


@dataclass
class DiscordMeta:
    guild_id: str
    channel_id: str
    thread_id: str
    panel_message_id: Optional[str] = None
    control_message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "thread_id": self.thread_id,
            "panel_message_id": self.panel_message_id,
            "control_message_id": self.control_message_id
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["DiscordMeta"]:
        if not data:
            return None
        return cls(
            guild_id=str(data.get("guild_id", "")),
            channel_id=str(data.get("channel_id", "")),
            thread_id=str(data.get("thread_id", "")),
            panel_message_id=str(data.get("panel_message_id")) if data.get("panel_message_id") else None,
            control_message_id=str(data.get("control_message_id")) if data.get("control_message_id") else None
        )


@dataclass
class TicketMessage:
    sender_id: str
    sender_name: str
    sender_avatar: Optional[str] = None
    sender_role: str = "user"  # "user", "admin", "lead", "bot"
    source: str = "discord"     # "discord", "web"
    content: str = ""
    attachments: List[str] = field(default_factory=list)
    timestamp: Any = None
    discord_message_id: Optional[str] = None
    id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_avatar": self.sender_avatar,
            "sender_role": self.sender_role,
            "source": self.source,
            "content": self.content,
            "attachments": self.attachments,
            "timestamp": self.timestamp or firestore.SERVER_TIMESTAMP,
            "discord_message_id": self.discord_message_id
        }

    @classmethod
    def from_dict(cls, doc_id: str, data: Dict[str, Any]) -> "TicketMessage":
        return cls(
            id=doc_id,
            sender_id=str(data.get("sender_id", "")),
            sender_name=data.get("sender_name", "Unknown"),
            sender_avatar=data.get("sender_avatar"),
            sender_role=data.get("sender_role", "user"),
            source=data.get("source", "discord"),
            content=data.get("content", ""),
            attachments=data.get("attachments", []),
            timestamp=data.get("timestamp"),
            discord_message_id=str(data.get("discord_message_id")) if data.get("discord_message_id") else None
        )


@dataclass
class Ticket:
    id: Optional[str] = None
    category: TicketCategory = TicketCategory.MISC
    title: str = ""
    description: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    status: TicketStatus = TicketStatus.OPEN
    priority: TicketPriority = TicketPriority.MEDIUM
    created_by: Optional[TicketUser] = None
    created_by_uid: Optional[str] = None
    assigned_to: Optional[TicketUser] = None
    assigned_to_uid: Optional[str] = None
    closed_by: Optional[TicketUser] = None
    closed_by_uid: Optional[str] = None
    close_reason: Optional[str] = None
    spg_id: Optional[str] = None
    discord_meta: Optional[DiscordMeta] = None
    thread_id: Optional[str] = None
    guild_id: Optional[str] = None
    created_at: Any = None
    updated_at: Any = None
    closed_at: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        tid = self.thread_id or (self.discord_meta.thread_id if self.discord_meta else None)
        gid = self.guild_id or (self.discord_meta.guild_id if self.discord_meta else None)
        c_uid = self.created_by_uid or (self.created_by.uid if self.created_by else None)
        a_uid = self.assigned_to_uid or (self.assigned_to.uid if self.assigned_to else None)
        cl_uid = self.closed_by_uid or (self.closed_by.uid if self.closed_by else None)

        data = {
            "category": self.category.value if isinstance(self.category, TicketCategory) else str(self.category),
            "title": self.title,
            "description": self.description,
            "fields": self.fields,
            "status": self.status.value if isinstance(self.status, TicketStatus) else str(self.status),
            "priority": self.priority.value if isinstance(self.priority, TicketPriority) else str(self.priority),
            "created_by": self.created_by.to_dict() if self.created_by else None,
            "created_by_uid": c_uid,
            "assigned_to": self.assigned_to.to_dict() if self.assigned_to else None,
            "assigned_to_uid": a_uid,
            "closed_by": self.closed_by.to_dict() if self.closed_by else None,
            "closed_by_uid": cl_uid,
            "close_reason": self.close_reason,
            "spg_id": self.spg_id,
            "discord_meta": self.discord_meta.to_dict() if self.discord_meta else None,
            "thread_id": tid,
            "guild_id": gid,
            "created_at": self.created_at or firestore.SERVER_TIMESTAMP,
            "updated_at": self.updated_at or firestore.SERVER_TIMESTAMP,
            "closed_at": self.closed_at
        }
        return data

    @classmethod
    def from_dict(cls, doc_id: str, data: Dict[str, Any]) -> "Ticket":
        cat_val = data.get("category", "misc")
        try:
            category = TicketCategory(cat_val)
        except ValueError:
            category = TicketCategory.MISC

        status_val = data.get("status", "open")
        try:
            status = TicketStatus(status_val)
        except ValueError:
            status = TicketStatus.OPEN

        prio_val = data.get("priority", "medium")
        try:
            priority = TicketPriority(prio_val)
        except ValueError:
            priority = TicketPriority.MEDIUM

        discord_meta = DiscordMeta.from_dict(data.get("discord_meta"))
        thread_id = str(data.get("thread_id")) if data.get("thread_id") else (discord_meta.thread_id if discord_meta else None)
        guild_id = str(data.get("guild_id")) if data.get("guild_id") else (discord_meta.guild_id if discord_meta else None)

        return cls(
            id=doc_id,
            category=category,
            title=data.get("title", ""),
            description=data.get("description", ""),
            fields=data.get("fields", {}),
            status=status,
            priority=priority,
            created_by=TicketUser.from_dict(data.get("created_by")),
            created_by_uid=data.get("created_by_uid"),
            assigned_to=TicketUser.from_dict(data.get("assigned_to")),
            assigned_to_uid=data.get("assigned_to_uid"),
            closed_by=TicketUser.from_dict(data.get("closed_by")),
            closed_by_uid=data.get("closed_by_uid"),
            close_reason=data.get("close_reason"),
            spg_id=data.get("spg_id"),
            discord_meta=discord_meta,
            thread_id=thread_id,
            guild_id=guild_id,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            closed_at=data.get("closed_at")
        )
