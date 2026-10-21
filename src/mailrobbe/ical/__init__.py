"""Calendar invitations (milestone 14, D154, D155): the events of iCalendar parts.

    mail, attachment       phase.waiting: mails without a calendar_scan row of the current
          |                CALENDAR_VERSION; model's candidate rule (an iCalendar attachment, a
          |                subject or text of invitations) decides which of them are read
          v
    read_message           phase, step calendar: each candidate read from its MBOX file, every
          |                text/calendar part and iCalendar attachment parsed
          v
    calendar_event, calendar_attendee, calendar_scan   replaced per mail; figures in
                                                       global_stats 'calendar'

- model.py: kinds (event_kind), limits and CalendarFigures
- phase.py: the import's calendar phase (waiting, scan_calendar)

api/events.py shows the events in the detail, the mail list and the person profile;
api/filters.py filters them (event, event_uid).
"""
