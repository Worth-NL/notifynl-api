from flask import Blueprint, Response, current_app, redirect, url_for

security_txt = Blueprint("security_txt", __name__)

# RFC 9116 security.txt, based on the repository's SECURITY.md.
# Expires must be renewed before it passes (RFC 9116 advises less than a year ahead).
SECURITY_TXT_EXPIRES = "2027-10-08T00:00:00Z"


@security_txt.route("/.well-known/security.txt", methods=["GET"])
def security_policy():
    canonical = f"{current_app.config['API_HOST_NAME']}/.well-known/security.txt"
    return Response(
        "\n".join(
            [
                "Contact: mailto:info@worth.nl",
                f"Expires: {SECURITY_TXT_EXPIRES}",
                "Preferred-Languages: en, nl",
                "Policy: https://github.com/Worth-NL/notifynl-api/security/policy",
                f"Canonical: {canonical}",
                "",
            ]
        ),
        mimetype="text/plain",
    )


@security_txt.route("/security.txt", methods=["GET"])
def security_policy_legacy():
    return redirect(url_for("security_txt.security_policy"), 301)
