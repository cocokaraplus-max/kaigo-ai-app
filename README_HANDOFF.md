
##   - 2026-04-25 

###  
- [ ] Cloud Run dev  API GEMINI_API_KEY, SENDGRID_API_KEY Secret Manager 
  - : dev 

###  
- [ ] Cloud Build tasukaru-dev 
  - cloudbuild-dev.yaml 
  - : ^tasukaru-dev$filename: cloudbuild-dev.yaml
- [ ] 
  - cloudrun-test4/8 
  - main tasukaru 
  - fix/history-encoding-20260422

###  
- [ ] calendar_events  task_id 
- [ ] UI ////
- [ ] Phase 3c-2

###  
- [ ] 
  - DB: "DB - kaigo-ai-app (abvglnkwtdeoaazyqwyd)"
  - dev DB: "dev DB - tasukaru-dev (otjevnmoycnvaxeltrtj)"


---

##  Session 2026-04-25: Phase 3c-1 Calendar UI Restored + Pipeline Setup

###  

**UI**
- `calendar_old.html` (894)  `calendar.html` 
- `calendar.html.phase3c_backup` 
- dev Cloud Run Google CalendarUI
- commit: `e65ab3e` Phase 3c-1: restore calendar_old.html

**devCloud Build**
- `cloudbuild-dev.yaml` envimage
-  (2M14S, SUCCESS)
- commit: `32618c0` Phase 3c-0: add cloudbuild-dev.yaml

****
-  `develop` 
- Cloud Build `cloudrun-kaigo-ai-app-...` 

**Git**
- user.email: `cocokaraplus-max@users.noreply.github.com`
- user.name: `cocokaraplus-max`
- credential.helper: `cache --timeout=3600`

---

##  

###  : 
- [ ] Cloud Run dev  API  Secret Manager 
  - : `GEMINI_API_KEY`, `SENDGRID_API_KEY`
  - : Cloud Run

###  
- [ ] Cloud Build tasukaru-dev 
  - `cloudbuild-dev.yaml` 
  - gcloud builds triggers create github ...
- [ ] 
  - `cloudrun-test` (2026-04-08 )
  - `main` (`tasukaru`)
  - `fix/history-encoding-20260422` ()

###  
- [ ] ** + **UI
  - : `[][][][+]` 
  - : 1
  - : `cal-chips` HTMLJavaScript
- [ ] 
  - `calendar_events.task_id` 
  - 
- [ ] UI
  - cal-modal
  - event-modal
  - invite-modal
  -  / 

###  
- [ ] 
  - DB: "DB - kaigo-ai-app (abvglnkwtdeoaazyqwyd)"
  - dev DB: "dev DB - tasukaru-dev (otjevnmoycnvaxeltrtj)"



---

## Session 2026-04-25 (Part 2): Cloud Build Trigger Created

### Achievement
- Created Cloud Build trigger: `tasukaru-dev-auto-deploy` (region: asia-northeast1)
- Trigger UUID: 438b21a8-95a3-49b1-8fa0-e4fdd9f9581b
- Successfully tested manual run: build `15fd5a4b` finished in 2m29s (3 steps all green)
- Verified dev URL still serves the calendar UI after auto-deploy

### Root Cause of Previous INVALID_ARGUMENT (the 2-session blocker)
Cloud Build projects without legacy service account REQUIRE `--service-account` flag when creating a trigger.
- This project (`tasukaru-production`, number 191764727533) has only the Compute Engine default SA.
- No `<num>@cloudbuild.gserviceaccount.com` legacy SA exists.
- Without `--service-account`, the API returns `400 INVALID_ARGUMENT` with NO field-level details.
- Reference: https://cloud.google.com/build/docs/cloud-build-service-account-updates
- Quote: "You'll have to specify a service account when you create or update a trigger, unless the default service account for your project is the Cloud Build legacy service account."

### Working command (KEEP THIS  the missing piece is `--service-account`)
```
gcloud beta builds triggers create github \
  --name=tasukaru-dev-auto-deploy \
  --description='Auto-deploy tasukaru-dev branch to Cloud Run' \
  --region=asia-northeast1 \
  --project=tasukaru-production \
  --repository='projects/tasukaru-production/locations/asia-northeast1/connections/cocokaraplus-max-github/repositories/cocokaraplus-max-kaigo-ai-app' \
  --branch-pattern='^tasukaru-dev$' \
  --build-config=cloudbuild-dev.yaml \
  --service-account='projects/tasukaru-production/serviceAccounts/191764727533-compute@developer.gserviceaccount.com'
```

### Other useful findings
- `gcloud builds triggers import` issues HTTP PATCH (update only). It cannot create new triggers  `triggers create` is the only way.
- Current trigger uses Compute Engine default SA. Future hardening: create a least-privilege custom SA for Cloud Build.
- The 400 INVALID_ARGUMENT response body has no `details` / `fieldViolations`  debugging requires `--log-http` and reading the request body.

### Next session priorities
- [ ] Test push-driven auto-deploy with a small commit
- [ ] Move Gemini / SendGrid API keys to Secret Manager
- [ ] Delete stale branches: main, cloudrun-test, fix/history-encoding-20260422
- [ ] Change GitHub default branch from main to tasukaru
- [ ] Phase 3c-2 implementation: calendar_events.task_id column + per-resident care plan calendar


---

## Session 2026-04-25 (Part 3): Calendar UI Redesign Plan (TimeTree-style)

### Confirmed user requirements
- Replace top horizontal calendar chips with a hamburger (`menu` icon) button placed top-right
- Tapping the icon opens a dropdown panel with ON/OFF switches (multi-select)
- Keep the page-title row (calendar_month icon + "" text) as-is
- Overall direction: TimeTree-like look and feel

### File layout (templates/calendar.html, 869 lines total)
- Lines 1-3: Jinja extends + title block
- Lines 5-176: `{% block extra_style %}` (CSS)
- Lines 178-426: `{% block content %}` (HTML)
- Lines 428-869: `{% block extra_script %}` (JavaScript)

### Target replacement region (verified by Python div-balance analysis)
- Line 178-181: `.page-title` div (KEEP  calendar_month icon + "")
- Line 183: comment `<!--  -->`
- **Line 185 - 207 (23 lines): `<div class="calendar-list" id="cal-chips">` ... `</div>`**  REPLACE THIS
- Line 209+: month nav, prev/next buttons, today button, month/week toggle (KEEP)

### Inside cal-chips block (what to preserve in semantics)
- "" toggle chip (toggles all calendars on/off)
- `{% for cal in calendars %}` loop with per-calendar chip
  - dot (cal.color), name, lock/group icon based on `cal.is_private`
  - `onclick="toggleCalendar('{{ cal.id }}')"`
- Invite icon `openInviteModal('{{ cal.id }}','{{ cal.name }}')` (uses material-symbols person_add)
- "+ " chip (opens new-calendar modal  exact text TBD, may use icon only)

### Existing JS hooks (DO NOT BREAK)
- `toggleCalendar(calId)`  per-calendar visibility toggle (likely flips `.cal-chip.active` class)
- `openInviteModal(calId, calName)`  invitation modal opener
- New calendar modal opener  exact function name TBD (search for `openCalModal` or modal-related names)

### Implementation plan for next session
1. Extract block 185-207 to /tmp/cal_chips_block.txt (already done this session)
2. Inspect block contents to find: "" chip exact markup, "+ " chip exact markup, modal-open handler name
3. Write new HTML for hamburger button + dropdown panel (use `<details>` element or custom `<div>` with toggle JS)
4. Add CSS for: hamburger button position (top-right), dropdown panel, switch (~ -webkit-appearance), color dots
5. Add minimal JS: click outside to close, sync switches to existing `toggleCalendar()` calls
6. Save to /home/cocokaraplus/tasukaru/templates/calendar.html via Python script (verify byte length and grep for sentinels)
7. git diff to confirm only the 185-207 region changed
8. Commit + push to tasukaru-dev  trigger fires  ~2.5 min build  verify on dev URL

### Risk register
- The current chip layout is a flexbox row with `flex-wrap:wrap` (line 9). Removing `.calendar-list` may leave dangling CSS  check class is unused elsewhere before removing.
- `toggleCalendar()` may rely on the `.cal-chip.active` class. New switch UI must reproduce that class flip.
- `class="cal-chip"` is referenced multiple places in CSS (lines 35+). Decide: keep `.cal-chip` class on switch row OR remove and replace with new class.
- Consider mobile breakpoints  hamburger placement should be `position:absolute;top:12px;right:12px` or similar; verify it does not overlap page-title icon.

### Saved artifacts in /tmp (may be erased on Cloud Shell VM cycling)
- /tmp/cal_chips_block.txt  extracted block 185-207 for offline study
- /tmp/trigger-create.log  Cloud Build trigger debug log from earlier
- /tmp/trigger-import.log  earlier import attempt log
- /tmp/handoff_append.md  earlier session 2 append text
