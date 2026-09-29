import base64
from time import monotonic

import requests
from cryptography.fernet import InvalidToken

from app.clients.letter import (
    Letter,
    LetterClient,
    LetterClientNonRetryableException,
    LetterClientRetryableException,
    LetterSendResult,
)
from app.letters_nl.constants import (
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_BASIC,
    AUTH_METHOD_OAUTH,
    LETTER_PROVIDER_REST_ENDPOINT,
)
from app.letters_nl.url_validation import InvalidLetterEndpointUrl, validate_letter_endpoint_url
from app.utils_nl import get_client_certificate_path

# (connect, read) - the read timeout allows for endpoints that take a while to accept a multi-page PDF
TIMEOUT = (10, 60)
# refresh OAuth tokens this many seconds before they expire
OAUTH_TOKEN_EXPIRY_MARGIN = 60


class RestEndpointLetterClient(LetterClient):
    """
    Sends letters to an organisation's own REST endpoint (e.g. a municipality's print street), configured per
    organisation in OrganisationLetterProvider. The JSON contract is the one notifynl-dvla-service used, so existing
    endpoints work unchanged; `callbackUrl` is new and optional for the endpoint to use.
    """

    name = LETTER_PROVIDER_REST_ENDPOINT

    def __init__(self, current_app, statsd_client):
        super().__init__(current_app, statsd_client)
        # (token_endpoint, client_id) -> (access_token, expires_at as monotonic time)
        self._oauth_tokens: dict[tuple[str, str], tuple[str, float]] = {}

    def try_send_letter(self, letter: Letter, letter_provider) -> LetterSendResult:
        endpoint_url = letter_provider.endpoint_url
        self._validate_url(endpoint_url)
        try:
            auth_config = letter_provider.auth_config or {}
        except (InvalidToken, ValueError) as e:
            raise LetterClientNonRetryableException(
                f"Credentials for organisation {letter.organisation_id} cannot be decrypted", "invalid-credentials"
            ) from e

        headers = {
            "User-Agent": "NotifyNL",
            # lets endpoints that support it ignore a retried request they already accepted
            "Idempotency-Key": letter.notification_id,
            **self._auth_headers(letter_provider.auth_method, auth_config),
        }
        payload = {
            "filename": f"{letter.notification_id}.pdf",
            "content": base64.b64encode(letter.pdf).decode("ascii"),
            "reference": letter.reference,
            "organisationId": letter.organisation_id,
            "notificationId": letter.notification_id,
            "callbackUrl": letter.callback_url,
        }

        response = self._request("POST", endpoint_url, json=payload, headers=headers)

        if response.status_code == 401 and letter_provider.auth_method == AUTH_METHOD_OAUTH:
            # the token may have been revoked before it expired: fetch a new one on the retry
            self._oauth_tokens.pop((auth_config["token_endpoint"], auth_config["client_id"]), None)
            raise LetterClientRetryableException(f"{endpoint_url} rejected the OAuth access token")
        self._raise_for_status(response, endpoint_url)

        return LetterSendResult(provider_reference=_provider_reference(response))

    def _auth_headers(self, auth_method: str, auth_config: dict) -> dict:
        if auth_method == AUTH_METHOD_BASIC:
            credentials = f"{auth_config['username']}:{auth_config['password']}".encode()
            return {"Authorization": f"Basic {base64.b64encode(credentials).decode('ascii')}"}
        if auth_method == AUTH_METHOD_API_KEY:
            return {auth_config["api_key_header"]: auth_config["api_key"]}
        if auth_method == AUTH_METHOD_OAUTH:
            return {"Authorization": f"Bearer {self._get_oauth_token(auth_config)}"}
        raise LetterClientNonRetryableException(f"Unknown auth method {auth_method}", "invalid-credentials")

    def _get_oauth_token(self, auth_config: dict) -> str:
        cache_key = (auth_config["token_endpoint"], auth_config["client_id"])
        cached = self._oauth_tokens.get(cache_key)
        if cached and cached[1] > monotonic():
            return cached[0]

        self._validate_url(auth_config["token_endpoint"])
        data = {
            "grant_type": "client_credentials",
            "client_id": auth_config["client_id"],
            "client_secret": auth_config["client_secret"],
        }
        if auth_config.get("scope"):
            data["scope"] = auth_config["scope"]

        response = self._request("POST", auth_config["token_endpoint"], data=data)
        if not _is_success(response):
            # most likely wrong credentials or a misconfigured token endpoint, which can be fixed in the meantime
            raise LetterClientRetryableException(
                f"Could not get an OAuth access token from {auth_config['token_endpoint']}: {response.status_code}"
            )
        token = response.json()
        expires_in = int(token.get("expires_in") or 300)
        self._oauth_tokens[cache_key] = (
            token["access_token"],
            monotonic() + max(expires_in - OAUTH_TOKEN_EXPIRY_MARGIN, 0),
        )
        return token["access_token"]

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            return self.requests_session.request(
                method,
                url,
                timeout=TIMEOUT,
                allow_redirects=False,
                cert=get_client_certificate_path(url),
                **kwargs,
            )
        except requests.RequestException as e:
            raise LetterClientRetryableException(f"Request to {url} failed: {e}") from e

    @staticmethod
    def _validate_url(url: str):
        # checked again at send time, as DNS can change after the URL was saved
        try:
            validate_letter_endpoint_url(url)
        except InvalidLetterEndpointUrl as e:
            raise LetterClientNonRetryableException(str(e), "invalid-endpoint-url") from e

    @staticmethod
    def _raise_for_status(response: requests.Response, url: str):
        if _is_success(response):
            return
        if response.status_code == 429 or response.status_code >= 500:
            raise LetterClientRetryableException(f"{url} responded with {response.status_code}")
        # includes redirects, which are never followed
        raise LetterClientNonRetryableException(
            f"{url} rejected the letter with {response.status_code}: {response.text[:500]}",
            f"endpoint-http-{response.status_code}",
        )


def _is_success(response: requests.Response) -> bool:
    # not response.ok: that includes redirects, which are never followed
    return 200 <= response.status_code < 300


def _provider_reference(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    reference = body.get("id") if isinstance(body, dict) else None
    return str(reference) if reference else None
