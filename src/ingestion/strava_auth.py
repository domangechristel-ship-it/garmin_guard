"""
strava_auth.py
--------------
Retrieve a valid Strava access token using the refresh-token OAuth2 flow.
Credentials are read from environment variables (never hardcoded).
"""

import os
import requests


STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def get_access_token() -> str:
    """Exchange the stored refresh token for a fresh Strava access token."""
    payload = {
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }
    response = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=10)
    response.raise_for_status()
    return response.json()["access_token"]
