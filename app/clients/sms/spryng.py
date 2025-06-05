import json
import logging

from requests import RequestException, request

from app.clients.sms import SmsClient, SmsClientResponseException

logger = logging.getLogger(__name__)

spryng_response_map = {
    "10": {"status": "delivered", "reasoncode": {"0": "No error"}},
    "20": {
        "status": "permanent-failure",
        "reasoncode": {
            "20": "Recipient number unreachable",
            "21": "Recipient number incorrect",
            "22": "Delivery failure",
            "31": "The recipient is blacklisted",
            "32": "The originator is not registered for this country",
        },
    },
}


def get_spryng_responses(status, detailed_status_code=None):
    return (
        spryng_response_map[status]["status"],
        spryng_response_map[status]["reasoncode"].get(detailed_status_code, None),
    )


class SpryngClient(SmsClient):
    """
    Spryng sms client.
    """

    name = "spryng"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = self.current_app.config.get("SPRYNG_API_KEY")
        self.url = self.current_app.config.get("SPRYNG_URL")
        self.receipt_url = self.current_app.config.get("SPRYNG_RECEIPT_URL")

    def try_send_sms(self, to, content, reference, international, sender):
        data = {
            "originator": sender,
            "recipients": [to.replace("+", "")],
            "body": content,
            "reference": reference,
            "route": "business",
            "encoding": "unicode",
        }

        try:
            response = request(
                "POST",
                self.url,
                data=json.dumps(data),
                timeout=60,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            )

            response.raise_for_status()

            try:
                json.loads(response.text)

                if response.status_code != 200:
                    raise ValueError("Expected 'status code' to be '200'")
            except (ValueError, AttributeError) as e:
                raise SmsClientResponseException("Invalid response JSON") from e
        except RequestException as e:
            raise SmsClientResponseException("Request failed") from e

        return response
