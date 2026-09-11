"""The same database connection the other two scrapers use.

Re-exported rather than duplicated: one DSN, one driver choice, one place to change it.
"""
from gabs_scraper.db import connect  # noqa: F401
