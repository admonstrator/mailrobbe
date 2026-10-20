"""DKIM verification (SPEC 3.4).

- model.py: DnsAnswer, KeySource, SignatureResult, MailVerdict (plain, picklable data)
- verify.py: verify_mail(raw, keys), pure, never raises
- override.py: the DNS override table for tests and generated data
- resolver.py: real DNS (dnspython), reserved TLDs, offline mode, the in-process key cache
- checker.py: DkimChecker, one per process: verify_mail with the cached key source
- store.py: dkim_result, dns_cache and mail.dkim_status in PostgreSQL
- recheck.py, cli.py: `mailrobbe dkim`, checking imported mails again from their MBOX files
"""
