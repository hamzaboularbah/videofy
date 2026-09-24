"""ElevenLabs account voices and paginated public Voice Library access."""

from urllib.parse import quote

import requests

BASE_URL = "https://api.elevenlabs.io"


class VoiceCatalogError(RuntimeError):
    """A safe, user-facing catalog error without provider payloads or credentials."""


def _request(api_key, path, *, params=None, body=None):
    if not api_key:
        raise VoiceCatalogError("Enter an ElevenLabs API key first.")
    try:
        kwargs = {"headers": {"xi-api-key": api_key}, "timeout": (5, 20)}
        if body is None:
            response = requests.get(BASE_URL + path, params=params, **kwargs)
        else:
            response = requests.post(BASE_URL + path, json=body, **kwargs)
        if response.status_code != 200:
            hints = {
                401: "Check your ElevenLabs API key.",
                403: "Check your ElevenLabs key permissions and plan access.",
                429: "ElevenLabs is rate limiting requests. Try again shortly.",
            }
            raise VoiceCatalogError(
                hints.get(
                    response.status_code, "ElevenLabs could not complete the request."
                )
                + f" (HTTP {response.status_code})"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data
    except (requests.RequestException, ValueError) as exc:
        # Never include request headers, provider bodies or raw exception text.
        raise VoiceCatalogError(
            "Could not load ElevenLabs voices. Please retry."
        ) from exc


def _valid_voices(data):
    rows = data.get("voices")
    if not isinstance(rows, list):
        raise VoiceCatalogError(
            "ElevenLabs returned an invalid voice list. Please retry."
        )
    return [
        v
        for v in rows
        if isinstance(v, dict)
        and isinstance(v.get("voice_id"), str)
        and v["voice_id"]
        and isinstance(v.get("name"), str)
        and v["name"]
        and v.get("status") != "disabled"
    ]


def list_account_voices(api_key):
    """Fetch every account page, without the old favorites-only restriction."""
    voices = {}
    token = None
    seen_tokens = set()
    while True:
        params = {"page_size": 100, "include_total_count": "false"}
        if token:
            params["next_page_token"] = token
        data = _request(api_key, "/v2/voices", params=params)
        for item in _valid_voices(data):
            voices[item["voice_id"]] = item
        if not data.get("has_more"):
            break
        token = data.get("next_page_token")
        if not isinstance(token, str) or not token or token in seen_tokens:
            raise VoiceCatalogError(
                "ElevenLabs returned incomplete pagination. Please refresh voices."
            )
        seen_tokens.add(token)
    return sorted(
        voices.values(), key=lambda item: (item["name"].casefold(), item["voice_id"])
    )


def search_library(api_key, *, search="", language="", gender="", page=0):
    """One public-library page. Browsing does not add voices or generate audio."""
    if not isinstance(page, int) or page < 0:
        raise ValueError("page must be a non-negative integer")
    params = {"page_size": 100, "page": page, "sort": "trending"}
    for key, value in (("search", search), ("language", language), ("gender", gender)):
        if value.strip():
            params[key] = value.strip()
    data = _request(api_key, "/v1/shared-voices", params=params)
    return {
        "voices": _valid_voices(data),
        "has_more": bool(data.get("has_more")),
        "total_count": data.get("total_count", 0),
    }


def add_library_voice(api_key, item):
    """Add only the explicitly selected actor and use the returned account ID."""
    owner = item.get("public_owner_id")
    voice_id = item.get("voice_id")
    name = item.get("name")
    if not all(isinstance(v, str) and v for v in (owner, voice_id, name)):
        raise VoiceCatalogError("This voice cannot be added. Choose another actor.")
    data = _request(
        api_key,
        f"/v1/voices/add/{quote(owner, safe='')}/{quote(voice_id, safe='')}",
        body={"new_name": name},
    )
    added_id = data.get("voice_id")
    if not isinstance(added_id, str) or not added_id:
        raise VoiceCatalogError(
            "ElevenLabs did not confirm the added voice. Refresh voices before retrying."
        )
    return f"elevenlabs:{added_id}:{name}"
