"""
Configuration overrides for NotifyNL
"""

import os

from config import Config as ConfigUK

NL_PREFIX = "notifynl"


class Config(ConfigUK):
    """
    Overrides for NotifyNL usage
    """

    NOTIFY_EMAIL_DOMAIN = os.environ.get("NOTIFY_EMAIL_DOMAIN", "notifynl.nl")
    FROM_NUMBER = os.environ.get("FROM_NUMBER", "NOTIFYNL")
    NOTIFY_SUPPORT_EMAIL_ADDRESS = "info@worth.nl"

    # Spryng setup
    SPRYNG_URL = os.environ.get("SPRYNG_URL", "https://rest.spryngsms.com/v1/messages")
    SPRYNG_API_KEY = os.getenv("SPRYNG_API_KEY")
    # Spryng Callback URL for delivery receipts
    # At the moment, Spryng only supports callbacks to a URL configured on their
    # dashboard
    # SPRYNG_RECEIPT_URL = os.getenv("SPRYNG_RECEIPT_URL")

    # Client-side SSL setup
    # NOTE: For mTLS setup, trusted certificates should be added to the system certificates.
    # For a custom bundle to be used, override the CURL_CA_BUNDLE environment variable.
    SSL_CERT_DIR = os.getenv("SSL_CERT_DIR", "/ssl")

    # these should always add up to 100%
    SMS_PROVIDER_RESTING_POINTS = {"mmg": 0, "firetext": 0, "spryng": 100}

    ########################
    # Template overrides ###
    ########################
    # See:
    # - migrations_nl/versions/0001_add_notifynl_templates.py
    # - migrations_nl/versions/0002_additional_notifynl_templates.py
    ALREADY_REGISTERED_EMAIL_TEMPLATE_ID = "bb3c17a8-6009-4f67-a943-353982c15c98"
    BROADCAST_INVITATION_EMAIL_TEMPLATE_ID = "86761e21-b39c-43e1-a06b-a3340bc2bc7a"
    CHANGE_EMAIL_CONFIRMATION_TEMPLATE_ID = "9eefb5bf-f1fb-46ce-9079-691260b0af9b"
    EMAIL_2FA_TEMPLATE_ID = "320a5f19-600f-451e-9646-11206c69828d"
    INVITATION_EMAIL_TEMPLATE_ID = "b24bf0fa-dd64-4105-867c-4ed529e12df3"
    NEW_USER_EMAIL_VERIFICATION_TEMPLATE_ID = "afd325cd-c83e-4b0b-8426-7acb9c0aa62b"
    ORGANISATION_INVITATION_EMAIL_TEMPLATE_ID = "dfd254da-39d1-468f-bd0d-2c9e017c13a6"
    PASSWORD_RESET_TEMPLATE_ID = "4cc48b09-62d0-473f-8514-3023b306a0fb"
    REPLY_TO_EMAIL_ADDRESS_VERIFICATION_TEMPLATE_ID = "2e542078-1b7e-4640-ab44-57e5db6b3bf3"
    SERVICE_NOW_LIVE_TEMPLATE_ID = "ec92ba79-222b-46f1-944a-79b3c072234d"
    SMS_CODE_TEMPLATE_ID = "f8209d70-9aa2-4a8c-89f9-00514492fa27"

    # Dutch phones
    # TODO: To be fixed with unit tests
    # SIMULATED_SMS_NUMBERS = ("+31612345678", "+31623456789", "+31634567890")


class Development(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False

    SERVER_NAME = os.getenv("SERVER_NAME")

    REDIS_ENABLED = os.getenv("REDIS_ENABLED") == "1"

    NOTIFY_ENVIRONMENT = "development"

    S3_BUCKET_CSV_UPLOAD = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-notifications-csv-upload"
    S3_BUCKET_CONTACT_LIST = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-contact-list"
    S3_BUCKET_TEST_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-test-letters"
    S3_BUCKET_LETTERS_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-pdf"
    S3_BUCKET_LETTERS_SCAN = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-scan"
    S3_BUCKET_INVALID_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-invalid-pdf"
    S3_BUCKET_TRANSIENT_UPLOADED_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-transient-uploaded-letters"
    S3_BUCKET_LETTER_SANITISE = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-sanitise"

    INTERNAL_CLIENT_API_KEYS = {
        Config.ADMIN_CLIENT_ID: ["dev-notify-secret-key"],
        Config.FUNCTIONAL_TESTS_CLIENT_ID: ["functional-tests-secret-key"],
    }

    SECRET_KEY = "dev-notify-secret-key"
    DANGEROUS_SALT = "dev-notify-salt"

    MMG_INBOUND_SMS_AUTH = ["testkey"]
    MMG_INBOUND_SMS_USERNAME = ["username"]

    NOTIFY_EMAIL_DOMAIN = "dev.notifynl.nl"

    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "postgresql://localhost/notification_api")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    ANTIVIRUS_ENABLED = os.getenv("ANTIVIRUS_ENABLED") == "1"

    API_HOST_NAME = os.getenv("API_HOST_NAME", "http://localhost:6011")
    API_HOST_NAME_INTERNAL = os.getenv("API_HOST_NAME_INTERNAL", "http://localhost:6011")
    API_RATE_LIMIT_ENABLED = True
    DVLA_EMAIL_ADDRESSES = ["success@simulator.amazonses.com"]

    CBC_PROXY_ENABLED = False

    REGISTER_FUNCTIONAL_TESTING_BLUEPRINT = True

    FROM_NUMBER = "development"


class Test(Development):
    NOTIFY_EMAIL_DOMAIN = "test.notifynl.nl"
    FROM_NUMBER = "testing"
    NOTIFY_ENVIRONMENT = "test"
    TESTING = True

    S3_BUCKET_CSV_UPLOAD = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-notifications-csv-upload"
    S3_BUCKET_CONTACT_LIST = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-contact-list"
    S3_BUCKET_TEST_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-test-letters"
    S3_BUCKET_LETTERS_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-pdf"
    S3_BUCKET_LETTERS_SCAN = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-scan"
    S3_BUCKET_INVALID_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-invalid-pdf"
    S3_BUCKET_TRANSIENT_UPLOADED_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-transient-uploaded-letters"
    S3_BUCKET_LETTER_SANITISE = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-sanitise"

    # when testing, the SQLALCHEMY_DATABASE_URI is used for the postgres server's location
    # but the database name is set in the _notify_db fixture
    SQLALCHEMY_RECORD_QUERIES = True

    CELERY = {**Config.CELERY, "broker_url": "you-forgot-to-mock-celery-in-your-tests://", "broker_transport": None}

    ANTIVIRUS_ENABLED = True

    API_RATE_LIMIT_ENABLED = True
    API_HOST_NAME = "http://localhost:6011"
    API_HOST_NAME_INTERNAL = "http://localhost:6011"

    SMS_INBOUND_WHITELIST = ["203.0.113.195"]
    FIRETEXT_INBOUND_SMS_AUTH = ["testkey"]
    TEMPLATE_PREVIEW_API_HOST = "http://localhost:9999"

    MMG_URL = "https://example.com/mmg"
    FIRETEXT_URL = "https://example.com/firetext"

    CBC_PROXY_ENABLED = True
    DVLA_EMAIL_ADDRESSES = ["success@simulator.amazonses.com", "success+2@simulator.amazonses.com"]

    DVLA_API_BASE_URL = "https://test-dvla-api.com"

    REGISTER_FUNCTIONAL_TESTING_BLUEPRINT = True

    SEND_LETTERS_ENABLED = True

    SEND_ZENDESK_ALERTS_ENABLED = True


class Acceptance(Config):
    NOTIFY_EMAIL_DOMAIN = "acc.notifynl.nl"
    FROM_NUMBER = "acceptance"
    NOTIFY_ENVIRONMENT = "acceptance"

    S3_BUCKET_CSV_UPLOAD = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-notifications-csv-upload"
    S3_BUCKET_CONTACT_LIST = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-contact-list"
    S3_BUCKET_TEST_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-test-letters"
    S3_BUCKET_LETTERS_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-pdf"
    S3_BUCKET_LETTERS_SCAN = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-scan"
    S3_BUCKET_INVALID_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-invalid-pdf"
    S3_BUCKET_TRANSIENT_UPLOADED_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-transient-uploaded-letters"
    S3_BUCKET_LETTER_SANITISE = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-sanitise"


class Production(Config):
    DEBUG = False

    NOTIFY_EMAIL_DOMAIN = "notifynl.nl"
    FROM_NUMBER = "NOTIFYNL"
    NOTIFY_ENVIRONMENT = "production"

    S3_BUCKET_CSV_UPLOAD = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-notifications-csv-upload"
    S3_BUCKET_CONTACT_LIST = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-contact-list"
    S3_BUCKET_TEST_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-test-letters"
    S3_BUCKET_LETTERS_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-pdf"
    S3_BUCKET_LETTERS_SCAN = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-scan"
    S3_BUCKET_INVALID_PDF = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-invalid-pdf"
    S3_BUCKET_TRANSIENT_UPLOADED_LETTERS = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-transient-uploaded-letters"
    S3_BUCKET_LETTER_SANITISE = f"{NL_PREFIX}-{NOTIFY_ENVIRONMENT}-letters-sanitise"
