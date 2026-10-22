"""Protected and packed attachments (milestone 19, D230 to D239): passwords.

candidates: password candidates in a text (D234). order: the tiers a document is tried in (D235).
store: the one place writing the password tables. phase: the import's passwords step. Trying a
password and decrypting are attachments.protected; the containers are unpacked by
attachments.containers (the archives step); api.passwords serves the typed-in passwords.
"""
