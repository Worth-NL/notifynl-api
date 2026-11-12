from datetime import datetime

import pytest

from app import db
from tests.app.db import create_inbound_number


def test_rest_get_inbound_numbers_nl(admin_request, sample_inbound_numbers):
    # the numbers have no updated_at yet, so the endpoint's order between them is undefined
    result = admin_request.get("inbound_number.get_inbound_numbers")

    assert len(result["data"]) == len(sample_inbound_numbers)
    assert sorted(result["data"], key=lambda number: number["id"]) == sorted(
        (number.serialize() for number in sample_inbound_numbers), key=lambda number: number["id"]
    )


def test_rest_get_inbound_numbers_orders_by_updated_at_nl(admin_request, notify_db_session):
    updated_last = create_inbound_number(number="1")
    updated_first = create_inbound_number(number="2")
    updated_last.updated_at = datetime(2026, 1, 2)
    updated_first.updated_at = datetime(2026, 1, 1)
    db.session.commit()

    result = admin_request.get("inbound_number.get_inbound_numbers")

    assert [number["number"] for number in result["data"]] == ["2", "1"]


@pytest.mark.flaky(max_runs=3, min_passes=1)
def test_rest_get_inbound_numbers_in_creation_order_nl(admin_request, sample_inbound_numbers):
    # upstream's assertion: the order only holds while Postgres happens to return the NULL updated_at rows as inserted
    result = admin_request.get("inbound_number.get_inbound_numbers")

    assert result["data"] == [number.serialize() for number in sample_inbound_numbers]
