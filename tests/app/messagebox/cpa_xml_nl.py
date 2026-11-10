"""Builds CPAs in Logius's layout with dummy parties, for the messagebox CPA tests. No certificates, no real ids."""

OWN_OIN = "11111111111111111111"
LOGIUS_OIN = "22222222222222222222"
OWN_ENDPOINT = "https://ebms.example.invalid/ebms"
PREPROD_ENDPOINT = "https://preprod-globe-ebms-internet.procesinfrastructuur.nl/ebXML"
LIVE_ENDPOINT = "https://globe-ebms-internet.procesinfrastructuur.nl/ebXML"


def _party(name, oin, *, endpoint, can_send, process):
    sends = "".join(f'<tp:ThisPartyActionBinding tp:action="{action}"/>' for action in can_send)
    return f"""
  <tp:PartyInfo tp:partyName="{name}">
    <tp:PartyId tp:type="urn:osb:oin">{oin}</tp:PartyId>
    <tp:CollaborationRole>
      <tp:ProcessSpecification tp:name="{process}"/>
      <tp:Role tp:name="role"/>
      <tp:ServiceBinding>
        <tp:Service tp:type="urn:osb:services">MIJNOVERHEID.ebMS.BB.2.0</tp:Service>
        <tp:CanSend>{sends}</tp:CanSend>
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
    process="MijnOverheid_BB_R",
    start="2026-01-01T00:00:00Z",
    end="2030-01-01T00:00:00Z",
):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<tp:CollaborationProtocolAgreement xmlns:tp="http://www.oasis-open.org/committees/ebxml-cppa/schema/cpp-cpa-2_0.xsd"
    tp:cpaid="{cpa_id}" tp:version="1.0">
  <tp:Status tp:value="agreed"/>
  <tp:Start>{start}</tp:Start>
  <tp:End>{end}</tp:End>
  {_party("Logius", LOGIUS_OIN, endpoint=logius_endpoint, can_send=("GLOBE-R-BV-Result",), process=process)}
  {_party("Example", OWN_OIN, endpoint=own_endpoint, can_send=own_actions, process=process)}
</tp:CollaborationProtocolAgreement>
"""
