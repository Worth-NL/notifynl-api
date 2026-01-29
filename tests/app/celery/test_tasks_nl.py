import uuid
from unittest.mock import MagicMock

import pytest

from app import signing
from app.celery.letters_pdf_tasks import get_pdf_for_templated_letter
from app.celery.tasks import (
    save_letter,
)
from app.constants import (
    LETTER_TYPE,
)
from app.models import Notification
from tests.app.db import (
    create_job,
    create_letter_contact,
    create_service,
    create_template,
)


@pytest.fixture
def mock_celery_task_nl(mocker):
    def celery_mocker(celery_task):
        mock_apply = MagicMock()
        # if you want, add type checking here
        # but don't call the real task or do any I/O
        mocker.patch.object(celery_task, "apply_async", mock_apply)
        return mock_apply

    return celery_mocker


def _notification_json(template, to, personalisation=None, job_id=None, row_number=0, client_reference=None):
    return {
        "template": str(template.id),
        "template_version": template.version,
        "to": to,
        "notification_type": template.template_type,
        "personalisation": personalisation or {},
        "job": job_id and str(job_id),
        "row_number": row_number,
        "client_reference": client_reference,
    }


@pytest.mark.parametrize(
    "personalisation, expected_to, expected_normalised, client_reference",
    [
        # Standard: postcode + city on separate lines
        (
            {"addressline1": "Foo", "addressline2": "1012NX", "addressline3": "Amsterdam"},
            "Foo\n1012 NX Amsterdam",
            "foo1012nxamsterdam",
            None,
        ),
        # Country included in last line, should be removed
        (
            {"addressline1": "Foo", "addressline2": "1012NX Amsterdam", "addressline3": "Netherlands"},
            "Foo\n1012 NX Amsterdam",
            "foo1012nxamsterdam",
            None,
        ),
        # Postcode + city combined in one line
        (
            {"addressline1": "Bar", "addressline2": "2000AB Rotterdam"},
            "Bar\n2000 AB Rotterdam",  # combine last line logic: postcode + first line of last line
            "bar2000abrotterdam",
            None,
        ),
        # Postcode + city on separate lines with extra empty line
        (
            {"addressline1": "Baz", "addressline2": "", "addressline3": "3011CD", "addressline4": "Utrecht"},
            "Baz\n3011 CD Utrecht",
            "baz3011cdutrecht",
            None,
        ),
        # Only postcode provided, no city
        (
            {"addressline1": "Qux", "addressline2": "4000EF"},
            "4000 EF Qux",
            "4000efqux",
            None,
        ),
        # Country present alone, should be ignored
        (
            {"addressline1": "Foo", "addressline2": "Netherlands"},
            "Foo",
            "foo",
            None,
        ),
    ],
)
def test_save_letter_saves_letter_to_database(
    mocker,
    mock_celery_task_nl,
    notify_db_session,
    personalisation,
    expected_to,
    expected_normalised,
    client_reference,
):
    service = create_service()
    contact_block = create_letter_contact(service=service, contact_block="Address contact", is_default=True)
    template = create_template(service=service, template_type=LETTER_TYPE, reply_to=contact_block.id)
    job = create_job(template=template)

    mocker.patch("app.celery.tasks.create_random_identifier", return_value="this-is-random-in-real-life")
    mock_celery_task_nl(get_pdf_for_templated_letter)

    notification_json = _notification_json(
        template=job.template,
        to="ignored",
        personalisation=personalisation,
        job_id=job.id,
        row_number=1,
        client_reference=client_reference,
    )
    notification_id = uuid.uuid4()

    save_letter(job.service_id, notification_id, signing.encode(notification_json))

    notification_db = Notification.query.one()

    assert notification_db.to == expected_to
    assert notification_db.normalised_to == expected_normalised
    assert notification_db.client_reference == client_reference


@pytest.mark.parametrize(
    "last_line_of_address, postage, expected_postage, expected_international",
    [
        # Domestic NL addresses
        ("1012 NX Amsterdam", "europe", "europe", False),
        ("2000 AB Rotterdam", "europe", "europe", False),
        ("3011 CD Utrecht", "europe", "europe", False),
        # International addresses (country included in last line)
        ("New Zealand", "second", "rest-of-world", True),
        ("France", "first", "europe", True),
    ],
)
def test_save_letter_saves_letter_to_database_with_correct_postage_nl(
    mocker,
    mock_celery_task_nl,
    notify_db_session,
    last_line_of_address,
    postage,
    expected_postage,
    expected_international,
):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service=service, template_type=LETTER_TYPE, postage=postage)
    letter_job = create_job(template=template)

    mock_celery_task_nl(get_pdf_for_templated_letter)
    notification_json = _notification_json(
        template=letter_job.template,
        to="ignored",
        personalisation={
            "addressline1": "Foo",
            "addressline2": last_line_of_address if " " in last_line_of_address else "Bar",
            "addressline3": last_line_of_address if " " not in last_line_of_address else None,
        },
        job_id=letter_job.id,
        row_number=1,
    )
    notification_id = uuid.uuid4()
    save_letter(
        letter_job.service_id,
        notification_id,
        signing.encode(notification_json),
    )

    notification_db = Notification.query.one()
    assert notification_db.id == notification_id
    assert notification_db.postage == expected_postage
    assert notification_db.international == expected_international


def test_save_letter_saves_letter_to_database_with_uppercased_postcode(mocker, mock_celery_task, notify_db_session):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service=service, template_type=LETTER_TYPE)
    letter_job = create_job(template=template)

    mock_celery_task(get_pdf_for_templated_letter)

    notification_json = _notification_json(
        template=template,
        to="Foo",
        personalisation={
            "addressline1": "Foo",
            "addressline2": "Bar",
            "postcode": "se1 64sa",
        },
        job_id=letter_job.id,
        row_number=1,
    )

    notification_id = uuid.uuid4()

    save_letter(
        letter_job.service_id,
        notification_id,
        signing.encode(notification_json),
    )

    notification_db = Notification.query.one()

    assert notification_db.id == notification_id
    assert notification_db.personalisation["postcode"] == "SE1 64SA"
