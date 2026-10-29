from app.constants import CacheKeys


def test_get_usage_updated_at(admin_request, sample_service, mocker):
    redis_get = mocker.patch("app.redis_store.get", return_value=b"2026-10-29T12:00:00+00:00")

    json_response = admin_request.get("billing.get_usage_updated_at", service_id=sample_service.id)

    assert json_response == {"updated_at": "2026-10-29T12:00:00+00:00"}
    redis_get.assert_called_once_with(CacheKeys.FT_BILLING_FOR_TODAY_UPDATED_AT_UTC_ISOFORMAT)


def test_get_usage_updated_at_before_the_first_hourly_update(admin_request, sample_service, mocker):
    mocker.patch("app.redis_store.get", return_value=None)

    json_response = admin_request.get("billing.get_usage_updated_at", service_id=sample_service.id)

    assert json_response == {"updated_at": None}
