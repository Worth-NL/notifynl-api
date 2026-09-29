import glob
import importlib.util
import pathlib

from sqlalchemy import text

from app.models_nl import OrganisationLetterProvider
from tests.app.db import create_organisation
from tests.app.db_nl import create_organisation_letter_provider


def _load_nl_migration(filename_prefix):
    (path,) = glob.glob(f"migrations_nl/versions/{filename_prefix}_*.py")
    spec = importlib.util.spec_from_file_location(pathlib.Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nl_migrations_form_a_single_chain():
    migrations = sorted(glob.glob("migrations_nl/versions/*.py"))
    revisions = [_load_nl_migration(pathlib.Path(m).stem.split("_")[0]) for m in migrations]

    assert revisions[0].down_revision is None
    for previous, current in zip(revisions, revisions[1:], strict=False):
        assert current.down_revision == previous.revision


def test_nl_migrations_are_applied_up_to_the_head(notify_db_session):
    head = pathlib.Path(sorted(glob.glob("migrations_nl/versions/*.py"))[-1]).stem.split("_")[0]

    assert notify_db_session.execute(text("select version_num from alembic_version_nl")).scalar() == head


def test_letter_providers_are_ordered_after_dvla(notify_db_session):
    priorities = dict(
        notify_db_session.execute(
            text("select identifier, priority from provider_details where notification_type = 'letter'")
        ).all()
    )

    assert priorities["pingen"] > priorities["dvla"]
    assert priorities["rest-endpoint"] > priorities["dvla"]


def test_backfill_assigns_pingen_to_every_organisation_once(notify_db_session):
    backfill = text(_load_nl_migration("0030").BACKFILL_PINGEN_LETTER_PROVIDER)
    without_provider = create_organisation(name="without provider")
    with_rest_endpoint = create_organisation(name="with rest endpoint")
    create_organisation_letter_provider(
        with_rest_endpoint, "rest-endpoint", endpoint_url="https://print.example.com/letters"
    )

    notify_db_session.execute(backfill)
    notify_db_session.execute(backfill)

    providers = {
        row.organisation_id: (row.provider.identifier, row.address_placement)
        for row in OrganisationLetterProvider.query.all()
    }
    assert providers == {
        without_provider.id: ("pingen", "60mm"),
        with_rest_endpoint.id: ("rest-endpoint", "60mm"),
    }
