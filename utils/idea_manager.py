import asyncio
import random
from typing import List, Optional
from firebase_admin import firestore
from models.idea import Idea
from models.ticket import TicketUser
from utils.firestore_client import get_firestore_client

IDEAS_COLLECTION = "ideas"
USERS_COLLECTION = "users"


class IdeaManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @staticmethod
    def _normalized_track(track: Optional[str]) -> Optional[str]:
        if track is None:
            return None
        normalized = track.lower().strip()
        return "other" if normalized == "misc" else normalized

    @classmethod
    def _load_ideas(cls, collection, is_approved: Optional[bool], limit: int):
        by_id = {}
        if is_approved is None:
            queries = [collection]
        else:
            queries = [
                collection.where(field, "==", is_approved)
                for field in ("is_approved", "is_verified")
            ]
        for query in queries:
            for doc in query.stream():
                by_id[doc.id] = doc
        return [Idea.from_dict(doc.id, doc.to_dict()) for doc in by_id.values()]

    @classmethod
    async def create_idea(cls, idea: Idea) -> str:
        """Create a new idea in Firestore with an auto-generated ID."""

        def _sync_create():
            try:
                db = cls._get_db()
                if idea.created_by and not idea.created_by_uid:
                    profiles = list(
                        db.collection(USERS_COLLECTION)
                        .where("discord_id", "==", idea.created_by.discord_id)
                        .limit(1)
                        .stream()
                    )
                    if profiles:
                        profile = profiles[0].to_dict() or {}
                        idea.created_by_uid = str(
                            profile.get("id")
                            or profile.get("firebase_uid")
                            or profiles[0].id
                        )
                doc_ref = db.collection(IDEAS_COLLECTION).document()
                idea.id = doc_ref.id
                doc_ref.set(idea.to_dict())
                print(
                    f"[IdeaManager] Created idea {doc_ref.id} (Approved: {idea.is_approved})"
                )
                return doc_ref.id
            except Exception as e:
                print(f"[IdeaManager] Error creating idea: {e}")
                raise e

        return await asyncio.to_thread(_sync_create)

    @classmethod
    async def get_idea(cls, idea_id: str) -> Optional[Idea]:
        """Fetch an idea by its Firestore document ID."""

        def _sync_get():
            try:
                db = cls._get_db()
                doc = db.collection(IDEAS_COLLECTION).document(idea_id.strip()).get()
                if doc.exists:
                    return Idea.from_dict(doc.id, doc.to_dict())
                return None
            except Exception as e:
                print(f"[IdeaManager] Error getting idea {idea_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_get)

    @classmethod
    async def get_random_idea(
        cls, track: Optional[str] = None, difficulty: Optional[str] = None
    ) -> Optional[Idea]:
        """Fetch a random approved idea, with optional track or difficulty filters."""

        def _sync_random():
            try:
                db = cls._get_db()
                ideas = cls._load_ideas(db.collection(IDEAS_COLLECTION), True, 200)
                normalized_track = cls._normalized_track(track)
                normalized_difficulty = (
                    difficulty.lower().strip() if difficulty else None
                )
                ideas = [
                    idea
                    for idea in ideas
                    if (normalized_track is None or idea.track == normalized_track)
                    and (
                        normalized_difficulty is None
                        or idea.difficulty == normalized_difficulty
                    )
                ]
                if not ideas:
                    return None
                return random.choice(ideas)
            except Exception as e:
                print(f"[IdeaManager] Error fetching random idea: {e}")
                return None

        return await asyncio.to_thread(_sync_random)

    @classmethod
    async def list_ideas(
        cls,
        is_approved: Optional[bool] = True,
        track: Optional[str] = None,
        limit: int = 50,
    ) -> List[Idea]:
        """List ideas with optional approval and track filters."""

        def _sync_list():
            try:
                db = cls._get_db()
                ideas = cls._load_ideas(
                    db.collection(IDEAS_COLLECTION), is_approved, limit
                )
                if is_approved is not None:
                    ideas = [idea for idea in ideas if idea.is_approved is is_approved]
                normalized_track = cls._normalized_track(track)
                if normalized_track is not None:
                    ideas = [idea for idea in ideas if idea.track == normalized_track]
                return ideas[:limit]
            except Exception as e:
                print(f"[IdeaManager] Error listing ideas: {e}")
                return []

        return await asyncio.to_thread(_sync_list)

    @classmethod
    async def approve_idea(cls, idea_id: str, admin: TicketUser) -> bool:
        """Mark an idea as approved."""

        def _sync_approve():
            try:
                db = cls._get_db()
                doc_ref = db.collection(IDEAS_COLLECTION).document(idea_id.strip())
                if not doc_ref.get().exists:
                    return False
                profiles = list(
                    db.collection(USERS_COLLECTION)
                    .where("discord_id", "==", admin.discord_id)
                    .limit(1)
                    .stream()
                )
                doc_ref.update(
                    {
                        "is_approved": True,
                        "is_verified": True,
                        "approved_by": admin.to_dict(),
                        "approved_by_uid": (
                            str(
                                (profiles[0].to_dict() or {}).get("id")
                                or (profiles[0].to_dict() or {}).get("firebase_uid")
                                or profiles[0].id
                            )
                            if profiles
                            else None
                        ),
                        "approved_at": firestore.SERVER_TIMESTAMP,
                    }
                )
                print(f"[IdeaManager] Approved idea {idea_id} by {admin.username}")
                return True
            except Exception as e:
                print(f"[IdeaManager] Error approving idea {idea_id}: {e}")
                return False

        return await asyncio.to_thread(_sync_approve)

    @classmethod
    async def delete_idea(cls, idea_id: str) -> bool:
        """Delete an idea document."""

        def _sync_delete():
            try:
                db = cls._get_db()
                db.collection(IDEAS_COLLECTION).document(idea_id.strip()).delete()
                print(f"[IdeaManager] Deleted idea {idea_id}")
                return True
            except Exception as e:
                print(f"[IdeaManager] Error deleting idea {idea_id}: {e}")
                return False

        return await asyncio.to_thread(_sync_delete)
