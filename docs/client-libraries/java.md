# Java client

## Installatie

Voeg de dependency toe aan je `pom.xml` (Maven):

```xml
<dependency>
    <groupId>uk.gov.service.notify</groupId>
    <artifactId>notifications-java-client</artifactId>
    <version>5.2.1-RELEASE</version>
</dependency>
```

Of voor Gradle:

```gradle
implementation 'uk.gov.service.notify:notifications-java-client:5.2.1-RELEASE'
```

## Client aanmaken

Geef de NotifyNL API-URL mee als tweede argument. Zonder de URL stuurt de client berichten via de Britse GOV.UK Notify omgeving.

```java
import uk.gov.service.notify.NotificationClient;

NotificationClient client = new NotificationClient(
    "jouw-api-sleutel",
    "https://api.notifynl.nl"
);
```

## SMS versturen

```java
import uk.gov.service.notify.SendSmsResponse;
import java.util.HashMap;

HashMap<String, Object> personalisation = new HashMap<>();
personalisation.put("naam", "Jan");

SendSmsResponse response = client.sendSms(
    "jouw-template-id",
    "+31612345678",
    personalisation,        // optioneel, null als niet nodig
    "jouw-referentie",      // optioneel, null als niet nodig
    "jouw-sender-id"        // optioneel, null als niet nodig
);
```

## E-mail versturen

```java
import uk.gov.service.notify.SendEmailResponse;

SendEmailResponse response = client.sendEmail(
    "jouw-template-id",
    "ontvanger@voorbeeld.nl",
    personalisation,        // optioneel, null als niet nodig
    "jouw-referentie",      // optioneel, null als niet nodig
    "reply-to-id"           // optioneel, null als niet nodig
);
```

## Notificatiestatus ophalen

```java
import uk.gov.service.notify.Notification;

Notification notification = client.getNotificationById("notificatie-id");
```

## Lijst van notificaties ophalen

```java
import uk.gov.service.notify.NotificationList;

NotificationList notifications = client.getNotifications(
    "sms",              // optioneel: "sms", "email" of "letter"
    "delivered",        // optioneel status
    "jouw-referentie",  // optioneel
    null                // optioneel: older_than (notificatie-id)
);
```

## Templates ophalen

```java
import uk.gov.service.notify.Template;
import uk.gov.service.notify.TemplateList;
import uk.gov.service.notify.TemplatePreview;

// Alle templates
TemplateList templates = client.getAllTemplates("sms"); // optioneel filter

// Template preview
TemplatePreview preview = client.generateTemplatePreview(
    "jouw-template-id",
    personalisation
);
```
