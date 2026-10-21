"""Exports for lawyers and archives (milestone 8, D62, D63); api/exports.py serves them.

- records.py: what an export says about a mail, read from the database in batches
- pdf.py: one mail as PDF, a reading copy in the DejaVu Sans font of fonts/
- manifest.py: manifest.json (its models are the format) and manifest.csv
- readme.py: LIESMICH.txt
- bundle.py: the ZIP of an export as a stream, and the record of its first download
"""
