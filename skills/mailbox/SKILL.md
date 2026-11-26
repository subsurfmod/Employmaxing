---
name: mailbox
description: Scan user's IMAP mailbox for recruiter & hiring manager replies, classify interviews/offers/rejections to auto-update the job pipeline, and send MX-verified plain-text outreach via SMTP with an explicit approval queue
argument-hint: "'scan-inbox', 'queue', 'send', or 'configure'"
---

# Mailbox Automation Skill (IMAP Reply Scanner + SMTP Sender)

Close the loop on outreach and applications directly against the user's mailbox.

## Capabilities

1. **Configure Local Credentials (`chmod 600`)**:
   ```bash
   ./bin/employmaxing mail configure --provider gmail --email you@gmail.com --password "<app-password>" --display-name "Your Name"
   ```
   Supports Gmail, Outlook/M365, Fastmail, iCloud, and custom IMAP/SMTP servers (or `EMPLOYMAXING_MAIL_USER` / `EMPLOYMAXING_MAIL_PASS` env vars).

2. **Check Mailbox for Replies (`scan-inbox`)**:
   ```bash
   ./bin/employmaxing mail scan-inbox --days 14
   ```
   - Matches replies via `In-Reply-To` threads, sent recipient domains, tracked company names, and ATS senders.
   - Classifies each message: `interview_invite`, `recruiter_screen`, `assessment`, `offer`, `rejection`, `auto_reply`, or `follow_up_needed`.
   - Automatically advances matching jobs in `employmaxing.db` and surfaces urgent interview invites in the Web Dashboard.

3. **Transparent Plain-Text Sending (`queue` + `send`)**:
   - Scores every email via Lavender/Gong rules (`45–95w`, `3–6w` subject, `0 attachments` on Touch #1), checks live DNS MX records, records `facts_used`, and places it in the Outbox approval queue.
   - Always supports `--dry-run` and enforces a safe daily send rate limit (`20/day`) with jitter spacing.
