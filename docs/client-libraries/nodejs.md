# Node.js client

## Installatie

```bash
npm install --save notifications-node-client
```

## Client aanmaken

Geef de NotifyNL API-URL mee als eerste argument, gevolgd door je API-sleutel. Zonder de URL stuurt de client berichten via de Britse GOV.UK Notify omgeving.

```javascript
const NotifyClient = require("notifications-node-client").NotifyClient;

const client = new NotifyClient("https://api.notifynl.nl", "jouw-api-sleutel");
```

## SMS versturen

```javascript
const response = await client.sendSms(
  "jouw-template-id",
  "+31612345678",
  {
    personalisation: { naam: "Jan" },   // optioneel
    reference: "jouw-referentie",       // optioneel
    smsSenderId: "jouw-sender-id"       // optioneel
  }
);
```

## E-mail versturen

```javascript
const response = await client.sendEmail(
  "jouw-template-id",
  "ontvanger@voorbeeld.nl",
  {
    personalisation: { naam: "Jan" },   // optioneel
    reference: "jouw-referentie",       // optioneel
    emailReplyToId: "reply-to-id"       // optioneel
  }
);
```

## Notificatiestatus ophalen

```javascript
const response = await client.getNotificationById("notificatie-id");
```

## Lijst van notificaties ophalen

```javascript
const response = await client.getNotifications(
  "sms",             // optioneel: "sms", "email" of "letter"
  "delivered",       // optioneel status
  "jouw-referentie"  // optioneel
);
```

## Templates ophalen

```javascript
// Alle templates
const response = await client.getAllTemplates("sms"); // optioneel filter

// Template preview
const response = await client.previewTemplateById(
  "jouw-template-id",
  { naam: "Jan" }
);
```
