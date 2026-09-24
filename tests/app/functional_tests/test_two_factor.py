import json
import uuid

from flask import current_app, url_for
from notifications_utils.url_safe_token import check_token

from app.dao.users_dao import get_user_code
from app.models import Notification, VerifyCode


class TestCreateFunctionalTest2faLink:
    def test_auth_required(self, client, sample_user):
        response = client.post(
            url_for("functional_tests.create_functional_test_2fa_link_route", user_id=sample_user.id),
        )
        assert response.status_code == 401

    def test_creates_usable_code_and_returns_matching_url(
        self, functional_tests_request, mocker, sample_user, email_2fa_code_template
    ):
        deliver_email = mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")

        result = functional_tests_request.post(
            "functional_tests.create_functional_test_2fa_link_route",
            user_id=sample_user.id,
            _expected_status=201,
        )

        assert result["url"].startswith("http")
        assert "/email-auth/" in result["url"]

        noti = Notification.query.one()
        assert noti.to == sample_user.email_address
        assert str(noti.template_id) == str(email_2fa_code_template.id)
        assert noti.personalisation["url"] == result["url"]
        deliver_email.assert_called_once()

        # Decode the token the same way notifynl-admin's real /email-auth
        # route would, rather than re-deriving the secret_code
        # independently, so this test breaks if that signing contract ever
        # changes.
        token = result["url"].rsplit("/email-auth/", 1)[1].split("?")[0]
        payload = json.loads(
            check_token(
                token,
                current_app.config["SECRET_KEY"],
                current_app.config["DANGEROUS_SALT"],
                max_age_seconds=3600,
                encryption_secret=current_app.config.get("TOKEN_SECRET_KEY"),
            )
        )
        assert payload["user_id"] == str(sample_user.id)

        code = get_user_code(sample_user, payload["secret_code"], "email")
        assert code is not None
        assert not code.code_used
        assert VerifyCode.query.filter_by(user=sample_user).count() == 1

    def test_returns_404_for_unknown_user(self, functional_tests_request):
        functional_tests_request.post(
            "functional_tests.create_functional_test_2fa_link_route",
            user_id=uuid.uuid4(),
            _expected_status=404,
        )
