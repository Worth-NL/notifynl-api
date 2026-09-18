import json
from unittest.mock import mock_open

from app import db
from app.commands import sync_org_boundaries_geojson
from tests.app.db import create_organisation


def test_sync_org_boundaries_geojson(notify_db_session, notify_api, mocker):
    org_with_boundary = create_organisation(name="Gemeente Den Haag")
    org_with_boundary.area_boundary = {
        "type": "Polygon",
        "coordinates": [[[4.30, 52.07], [4.32, 52.07], [4.32, 52.09], [4.30, 52.09], [4.30, 52.07]]],
    }
    db.session.commit()

    create_organisation(name="Gemeente Zonder Grens")

    mocker.patch("app.commands.open", mock_open(read_data="fake-token"))
    mocker.patch.dict(
        "os.environ",
        {"KUBERNETES_SERVICE_HOST": "kubernetes.default.svc", "KUBERNETES_SERVICE_PORT": "443"},
    )
    mock_patch = mocker.patch("app.commands.requests.patch")
    mock_patch.return_value.raise_for_status.return_value = None

    notify_api.test_cli_runner().invoke(sync_org_boundaries_geojson)

    assert mock_patch.call_count == 1
    args, kwargs = mock_patch.call_args
    assert args[0] == (
        "https://kubernetes.default.svc:443/api/v1/namespaces/fake-token/configmaps/notifynl-org-boundaries"
    )
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"

    body = json.loads(kwargs["data"])
    feature_collection = json.loads(body["data"]["notifynl-org-boundaries.json"])

    assert feature_collection["type"] == "FeatureCollection"
    assert len(feature_collection["features"]) == 1
    assert feature_collection["features"][0]["properties"]["organisation_name"] == "Gemeente Den Haag"
    assert feature_collection["features"][0]["geometry"] == org_with_boundary.area_boundary
