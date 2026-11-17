from opentelemetry.metrics import get_meter

_meter = get_meter(__name__)

_envelope_fetch_parse_failures = _meter.create_counter(
    "messagebox.envelope.fetch_parse_failures",
    unit="{envelope}",
    description="Number of ebMS envelopes that could not be fetched or parsed while polling for messagebox status",
)


def record_envelope_fetch_parse_failure() -> None:
    _envelope_fetch_parse_failures.add(1)
