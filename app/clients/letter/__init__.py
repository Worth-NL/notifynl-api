import platform
import socket
from abc import abstractmethod
from dataclasses import dataclass
from time import monotonic

import requests
from urllib3.connection import HTTPConnection
from urllib3.exceptions import MaxRetryError

from app.clients import Client, ClientException


class LetterClientException(ClientException):
    """Base exception for letter (print provider) clients"""


class LetterClientRetryableException(LetterClientException):
    """
    A temporary failure (network, throttling, provider downtime): the send can be retried. `may_have_been_accepted`
    says whether the provider may have accepted the letter anyway (e.g. a timeout waiting for its response), in which
    case it must only be retried with the same provider.
    """

    def __init__(self, message: str, may_have_been_accepted: bool = False):
        super().__init__(message)
        self.may_have_been_accepted = may_have_been_accepted


def may_have_reached_the_provider(error: requests.RequestException) -> bool:
    """
    Whether a request that failed with `error` may have been received by the provider anyway. With requests' default
    of no retries, urllib3 only wraps an error in MaxRetryError when it couldn't connect (refused, DNS, connect timeout,
    TLS handshake): errors after the request went out (a read timeout, the connection closed) are raised as they are.
    """
    return not (isinstance(error, requests.ConnectionError) and error.args and isinstance(error.args[0], MaxRetryError))


class LetterClientNonRetryableException(LetterClientException):
    """
    The print provider rejected the letter or the configuration is unusable: retrying won't help, the letter should be
    marked as failed with `detailed_status_code`.
    """

    def __init__(self, message: str, detailed_status_code: str):
        super().__init__(message)
        self.detailed_status_code = detailed_status_code


@dataclass(frozen=True)
class Letter:
    notification_id: str
    # the reference the print provider gets: the client reference or the generated one, as chosen by the caller
    reference: str
    organisation_id: str
    pdf: bytes
    postage: str
    callback_url: str | None = None


@dataclass(frozen=True)
class LetterSendResult:
    # the provider's id for the letter, if it returned one
    provider_reference: str | None = None


class LetterClient(Client):
    """
    Base client for handing letters to a print provider. A successful send means the provider accepted the letter;
    printing and posting happen afterwards and are reported back through a callback, if the provider supports it.
    """

    def __init__(self, current_app):
        super().__init__()
        self.current_app = current_app

        self.requests_session = requests.Session()
        if platform.system() == "Linux":
            for adapter in self.requests_session.adapters.values():
                adapter.poolmanager.connection_pool_kw = {
                    "socket_options": HTTPConnection.default_socket_options
                    + [
                        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
                        (socket.SOL_TCP, socket.TCP_KEEPIDLE, 4),
                        (socket.SOL_TCP, socket.TCP_KEEPINTVL, 2),
                        (socket.SOL_TCP, socket.TCP_KEEPCNT, 8),
                    ],
                    **adapter.poolmanager.connection_pool_kw,
                }

    def record_outcome(self, success: bool, notification_id: str):
        extra = {"notification_id": notification_id, "provider_name": self.name}
        if success:
            self.current_app.logger.info("Provider request for %s succeeded", self.name, extra=extra)
        else:
            self.current_app.logger.warning("Provider request for %s failed", self.name, extra=extra)

    def send_letter(self, letter: Letter, letter_provider) -> LetterSendResult:
        start_time = monotonic()

        try:
            result = self.try_send_letter(letter, letter_provider)
            self.record_outcome(True, letter.notification_id)
        except LetterClientException:
            self.record_outcome(False, letter.notification_id)
            raise
        finally:
            elapsed_time = monotonic() - start_time
            self.current_app.logger.info(
                "%s request for %s finished in %s",
                self.name,
                letter.notification_id,
                elapsed_time,
                extra={
                    "provider_name": self.name,
                    "notification_id": letter.notification_id,
                    "elapsed_time": elapsed_time,
                },
            )

        return result

    @abstractmethod
    def try_send_letter(self, letter: Letter, letter_provider) -> LetterSendResult:
        """`letter_provider` is the organisation's OrganisationLetterProvider, or None for the default (Pingen)."""
