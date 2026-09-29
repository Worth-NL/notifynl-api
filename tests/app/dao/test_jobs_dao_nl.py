from freezegun import freeze_time

from app.dao.jobs_dao import dao_cancel_letter_job
from tests.app.db import create_job, create_notification


@freeze_time("2019-06-13 13:00")
def test_dao_cancel_letter_job_leaves_letters_already_handed_to_print_provider(sample_letter_template):
    # can_letter_job_be_cancelled passed, but one letter was claimed for sending before the job was cancelled
    job = create_job(template=sample_letter_template, notification_count=3, job_status="finished")
    created = create_notification(template=job.template, job=job, status="created")
    pending = create_notification(template=job.template, job=job, status="pending-virus-check")
    sending = create_notification(template=job.template, job=job, status="sending")

    result = dao_cancel_letter_job(job)

    assert result == 2
    assert created.status == "cancelled"
    assert pending.status == "cancelled"
    assert sending.status == "sending"
    assert job.job_status == "cancelled"
