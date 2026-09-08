"""Metrorail Western Cape timetables, read out of PRASA's published PDFs.

Separate from ``gabs_scraper`` because almost nothing is shared. Golden Arrow publishes
text PDFs whose grids ``pdfplumber`` reads directly; PRASA publishes pictures of grids,
so every departure time here has to be recognised rather than parsed, and checked
afterwards against the one thing a timetable cannot do - run backwards.

What the two do share is the database. Both load into the same route / timetable /
schedule / trip / stop_time tables, tagged by operator, which is what lets one planner
answer for both.
"""
