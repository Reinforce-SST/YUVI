import importlib
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

class VerificationWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Firebase and the Discord gateway are external; never connect in tests.
        with patch('utils.firestore_client.get_firestore_client', return_value=MagicMock()):
            self.server = importlib.import_module('server')
    async def test_missing_secret_fails_closed(self):
        with patch.dict(os.environ, {'BOT_INTERNAL_SECRET': ''}):
            with self.assertRaises(HTTPException) as error:
                await self.server.verify_success(self.server.VerifySuccessRequest(discord_id='123456', email='member@sst.scaler.com'), None)
        self.assertEqual(error.exception.status_code, 503)
    async def test_wrong_secret_is_rejected_before_database_or_discord(self):
        with patch.dict(os.environ, {'BOT_INTERNAL_SECRET': 'expected'}), patch.object(self.server, 'get_firestore_client', side_effect=AssertionError('must not access db')):
            with self.assertRaises(HTTPException) as error:
                await self.server.verify_success(self.server.VerifySuccessRequest(discord_id='123456', email='member@sst.scaler.com'), 'wrong')
        self.assertEqual(error.exception.status_code, 401)
    async def test_existing_role_retry_does_not_send_another_dm(self):
        role = MagicMock(); role.name = 'Verified Member'
        member = MagicMock(); member.roles = [role]; member.send = AsyncMock(); member.add_roles = AsyncMock()
        guild = MagicMock(); guild.get_member.return_value = member; guild.fetch_member = AsyncMock(return_value=member); guild.get_role.return_value = role
        bot = MagicMock(); bot.is_ready.return_value = True; bot.get_guild.return_value = guild
        with patch.dict(os.environ, {'BOT_INTERNAL_SECRET': 'expected', 'GUILD_ID': '123456', 'VERIFIED_ROLE_ID': '456789'}), patch.object(self.server, 'bot', bot), patch.object(self.server, 'get_firestore_client'), patch.object(self.server, 'require_verified_link'):
            result = await self.server.verify_success(self.server.VerifySuccessRequest(discord_id='123456', email='member@sst.scaler.com'), 'expected')
        self.assertTrue(result['role_assigned'])
        member.send.assert_not_awaited()
        member.add_roles.assert_not_awaited()

    async def test_overlapping_retries_grant_and_welcome_only_once(self):
        role = MagicMock(); role.name = 'Verified Member'
        assigned = False
        send = AsyncMock()

        async def grant(*args, **kwargs):
            nonlocal assigned
            await asyncio.sleep(0.01)
            assigned = True

        add_roles = AsyncMock(side_effect=grant)

        def snapshot():
            member = MagicMock()
            member.roles = [role] if assigned else []
            member.send, member.add_roles = send, add_roles
            return member

        guild = MagicMock(); guild.id = 123456
        # The gateway cache may lag behind the REST role update.
        guild.get_member.return_value = snapshot()
        guild.fetch_member = AsyncMock(side_effect=lambda *_: snapshot())
        guild.get_role.return_value = role
        bot = MagicMock(); bot.is_ready.return_value = True; bot.get_guild.return_value = guild
        payload = self.server.VerifySuccessRequest(discord_id='123456', email='member@sst.scaler.com')
        with patch.dict(os.environ, {'BOT_INTERNAL_SECRET': 'expected', 'GUILD_ID': '123456', 'VERIFIED_ROLE_ID': '456789'}), patch.object(self.server, 'bot', bot), patch.object(self.server, 'get_firestore_client'), patch.object(self.server, 'require_verified_link'):
            results = await asyncio.gather(*(self.server.verify_success(payload, 'expected') for _ in range(3)))
        self.assertTrue(all(result['role_assigned'] for result in results))
        add_roles.assert_awaited_once()
        send.assert_awaited_once()
