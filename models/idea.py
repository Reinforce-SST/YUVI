from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from firebase_admin import firestore
from models.ticket import TicketUser


class IdeaTrack(str, Enum):
    RESEARCH = "research"
    PRODUCT = "product"
    KAGGLE = "kaggle"
    MISC = "misc"
    OTHER = "misc"

    @property
    def label(self) -> str:
        labels = {
            IdeaTrack.RESEARCH: "🔬 Research Track",
            IdeaTrack.PRODUCT: "🛠️ Product Track",
            IdeaTrack.KAGGLE: "📊 Kaggle Track",
            IdeaTrack.MISC: "📦 General / Misc",
            IdeaTrack.OTHER: "📦 General / Misc",
        }
        return labels.get(self, self.value.capitalize())


class IdeaDifficulty(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

    @property
    def label(self) -> str:
        labels = {
            IdeaDifficulty.BEGINNER: "🟢 Beginner",
            IdeaDifficulty.INTERMEDIATE: "🟡 Intermediate",
            IdeaDifficulty.ADVANCED: "🔴 Advanced",
        }
        return labels.get(self, self.value.capitalize())


def normalize_items_list(val: Any) -> List[str]:
    """Helper to ensure newline-separated strings or lists are parsed as a clean list of strings."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(item).strip() for item in val if str(item).strip()]
    if isinstance(val, str):
        items = []
        for line in val.splitlines():
            cleaned = line.strip().lstrip("•-*0123456789.) ").strip()
            if cleaned:
                items.append(cleaned)
        return items
    return []


@dataclass
class Idea:
    id: Optional[str] = None
    title: str = ""
    description: str = ""
    track: str = "misc"                           # research | product | kaggle | misc
    difficulty: str = "intermediate"              # beginner | intermediate | advanced
    prerequisites: List[str] = field(default_factory=list)
    learning_outcomes: List[str] = field(default_factory=list)
    rough_roadmap: List[str] = field(default_factory=list)
    is_verified: bool = False
    is_approved: bool = False
    created_by_uid: Optional[str] = None
    created_by: Optional[TicketUser] = None
    approved_by_uid: Optional[str] = None
    approved_by: Optional[TicketUser] = None
    stats: Dict[str, int] = field(default_factory=lambda: {"upvote_count": 0, "views_count": 0, "claims_count": 0})
    created_at: Any = None
    approved_at: Optional[Any] = None

    @property
    def roadmap(self) -> List[str]:
        return self.rough_roadmap

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "track": "misc" if self.track in ("other", "general") else self.track.lower(),
            "difficulty": self.difficulty.lower() if self.difficulty else "intermediate",
            "prerequisites": self.prerequisites,
            "learning_outcomes": self.learning_outcomes,
            "rough_roadmap": self.rough_roadmap,
            "roadmap": self.rough_roadmap,
            "is_verified": self.is_verified or self.is_approved,
            "is_approved": self.is_verified or self.is_approved,
            "created_by_uid": self.created_by_uid or (self.created_by.uid if self.created_by else None),
            "created_by": self.created_by.to_dict() if self.created_by else None,
            "approved_by_uid": self.approved_by_uid or (self.approved_by.uid if self.approved_by else None),
            "approved_by": self.approved_by.to_dict() if self.approved_by else None,
            "stats": self.stats,
            "created_at": self.created_at or firestore.SERVER_TIMESTAMP,
            "approved_at": self.approved_at
        }

    @classmethod
    def from_dict(cls, doc_id: str, data: Dict[str, Any]) -> "Idea":
        stats_raw = data.get("stats") or {}
        stats = {
            "upvote_count": int(stats_raw.get("upvote_count", 0)),
            "views_count": int(stats_raw.get("views_count", 0)),
            "claims_count": int(stats_raw.get("claims_count", 0)),
        }
        roadmap = normalize_items_list(data.get("rough_roadmap") or data.get("roadmap"))
        is_verified = bool(data.get("is_verified") or data.get("is_approved"))

        return cls(
            id=doc_id,
            title=data.get("title", "Untitled Idea"),
            description=data.get("description", ""),
            track="misc" if data.get("track") in ("other", "general") else data.get("track", "misc"),
            difficulty=data.get("difficulty", "intermediate"),
            prerequisites=normalize_items_list(data.get("prerequisites")),
            learning_outcomes=normalize_items_list(data.get("learning_outcomes")),
            rough_roadmap=roadmap,
            is_verified=is_verified,
            is_approved=is_verified,
            created_by_uid=data.get("created_by_uid"),
            created_by=TicketUser.from_dict(data.get("created_by")),
            approved_by_uid=data.get("approved_by_uid"),
            approved_by=TicketUser.from_dict(data.get("approved_by")),
            stats=stats,
            created_at=data.get("created_at"),
            approved_at=data.get("approved_at")
        )

