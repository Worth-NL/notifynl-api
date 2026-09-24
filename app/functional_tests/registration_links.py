"""
Lets functional/smoke tests complete self-registration's email-verification
step and an invite's acceptance step without reading a real inbox -- same
motivation as two_factor.py, but for two different signed-URL builders.
Both are pure functions (no DB-stored code to mint fresh, unlike VerifyCode):
the token embeds its payload directly and is verified by re-signing and
comparing, so simply calling the same builder a real send would have used
returns an identical, genuinely valid link.
"""

from flask import current_app

from app.dao.users_dao import get_user_by_email
from app.errors import InvalidRequest
from app.models import InvitedUser
from app.service_invite.rest import invited_user_url
from app.user.rest import _create_verification_url


def create_functional_test_verification_link(email_address: str) -> str:
    user = get_user_by_email(email_address)
    return _create_verification_url(user, base_url=current_app.config.get("ADMIN_BASE_URL"))


def create_functional_test_invite_link(email_address: str) -> str:
    invited_user = (
        InvitedUser.query.filter_by(email_address=email_address).order_by(InvitedUser.created_at.desc()).first()
    )
    if invited_user is None:
        raise InvalidRequest(f"No invited user found for {email_address}", 404)
    return invited_user_url(invited_user.id, invite_link_host=current_app.config.get("ADMIN_BASE_URL"))
