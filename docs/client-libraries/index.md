# NotifyNL Client Libraries

NotifyNL biedt officiële client libraries voor de meestgebruikte programmeertalen. Deze libraries zijn gebaseerd op de [GOV.UK Notify clients](https://github.com/alphagov) en werken standaard met de GOV.UK Notify API.

> **Belangrijk:** Je moet bij elke client de NotifyNL API-URL meegeven: `https://api.notifynl.nl`  
> Zonder deze instelling stuurt de client berichten via de Britse GOV.UK Notify omgeving.

## Beschikbare clients

| Taal | Pakket | Documentatie |
|------|--------|--------------|
| Java | `uk.gov.service.notify:notifications-java-client` | [Java](java.md) |
| .NET (C#) | `GovukNotify` | [.NET](dotnet.md) |
| Node.js | `notifications-node-client` | [Node.js](nodejs.md) |
| PHP | `alphagov/notifications-php-client` | [PHP](php.md) |
| Python | `notifications-python-client` | [Python](python.md) |
| Ruby | `notifications-ruby-client` | [Ruby](ruby.md) |

## API-sleutel

Je hebt een API-sleutel nodig om de client te gebruiken. Deze vind je in het [NotifyNL dashboard](https://app.notifynl.nl) onder **API-integratie**.

Er zijn drie typen sleutels:

| Type | Beschrijving |
|------|-------------|
| **Live** | Verstuurt echte berichten |
| **Team & gasten** | Verstuurt alleen naar geverifieerde adressen/nummers |
| **Test** | Simuleert verzending zonder echte berichten te sturen |
