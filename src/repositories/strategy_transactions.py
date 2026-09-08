"""Serialize strategy read/modify/write operations on the application's SQLite DB."""


def begin_strategy_write(session):
    """Reserve the writer before reading so concurrent workers see committed state.

    The caller owns commit/rollback and must use a fresh session. A process-local
    lock would not protect independent scheduler processes.
    """
    if session.get_bind().dialect.name != "sqlite":
        raise NotImplementedError("Strategy write serialization requires SQLite")
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
