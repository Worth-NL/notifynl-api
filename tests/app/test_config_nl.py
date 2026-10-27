import importlib.util

import bcrypt
import pytest

import app.config
from app.config import Config, build_letter_beat_schedule

STUBBED_ENV_VARS = (
    "MMG_URL",
    "FIRETEXT_URL",
    "SPRYNG_URL",
    "PINGEN_API_URL",
    "PINGEN_IDENTITY_URL",
    "PINGEN_CLIENT_ID",
    "PINGEN_CLIENT_SECRET",
    "PINGEN_ORGANISATION_ID",
    "LETTER_DELIVERY_VIA_PROVIDERS",
    "MMG_DELIVERY_STATUS_CALLBACK_ALLOWED_BASIC_AUTH_CREDENTIALS",
    "FIRETEXT_DELIVERY_STATUS_CALLBACK_ALLOWED_BASIC_AUTH_CREDENTIALS",
    "RESEARCH_MODE_SELF_CALLBACK_MMG_BASIC_AUTH_CREDENTIALS",
    "RESEARCH_MODE_SELF_CALLBACK_FIRETEXT_BASIC_AUTH_CREDENTIALS",
)

DVLA_TASKS = {
    "check-time-to-collate-letters",
    "change-dvla-api-key",
    "change-dvla-password",
    "raise-alert-if-letter-notifications-still-sending",
    "check-if-letters-in-technical-failure",
}
PROVIDER_TASKS = {
    "dispatch-stranded-letters",
    "check-letters-stuck-sending",
    "check-provider-letters-in-technical-failure",
}


def test_letter_beat_schedule_while_letters_go_through_dvla():
    schedule = build_letter_beat_schedule(Config.CELERY["beat_schedule"], False, "*/5")

    assert DVLA_TASKS <= set(schedule)
    assert not PROVIDER_TASKS & set(schedule)
    assert schedule["check-time-to-collate-letters"]["schedule"]._orig_minute == "*/5"


def test_letter_beat_schedule_when_letters_go_straight_to_print_providers():
    schedule = build_letter_beat_schedule(Config.CELERY["beat_schedule"], True, "*/5")

    assert PROVIDER_TASKS <= set(schedule)
    assert not DVLA_TASKS & set(schedule)
    assert schedule["dispatch-stranded-letters"]["task"] == "dispatch-stranded-letters"


def test_letter_beat_schedule_keeps_the_other_tasks():
    base = Config.CELERY["beat_schedule"]
    others = set(base) - DVLA_TASKS

    for delivery_via_providers in (True, False):
        assert others <= set(build_letter_beat_schedule(base, delivery_via_providers, "*/5"))


@pytest.fixture
def config_without_stub_env(monkeypatch):
    # config classes read the environment when app/config.py is imported (and pytest-dotenv loads .env), so evaluate
    # a fresh copy of the module with the stubbed variables unset, leaving app.config itself untouched
    for name in STUBBED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("config_without_stub_env", app.config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_development_sends_third_party_calls_to_the_local_stub(config_without_stub_env):
    dev = config_without_stub_env.DevNL

    assert dev.MMG_URL == "http://localhost:6300/mmg"
    assert dev.FIRETEXT_URL == "http://localhost:6300/firetext"
    assert dev.SPRYNG_URL == "http://localhost:6300/spryng"
    assert dev.PINGEN_API_URL == "http://localhost:6300/pingen/api"
    assert dev.PINGEN_IDENTITY_URL == "http://localhost:6300/pingen/identity"
    assert dev.PINGEN_CLIENT_ID
    assert dev.PINGEN_CLIENT_SECRET
    assert dev.PINGEN_ORGANISATION_ID


def test_local_development_accepts_the_local_stubs_sms_receipts(config_without_stub_env):
    dev = config_without_stub_env.DevNL

    for allowed, (username, password) in (
        (
            dev.MMG_DELIVERY_STATUS_CALLBACK_ALLOWED_BASIC_AUTH_CREDENTIALS,
            dev.RESEARCH_MODE_SELF_CALLBACK_MMG_BASIC_AUTH_CREDENTIALS,
        ),
        (
            dev.FIRETEXT_DELIVERY_STATUS_CALLBACK_ALLOWED_BASIC_AUTH_CREDENTIALS,
            dev.RESEARCH_MODE_SELF_CALLBACK_FIRETEXT_BASIC_AUTH_CREDENTIALS,
        ),
    ):
        assert (username, password) == ("notify", "testkey")
        assert bcrypt.checkpw(password.encode(), allowed[username].encode())


def test_local_development_delivers_letters_through_the_print_providers(config_without_stub_env):
    dev = config_without_stub_env.DevNL
    schedule = dev.CELERY["beat_schedule"]

    assert dev.LETTER_DELIVERY_VIA_PROVIDERS
    assert PROVIDER_TASKS <= set(schedule)
    assert not DVLA_TASKS & set(schedule)
    assert "messagebox-process-unprocessed" in schedule


def test_deployed_environments_keep_letters_on_the_dvla_path_by_default(config_without_stub_env):
    for config in (config_without_stub_env.TestNL, config_without_stub_env.AccNL, config_without_stub_env.ProdNL):
        assert not config.LETTER_DELIVERY_VIA_PROVIDERS
        assert DVLA_TASKS <= set(config.CELERY["beat_schedule"])


def test_deployed_environments_default_to_the_real_third_parties(config_without_stub_env):
    for config in (config_without_stub_env.TestNL, config_without_stub_env.AccNL):
        assert config.PINGEN_API_URL == "https://api-staging.pingen.com"
        assert config.PINGEN_IDENTITY_URL == "https://identity-staging.pingen.com"
        for url in (config.MMG_URL, config.FIRETEXT_URL, config.SPRYNG_URL):
            assert url.startswith("https://")
            assert "localhost" not in url
