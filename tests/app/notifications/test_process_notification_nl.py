import pytest

from app.constants import SMS_TYPE
from app.notifications.process_notifications import persist_notification


@pytest.mark.parametrize(
    "unformatted_recipient, normalised_recipient",
    [
        ("+31703456789", "31703456789"),  # Den Haag landline, national number starts with a UK S7 prefix
        ("+31612345678", "31612345678"),
    ],
)
def test_persist_notification_never_logs_ofcom_protected_range_for_dutch_numbers(
    notify_api,
    notify_db_session,
    mocker,
    sample_template,
    sample_api_key,
    sample_job,
    caplog,
    unformatted_recipient,
    normalised_recipient,
):
    caplog.set_level("INFO")
    mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=None)
    persist_notification(
        template_id=sample_template.id,
        template_version=sample_template.version,
        recipient={
            "unformatted_recipient": unformatted_recipient,
            "normalised_to": normalised_recipient,
            "international": False,
            "phone_prefix": "31",
            "rate_multiplier": 1,
        },
        service=sample_template.service,
        personalisation={},
        notification_type=SMS_TYPE,
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        job_row_number=100,
        reference="ref",
        reply_to_text=sample_template.service.get_default_sms_sender(),
    )

    assert not [r for r in caplog.records if "ofcom protected range" in r.message]
