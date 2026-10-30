import inspect
import smtplib

import pytest

from app import smtp_client
from app.clients.email import EmailClientNonRetryableException
from app.clients.email.aws_ses import (
    AwsSesClient,
    get_aws_responses,
)
from app.clients.email.aws_ses_stub import AwsSesStubClient
from app.clients.email.smtp import SmtpClientException

TEST_FROM_ADDRESS = "demo-noreply@basisdienst.overheid.nl"
TEST_TO_ADDRESS = "foo@bar.com"
TEST_SUBJECT = "Test Subject"
TEST_BODY = "Test Body"
TEST_HTML_BODY = "<p>Test Body</p>"
TEST_HEADERS = []


def test_should_return_correct_details_for_delivery():
    response_dict = get_aws_responses("Delivery")
    assert response_dict["message"] == "Delivered"
    assert response_dict["notification_status"] == "delivered"
    assert response_dict["notification_statistics_status"] == "delivered"
    assert response_dict["success"]


def test_should_return_correct_details_for_hard_bounced():
    response_dict = get_aws_responses("Permanent")
    assert response_dict["message"] == "Hard bounced"
    assert response_dict["notification_status"] == "permanent-failure"
    assert response_dict["notification_statistics_status"] == "failure"
    assert not response_dict["success"]


def test_should_return_correct_details_for_soft_bounced():
    response_dict = get_aws_responses("Temporary")
    assert response_dict["message"] == "Soft bounced"
    assert response_dict["notification_status"] == "temporary-failure"
    assert response_dict["notification_statistics_status"] == "failure"
    assert not response_dict["success"]


def test_should_return_correct_details_for_complaint():
    response_dict = get_aws_responses("Complaint")
    assert response_dict["message"] == "Complaint"
    assert response_dict["notification_status"] == "delivered"
    assert response_dict["notification_statistics_status"] == "delivered"
    assert response_dict["success"]


def test_should_be_none_if_unrecognised_status_code():
    with pytest.raises(KeyError) as e:
        get_aws_responses("99")
    assert "99" in str(e.value)


@pytest.mark.parametrize(
    "reply_to_address, expected_value",
    [
        (None, None),
        ("foo@bar.com", "foo@bar.com"),
        ("føøøø@bååååår.com", "føøøø@bååååår.com"),
    ],
    ids=["empty", "single_email", "punycode"],
)
def test_send_email_handles_reply_to_address(
    notify_api,
    mocker,
    reply_to_address,
    expected_value,
):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    with notify_api.app_context():
        smtp_client.send_email(
            from_address=TEST_FROM_ADDRESS,
            to_address="to@address.com",
            subject=TEST_SUBJECT,
            body=TEST_BODY,
            html_body=TEST_HTML_BODY,
            headers=TEST_HEADERS,
            reply_to_address=reply_to_address,
        )

    server = smtp_mock.return_value.__enter__.return_value
    server.send_message.assert_called_once()

    msg = server.send_message.call_args[0][0]

    if expected_value:
        assert msg["Reply-To"] == expected_value
    else:
        assert "Reply-To" not in msg


def test_send_email_handles_punycode_to_address(notify_api, mocker):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    with notify_api.app_context():
        smtp_client.send_email(
            from_address=TEST_FROM_ADDRESS,
            to_address="føøøø@bååååår.com",
            subject=TEST_SUBJECT,
            body=TEST_BODY,
            html_body=TEST_HTML_BODY,
            reply_to_address=None,
            headers=TEST_HEADERS,
        )

    server = smtp_mock.return_value.__enter__.return_value
    server.send_message.assert_called_once()

    msg = server.send_message.call_args[0][0]

    assert msg["To"] == "føøøø@bååååår.com"


def test_send_email_sends_content_correctly(notify_api, mocker):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    with notify_api.app_context():
        smtp_client.send_email(
            from_address=TEST_FROM_ADDRESS,
            to_address=TEST_TO_ADDRESS,
            reply_to_address=None,
            subject=TEST_SUBJECT,
            body=TEST_BODY,
            html_body=TEST_HTML_BODY,
            headers=TEST_HEADERS,
        )

    server = smtp_mock.return_value.__enter__.return_value
    server.send_message.assert_called_once()

    msg = server.send_message.call_args[0][0]

    assert "noreply@overheid.nl" in msg["From"]
    assert msg["To"] == TEST_TO_ADDRESS
    assert msg["Subject"] == TEST_SUBJECT


def test_send_email_raises_invalid_recipient_as_EmailClientNonRetryableException(
    notify_api,
    mocker,
):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    server = smtp_mock.return_value.__enter__.return_value
    server.send_message.side_effect = smtplib.SMTPRecipientsRefused({})

    with notify_api.app_context():
        with pytest.raises(EmailClientNonRetryableException):
            smtp_client.send_email(
                from_address=TEST_FROM_ADDRESS,
                to_address="definitely@invalid_email.com",
                subject=TEST_SUBJECT,
                body=TEST_BODY,
                html_body=TEST_HTML_BODY,
                reply_to_address=None,
                headers=TEST_HEADERS,
            )


def test_send_email_raises_authentication_error_as_SmtpClientException(
    notify_api,
    mocker,
):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    mocker.patch.object(smtp_client, "username", "user")
    mocker.patch.object(smtp_client, "password", "password")

    server = smtp_mock.return_value.__enter__.return_value
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")

    with notify_api.app_context():
        with pytest.raises(SmtpClientException):
            smtp_client.send_email(
                from_address=TEST_FROM_ADDRESS,
                to_address=TEST_TO_ADDRESS,
                subject=TEST_SUBJECT,
                body=TEST_BODY,
                html_body=TEST_HTML_BODY,
                reply_to_address=None,
                headers=TEST_HEADERS,
            )


def test_send_email_raises_other_errors_as_SmtpClientException(
    notify_api,
    mocker,
):
    smtp_mock = mocker.patch("app.clients.email.smtp.smtplib.SMTP")
    mocker.patch.object(smtp_client, "statsd_client", create=True)

    server = smtp_mock.return_value.__enter__.return_value
    server.send_message.side_effect = Exception("some smtp error")

    with notify_api.app_context():
        with pytest.raises(SmtpClientException) as excinfo:
            smtp_client.send_email(
                from_address=TEST_FROM_ADDRESS,
                to_address=TEST_TO_ADDRESS,
                subject=TEST_SUBJECT,
                body=TEST_BODY,
                html_body=TEST_HTML_BODY,
                reply_to_address=None,
                headers=TEST_HEADERS,
            )

    assert "some smtp error" in str(excinfo.value)


def test_stub_client_is_compatible_with_real_client():
    # AwsSesStubClient can have additonal arguments, so we only check that
    # its arguments are a superset of AwsSesClient's
    assert set(inspect.signature(AwsSesStubClient.__init__).parameters).issuperset(
        set(inspect.signature(AwsSesClient.__init__).parameters)
    )

    # send_email should match exactly
    assert inspect.signature(AwsSesClient.send_email) == inspect.signature(AwsSesStubClient.send_email)
