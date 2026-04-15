import re

with open("templates/manual.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

mapping = {
    123: "tasukaru_ooyorokobi.png",
    190: "tasukaru_sestumei.png",
    217: "tasukaru_ageage.png",
    249: "tasukaru_sestumei.png",
    273: "tasukaru_gimon.png",
    300: "tasukaru_onegai.png",
    347: "tasukaru_ageage.png",
    371: "tasukaru_ooyorokobi.png",
    394: "tasukaru_sestumei.png",
    419: "tasukaru_gimon.png",
    447: "tasukaru_odoroki.png",
    468: "tasukaru_ooyorokobi.png",
    483: "tasukaru_top_white.png",
}

import re
for idx, img in mapping.items():
    line = lines[idx]
    new = re.sub(r'src="data:image/png;base64,[^"]*"', f'src="/static/{img}"', line)
    if new != line:
        lines[idx] = new
        print(f"L{idx+1}: -> {img}")
    else:
        print(f"L{idx+1}: skip")

with open("templates/manual.html", "w", encoding="utf-8") as f:
    f.writelines(lines)
