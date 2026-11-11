"""Render recorded SUMO positions and signal stages; this is not a SUMO GUI capture."""
from pathlib import Path
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
import bootstrap
bootstrap.configure()
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
recording=ROOT/'results/replay/ped-burst-1001/motion.json'
frames=json.loads(recording.read_text(encoding='utf-8'))
seconds=json.loads(recording.with_name('seconds.json').read_text(encoding='utf-8'))
network=ET.parse(ROOT/'network/corridor.net.xml').getroot()
groups=[]
for site,ew_edges in [('J0',['w_in','link_w']),('J1',['link_e','e_in'])]:
    vehicle={int(c.get('linkIndex')) for c in network.findall('connection') if c.get('tl')==site and not c.get('from').startswith(':')}
    ew={int(c.get('linkIndex')) for c in network.findall('connection') if c.get('tl')==site and c.get('from') in ew_edges}
    count=len(network.find(f"tlLogic[@id='{site}']/phase").get('state'))
    groups.append({'EW':ew,'NS':vehicle-ew,'PED':set(range(count))-vehicle})
font_path=Path('C:/Windows/Fonts/malgun.ttf')
def font(size):
    try:
        return ImageFont.truetype(str(font_path) if font_path.exists() else 'DejaVuSans.ttf',size)
    except OSError:
        return ImageFont.load_default(size=size)

WIDTH,HEIGHT=1200,760
SCALE=3.05
def point(x,y):
    return (int(80+x*SCALE),int(650-y*SCALE))
def box(draw,extent,fill):
    x0,y0=point(extent[0],extent[1]); x1,y1=point(extent[2],extent[3])
    draw.rectangle((min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1)),fill=fill)

images=[]
for frame in frames:
    im=Image.new('RGB',(WIDTH,HEIGHT),(235,241,230))
    draw=ImageDraw.Draw(im)
    draw.text((30,18),'PedLink-Corridor2 | One central DQN, two intersections',font=font(26),fill=(25,35,50))
    draw.text((30,58),f'SUMO trajectory replay  |  adaptive / ped-burst / seed 1001  |  t = {frame["time"]} s',font=font(19),fill=(50,65,75))
    box(draw,(0,78.8,340,91.2),(190,196,184))
    box(draw,(0,81.8,340,88.2),(58,66,78))
    for x in [100,240]:
        box(draw,(x-6.2,0,x+6.2,170),(190,196,184))
        box(draw,(x-3.2,0,x+3.2,170),(58,66,78))
        box(draw,(x-6.2,78.8,x+6.2,91.2),(58,66,78))
        for shift in [-13,13]:
            for stripe in range(6):
                px=x-2.7+stripe*.95
                box(draw,(px,85+shift-2,px+.45,85+shift+2),(235,239,234))
                py=85-2.7+stripe*.95
                box(draw,(x+shift-2,py,x+shift+2,py+.45),(235,239,234))
        for y in range(3,170,7):
            if abs(y-85)>18:
                draw.line([point(x,y),point(x,y+3)],fill=(220,225,215),width=2)
    for x in range(3,340,7):
        if min(abs(x-100),abs(x-240))>18:
            draw.line([point(x,85),point(x+3,85)],fill=(220,225,215),width=2)
    for j,x in enumerate([100,240]):
        stage=frame['stages'][j]
        px,py=point(x-32,143)
        draw.rounded_rectangle((px-8,py-8,px+238,py+92),radius=10,fill=(255,255,255),outline=(150,166,157))
        draw.text((px,py),f'J{j} : {stage}',font=font(22),fill=(25,35,50))
        for k,label in enumerate(['EW','NS','PED']):
            actual=seconds[frame['time']-1]['sites'][j]['signal']
            green=any(actual[i] in 'Gg' for i in groups[j][label])
            yellow=any(actual[i]=='y' for i in groups[j][label])
            color=(45,195,100) if green else (245,185,35) if yellow else (225,65,65)
            draw.ellipse((px+k*78,py+38,px+k*78+17,py+55),fill=color)
            draw.text((px+k*78,py+60),label,font=font(15),fill=(25,35,50))
    for vehicle in frame['vehicles']:
        x,y=point(*vehicle['xy'])
        angle=math.radians(vehicle['angle'])
        forward=(math.sin(angle),-math.cos(angle)); side=(-forward[1],forward[0])
        shape=[(x+a*7.5*forward[0]+b*3.5*side[0],y+a*7.5*forward[1]+b*3.5*side[1])
               for a,b in [(1,1),(1,-1),(-1,-1),(-1,1)]]
        color=(40,125,235) if int(hashlib.sha256(vehicle['id'].encode()).hexdigest()[:2],16)%2 else (90,155,215)
        draw.polygon(shape,fill=color,outline=(20,55,95))
    for person in frame['persons']:
        x,y=point(*person['xy'])
        draw.ellipse((x-3,y-3,x+3,y+3),fill=(240,105,30),outline=(130,60,20))
    draw.text((30,700),f'Cars: {len(frame["vehicles"])}   Pedestrians: {len(frame["persons"])}   |   positions and phases recorded from SUMO',
              font=font(19),fill=(35,50,65))
    draw.text((30,730),'Schematic replay of real simulation data; open START_SIMULATION.cmd for native SUMO GUI.',font=font(15),fill=(75,85,90))
    images.append(im.convert('P',palette=Image.Palette.ADAPTIVE,colors=128))
media=ROOT/'media'
media.mkdir(exist_ok=True)
images[0].save(media/'two-junctions-replay.gif',save_all=True,append_images=images[1:],duration=180,loop=0,optimize=True)
images[len(images)//2].convert('RGB').save(media/'two-junctions-preview.png')
print(json.dumps({'frames':len(frames),'gif':str(media/'two-junctions-replay.gif')}))
