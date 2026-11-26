# Empirical Job-Hunting Conversion Science (v3.0 Reference)

Every skill in Proficiently v3.0 is governed by empirical recruiting datasets, eye-tracking studies, outbound sales/recruiting benchmarks, and modern ATS engineering realities. **Auto-apply every rule below by default.**

---

## 1. Resume Conversion Laws (Eye-Tracking + 125k-Resume Datasets)

1. **The 6–7.4 Second F-Pattern Scan (TheLadders Eye-Tracking)**:
   - Recruiters spend 6–8 seconds on initial triage in an **F-pattern**:
     1. Name + Target Role Headline / Summary (top 25% of Page 1)
     2. Current Company + Current Title + Right-aligned Dates + **First 2 Bullets**
     3. Previous Company + Title + **First Bullet**
     4. Technical / Core Skills block
   - **Auto-Rule**: Always front-load the 2 highest-relevance, highest-metric bullets at the top of the 2 most recent roles. Put the exact target role archetype + top 3 JD hard skills + 1 signature metric in the 2-sentence Summary.

2. **Word Count Sweet Spot (TalentWorks 125,000+ Resume Study)**:
   - **475–600 words** (up to **750 words** for Staff/Principal/Director/VP 2-page profiles) nearly **doubles interview callback rates** compared to <400w (too thin) or >850w (diluted fluff). ~77% of applicants miss this window.

3. **Google X-Y-Z Formula & >=70% Metric Density (Laszlo Bock)**:
   - Only 26% of resumes contain 5+ quantified metrics; 36% have zero.
   - Structure bullets as: **"Accomplished [X outcome] as measured by [Y concrete metric], by doing [Z specific method/tool]."**
   - **Auto-Rule**: At least **70% of bullets** (minimum 6 across the resume) MUST contain hard numbers (`$`, `%`, `ms`, `x`, users, throughput, team size, hours saved, SLA) sourced strictly from the candidate's real history (never fabricated). Keep bullets **14–26 words** (max 2 printed lines).

4. **Boolean Search Parity Without Keyword Stuffing (Greenhouse / Lever / Ashby / Workday)**:
   - Modern ATS queues default to **chronological order** + **Recruiter Boolean Search** (`"Python" AND ("Kubernetes" OR "K8s")`), NOT a mythical secret auto-reject score.
   - Average candidates match only ~51% of JD hard skills.
   - **Auto-Rule**: Match **>=80% of truthful hard skills/tools** from the JD using exact JD spelling, pairing common acronyms once (`Kubernetes (K8s)`, `Continuous Integration (CI/CD)`). Never use white hidden text (flagged as fraud by Ashby/Workday parsers).

5. **Zero-Fluff, Zero-Pronoun, Zero-AI-Tell Law**:
   - Ban first-person pronouns (`I`, `my`, `we`), passive openers (`Responsible for`, `Helped with`, `Worked on`), clichés (`results-driven`, `synergy`, `passionate`, `thought leader`), AI tells (`leveraging`, `utilizing`, `delve`, `spearheaded cross-functional`, `testament`), and prose em-dashes (`—`). Never repeat the same leading action verb twice in one role.

6. **Clean Hyperlinked LinkedIn Slug**:
   - Including a clean LinkedIn link (`linkedin.com/in/firstname-lastname`, without random `-8a92b103` hex suffixes) boosts callbacks **only when LinkedIn and Resume titles/dates match 100%**.

---

## 2. Cold Mail, Outreach & Cover Letter Science (Lavender + Gong Data)

1. **Cold Hiring Manager / Recruiter Email Rules**:
   - **Subject Line**: **3–6 words** (25–48 chars), natural/lowercase peer style (`scaling [system] at [company]`, `quick question re: [role]`). Mobile truncates after ~5 words.
   - **Word Count**: **45–95 words** (hard cap `<110 words`). Emails >150 words cut reply rates by >50%.
   - **Reading Grade Level**: **4th–6th grade** (Flesch-Kincaid <= 7.0). Short 1–2 sentence paragraphs for mobile scanning.
   - **Ego Ratio**: `<=25%` of sentences starting with `"I"`. Lead with *their* product/scaling problem, drop **1 quantified XYZ proof point**, and close with a **low-friction interest CTA** (*"Worth a quick look at how I approached this?"* outperforms calendar-booking demands per Gong data).
   - **Spam Filter Survival**: **NEVER attach PDFs/DOCX on Cold Touch #1** (quarantined by Microsoft Defender / Google Workspace). Send **plain text only**, zero tracking pixels, max 1 clean link, and verify domain MX records before sending.
   - **Follow-Up Cadence**: Day 0 (Value note) → Day 3 (Same-thread 2-sentence bump with micro-observation) → Day 7 (Channel switch: <295-char LinkedIn note) → Day 14 (Polite close-the-loop breakup).

2. **Pain-Hook Cover Letter Rules**:
   - **200–290 words** max. Never open with *"I am writing to apply for..."*.
   - Paragraph 1: Specific company initiative/bottleneck hook.
   - Body: 2–3 quantified XYZ proof bullets mapped directly to JD pain points.
   - Close: Confident peer sign-off.

---

## 3. Form-Fill & Knockout Survival Rules

1. **Knockout Questions Are the Real Auto-Rejector**:
   - Binary/dropdown screening questions in Workday, Greenhouse, and Ashby instantly auto-reject or bucket-hide candidates on a single wrong click.
   - Verify **Work Authorization** vs **Future Sponsorship** wording carefully (avoid double-negative traps).
   - Compute **Years of Experience** numeric fields from earliest defensible production/relevant date in `profile.md` (never leave `0` or blank on required numeric fields).

2. **Salary Expectation Band Anchoring**:
   - When a JD posts a pay-transparency range (`$L – $H`), anchor numeric answers at the **75th percentile** (`L + 0.75 * (H - L)`) — safely inside budget while preserving upside.
   - On text fields: *"Flexible based on total compensation structure; targeting ~$[65th_pct]–$[85th_pct] aligned with role scope."* Never enter `$0`, `$1`, or `$999,999`.

3. **Supplemental Essay Questions ("Why [Company]?", "Biggest Technical Challenge")**:
   - Read by recruiters *before* opening the resume PDF on Ashby and Lever.
   - Answer in **60–110 words** using: **[Specific Company Product/Engineering Detail] + [Candidate XYZ Proof] + [First-90-Day Impact]**.

4. **Source Attribution**:
   - Select `Employee Referral` when referred (triggers priority SLA review), otherwise `Company Website / Careers Page`.

---

## 4. Job Efficiency, Freshness & Triple-Tap Multiplier

1. **First-48-Hour Speed Law**:
   - Applying within **24–48 hours** of posting lands in the recruiter's first chronological review batch before 500+ applicants trigger queue fatigue.
2. **Ghost-Job Filter (18–30% of Online Postings Are Ghost Jobs)**:
   - Deprioritize or skip postings `>30 days old`, aggregator-only listings missing from the company's live ATS board, or vague boilerplate JDs lacking concrete tools/deliverables (unless unlocked via warm internal referral).
3. **The Triple-Tap Protocol (15–28%+ Interview Conversion vs 1–2% Cold Apply)**:
   - Within 24 hours on every P0/P1 role, execute all three touches:
     1. **ATS Portal Apply** (Tailored >=85-score XYZ PDF resume + optimized supplemental answers)
     2. **Internal Referral Ask** (with copy-pasteable 3-bullet forwardable blurb) **OR** **Direct Hiring Manager Plain-Text Value Email**
     3. **LinkedIn Alignment** (100% date/title-consistent profile + <295-char targeted connection note to team peer/recruiter).
