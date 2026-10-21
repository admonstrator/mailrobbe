"""The relationship map (SPEC 5.4, decisions D36 to D39).

- edges.py: refresh_edges recomputes edge, edge_year and person.kind from the imported mails,
  for the whole archive or for some persons after a merge
- excerpt.py: the excerpt of the counted graph that /api/graph shows (D37)
- graphml.py: GraphML for Gephi, shared by the excerpt download and the full export (D38)
- cli.py: `mailrobbe graph refresh` and `mailrobbe graph export`
"""
