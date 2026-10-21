"""Persons (milestone 5, SPEC 5.3, D28 to D33, D160 to D163): root persons, their figures, alias
suggestions, merges.

- roots.py: ROOT, the root person of an address (D28), and lookups by person id
- stats.py: refresh_person_stats, person_stats and person_year of the root persons (D29)
- suggestions.py: refresh_alias_suggestions, pairs that may be the same person, certain or
  uncertain (D30, D160, D161)
- merge.py: merge_persons, merge_certain, undo_merge, undo_batch, unmerge_person,
  dismiss_suggestion, the user's writes, every merge logged (D28, D162, D163)
- sync.py: sync_rows, writing computed rows into a table, only those that change

The refreshes run in the caller's transaction and never commit. aggregates.refresh_aggregates
calls them in dependency order, after the edges of milestone 6 (graph/edges.py), which the
person figures count as contacts.
"""
