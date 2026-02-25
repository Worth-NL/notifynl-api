import time
from unittest.mock import Mock

import boto3
import jwt
import pytest
from flask import current_app
from moto import mock_aws
from notifications_utils.recipient_validation.notifynl.postal_address import PostalAddress

from app.clients.letter.dvla import (
    DVLAClient,
)


@pytest.fixture
def ssm():
    with mock_aws():
        ssm_client = boto3.client("ssm", "eu-west-1")
        ssm_client.put_parameter(
            Name="/notify/api/dvla_username",
            Value="some username",
            Type="SecureString",
        )
        ssm_client.put_parameter(
            Name="/notify/api/dvla_password",
            Value="some password",
            Type="SecureString",
        )
        ssm_client.put_parameter(
            Name="/notify/api/dvla_api_key",
            Value="some api key",
            Type="SecureString",
        )
        yield ssm_client


@pytest.fixture
def dvla_client(notify_api, client, ssm):
    dvla_client = DVLAClient(notify_api, statsd_client=Mock())
    yield dvla_client


@pytest.fixture
def dvla_authenticate(rmock):
    token = jwt.encode(payload={"exp": int(time.time())}, key="foo")
    rmock.request("POST", "https://test-dvla-api.com/thirdparty-access/v1/authenticate", json={"id-token": token})


def test_format_create_print_job_json_adds_despatchMethod_key_for_first_class_post(dvla_client):
    formatted_json = dvla_client._format_create_print_job_json(
        notification_id="my_notification_id",
        reference="ABCDEFGHIJKL",
        address=PostalAddress("A. User\nThe road\n1234AB City"),
        postage="netherlands",
        service_id="my_service_id",
        organisation_id="my_organisation_id",
        pdf_file=b"pdf_content",
        callback_url="/my-callback",
    )

    assert formatted_json["standardParams"]["despatchMethod"] == "NETHERLANDS"


def test_send_domestic_letter(dvla_client, dvla_authenticate, rmock):
    print_mock = rmock.post(
        f"{current_app.config['DVLA_API_BASE_URL']}/print-request/v1/print/jobs",
        json={"id": "noti_id"},
        status_code=202,
    )

    response = dvla_client.send_letter(
        notification_id="noti_id",
        reference="ABCDEFGHIJKL",
        address=PostalAddress("recipient\naddress\n1234AB City"),
        postage="netherlands",
        service_id="service_id",
        organisation_id="org_id",
        pdf_file=b"pdf",
        callback_url="https://www.example.com?token=1234",
    )

    assert response == {"id": "noti_id"}

    assert print_mock.last_request.json() == {
        "id": "noti_id",
        "standardParams": {
            "jobType": "NOTIFY",
            "templateReference": "NOTIFY",
            "businessIdentifier": "ABCDEFGHIJKL",
            "despatchMethod": "NETHERLANDS",
            "recipientName": "recipient",
            "address": {"unstructuredAddress": {"line1": "address", "postcode": "1234 AB  CITY"}},
        },
        "customParams": [
            {"key": "pdfContent", "value": "cGRm"},
            {"key": "organisationIdentifier", "value": "org_id"},
            {"key": "serviceIdentifier", "value": "service_id"},
        ],
        "callbackParams": {
            "target": "https://www.example.com?token=1234",
            "retryParams": {"enabled": True, "maxRetryWindow": 10800},
        },
    }

    request_headers = print_mock.last_request.headers

    assert request_headers["Accept"] == "application/json"
    assert request_headers["Content-Type"] == "application/json"
    assert request_headers["X-API-Key"] == "some api key"
    assert request_headers["Authorization"]


def test_send_bfpo_letter_returns_default(dvla_client, dvla_authenticate, rmock):
    print_mock = rmock.post(
        f"{current_app.config['DVLA_API_BASE_URL']}/print-request/v1/print/jobs",
        json={"id": "noti_id"},
        status_code=202,
    )

    response = dvla_client.send_letter(
        notification_id="noti_id",
        reference="ABCDEFGHIJKL",
        address=PostalAddress("recipient\nbfpo address\n1234AB City"),
        postage="netherlands",
        service_id="service_id",
        organisation_id="org_id",
        pdf_file=b"pdf",
        callback_url="https://www.example.com?token=1234",
    )

    assert response == {"id": "noti_id"}

    assert print_mock.last_request.json() == {
        "id": "noti_id",
        "standardParams": {
            "jobType": "NOTIFY",
            "templateReference": "NOTIFY",
            "businessIdentifier": "ABCDEFGHIJKL",
            "despatchMethod": "NETHERLANDS",
            "recipientName": "recipient",
            "address": {"unstructuredAddress": {"line1": "bfpo address", "postcode": "1234 AB  CITY"}},
        },
        "customParams": [
            {"key": "pdfContent", "value": "cGRm"},
            {"key": "organisationIdentifier", "value": "org_id"},
            {"key": "serviceIdentifier", "value": "service_id"},
        ],
        "callbackParams": {
            "target": "https://www.example.com?token=1234",
            "retryParams": {"enabled": True, "maxRetryWindow": 10800},
        },
    }

    request_headers = print_mock.last_request.headers

    assert request_headers["Accept"] == "application/json"
    assert request_headers["Content-Type"] == "application/json"
    assert request_headers["X-API-Key"] == "some api key"
    assert request_headers["Authorization"]


@pytest.mark.parametrize(
    "address, recipient, unstructured_address",
    [
        (
            PostalAddress("The user\nThe road\n1234 AB City Name"),
            "The user",
            {"line1": "The road", "postcode": "1234 AB  CITY NAME"},
        ),
        (
            PostalAddress("The user\nHouse no.\nMy Street\n1234 AB City Name"),
            "The user",
            {"line1": "House no.", "line2": "My Street", "postcode": "1234 AB  CITY NAME"},
        ),
        (
            PostalAddress("The user\n1\n2\n3\n4\n5\n1234 AB City Name"),
            "The user",
            {"line1": "1", "line2": "2", "line3": "3", "line4": "4", "line5": "5", "postcode": "1234 AB  CITY NAME"},
        ),
        (
            PostalAddress("The user\n1\n" + ("2" * 50) + "\n3\n4\n5\n1234 AB City Name"),
            "The user",
            {
                "line1": "1",
                "line2": "2" * 45,
                "line3": "3",
                "line4": "4",
                "line5": "5",
                "postcode": "1234 AB  CITY NAME",
            },
        ),
        (
            PostalAddress("The user\n1\n2\n3\n4\n5\nPostcode should not be over forty characters"),
            "The user",
            {
                "line1": "1",
                "line2": "2",
                "line3": "3",
                "line4": "4",
                "line5": "5",
                "postcode": "Postcode should not be over forty charac",
            },
        ),
    ],
)
def test_format_create_print_job_json_formats_address_lines(dvla_client, address, recipient, unstructured_address):
    formatted_json = dvla_client._format_create_print_job_json(
        notification_id="my_notification_id",
        reference="ABCDEFGHIJKL",
        address=address,
        postage="first",
        service_id="my_service_id",
        organisation_id="my_organisation_id",
        pdf_file=b"pdf_content",
        callback_url="/my-callback",
    )

    assert formatted_json["standardParams"]["recipientName"] == recipient
    assert formatted_json["standardParams"]["address"]["unstructuredAddress"] == unstructured_address


@pytest.mark.parametrize(
    "address, postage, despatch, international",
    [
        ("The user\nThe road\n1234 AB City Name", "netherlands", "NETHERLANDS", False),
        ("The user\nThe road\n1234 AB City Name\nGermany", "europe", "INTERNATIONAL_EU", True),
        ("The user\nThe road\n1234 AB City Name\nGuatemala", "rest-of-world", "INTERNATIONAL_ROW", True),
    ],
)
def test_format_create_print_job_json_adds_despatchMethod_key_for_economy_class_post(
    dvla_client, address, postage, despatch, international
):
    formatted_json = dvla_client._format_create_print_job_json(
        notification_id="my_notification_id",
        reference="ABCDEFGHIJKL",
        address=PostalAddress(address, international),
        postage=postage,
        service_id="my_service_id",
        organisation_id="my_organisation_id",
        pdf_file=b"pdf_content",
        callback_url="/my-callback",
    )

    assert formatted_json["standardParams"]["despatchMethod"] == despatch
