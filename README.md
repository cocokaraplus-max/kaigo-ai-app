# TASUKARU  

> cocokaraplus-maxZIMAX  
> Claude 

---

##  

```bash
# Cloud Shell 
cd ~/tasukaru
git status  # 

# VS Code 
git fetch origin
git checkout cloudrun      # 
# 
git checkout cloudrun-dev  # 
git pull origin cloudrun   # 
```

---

##  

### GitHub
`https://github.com/cocokaraplus-max/kaigo-ai-app`

|  |  |  |
|---------|------|--------|
| `main` | Streamlit |   |
| `develop` | Streamlit |   |
| `cloudrun` | **Flask** |   |
| `cloudrun-dev` | **Flask** |   |

### Cloud Run: tasukaru-production, region: asia-northeast1

|  | URL |  |
|-----------|-----|------|
| `tasukaru` | https://tasukaru-dmgqqhsp6q-an.a.run.app | **Flask**   |
| `tasukaru-dev` | https://tasukaru-dev-dmgqqhsp6q-an.a.run.app | Flask |
| `kaigo-ai-app` | https://kaigo-ai-app-191764727533.asia-northeast1.run.app | Streamlit|

### Cloud Shell
`~/tasukaru/``cloudrun-dev`

---

##  

```bash
cd ~/tasukaru

# 
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet

# 
gcloud run deploy tasukaru --source . --region asia-northeast1 --project tasukaru-production --quiet
```

##  GitHubpush

```bash
# cloudrun-dev  cloudrun 
git add -A
git commit -m "feat: "
git push origin cloudrun-dev
git push origin cloudrun-dev:cloudrun --force
```

>  pushGitHub PAT
> GitHub  Settings  Developer settings  Personal access tokens

---

##  

|  |  |
|---------|------|
| `app.py` | Flask |
| `templates/admin.html` | MENU |
| `static/mapping.html` |  |
| `static/help.html` |  |
| `static/admin.js` | MENU JavaScript |

---

##  2026-04-17 

|  |  |
|------|---------|
| `/mapping` Supabase Config | `app.py` |
| `/help`  | `app.py` |
| MENU 500`board_editors=[]`3 | `app.py` |
| MENU | `templates/admin.html` |
| ? | `templates/admin.html` |
| `develop`  `d8b8d97` | GitHub |
| `kaigo-ai-app`Streamlit   | Cloud Run |

---

##  

### `board_editors` 
`templates/admin.html` 814
```javascript
var _boardEditors = {{ board_editors | tojson }};
```
 `render_template("admin.html", ...)` **** `board_editors=[]` 
MENU500

### `/mapping` 
```python
@app.route('/mapping')
@login_required
def mapping():
    import os
    html = open('static/mapping.html', encoding='utf-8').read()
    su = os.environ.get('SUPABASE_URL', '')
    sk = os.environ.get('SUPABASE_KEY', '')
    fc = os.environ.get('FACILITY_CODE', 'cocokaraplus-5526')
    cfg = f'<script>window.TASUKARU_CONFIG={{supabaseUrl:"{su}",supabaseKey:"{sk}",facilityCode:"{fc}"}};</script>'
    html = html.replace('</head>', cfg + '</head>', 1)
    return html
```
`static/mapping.html` HTMLFlaskConfig

### `kaigo-ai-app` 
- URL: `https://kaigo-ai-app-191764727533.asia-northeast1.run.app`
- Streamlit
- **Flask**

---

##  MENU

```
MENU
 AI
 [ ]  [?]   2026-04-17
 
 
 MENU
```

-  `/mapping` 
- ? `/help`

---

##  Supabase

|  |  |
|------|---|
| URL | https://abvglnkwtdeoaazyqwyd.supabase.co |
|  | cocokaraplus-5526 |

---

##  TODO

- [ ] VS Code`git pull origin cloudrun`  diverge  `git reset --hard origin/cloudrun` 
- [ ] Supabase
- [ ] PAT

---

##  

```
1. VS Code  cloudrun-dev 
2. Cloud Shell  git pull
3. Cloud Shell  tasukaru-dev   
4.  tasukaru
5. GitHub  pushcloudrun-dev  cloudrun 
```

---

*: 2026-04-18 by TASUKARUClaude*
