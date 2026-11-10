"""
Messagebox CPAs managed by platform admins: validate, upload to ebms-core, and select one per purpose.

A CPA names the endpoint ebms-core sends signed citizen data (BSN and message) to. A wrong or hostile CPA would leak
that data, or send test messages to real citizens, so every upload and selection passes the guardrails below here in
the API, whatever the admin UI shows. The CPA itself stays in ebms-core; only the selection is stored (see
app/models_nl.py::MessageboxCpaSelection).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from ebms_adapter_client import (
    CpaParseError,
    CpaParty,
    CpaSummary,
    EbmsAdapterClientConfig,
    EbmsBadRequestError,
    parse_cpa_summary,
)
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from ebms_adapter_client.cpa import CPA_STATUS_PROPOSED
from flask import current_app

from app.dao.messagebox_cpa_dao_nl import dao_get_messagebox_cpa_selections, dao_set_messagebox_cpa_selection
from app.messagebox.constants import BERICHTENBOX_PROCESS, CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM, CPA_PURPOSES
from app.models_nl import MessageboxCpaSelection

EXPIRY_WARNING_PERIOD = timedelta(days=60)

CHECK_EBMS_CORE = "ebms_core_validation"
CHECK_PARTIES = "parties"
CHECK_OWN_ENDPOINT = "own_endpoint"
CHECK_COUNTERPARTY_ENDPOINT = "counterparty_endpoint"
CHECK_ACTION = "action"
CHECK_STATUS = "status"
CHECK_PERIOD = "period"


class CpaRejected(Exception):
    """The CPA can't be uploaded or selected for this purpose; `assessment` says which guardrails failed."""

    def __init__(self, message: str, assessment: "CpaAssessment | None" = None):
        super().__init__(message)
        self.message = message
        self.assessment = assessment


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    message: str

    def serialize(self) -> dict:
        return {"name": self.name, "passed": self.passed, "message": self.message}


@dataclass(frozen=True)
class CpaAssessment:
    purpose: str
    summary: CpaSummary
    checks: tuple[Check, ...]
    warnings: tuple[str, ...] = ()
    own_party: CpaParty | None = None
    counterparty: CpaParty | None = None

    @property
    def eligible(self) -> bool:
        return all(check.passed for check in self.checks)

    def serialize(self) -> dict:
        return {
            "purpose": self.purpose,
            "eligible": self.eligible,
            "checks": [check.serialize() for check in self.checks],
            "warnings": list(self.warnings),
        }


@dataclass
class CpaListing:
    cpa_id: str
    summary: CpaSummary | None = None
    error: str | None = None
    assessments: dict[str, CpaAssessment] = field(default_factory=dict)
    selected_for: list[str] = field(default_factory=list)

    def serialize(self) -> dict:
        return {
            "cpa_id": self.cpa_id,
            "summary": serialize_summary(self.summary) if self.summary else None,
            "error": self.error,
            "assessments": {purpose: assessment.serialize() for purpose, assessment in self.assessments.items()},
            "selected_for": self.selected_for,
        }


def serialize_summary(summary: CpaSummary) -> dict:
    return {
        "cpa_id": summary.cpa_id,
        "status": summary.status,
        "start": summary.start.isoformat(),
        "end": summary.end.isoformat(),
        "parties": [
            {
                "name": party.name,
                "party_ids": [party_id.qualified for party_id in party.party_ids],
                "endpoints": list(party.endpoints),
                "processes": sorted({role.process for role in party.collaboration_roles if role.process}),
                "can_send": sorted({action for role in party.collaboration_roles for action in role.can_send}),
                "certificates": [
                    {
                        "cert_id": certificate.cert_id,
                        "subject": certificate.subject,
                        "issuer": certificate.issuer,
                        "serial_number": certificate.serial_number,
                        "not_after": certificate.not_after.isoformat() if certificate.not_after else None,
                    }
                    for certificate in party.certificates
                ],
            }
            for party in summary.parties
        ],
    }


def _core_client() -> EbmsCoreClient:
    return EbmsCoreClient(EbmsAdapterClientConfig(base_url=current_app.config["EBMS_ADAPTER_URL"]))


def _allowed_hosts(purpose: str) -> tuple[str, ...]:
    key = {CPA_PURPOSE_LIVE: "EBMS_LIVE_ENDPOINT_HOSTS", CPA_PURPOSE_TEAM: "EBMS_PREPROD_ENDPOINT_HOSTS"}[purpose]
    return tuple(current_app.config.get(key) or ())


def _host_matches(host: str, pattern: str) -> bool:
    """
    Matches label by label, so a `*` stays within one DNS label: `preprod-globe-ebms-*.procesinfrastructuur.nl`
    allows `preprod-globe-ebms-internet.procesinfrastructuur.nl` but not `preprod-globe-ebms-x.attacker.example`.
    """
    host_labels = host.lower().rstrip(".").split(".")
    pattern_labels = pattern.lower().rstrip(".").split(".")
    return len(host_labels) == len(pattern_labels) and all(
        fnmatchcase(label, label_pattern) for label, label_pattern in zip(host_labels, pattern_labels, strict=True)
    )


def _host_allowed(host: str, patterns: tuple[str, ...]) -> bool:
    return any(_host_matches(host, pattern) for pattern in patterns)


def _normalise_endpoint(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme.lower()}://{(parts.netloc or '').lower()}{parts.path.rstrip('/')}"


def _parse(cpa_xml: str) -> CpaSummary:
    try:
        return parse_cpa_summary(cpa_xml)
    except CpaParseError as e:
        raise CpaRejected(str(e)) from e


def _ebms_core_check(core_client: EbmsCoreClient, cpa_xml: str) -> Check:
    try:
        core_client.validate_cpa(cpa_xml)
    except EbmsBadRequestError as e:
        return Check(CHECK_EBMS_CORE, False, f"ebms-core rejects the CPA: {e}")
    return Check(CHECK_EBMS_CORE, True, "ebms-core accepts the CPA")


def _endpoint_matches(endpoint: str, public_endpoint: str) -> bool:
    return _normalise_endpoint(endpoint) == _normalise_endpoint(public_endpoint)


def _own_party(summary: CpaSummary, public_endpoint: str) -> CpaParty | None:
    """The party whose endpoint is this environment's; None unless exactly one party has it."""
    if not public_endpoint:
        return None
    own_parties = [
        party
        for party in summary.parties
        if any(_endpoint_matches(endpoint, public_endpoint) for endpoint in party.endpoints)
    ]
    return own_parties[0] if len(own_parties) == 1 else None


def _parties_check(summary: CpaSummary) -> Check:
    if len(summary.parties) != 2:
        return Check(CHECK_PARTIES, False, f"The CPA has {len(summary.parties)} parties instead of 2")
    return Check(CHECK_PARTIES, True, "The CPA has 2 parties")


def _own_endpoint_check(own_party: CpaParty | None, public_endpoint: str) -> Check:
    if not public_endpoint:
        return Check(CHECK_OWN_ENDPOINT, False, "EBMS_PUBLIC_ENDPOINT isn't configured for this environment")
    if own_party is None:
        return Check(CHECK_OWN_ENDPOINT, False, f"Exactly one party must have our endpoint {public_endpoint}")
    if not all(_endpoint_matches(endpoint, public_endpoint) for endpoint in own_party.endpoints):
        return Check(CHECK_OWN_ENDPOINT, False, f"Our party also lists other endpoints than {public_endpoint}")
    return Check(CHECK_OWN_ENDPOINT, True, f"Our endpoint is {public_endpoint}")


def _counterparty_endpoint_check(counterparty: CpaParty | None, purpose: str) -> Check:
    if counterparty is None:
        return Check(CHECK_COUNTERPARTY_ENDPOINT, False, "The other party couldn't be determined")
    if not counterparty.endpoints or len(counterparty.endpoint_hosts) != len(counterparty.endpoints):
        return Check(CHECK_COUNTERPARTY_ENDPOINT, False, "The other party has no valid endpoint")
    allowed_hosts = _allowed_hosts(purpose)
    if disallowed := [host for host in counterparty.endpoint_hosts if not _host_allowed(host, allowed_hosts)]:
        return Check(
            CHECK_COUNTERPARTY_ENDPOINT,
            False,
            f"{', '.join(disallowed)} isn't allowed for {purpose} (allowed: {', '.join(allowed_hosts) or 'none'})",
        )
    hosts = ", ".join(counterparty.endpoint_hosts)
    return Check(CHECK_COUNTERPARTY_ENDPOINT, True, f"{hosts} is allowed for {purpose}")


def _action() -> str:
    return current_app.config.get("EBMS_BERICHTENBOX_ACTION") or "GLOBE-R-BV-Request"


def _action_check(own_party: CpaParty | None) -> Check:
    action = _action()
    if own_party is not None and own_party.can_send(action, process=BERICHTENBOX_PROCESS):
        return Check(CHECK_ACTION, True, f"Our party can send {action} ({BERICHTENBOX_PROCESS})")
    return Check(CHECK_ACTION, False, f"Our party can't send {action} in process {BERICHTENBOX_PROCESS}")


def _status_check(summary: CpaSummary) -> Check:
    # ebms-core refuses a proposed CPA too (CPAValidator); the check here also covers the overview, which skips it
    if summary.status == CPA_STATUS_PROPOSED:
        return Check(CHECK_STATUS, False, "The CPA is only proposed, not agreed")
    return Check(CHECK_STATUS, True, f"The CPA's status is {summary.status or 'not set'}")


def _period_check(summary: CpaSummary, now: datetime, *, for_selection: bool) -> Check:
    """
    End is exclusive, as in ebms-core. A CPA that hasn't started yet may be uploaded, so it's in ebms-core before the
    day Logius switches to it, but only selected from its Start.
    """
    period = f"from {summary.start:%Y-%m-%d} to {summary.end:%Y-%m-%d}"
    if now >= summary.end:
        return Check(CHECK_PERIOD, False, f"Ended: valid {period}")
    if now < summary.start:
        if for_selection:
            return Check(CHECK_PERIOD, False, f"Not started yet: valid {period}")
        return Check(CHECK_PERIOD, True, f"Valid {period}; it can be selected from {summary.start:%Y-%m-%d}")
    return Check(CHECK_PERIOD, True, f"Valid {period}")


def _expiry_warnings(summary: CpaSummary, now: datetime) -> tuple[str, ...]:
    warn_before = now + EXPIRY_WARNING_PERIOD
    warnings = [f"The CPA ends on {summary.end:%Y-%m-%d}"] if now <= summary.end < warn_before else []
    warnings += [
        f"Certificate {certificate.cert_id} of {party.name} expires on {certificate.not_after:%Y-%m-%d}"
        for party in summary.parties
        for certificate in party.certificates
        if certificate.not_after and certificate.not_after < warn_before
    ]
    return tuple(dict.fromkeys(warnings))


def assess(
    summary: CpaSummary,
    purpose: str,
    *,
    now: datetime | None = None,
    ebms_core_check: Check | None = None,
    for_selection: bool = True,
) -> CpaAssessment:
    """
    Runs the guardrails for one purpose against a parsed CPA. Doesn't call ebms-core itself. With `for_selection`
    false (an upload), a CPA that hasn't started yet passes.
    """
    now = now or datetime.now(UTC)
    public_endpoint = current_app.config.get("EBMS_PUBLIC_ENDPOINT") or ""
    own_party = _own_party(summary, public_endpoint)
    counterparties = summary.other_parties(own_party) if own_party else ()
    counterparty = counterparties[0] if len(counterparties) == 1 else None

    checks = (
        *([ebms_core_check] if ebms_core_check else []),
        _parties_check(summary),
        _own_endpoint_check(own_party, public_endpoint),
        _counterparty_endpoint_check(counterparty, purpose),
        _action_check(own_party),
        _status_check(summary),
        _period_check(summary, now, for_selection=for_selection),
    )
    return CpaAssessment(
        purpose=purpose,
        summary=summary,
        checks=checks,
        warnings=_expiry_warnings(summary, now),
        own_party=own_party,
        counterparty=counterparty,
    )


def validate(cpa_xml: str, purpose: str) -> CpaAssessment:
    """Parses the CPA, has ebms-core validate it and runs the guardrails for the purpose. Stores nothing."""
    summary = _parse(cpa_xml)
    with _core_client() as core_client:
        return assess(summary, purpose, ebms_core_check=_ebms_core_check(core_client, cpa_xml), for_selection=False)


def upload(cpa_xml: str, purpose: str) -> CpaAssessment:
    """Inserts the CPA into ebms-core, only if every guardrail for the purpose passes. Never overwrites a CPA."""
    summary = _parse(cpa_xml)
    with _core_client() as core_client:
        assessment = assess(
            summary, purpose, ebms_core_check=_ebms_core_check(core_client, cpa_xml), for_selection=False
        )
        if not assessment.eligible:
            raise CpaRejected(f"The CPA can't be used for {purpose}", assessment)
        if summary.cpa_id in core_client.list_cpa_ids():
            raise CpaRejected(f"ebms-core already has a CPA with id {summary.cpa_id}", assessment)
        core_client.insert_cpa(cpa_xml, overwrite=False)
    return assessment


def list_cpas() -> list[CpaListing]:
    """Every CPA in ebms-core, with the guardrails per purpose (without ebms-core's own validation) and selections."""
    selected: dict[str, list[str]] = {}
    for selection in dao_get_messagebox_cpa_selections():
        selected.setdefault(selection.cpa_id, []).append(selection.purpose)

    listings = []
    with _core_client() as core_client:
        for cpa_id in core_client.list_cpa_ids():
            listing = CpaListing(cpa_id=cpa_id, selected_for=sorted(selected.get(cpa_id, [])))
            try:
                listing.summary = parse_cpa_summary(core_client.get_cpa(cpa_id))
            except CpaParseError as e:
                listing.error = str(e)
            else:
                listing.assessments = {purpose: assess(listing.summary, purpose) for purpose in CPA_PURPOSES}
            listings.append(listing)
    return listings


def select(purpose: str, cpa_id: str, *, message_type: str, user_id) -> MessageboxCpaSelection:
    """
    Selects a CPA that ebms-core holds for a purpose. The CPA is fetched from ebms-core and checked again here: the
    party ids and action stored with the selection come from the CPA itself, never from the request.
    """
    with _core_client() as core_client:
        if cpa_id not in core_client.list_cpa_ids():
            raise CpaRejected(f"ebms-core has no CPA with id {cpa_id}")
        cpa_xml = core_client.get_cpa(cpa_id)
        assessment = assess(_parse(cpa_xml), purpose, ebms_core_check=_ebms_core_check(core_client, cpa_xml))

    if not assessment.eligible or assessment.own_party is None or assessment.counterparty is None:
        raise CpaRejected(f"The CPA can't be used for {purpose}", assessment)

    return dao_set_messagebox_cpa_selection(
        purpose,
        cpa_id=cpa_id,
        from_party_id=assessment.own_party.party_ids[0].qualified,
        to_party_id=assessment.counterparty.party_ids[0].qualified,
        action=_action(),
        message_type=message_type,
        updated_by_id=user_id,
    )
