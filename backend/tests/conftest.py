import os

# The original test suite exercises the OpenStreetMap/OSRM providers; the Mappls
# integration has its own tests that switch this back to "mappls".
os.environ.setdefault("NAVIRA_MAP_PROVIDER", "legacy")
os.environ.setdefault("NAVIRA_SOS_WATCHDOG", "0")
