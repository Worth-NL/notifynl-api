# Python client

## Installatie

```bash
pip install notifications-python-client
```

## Client aanmaken

Geef altijd de NotifyNL API-URL mee als `base_url`, anders gaat het verkeer naar de Britse GOV.UK Notify omgeving.

```python
from notifications_python_client.notifications import NotificationsAPIClient

client = NotificationsAPIClient(
    api_key="jouw-api-sleutel",
    base_url="https://api.notifynl.nl"
)
```

## SMS versturen

```python
response = client.send_sms_notification(
    phone_number="+31612345678",
    template_id="jouw-template-id",
    personalisation={          # optioneel
        "naam": "Jan"
    },
    reference="jouw-referentie",   # optioneel
    sms_sender_id="jouw-sender-id" # optioneel
)
```

## E-mail versturen

```python
response = client.send_email_notification(
    email_address="ontvanger@voorbeeld.nl",
    template_id="jouw-template-id",
    personalisation={           # optioneel
        "naam": "Jan"
    },
    reference="jouw-referentie",  # optioneel
    email_reply_to_id="reply-to-id"  # optioneel
)
```

## Notificatiestatus ophalen

```python
response = client.get_notification_by_id("notificatie-id")
```

## Lijst van notificaties ophalen

```python
response = client.get_all_notifications(
    template_type="sms",  # optioneel: "sms", "email" of "letter"
    status="delivered",   # optioneel
    reference="jouw-referentie"  # optioneel
)
```

## Templates ophalen

```python
# Alle templates
response = client.get_all_templates(template_type="sms")  # optioneel filter

# Specifiek template met preview
response = client.post_template_preview(
    template_id="jouw-template-id",
    personalisation={"naam": "Jan"}
)
```
