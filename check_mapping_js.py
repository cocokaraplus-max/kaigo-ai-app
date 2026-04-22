# coding: utf-8
import re, subprocess, sys

html = open('static/mapping.html', encoding='utf-8').read()

# scriptブロックを全て取得
pattern = re.compile(r'<script(\s[^>]*)?>[\s\S]*?</script>', re.IGNORECASE)
blocks = pattern.findall(html)
full_blocks = pattern.finditer(html)

print('=== script blocks ===')
for i, m in enumerate(pattern.finditer(html)):
    src_match = re.search(r'src=["\']([^"\']+)["\']', m.group())
    if src_match:
        print(f'Block {i}: external - {src_match.group(1)[:60]}')
    else:
        inner = re.sub(r'^<script[^>]*>|</script>$', '', m.group(), flags=re.IGNORECASE).strip()
        print(f'Block {i}: inline {len(inner)} chars')
        print(f'  first 60: {repr(inner[:60])}')
        
        # 構文チェック
        result = subprocess.run(
            ['node', '-e', f'try {{ new Function({repr(inner)}); console.log("OK") }} catch(e) {{ console.log("ERR line", e.lineNumber || "?", ":", e.message) }}'],
            capture_output=True, text=True, timeout=10
        )
        print(f'  syntax: {result.stdout.strip() or result.stderr.strip()[:100]}')
