
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

