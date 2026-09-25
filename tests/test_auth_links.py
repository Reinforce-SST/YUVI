import unittest
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit, parse_qs
from unittest.mock import MagicMock
from utils.auth_links import issue_link, require_verified_link
from fastapi import HTTPException

class AuthLinkTests(unittest.TestCase):
    def test_private_token_is_hashed_short_lived_and_only_in_fragment(self):
        db = MagicMock()
        now = datetime(2026, 9, 24, tzinfo=timezone.utc)
        url = issue_link(db, '123456789012345678', 'https://club.example/auth', now)
        parsed = urlsplit(url)
        token = parse_qs(parsed.fragment)['link_token'][0]
        self.assertEqual(parsed.query, '')
        self.assertGreaterEqual(len(token), 43)
        db.collection.assert_called_once_with('discord_link_tokens')
        db.collection.return_value.document.assert_called_once_with(sha256(token.encode()).hexdigest())
        data = db.collection.return_value.document.return_value.create.call_args.args[0]
        self.assertEqual(data['discord_id'], '123456789012345678')
        self.assertEqual((data['expires_at'] - now).total_seconds(), 600)
        self.assertNotIn(token, repr(data))
    def test_webhook_rejects_unproven_link(self):
        db = MagicMock()
        db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {'email': 'member@sst.scaler.com', 'discord_id': '123'}
        with self.assertRaises(HTTPException): require_verified_link(db, '123', 'member@sst.scaler.com')
    def test_webhook_requires_both_records_to_agree(self):
        db = MagicMock()
        alias = {'email': 'member@sst.scaler.com', 'discord_id': '123', 'discord_link_version': 1}
        primary = {**alias, 'discord_id': '456'}
        db.collection.return_value.document.return_value.get.return_value.to_dict.side_effect = [alias, primary]
        with self.assertRaises(HTTPException): require_verified_link(db, '123', 'member@sst.scaler.com')
