"""
Lets functional/smoke tests complete admin login without reading a real
inbox. `VerifyCode._code` (app/models.py) is bcrypt-hashed and genuinely
unreadable after creation -- there is no way to recover the code a normal
`POST /user/<id>/email-code` call already sent, so this mints a second,
independent code instead. `get_user_code` (app/dao/users_dao.py) accepts
any valid, unexpired, unused code for the user, not just the most recent
one, so the pending code from a real sign-in-form submission is simply left
unused (and expires normally) rather than conflicting with this one.
"""

import uuid

from flask import current_app

from app.dao.users_dao import get_user_by_id
from app.user.rest import _create_2fa_url, create_2fa_code


def create_functional_test_2fa_link(user_id: str) -> str:
    """
    Creates a fresh email-auth VerifyCode for the user and returns the same
    signed magic-link URL a real /email-code call would have emailed --
    without needing to read any inbox. The underlying notification is still
    queued for delivery for consistency with the normal flow, but for a
    fixture user (whose email is the deliberately-undeliverable
    smoke-test.notifynl.invalid domain -- see fixtures.py) it's expected to
    fail/bounce in the background; that's harmless since verification only
    checks the DB-stored code, never delivery success.
    """
    user = get_user_by_id(user_id=user_id)
    secret_code = str(uuid.uuid4())
    url = _create_2fa_url(
        user, secret_code, next_redirect=None, email_auth_link_host=current_app.config.get("ADMIN_BASE_URL")
    )
    create_2fa_code(
        current_app.config["EMAIL_2FA_TEMPLATE_ID"],
        user,
        secret_code,
        user.email_address,
        {"name": user.name, "url": url},
    )
    return url
