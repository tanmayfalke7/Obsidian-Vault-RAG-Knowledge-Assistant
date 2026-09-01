"""
Neo4j driver singleton.

Creates one driver for the application lifetime and exposes a session factory.
All callers should use `get_driver()` or `get_session()`.
"""
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from neo4j import GraphDatabase, Driver, Session

logger = logging.getLogger(__name__)

_driver: Optional[Driver] = None


def init_driver(uri: str, username: str, password: str) -> Driver:
    """Initialise the module-level driver. Safe to call multiple times."""
    global _driver
    if _driver is not None:
        return _driver

    logger.info("Initialising Neo4j driver → %s", uri)
    _driver = GraphDatabase.driver(uri, auth=(username, password))
    return _driver


def get_driver() -> Driver:
    """Return the initialised driver, raising if not yet initialised."""
    if _driver is None:
        raise RuntimeError(
            "Neo4j driver has not been initialised. "
            "Call init_driver() before using the database."
        )
    return _driver


def close_driver() -> None:
    """Close the driver cleanly (call on application shutdown)."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed.")


def verify_connectivity() -> bool:
    """Return True if the Neo4j connection is healthy."""
    try:
        driver = get_driver()
        driver.verify_connectivity()
        logger.info("Neo4j connectivity verified.")
        return True
    except Exception as e:
        logger.error("Neo4j connectivity check failed: %s", e)
        return False


@contextmanager
def get_session(database: str = "neo4j") -> Generator[Session, None, None]:
    """Context manager yielding a Neo4j session for the given database."""
    driver = get_driver()
    session = driver.session(database=database)
    try:
        yield session
    finally:
        session.close()


def run_query(
    cypher: str,
    parameters: Optional[dict] = None,
    database: str = "neo4j",
) -> list[dict]:
    """Execute a read/write Cypher query and return results as dicts."""
    params = parameters or {}
    with get_session(database=database) as session:
        result = session.run(cypher, params)
        return [dict(record) for record in result]
