import os
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import server
from models.idea import Idea
from models.ticket import Ticket, TicketMessage, TicketUser
from utils.idea_manager import IdeaManager
from utils.ticket_manager import TicketManager


class FakeIdeaDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeIdeaQuery:
    def __init__(self, docs, predicate=lambda _data: True, limit=None):
        self.docs = docs
        self.predicate = predicate
        self.limit_count = limit

    def where(self, field, _operator, value):
        return FakeIdeaQuery(
            self.docs,
            lambda data: self.predicate(data) and data.get(field) == value,
            self.limit_count,
        )

    def limit(self, count):
        return FakeIdeaQuery(self.docs, self.predicate, count)

    def stream(self):
        matches = [doc for doc in self.docs if self.predicate(doc.to_dict())]
        return matches[: self.limit_count]


class FakeIdeaDB:
    def __init__(self, docs):
        self.query = FakeIdeaQuery(docs)

    def collection(self, _name):
        return self.query


class FakeMessageCollection:
    def __init__(self):
        self.requested_id = None
        self.saved = None
        self.direction = None

    def document(self, doc_id=None):
        self.requested_id = doc_id
        collection = self

        class Ref:
            id = doc_id or "auto-id"

            def get(self):
                return SimpleNamespace(exists=collection.saved is not None)

            def set(self, data):
                collection.saved = data

        return Ref()

    def order_by(self, _field, direction=None):
        self.direction = direction
        return self

    def limit(self, _count):
        return self

    def stream(self):
        return [
            FakeIdeaDoc("new", {"sender_uid": "u", "timestamp": 2}),
            FakeIdeaDoc("old", {"sender_uid": "u", "timestamp": 1}),
        ]


class FakeTicketRef:
    def __init__(self):
        self.messages = FakeMessageCollection()

    def collection(self, _name):
        return self.messages

    def update(self, _updates):
        pass


class FakeTicketDB:
    def __init__(self):
        self.ticket = FakeTicketRef()

    def collection(self, _name):
        db = self

        class Tickets:
            def document(self, _ticket_id):
                return db.ticket

        return Tickets()


class FakeThread:
    def __init__(self):
        self.id = 333
        self.add_user = AsyncMock()
        self.send = AsyncMock(return_value=SimpleNamespace(id=444))


class FakeChannel:
    def __init__(self):
        self.id = 222
        self.thread = FakeThread()
        self.threads = []
        self.create_thread = AsyncMock(return_value=self.thread)


class FakeGuild:
    def __init__(self):
        self.id = 111
        self.channel = FakeChannel()
        self.member = SimpleNamespace(id=555, mention="<@555>")
        self.roles = []
        self.icon = None

    def get_channel(self, channel_id):
        return self.channel if channel_id == self.channel.id else None

    def get_member(self, member_id):
        return self.member if member_id == self.member.id else None


class FakeBot:
    def __init__(self, guild):
        self.guild = guild
        self.guilds = [guild]
        self.relay_thread = guild.channel.thread

    def is_ready(self):
        return True

    def get_guild(self, guild_id):
        return self.guild if guild_id == self.guild.id else None

    def get_channel(self, channel_id):
        return self.relay_thread if channel_id == self.relay_thread.id else None


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.guild = FakeGuild()
        self.bot = FakeBot(self.guild)
        self.client = TestClient(server.app)
        self.env = patch.dict(
            os.environ,
            {
                "BOT_INTERNAL_SECRET": "bridge-secret",
                "GUILD_ID": "111",
                "TICKETS_CHANNEL_ID": "222",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_bridge_routes_require_secret(self):
        create = self.client.post(
            "/tickets/create-thread",
            json={
                "ticket_id": "tkt-1",
                "category": "support",
                "title": "Help",
                "creator_uid": "uid-1",
            },
        )
        relay = self.client.post(
            "/tickets/relay-message",
            json={
                "ticket_id": "tkt-1",
                "thread_id": "333",
                "sender_uid": "uid-1",
                "content": "Hello",
            },
        )
        self.assertEqual((create.status_code, relay.status_code), (401, 401))

    def test_create_thread_adds_member_and_persists_metadata(self):
        with (
            patch.object(server, "bot", self.bot),
            patch.object(server, "user_discord_id", AsyncMock(return_value="555")),
            patch.object(
                server.TicketManager,
                "reserve_thread_creation",
                AsyncMock(return_value={"status": "reserved"}),
            ),
            patch.object(server.TicketManager, "update_ticket", AsyncMock()) as update,
        ):
            response = self.client.post(
                "/tickets/create-thread",
                headers={"X-Internal-Secret": "bridge-secret"},
                json={
                    "ticket_id": "tkt-1",
                    "category": "support",
                    "title": "Help",
                    "creator_uid": "uid-1",
                    "fields": {"topic": "Auth"},
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["discord_meta"]["thread_id"], "333")
        self.guild.channel.thread.add_user.assert_awaited_once_with(self.guild.member)
        self.assertEqual(update.await_count, 2)

    def test_create_thread_retry_returns_existing_metadata(self):
        with patch.object(
            server.TicketManager,
            "reserve_thread_creation",
            AsyncMock(
                return_value={
                    "status": "existing",
                    "discord_meta": {
                        "guild_id": "111",
                        "channel_id": "222",
                        "thread_id": "333",
                    },
                }
            ),
        ):
            response = self.client.post(
                "/tickets/create-thread",
                headers={"X-Internal-Secret": "bridge-secret"},
                json={
                    "ticket_id": "tkt-1",
                    "category": "support",
                    "title": "Help",
                    "creator_uid": "uid-1",
                },
            )
        self.assertTrue(response.json()["existing"])

    def test_incomplete_thread_setup_is_resumed(self):
        with (
            patch.object(server, "bot", self.bot),
            patch.object(server, "user_discord_id", AsyncMock(return_value="555")),
            patch.object(
                server.TicketManager,
                "reserve_thread_creation",
                AsyncMock(
                    return_value={
                        "status": "resume",
                        "discord_meta": {
                            "guild_id": "111",
                            "channel_id": "222",
                            "thread_id": "333",
                        },
                    }
                ),
            ),
            patch.object(server.TicketManager, "update_ticket", AsyncMock()) as update,
        ):
            response = self.client.post(
                "/tickets/create-thread",
                headers={"X-Internal-Secret": "bridge-secret"},
                json={
                    "ticket_id": "tkt-1",
                    "category": "support",
                    "title": "Help",
                    "creator_uid": "uid-1",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.guild.channel.create_thread.assert_not_awaited()
        self.guild.channel.thread.add_user.assert_awaited_once()
        self.assertEqual(update.await_count, 2)

    def test_relay_validates_link_and_sends_message(self):
        ticket = SimpleNamespace(thread_id="333", discord_meta=None)
        with (
            patch.object(server, "bot", self.bot),
            patch.object(
                server.TicketManager, "get_ticket", AsyncMock(return_value=ticket)
            ),
        ):
            response = self.client.post(
                "/tickets/relay-message",
                headers={"X-Internal-Secret": "bridge-secret"},
                json={
                    "ticket_id": "tkt-1",
                    "thread_id": "333",
                    "sender_uid": "uid-1",
                    "content": "Hello",
                    "attachments": ["https://example.test/file"],
                },
            )
        self.assertEqual(response.status_code, 200)
        sent = self.guild.channel.thread.send.await_args.args[0]
        self.assertIn("Hello", sent)
        self.assertIn("https://example.test/file", sent)


class IdeaContractTests(unittest.TestCase):
    def test_idea_dual_writes_dashboard_contract(self):
        idea = Idea(
            title="Idea",
            description="Description",
            track="other",
            roadmap=["Step one"],
            is_approved=True,
            created_by_uid="uid-1",
            created_by=TicketUser(discord_id="555", username="Member"),
        )
        data = idea.to_dict()
        self.assertTrue(data["is_verified"])
        self.assertEqual(data["rough_roadmap"], ["Step one"])
        self.assertEqual(data["created_by_uid"], "uid-1")

    def test_idea_reads_dashboard_contract(self):
        idea = Idea.from_dict(
            "idea-1",
            {
                "title": "Idea",
                "description": "Description",
                "track": "misc",
                "rough_roadmap": ["Step one"],
                "is_verified": True,
                "created_by_uid": "uid-1",
            },
        )
        self.assertTrue(idea.is_approved)
        self.assertEqual(idea.roadmap, ["Step one"])
        self.assertEqual(idea.track, "other")

    def test_idea_normalizes_optional_dashboard_display_fields(self):
        idea = Idea.from_dict(
            "idea-1", {"title": "Idea", "track": None, "difficulty": None}
        )
        self.assertEqual(idea.track, "other")
        self.assertEqual(idea.difficulty, "intermediate")

    def test_manager_unions_canonical_and_legacy_approval_fields(self):
        db = FakeIdeaDB(
            [
                FakeIdeaDoc(
                    "canonical", {"title": "A", "track": "misc", "is_verified": True}
                ),
                FakeIdeaDoc(
                    "legacy", {"title": "B", "track": "other", "is_approved": True}
                ),
            ]
        )
        with patch.object(IdeaManager, "_get_db", return_value=db):
            ideas = asyncio.run(IdeaManager.list_ideas(track="other"))
        self.assertEqual({idea.id for idea in ideas}, {"canonical", "legacy"})


class TicketContractTests(unittest.TestCase):
    def test_dashboard_identity_fields_are_read(self):
        ticket = Ticket.from_dict(
            "ticket-1", {"created_by_uid": "uid-1", "category": "feedback"}
        )
        message = TicketMessage.from_dict(
            "message-1", {"sender_uid": "uid-2", "content": "Hello"}
        )
        self.assertEqual(ticket.created_by_uid, "uid-1")
        self.assertEqual(ticket.category.value, "feedback")
        self.assertEqual(message.sender_id, "uid-2")

    def test_discord_messages_are_idempotent_and_latest_window_is_chronological(self):
        db = FakeTicketDB()
        message = TicketMessage(
            sender_id="discord-user",
            sender_name="Member",
            content="Hello",
            discord_message_id="987654321",
        )
        with patch.object(TicketManager, "_get_db", return_value=db):
            message_id = asyncio.run(
                TicketManager.add_ticket_message("ticket-1", message)
            )
            original = dict(db.ticket.messages.saved)
            message.content = "Changed replay"
            asyncio.run(TicketManager.add_ticket_message("ticket-1", message))
            messages = asyncio.run(TicketManager.get_ticket_messages("ticket-1"))
        self.assertEqual(message_id, "987654321")
        self.assertEqual(db.ticket.messages.requested_id, "987654321")
        self.assertEqual(db.ticket.messages.saved, original)
        self.assertEqual([item.id for item in messages], ["old", "new"])


if __name__ == "__main__":
    unittest.main()
