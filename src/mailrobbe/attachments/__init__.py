"""Attachments and their documents (milestone 9, D70 to D77).

    import      importer.parse records each attachment's metadata and its position in the mail
    finalize    documents.refresh_documents: one document per distinct content (SHA-256),
                figures over the mails carrying it, kind (kinds.classify)
    attachments the import's last phase (phase): reads each document waiting for its text once,
                from one of its occurrences (content.read_attachment), extracts the text in a
                child process with time and memory limits (extract), stores it; document.tsv
                indexes it for the search
    API         api/documents.py: the document list and page, downloads (content)

Modules: kinds (file formats, kinds), content (attachment bytes back from the MBOX files),
documents (assignment and figures), extract (text extraction, one module per format family,
sandboxed), phase (the attachments phase of an import).
"""
