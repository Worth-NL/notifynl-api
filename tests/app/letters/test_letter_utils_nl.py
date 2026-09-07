from datetime import datetime

import pytest
from flask import current_app

from app.constants import (
    PRECOMPILED_TEMPLATE_NAME,
)
from app.letters.utils import (
    build_letter_part_filename,
    generate_letter_pdf_filename,
    get_reference_from_filename,
    upload_letter_pdf,
    upload_letter_pdf_parts,
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


@pytest.mark.parametrize(
    "part_index, expected_filename",
    [
        (0, "NOTIFY.FOO.D.1.C.20171204172900.PDF"),
        (1, "NOTIFY.FOO.D.1.C.20171204172900.PART2.PDF"),
        (2, "NOTIFY.FOO.D.1.C.20171204172900.PART3.PDF"),
    ],
)
def test_build_letter_part_filename(part_index, expected_filename):
    base_filename = "NOTIFY.FOO.D.1.C.20171204172900.PDF"

    assert build_letter_part_filename(base_filename, part_index) == expected_filename


@pytest.mark.parametrize("part_index", [0, 1, 2])
def test_build_letter_part_filename_preserves_reference_position(part_index):
    base_filename = "NOTIFY.ABCDEF1234567890.D.1.C.20171204172900.PDF"

    part_filename = build_letter_part_filename(base_filename, part_index)

    assert get_reference_from_filename(part_filename) == "ABCDEF1234567890"
    assert get_reference_from_filename(base_filename) == "ABCDEF1234567890"


def test_upload_letter_pdf_parts_uploads_all_parts_with_part_suffixes(sample_letter_notification, mocker):
    mock_s3 = mocker.patch("app.letters.utils.s3upload")

    filenames = upload_letter_pdf_parts(
        sample_letter_notification, [b"\x00\x01", b"\x00\x02", b"\x00\x03"], precompiled=True
    )

    base_filename = generate_letter_pdf_filename(
        reference=sample_letter_notification.reference,
        created_at=sample_letter_notification.created_at,
        ignore_folder=True,
        postage=sample_letter_notification.postage,
    )
    assert filenames == [
        base_filename,
        build_letter_part_filename(base_filename, 1),
        build_letter_part_filename(base_filename, 2),
    ]
    assert mock_s3.call_args_list == [
        mocker.call(
            bucket_name=current_app.config["S3_BUCKET_LETTERS_SCAN"],
            file_location=filenames[0],
            filedata=b"\x00\x01",
            region=current_app.config["AWS_REGION"],
        ),
        mocker.call(
            bucket_name=current_app.config["S3_BUCKET_LETTERS_SCAN"],
            file_location=filenames[1],
            filedata=b"\x00\x02",
            region=current_app.config["AWS_REGION"],
        ),
        mocker.call(
            bucket_name=current_app.config["S3_BUCKET_LETTERS_SCAN"],
            file_location=filenames[2],
            filedata=b"\x00\x03",
            region=current_app.config["AWS_REGION"],
        ),
    ]


def test_upload_letter_pdf_parts_single_part_matches_legacy_filename(sample_letter_notification, mocker):
    mocker.patch("app.letters.utils.s3upload")

    filenames = upload_letter_pdf_parts(sample_letter_notification, [b"\x00\x01"], precompiled=True)

    legacy_filename = generate_letter_pdf_filename(
        reference=sample_letter_notification.reference,
        created_at=sample_letter_notification.created_at,
        ignore_folder=True,
        postage=sample_letter_notification.postage,
    )
    assert filenames == [legacy_filename]
