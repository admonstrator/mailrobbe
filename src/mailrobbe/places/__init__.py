"""Places (milestone 20, D240 to D249): where photos were taken, which places the texts name,
where invitations meet, and the maps that show them.

    photos       the metadata step stores a document's GPS position with its other metadata
                 (attachments.metadata.model.summarize, D241); migration 0017 copied the
                 positions read before, so nothing is read from the MBOX files again
    texts        the step places of every import run (phase) gives each place entity a point
                 from the lists shipped in data/ (gazetteer), or says why it has none (D242)
    invitations  the same step reads the location of every calendar event (D243)
    overview     the shipped map of frontend/public/map, with the towns of the gazetteer as its
                 labels (GET /api/map/towns, D244)
    detail map   `mailrobbe map download` (cli, tiles) takes the tiles of a region from a
                 PMTiles file on the internet by range requests into one file in
                 MAILROBBE_MAP_DIR, on request only (D245, D246); api/maps.py serves it

Modules: model (what the step, the API and the runs share: regions, details, size hints, the job's
options and progress), gazetteer (the shipped lists of towns, postcodes and countries: names to
points, the nearest town), phase (the step places), tiles (the extract of a PMTiles file), cli
(`mailrobbe map`).
"""
