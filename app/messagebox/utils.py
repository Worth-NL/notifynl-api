import base64

from flask import current_app
from notifications_utils.s3 import s3_download_all_files_from_folder, s3upload

from app.models import Notification

MESSAGEBOX_FILE_LOCATION_STRUCTURE = "{folder}/{filename}"


def upload_messagebox_attachments(notification: Notification, attachments: list[dict]) -> list[str]:
    current_app.logger.info(
        "Messagebox attachments [%s] for notification %s :: UPLOAD",
        len(attachments),
        notification.id,
    )

    bucket_name = current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"]

    uploads = []

    for attachment in attachments:
        filename = attachment["filename"]
        file_content = base64.b64decode(attachment["file"])

        upload_file_name = MESSAGEBOX_FILE_LOCATION_STRUCTURE.format(folder=notification.id, filename=filename)

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


def get_messagebox_attachments(notification: Notification) -> list[dict]:
    current_app.logger.info("Messagebox attachments for notification %s :: GET", notification.id)

    bucket_attachment = current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"]

    files_data = s3_download_all_files_from_folder(bucket_attachment, str(notification.id))

    return [{"filename": filename, "content": content} for filename, content in files_data.items()]
