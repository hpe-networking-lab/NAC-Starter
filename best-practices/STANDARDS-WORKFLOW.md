# Standards Workflow — how a lesson becomes a standard without drift (binding)

When any chat hits a generalizable problem and fixes it, follow this so the fix reaches every chat
**without going out of sync**. Rule of thumb: **one home, one writer, inherit — never copy.**

## Lanes (this is what prevents drift)
- **`best-practices/`** = the single canonical home. **Only the mist-reference-designs chat writes here.**
- **`proposals/`** = the intake inbox. **Any chat may drop a proposal file here** (append-only; never
  edit someone else's). No customer/build chat edits `best-practices/` directly.

## Workflow
1. **Fix + capture (discovering chat).** Fix your own issue. Write the generalizable lesson using
   `proposals/PROPOSAL_TEMPLATE.md` and **commit it to `proposals/`** (git from `/lab/github/...`). Do
   NOT touch `best-practices/`. Any engagement-local applied copy is clearly marked as a mirror.
2. **Route (human, one line).** Tell the mist-reference-designs chat: "promote the open proposals."
   That is the ONLY manual relay — you never paste standard *content* between chats.
3. **Promote (standards chat = single writer).** The mist-reference-designs chat reviews each proposal,
   promotes accepted ones into `best-practices/` (new file or edit), commits/pushes, and **deletes the
   proposal** so it can't go stale. Rejected -> record the reason in the proposal, then delete.
4. **Inherit (automatic).** Because every grounding reads *all of* `best-practices/` ("binding as it
   grows") at self-ground, the new standard reaches every chat on its next session with **no re-paste
   and no per-chat sync.** That is the whole point.

## Anti-desync guardrails
- **Never two writers on `best-practices/`.** Discovering chats propose; they do not write the standard.
- **Promoter closes the loop** — delete the promoted/rejected proposal. Open proposals are the only
  backlog and should be short-lived.
- **Applied copies are read-only mirrors** ("snapshot of best-practices/ as of <date>"), never authority.
- **Grounding hooks** are per-repo (added once, in that repo's own chat); the grounding template
  (`lab-roadmap/templates/ENGINEERING_OFFICE.template.md`) carries the hook so new chats inherit by
  construction.

## Automation
A scheduled check lists open `proposals/` each morning so nothing sits un-promoted (prevents the
stale-handoff failure). If the folder is non-empty, the daily lab report flags "N standards proposals
awaiting promotion."
