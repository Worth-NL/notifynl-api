import os
from functools import partial

from sentry_sdk.integrations.boto3 import Boto3Integration
from sentry_sdk.integrations.celery import CeleryIntegration


def sentry_sampler(sampling_context, sample_rate: float = 0.0):
    if sampling_context["parent_sampled"]:
        return 1

    return sample_rate


def init_performance_monitoring():
    environment = os.getenv("NOTIFY_ENVIRONMENT").lower()
    sentry_enabled = bool(int(os.getenv("SENTRY_ENABLED", "0")))
    sentry_dsn = os.getenv("SENTRY_DSN")

    allow_pii = os.getenv("SENTRY_ALLOW_PII", "0") == "1"

    if environment and sentry_enabled and sentry_dsn:
        import sentry_sdk

        error_sample_rate = float(os.getenv("SENTRY_ERRORS_SAMPLE_RATE", 0.0))
        trace_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", 0.0))

        send_pii = True if allow_pii else False
        send_request_bodies = "medium" if allow_pii else "never"

        traces_sampler = partial(sentry_sampler, sample_rate=trace_sample_rate)

        try:
            from app.version import __git_commit__

            release = __git_commit__
        except ImportError:
            release = None

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=environment,
            sample_rate=error_sample_rate,
            send_default_pii=send_pii,
            max_request_body_size=send_request_bodies,
            traces_sampler=traces_sampler,
            enable_logs=True,
            # We explicitly enable the celery integration here so that we can toggle `monitor_beat_tasks` on (default
            # is off). This doesn't stop a number of other integrations being automatically enabled, eg Flask, Redis,
            # SQLAlchemy. Boto3Integration is explicit too: it spans every S3/SQS call (including kombu's own SQS
            # broker polling, not just deliberate app-level S3 writes) -- noisy, but the alternative is no visibility
            # at all into whether a given notification's S3 writes/queue dispatches actually happened.
            integrations=[CeleryIntegration(monitor_beat_tasks=True), Boto3Integration()],
            release=release,
        )

        if app_name := os.getenv("NOTIFY_APP_NAME"):
            sentry_sdk.set_tag("app", app_name)
