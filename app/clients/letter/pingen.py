from time import monotonic

import requests

from app.clients.letter import (
    Letter,
    LetterClient,
    LetterClientNonRetryableException,
    LetterClientRetryableException,
    LetterSendResult,
)
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN

# Pingen API v2, see https://api.pingen.com/documentation
JSON_API = "application/vnd.api+json"
TIMEOUT = (10, 60)
# refresh the access token (valid for 12 hours) this many seconds before it expires
ACCESS_TOKEN_EXPIRY_MARGIN = 300
# Pingen doesn't have to be told where the address is: our letters have it in the left-hand window
ADDRESS_POSITION = "left"
# access token scopes: sending letters, and managing webhooks (the register-pingen-webhook command)
LETTER_SCOPE = "letter"
WEBHOOK_SCOPE = "webhook"


class PingenClient(LetterClient):
    """
    Sends letters to Pingen with NotifyNL's own Pingen account, the default print provider.

    Letters are created with auto_send: Pingen sends them as soon as it has validated them. Anything that goes wrong
    after that (validation issues, undeliverable) is reported through Pingen's webhooks.
    """

    name = LETTER_PROVIDER_PINGEN

    def __init__(self, current_app, statsd_client):
        super().__init__(current_app, statsd_client)
        # scope -> (access_token, expires_at as monotonic time)
        self._access_tokens: dict[str, tuple[str, float]] = {}

    def try_send_letter(self, letter: Letter, letter_provider) -> LetterSendResult:
        file_url, file_url_signature = self._request_file_upload()
        self._upload_file(file_url, letter.pdf)
        letter_id = self._create_letter(letter, file_url, file_url_signature)
        return LetterSendResult(provider_reference=letter_id)

    def _request_file_upload(self) -> tuple[str, str]:
        response = self._api_request("GET", "/file-upload")
        attributes = response.json()["data"]["attributes"]
        return attributes["url"], attributes["url_signature"]

    def _upload_file(self, file_url: str, pdf: bytes):
        # the raw PDF to the pre-signed URL, without our Authorization header
        try:
            response = self.requests_session.put(file_url, data=pdf, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise LetterClientRetryableException(f"Uploading the letter to Pingen failed: {e}") from e
        if not 200 <= response.status_code < 300:
            # e.g. an expired upload URL: a retry requests a new one
            raise LetterClientRetryableException(f"Uploading the letter to Pingen failed with {response.status_code}")

    def _create_letter(self, letter: Letter, file_url: str, file_url_signature: str) -> str:
        config = self.current_app.config
        body = {
            "data": {
                "type": "letters",
                "attributes": {
                    "file_original_name": f"{letter.notification_id}.pdf",
                    "file_url": file_url,
                    "file_url_signature": file_url_signature,
                    "address_position": ADDRESS_POSITION,
                    "auto_send": True,
                    "delivery_product": config["PINGEN_DELIVERY_PRODUCT"],
                    "print_mode": config["PINGEN_PRINT_MODE"],
                    "print_spectrum": config["PINGEN_PRINT_SPECTRUM"],
                },
            }
        }
        response = self._api_request(
            "POST",
            f"/organisations/{config['PINGEN_ORGANISATION_ID']}/deliveries/letters",
            json=body,
            # a retried create (e.g. after a timeout) returns the letter created the first time instead of a new one
            headers={"Idempotency-Key": f"notifynl-letter-{letter.notification_id}"},
        )
        return response.json()["data"]["id"]

    def list_webhooks(self) -> list[dict]:
        """The webhooks of our Pingen organisation, as dicts of id, event_category, url and signing_key."""
        response = self._api_request(
            "GET",
            f"/organisations/{self.current_app.config['PINGEN_ORGANISATION_ID']}/webhooks",
            params={"page[limit]": 100},
            scope=WEBHOOK_SCOPE,
        )
        return [{"id": webhook["id"], **webhook["attributes"]} for webhook in response.json()["data"]]

    def create_webhook(self, event_category: str, url: str, signing_key: str) -> str:
        response = self._api_request(
            "POST",
            f"/organisations/{self.current_app.config['PINGEN_ORGANISATION_ID']}/webhooks",
            json={
                "data": {
                    "type": "webhooks",
                    "attributes": {"event_category": event_category, "url": url, "signing_key": signing_key},
                }
            },
            scope=WEBHOOK_SCOPE,
        )
        return response.json()["data"]["id"]

    def _api_request(
        self, method: str, path: str, headers: dict | None = None, scope: str = LETTER_SCOPE, **kwargs
    ) -> requests.Response:
        url = f"{self.current_app.config['PINGEN_API_URL']}{path}"
        try:
            response = self.requests_session.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self._get_access_token(scope)}",
                    "Accept": JSON_API,
                    **({"Content-Type": JSON_API} if "json" in kwargs else {}),
                    **(headers or {}),
                },
                timeout=TIMEOUT,
                **kwargs,
            )
        except requests.RequestException as e:
            raise LetterClientRetryableException(f"Request to Pingen {method} {path} failed: {e}") from e

        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 401:
            self._access_tokens.pop(scope, None)
            raise LetterClientRetryableException(f"Pingen rejected the access token for {method} {path}")
        # 409: a request with the same idempotency key is still in progress; 424: a Pingen dependency is down
        if response.status_code in (409, 424, 429) or response.status_code >= 500:
            raise LetterClientRetryableException(f"Pingen {method} {path} responded with {response.status_code}")
        raise LetterClientNonRetryableException(
            f"Pingen {method} {path} was rejected with {response.status_code}: {_error_detail(response)}",
            f"pingen-http-{response.status_code}",
        )

    def _get_access_token(self, scope: str) -> str:
        access_token, expires_at = self._access_tokens.get(scope, (None, 0.0))
        if access_token and expires_at > monotonic():
            return access_token

        config = self.current_app.config
        try:
            response = self.requests_session.post(
                f"{config['PINGEN_IDENTITY_URL']}/auth/access-tokens",
                data={
                    "grant_type": "client_credentials",
                    "client_id": config["PINGEN_CLIENT_ID"],
                    "client_secret": config["PINGEN_CLIENT_SECRET"],
                    "scope": scope,
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise LetterClientRetryableException(f"Getting a Pingen access token failed: {e}") from e
        if not 200 <= response.status_code < 300:
            # most likely missing or wrong credentials, which can be fixed while the letter is retried
            raise LetterClientRetryableException(f"Getting a Pingen access token failed with {response.status_code}")

        token = response.json()
        expires_at = monotonic() + max(int(token["expires_in"]) - ACCESS_TOKEN_EXPIRY_MARGIN, 0)
        self._access_tokens[scope] = (token["access_token"], expires_at)
        return token["access_token"]


def _error_detail(response: requests.Response) -> str:
    try:
        errors = response.json()["errors"]
        return "; ".join(f"{error.get('title')}: {error.get('detail')}" for error in errors)
    except (ValueError, KeyError, TypeError):
        return response.text[:500]
