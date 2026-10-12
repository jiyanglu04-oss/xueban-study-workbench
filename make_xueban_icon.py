"""将选定的学伴 logo 导出为 PNG 和 Windows 多尺寸 ICO；不修改原图。"""
import sys
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent
source = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'assets' / '学伴-logo.png'
im = Image.open(source).convert('RGBA')
im.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
canvas = Image.new('RGBA', (1024, 1024))
canvas.alpha_composite(im, ((1024 - im.width) // 2, (1024 - im.height) // 2))
canvas.save(root / 'assets' / '学伴-logo.png')
for size in (16, 24, 32, 48, 64, 128, 256):
    canvas.resize((size, size), Image.Resampling.LANCZOS).save(root / 'assets' / f'学伴-{size}.png')
canvas.save(root / 'assets' / 'xueban-v1.ico', format='ICO', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print('Icon exported:', root / 'assets' / 'xueban-v1.ico')
