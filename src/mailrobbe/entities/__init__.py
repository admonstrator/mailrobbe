"""Entities found in the texts of the archive (milestone 10, D80 to D89).

    texts      the subject and text of every mail (model.scanned_text, from the database) and
               the extracted text of every document (milestone 9); nothing is read from the
               MBOX files
    extract    extract.extract_entities: one text to its entities, local and deterministic
               (patterns, gazetteers in data/, the word fields and context words of themes.toml)
    entities   the import's last phase (phase): every mail and document text not scanned by
               the current ENTITY_VERSION is scanned in worker processes, its mentions replace
               the earlier ones (mail_entity, document_entity) and the scan is recorded
               (mail_entity_scan, document_entity_scan); a stop keeps what is stored
    figures    figures.refresh_entity_figures: mails, documents, first and last date per entity,
               at the end of the phase
    API        api/entities.py: the entity list and page, the facets of the mail list, the
               entities of one mail; api/filters.py: the mail list's entity and amount filters

An entity found in a document counts for every mail carrying the document (mentions.mentions).

Modules: model (the contract between extraction, phase and API), mentions (the mentions of mails
and documents as one relation), extract (with one module per family of kinds), phase, figures.
"""
