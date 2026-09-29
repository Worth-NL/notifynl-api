from app.config import Config, build_letter_beat_schedule

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
