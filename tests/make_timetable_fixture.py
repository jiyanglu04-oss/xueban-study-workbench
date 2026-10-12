"""Create a clearly labelled synthetic screenshot for local OCR/UI verification."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def create(path: Path):
    image = Image.new('RGB', (1800, 1250), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 30)
    small = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 24)
    draw.text((75, 25), '课表识别测试（虚构课程）', fill='black', font=font)
    for i, day in enumerate('一二三四五'):
        draw.text((245+i*310,100),'星期'+day,fill='black',font=font)
    for section in range(1,9):
        y=200+(section-1)*125
        draw.text((70,y),str(section),fill='black',font=font)
        draw.line((150,y-15,1750,y-15),fill='#cccccc',width=2)
    for i in range(6):
        draw.line((160+i*310,170,160+i*310,1200),fill='#cccccc',width=2)
    courses=[('高等数学','陈老师','教学楼A301','1-16周(单)',0,1),
             ('大学英语','李老师','教学楼B205','2-16周(双)',1,3),
             ('程序设计','张老师','实验楼C301','1-18周',3,5)]
    for name,teacher,room,weeks,day,section in courses:
        x,y=185+day*310,200+(section-1)*125
        for j,text in enumerate((name,teacher,room,weeks)):
            draw.text((x,y+j*36),text,fill='black',font=font if j==0 else small)
    path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path)


if __name__ == '__main__':
    import sys
    create(Path(sys.argv[1]))
