---
name: mailbox
description: Scan user's IMAP mailbox for recruiter & hiring manager replies, classify interviews/offers/rejections to auto-update the job pipeline, and send MX-verified plain-text outreach via SMTP with an explicit approval queue
argument-hint: "'scan-inbox', 'queue', 'send', or 'configure'"
---

# Mailbox Automation Skill (Single-Provider 2FA-Safe OAuth2 + Custom Mail API)

Close the loop on outreach and applications cleanly through **EXACTLY ONE active mail provider** — designed to work natively with **Google 2FA/Passkeys** and **Microsoft Authenticator/2FA** without complex manual IMAP/SMTP setup.

## Supported Single Providers (Choose One in `00 // Get Started` or `05 // Mailbox & Sent`)

1. **Google (Gmail)** — **Sign in with Google** (OAuth 2.0 + PKCE `S256` → official **Gmail REST API** for inbox reply scanning & plain-text sending).
2. **Microsoft (Outlook / M365)** — **Sign in with Microsoft** (OAuth 2.0 + PKCE `S256`, no client secret required → official **Microsoft Graph API**).
3. **Yahoo Mail** — Yahoo OAuth 2.0 (`XOAUTH2`) or Yahoo 2FA App Password.
4. **Proton Mail** — **Proton Mail Bridge** local loopback TLS (`127.0.0.1:1143` / `1025`, 2FA native).
5. **Custom Mail API** — Custom HTTP REST API (presets for **Resend**, **Postmark**, or custom send/inbox JSON endpoints with Bearer/Header API key).

## Capabilities

- **Inbox Reply Monitor (`scan-inbox`)**: Classifies replies (`interview_invite`, `recruiter_screen`, `assessment`, `offer`, `rejection`, `auto_reply`, `follow_up_needed`) and auto-updates matching job stages in `employmaxing.db`.
- **Transparent Plain-Text Outbox (`queue` + `send`)**: Scores drafts against Lavender/Gong rules (`45–95w`, `3–6w` subject, `0 attachments` on Touch #1), verifies live DNS MX gateways, logs exact `facts_used`, supports `--dry-run`, and enforces a safe daily rate limit (`20/day`).
