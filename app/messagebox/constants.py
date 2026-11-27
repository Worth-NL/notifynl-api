"""Messagebox constants: CPA purposes, the Berichtenbox process, and why a notification ended in technical-failure."""

# Normal API keys (and jobs/one-offs): Logius's production Berichtenbox.
CPA_PURPOSE_LIVE = "live"
# Team API keys: Logius's pre-production Berichtenbox, for testing on production without reaching real citizens.
CPA_PURPOSE_TEAM = "team"
CPA_PURPOSES = (CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM)

# The MijnOverheid Berichtenbox 2.0 process our sends belong to (Logius's "Technische Aansluithandleiding
# MijnOverheid Berichtenbox"); a CPA for another process names other actions.
BERICHTENBOX_PROCESS = "MijnOverheid_BB_R"

# detailed_status_code of a messagebox notification in technical-failure, i.e. never accepted by Logius. The service
# gets a callback for each, so it can fall back to another channel; check_if_messagebox_still_pending alerts us.
# Rejected before it left ebms-core, e.g. XML failing the Berichtenbox constraints or no CPA selected: a bug or
# misconfiguration on our side.
TECHNICAL_FAILURE_SEND_REJECTED = "messagebox-send-rejected"
# The ebms-adapter stayed unreachable or failing through all of messagebox_deliver's retries.
TECHNICAL_FAILURE_SEND_RETRIES_EXHAUSTED = "messagebox-send-retries-exhausted"
# ebms-core couldn't deliver it to Logius, e.g. an ebMS MessageError for an unknown CPAId.
TECHNICAL_FAILURE_EBMS_DELIVERY_FAILED = "ebms-delivery-failed"
# ebms-core kept retrying until the ebMS TimeToLive passed.
TECHNICAL_FAILURE_EBMS_EXPIRED = "ebms-expired"
