# Serbia Post-Election Monitor

A daily monitor of state-level political change in Serbia after the 25 October 2026
parliamentary election. It collects Serbian and international press (and, from stage 4,
social media), codes each story with AI against a fixed codebook, and publishes a reviewed
daily brief, an alert focus box and running trackers to one static GitHub Pages page shared
by link, plus a dated PDF extract for external stakeholders.

Claude Code reads this file at the start of every session. The **staged plan at the end is
the work plan**: work through it in order and tick items off as they are done. Do not start
a later stage until the earlier stage's "done when" line is true. Keep this file current
when a decision changes.

## What readers need

Audience: business people and international officials (embassies, think tanks) who must
navigate the transition without reading Serbian media. Each morning they need:

1. **Brief**: the five to eight developments of the last 24 hours, one paragraph each, with a
   "why it matters" line written for an outsider.
2. **Alert focus box**: items in the alert categories since the last brief, ranked by
   severity. A fixed spot at the top of the page, not a push notification.
3. **Trackers**: who has been called to resign or has gone; who is emerging; where the
   transition stands; which institutions are contested.
4. **Trail**: every item links to its source. Nothing is published without a team reviewer's
   approval.

Context the codebook assumes (these change; never hard-code them in scripts; last checked
2 Nov 2026 from collected headlines and coded stories, not yet reviewer-confirmed): after
the 1 November rerun RIK published results from all 8,392 polling stations, Student List
53.01%, United Serbia 38.98%, turnout 68.89%; RIK's overall report and the seat allocation
are still due; CRTA projects the Student List at 140 seats after the rerun and Zukorlić's
SPP says it won one seat, so the earlier projection is superseded (CeSID/Ipsos: Student
List 141 of 250, "Aleksandar Vučić – United Serbia" (SNS-led) 103, minority lists 6);
national minority council elections are on 8 November; Vučić resigned the presidency on 27 September to run for
prime minister; Ana Brnabić, as Speaker of Parliament, is acting president and is under
pressure to call the presidential election; a presidential election
is due by 26 December 2026; the outgoing authorities stay in control as caretakers until
the handover (e.g. Ivica Dačić caretaker interior minister).

## Scope decisions (fixed for this version)

- **Languages:** Serbian (Cyrillic and Latin) and English from day 1; French and German via
  Google News editions from stage 4. The AI always answers in English.
- **Outlet groups** (`outlets.csv`): `official`, `serbian_independent`,
  `serbian_pro_government`, `international`, `aggregator`, `primary_nonstate`. Reach tier
  3 = global or national flagship, 2 = national, 1 = specialist. Aggregators are credited
  to the original outlet when known.
- **Primary non-state sources (decided 3 Nov):** the Student List's official site
  (gg.studenti.org.rs; its official social channels from stage 4) and UNS are
  `primary_nonstate`: collected and linked, but never counted towards severity, since they
  speak for themselves rather than corroborate. They supplement, never replace, the
  institutional sources: government, National Assembly, RIK, RTS, REM, prosecutors and
  courts stay the default confirmation for formal appointments, decisions and legal
  actions. For the media-independence strand, Nova.rs, Radar, N1 and UNS are watched, and
  a newsroom union's own statement is preferred to secondary reporting of it.
- **Time zone:** CET everywhere (`timezone: Europe/Belgrade` in `config.yaml`). Collection
  at 06:00, draft brief ready for the team by 07:30, publication by 09:00 after approval.
- **Weekends:** collection runs every day; briefs are published Monday to Friday. The
  Monday brief and focus box cover everything since Friday's brief (about 72 hours).
- **Delivery:** one static page on GitHub Pages, shared by URL with named individuals. No
  logins, no email, no push alerts. PDF extract by script from stage 3. Free to readers.
- **Visibility (accepted risk):** the repository is public, so `docs/`, prompts, the
  codebook and outlet lists can be found through GitHub search and the profile page; the
  unlisted name and `noindex` only reduce discovery. Nothing in the repository may assume
  secrecy. Revisit if a private host (Pages from a private repo on a paid plan, or
  Cloudflare Pages with an access gate) becomes necessary.
- **Social media:** stage 4 adds X (about 60 accounts plus one daily keyword search),
  YouTube (about 15 channels) and Telegram (about 20 public channels). Stage 5 adds about
  20 public Facebook pages, polled once a day, posts and reaction counts only, no comments,
  no user-level data. No Instagram, Threads or TikTok. No Meta Content Library.
- **Duplicates:** keep every copy (copies measure reach), group copies of one story under
  one `story_id`, code each story once.
- **Threads:** a running issue that returns over several days (e.g. the NIS/OFAC licence,
  a dismissal demand that is later met) gets a `thread_id` linking its stories across
  days. Threads feed the transition timeline and "since the last brief"; a reviewer can
  merge or split threads.
- **Paywalls:** keep the headline and any free text, set `text_status = partial`. Never try
  to get around paywalls or consent walls.
- **Collection routes (decided 30 Oct):** per outlet, RSS first, then the outlet's news
  sitemap, then a Google News `site:` search only when it has neither. Google News keyword
  searches add discovery. Google News links are **not decoded**: from the EU, Google shows a
  consent page, so a Google item is matched by title to a direct copy from the same outlet
  and dropped if found; otherwise it is kept as a headline-only row (`text_route =
  headline_only`) linking to Google News. Sites that answer 401/403 to the collector (AP,
  Reuters, Tanjug as of 30 Oct) are reached only through Google News headlines;
  Bloomberg's sitemap works but its article pages return 403, so Bloomberg items stay
  headline-only.
- **Volume (decided 30 Oct):** a day yields about 2,000+ stories, mostly sport and
  entertainment. `2_extract_text.py` first screens headlines in batches with the cheaper
  coding model, tuned for recall; only possibly relevant stories are fetched and coded.
- **Spend caps:** a budget alert on the AI provider account, the spending limit in the X
  developer console, Apify's prepaid usage. When a cap is hit the collector stops and the
  method notes on the page say so.
- **Person time:** about 4 hours a day across the team. The tool does not track it.

## Codebook rules

- `codebook.md` (plain-English definitions) and `codebook.py` (the same lists, the Pydantic
  schema `Extraction`, and `prompt_text()`) are the single source of truth. Keep them in
  sync and bump `CODEBOOK_VERSION` whenever either changes (and `PROMPT_VERSION`, also
  in `codebook.py`, whenever the prompt text changes). Scripts import from
  `codebook.py`; they never define their own copies of the lists.
- **Story level (coded by the model):** `relevant` (yes/no), `category` (one alert
  category or `background`), `secondary_category` (optional, a different alert category
  when the story clearly carries two, e.g. a foreign sanctions call on named businessmen),
  `top_tier` (yes/no: does the story involve a top-tier post, list below), `article_type`,
  `actors` (from the actor list), `summary` (two sentences), `why_it_matters` (one
  sentence for an outsider), `evidence_quote` (original language, at most 25 words, never
  published).
- **Article level (from collection, not the model):** `outlet`, `outlet_group`,
  `reach_tier`, `language`, `text_status`. A story stores the set of outlet groups and
  outlets across its copies; it has no single `outlet_group`.
- **Alert categories (fixed list):** `resignation_call` (calls to resign or demands for
  dismissal); `post_change` (resignation, dismissal, suspension, appointment);
  `legal_action` (arrest, indictment, investigation, criminal complaint, case opened);
  `transition_milestone`; `new_actor`; `legal_challenge` (election complaints, court
  rulings, decrees); `institution_change` (state company, regulator, public broadcaster);
  `protest_incident`; `foreign_statement`; `business_decision` (contracts, tenders,
  concessions, EXPO 2027, Jadar); `economic_stability` (sanctions and licences affecting
  strategic companies such as NIS, central-bank measures, bank liquidity or capital-flight
  claims, currency demand, rating-agency and IFI statements on the transition);
  `background`.
- **Severity is computed by script, not by the model**, from the story group and the
  model's `top_tier` flag: 1 = reported by one outlet group only; 2 = reported by two or
  more outlet groups, or by an `official` outlet; 3 = meets 2 and `top_tier` is yes. A
  severity-3 story records the ids of two articles from different outlet groups (or one
  official article) that confirm it. Aggregator copies count under the original outlet's
  group when known; `primary_nonstate` copies never count.
- **Top-tier posts:** PM and ministers (including caretaker ministers), the President or
  acting president, Speaker of Parliament, head of police, BIA, the Supreme Public
  Prosecutor and the Prosecutor's Office for Organized Crime (TOK), RIK, REM, RTS, the NBS
  governor, and the CEO of a state company (e.g. Telekom Srbija, EPS, NIS, Srbijagas).
- **Entity level** (0 to 5 rows per story): `person_or_body`, `role`, `action`
  (`called_to_resign`, `dismissal_demanded`, `resigned`, `dismissed`, `suspended`,
  `appointed`, `investigated`, `charged`, `arrested`, `accused`, `sued`, `statement`,
  `other`), `stage` (`completed`, `announced` for threatened or intended actions not yet
  reported as done, or `not_addressed`), `by_whom`, `response` (the accused or targeted party's reply, or `not_addressed`),
  `stance` (−2 to +2, the article's stance towards this person or body). `accused` covers
  public allegations not yet backed by an official proceeding; they are recorded with
  attribution (`by_whom`) and the response. The trackers are built from these rows only.
- **Actors:** `actors.csv` is built from scratch: the main parties and lists, key
  institutions, and the officials named in the first week's coverage. Named officials and
  institutions are added to `actors.csv` only when a reviewer confirms them. The model may
  propose a new name with `proposed: true`; proposed names never appear in trackers or on
  the page until confirmed.
- **Stance** (−2 to +2, on entity rows) is kept for the emerging-leaders panel. Rules:
  labels count, quoted criticism counts when unbalanced, opinion pieces speak for the
  article.
- Code what the article says, not what you know. If the article does not say it, the field
  is empty or `not_addressed`. Never let the model invent categories, actors or actions.
- Built and validated on English first; the Serbian sample is checked by the
  Serbian-reading reviewer.

## Reference material: `ExecutiveBriefings/`

Daily PDF issues of *Executive Newsletter* (Ninamedia), an English-language subscription
digest of Serbian business and political news, one file per weekday (e.g.
`okt30pet.pdf`). The licence reserves all rights and prohibits redistribution, so:

- The folder is git-ignored and must never be committed, quoted on the page, put in
  `docs/` or `exports/`, or sent to an AI API in bulk.
- It is **not** a pipeline source. `1_collect_press.py` never reads it.
- Uses inside the Codespace only:
  1. **Early validation set.** Each issue has about 15 stories already in English with the
     original outlet credited (N1, RTS, Beta, Forbes Srbija, Radar…). Reviewers hand-code
     them (roughly half are useful `relevant = no` examples) so `10_validate.py` has a
     sample from stage 1. Extracted headlines and hand codes go in
     `data/validation/` (git-ignored); PDFs are read with `pypdf`.
  2. **Recall check.** For each weekday, did the collector find the political and
     transition stories the newsletter led with? Reported as a number in the validation
     report, without reproducing their text.
  3. **Seed lists.** Officials and outlets named in it inform `actors.csv` and
     `outlets.csv`.
  4. **Benchmark for selection.** Their lead items (4 to 8 a day) are a sanity check on
     the brief's five to eight; our brief adds the "why it matters" line and the source
     trail.

## Pipeline

Run in this order. Each script reads `config.yaml`, logs progress, and can be re-run
safely: it skips items already done.

| Script | Does | Writes |
|---|---|---|
| `1_collect_press.py` | RSS, news sitemaps and Google News per outlet and language, date filter, crediting to the original outlet, story grouping | `data/links.csv` |
| `2_extract_text.py` | Headline triage of new stories with the coding model (recall-first), then fetch the best copies of possibly relevant stories, extract text (trafilatura), detect junk and language | `data/triage.csv`, `data/articles.csv` |
| `3_code_stories.py` | AI coding against the codebook, structured outputs, one row per story; then computes severity from the story group and assigns `thread_id` | `data/coded.jsonl` |
| `4_draft_brief.py` | Daily brief and alert focus box from the day's coded stories, stronger model, cites story ids | `review/brief_YYYY-MM-DD.md` |
| `5_build_trackers.py` | Resignations, emerging leaders, transition timeline, institutions watchlist, external reactions from entity rows | `data/trackers.json` |
| `6_export_for_web.py` | Build `docs/data.js` from approved briefs, trackers and coded summaries; no text or quotes | `docs/data.js` |
| `7_export_pdf.py` | Dated PDF of the approved brief, focus box and tracker snapshots | `exports/brief_YYYY-MM-DD.pdf` |
| `8_collect_social.py` | X, YouTube, Telegram (stage 4); Facebook pages (stage 5) | `data/social.csv` |
| `9_social_trends.py` | Topic and account engagement by sphere (pro-government, independent, international) | `data/social_trends.json` |
| `10_validate.py` | Hand-coding sheet, agreement report, translation test, spot check | `data/validation/*`, `validation_report.md` |
| `11_weekly_digest.py` | One-page narrative of the week, checked by the team | `review/digest_YYYY-WW.md` |
| `run_morning.py` | Runs 1, 2, 3, 4, 5 (and 8, 9 once enabled) | |
| `publish.py` | Checks the approval gate, runs 6 and 7, commits `docs/` | |

**Review gate.** `4_draft_brief.py` writes the draft with front matter `status: draft`. A
reviewer edits the file in the Codespace, sets `status: approved` and `reviewed_by:
<name>`, and runs `python publish.py`. `publish.py` refuses to export anything whose status
is not `approved`, and the page shows "No brief today" for a date with no approved brief.
The same gate applies to the weekly digest.

## Hard rules

- **Never publish article text, evidence quotes or social post text.** Only `docs/` and
  `exports/` leave the repository. `data/` and `review/` are in `.gitignore`.
- **Never commit secrets.** Keys come from Codespaces secrets (environment variables) or a
  local `.env`; both are read the same way through `config.py`.
- **Never hand-edit `docs/data.js`.** Regenerate it with `6_export_for_web.py`.
- **Nothing reaches `docs/` without an approved brief** for that date. `publish.py` is the
  only script that writes to `docs/`.
- Every coded row records `model`, `prompt_version` and `codebook_version`.
- A coding run that fails on a story must not write a partial row; the story is retried on
  the next run.
- Before changing the prompt or codebook, run `10_validate.py` on the existing
  hand-coded sample and report the before and after numbers. Until stage 6 the sample is
  whatever has been hand-coded so far (starting with the `ExecutiveBriefings/` stories);
  if none exists yet, say so in the change note.
- Be polite to websites: at least 2 seconds between requests to the same domain, a clear
  User-Agent naming the project and a contact address, no retries on 403 or 429.
- Social collectors fetch posts from the fixed account and page lists in `config.yaml` only.
  No comments, no follower lists, no user-level data.
- Public figures and public roles only. Accusations are recorded with attribution and the
  official's response. A takedown contact appears in the method notes.
- When a spend cap is hit, stop that collector, log it, and surface it on the page.

## Code conventions

- Python 3.12. Dependencies in `requirements.txt`, pinned.
- Small functions with type hints and docstrings. `logging`, not `print`.
- Settings come from `config.yaml` and the environment, never hard-coded in scripts.
- Tests in `tests/` with `pytest`, using small fixture files in `tests/fixtures/`. No test
  may call the network or an AI API; mock them.
- All scripts are written from scratch for this project; there is no legacy code.
- Dates and times are stored in ISO 8601 with the CET offset.

## Website and PDF

- `docs/index.html` is a single static page; `docs/data.js` sets `window.SITE_DATA`.
- It must work opened from disk and on GitHub Pages, at phone width, in light and dark
  mode, and carry `<meta name="robots" content="noindex">`.
- Panels, in page order: alert focus box; daily brief; transition timeline; resignation and
  dismissal tracker; emerging leaders; institutions watchlist; external reactions; social
  media trends (from stage 4); coverage by outlet group; searchable article and post list
  (headline, summary, link only); weekly digest; method notes with sources, validation
  results, known gaps and the takedown contact.
- Stages 1 to 3 build only the panels those stages need; later panels appear as their data
  does, never as empty boxes.
- The PDF extract uses a pure-Python route (WeasyPrint or similar) so it runs in the
  Codespace and in GitHub Actions without a browser. It contains the brief, the focus box
  and a snapshot of the three trackers for that date, with the source links as footnotes.
- English interface only. A Serbian toggle is not planned for this version.

## Codespaces and GitHub set-up

- `.devcontainer/devcontainer.json`: Python 3.12 image,
  `postCreateCommand` installs the system libraries WeasyPrint needs (Pango, HarfBuzz)
  and then `pip install -r requirements.txt`; port 8000 forwarded so
  `python -m http.server --directory docs 8000` previews the page. The Actions workflow
  installs the same system libraries.
- **Secrets** are repository Codespaces secrets (GitHub: Settings → Secrets and variables →
  Codespaces). They appear as environment variables inside the Codespace:
  `OPENAI_API_KEY`, `OPENAI_MODEL` (coding), `OPENAI_MODEL_BRIEF` (brief and digest);
  from stage 4 `X_BEARER_TOKEN`, `YOUTUBE_API_KEY`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  `TELEGRAM_SESSION` (a string session from a logged-in Telegram account; treat it as a
  password); from stage 5 `APIFY_TOKEN`. GitHub Actions needs the same values added separately as
  Actions secrets.
- **GitHub Pages:** public repository with an unlisted name; Settings → Pages → deploy from
  branch `main`, folder `/docs`. The page URL is what gets shared.
- **Scheduled run** (stage 6): `.github/workflows/morning.yml`, cron `0 5 * * *` (06:00
  CET; GitHub cron is UTC, so this becomes 07:00 when summer time starts on 28 March 2027,
  and scheduled runs can start 10 to 30 minutes late), runs `run_morning.py`. `data/` is restored from and saved to the Actions cache,
  never committed; the draft brief is uploaded as a workflow artifact. The reviewer pulls it
  into the Codespace (`gh run download`), approves it, and runs `publish.py`. Until stage 6
  the morning run is started by hand in the Codespace.
- Claude Code runs inside the Codespace terminal. If it is not installed yet, follow the
  official instructions at https://docs.claude.com rather than guessing a command.

## Repository layout

```
CLAUDE.md  README.md  .gitignore  config.yaml  config.py  http_client.py  ai_client.py
outlets.csv  actors.csv
codebook.md  codebook.py  validation_report.md
1_collect_press.py  2_extract_text.py  3_code_stories.py  4_draft_brief.py
5_build_trackers.py  6_export_for_web.py  7_export_pdf.py  8_collect_social.py
9_social_trends.py  10_validate.py  11_weekly_digest.py  run_morning.py  publish.py
web/        index.html template, copied to docs/ by publish.py
.devcontainer/  devcontainer.json
.github/workflows/  morning.yml                      (stage 6)
docs/       index.html, data.js                      (public)
exports/    brief_YYYY-MM-DD.pdf                     (git-ignored)
review/     brief_YYYY-MM-DD.md, digest_YYYY-WW.md   (git-ignored)
data/       links.csv, articles.csv, coded.jsonl, trackers.json, social.csv,
            social_trends.json, validation/          (git-ignored)
tests/      test_*.py, fixtures/
ExecutiveBriefings/  licensed newsletter PDFs, reference only (git-ignored, never committed)
```

## Staged plan

Working days from Monday 2 November 2026. Tick items as they are done and add the date.

### Stage 1 · Press-only brief (days 1 to 2, 2 to 3 Nov)

- [x] Repository, `.devcontainer`, `requirements.txt`, `.gitignore` (`data/`, `review/`, `exports/`, `.env`, `ExecutiveBriefings/`) — 30 Oct
- [x] `config.yaml`, `config.py`, `outlets.csv` (Serbian independent, Serbian pro-government, official, international), `actors.csv` seeded from scratch (parties, institutions, officials in the first week's coverage) — 30 Oct (actors have `status: seed` until a reviewer signs the list off; `project.contact_email` must be set before collecting)
- [x] `codebook.md` v0.1 and `codebook.py` with the schema above — 30 Oct (v0.1.0; severity rule and actor-id check in `codebook.py`; `tests/test_codebook.py` keeps the two files in sync)
- [x] `1_collect_press.py` written from scratch with Serbian sources and story grouping — 30 Oct (first live run: ~2,500 links, ~2,200 stories, 85 s; shared polite client in `http_client.py`)
- [x] `2_extract_text.py` written from scratch — 30 Oct (headline triage before fetching, decided 30 Oct to keep coding volume within budget; live text test 39/40 full; first live triage 2 Nov: 5,701 stories, 2,157 passed, 38%)
- [x] `3_code_stories.py` with structured outputs, script-computed severity and `thread_id`; coded 30 stories and eyeballed them — 2 Nov (0 failed; real cost about $0.004 a story, token use now logged by `ai_client.py`; `relevant` was too narrow and was widened in prompt 0.1.1 / codebook 0.1.2: no hand-coded sample existed, so no `10_validate.py` numbers; informal before/after on the 15 rejected stories: 9 flipped to relevant, including NIS/OFAC. Not reviewer-checked. Open issue: same event under different headlines splits into several `story_id`s, so severity differs between them, e.g. RIK results at 3 and 1)
- [ ] First `ExecutiveBriefings/` stories hand-coded into `data/validation/` as the early sample
  - 2 Nov: not done from the newsletters. As a stopgap Claude coded 30 randomly drawn collected stories from excerpts (`data/validation/hand_codes_claude.csv`), which is not independent validation. Prompt 0.1.2 / codebook 0.1.3 scored category 80%, `top_tier` 90%, `relevant` 90% against them (before: 63%, 77%, 90%), on the sample the fixes were designed from. The 30 coded stories in `data/coded.jsonl` predate these versions and need recoding. A reviewer still needs to check these codes.
- [x] `4_draft_brief.py` producing the brief and the alert focus box with story ids — 2 Nov (stories consolidated by thread; the model writes and merges focus lines, severity and rank stay script-computed across the cited stories; 396 coded, 4 failed on the 25-word quote limit and retry next run; first draft in `review/brief_2026-11-02.md`, numbers and names traced to sources)
- [x] `publish.py` with the approval gate; `6_export_for_web.py`; `docs/index.html` with the focus box, brief and method notes — 2 Nov (template in `web/index.html`, copied to `docs/` by `publish.py` so nothing reaches `docs/` before approval; `publish.py` also refuses if an evidence quote reaches the page data; script parses, not yet seen in a browser)
- [x] GitHub Pages enabled; first approved brief on the page — 2 Nov (https://europehub2026.github.io/MediaMonitoring/, brief approved by GKK)

Done when: a reviewer has approved one real morning brief and it is visible at the Pages URL.

### Stage 2 · Low version (days 3 to 4, 4 to 5 Nov)

- 3 Nov, added at the team's request: media-independence strand. `actors.csv` gains Nova (daily), Radar, ANN, Alpac Capital, the Nova/Radar union, UNS, Jovan Memedović and Olivera Kovačević (`status: confirmed`); Student List aliases extended. `outlets.csv` gains the Student List site and UNS as `primary_nonstate`. Codebook 0.2.0 / prompt 0.2.0: `stage` field, `sued` action, media decisions in scope (numbers in the `codebook.md` change log). Stories coded before 0.2.0 have no `stage` and should be recoded before `5_build_trackers.py` relies on it.

- [ ] `5_build_trackers.py`: resignation and dismissal tracker, emerging leaders, transition timeline from entity rows
- [ ] Article list panel with search and filters (category, actor, outlet group, date)
- [ ] Method notes panel: sources, codebook version, known gaps, takedown contact
- [ ] Page checked at phone width and in dark mode
- [ ] Reviewer rota and the 07:30 / 09:00 routine written in `README.md`

Done when: the page carries two consecutive approved briefs plus the three trackers, and the link has gone to the first named external readers.

### Stage 3 · PDF extract (day 5, 6 Nov)

- [ ] `7_export_pdf.py`: dated PDF of the approved brief, focus box and tracker snapshots with source footnotes
- [ ] `publish.py` runs it after the web export
- [ ] First PDF sent to external stakeholders

Done when: an external stakeholder has received a PDF generated by the script for that day's approved brief.

### Stage 4 · Open social (days 6 to 8, 9 to 11 Nov)

- [ ] Account and channel lists in `config.yaml` (about 60 X accounts, 15 YouTube channels, 20 Telegram channels) confirmed by the team; include the Student List's official channels
- [ ] `8_collect_social.py` for X (pay-per-use, spending limit set), YouTube Data API, Telegram public channels
- [ ] Social posts coded with a shorter prompt; grouped into the same `story_id` where they carry a press story
- [ ] `9_social_trends.py` and the social media trends panel; coverage by outlet group panel
- [ ] French and German Google News editions added to `1_collect_press.py`

Done when: the trends panel shows a full day of X, YouTube and Telegram data and the X spend for the day is within budget.

### Stage 5 · Facebook, light (days 8 to 9, 11 to 12 Nov)

- [ ] Page list (about 20) confirmed by the team
- [ ] Facebook collector via a pay-per-result Apify actor, once a day, posts and reaction counts only
- [ ] Facebook included in the trends panel; collector fails safe when the actor breaks

Done when: Facebook posts from the listed pages appear in the trends panel for one full day.

### Stage 6 · Watchlists and validation (days 9 to 10, 12 to 13 Nov)

- [ ] Institutions watchlist and external reactions panels from entity rows
- [ ] `10_validate.py`: 50 English and 50 Serbian stories hand-coded; targets 80% on category, 80% on `top_tier`, 75% on computed severity within one point, agreement check on entities; Serbian spot check by the Serbian-reading reviewer; results in `validation_report.md` and the method notes
- [ ] `11_weekly_digest.py` with the same approval gate; first digest approved
- [ ] `.github/workflows/morning.yml` scheduled at 06:00 CET; draft arrives as a workflow artifact
- [ ] Costs reviewed against real volumes; caps adjusted

Done when: the morning run has started itself on two consecutive days and the validation report is published in the method notes.
