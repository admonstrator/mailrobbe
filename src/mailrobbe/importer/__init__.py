"""MBOX importer (SPEC 3.5, milestone 2).

    scan (main process)        find MBOX files below MAILROBBE_MBOX_DIR, keep mbox_file rows
      -> per file, in one of N worker processes, from mbox_file.bytes_done to the end:
         split.iter_records    -> parse.parse_record -> DKIM check (dkim_hook)
                               -> store: one transaction per batch, including bytes_done
      -> finalize (main)       duplicates, threads, display names, aggregates

Every batch commits its mails together with the file's progress, so an interrupted import
resumes at the last committed record and never stores a mail twice. Raw mails never reach the
database (SPEC 2): it gets metadata, byte offsets and the text for the full text index.

A run holds the import lock and records itself in `job` (mailrobbe.jobrun, D47): its phase
(scan, import, finalize), live figures every few seconds, and how it ended. A stop
request from the dashboard ends it like Ctrl-C.

Modules: split (MBOX framing), parse (one message -> ParsedMail), text (charsets, encoded
words, HTML), model (types between parse and store), dkim_hook (seam to milestone 3), scan,
store, runner (worker pool, resume, live figures),
finalize, cli.
"""
