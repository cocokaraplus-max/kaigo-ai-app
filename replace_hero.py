import base64, io
from PIL import Image

img = Image.open("static/tasukaruカラー.png").convert("RGBA")

bg = Image.new("RGBA", img.size, (21, 88, 208, 255))
bg.paste(img, mask=img.split()[3])
result = bg.convert("RGB")
result = result.resize((300, 300), Image.LANCZOS)

buf = io.BytesIO()
result.save(buf, format="PNG", optimize=True)
b64 = base64.b64encode(buf.getvalue()).decode()
new_src = f"data:image/png;base64,{b64}"

with open("templates/manual.html", "r", encoding="utf-8") as f:
    html = f.read()

alt_idx = html.find('alt="タスカルくん"')
src_idx = html.rfind('src="', 0, alt_idx)
end_idx = html.index('"', src_idx + 5) + 1

new_html = html[:src_idx] + f'src="{new_src}"' + html[end_idx:]

with open("templates/manual.html", "w", encoding="utf-8") as f:
    f.write(new_html)
print("OK: 差し替え完了!")