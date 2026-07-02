# Ruby client

## Installatie

Voeg toe aan je `Gemfile`:

```ruby
gem "notifications-ruby-client"
```

Installeer daarna:

```bash
bundle install
```

Of direct via gem:

```bash
gem install notifications-ruby-client
```

## Client aanmaken

Geef de NotifyNL API-URL mee als tweede argument. Zonder de URL stuurt de client berichten via de Britse GOV.UK Notify omgeving.

```ruby
require "notifications/client"

client = Notifications::Client.new("jouw-api-sleutel", "https://api.notifynl.nl")
```

## SMS versturen

```ruby
response = client.send_sms(
  phone_number:  "+31612345678",
  template_id:   "jouw-template-id",
  personalisation: { naam: "Jan" },      # optioneel
  reference: "jouw-referentie",          # optioneel
  sms_sender_id: "jouw-sender-id"        # optioneel
)
```

## E-mail versturen

```ruby
response = client.send_email(
  email_address: "ontvanger@voorbeeld.nl",
  template_id:   "jouw-template-id",
  personalisation: { naam: "Jan" },      # optioneel
  reference: "jouw-referentie",          # optioneel
  email_reply_to_id: "reply-to-id"       # optioneel
)
```

## Notificatiestatus ophalen

```ruby
notification = client.get_notification("notificatie-id")
```

## Lijst van notificaties ophalen

```ruby
notifications = client.get_notifications(
  template_type: "sms",            # optioneel
  status: "delivered",             # optioneel
  reference: "jouw-referentie"     # optioneel
)
```

## Templates ophalen

```ruby
# Alle templates
templates = client.get_all_templates(template_type: "sms") # optioneel

# Template preview
preview = client.post_template_preview(
  "jouw-template-id",
  personalisation: { naam: "Jan" }
)
```
