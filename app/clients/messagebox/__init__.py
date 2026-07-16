import platform
import socket
from abc import abstractmethod
from time import monotonic

import requests
from urllib3.connection import HTTPConnection

from app.clients import Client, ClientException


class MessageboxClientException(ClientException):
    """Base Exception for MessageboxClient"""


class MessageboxClientNonRetryableException(ClientException):
    """
    Represents an error returned from the email client API with a 4xx response
    code that should not be retried and should instead be marked as technical
    failure.

    An example of this would be an email address that makes it through our
    validation rules but is rejected by the end provider. There is no point in
    retrying this type as it will always fail however many calls to the end
    provider. Whereas a throttling error would not use this exception as it may
    succeed if we retry
    """


class MessageboxClient(Client):
    """Base Messagebox client for sending messagebox messages."""

    def __init__(self, current_app, statsd_client):
        super().__init__()
        self.current_app = current_app
        self.statsd_client = statsd_client

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

    def record_outcome(self, success):
        if success:
            self.current_app.logger.info("Provider request for %s %s", self.name, "succeeded" if success else "failed")
            self.statsd_client.incr(f"clients.{self.name}.success")
        else:
            self.statsd_client.incr(f"clients.{self.name}.error")
            self.current_app.logger.warning(
                "Provider request for %s %s", self.name, "succeeded" if success else "failed"
            )

    def send_messagebox(self, notification_id: str):
        start_time = monotonic()

        try:
            response = self.try_send_messagebox(notification_id)
            self.record_outcome(True)
        except MessageboxClientException as e:
            self.record_outcome(False)
            raise e
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing(f"clients.{self.name}.request-time", elapsed_time)
            self.current_app.logger.info(
                "%s request for %s finished in %s",
                self.name,
                notification_id,
                elapsed_time,
                extra={
                    "provider_name": self.name,
                    "notification_id": notification_id,
                    "elapsed_time": elapsed_time,
                },
            )

        return response

    @abstractmethod
    def try_send_messagebox(self, notification_id: str):
        pass
