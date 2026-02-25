from datetime import datetime

import pytest
from flask import current_app

from app.constants import (
    PRECOMPILED_TEMPLATE_NAME,
)
from app.letters.utils import (
    generate_letter_pdf_filename,
    upload_letter_pdf,
)
from tests.app.db import create_notification

FROZEN_DATE_TIME = "2018-03-14 17:00:00"


@pytest.mark.parametrize(
    "postage,expected_postage",
    [("europe", "E"), ("netherlands", 1), ("rest-of-world", "N")],
)
def test_generate_letter_pdf_filename_returns_correct_postage_for_filename(notify_api, postage, expected_postage):
    created_at = datetime(2017, 12, 4, 17, 29)
    filename = generate_letter_pdf_filename(reference="foo", created_at=created_at, postage=postage)

    assert filename == f"2017-12-04/NOTIFY.FOO.D.{expected_postage}.C.20171204172900.PDF"


def test_generate_letter_pdf_filename_returns_correct_filename_for_test_letters(notify_api, mocker):
    created_at = datetime(2017, 12, 4, 17, 29)
    filename = generate_letter_pdf_filename(reference="foo", created_at=created_at, ignore_folder=True)

    assert filename == "NOTIFY.FOO.D.1.C.20171204172900.PDF"


def test_generate_letter_pdf_filename_returns_tomorrows_filename(notify_api):
    created_at = datetime(2017, 12, 4, 17, 31)
    filename = generate_letter_pdf_filename(reference="foo", created_at=created_at)

    assert filename == "2017-12-05/NOTIFY.FOO.D.1.C.20171204173100.PDF"


@pytest.mark.parametrize(
    "is_precompiled_letter,bucket_config_name", [(False, "S3_BUCKET_LETTERS_PDF"), (True, "S3_BUCKET_LETTERS_SCAN")]
)
def test_upload_letter_pdf_to_correct_bucket(
    sample_letter_notification, mocker, is_precompiled_letter, bucket_config_name
):
    if is_precompiled_letter:
        sample_letter_notification.template.hidden = True
        sample_letter_notification.template.name = PRECOMPILED_TEMPLATE_NAME

    mock_s3 = mocker.patch("app.letters.utils.s3upload")

    filename = generate_letter_pdf_filename(
        reference=sample_letter_notification.reference,
        created_at=sample_letter_notification.created_at,
        ignore_folder=is_precompiled_letter,
    )

    upload_letter_pdf(sample_letter_notification, b"\x00\x01", precompiled=is_precompiled_letter)

    mock_s3.assert_called_once_with(
        bucket_name=current_app.config[bucket_config_name],
        file_location=filename,
        filedata=b"\x00\x01",
        region=current_app.config["AWS_REGION"],
    )


@pytest.mark.parametrize("postage", ["netherlands", "europe"])
def test_upload_letter_pdf_uses_postage_from_notification(sample_letter_template, mocker, postage):
    letter_notification = create_notification(template=sample_letter_template, postage=postage)
    mock_s3 = mocker.patch("app.letters.utils.s3upload")

    filename = generate_letter_pdf_filename(
        reference=letter_notification.reference,
        created_at=letter_notification.created_at,
        ignore_folder=False,
        postage=letter_notification.postage,
    )

    upload_letter_pdf(letter_notification, b"\x00\x01", precompiled=False)

    mock_s3.assert_called_once_with(
        bucket_name=current_app.config["S3_BUCKET_LETTERS_PDF"],
        file_location=filename,
        filedata=b"\x00\x01",
        region=current_app.config["AWS_REGION"],
    )
