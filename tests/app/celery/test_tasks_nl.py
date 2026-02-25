import uuid
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest
from freezegun import freeze_time
from notifications_utils.template import (
    LetterPrintTemplate,
)

from app import signing
from app.celery.letters_pdf_tasks import get_pdf_for_templated_letter
from app.celery.tasks import (
    get_recipient_csv_and_template_and_sender_id,
    process_job,
    save_letter,
    shatter_job_rows,
)
from app.constants import (
    LETTER_TYPE,
)
from app.dao import jobs_dao
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
            "Foo\n1012 NX  AMSTERDAM",
            "foo1012nxamsterdam",
            None,
        ),
        # Country included in last line, should be removed
        (
            {"addressline1": "Foo", "addressline2": "1012NX Amsterdam", "addressline3": "Netherlands"},
            "Foo\n1012 NX  AMSTERDAM",
            "foo1012nxamsterdam",
            None,
        ),
        # Postcode + city combined in one line
        (
            {"addressline1": "Bar", "addressline2": "2000AB Rotterdam"},
            "Bar\n2000 AB  ROTTERDAM",  # combine last line logic: postcode + first line of last line
            "bar2000abrotterdam",
            None,
        ),
        # Postcode + city on separate lines with extra empty line
        (
            {"addressline1": "Baz", "addressline2": "", "addressline3": "3011CD", "addressline4": "Utrecht"},
            "Baz\n3011 CD  UTRECHT",
            "baz3011cdutrecht",
            None,
        ),
        # Only postcode provided, no city
        (
            {"addressline1": "Name", "addressline2": "Streetname", "addressline3": "4000 EF"},
            "Name\nStreetname\n4000 EF",
            "namestreetname4000ef",
            None,
        ),
        # Country present alone, should be ignored
        (
            {"addressline1": "Foo", "addressline2": "Netherlands"},
            "Foo\nNetherlands",
            "foonetherlands",
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
        ("1012 NX Amsterdam", "netherlands", "netherlands", False),
        ("2000 AB Rotterdam", "netherlands", "netherlands", False),
        ("3011 CD Utrecht", "netherlands", "netherlands", False),
        # International addresses (country included in last line)
        ("New Zealand", "rest-of-world", "rest-of-world", True),
        ("France", "europe", "europe", True),
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


def test_save_letter_saves_letter_to_database_with_uppercased_postcode(mocker, mock_celery_task_nl, notify_db_session):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service=service, template_type=LETTER_TYPE)
    letter_job = create_job(template=template)

    mock_celery_task_nl(get_pdf_for_templated_letter)

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
    assert notification_db.personalisation["postcode"] == "se1 64sa"


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_process_letter_job(sample_letter_job, mocker, mock_celery_task_nl):
    csv = """address_line_1,address_line_2,address_line_3,address_line_4,postcode,name
    A1,A2,A3,A4,A_POST,Alice
    """
    s3_mock = mocker.patch(
        "app.celery.tasks.s3.get_job_and_metadata_from_s3",
        return_value=(csv, {"sender_id": None}),
    )
    mock_encode = mocker.patch("app.signing.encode", return_value="something_encoded")
    mock_shatter_job_rows = mock_celery_task_nl(shatter_job_rows)
    mocker.patch("app.celery.tasks.create_uuid", return_value="uuid")

    process_job(sample_letter_job.id)

    s3_mock.assert_called_once_with(service_id=str(sample_letter_job.service.id), job_id=str(sample_letter_job.id))

    assert mock_encode.mock_calls == [
        call(
            {
                "template": str(sample_letter_job.template.id),
                "template_version": sample_letter_job.template.version,
                "job": str(sample_letter_job.id),
                "to": ["A1", "A2", "A3", "A4", None, "A_POST", None],
                "row_number": 0,
                "personalisation": {
                    "addressline1": "A1",
                    "addressline2": "A2",
                    "addressline3": "A3",
                    "addressline4": "A4",
                    "postcode": "A_POST",
                },
                "client_reference": None,
            }
        )
    ]

    assert mock_shatter_job_rows.mock_calls == [
        call(
            (
                sample_letter_job.template.template_type,
                [
                    (
                        (
                            str(sample_letter_job.service_id),
                            "uuid",
                            "something_encoded",
                        ),
                        {},
                    )
                ],
            ),
            queue="job-tasks",
        )
    ]

    job = jobs_dao.dao_get_job_by_id(sample_letter_job.id)
    assert job.job_status == "finished"


def test_save_letter_saves_letter_to_database_right_reply_to(mocker, mock_celery_task_nl, notify_db_session):
    service = create_service()
    create_letter_contact(service=service, contact_block="Address contact", is_default=True)
    template = create_template(service=service, template_type=LETTER_TYPE, reply_to=None)
    job = create_job(template=template)

    mocker.patch(
        "app.celery.tasks.create_random_identifier",
        return_value="this-is-random-in-real-life",
    )
    mock_celery_task_nl(get_pdf_for_templated_letter)

    personalisation = {
        "addressline1": "Foo",
        "addressline2": "Bar",
        "addressline3": "Baz",
        "addressline4": "Wibble",
        "addressline5": "Wobble",
        "postcode": "SE1 3WS",
    }
    notification_json = _notification_json(
        template=job.template,
        to="Foo",
        personalisation=personalisation,
        job_id=job.id,
        row_number=1,
    )
    notification_id = uuid.uuid4()
    created_at = datetime.utcnow()

    save_letter(
        job.service_id,
        notification_id,
        signing.encode(notification_json),
    )

    notification_db = Notification.query.one()
    assert notification_db.id == notification_id
    assert notification_db.to == ("Foo\nBar\nBaz\nWibble\nWobble\nSE1 3WS")
    assert notification_db.job_id == job.id
    assert notification_db.template_id == job.template.id
    assert notification_db.template_version == job.template.version
    assert notification_db.status == "created"
    assert notification_db.created_at >= created_at
    assert notification_db.notification_type == "letter"
    assert notification_db.sent_at is None
    assert notification_db.sent_by is None
    assert notification_db.personalisation == personalisation
    assert notification_db.reference == "this-is-random-in-real-life"
    assert not notification_db.reply_to_text


def test_get_letter_template_instance(mocker, mock_celery_task_nl, sample_job):
    mocker.patch(
        "app.celery.tasks.s3.get_job_and_metadata_from_s3",
        return_value=("", {}),
    )
    sample_contact_block = create_letter_contact(service=sample_job.service, contact_block="((reference number))")
    sample_template = create_template(
        service=sample_job.service,
        template_type=LETTER_TYPE,
        reply_to=sample_contact_block.id,
    )
    sample_job.template_id = sample_template.id

    (
        recipient_csv,
        template,
        _sender_id,
    ) = get_recipient_csv_and_template_and_sender_id(sample_job)

    assert isinstance(template, LetterPrintTemplate)
    assert template.contact_block == ("((reference number))")
    assert template.placeholders == {"reference number"}
    assert recipient_csv.placeholders == [
        "reference number",
        "address line 1",
        "address line 2",
        "address line 3",
        "address line 4",
        "address line 5",
        "postcode",
        "address line 6",
    ]
