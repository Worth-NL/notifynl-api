import io
import json
import math
from datetime import datetime, timedelta
from enum import Enum

import boto3
from flask import current_app
from notifications_utils.clients.redis import daily_limit_cache_key
from notifications_utils.letter_timings import LETTER_PROCESSING_DEADLINE
from notifications_utils.pdf import pdf_page_count
from notifications_utils.s3 import s3upload
from notifications_utils.timezones import convert_utc_to_bst

from app import redis_store
from app.constants import (
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NETHERLANDS,
    NOTIFICATION_VALIDATION_FAILED,
    RESOLVE_POSTAGE_FOR_FILE_NAME,
)


class ScanErrorType(Enum):
    ERROR = 1
    FAILURE = 2


# [NOTIFYNL] Human-readable text for every detailed_status_code a letter's validation-failed
# or virus-scan-failed status can carry - the slugs raised by notifynl-template-preview's
# sanitise_file_contents (app/precompiled.py, ValidationFailed call sites) plus the
# PrecompiledPostalAddress.error_code values it can also raise, and the fixed
# "virus-detected" code used for an actual virus match. Mirrors
# app.clients.messagebox.ebms_adapter.get_messagebox_failure_reason's shape for the
# messagebox channel.
LETTER_FAILURE_REASONS = {
    "letter-too-long": "The letter has too many pages.",
    "letter-not-a4-portrait-oriented": "The letter is not A4 portrait.",
    "content-outside-printable-area": "Content is outside the printable area.",
    "notify-tag-found-in-content": "A NOTIFY tag was found in the letter content.",
    "unable-to-read-the-file": "The file could not be read as a valid PDF.",
    "address-placement-mismatch": "The address block is not where it was expected to be.",
    "address-is-empty": "The address block is empty.",
    "not-enough-address-lines": "The address does not have enough lines.",
    "too-many-address-lines": "The address has too many lines.",
    "invalid-address-line-1-or-2": "The first or second address line is invalid.",
    "has-country-for-bfpo-address": "A country was given for a BFPO address.",
    "not-a-real-uk-postcode-or-country": "The last address line is not a real postcode or country.",
    "cant-send-international-letters": "The service is not permitted to send international letters.",
    "not-a-real-uk-postcode": "The last address line is not a real postcode.",
    "invalid-char-in-address": "The address contains an invalid character.",
    "no-fixed-abode-address": "The address indicates no fixed abode.",
    "virus-detected": "A virus was detected in the uploaded file.",
}


def get_letter_failure_reason(detailed_status_code):
    """Decodes a letter's detailed_status_code into human-readable reason text.
    Returns None for an unrecognised or absent code."""
    if not detailed_status_code:
        return None
    return LETTER_FAILURE_REASONS.get(detailed_status_code, detailed_status_code)


LETTERS_PDF_FILE_LOCATION_STRUCTURE = "{folder}NOTIFY.{reference}.{duplex}.{letter_class}.{colour}.{date}.pdf"

PRECOMPILED_BUCKET_PREFIX = "{folder}NOTIFY.{reference}"


def get_folder_name(created_at):
    print_datetime = convert_utc_to_bst(created_at)
    if print_datetime.time() > LETTER_PROCESSING_DEADLINE:
        print_datetime += timedelta(days=1)
    return f"{print_datetime.date()}/"


class LetterPDFNotFound(Exception):
    pass


def find_letter_pdf_in_s3(notification):
    bucket_name, prefix = get_bucket_name_and_prefix_for_notification(notification)

    s3 = boto3.resource("s3")
    bucket = s3.Bucket(bucket_name)
    try:
        item = next(x for x in bucket.objects.filter(Prefix=prefix))
    except StopIteration as e:
        raise LetterPDFNotFound(
            f"File not found in bucket {bucket_name} with prefix {prefix}",
        ) from e
    return item


def generate_letter_pdf_filename(reference, created_at, ignore_folder=False, postage=NETHERLANDS):
    upload_file_name = LETTERS_PDF_FILE_LOCATION_STRUCTURE.format(
        folder="" if ignore_folder else get_folder_name(created_at),
        reference=reference,
        duplex="D",
        letter_class=RESOLVE_POSTAGE_FOR_FILE_NAME[postage],
        colour="C",
        date=created_at.strftime("%Y%m%d%H%M%S"),
    ).upper()
    return upload_file_name


def get_bucket_name_and_prefix_for_notification(notification):
    folder = ""
    if notification.status == NOTIFICATION_VALIDATION_FAILED:
        bucket_name = current_app.config["S3_BUCKET_INVALID_PDF"]
    elif notification.key_type == KEY_TYPE_TEST:
        bucket_name = current_app.config["S3_BUCKET_TEST_LETTERS"]
    else:
        bucket_name = current_app.config["S3_BUCKET_LETTERS_PDF"]
        folder = get_folder_name(notification.created_at)

    upload_file_name = PRECOMPILED_BUCKET_PREFIX.format(folder=folder, reference=notification.reference).upper()

    return bucket_name, upload_file_name


def get_reference_from_filename(filename):
    # filename looks like '2018-01-13/NOTIFY.ABCDEF1234567890.D.2.C.20180113120000.PDF'
    filename_parts = filename.split(".")
    return filename_parts[1]


def upload_letter_pdf(notification, pdf_data, precompiled=False):
    extra = {
        "notification_id": notification.id,
        "notification_reference": notification.reference,
        "notification_created_at": notification.created_at,
        "file_size": len(pdf_data),
    }
    current_app.logger.info(
        "PDF Letter notification %(notification_id)s reference %(notification_reference)s "
        "created at %(notification_created_at)s, %(file_size)s bytes",
        extra,
        extra=extra,
    )

    upload_file_name = generate_letter_pdf_filename(
        reference=notification.reference,
        created_at=notification.created_at,
        ignore_folder=precompiled or notification.key_type == KEY_TYPE_TEST,
        postage=notification.postage,
    )

    if precompiled:
        bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    elif notification.key_type == KEY_TYPE_TEST:
        bucket_name = current_app.config["S3_BUCKET_TEST_LETTERS"]
    else:
        bucket_name = current_app.config["S3_BUCKET_LETTERS_PDF"]

    s3upload(
        filedata=pdf_data,
        region=current_app.config["AWS_REGION"],
        bucket_name=bucket_name,
        file_location=upload_file_name,
    )

    extra = {
        "notification_id": notification.id,
        "s3_bucket": bucket_name,
        "s3_key": upload_file_name,
    }
    current_app.logger.info(
        "Uploaded letters PDF %(s3_key)s to %(s3_bucket)s for notification id %(notification_id)s", extra, extra=extra
    )
    return upload_file_name


def build_letter_part_filename(base_filename, part_index):
    """
    [NOTIFYNL] part_index is 0-based. Part 0 (the primary/address-bearing PDF) keeps the
    canonical filename unchanged, for full backward compatibility with single-PDF requests and
    with get_reference_from_filename (which reads filename.split(".")[1] - untouched by this,
    since the reference is always the second dot-separated segment regardless of what's appended
    before the final extension). Parts 1 and 2 get a `.PARTn` marker inserted before the file
    extension so they get distinct S3 keys without colliding with the canonical one.
    """
    if part_index == 0:
        return base_filename
    stem, _, ext = base_filename.rpartition(".")
    return f"{stem}.PART{part_index + 1}.{ext}"


def upload_letter_pdf_parts(notification, pdf_data_list, precompiled=True):
    """
    [NOTIFYNL] Uploads an ordered list of precompiled letter PDFs (up to 3, to be merged into a
    single letter downstream - see app.celery.letters_pdf_tasks.sanitise_letter_parts) to the
    letters-scan bucket. filenames[0] is byte-for-byte identical to what upload_letter_pdf would
    produce for the same notification, so the rest of the pipeline can keep addressing "the"
    canonical filename exactly as it does for a single-PDF letter.
    """
    base_filename = generate_letter_pdf_filename(
        reference=notification.reference,
        created_at=notification.created_at,
        ignore_folder=precompiled or notification.key_type == KEY_TYPE_TEST,
        postage=notification.postage,
    )
    bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]

    filenames = []
    for part_index, pdf_data in enumerate(pdf_data_list):
        filename = build_letter_part_filename(base_filename, part_index)
        s3upload(
            filedata=pdf_data,
            region=current_app.config["AWS_REGION"],
            bucket_name=bucket_name,
            file_location=filename,
        )
        filenames.append(filename)

    current_app.logger.info(
        "PDF Letter %s reference %s created at %s, uploaded %s part(s): %s",
        notification.id,
        notification.reference,
        notification.created_at,
        len(filenames),
        filenames,
    )

    return filenames


def upload_letter_attachments(notification, attachments: list[bytes]) -> list[str]:
    """
    [NOTIFYNL] Uploads 1-2 ad-hoc PDFs submitted alongside a templated-letter send to the
    letters-scan bucket, keyed by notification id rather than the filename scheme
    upload_letter_pdf_parts uses - a templated letter has no canonical letter_filename yet
    at send time (that's only computed later, in get_pdf_for_templated_letter).
    """
    bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]

    keys = []
    for index, attachment in enumerate(attachments, start=1):
        key = f"{notification.id}/attachment-{index}.pdf"
        s3upload(
            filedata=attachment,
            region=current_app.config["AWS_REGION"],
            bucket_name=bucket_name,
            file_location=key,
        )
        keys.append(key)

    current_app.logger.info("Letter %s uploaded %s ad-hoc attachment(s): %s", notification.id, len(keys), keys)

    return keys


def get_letter_attachment_keys(notification_id) -> list[str]:
    """
    [NOTIFYNL] Lists any ad-hoc attachments uploaded by upload_letter_attachments for a given
    notification - used both to populate the payload get_pdf_for_templated_letter sends to
    notifynl-template-preview, and by the stuck-notification recovery check in
    check_if_letters_still_pending_virus_check (existence there is just bool(keys)).
    """
    bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]

    s3 = boto3.resource("s3")
    files = s3.Bucket(bucket_name).objects.filter(Prefix=f"{notification_id}/")

    return sorted(f.key for f in files if not f.key.endswith("/"))


def move_failed_pdf(source_filename, scan_error_type):
    scan_bucket = current_app.config["S3_BUCKET_LETTERS_SCAN"]

    target_filename = ("ERROR/" if scan_error_type == ScanErrorType.ERROR else "FAILURE/") + source_filename

    _move_s3_object(scan_bucket, source_filename, scan_bucket, target_filename)


def move_error_pdf_to_scan_bucket(source_filename):
    scan_bucket = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    error_file = "ERROR/" + source_filename

    _move_s3_object(scan_bucket, error_file, scan_bucket, source_filename)


def move_scan_to_invalid_pdf_bucket(source_filename, message=None, invalid_pages=None, page_count=None):
    metadata = {}
    if message:
        metadata["message"] = message
    if invalid_pages:
        metadata["invalid_pages"] = json.dumps(invalid_pages)
    if page_count:
        metadata["page_count"] = str(page_count)

    _move_s3_object(
        source_bucket=current_app.config["S3_BUCKET_LETTERS_SCAN"],
        source_filename=source_filename,
        target_bucket=current_app.config["S3_BUCKET_INVALID_PDF"],
        target_filename=source_filename,
        metadata=metadata,
    )


def move_uploaded_pdf_to_letters_bucket(source_filename, upload_filename):
    _move_s3_object(
        source_bucket=current_app.config["S3_BUCKET_TRANSIENT_UPLOADED_LETTERS"],
        source_filename=source_filename,
        target_bucket=current_app.config["S3_BUCKET_LETTERS_PDF"],
        target_filename=upload_filename,
    )


def move_sanitised_letter_to_test_or_live_pdf_bucket(filename, is_test_letter, created_at, new_filename):
    target_bucket_config = "S3_BUCKET_TEST_LETTERS" if is_test_letter else "S3_BUCKET_LETTERS_PDF"
    target_bucket_name = current_app.config[target_bucket_config]
    target_folder = "" if is_test_letter else get_folder_name(created_at)
    target_filename = target_folder + new_filename

    _move_s3_object(
        source_bucket=current_app.config["S3_BUCKET_LETTER_SANITISE"],
        source_filename=filename,
        target_bucket=target_bucket_name,
        target_filename=target_filename,
    )


def get_file_names_from_error_bucket():
    s3 = boto3.resource("s3")
    scan_bucket = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    bucket = s3.Bucket(scan_bucket)

    return bucket.objects.filter(Prefix="ERROR")


def get_letter_pdf_and_metadata(notification):
    obj = find_letter_pdf_in_s3(notification).get()
    return obj["Body"].read(), obj["Metadata"]


def _move_s3_object(source_bucket, source_filename, target_bucket, target_filename, metadata=None):
    s3 = boto3.resource("s3")
    copy_source = {"Bucket": source_bucket, "Key": source_filename}

    target_bucket = s3.Bucket(target_bucket)
    obj = target_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    put_args = {"ServerSideEncryption": "AES256"}
    if metadata:
        put_args["Metadata"] = metadata
        put_args["MetadataDirective"] = "REPLACE"
    obj.copy(copy_source, ExtraArgs=put_args)

    s3.Object(source_bucket, source_filename).delete()

    extra = {
        "s3_bucket": source_bucket,
        "s3_key": source_filename,
        "s3_bucket_new": target_bucket,
        "s3_key_new": target_filename,
    }
    current_app.logger.info(
        "Moved letter PDF: %(s3_bucket)s/%(s3_key)s to %(s3_bucket_new)s/%(s3_key_new)s",
        extra,
        extra=extra,
    )


def letter_print_day(created_at):
    bst_print_datetime = convert_utc_to_bst(created_at) + timedelta(hours=6, minutes=30)
    bst_print_date = bst_print_datetime.date()

    current_bst_date = convert_utc_to_bst(datetime.utcnow()).date()

    if bst_print_date >= current_bst_date:
        return "today"
    else:
        print_date = bst_print_datetime.strftime("%d %B").lstrip("0")
        return f"on {print_date}"


def get_page_count(pdf):
    return pdf_page_count(io.BytesIO(pdf))


def get_billable_units_for_letter_page_count(page_count):
    if not page_count:
        return 0
    pages_per_sheet = 2
    billable_units = math.ceil(page_count / pages_per_sheet)
    return billable_units


def adjust_daily_service_limits_for_cancelled_letters(service_id, no_of_cancelled_letters, letters_created_at):
    """
    Updates the Redis values for the daily letters sent and total number of notifications sent
    by a service. These values should be decreased if letters are cancelled.

    Before updating the value, we check that the key exists and that we would not be changing its
    value to a negative number.

    We only want to update today's cached value, so if the letters were created yesterday we return
    early.
    """

    if not current_app.config["REDIS_ENABLED"]:
        return

    if letters_created_at.date() != datetime.today().date():
        return

    letters_cache_key = daily_limit_cache_key(service_id, notification_type=LETTER_TYPE)

    if (cached_letters_sent := redis_store.get(letters_cache_key)) is not None:
        if (int(cached_letters_sent) - no_of_cancelled_letters) >= 0:
            redis_store.decrby(letters_cache_key, no_of_cancelled_letters)
