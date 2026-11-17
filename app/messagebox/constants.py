"""Messagebox CPA purposes: which Collaboration-Protocol Agreement a messagebox notification is sent under."""

# Normal API keys (and jobs/one-offs): Logius's production Berichtenbox.
CPA_PURPOSE_LIVE = "live"
# Team API keys: Logius's pre-production Berichtenbox, for testing on production without reaching real citizens.
CPA_PURPOSE_TEAM = "team"
CPA_PURPOSES = (CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM)

# The MijnOverheid Berichtenbox 2.0 process our sends belong to (Logius's "Technische Aansluithandleiding
# MijnOverheid Berichtenbox"); a CPA for another process names other actions.
BERICHTENBOX_PROCESS = "MijnOverheid_BB_R"
