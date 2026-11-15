"""Display-only city scene and tracked car bodies. No traffic/vehicle dynamics setters.

Native polygons are attached to actual SUMO vehicles through addDynamics, so they
follow the simulated position and turning angle. Streets, signals, and buildings
are graphical shapes, never additional drivable lanes or pedestrian demand.
"""
from __future__ import annotations
import math
import json
import os
from pathlib import Path


class CityAppearance:
    def __init__(self, connection, out, level):
        self.c = connection
        self.cx, self.cy = self.c.junction.getPosition('J')
        self.counter = 0
        self.cars = set()
        self.last_signals = None
        self.signal_ids = {}
        self.shapes = {}
        self.out, self.level = Path(out), level
        self.preview = None

    def poly(self, shape, color, layer=10, name=None, tracked=None, absolute=False):
        self.counter += 1
        name = name or f'city.{self.counter}'
        pts = shape if absolute else [(self.cx+x,self.cy+y) for x,y in shape]
        self.c.polygon.add(name,pts,tuple(color),fill=True,polygonType='display-only',layer=layer)
        self.shapes[name] = dict(shape=pts,color=tuple(color),layer=layer,vehicle=tracked)
        if tracked:
            self.c.polygon.addDynamics(name,trackedObjectID=tracked,rotate=True)
        return name

    def rect(self,x,y,w,h,color,layer=10):
        return self.poly([(x,y),(x+w,y),(x+w,y+h),(x,y+h)],color,layer)

    def circle(self,x,y,r,color,layer=12):
        return self.poly([(x+r*math.cos(i*math.tau/20),y+r*math.sin(i*math.tau/20)) for i in range(20)],color,layer)

    def tree(self,x,y,r=2):
        self.circle(x+.7,y-.7,r,(103,124,95),10)
        self.circle(x,y,r,(58,119,77),11)
        self.circle(x-.4,y+.4,r*.72,(80,148,90),12)

    def building(self,x,y,w,h,color):
        self.rect(x+1.6,y-1.8,w,h,(137,146,137),8)
        self.rect(x,y,w,h,(83,91,99),10)
        self.rect(x+.5,y+.6,w-1,h-1.2,color,11)
        # South facade, parapet, blue glazing, and roof-mounted equipment.
        self.rect(x+.5,y+.6,w-1,1.7,tuple(max(0,v-26) for v in color),12)
        for wx in range(2,int(w)-2,3):
            self.rect(x+wx,y+.85,1.5,1,(159,195,202),13)
        self.rect(x+2,y+h-4,4,2,(110,124,137),12)
        self.rect(x+2.4,y+h-3.7,3.2,1.3,(169,185,193),13)
        if w>19:
            self.rect(x+w-6,y+h-5,3,2.6,(124,137,144),12)
            self.rect(x+w-5.6,y+h-4.6,2.2,1.8,(188,197,199),13)

    def parked_car(self,x,y,color,angle=0):
        self.car_parts(None,self.cx+x,self.cy+y,angle,color,layer=25)

    def parking(self,x,y,w=22,h=16):
        self.rect(x,y,w,h,(163,171,174),9)
        self.rect(x+1,y+1,w-2,h-2,(100,112,122),10)
        for i in range(1,int(w)-2,4):
            self.rect(x+i,y+1,.13,5.5,(227,230,224),11)
            self.rect(x+i,y+h-6.5,.13,5.5,(227,230,224),11)
        for i,col in [(0,(212,218,224)),(2,(79,112,147)),(3,(192,103,81))]:
            if 2+i*4 < w-2:
                self.parked_car(x+3+i*4,y+6,col)

    def build(self):
        # Sidewalk paving under the original carriageway; cosmetic curbs above it.
        self.rect(-460,-9.6,920,19.2,(190,197,190),-3)
        self.rect(-9.6,-460,19.2,920,(190,197,190),-3)
        self.rect(-460,-8.8,920,17.6,(221,216,202),-2)
        self.rect(-8.8,-460,17.6,920,(221,216,202),-2)
        # Cover only the existing asphalt width; also hides the cyan detector display.
        self.rect(-460,-3.2,920,6.4,(61,69,80),200)
        self.rect(-3.2,-460,6.4,920,(61,69,80),200)
        self.rect(-7.2,-7.2,14.4,14.4,(61,69,80),200)
        for side in (-1,1):
            for start,end in [(-460,-8),(8,460)]:
                self.rect(start,side*3.25-.09,end-start,.18,(243,239,221),201)
                self.rect(side*3.25-.09,start,.18,end-start,(243,239,221),201)
                for offset in (-.13,.13):
                    self.rect(start,offset-.045,end-start,.09,(235,192,68),201)
                    self.rect(offset-.045,start,.09,end-start,(235,192,68),201)
        # Crosswalk paint inside the physical SUMO stop lines: no pedestrian model added.
        for i in range(7):
            p=-2.95+i*.88
            for side in (-1,1):
                self.rect(p,side*5.7-.85,.48,1.7,(242,242,226),202)
                self.rect(side*5.7-.85,p,1.7,.48,(242,242,226),202)
        for x,y,w,h in [(-3.2,7.05,3.08,.25),(.12,-7.3,3.08,.25),(7.05,.12,.25,3.08),(-7.3,-3.2,.25,3.08)]:
            self.rect(x,y,w,h,(249,248,235),203)
        # Pavement tile joints, small curbside planters, and road direction arrows.
        for t in range(-140,141,4):
            if abs(t)<12: continue
            for side in (-1,1):
                self.rect(t,side*6-2.5,.055,5,(192,190,178),1)
                self.rect(side*6-2.5,t,5,.055,(192,190,178),1)
        for d,x,y,angle in [('N',-1.6,24,180),('S',1.6,-24,0),('E',24,1.6,270),('W',-24,-1.6,90)]:
            arrow=[(-.15,-3),(.15,-3),(.15,-1.1),(.65,-1.1),(0,0),(-.65,-1.1),(-.15,-1.1)]
            self.poly(self.transform(arrow,self.cx+x,self.cy+y,angle),(235,237,225),204,absolute=True)

        # Four distinct blocks, all clear of the drivable lanes and junction.
        self.rect(-91,13,76,47,(206,202,186),2)
        self.building(-83,22,27,23,(181,139,117))
        self.building(-48,22,28,23,(184,183,165))
        self.parking(-82,48,58,17)
        for x in (-86,-52,-17): self.tree(x,16,1.8)

        # North-east neighborhood park, path, fountain, and benches.
        self.rect(13,13,54,45,(134,169,119),2)
        self.rect(15,15,50,41,(155,187,136),3)
        self.rect(35,15,3,41,(215,211,189),4)
        self.rect(15,32,50,3,(215,211,189),4)
        self.circle(36.5,33.5,6,(220,221,206),5)
        self.circle(36.5,33.5,3.8,(115,170,190),6)
        self.circle(35.7,34.2,2.7,(156,205,214),7)
        for x,y in [(21,21),(55,21),(22,47),(54,48),(60,39),(19,38)]: self.tree(x,y,2.8)
        for x,y in [(26,29),(45,37)]:
            self.rect(x,y,3.5,.7,(122,89,66),9)
            self.rect(x+.3,y-.4,.3,1.2,(70,75,72),8)
            self.rect(x+2.8,y-.4,.3,1.2,(70,75,72),8)
        self.building(75,19,25,29,(172,188,189))
        self.tree(71,16,2)

        self.rect(-94,-66,80,51,(207,204,188),2)
        self.building(-87,-52,28,32,(171,157,142))
        self.building(-50,-48,30,28,(190,165,142))
        for x in (-85,-67,-47,-28): self.tree(x,-14,1.9)
        self.parking(-85,-73,61,16)

        self.rect(13,-65,91,51,(199,204,190),2)
        self.building(19,-46,35,25,(179,192,195))
        self.building(63,-48,33,27,(179,164,149))
        self.parking(19,-67,35,16)
        for x in (17,56,101): self.tree(x,-16,2)
        for x,y,w,h in [(-135,20,28,34),(-129,-50,25,27),(113,18,30,31),(114,-51,28,30),(-82,82,33,27),(19,81,34,30)]:
            self.building(x,y,w,h,(177,181,169))
        for t in (-120,-100,-72,-52,-32,32,52,72,100,120):
            for side in (-1,1):
                if abs(t)>85: self.tree(t,side*7,1.7)

        self.build_signals()
        self.update()

    def build_signals(self):
        positions={'N':(-7.5,12.5),'E':(12.5,7.5),'S':(7.5,-12.5),'W':(-12.5,-7.5)}
        self.link_origins=[]
        for group in self.c.trafficlight.getControlledLinks('J'):
            self.link_origins.append(group[0][0][0])
        for d,(x,y) in positions.items():
            self.rect(x-.15,y-5,.3,5,(96,106,112),590)
            self.rect(x-1.15,y-3.25,2.3,6.5,(24,31,39),600)
            self.rect(x-.95,y-3.05,1.9,6.1,(40,48,55),601)
            self.signal_ids[d]=[self.circle(x,y+dy,.68,(50,57,60),602) for dy in (2,0,-2)]

    @staticmethod
    def transform(shape,x,y,angle):
        a=math.radians(angle)
        return [(x+u*math.cos(a)+v*math.sin(a),y-u*math.sin(a)+v*math.cos(a)) for u,v in shape]

    def car_parts(self,vid,x,y,angle,color,layer=500):
        def part(shape,col,z):
            pid=self.poly(self.transform(shape,x,y,angle),col,z,tracked=vid,absolute=True)
            if vid: self.shapes[pid]['local_shape']=shape
            return pid
        def box(x0,y0,w,h,col,z):
            return part([(x0,y0),(x0+w,y0),(x0+w,y0+h),(x0,y0+h)],col,z)
        # Vehicle position is the center of the front bumper; every shape extends behind it.
        body=[(-.7,0),(.7,0),(.95,-.35),(.95,-4.65),(.7,-5),(-.7,-5),(-.95,-4.65),(-.95,-.35)]
        part(body,(30,38,46),layer)
        part([(-.67,-.1),(.67,-.1),(.84,-.4),(.84,-4.6),(.65,-4.85),(-.65,-4.85),(-.84,-4.6),(-.84,-.4)],color,layer+1)
        # Tires, front/rear glazing, roof and a small highlight give a clear car silhouette.
        for side in (-1,1):
            for longitudinal in (-1.25,-3.85): box(side*.93-.12,longitudinal,.24,.65,(23,29,34),layer+2)
        part([(-.68,-1.2),(.68,-1.2),(.53,-1.95),(-.53,-1.95)],(148,196,214),layer+3)
        box(-.54,-3.2,1.08,1.23,tuple(min(255,v+20) for v in color),layer+3)
        part([(-.53,-3.3),(.53,-3.3),(.68,-3.9),(-.68,-3.9)],(89,132,151),layer+3)
        box(-.69,-.3,.38,.15,(255,247,194),layer+4)
        box(.31,-.3,.38,.15,(255,247,194),layer+4)
        box(-.7,-4.8,.32,.16,(240,69,58),layer+4)
        box(.38,-4.8,.32,.16,(240,69,58),layer+4)

    def update(self):
        signals=self.c.trafficlight.getRedYellowGreenState('J')
        if signals!=self.last_signals:
            for d,ids in self.signal_ids.items():
                states=[signals[i].lower() for i,origin in enumerate(self.link_origins) if origin==d]
                lit=1 if 'y' in states else 2 if 'g' in states else 0
                for i,pid in enumerate(ids):
                    colors=[(255,73,63),(255,190,42),(35,226,130)]
                    self.c.polygon.setColor(pid,colors[i] if i==lit else (57,64,67))
                    self.shapes[pid]['color']=colors[i] if i==lit else (57,64,67)
            self.last_signals=signals
        palette={'N':(216,86,83),'E':(73,138,197),'S':(225,166,56),'W':(60,156,119)}
        for vid in self.c.vehicle.getIDList():
            if vid in self.cars: continue
            x,y=self.c.vehicle.getPosition(vid)
            angle=self.c.vehicle.getAngle(vid)
            self.car_parts(vid,x,y,angle,palette.get(vid[0],(175,183,191)))
            self.cars.add(vid)
        if self.preview is None and self.c.simulation.getTime()>=180:
            self.capture_preview()

    def capture_preview(self):
        """Export actual live SUMO coordinates without blocking OpenGL pixel readback."""
        poses={v:(*self.c.vehicle.getPosition(v),self.c.vehicle.getAngle(v)) for v in self.c.vehicle.getIDList()}
        shapes=[]
        for rec in self.shapes.values():
            if rec['vehicle']:
                if rec['vehicle'] not in poses: continue
                points=self.transform(rec['local_shape'],*poses[rec['vehicle']])
            else:
                points=rec['shape']
            shapes.append(dict(shape=points,color=rec['color'],layer=rec['layer']))
        self.preview=dict(second=self.c.simulation.getTime(),level=self.level,center=[self.cx,self.cy],
                          trafficlight_state=self.c.trafficlight.getRedYellowGreenState('J'),
                          vehicles=len(poses),shapes=sorted(shapes,key=lambda r:r['layer']))
        (self.out/'scene-frame.json').write_text(json.dumps(self.preview),encoding='utf-8')
        self.write_svg()

    def write_svg(self):
        width,height=1200,700
        scale=width/220
        def screen(x,y): return ((x-self.cx+110)*scale,(62-(y-self.cy))*scale)
        items=[]
        for rec in self.preview['shapes']:
            points=' '.join(f'{sx:.2f},{sy:.2f}' for sx,sy in (screen(x,y) for x,y in rec['shape']))
            col=','.join(str(v) for v in rec['color'][:3])
            items.append(f'<polygon points="{points}" fill="rgb({col})"/>')
        title=f'SUMO | {self.level.upper()} demand | t={int(self.preview["second"])}s | actual vehicle positions and signals'
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><defs><clipPath id="view"><rect width="{width}" height="{height}"/></clipPath></defs><rect width="100%" height="100%" fill="#d8e2d3"/><g clip-path="url(#view)">'+''.join(items)+f'</g><rect x="18" y="16" width="720" height="32" rx="6" fill="#ffffff" fill-opacity=".92"/><text x="30" y="37" font-family="Arial,sans-serif" font-size="15" fill="#273746">{title}</text></svg>'
        (self.out/'simulation.svg').write_text(svg,encoding='utf-8')

    def finish_preview(self):
        if self.preview is None: return
        # Standard vector plotting only; no screenshot editing or simulated vehicle positions.
        from .common import ROOT
        os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'tmp/matplotlib'))
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Polygon
        fig=Figure(figsize=(12,7),dpi=120,facecolor='#d8e2d3')
        canvas=FigureCanvasAgg(fig)
        ax=fig.add_axes((0,0,1,1))
        ax.set_facecolor('#d8e2d3')
        ax.set_xlim(self.cx-110,self.cx+110)
        ax.set_ylim(self.cy-66,self.cy+62)
        ax.set_aspect('equal',adjustable='box')
        ax.set_axis_off()
        for r in self.preview['shapes']:
            ax.add_patch(Polygon(r['shape'],closed=True,facecolor=tuple(v/255 for v in r['color'][:3]),edgecolor='none',antialiased=True))
        ax.text(self.cx-106,self.cy+58,
                f'SUMO  |  {self.level.upper()} demand  |  t={int(self.preview["second"])}s  |  live vehicle positions and signals',
                fontsize=10,color='#273746',ha='left',va='top',bbox=dict(facecolor='white',alpha=.95,edgecolor='none',pad=7))
        canvas.print_png(str(self.out/'simulation.png'))
