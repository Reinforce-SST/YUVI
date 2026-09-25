"""Asynchronous API Client for YUVI Discord Bot.

Handles all communication with the FastAPI Backend Server (/api/v1/*),
attaching internal authentication headers automatically.
"""

import os
from typing import Any, Dict, Optional
import aiohttp


class APIClient:
    """Async client to communicate with the Reinforce Dashboard API."""

    @staticmethod
    def _base_url() -> str:
        url = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
        return url

    @staticmethod
    def _headers() -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        secret = os.getenv("BOT_INTERNAL_SECRET", "")
        if secret:
            headers["X-Internal-Secret"] = secret
        return headers

    @classmethod
    async def get(
        cls, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Perform an authenticated GET request."""
        clean_endpoint = endpoint.lstrip("/")
        url = f"{cls._base_url()}/{clean_endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=cls._headers(), params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        return None
                    else:
                        text = await resp.text()
                        print(f"[APIClient] GET {url} returned status {resp.status}: {text}")
                        return None
        except Exception as e:
            print(f"[APIClient] GET {url} failed: {e}")
            return None

    @classmethod
    async def post(
        cls, endpoint: str, json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Perform an authenticated POST request."""
        clean_endpoint = endpoint.lstrip("/")
        url = f"{cls._base_url()}/{clean_endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=cls._headers(), json=json_data, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    else:
                        text = await resp.text()
                        print(f"[APIClient] POST {url} returned status {resp.status}: {text}")
                        return None
        except Exception as e:
            print(f"[APIClient] POST {url} failed: {e}")
            return None

    @classmethod
    async def patch(
        cls, endpoint: str, json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Perform an authenticated PATCH request."""
        clean_endpoint = endpoint.lstrip("/")
        url = f"{cls._base_url()}/{clean_endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url, headers=cls._headers(), json=json_data, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        print(f"[APIClient] PATCH {url} returned status {resp.status}: {text}")
                        return None
        except Exception as e:
            print(f"[APIClient] PATCH {url} failed: {e}")
            return None

    @classmethod
    async def delete(cls, endpoint: str) -> bool:
        """Perform an authenticated DELETE request."""
        clean_endpoint = endpoint.lstrip("/")
        url = f"{cls._base_url()}/{clean_endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url, headers=cls._headers(), timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status in (200, 204)
        except Exception as e:
            print(f"[APIClient] DELETE {url} failed: {e}")
            return False
