import json

from flask import current_app, url_for
from notifications_utils.url_safe_token import check_token

from tests.app.db import create_invited_user, create_user


class TestCreateFunctionalTestVerificationLink:
    def test_auth_required(self, client, sample_user):
        response = client.post(
            url_for(
                "functional_tests.create_functional_test_verification_link_route",
                email_address=sample_user.email_address,
            ),
        )
        assert response.status_code == 401

    def test_returns_link_matching_the_user(self, functional_tests_request):
        user = create_user(email="smoke-test-verify@notifynl.invalid")

        result = functional_tests_request.post(
            "functional_tests.create_functional_test_verification_link_route",
            email_address=user.email_address,
            _expected_status=201,
        )

        assert "/verify-email/" in result["url"]
        token = result["url"].rsplit("/verify-email/", 1)[1].split("?")[0]
        payload = json.loads(
            check_token(
                token,
                current_app.config["SECRET_KEY"],
                current_app.config["DANGEROUS_SALT"],
                max_age_seconds=3600,
                encryption_secret=current_app.config.get("TOKEN_SECRET_KEY"),
            )
        )
        assert payload["user_id"] == str(user.id)
        assert payload["email"] == user.email_address

    def test_returns_404_for_unknown_email(self, functional_tests_request):
        functional_tests_request.post(
            "functional_tests.create_functional_test_verification_link_route",
            email_address="no-such-user@notifynl.invalid",
            _expected_status=404,
        )


class TestCreateFunctionalTestInviteLink:
    def test_auth_required(self, client):
        response = client.post(
            url_for(
                "functional_tests.create_functional_test_invite_link_route", email_address="invitee@notifynl.invalid"
            ),
        )
        assert response.status_code == 401

    def test_returns_link_matching_the_invite(self, functional_tests_request):
        invited_user = create_invited_user(to_email_address="smoke-test-invitee@notifynl.invalid")

        result = functional_tests_request.post(
            "functional_tests.create_functional_test_invite_link_route",
            email_address=invited_user.email_address,
            _expected_status=201,
        )

        assert "/invitation/" in result["url"]
        token = result["url"].rsplit("/invitation/", 1)[1]
        payload = check_token(
            token,
            current_app.config["SECRET_KEY"],
            current_app.config["DANGEROUS_SALT"],
            max_age_seconds=3600,
            encryption_secret=current_app.config.get("TOKEN_SECRET_KEY"),
        )
        assert payload == str(invited_user.id)

    def test_returns_404_when_no_invite_exists(self, functional_tests_request):
        functional_tests_request.post(
            "functional_tests.create_functional_test_invite_link_route",
            email_address="never-invited@notifynl.invalid",
            _expected_status=404,
        )
