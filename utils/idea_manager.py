import asyncio
import random
from typing import List, Optional
from firebase_admin import firestore
from models.idea import Idea
from models.ticket import TicketUser
from utils.api_client import APIClient
from utils.auth_links import verified_uid_for_discord
from utils.firestore_client import get_firestore_client

IDEAS_COLLECTION = "ideas"
def _user_uid(db, discord_id: Optional[str]) -> Optional[str]:
    return verified_uid_for_discord(db, discord_id) if discord_id else None


class IdeaManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @classmethod
    async def create_idea(cls, idea: Idea) -> str:
        """Create a new idea via API (/api/v1/ideas) with Firestore fallback."""
        payload = {
            "title": idea.title,
            "description": idea.description,
            "track": "misc" if idea.track in ("other", "general") else idea.track.lower(),
            "difficulty": idea.difficulty.lower() if idea.difficulty else "intermediate",
            "prerequisites": idea.prerequisites,
            "rough_roadmap": idea.rough_roadmap,
            "learning_outcomes": idea.learning_outcomes,
        }

        res = await APIClient.post("ideas", json_data=payload)
        if res and res.get("id"):
            idea_id = res["id"]
            idea.id = idea_id
            if idea.created_by:
                def _sync_creator_patch():
                    db = cls._get_db()
                    db.collection(IDEAS_COLLECTION).document(idea_id).set({
                        "created_by": idea.created_by.to_dict()
                    }, merge=True)
                await asyncio.to_thread(_sync_creator_patch)
            return idea_id

        # Direct Firestore Fallback
        def _sync_create():
            try:
                db = cls._get_db()
                if idea.created_by and not idea.created_by_uid:
                    idea.created_by_uid = _user_uid(db, idea.created_by.discord_id)
                doc_ref = db.collection(IDEAS_COLLECTION).document()
                idea.id = doc_ref.id
                doc_ref.set(idea.to_dict())
                return doc_ref.id
            except Exception as e:
                print(f"[IdeaManager] Error creating idea in Firestore: {e}")
                raise e

        return await asyncio.to_thread(_sync_create)

    @classmethod
    async def get_idea(cls, idea_id: str) -> Optional[Idea]:
        """Fetch an idea by ID via API with fallback."""
        clean_id = idea_id.strip()
        res = await APIClient.get(f"ideas/{clean_id}")
        if res and res.get("id"):
            return Idea.from_dict(res["id"], res)

        def _sync_get():
            try:
                db = cls._get_db()
                doc = db.collection(IDEAS_COLLECTION).document(clean_id).get()
                if doc.exists:
                    return Idea.from_dict(doc.id, doc.to_dict())
                return None
            except Exception as e:
                print(f"[IdeaManager] Error getting idea {idea_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_get)

    @classmethod
    async def get_random_idea(
        cls,
        track: Optional[str] = None,
        difficulty: Optional[str] = None
    ) -> Optional[Idea]:
        """Fetch a random approved idea via API (/api/v1/ideas/random) with fallback."""
        params = {}
        if track and track.lower() not in ("all", "any"):
            params["track"] = "misc" if track.lower() in ("other", "general") else track.lower()

        res = (
            await APIClient.get("ideas/random", params=params if params else None)
            if not difficulty else None
        )
        if res and res.get("id"):
            return Idea.from_dict(res["id"], res)

        # Fallback to direct Firestore
        def _sync_random():
            try:
                db = cls._get_db()
                docs_verified = list(db.collection(IDEAS_COLLECTION).where("is_verified", "==", True).stream())
                docs_approved = list(db.collection(IDEAS_COLLECTION).where("is_approved", "==", True).stream())
                combined = {d.id: d for d in [*docs_verified, *docs_approved]}
                ideas = [Idea.from_dict(doc.id, doc.to_dict() or {}) for doc in combined.values()]
                if track and track.lower() not in ("all", "any"):
                    clean_t = "misc" if track.lower() in ("other", "general", "misc") else track.lower()
                    ideas = [idea for idea in ideas if idea.track == clean_t]
                if difficulty:
                    ideas = [idea for idea in ideas if idea.difficulty == difficulty.lower().strip()]

                if not ideas:
                    return None

                return random.choice(ideas)
            except Exception as e:
                print(f"[IdeaManager] Error fetching random idea from Firestore: {e}")
                return None

        return await asyncio.to_thread(_sync_random)

    @classmethod
    async def list_ideas(
        cls,
        is_approved: Optional[bool] = True,
        track: Optional[str] = None,
        limit: int = 50
    ) -> List[Idea]:
        """List canonical and legacy ideas with approval and track filters."""
        def _sync_list():
            try:
                db = cls._get_db()
                collection = db.collection(IDEAS_COLLECTION)
                queries = [collection] if is_approved is None else [
                    collection.where("is_verified", "==", is_approved),
                    collection.where("is_approved", "==", is_approved),
                ]
                by_id = {doc.id: doc for query in queries for doc in query.stream()}
                ideas = [Idea.from_dict(doc.id, doc.to_dict() or {}) for doc in by_id.values()]
                if is_approved is not None:
                    ideas = [idea for idea in ideas if idea.is_approved is is_approved]
                if track:
                    clean_t = "misc" if track.lower() in ("other", "general", "misc") else track.lower()
                    ideas = [idea for idea in ideas if idea.track == clean_t]
                return ideas[:limit]
            except Exception as e:
                print(f"[IdeaManager] Error listing ideas: {e}")
                return []

        return await asyncio.to_thread(_sync_list)

    @classmethod
    async def approve_idea(cls, idea_id: str, admin: TicketUser) -> bool:
        """Mark an idea as approved via API / Firestore."""
        clean_id = idea_id.strip()
        res = await APIClient.post(f"ideas/{clean_id}/approve")
        if res:
            return True

        def _sync_approve():
            try:
                db = cls._get_db()
                doc_ref = db.collection(IDEAS_COLLECTION).document(clean_id)
                if not doc_ref.get().exists:
                    return False
                doc_ref.update({
                    "is_verified": True,
                    "is_approved": True,
                    "approved_by": admin.to_dict(),
                    "approved_by_uid": admin.uid or _user_uid(db, admin.discord_id),
                    "approved_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP
                })
                return True
            except Exception as e:
                print(f"[IdeaManager] Error approving idea {idea_id}: {e}")
                return False

        return await asyncio.to_thread(_sync_approve)

    @classmethod
    async def delete_idea(cls, idea_id: str) -> bool:
        """Delete an idea document via API / Firestore."""
        clean_id = idea_id.strip()
        deleted = await APIClient.delete(f"ideas/{clean_id}")
        if deleted:
            return True

        def _sync_delete():
            try:
                db = cls._get_db()
                db.collection(IDEAS_COLLECTION).document(clean_id).delete()
                return True
            except Exception as e:
                print(f"[IdeaManager] Error deleting idea {idea_id}: {e}")
                return False

        return await asyncio.to_thread(_sync_delete)
