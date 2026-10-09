from PIL import Image, ImageDraw, ImageFont
import sys

img = Image.new("RGB", (1600, 1200), color="white")
d = ImageDraw.Draw(img)
try:
    font = ImageFont.load_default(size=48)
except TypeError:
    font = ImageFont.load_default()

d.text((50, 50), "COMMUNITY NOTICE", fill=(0, 0, 0), font=font)
d.text(
    (50, 150), "Application deadline: 18 October 2026", fill=(0, 0, 0), font=font
)
d.text((50, 250), "Required document: ID proof", fill=(0, 0, 0), font=font)

img.save("sample_notice.png", format="PNG")
print("Saved sample_notice.png")
