"""The timeline (milestone 11, D90 to D95): the mail list's matching mails over time.

    filters     api/timeline.py takes the conditions of the mail list (mails._where,
                filters.resolve_contents), so every filter of MailFilters holds as there
    days        PostgreSQL counts the matching mails per UTC day, the undated ones apart; a
                series counts the mails of one person, one thread or one search string as well
    axis        buckets: from date_from or the earliest mail to date_to or the archive's end,
                by day, ISO week or month (chosen by the span, coarsened above
                MAX_TIMELINE_BUCKETS), the days summed into the buckets
    marks       marks: buckets far above or below the moving mean, and series that fall
                silent, for the total and every series
    first       api/timeline.py: per root person the earliest matching mail it takes part in

Nothing is stored: every request counts from mail and participation under the count budget of
the mail list (D19), so the timeline works on every archive already imported. buckets and marks
are pure (dates and counts in, dates and counts out).
"""
