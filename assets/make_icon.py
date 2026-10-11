# 바탕화면 바로가기 아이콘: 초록 둥근 사각형 위에 A4 세 장이 겹친 모양 (웹 상단 로고와 같은 모양)
# 실행: uv run --with pillow python assets/make_icon.py
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill=(23, 105, 90, 255))
w, h = 112, 150   # 종이 크기 (A4 비율에 가깝게)
for k, alpha in ((2, 110), (1, 175), (0, 255)):   # 뒤 장일수록 위·오른쪽으로 비켜나고 흐리게
    x0, y0 = 66 + k * 22, 70 - k * 22
    d.rectangle((x0, y0, x0 + w, y0 + h), fill=(255, 255, 255, alpha), outline=(23, 105, 90, 255), width=4)
x0, y0 = 66, 70
for i, frac in enumerate((0.75, 0.6, 0.75, 0.5)):   # 앞 장의 글줄
    y = y0 + 34 + i * 26
    d.rounded_rectangle((x0 + 18, y, x0 + 18 + int((w - 36) * frac), y + 9), radius=4, fill=(23, 105, 90, 200))
out = Path(__file__).resolve().parent / "agent.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.with_suffix(".png"))
print(out)
