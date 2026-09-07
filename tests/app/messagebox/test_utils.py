import uuid

import boto3
from flask import current_app
from moto import mock_aws

from app.messagebox.utils import get_messagebox_attachments
from app.models import Notification


@mock_aws
def test_get_messagebox_attachments_downloads_all_files_from_notification_folder(client):
    bucket_name = "notifynl-test-messagebox-attachments"
    current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"] = bucket_name

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})

    notification_id = uuid.uuid4()
    s3.put_object(Bucket=bucket_name, Key=f"{notification_id}/one.pdf", Body=b"content-one")
    s3.put_object(Bucket=bucket_name, Key=f"{notification_id}/two.pdf", Body=b"content-two")

    notification = Notification(id=notification_id)

    attachments = get_messagebox_attachments(notification)

    assert {a["filename"]: a["content"] for a in attachments} == {
        "one.pdf": b"content-one",
        "two.pdf": b"content-two",
    }


@mock_aws
def test_get_messagebox_attachments_returns_empty_list_when_no_files(client):
    bucket_name = "notifynl-test-messagebox-attachments-empty"
    current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"] = bucket_name

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})

    notification = Notification(id=uuid.uuid4())

    assert get_messagebox_attachments(notification) == []
