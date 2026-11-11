# Serbia Post-Election Monitor

A daily monitor of state-level political change in Serbia after the 25 October 2026
election. Press reports are collected and coded by AI against `codebook.md`. A team
reviewer approves each brief, and only then is it published to the GitHub Pages site.
`CLAUDE.md` has the full design and the staged plan.

## Daily routine (CET)

Briefs come out Monday to Friday. Collection is meant to run every day. On Mondays the
brief covers everything since Friday's brief.

| Time | Who | What |
|---|---|---|
| 06:00 | Operator on duty | Start the morning run in the Codespace (commands below). Until stage 6 this is done by hand. |
| by 07:30 | Operator | The draft brief is in `review/brief_YYYY-MM-DD.md` with `status: draft`. Tell the reviewer it is ready. |
| 07:30–08:45 | Reviewer on duty | Review the draft (checklist below), edit it in place, then set `status: approved` and `reviewed_by: <initials>`. |
| by 09:00 | Reviewer | Run `python publish.py`, push, and check the live page. |

When a day is missed, nothing appears on the page for it: the page shows "No brief today"
together with the latest approved brief. Add the gap to `method.known_gaps` in
`config.yaml` so readers can see it.

### Morning run

```bash
python 1_collect_press.py            # links since yesterday
python 2_extract_text.py             # headline triage, then fetch text of possibly relevant stories
python 3_code_stories.py --since <start of the brief window, e.g. 2026-11-10T00:00:00+01:00>
                                     # code the window first; also regroups events and threads
python 4_draft_brief.py              # window runs from the end of the last approved brief
python 5_build_trackers.py
```

Every script can be re-run safely and skips work that is already done. Logs are in
`data/logs/`. If a spend cap is hit, the script stops and logs it, and the method notes
say so after the next publish.

### Review checklist

1. **Sources:** open each link in the focus box and the brief. Every name, number and date
   must match a source.
2. **Selection:** five to eight developments. Nothing important missing, and nothing
   trivial included.
3. **Why it matters:** each line must make sense to someone who does not follow Serbian
   politics.
4. **Fairness:** every accusation names who made it and gives the response, where one
   was reported. Public figures and public roles only.
5. **Severity:** it is computed by the script. Do not edit the numbers. If one looks
   wrong, note it for the team.
6. **No quotes from article text.** Headlines and our own English summaries are fine.
7. Delete any item you cannot verify. Do not rewrite it from memory.

### Publishing

```bash
python publish.py                    # refuses unless today's brief is approved and names a reviewer
git push                             # GitHub Pages deploys from main, /docs
```

`publish.py` is the only script that writes to `docs/`. Never edit `docs/data.js` by
hand.

## Reviewer rota

The team fills this in. Each day needs one operator and one reviewer, and the reviewer
is not the operator. The Serbian-reading reviewer spot-checks Serbian-language stories
at least once a week.

| Day | Operator (06:00) | Reviewer (07:30–09:00) | Back-up |
|---|---|---|---|
| Monday | | | |
| Tuesday | | | |
| Wednesday | | | |
| Thursday | | | |
| Friday | | | |
| Saturday / Sunday | collection only, no brief | | |

## Set-up

Open the repository in a Codespace: `.devcontainer/` installs everything. Secrets are
repository Codespaces secrets (see `CLAUDE.md`). Run the tests with `pytest`. To preview
the page, run `python -m http.server --directory docs 8000`.
