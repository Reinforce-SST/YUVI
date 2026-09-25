import asyncio
import random
from typing import Any, Dict, List, Optional
from firebase_admin import firestore
from models.idea import Idea
from models.ticket import TicketUser
from utils.api_client import APIClient
from utils.firestore_client import get_firestore_client

IDEAS_COLLECTION = "ideas"


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
            "creator_uid": idea.created_by_uid,
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

        res = await APIClient.get("ideas/random", params=params if params else None)
        if res and res.get("id"):
            return Idea.from_dict(res["id"], res)

        # Fallback to direct Firestore
        def _sync_random():
            try:
                db = cls._get_db()
                docs_verified = list(db.collection(IDEAS_COLLECTION).where("is_verified", "==", True).stream())
                docs_approved = list(db.collection(IDEAS_COLLECTION).where("is_approved", "==", True).stream())
                combined = {d.id: d for d in [*docs_verified, *docs_approved]}
                docs = list(combined.values())

                if track and track.lower() not in ("all", "any"):
                    clean_t = "misc" if track.lower() in ("other", "general") else track.lower()
                    docs = [d for d in docs if (d.to_dict() or {}).get("track") == clean_t]

                if difficulty:
                    docs = [d for d in docs if (d.to_dict() or {}).get("difficulty") == difficulty.lower().strip()]

                if not docs:
                    return None

                selected_doc = random.choice(docs)
                return Idea.from_dict(selected_doc.id, selected_doc.to_dict())
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
        """List ideas with filters via API/Firestore."""
        def _sync_list():
            try:
                db = cls._get_db()
                query = db.collection(IDEAS_COLLECTION)
                if is_approved is not None:
                    query = query.where("is_verified", "==", is_approved)
                if track:
                    clean_t = "misc" if track.lower() in ("other", "general") else track.lower()
                    query = query.where("track", "==", clean_t)

                docs = list(query.limit(limit).stream())
                return [Idea.from_dict(d.id, d.to_dict()) for d in docs]
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
                    "approved_by_uid": admin.uid or admin.discord_id,
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

