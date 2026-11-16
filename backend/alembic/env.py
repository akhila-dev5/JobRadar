from logging.config import fileConfig

from alembic import context

import backend.app.models  # noqa: F401  (registers all tables on Base.metadata)
from backend.app.core.config import get_settings
from backend.app.database.base import Base
from backend.app.database.session import build_engine, resolve_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Allow `alembic -x url=...` for one-off runs, otherwise use the app settings.
    override = context.get_x_argument(as_dictionary=True).get("url")
    return override or resolve_database_url(get_settings())


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
