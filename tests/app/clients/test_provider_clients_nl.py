from app import notification_provider_clients
from app.clients.letter.pingen import PingenClient
from app.clients.letter.rest_endpoint import RestEndpointLetterClient


def test_letter_clients_are_registered(notify_api):
    assert isinstance(notification_provider_clients.get_client_by_name_and_type("pingen", "letter"), PingenClient)
    assert isinstance(
        notification_provider_clients.get_client_by_name_and_type("rest-endpoint", "letter"), RestEndpointLetterClient
    )
    assert notification_provider_clients.get_client_by_name_and_type("dvla", "letter") is None
