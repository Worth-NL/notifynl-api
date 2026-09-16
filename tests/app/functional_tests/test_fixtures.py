import uuid

import freezegun
import pytest
from flask import url_for

from app.functional_tests.fixtures import fixture_email_for_resource
from app.models import Service, Template, User
from tests.app.db import create_user


@pytest.fixture(autouse=True)
def notify_db_session(notify_db_session):
    return notify_db_session


class TestCreateFixture:
    def test_auth_required(self, client):
        response = client.post(
            url_for("functional_tests.create_functional_test_fixture"),
            json={"runId": "run-1"},
        )
        assert response.status_code == 401

    def test_creates_org_service_user_keys_and_templates(self, functional_tests_request):
        result = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "gh-run-42-1"},
            _expected_status=201,
        )

        assert result["runId"] == "gh-run-42-1"
        assert result["resourceId"] == "gh-run-42-1"

        service = Service.query.filter_by(id=result["serviceId"]).one()
        assert service.name == "Smoke Test gh-run-42-1"

        admin_user = User.query.filter_by(email_address=fixture_email_for_resource("gh-run-42-1")).one()
        assert str(admin_user.id) == result["adminUser"]["id"]
        assert admin_user.auth_type == "email_auth"
        assert service in admin_user.services
        assert admin_user.check_password(result["adminUser"]["password"])

        assert result["apiKeyNormal"].startswith(f"smoke-test-normal-{service.id}-")
        assert result["apiKeyTest"].startswith(f"smoke-test-test-{service.id}-")
        assert result["emailTemplateId"]
        assert result["smsTemplateId"]

    def test_admin_user_gets_full_service_permissions(self, functional_tests_request):
        """
        Regression test: an earlier version of create_fixture explicitly
        narrowed the creator's permissions down to (send_emails, send_texts,
        view_activity), overwriting the full default set dao_create_service
        already grants -- which 403'd every admin-UI flow needing
        manage_templates/manage_api_keys/manage_users. See fixtures.py's
        comment above dao_create_service for the full story.
        """
        result = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "permissions-check"},
            _expected_status=201,
        )

        admin_user = User.query.filter_by(email_address=fixture_email_for_resource("permissions-check")).one()
        assert set(admin_user.get_permissions()[result["serviceId"]]) == {
            "manage_users",
            "manage_templates",
            "manage_settings",
            "send_texts",
            "send_emails",
            "send_letters",
            "manage_api_keys",
            "view_activity",
        }

    def test_service_has_email_auth_permission(self, functional_tests_request):
        """
        Regression test: without the service-level email_auth permission
        (separate from admin_user's own auth_type="email_auth"), notifynl-admin
        doesn't even render the "email link" login option when inviting a team
        member -- confirmed live: invite-team-member.spec.ts timed out waiting
        for that radio before this was added. See fixtures.py's comment above
        dao_create_service.
        """
        result = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "email-auth-permission-check"},
            _expected_status=201,
        )

        service = Service.query.filter_by(id=result["serviceId"]).one()
        assert service.has_permission("email_auth")

    def test_templates_use_nonce_placeholder(self, functional_tests_request):
        """
        Regression test: an earlier version used a ((resourceId)) placeholder
        that notifynl-smoke-tests' send-notification.spec.ts (a fixed,
        pre-existing test sending only {nonce}) never supplies -- confirmed
        live: every real send 400'd with "Missing personalisation: resourceId".
        """
        result = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "template-placeholder-check"},
            _expected_status=201,
        )

        email_template = Template.query.filter_by(id=result["emailTemplateId"]).one()
        sms_template = Template.query.filter_by(id=result["smsTemplateId"]).one()
        assert "((nonce))" in email_template.content
        assert "((resourceId))" not in email_template.content
        assert "((nonce))" in sms_template.content
        assert "((resourceId))" not in sms_template.content

    def test_sanitizes_run_id_into_resource_id(self, functional_tests_request):
        result = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "notifynl-admin/PR#123 Run!!"},
            _expected_status=201,
        )

        assert result["resourceId"] == "notifynl-admin-pr-123-run"

    def test_missing_run_id_is_400(self, functional_tests_request):
        functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={},
            _expected_status=400,
        )

    def test_run_id_with_no_alphanumeric_characters_is_400(self, functional_tests_request):
        functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "!!!"},
            _expected_status=400,
        )


class TestDeleteFixture:
    def test_auth_required(self, client):
        response = client.delete(url_for("functional_tests.delete_functional_test_fixture", service_id=uuid.uuid4()))
        assert response.status_code == 401

    def test_deletes_service_and_admin_user(self, functional_tests_request):
        created = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "run-to-delete"},
            _expected_status=201,
        )

        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id=created["serviceId"],
            _expected_status=204,
        )

        assert Service.query.filter_by(id=created["serviceId"]).one_or_none() is None
        assert User.query.filter_by(email_address=fixture_email_for_resource("run-to-delete")).one_or_none() is None

    def test_idempotent_when_already_deleted(self, functional_tests_request):
        created = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "run-delete-twice"},
            _expected_status=201,
        )

        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id=created["serviceId"],
            _expected_status=204,
        )
        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id=created["serviceId"],
            _expected_status=204,
        )

    def test_unknown_service_id_is_204(self, functional_tests_request):
        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id=uuid.uuid4(),
            _expected_status=204,
        )

    def test_malformed_service_id_is_204(self, functional_tests_request):
        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id="not-a-uuid",
            _expected_status=204,
        )

    def test_does_not_delete_non_fixture_users_of_the_service(self, functional_tests_request, notify_db_session):
        created = functional_tests_request.post(
            "functional_tests.create_functional_test_fixture",
            _data={"runId": "run-with-extra-user"},
            _expected_status=201,
        )
        service = Service.query.filter_by(id=created["serviceId"]).one()
        other_user = create_user(email="not-a-fixture-user@example.com")
        service.users.append(other_user)
        notify_db_session.commit()

        functional_tests_request.delete(
            "functional_tests.delete_functional_test_fixture",
            service_id=created["serviceId"],
            _expected_status=204,
        )

        assert User.query.filter_by(email_address="not-a-fixture-user@example.com").one_or_none() is not None


class TestListStaleFixtures:
    def test_auth_required(self, client):
        response = client.get(url_for("functional_tests.list_stale_functional_test_fixtures", olderThanMinutes=60))
        assert response.status_code == 401

    def test_missing_query_param_is_400(self, functional_tests_request):
        functional_tests_request.get(
            "functional_tests.list_stale_functional_test_fixtures",
            _expected_status=400,
        )

    def test_non_integer_query_param_is_400(self, functional_tests_request):
        functional_tests_request.get(
            "functional_tests.list_stale_functional_test_fixtures",
            olderThanMinutes="soon",
            _expected_status=400,
        )

    def test_returns_only_stale_fixture_service_ids(self, functional_tests_request):
        with freezegun.freeze_time("2020-01-01T00:00:00"):
            old = functional_tests_request.post(
                "functional_tests.create_functional_test_fixture",
                _data={"runId": "old-run"},
                _expected_status=201,
            )

        with freezegun.freeze_time("2020-01-01T01:05:00"):
            fresh = functional_tests_request.post(
                "functional_tests.create_functional_test_fixture",
                _data={"runId": "fresh-run"},
                _expected_status=201,
            )

        with freezegun.freeze_time("2020-01-01T01:10:00"):
            result = functional_tests_request.get(
                "functional_tests.list_stale_functional_test_fixtures",
                olderThanMinutes=60,
                _expected_status=200,
            )

        assert result["serviceIds"] == [old["serviceId"]]
        assert fresh["serviceId"] not in result["serviceIds"]

    def test_returns_empty_list_when_nothing_stale(self, functional_tests_request):
        result = functional_tests_request.get(
            "functional_tests.list_stale_functional_test_fixtures",
            olderThanMinutes=60,
            _expected_status=200,
        )
        assert result["serviceIds"] == []
