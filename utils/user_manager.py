import asyncio
from typing import Any, Dict, Optional
from firebase_admin import firestore
from utils.api_client import APIClient
from utils.firestore_client import get_firestore_client

USERS_COLLECTION = "users"


class UserManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @classmethod
    async def get_user(cls, discord_id: str) -> Optional[Dict[str, Any]]:
        """Fetch user record via FastAPI Backend (/api/v1/users?discord_id=...) with fallback."""
        clean_id = str(discord_id).strip()

        # 1. Query via Backend API
        res = await APIClient.get("users", params={"discord_id": clean_id})
        if res and res.get("items"):
            return res["items"][0]

        # 2. Fallback direct API lookup by ID
        res_direct = await APIClient.get(f"users/{clean_id}")
        if res_direct and res_direct.get("id"):
            return res_direct

        # 3. Direct Firestore Fallback
        def _sync_get():
            try:
                db = cls._get_db()
                query = db.collection(USERS_COLLECTION).where("discord_id", "==", clean_id).limit(1)
                docs = list(query.stream())
                if docs:
                    data = docs[0].to_dict()
                    data["doc_id"] = docs[0].id
                    return data

                if clean_id.isdigit():
                    query_int = db.collection(USERS_COLLECTION).where("discord_id", "==", int(clean_id)).limit(1)
                    docs_int = list(query_int.stream())
                    if docs_int:
                        data = docs_int[0].to_dict()
                        data["doc_id"] = docs_int[0].id
                        return data

                doc = db.collection(USERS_COLLECTION).document(clean_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["doc_id"] = doc.id
                    return data

                return None
            except Exception as e:
                print(f"[UserManager] Firestore fallback error fetching user {discord_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_get)

    @classmethod
    async def get_user_by_email(cls, email: str) -> Optional[Dict[str, Any]]:
        """Query user record from API by email with Firestore fallback."""
        clean_email = str(email).lower().strip()

        # 1. Query via Backend API
        res = await APIClient.get(f"users/{clean_email}")
        if res and res.get("id"):
            return res

        # 2. Direct Firestore Fallback
        def _sync_query():
            try:
                db = cls._get_db()
                doc = db.collection(USERS_COLLECTION).document(clean_email).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["doc_id"] = doc.id
                    return data

                query = db.collection(USERS_COLLECTION).where("email", "==", clean_email).limit(1)
                docs = list(query.stream())
                if docs:
                    data = docs[0].to_dict()
                    data["doc_id"] = docs[0].id
                    return data

                return None
            except Exception as e:
                print(f"[UserManager] Firestore fallback error querying email {email}: {e}")
                return None

        return await asyncio.to_thread(_sync_query)

    @classmethod
    async def unlink_user(cls, discord_id: str) -> bool:
        """Unlink Discord ID from user record in Firestore and clear verification status."""
        def _sync_unlink():
            try:
                db = cls._get_db()
                clean_id = str(discord_id).strip()
                unlinked = False

                query_str = db.collection(USERS_COLLECTION).where("discord_id", "==", clean_id)
                for doc in query_str.stream():
                    doc.reference.update({
                        "discord_id": None,
                        "is_verified": False,
                        "discord_link_version": None,
                        "verified_at": None,
                        "social_links.discord": None,
                        "updated_at": firestore.SERVER_TIMESTAMP
                    })
                    unlinked = True

                if clean_id.isdigit():
                    query_int = db.collection(USERS_COLLECTION).where("discord_id", "==", int(clean_id))
                    for doc in query_int.stream():
                        doc.reference.update({
                            "discord_id": None,
                            "is_verified": False,
                            "discord_link_version": None,
                            "verified_at": None,
                            "social_links.discord": None,
                            "updated_at": firestore.SERVER_TIMESTAMP
                        })
                        unlinked = True

                direct_doc = db.collection(USERS_COLLECTION).document(clean_id)
                if direct_doc.get().exists:
                    direct_doc.delete()
                    unlinked = True

                return unlinked
            except Exception as e:
                print(f"[UserManager] Error unlinking user {discord_id}: {e}")
                return False

        return await asyncio.to_thread(_sync_unlink)

