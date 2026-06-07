import base64

from flask import current_app
from notifications_utils.s3 import s3upload
from notifications_utils.timezones import convert_utc_to_bst

from app.models import Notification

MESSAGEBOX_FILE_LOCATION_STRUCTURE = "{base_folder}/{folder}/{filename}"


def get_base_folder_name(created_at) -> str:
    print_datetime = convert_utc_to_bst(created_at)

    return f"{print_datetime.date()}"


def upload_messagebox_attachments(notification: Notification, attachments: list[dict]) -> list[str]:
    current_app.logger.info(
        "Messagebox attachments [%s] for notification %s, created at %s ",
        len(attachments),
        notification.id,
        notification.created_at,
    )

    bucket_name = current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"]

    uploads = []

    for attachment in attachments:
        filename = attachment["filename"]
        file_content = base64.b64decode(attachment["file"])

        upload_file_name = MESSAGEBOX_FILE_LOCATION_STRUCTURE.format(
            base_folder=get_base_folder_name(notification.created_at), folder=notification.id, filename=filename
        )

        s3upload(
            filedata=file_content,
            region=current_app.config["AWS_REGION"],
            bucket_name=bucket_name,
            file_location=upload_file_name,
        )

        current_app.logger.info(
            "Uploaded messagebox attachment %s to %s for notification id %s",
            upload_file_name,
            bucket_name,
            notification.id,
        )

        uploads.append(upload_file_name)

    return uploads
