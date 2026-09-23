"""One-time proof that the link recipient controls a Discord account."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit
from fastapi import HTTPException


def issue_link(db, discord_id, frontend_url, now=None):
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.collection('discord_link_tokens').document(sha256(token.encode()).hexdigest()).create({
        'discord_id': str(discord_id),
        'issued_at': now,
        'expires_at': now + timedelta(minutes=10),
        'consumed_by': None,
    })
    url = urlsplit(frontend_url)
    return urlunsplit((url.scheme, url.netloc, url.path, '', urlencode({'link_token': token})))


def require_verified_link(db, discord_id, email):
    email = email.lower().strip()
    alias = db.collection('users').document(discord_id).get().to_dict() or {}
    primary = db.collection('users').document(email).get().to_dict() or {}
    for record in (alias, primary):
        if (record.get('email') != email or str(record.get('discord_id')) != discord_id
                or record.get('discord_link_version') != 1):
            raise HTTPException(403, 'A verified Discord link is required.')
