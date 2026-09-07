# PHP client

## Installatie

```bash
composer require php-http/guzzle7-adapter alphagov/notifications-php-client
```

## Client aanmaken

Geef `baseUrl` mee in de configuratie-array. Zonder deze instelling stuurt de client berichten via de Britse GOV.UK Notify omgeving.

```php
use Alphagov\Notifications\Client;
use Http\Adapter\Guzzle7\Client as GuzzleClient;

$client = new Client([
    'apiKey'     => 'jouw-api-sleutel',
    'baseUrl'    => 'https://api.notifynl.nl',
    'httpClient' => new GuzzleClient(),
]);
```

## SMS versturen

```php
$response = $client->sendSms(
    '+31612345678',
    'jouw-template-id',
    [                           // optioneel: personalisation
        'naam' => 'Jan'
    ],
    'jouw-referentie',          // optioneel
    'jouw-sender-id'            // optioneel
);
```

## E-mail versturen

```php
$response = $client->sendEmail(
    'ontvanger@voorbeeld.nl',
    'jouw-template-id',
    [                           // optioneel: personalisation
        'naam' => 'Jan'
    ],
    'jouw-referentie',          // optioneel
    'reply-to-id'               // optioneel
);
```

## Notificatiestatus ophalen

```php
$notification = $client->getNotification('notificatie-id');
```

## Lijst van notificaties ophalen

```php
$notifications = $client->listNotifications([
    'template_type' => 'sms',           // optioneel
    'status'        => 'delivered',     // optioneel
    'reference'     => 'jouw-referentie' // optioneel
]);
```

## Templates ophalen

```php
// Alle templates
$templates = $client->listTemplates('sms'); // optioneel filter

// Template preview
$preview = $client->previewTemplate(
    'jouw-template-id',
    ['naam' => 'Jan']
);
```
