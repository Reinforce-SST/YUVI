import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from firebase_admin import firestore
from models.ticket import (
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketStatus,
    TicketUser,
)
from utils.firestore_client import get_firestore_client

TICKETS_COLLECTION = "tickets"
MESSAGES_SUBCOLLECTION = "messages"


class TicketManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @classmethod
    async def create_ticket(cls, ticket: Ticket) -> str:
        """Create a new ticket document with an auto-generated Firestore ID."""

        def _sync_create():
            try:
                db = cls._get_db()
                doc_ref = db.collection(TICKETS_COLLECTION).document()
                ticket.id = doc_ref.id
                doc_data = ticket.to_dict()
                doc_ref.set(doc_data)
                print(
                    f"[TicketManager] Successfully created ticket {doc_ref.id} in Firestore for thread {ticket.thread_id or (ticket.discord_meta.thread_id if ticket.discord_meta else 'N/A')}"
                )
                return doc_ref.id
            except Exception as e:
                print(f"[TicketManager] Error creating ticket in Firestore: {e}")
                import traceback

                traceback.print_exc()
                raise e

        return await asyncio.to_thread(_sync_create)

    @classmethod
    async def get_ticket(cls, ticket_id: str) -> Optional[Ticket]:
        """Fetch a ticket by its Firestore document ID."""

        def _sync_get():
            try:
                db = cls._get_db()
                doc = db.collection(TICKETS_COLLECTION).document(ticket_id).get()
                if doc.exists:
                    return Ticket.from_dict(doc.id, doc.to_dict())
                return None
            except Exception as e:
                print(f"[TicketManager] Error getting ticket {ticket_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_get)

    @classmethod
    async def get_ticket_by_thread_id(cls, thread_id: str) -> Optional[Ticket]:
        """Fetch a ticket by its Discord thread ID or document ID."""

        def _sync_query():
            try:
                db = cls._get_db()
                # 1. Query by top-level thread_id
                query = (
                    db.collection(TICKETS_COLLECTION)
                    .where("thread_id", "==", str(thread_id))
                    .limit(1)
                )
                docs = list(query.stream())
                if docs:
                    return Ticket.from_dict(docs[0].id, docs[0].to_dict())

                # 2. Fallback: Query by discord_meta.thread_id
                query2 = (
                    db.collection(TICKETS_COLLECTION)
                    .where("discord_meta.thread_id", "==", str(thread_id))
                    .limit(1)
                )
                docs2 = list(query2.stream())
                if docs2:
                    return Ticket.from_dict(docs2[0].id, docs2[0].to_dict())

                # 3. Fallback: Check if document ID is the thread_id
                doc3 = db.collection(TICKETS_COLLECTION).document(str(thread_id)).get()
                if doc3.exists:
                    return Ticket.from_dict(doc3.id, doc3.to_dict())

                return None
            except Exception as e:
                print(
                    f"[TicketManager] Error querying ticket by thread_id {thread_id}: {e}"
                )
                import traceback

                traceback.print_exc()
                return None

        return await asyncio.to_thread(_sync_query)

    @classmethod
    async def update_ticket(cls, ticket_id: str, updates: Dict[str, Any]) -> None:
        """Update fields on a ticket document."""

        def _sync_update():
            db = cls._get_db()
            updates["updated_at"] = firestore.SERVER_TIMESTAMP
            db.collection(TICKETS_COLLECTION).document(ticket_id).update(updates)

        await asyncio.to_thread(_sync_update)

    @classmethod
    async def reserve_thread_creation(cls, ticket_id: str) -> Dict[str, Any]:
        """Atomically reserve Discord thread creation for one worker."""

        def _sync_reserve():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            transaction = db.transaction()

            @firestore.transactional
            def reserve(txn):
                snapshot = ticket_ref.get(transaction=txn)
                if not snapshot.exists:
                    return {"status": "missing"}
                data = snapshot.to_dict() or {}
                meta = data.get("discord_meta") or {}
                state = data.get("discord_thread_state")
                if meta.get("thread_id") and state == "ready":
                    return {"status": "existing", "discord_meta": meta}

                started_at = data.get("discord_thread_started_at")
                if isinstance(started_at, str):
                    try:
                        started_at = datetime.fromisoformat(
                            started_at.replace("Z", "+00:00")
                        )
                    except ValueError:
                        started_at = None
                now = datetime.now(timezone.utc)
                if (
                    state in {"creating", "created"}
                    and isinstance(started_at, datetime)
                    and now - started_at.astimezone(timezone.utc) < timedelta(minutes=2)
                ):
                    return {"status": "busy"}

                txn.update(
                    ticket_ref,
                    {
                        "discord_thread_state": "creating",
                        "discord_thread_started_at": now.isoformat(),
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                )
                return {
                    "status": "resume" if meta.get("thread_id") else "reserved",
                    "discord_meta": meta or None,
                }

            return reserve(transaction)

        return await asyncio.to_thread(_sync_reserve)

    @classmethod
    async def release_thread_creation(cls, ticket_id: str) -> None:
        """Release a failed bridge reservation so a retry can proceed."""
        await cls.update_ticket(
            ticket_id,
            {
                "discord_thread_state": "retryable",
                "discord_thread_started_at": None,
            },
        )

    @classmethod
    async def add_ticket_message(cls, ticket_id: str, message: TicketMessage) -> str:
        """Add a message to the ticket's messages subcollection and touch updated_at."""

        def _sync_add():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            msg_ref = ticket_ref.collection(MESSAGES_SUBCOLLECTION).document(
                str(message.discord_message_id) if message.discord_message_id else None
            )
            if message.discord_message_id and msg_ref.get().exists:
                return msg_ref.id
            msg_data = message.to_dict()
            msg_ref.set(msg_data)
            ticket_ref.update({"updated_at": firestore.SERVER_TIMESTAMP})
            return msg_ref.id

        return await asyncio.to_thread(_sync_add)

    @classmethod
    async def get_ticket_messages(
        cls, ticket_id: str, limit: int = 300
    ) -> List[TicketMessage]:
        """Retrieve all messages in chronological order for a ticket."""

        def _sync_get_messages():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            query = (
                ticket_ref.collection(MESSAGES_SUBCOLLECTION)
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(limit)
            )
            docs = query.stream()
            messages = []
            for d in docs:
                messages.append(TicketMessage.from_dict(d.id, d.to_dict()))
            messages.reverse()
            return messages

        return await asyncio.to_thread(_sync_get_messages)

    @classmethod
    async def claim_ticket(cls, ticket_id: str, admin: TicketUser) -> bool:
        """Mark ticket as claimed by admin and change status to in_progress."""

        def _sync_claim():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            ticket_ref.update(
                {
                    "assigned_to": admin.to_dict(),
                    "status": TicketStatus.IN_PROGRESS.value,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return True

        return await asyncio.to_thread(_sync_claim)

    @classmethod
    async def close_ticket(
        cls, ticket_id: str, closed_by: TicketUser, reason: Optional[str] = None
    ) -> bool:
        """Close the ticket and record closing metadata."""

        def _sync_close():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            ticket_ref.update(
                {
                    "status": TicketStatus.CLOSED.value,
                    "closed_by": closed_by.to_dict(),
                    "close_reason": reason or "No reason provided",
                    "closed_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return True

        return await asyncio.to_thread(_sync_close)

    @classmethod
    async def list_active_tickets(
        cls, category: Optional[str] = None, limit: int = 50
    ) -> List[Ticket]:
        """List active tickets (open or in_progress)."""

        def _sync_list():
            try:
                db = cls._get_db()
                query = (
                    db.collection(TICKETS_COLLECTION)
                    .where(
                        "status",
                        "in",
                        [TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value],
                    )
                    .limit(limit)
                )
                docs = list(query.stream())
                results = [Ticket.from_dict(d.id, d.to_dict()) for d in docs]
                if category:
                    results = [
                        t
                        for t in results
                        if (
                            t.category.value
                            if isinstance(t.category, TicketCategory)
                            else str(t.category)
                        )
                        == category
                    ]
                return results
            except Exception as e:
                print(f"[TicketManager] Error listing active tickets: {e}")
                import traceback

                traceback.print_exc()
                return []

        return await asyncio.to_thread(_sync_list)

    @classmethod
    async def list_user_tickets(
        cls, discord_user_id: str, limit: int = 20
    ) -> List[Ticket]:
        """List all tickets created by a specific Discord user."""

        def _sync_list_user():
            try:
                db = cls._get_db()
                query = (
                    db.collection(TICKETS_COLLECTION)
                    .where("created_by.discord_id", "==", str(discord_user_id))
                    .limit(limit)
                )
                docs = list(query.stream())
                return [Ticket.from_dict(d.id, d.to_dict()) for d in docs]
            except Exception as e:
                print(f"[TicketManager] Error listing user tickets: {e}")
                return []

        return await asyncio.to_thread(_sync_list_user)
