#!/usr/bin/env python3
"""Deterministic standard-library GLB construction for V2; no external models."""
import hashlib
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDINGS = ROOT / "server/data/buildings.json"
CITY = ROOT / "tools/sim/data/city_objects_proposed/catalog.json"
DEST = ROOT / "client/models"
STAGES = ("Foundation", "Frame", "Walls", "Roof", "Details")
COLORS = {
    "pine": "#386c57", "forest": "#22483b", "mint": "#b7efa5",
    "cream": "#eef5e8", "stone": "#a1b9ad", "amber": "#e9b85c",
    "brick": "#b87f68", "blue": "#729bb4", "dark": "#173a30",
    "red": "#f0a29b", "green": "#7bc67e", "sand": "#c5a77a",
}
PALETTES = {
    "farm": ("sand", "forest", "mint", "amber"),
    "factory": ("stone", "brick", "dark", "amber"),
    "extraction": ("sand", "stone", "dark", "amber"),
    "warehouse": ("stone", "forest", "cream", "amber"),
    "retail": ("stone", "cream", "blue", "amber"),
    "housing": ("stone", "cream", "pine", "red"),
    "office": ("stone", "cream", "blue", "amber"),
    "civic": ("stone", "cream", "blue", "amber"),
    "cultural": ("stone", "cream", "mint", "amber"),
    "commercial": ("stone", "cream", "blue", "amber"),
    "residential": ("stone", "cream", "pine", "amber"),
    "public_green": ("sand", "green", "forest", "cream"),
    "transport": ("stone", "dark", "blue", "amber"),
    "industrial_civic": ("stone", "cream", "dark", "amber"),
}

def catalog():
    b = json.loads(BUILDINGS.read_text(encoding="utf-8"))
    c = json.loads(CITY.read_text(encoding="utf-8"))["objects"]
    return ([dict(entry, family="buildings", width=entry["size"]["width"],
                  height=entry["size"]["height"]) for entry in b]
            + [dict(entry, family="city", category=entry["style_id"]) for entry in c])

class Model:
    def __init__(self, entry):
        self.e = entry
        self.width = entry["width"] * 20.0
        self.depth = entry["height"] * 20.0
        self.palette = PALETTES.get(entry["category"], PALETTES["civic"])
        self.geo = [[] for _ in STAGES]
        self.triangles = 0

    def tri(self, stage, a, b, c, color):
        ux, uy, uz = (b[i]-a[i] for i in range(3))
        vx, vy, vz = (c[i]-a[i] for i in range(3))
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        length = math.sqrt(nx*nx+ny*ny+nz*nz)
        if length < 1e-7:
            raise ValueError("degenerate triangle")
        self.geo[stage].append((a, b, c, (nx/length, ny/length, nz/length), color))
        self.triangles += 1

    def quad(self, stage, a, b, c, d, color):
        self.tri(stage, a, b, c, color)
        self.tri(stage, a, c, d, color)

    def box(self, stage, x, y, z, w, h, d, color=1):
        if min(w, h, d) <= 0:
            raise ValueError("non-positive box")
        xa, xb = x-w/2, x+w/2
        ya, yb = y, y+h
        za, zb = z-d/2, z+d/2
        p = [(xa,ya,za),(xb,ya,za),(xb,ya,zb),(xa,ya,zb),
             (xa,yb,za),(xb,yb,za),(xb,yb,zb),(xa,yb,zb)]
        for face in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),
                     (2,3,7,6),(3,0,4,7)]:
            self.quad(stage, *(p[i] for i in face), color)

    def cylinder(self, stage, x, y, z, r, h, color=2, sides=6):
        if h <= 0 or r <= 0:
            raise ValueError("invalid cylinder")
        # triangle fan caps + wall triangles, deterministic normals
        for i in range(sides):
            a, b = 2*math.pi*i/sides, 2*math.pi*(i+1)/sides
            p=(x+r*math.cos(a),y,z+r*math.sin(a))
            q=(x+r*math.cos(b),y,z+r*math.sin(b))
            u=(p[0],y+h,p[2])
            v=(q[0],y+h,q[2])
            self.tri(stage,p,u,v,color)
            self.tri(stage,p,v,q,color)
            self.tri(stage,(x,y,z),p,q,color)
            self.tri(stage,(x,y+h,z),v,u,color)

    def roof(self, x, y, z, w, d, height=2, color=2):
        xa,xb=x-w/2,x+w/2
        za,zb=z-d/2,z+d/2
        p=(x,y+height,za); q=(x,y+height,zb)
        a=(xa,y,za); b=(xb,y,za); c=(xb,y,zb); f=(xa,y,zb)
        self.quad(3,a,b,p,p if False else (x,y+height,za),color) if False else None
        self.tri(3,a,b,p,color)
        self.quad(3,b,c,q,p,color)
        self.tri(3,c,f,q,color)
        self.quad(3,f,a,p,q,color)

    def build(self):
        e = self.e
        ident = e["id"]
        kind = e["category"]
        w,d=self.width,self.depth
        # Foundation spans the exact parcel bounding rectangle; every part sits inside it.
        self.box(0,0,0,0,w,0.65,d,0)
        hall_h = 7 if kind in ("farm","retail","public_green","transport") else 13
        if kind in ("office","housing","civic","residential","commercial"):
            hall_h = 17
        if kind=="cultural": hall_h=13
        hall_h=min(hall_h,25)
        bw,bd=w*.72,d*.68
        if ident in ("field","park","sports_ground","embankment","bridge","quarry"):
            bw,bd=w*.3,d*.3
            hall_h=2.5
        # Frame: four distinct posts and top ring of beams.
        for xx in (-bw*.46,bw*.46):
            for zz in (-bd*.46,bd*.46):
                self.box(1,xx,0.65,zz,0.65,hall_h*.77,0.65,2)
        self.box(1,0,hall_h*.75,0,bw,.55,.65,2)
        self.box(1,0,hall_h*.75,0,.65,.55,bd,2)
        self.box(2,0,.65,0,bw,hall_h*.73,bd,1)
        self.box(3,0,hall_h*.73+.65,0,bw*1.08,.8,bd*1.08,2)
        self.box(4,0,2,bd*.505,bw*.45,2.0,.16,3)
        self.box(4,0,1.0,bd*.53,bw*.38,1.1,.15,2)
        # Identifying architecture uses curated motifs, not generic category-only boxes.
        if ident=="field":
            for i in range(7):
                self.box(4,-w*.38+i*w*.125,.7,0,.55,.65,d*.74,2)
        elif ident=="apiary":
            for i in range(5):
                self.box(4,-w*.29+i*w*.145,.7,d*.21,2,1.8,2.2,3)
                self.box(4,-w*.29+i*w*.145,2.5,d*.21,2.3,.35,2.6,2)
        elif ident in ("mill","spinning_mill","malthouse"):
            self.cylinder(4,0,hall_h*.58,bd*.53,1.25,.6,3)
            for i in range(4):
                ang=i*math.pi/2
                self.box(4,math.cos(ang)*3,hall_h*.59+math.sin(ang)*3,bd*.55,.7,5,.55,3)
        elif ident in ("oil_well","gas_well"):
            for i in range(4):
                angle=i*math.pi/2
                self.box(4,math.cos(angle)*3,.65,math.sin(angle)*3,.6,16,.6,2)
            for j in range(4):
                self.box(4,0,4+j*3,0,7,.32,.4,3)
            self.cylinder(4,w*.3,.65,d*.25,2,6,3)
        elif ident in ("refinery","polymer_plant","water_works","gas_station_utility"):
            for i in range(3):
                self.cylinder(4,-w*.28+i*w*.28,.65,d*.29,2.3,9+i*3,2)
                self.cylinder(4,-w*.28+i*w*.28,10+i*3,d*.29,1.45,1.0,3)
        elif ident in ("bakery","smokehouse","cement_plant","steel_mill",
                       "glass_plant","sugar_plant","beverage_plant"):
            self.cylinder(4,w*.27,hall_h*.7,-d*.15,1.25,9,3)
            self.cylinder(4,-w*.24,hall_h*.7,-d*.15,.9,5,2)
        elif ident in ("quarry","mine"):
            for i in range(5):
                self.box(4,-w*.33+i*w*.15,.67,-d*.1,3,1+i*.9,d*.48,2)
        elif ident in ("logging_camp","sawmill","furniture_workshop"):
            for i in range(4):
                self.cylinder(4,-w*.3+i*w*.17,.8,d*.3,1.1,6,3)
        elif ident in ("dairy","poultry_farm","fishery","slaughter"):
            for i in range(3):
                self.box(4,-w*.24+i*w*.24,.7,d*.26,3,2.5,3,3)
        elif ident in ("warehouse","feed_plant","electronics_plant","appliance_plant","auto_plant"):
            for i in range(3):
                self.box(4,-bw*.27+i*bw*.27,1,bd*.52,bw*.16,hall_h*.38,.3,3)
        elif ident=="fuel_station":
            self.box(4,0,7,d*.2,w*.68,.8,d*.45,2)
            for i in (-1,1):
                self.box(4,i*w*.19,.7,d*.2,2,4,2,3)
                self.box(4,i*w*.19,4.7,d*.2,.5,2.3,.5,2)
        elif ident=="car_dealer":
            for i in range(3):
                self.box(4,-w*.23+i*w*.23,.67,d*.3,5,1.8,2.4,3)
        elif ident in ("housing","housing_block","office","office_block","shopping_center","supermarket"):
            for floor in range(2,round(hall_h*.72),3):
                self.box(4,0,float(floor),bd*.505,bw*.74,.3,.15,3)
        elif ident in ("city_hall","police_station","fire_station"):
            self.box(4,0,hall_h*.8,0,.3,5,.3,3)
            self.box(4,1.3,hall_h*.8+3,0,2.5,1.2,.2,3)
        elif ident in ("school","hospital","clinic","culture_center"):
            self.box(4,0,hall_h*.49,bd*.54,4,4,.3,3)
            if ident in ("hospital","clinic"):
                self.box(4,0,hall_h*.49,bd*.57,1.0,7,.35,3)
        elif ident=="mosque":
            self.cylinder(4,0,hall_h*.75,0,4,3,3,8)
            self.cylinder(4,w*.36,0,-d*.24,1.2,22,2)
            self.cylinder(4,w*.36,22,-d*.24,1.7,1.2,3)
        elif ident=="temple":
            self.cylinder(4,0,hall_h*.75,0,3.6,5,3,8)
            self.box(4,0,hall_h+5,0,.7,4,.7,3)
            self.box(4,0,hall_h+7,0,3.0,.6,.7,3)
        elif ident in ("park","sports_ground","embankment"):
            for i in range(4):
                xx=-w*.3+i*w*.2
                self.cylinder(4,xx,.65,d*.2,1.5,2,1)
                self.cylinder(4,xx,2.65,d*.2,3.2,4,2)
        elif ident in ("bus_stop","station"):
            self.box(4,0,5,d*.15,w*.63,.6,d*.3,2)
            for i in (-1,1):
                self.box(4,i*w*.22,.65,d*.15,.6,4.4,.6,3)
        elif ident in ("power_substation",):
            for i in range(3):
                self.cylinder(4,-w*.28+i*w*.28,.65,d*.25,1.7,4,2)
                self.box(4,-w*.28+i*w*.28,5,d*.25,4,.4,1,3)
        else:
            # Differentiated silhouettes per ID via stable ASCII digest: signage pylons / roof modules.
            digest=hashlib.sha256(ident.encode()).digest()
            for i in range(2+digest[0]%3):
                self.box(4,-bw*.34+i*bw*.17,hall_h*.8,0,1.7,1.5+(digest[i+1]%5),1.7,3)
        if self.triangles>400:
            raise ValueError(f"{ident}: {self.triangles} triangles")
        return self

    def encode(self):
        """Five separate stage nodes, each with up to four shared material meshes."""
        binary=bytearray()
        views=[]; access=[]; meshes=[]; nodes=[{"name":"Root","children":[1,2,3,4,5]}]
        mats=[]
        for name in self.palette:
            value=COLORS[name]
            rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
            mats.append({"name":"lunex_"+name,
                         "pbrMetallicRoughness":{"baseColorFactor":rgb+[1.0],
                         "metallicFactor":0.0,"roughnessFactor":0.95},
                         "doubleSided":False})
        def add_view(payload,target):
            while len(binary)%4: binary.append(0)
            offset=len(binary)
            binary.extend(payload)
            views.append({"buffer":0,"byteOffset":offset,"byteLength":len(payload),
                          "target":target})
            return len(views)-1
        for stage, name in enumerate(STAGES):
            primitives=[]
            for color in range(4):
                triangles=[q for q in self.geo[stage] if q[4]==color]
                if not triangles: continue
                positions=[];normals=[]
                for a,b,c,n,_ in triangles:
                    positions.extend(a+b+c)
                    normals.extend(n*3)
                vertex_count=len(positions)//3
                if vertex_count>65535: raise ValueError("ushort overflow")
                pv=add_view(struct.pack("<%sf"%len(positions),*positions),34962)
                nv=add_view(struct.pack("<%sf"%len(normals),*normals),34962)
                iv=add_view(struct.pack("<%sH"%vertex_count,*range(vertex_count)),34963)
                posacc=len(access)
                vecs=list(zip(*(iter(positions),)*3))
                access.append({"bufferView":pv,"componentType":5126,"count":vertex_count,
                               "type":"VEC3","min":[min(v[i] for v in vecs) for i in range(3)],
                               "max":[max(v[i] for v in vecs) for i in range(3)]})
                normalacc=len(access)
                access.append({"bufferView":nv,"componentType":5126,"count":vertex_count,
                               "type":"VEC3"})
                indexacc=len(access)
                access.append({"bufferView":iv,"componentType":5123,"count":vertex_count,
                               "type":"SCALAR","min":[0],"max":[vertex_count-1]})
                primitives.append({"attributes":{"POSITION":posacc,"NORMAL":normalacc},
                                   "indices":indexacc,"material":color,"mode":4})
            if not primitives: raise ValueError(f"empty stage {name}")
            mesh_index=len(meshes);meshes.append({"name":name,"primitives":primitives})
            nodes.append({"name":name,"mesh":mesh_index})
        while len(binary)%4:binary.append(0)
        gltf={"asset":{"version":"2.0","generator":"LunexEconom V2 deterministic stdlib"},
              "scene":0,"scenes":[{"nodes":[0]}],
              "nodes":nodes,"meshes":meshes,"materials":mats,
              "buffers":[{"byteLength":len(binary)}],
              "bufferViews":views,"accessors":access}
        meta=json.dumps(gltf,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()
        meta+=b" " * (-len(meta)%4)
        length=12+8+len(meta)+8+len(binary)
        return (struct.pack("<4sII",b"glTF",2,length)
                +struct.pack("<I4s",len(meta),b"JSON")+meta
                +struct.pack("<I4s",len(binary),b"BIN\0")+binary)

def generate():
    entries=catalog()
    if len(entries)!=64 or len({(e["family"],e["id"]) for e in entries})!=64:
        raise ValueError("expected 42 building and 22 city unique models")
    manifest={"schema":1,"models":{}}
    for e in entries:
        model=Model(e).build()
        data=model.encode()
        rel=f'{e["family"]}/{e["id"]}.glb'
        path=DEST/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        manifest["models"][rel]={"sha256":hashlib.sha256(data).hexdigest(),
                                 "bytes":len(data),"triangles":model.triangles,
                                 "width":e["width"],"height":e["height"]}
    (DEST/"manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8")
    print(f'Generated {len(entries)} original models; {sum(v["bytes"] for v in manifest["models"].values())} bytes')

if __name__=="__main__":
    generate()
