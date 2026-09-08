"""The same database connection the Golden Arrow scraper uses.

Re-exported rather than duplicated: one DSN, one driver choice, one place to change it.
"""
from gabs_scraper.db import connect  # noqa: F401
