# Delhi pilot OpenStreetMap extract

`delhi_pilot_walkable.geojson` contains 1,362 OSM ways from six small map API windows around CR Park, Welcome Metro, Shalimar Bagh, Tajpur Pahadi/Badarpur, Moolchand/Lajpat Nagar, and Majnu Ka Tila. The exact retrieval windows and source response details are saved in each feature's `properties` and the collection's `metadata`.

The data was fetched from the OSM map API on 29 October 2026. Its XML response did not supply an OSM snapshot timestamp, so the collection date is not represented as a source version. Source: <https://api.openstreetmap.org/api/0.6/map>. License: Open Database License (ODbL) 1.0; attribution: `© OpenStreetMap contributors`. Preserve ODbL attribution/share-alike obligations when redistributing or creating a derivative database.

The importer keeps OSM ways whose `highway` tags are among `footway`, `path`, `pedestrian`, `living_street`, `residential`, `service`, `unclassified`, `tertiary`, `secondary`, `primary`, and `steps`, excluding explicit `foot=no/private`, `access=no/private`, and `motorroad=yes`. This is a map-tag filter, not field verification that a pedestrian path, sidewalk, crossing, or accessible route exists. Six pilot windows do not constitute Delhi-wide coverage. Incidents have not been snapped to these ways.

To re-import the checked GeoJSON into SQLite run `python -m backend.scripts.import_osm_pilot_network`. The command is local and performs no network request. To refresh the source data, first retrieve a new bounded extract with a recorded date and review the tags/licensing; do not overwrite the current snapshot without preserving provenance.
