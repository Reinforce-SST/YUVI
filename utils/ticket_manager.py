import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from firebase_admin import firestore
from models.ticket import Ticket, TicketCategory, TicketMessage, TicketStatus, TicketUser
from utils.api_client import APIClient
from utils.firestore_client import get_firestore_client

TICKETS_COLLECTION = "tickets"
MESSAGES_SUBCOLLECTION = "messages"


class TicketManager:
    @staticmethod
    def _get_db():
        return get_firestore_client()

    @classmethod
    async def create_ticket(cls, ticket: Ticket) -> str:
        """Create a new ticket via backend API (/api/v1/tickets) with Firestore fallback."""
        payload = {
            "category": ticket.category.value if isinstance(ticket.category, TicketCategory) else str(ticket.category),
            "title": ticket.title,
            "description": ticket.description,
            "fields": ticket.fields,
            "spg_id": ticket.spg_id,
        }

        # Try API creation first
        api_res = await APIClient.post("tickets", json_data=payload)
        if api_res and api_res.get("id"):
            ticket_id = api_res["id"]
            ticket.id = ticket_id
            # Sync discord_meta to the ticket doc in Firestore
            if ticket.discord_meta:
                await cls.update_ticket(ticket_id, {
                    "discord_meta": ticket.discord_meta.to_dict(),
                    "thread_id": ticket.thread_id or ticket.discord_meta.thread_id,
                    "guild_id": ticket.guild_id or ticket.discord_meta.guild_id,
                    "created_by": ticket.created_by.to_dict() if ticket.created_by else None
                })
            return ticket_id

        # Direct Firestore Fallback
        def _sync_create():
            try:
                db = cls._get_db()
                doc_ref = db.collection(TICKETS_COLLECTION).document()
                ticket.id = doc_ref.id
                doc_data = ticket.to_dict()
                doc_ref.set(doc_data)
                return doc_ref.id
            except Exception as e:
                print(f"[TicketManager] Error creating ticket in Firestore: {e}")
                raise e

        return await asyncio.to_thread(_sync_create)

    @classmethod
    async def get_ticket(cls, ticket_id: str) -> Optional[Ticket]:
        """Fetch a ticket by its document ID."""
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
                query = db.collection(TICKETS_COLLECTION).where("thread_id", "==", str(thread_id)).limit(1)
                docs = list(query.stream())
                if docs:
                    return Ticket.from_dict(docs[0].id, docs[0].to_dict())

                # 2. Query by discord_meta.thread_id
                query2 = db.collection(TICKETS_COLLECTION).where("discord_meta.thread_id", "==", str(thread_id)).limit(1)
                docs2 = list(query2.stream())
                if docs2:
                    return Ticket.from_dict(docs2[0].id, docs2[0].to_dict())

                # 3. Direct document ID check
                doc3 = db.collection(TICKETS_COLLECTION).document(str(thread_id)).get()
                if doc3.exists:
                    return Ticket.from_dict(doc3.id, doc3.to_dict())

                return None
            except Exception as e:
                print(f"[TicketManager] Error querying ticket by thread_id {thread_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_query)

    @classmethod
    async def update_ticket(cls, ticket_id: str, updates: Dict[str, Any]) -> None:
        """Update fields on a ticket document."""
        def _sync_update():
            db = cls._get_db()
            updates["updated_at"] = firestore.SERVER_TIMESTAMP
            db.collection(TICKETS_COLLECTION).document(ticket_id).set(updates, merge=True)

        await asyncio.to_thread(_sync_update)

    @classmethod
    async def add_ticket_message(cls, ticket_id: str, message: TicketMessage) -> str:
        """Sync message via API webhook (/api/v1/tickets/internal/bot-sync/{ticket_id}) with fallback."""
        payload = {
            "sender_uid": message.sender_id,
            "sender_name": message.sender_name,
            "sender_role": message.sender_role,
            "source": message.source or "discord",
            "content": message.content,
            "attachments": message.attachments,
            "discord_message_id": message.discord_message_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Try API sync endpoint
        res = await APIClient.post(f"tickets/internal/bot-sync/{ticket_id}", json_data=payload)
        if res and res.get("id"):
            return res["id"]

        # Direct Firestore Fallback
        def _sync_add():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            msg_ref = ticket_ref.collection(MESSAGES_SUBCOLLECTION).document()
            msg_data = message.to_dict()
            msg_ref.set(msg_data)
            ticket_ref.update({"updated_at": firestore.SERVER_TIMESTAMP})
            return msg_ref.id

        return await asyncio.to_thread(_sync_add)

    @classmethod
    async def get_ticket_messages(cls, ticket_id: str, limit: int = 300) -> List[TicketMessage]:
        """Retrieve all messages in chronological order for a ticket."""
        def _sync_get_messages():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            query = ticket_ref.collection(MESSAGES_SUBCOLLECTION).order_by("timestamp", direction=firestore.Query.ASCENDING).limit(limit)
            docs = query.stream()
            messages = []
            for d in docs:
                messages.append(TicketMessage.from_dict(d.id, d.to_dict()))
            return messages

        return await asyncio.to_thread(_sync_get_messages)

    @classmethod
    async def claim_ticket(cls, ticket_id: str, admin: TicketUser) -> bool:
        """Claim ticket via API / Firestore."""
        # 1. Update Firestore
        def _sync_claim():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            ticket_ref.update({
                "assigned_to": admin.to_dict(),
                "assigned_to_uid": admin.uid or admin.discord_id,
                "status": TicketStatus.IN_PROGRESS.value,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            return True

        return await asyncio.to_thread(_sync_claim)

    @classmethod
    async def close_ticket(cls, ticket_id: str, closed_by: TicketUser, reason: Optional[str] = None) -> bool:
        """Close ticket via API (/api/v1/tickets/{ticket_id}/close) with Firestore fallback."""
        payload = {"close_reason": reason or "Closed from Discord"}
        await APIClient.post(f"tickets/{ticket_id}/close", json_data=payload)

        def _sync_close():
            db = cls._get_db()
            ticket_ref = db.collection(TICKETS_COLLECTION).document(ticket_id)
            ticket_ref.update({
                "status": TicketStatus.CLOSED.value,
                "closed_by": closed_by.to_dict(),
                "closed_by_uid": closed_by.uid or closed_by.discord_id,
                "close_reason": reason or "No reason provided",
                "closed_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            return True

        return await asyncio.to_thread(_sync_close)

    @classmethod
    async def list_active_tickets(cls, category: Optional[str] = None, limit: int = 50) -> List[Ticket]:
        """List active tickets (open or in_progress)."""
        def _sync_list():
            try:
                db = cls._get_db()
                query = db.collection(TICKETS_COLLECTION).where("status", "in", [TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value]).limit(limit)
                docs = list(query.stream())
                results = [Ticket.from_dict(d.id, d.to_dict()) for d in docs]
                if category:
                    results = [t for t in results if (t.category.value if isinstance(t.category, TicketCategory) else str(t.category)) == category]
                return results
            except Exception as e:
                print(f"[TicketManager] Error listing active tickets: {e}")
                return []

        return await asyncio.to_thread(_sync_list)

    @classmethod
    async def list_user_tickets(cls, discord_user_id: str, limit: int = 20) -> List[Ticket]:
        """List all tickets created by a specific Discord user."""
        def _sync_list_user():
            try:
                db = cls._get_db()
                query = db.collection(TICKETS_COLLECTION).where("created_by.discord_id", "==", str(discord_user_id)).limit(limit)
                docs = list(query.stream())
                return [Ticket.from_dict(d.id, d.to_dict()) for d in docs]
            except Exception as e:
                print(f"[TicketManager] Error listing user tickets: {e}")
                return []

        return await asyncio.to_thread(_sync_list_user)

