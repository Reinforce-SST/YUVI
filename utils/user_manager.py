import asyncio
from typing import Any, Dict, Optional
from firebase_admin import firestore
from utils.firestore_client import get_firestore_client

USERS_COLLECTION = "users"

class UserManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @classmethod
    async def get_user(cls, discord_id: str) -> Optional[Dict[str, Any]]:
        """Fetch user record from Firestore by Discord ID (field search or doc ID)."""
        def _sync_get():
            try:
                db = cls._get_db()
                
                # 1. Query by discord_id field (string)
                query = db.collection(USERS_COLLECTION).where("discord_id", "==", str(discord_id).strip()).limit(1)
                docs = list(query.stream())
                if docs:
                    data = docs[0].to_dict()
                    data["doc_id"] = docs[0].id
                    return data

                # 2. Query by discord_id field (integer)
                if str(discord_id).strip().isdigit():
                    query_int = db.collection(USERS_COLLECTION).where("discord_id", "==", int(discord_id.strip())).limit(1)
                    docs_int = list(query_int.stream())
                    if docs_int:
                        data = docs_int[0].to_dict()
                        data["doc_id"] = docs_int[0].id
                        return data

                # 3. Direct document lookup by discord_id / email
                doc = db.collection(USERS_COLLECTION).document(str(discord_id).strip()).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["doc_id"] = doc.id
                    return data

                return None
            except Exception as e:
                print(f"[UserManager] Error fetching user {discord_id}: {e}")
                import traceback
                traceback.print_exc()
                return None

        return await asyncio.to_thread(_sync_get)

    @classmethod
    async def get_user_by_email(cls, email: str) -> Optional[Dict[str, Any]]:
        """Query user record from Firestore by email (document ID or email field)."""
        def _sync_query():
            try:
                db = cls._get_db()
                clean_email = str(email).lower().strip()

                # 1. Direct document lookup by email
                doc = db.collection(USERS_COLLECTION).document(clean_email).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["doc_id"] = doc.id
                    return data

                # 2. Query by email field
                query = db.collection(USERS_COLLECTION).where("email", "==", clean_email).limit(1)
                docs = list(query.stream())
                if docs:
                    data = docs[0].to_dict()
                    data["doc_id"] = docs[0].id
                    return data

                return None
            except Exception as e:
                print(f"[UserManager] Error querying user by email {email}: {e}")
                import traceback
                traceback.print_exc()
                return None

        return await asyncio.to_thread(_sync_query)

    @classmethod
    async def unlink_user(cls, discord_id: str) -> bool:
        """Unlink Discord ID from user record in Firestore and set is_verified to False."""
        def _sync_unlink():
            try:
                db = cls._get_db()
                clean_id = str(discord_id).strip()
                unlinked = False

                # 1. Query by discord_id field (string)
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
                    print(f"[UserManager] Unlinked discord_id from user doc '{doc.id}'")
                    unlinked = True

                # 2. Query by discord_id field (integer)
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
                        print(f"[UserManager] Unlinked int discord_id from user doc '{doc.id}'")
                        unlinked = True

                # 3. Direct document by discord_id if it was keyed by Discord ID
                direct_doc = db.collection(USERS_COLLECTION).document(clean_id)
                if direct_doc.get().exists:
                    direct_doc.delete()
                    print(f"[UserManager] Deleted direct user doc '{clean_id}'")
                    unlinked = True

                return unlinked
            except Exception as e:
                print(f"[UserManager] Error unlinking user {discord_id}: {e}")
                import traceback
                traceback.print_exc()
                return False

        return await asyncio.to_thread(_sync_unlink)
