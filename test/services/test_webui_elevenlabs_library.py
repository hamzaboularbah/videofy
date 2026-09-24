from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import elevenlabs_voices as catalog
from app.services import voice

MAIN = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def widget(elements, key):
    return next(
        x for x in elements if str(x.key) == key or str(x.key).startswith(key + "_")
    )


def actor(voice_id, name):
    return {
        "voice_id": voice_id,
        "name": name,
        "public_owner_id": "owner",
        "language": "en",
        "preview_url": "https://example.com/sample.mp3",
    }


def test_browse_search_load_more_and_add_preserve_active_voice_until_confirmed():
    ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="elevenlabs",
        voice_name="elevenlabs:saved:Saved",
    )
    with (
        patch.object(config, "ui", ui),
        patch.object(config, "elevenlabs", dict(config.elevenlabs, api_key="test-key")),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice, "get_elevenlabs_voices", return_value=["elevenlabs:saved:Saved"]
        ) as account,
        patch.object(
            catalog,
            "search_library",
            side_effect=[
                {
                    "voices": [actor("one", "Same name")],
                    "has_more": True,
                    "total_count": 2,
                },
                {
                    "voices": [actor("one", "Same name"), actor("two", "Same name")],
                    "has_more": False,
                    "total_count": 2,
                },
                {
                    "voices": [actor("three", "Energetic")],
                    "has_more": False,
                    "total_count": 1,
                },
            ],
        ) as search,
        patch.object(
            catalog, "add_library_voice", return_value="elevenlabs:copy:Energetic"
        ) as add,
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()
        assert not app.exception
        search.assert_not_called()
        widget(app.checkbox, "elevenlabs_browse_library").check().run()
        assert not app.exception
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
        add.assert_not_called()
        widget(app.button, "elevenlabs_library_more").click().run()
        assert not app.exception
        actors = widget(app.selectbox, "elevenlabs_library_actor")
        assert len(actors.options) == 2
        assert actors.options[0] != actors.options[1]
        assert search.call_args.kwargs["page"] == 1
        widget(app.text_input, "elevenlabs_library_query").set_value("energetic")
        next(b for b in app.button if b.label == "Search Voice Library").click().run()
        assert search.call_args.kwargs["page"] == 0
        assert search.call_args.kwargs["search"] == "energetic"
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
        widget(app.button, "elevenlabs_library_use").click().run()
        assert not app.exception
        add.assert_called_once()
        assert (
            widget(app.selectbox, "speech_synthesis_select_elevenlabs").value
            == "elevenlabs:copy:Energetic"
        )
        assert ui["voice_name"] == "elevenlabs:copy:Energetic"
        app.run()
        assert ui["voice_name"] == "elevenlabs:copy:Energetic"
        widget(app.checkbox, "elevenlabs_browse_library").uncheck().run()
        widget(app.checkbox, "elevenlabs_browse_library").check().run()
        assert widget(app.text_input, "elevenlabs_library_query").value == "energetic"
        assert account.call_count == 1
        assert search.call_count == 3


def test_refresh_failure_keeps_selection_and_retries():
    ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="elevenlabs",
        voice_name="elevenlabs:saved:Saved",
    )
    with (
        patch.object(config, "ui", ui),
        patch.object(config, "elevenlabs", dict(config.elevenlabs, api_key="test-key")),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_elevenlabs_voices",
            side_effect=[
                ["elevenlabs:saved:Saved"],
                catalog.VoiceCatalogError("Please retry."),
                ["elevenlabs:saved:Saved", "elevenlabs:new:New"],
            ],
        ) as account,
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()
        widget(app.button, "elevenlabs_refresh_voices").click().run()
        assert not app.exception
        assert any("retry" in item.value for item in app.error)
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
        widget(app.button, "elevenlabs_refresh_voices").click().run()
        assert (
            len(widget(app.selectbox, "speech_synthesis_select_elevenlabs").options)
            == 2
        )
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
        assert account.call_count == 3


def test_failed_add_does_not_change_active_voice_or_repeat_automatically():
    ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="elevenlabs",
        voice_name="elevenlabs:saved:Saved",
    )
    with (
        patch.object(config, "ui", ui),
        patch.object(config, "elevenlabs", dict(config.elevenlabs, api_key="test-key")),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice, "get_elevenlabs_voices", return_value=["elevenlabs:saved:Saved"]
        ),
        patch.object(
            catalog,
            "search_library",
            return_value={
                "voices": [actor("new", "New")],
                "has_more": False,
                "total_count": 1,
            },
        ),
        patch.object(
            catalog,
            "add_library_voice",
            side_effect=catalog.VoiceCatalogError("Check your plan."),
        ) as add,
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()
        widget(app.checkbox, "elevenlabs_browse_library").check().run()
        widget(app.button, "elevenlabs_library_use").click().run()
        assert not app.exception
        assert any("plan" in item.value for item in app.error)
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
        app.run()
        add.assert_called_once()
        assert ui["voice_name"] == "elevenlabs:saved:Saved"
