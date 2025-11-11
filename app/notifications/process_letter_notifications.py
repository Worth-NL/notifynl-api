import base64

from flask import current_app
from notifications_utils.recipient_validation.postal_address import PostalAddress

from app import create_random_identifier, statsd_client
from app.clients.letter.dvla import DVLAClient
from app.constants import LETTER_TYPE
from app.notifications.process_notifications import persist_notification


def create_letter_notification(
    letter_data,
    template,
    service,
    api_key,
    status,
    reply_to_text=None,
    billable_units=None,
    updated_at=None,
    postage=None,
):
    """
    Create a letter notification and send it immediately via DVLA client
    using a hardcoded PDF. This bypasses the batch process.
    """

    # Persist the notification
    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=PostalAddress.from_personalisation(letter_data["personalisation"]).normalised,
        service=service,
        personalisation=letter_data["personalisation"],
        notification_type=LETTER_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        job_id=None,
        job_row_number=None,
        reference=create_random_identifier(),
        client_reference=letter_data.get("reference"),
        status=status,
        reply_to_text=reply_to_text,
        billable_units=billable_units,
        postage=postage or letter_data.get("postage") or template.postage,
        updated_at=updated_at,
    )

    # Instantiate DVLA client inside the function
    dvla_client = DVLAClient(application=current_app, statsd_client=statsd_client)

    # Reconstruct address from notification personalisation
    address = PostalAddress.from_personalisation(notification.personalisation)

    # Hardcoded PDF (replace with your base64 string)
    pdf_base64 = """placehere"""
    pdf_file = base64.b64decode(pdf_base64)

    # Send immediately
    try:
        dvla_client.send_letter(
            notification_id=str(notification.id),
            reference=notification.reference,
            address=address,
            postage=notification.postage,
            service_id=service.id,
            organisation_id=service.id,
            pdf_file=pdf_file,
            callback_url="http://host.docker.internal:7072/api/SendLetter",
        )
    except Exception as e:
        current_app.logger.exception("Failed to send letter immediately: %s", e)

    return notification
