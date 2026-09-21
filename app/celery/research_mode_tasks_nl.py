"""
NL override: research-mode handling for the spryng SMS provider.

Spryng's real callback (app/notifications/notifications_sms_callback.py's
process_spryng_response) is a GET with STATUS/REASONCODE/REFERENCE query
params -- unlike mmg/firetext's POST body, which research_mode_tasks.py's
shared make_request() already handles. Kept self-contained here rather than
extending make_request() with a GET path, since that function is shared with
upstream's mmg/firetext callbacks and should stay untouched.
"""

import requests
from flask import current_app

from app.celery.research_mode_tasks import perm_fail, requests_session, temp_fail
from app.constants import SMS_TYPE


def send_spryng_response(reference, to):
    api_call = f"{current_app.config['API_HOST_NAME_INTERNAL']}/notifications/{SMS_TYPE}/spryng"
    params = spryng_callback(reference, to)

    try:
        response = requests_session.request("GET", api_call, params=params, timeout=60)  # type: ignore[attr-defined]
        response.raise_for_status()
    except requests.HTTPError as e:
        current_app.logger.error(
            "API GET request on %s failed with status %s",
            api_call,
            e.response.status_code,
            extra={"url": api_call, "status_code": e.response.status_code},
        )
        raise e
    finally:
        current_app.logger.info("Mocked provider callback request finished")
    return response.json()


def spryng_callback(notification_id, to):
    """
    STATUS 10 - delivered
    STATUS 20 - permanent failure

    Mirrors app/clients/sms/spryng.py's spryng_response_map, which only
    models these two outcomes -- unlike mmg/firetext, Spryng has no distinct
    temporary-failure status here, so temp_fail also maps to STATUS 20.
    """
    if to.strip().endswith(perm_fail) or to.strip().endswith(temp_fail):
        status, reasoncode = "20", "22"  # "Delivery failure"
    else:
        status, reasoncode = "10", "0"  # "No error"

    return {
        "STATUS": status,
        "REASONCODE": reasoncode,
        "REFERENCE": notification_id,
    }
