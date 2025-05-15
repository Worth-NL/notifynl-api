# NotifyNL migrations

Uses [Flask-Alembic](https://flask-alembic.readthedocs.io/en/latest/).

#### Run the NL migrations
```sh
flask db upgrade -d migrations_nl
```

#### Create a new revision (version)

```sh
./scripts/create_nl_migration.sh "<short description>"
```

#### Manually create a new revision (version) if the above script fails

```sh
flask db revision -d migrations_nl --rev-id <4 digit revision number> -m "<short description>"
```