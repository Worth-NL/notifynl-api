import importlib.util

import pytest

import app.config
from app.config import Config, build_letter_beat_schedule

PINGEN_ENV_VARS = (
    "PINGEN_API_URL",
    "PINGEN_IDENTITY_URL",
    "PINGEN_CLIENT_ID",
    "PINGEN_CLIENT_SECRET",
    "PINGEN_ORGANISATION_ID",
)

DVLA_TASKS = {
    "check-time-to-collate-letters",
    "change-dvla-api-key",
    "change-dvla-password",
    "raise-alert-if-letter-notifications-still-sending",
}
PROVIDER_TASKS = {"dispatch-stranded-letters", "check-letters-stuck-sending"}


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
def config_without_pingen_env(monkeypatch):
    # config classes read the environment when app/config.py is imported (and pytest-dotenv loads .env), so evaluate
    # a fresh copy of the module with the Pingen variables unset, leaving app.config itself untouched
    for name in PINGEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("config_without_pingen_env", app.config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_development_sends_pingen_letters_to_the_local_stub(config_without_pingen_env):
    dev = config_without_pingen_env.DevNL

    assert dev.PINGEN_API_URL == "http://localhost:6300/pingen/api"
    assert dev.PINGEN_IDENTITY_URL == "http://localhost:6300/pingen/identity"
    assert dev.PINGEN_CLIENT_ID
    assert dev.PINGEN_CLIENT_SECRET
    assert dev.PINGEN_ORGANISATION_ID


def test_deployed_environments_default_to_pingen_staging(config_without_pingen_env):
    for config in (config_without_pingen_env.TestNL, config_without_pingen_env.AccNL):
        assert config.PINGEN_API_URL == "https://api-staging.pingen.com"
        assert config.PINGEN_IDENTITY_URL == "https://identity-staging.pingen.com"
