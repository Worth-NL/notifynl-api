# .NET client (C#)

## Installatie

```bash
dotnet add package GovukNotify
```

Of via de NuGet Package Manager:

```
nuget install GovukNotify
```

## Client aanmaken

Geef de NotifyNL API-URL mee als eerste argument, gevolgd door je API-sleutel. Zonder de URL stuurt de client berichten via de Britse GOV.UK Notify omgeving.

```csharp
using Notify.Client;

var client = new NotificationClient("https://api.notifynl.nl", "jouw-api-sleutel");
```

## SMS versturen

```csharp
var personalisation = new Dictionary<string, dynamic>
{
    { "naam", "Jan" }
};

SmsNotificationResponse response = client.SendSms(
    mobileNumber: "+31612345678",
    templateId: "jouw-template-id",
    personalisation: personalisation,  // optioneel
    reference: "jouw-referentie",      // optioneel
    smsSenderId: "jouw-sender-id"      // optioneel
);
```

## E-mail versturen

```csharp
EmailNotificationResponse response = client.SendEmail(
    emailAddress: "ontvanger@voorbeeld.nl",
    templateId: "jouw-template-id",
    personalisation: personalisation,  // optioneel
    reference: "jouw-referentie",      // optioneel
    emailReplyToId: "reply-to-id"      // optioneel
);
```

## Notificatiestatus ophalen

```csharp
Notification notification = client.GetNotificationById("notificatie-id");
```

## Lijst van notificaties ophalen

```csharp
NotificationList notifications = client.GetNotifications(
    templateType: "sms",            // optioneel: "sms", "email" of "letter"
    status: "delivered",            // optioneel
    reference: "jouw-referentie"    // optioneel
);
```

## Templates ophalen

```csharp
// Alle templates
TemplateList templates = client.GetAllTemplates("sms"); // optioneel filter

// Template preview
TemplatePreview preview = client.GenerateTemplatePreview(
    "jouw-template-id",
    personalisation
);
```

## Gebruik met dependency injection

Bij gebruik van `IHttpClientFactory` in ASP.NET Core:

```csharp
services.AddHttpClient<INotificationClient, NotificationClient>((httpClient, sp) =>
{
    return new NotificationClient(
        new HttpClientWrapper(httpClient),
        "jouw-api-sleutel"
    );
});
```

> **Let op:** Bij gebruik van `HttpClientWrapper` wordt de base URL ingesteld via `httpClient.BaseAddress` — stel dan `https://api.notifynl.nl` in als base address op de `HttpClient`.
