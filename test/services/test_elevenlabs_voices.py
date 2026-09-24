from unittest.mock import Mock, patch

import pytest

from app.services import elevenlabs_voices as catalog
from app.services import voice


def response(data=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    result.text = "private-provider-payload"
    return result


def test_account_pagination_includes_non_favorites_and_deduplicates():
    with patch.object(
        catalog.requests,
        "get",
        side_effect=[
            response(
                {
                    "voices": [{"voice_id": "b", "name": "Bob"}],
                    "has_more": True,
                    "next_page_token": "page2",
                }
            ),
            response(
                {
                    "voices": [
                        {"voice_id": "a", "name": "Alice"},
                        {"voice_id": "b", "name": "Bob"},
                        {"voice_id": "x", "name": "Disabled", "status": "disabled"},
                        {"name": "Missing ID"},
                    ],
                    "has_more": False,
                }
            ),
        ],
    ) as get:
        assert voice.get_elevenlabs_voices("secret", raise_errors=True) == [
            "elevenlabs:a:Alice",
            "elevenlabs:b:Bob",
        ]
    assert get.call_count == 2
    assert "is_favorite" not in get.call_args_list[0].kwargs["params"]
    assert get.call_args_list[1].kwargs["params"]["next_page_token"] == "page2"


@pytest.mark.parametrize("token", [None, "loop"])
def test_incomplete_pagination_never_returns_a_truncated_list(token):
    with patch.object(
        catalog.requests,
        "get",
        side_effect=[
            response({"voices": [], "has_more": True, "next_page_token": "loop"}),
            response({"voices": [], "has_more": True, "next_page_token": token}),
        ],
    ):
        with pytest.raises(catalog.VoiceCatalogError, match="pagination"):
            catalog.list_account_voices("secret")


def test_failed_later_page_is_not_reported_as_complete():
    with patch.object(
        catalog.requests,
        "get",
        side_effect=[
            response(
                {
                    "voices": [{"voice_id": "a", "name": "Alice"}],
                    "has_more": True,
                    "next_page_token": "p2",
                }
            ),
            response(status=429),
        ],
    ):
        with pytest.raises(catalog.VoiceCatalogError, match="429"):
            voice.get_elevenlabs_voices("secret", raise_errors=True)


def test_library_search_passes_filters_and_preserves_pagination():
    payload = {
        "voices": [
            {
                "voice_id": "b",
                "name": "Bob",
                "preview_url": "https://example.com/sample.mp3",
            }
        ],
        "has_more": True,
        "total_count": 234,
    }
    with patch.object(catalog.requests, "get", return_value=response(payload)) as get:
        assert (
            catalog.search_library(
                "secret", search=" energetic ", language="en", gender="male", page=2
            )
            == payload
        )
    assert get.call_args.args[0].endswith("/v1/shared-voices")
    assert get.call_args.kwargs["params"] == {
        "page_size": 100,
        "page": 2,
        "sort": "trending",
        "search": "energetic",
        "language": "en",
        "gender": "male",
    }


def test_adding_library_voice_uses_returned_account_id():
    with patch.object(
        catalog.requests, "post", return_value=response({"voice_id": "account-copy"})
    ) as post:
        assert (
            catalog.add_library_voice(
                "secret",
                {
                    "voice_id": "library-id",
                    "public_owner_id": "owner",
                    "name": "Adam: energetic",
                },
            )
            == "elevenlabs:account-copy:Adam: energetic"
        )
    assert post.call_args.args[0].endswith("/v1/voices/add/owner/library-id")
    assert post.call_args.kwargs["json"] == {"new_name": "Adam: energetic"}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_errors_do_not_expose_credentials_or_response_bodies(status):
    with patch.object(catalog.requests, "get", return_value=response(status=status)):
        with pytest.raises(catalog.VoiceCatalogError) as error:
            catalog.search_library("secret-key")
    assert "secret-key" not in str(error.value)
    assert "private-provider-payload" not in str(error.value)


def test_invalid_library_response_is_recoverable():
    with patch.object(catalog.requests, "get", return_value=response({"voices": None})):
        with pytest.raises(catalog.VoiceCatalogError):
            catalog.search_library("secret")
