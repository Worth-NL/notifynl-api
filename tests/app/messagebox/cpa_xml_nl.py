"""Builds CPAs in Logius's layout with dummy parties, for the messagebox CPA tests. No certificates, no real ids."""

OWN_OIN = "11111111111111111111"
LOGIUS_OIN = "22222222222222222222"
OWN_ENDPOINT = "https://ebms.example.invalid/ebms"
PREPROD_ENDPOINT = "https://preprod-globe-ebms-internet.procesinfrastructuur.nl/ebXML"
LIVE_ENDPOINT = "https://globe-ebms-internet.procesinfrastructuur.nl/ebXML"


def _party(name, oin, *, endpoint, role, can_send, can_receive, process):
    # one binding per CanSend/CanReceive, the element repeated per action, as in Logius's CPAs (cpp-cpa-2_0.xsd)
    sends = "".join(
        f'<tp:CanSend><tp:ThisPartyActionBinding tp:action="{action}"/></tp:CanSend>' for action in can_send
    )
    receives = "".join(
        f'<tp:CanReceive><tp:ThisPartyActionBinding tp:action="{action}"/></tp:CanReceive>' for action in can_receive
    )
    return f"""
  <tp:PartyInfo tp:partyName="{name}">
    <tp:PartyId tp:type="urn:osb:oin">{oin}</tp:PartyId>
    <tp:CollaborationRole>
      <tp:ProcessSpecification tp:name="{process}"/>
      <tp:Role tp:name="{role}"/>
      <tp:ServiceBinding>
        <tp:Service tp:type="urn:osb:services">MIJNOVERHEID.ebMS.BB.2.0</tp:Service>
        {sends}
        {receives}
      </tp:ServiceBinding>
    </tp:CollaborationRole>
    <tp:Transport><tp:TransportReceiver><tp:Endpoint tp:uri="{endpoint}"/></tp:TransportReceiver></tp:Transport>
  </tp:PartyInfo>"""


def make_cpa_xml(
    *,
    cpa_id="EXAMPLE-EBMS-BB-2-0_0001",
    own_endpoint=OWN_ENDPOINT,
    logius_endpoint=PREPROD_ENDPOINT,
    own_actions=("GLOBE-R-A-Request", "GLOBE-R-BV-Request"),
    logius_receives=("GLOBE-R-A-Request", "GLOBE-R-BV-Request"),
    own_role="SR",
    logius_role="SP",
    process="MijnOverheid_BB_R",
    status="agreed",
    start="2026-01-01T00:00:00Z",
    end="2030-01-01T00:00:00Z",
):
    logius = _party(
        "Logius",
        LOGIUS_OIN,
        endpoint=logius_endpoint,
        role=logius_role,
        can_send=("GLOBE-R-A-Result", "GLOBE-R-BV-Result"),
        can_receive=logius_receives,
        process=process,
    )
    own = _party(
        "Example",
        OWN_OIN,
        endpoint=own_endpoint,
        role=own_role,
        can_send=own_actions,
        can_receive=("GLOBE-R-A-Result", "GLOBE-R-BV-Result"),
        process=process,
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<tp:CollaborationProtocolAgreement xmlns:tp="http://www.oasis-open.org/committees/ebxml-cppa/schema/cpp-cpa-2_0.xsd"
    tp:cpaid="{cpa_id}" tp:version="1.0">
  <tp:Status tp:value="{status}"/>
  <tp:Start>{start}</tp:Start>
  <tp:End>{end}</tp:End>
  {logius}
  {own}
</tp:CollaborationProtocolAgreement>
"""
