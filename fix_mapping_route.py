# coding: utf-8
"""
app.pyの/mappingルートを修正する
- json.dumpsを使ってSupabaseキーの特殊文字を安全にエスケープ
- Response(html, mimetype='text/html')で正しくContent-Typeを設定
kaigo-ai-appフォルダで python3 fix_mapping_route.py を実行
"""

path = 'app.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

old = """@app.route('/mapping')
@login_required
def mapping():
    import os
    html = open('static/mapping.html', encoding='utf-8').read()
    su = os.environ.get('SUPABASE_URL', '')
    sk = os.environ.get('SUPABASE_KEY', '')
    fc = os.environ.get('FACILITY_CODE', 'cocokaraplus-5526')
    cfg = f'<script>window.TASUKARU_CONFIG={{supabaseUrl:"{su}",supabaseKey:"{sk}",facilityCode:"{fc}"}};</script>'
    html = html.replace('</head>', cfg + '</head>', 1)
    return html"""

new = """@app.route('/mapping')
@login_required
def mapping():
    import os, json
    from flask import Response
    html = open('static/mapping.html', encoding='utf-8').read()
    config = json.dumps({
        'supabaseUrl': os.environ.get('SUPABASE_URL', ''),
        'supabaseKey': os.environ.get('SUPABASE_KEY', ''),
        'facilityCode': os.environ.get('FACILITY_CODE', 'cocokaraplus-5526')
    })
    cfg = '<script>window.TASUKARU_CONFIG=' + config + ';</script>'
    html = html.replace('</head>', cfg + '</head>', 1)
    return Response(html, mimetype='text/html')"""

if old in content:
    content = content.replace(old, new)
    print('OK: /mapping route fixed')
    print('  - json.dumps for safe escaping')
    print('  - Response(mimetype=text/html) added')
else:
    print('NG: pattern not found, trying partial match...')
    if "def mapping():" in content:
        idx = content.find("def mapping():")
        print('Found def mapping() at index:', idx)
        print('Context:', repr(content[idx:idx+300]))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Saved:', path)
