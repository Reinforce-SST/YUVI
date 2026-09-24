from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from firebase_admin import firestore
from models.ticket import TicketUser


class IdeaTrack(str, Enum):
    RESEARCH = "research"
    PRODUCT = "product"
    KAGGLE = "kaggle"
    OTHER = "other"

    @property
    def label(self) -> str:
        labels = {
            IdeaTrack.RESEARCH: "🔬 Research Track",
            IdeaTrack.PRODUCT: "🛠️ Product Track",
            IdeaTrack.KAGGLE: "📊 Kaggle Track",
            IdeaTrack.OTHER: "📦 Other / Cross-Track",
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
    track: str = "other"  # research | product | kaggle | other
    difficulty: str = "intermediate"  # beginner | intermediate | advanced
    prerequisites: List[str] = field(default_factory=list)
    learning_outcomes: List[str] = field(default_factory=list)
    roadmap: List[str] = field(default_factory=list)
    is_approved: bool = False
    created_by_uid: Optional[str] = None
    approved_by_uid: Optional[str] = None
    created_by: Optional[TicketUser] = None
    approved_by: Optional[TicketUser] = None
    created_at: Any = None
    approved_at: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "track": self.track.lower(),
            "difficulty": self.difficulty.lower(),
            "prerequisites": self.prerequisites,
            "learning_outcomes": self.learning_outcomes,
            "roadmap": self.roadmap,
            "rough_roadmap": self.roadmap,
            "is_approved": self.is_approved,
            "is_verified": self.is_approved,
            "created_by_uid": self.created_by_uid,
            "approved_by_uid": self.approved_by_uid,
            "created_by": self.created_by.to_dict() if self.created_by else None,
            "approved_by": self.approved_by.to_dict() if self.approved_by else None,
            "created_at": self.created_at or firestore.SERVER_TIMESTAMP,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, doc_id: str, data: Dict[str, Any]) -> "Idea":
        return cls(
            id=doc_id,
            title=data.get("title", "Untitled Idea"),
            description=data.get("description", ""),
            track=(
                "other" if data.get("track") in {None, "misc"} else data.get("track")
            ),
            difficulty=data.get("difficulty") or "intermediate",
            prerequisites=normalize_items_list(data.get("prerequisites")),
            learning_outcomes=normalize_items_list(data.get("learning_outcomes")),
            roadmap=normalize_items_list(
                data.get("roadmap") or data.get("rough_roadmap")
            ),
            is_approved=data.get("is_approved") is True
            or data.get("is_verified") is True,
            created_by_uid=data.get("created_by_uid"),
            approved_by_uid=data.get("approved_by_uid"),
            created_by=TicketUser.from_dict(data.get("created_by")),
            approved_by=TicketUser.from_dict(data.get("approved_by")),
            created_at=data.get("created_at"),
            approved_at=data.get("approved_at"),
        )
