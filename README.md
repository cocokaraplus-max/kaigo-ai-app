# TASUKARU  - Claude
2026-04-17

---

## 


Excel
AI


- AI
- Excel
- 

---

## GitHub

https://github.com/cocokaraplus-max/kaigo-ai-app


- main          
- cloudrun-dev  Cloud RunCloud Shell
- cloudrun      Cloud Run
- develop       VS Code
- cloudrun-test  


VS Codedevelop GitHub push  cloudrun-dev Cloud Shell
 OK  cloudrun/main   

Cloud Shellcloudrun-dev
VS Codedeveloppush

---

## 

URLhttps://tasukaru-dev-191764727533.asia-northeast1.run.app
GCPtasukaru-production
Cloud Runtasukaru-dev
asia-northeast1
tasukaru-dev-00200-l622026-04-17

---

## 

Python / Flask
Google Cloud RunDocker
DBSupabasePostgreSQL
  URLhttps://abvglnkwtdeoaazyqwyd.supabase.co
  ()cocokaraplus-5526
Google Apps ScriptGAS
HTML/CSS/JSFlaskHTML

---

## 

/top          TOP
/assessment   AIAI
/case_record  
/monitoring   
/vitals       
/calendar     
/daily_view   
/board        
/mapping      send_filestatic/mapping.html
/help         send_filestatic/help.html

---

## 

templates/  FlaskJinja2
static/     Jinja2
  mapping.html  UI30KB&
  help.html     5

static/HTMLJinja2{{ }}send_file()
app.pymappingHTMLwindow.TASUKARU_CONFIG

mapping
  @app.route('/mapping')
  @login_required
  def mapping():
      html = open('static/mapping.html').read()
      su = os.environ.get('SUPABASE_URL', '...')
      sk = os.environ.get('SUPABASE_KEY', '')
      fc = os.environ.get('FACILITY_CODE', 'cocokaraplus-5526')
      cfg = f'<script>window.TASUKARU_CONFIG={{...}};</script>'
      return html.replace('</head>', cfg + '</head>', 1)

---

## Supabase 

patients        
assessments     
case_records    
admin_settings  setting_key='field_mapping'

---

## GAS

GAShttps://script.google.com/u/0/home/projects/1_3CHezNwUFpBMchQv7cMWCS4qU7R_32glKcDankYrHBuLZdpqOz0OpsL/edit
https://docs.google.com/spreadsheets/d/13fAq0ELCyq8w_bryzt-CEpKrzdDdsPyqYd-UYEqLq6Q


- fillMonitoringFromAssessment()  
- fillMonitoringByMonth()         

---

## 

cd ~/tasukaru
git checkout cloudrun-dev
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet

---

## Cloud Shell

ClaudeCloud Shell
ClaudePC
Cloud Shell EditorUpload...
gcloud run deploy

---

## 

Flask + Supabase + Cloud Run 

GASSupabaseGoogle
GAS: monitoring.gs
2026-04-17/mappingstatic/mapping.html(30KB)
2026-04-17mapping.htmlTASUKARU_CONFIG
2026-04-17/helpstatic/help.html
2026-04-17CloudShellGitHubcloudrun-dev

---

## PENDING


- patientsgoal_short/long_func/act/join
- /monitoring
- TOP/help


- mapping.html
- 

---

## 

cd ~/tasukaru
git checkout cloudrun-dev
git add -A && git commit -m "" && git push origin cloudrun-dev
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet
python3 -c "import re; routes=re.findall(r\"@app\.route\('([^']+)'\)\", open('app.py').read()); [print(r) for r in sorted(set(routes))]"
