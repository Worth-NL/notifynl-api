# Letter providers (provider_details.identifier, notification_type "letter")
LETTER_PROVIDER_PINGEN = "pingen"
LETTER_PROVIDER_REST_ENDPOINT = "rest-endpoint"
LETTER_PROVIDERS = [LETTER_PROVIDER_PINGEN, LETTER_PROVIDER_REST_ENDPOINT]

# Auth methods for the REST endpoint letter provider
AUTH_METHOD_BASIC = "basic"
AUTH_METHOD_API_KEY = "api_key"
AUTH_METHOD_OAUTH = "oauth"
AUTH_METHODS = [AUTH_METHOD_BASIC, AUTH_METHOD_API_KEY, AUTH_METHOD_OAUTH]

# Fields of an organisation's auth config (stored encrypted) that must be set for each auth method
REQUIRED_AUTH_CONFIG_FIELDS = {
    AUTH_METHOD_BASIC: ("username", "password"),
    AUTH_METHOD_API_KEY: ("api_key_header", "api_key"),
    AUTH_METHOD_OAUTH: ("token_endpoint", "client_id", "client_secret"),
}
OPTIONAL_AUTH_CONFIG_FIELDS = {
    AUTH_METHOD_BASIC: (),
    AUTH_METHOD_API_KEY: (),
    AUTH_METHOD_OAUTH: ("scope",),
}
# Never returned by the API, only ever written
SECRET_AUTH_CONFIG_FIELDS = frozenset({"password", "api_key", "client_secret"})

DEFAULT_API_KEY_HEADER = "X-Api-Key"

# Pingen's envelopes need the address block 60mm from the top; a REST endpoint's config sets its own placement
PINGEN_ADDRESS_PLACEMENT = "60mm"
ADDRESS_PLACEMENTS = ["50mm", "60mm"]

# Where a REST endpoint reports back on a letter it accepted (app/notifications/letter_provider_callback.py)
LETTER_PROVIDER_CALLBACK_PATH = "/notifications/letter/provider-status"
