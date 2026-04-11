import secrets, os
from supabase import create_client
from datetime import datetime, timezone, timedelta

url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')
sb = create_client(url, key)
t = secrets.token_urlsafe(32)
exp = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
sb.table('claude_sessions').delete().eq('facility_code','cocokaraplus-5526').execute()
sb.table('claude_sessions').insert({'facility_code':'cocokaraplus-5526','token':t,'expires_at':exp}).execute()
print('https://tasukaru-191764727533.asia-northeast1.run.app/claude_view?token=' + t)