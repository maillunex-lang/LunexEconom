"""Create original, single-material low-poly GLB assets for the 2.5D Android world.

Run: blender --background --python tools/build_models_blender.py -- --output client/world3d/models
Blender Z-up -> glTF Y-up; Blender front -Y -> glTF facade +Z.
All units are metres, footprints are centered, grounded, with 2m per tile.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy

PALETTE = {
    "beige": (.69, .64, .55, 1),
    "sand": (.76, .69, .57, 1),
    "light": (.81, .81, .77, 1),
    "brick": (.61, .39, .31, 1),
    "brick2": (.71, .48, .37, 1),
    "blue": (.21, .38, .47, 1),
    "window": (.17, .32, .43, 1),
    "window2": (.25, .43, .55, 1),
    "teal": (.25, .47, .44, 1),
    "green": (.24, .47, .33, 1),
    "grass": (.33, .47, .30, 1),
    "canopy": (.23, .38, .29, 1),
    "leaves2": (.35, .52, .34, 1),
    "wood": (.42, .32, .23, 1),
    "dark": (.26, .29, .28, 1),
    "asphalt": (.24, .27, .29, 1),
    "pave": (.55, .57, .54, 1),
    "roof": (.37, .39, .38, 1),
    "yellow": (.86, .72, .35, 1),
    "white": (.87, .87, .81, 1),
    "red": (.72, .27, .28, 1),
}


class Geometry:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.colors = []
        self.face_colors = []

    def polygon(self, vertices, color):
        start = len(self.verts)
        self.verts.extend(vertices)
        self.faces.append(tuple(range(start, start + len(vertices))))
        self.face_colors.append(PALETTE[color])

    def box(self, x, y, z, w, d, h, color, roof=None):
        x0, x1 = x-w/2, x+w/2
        y0, y1 = y-d/2, y+d/2
        z0, z1 = z, z+h
        v = ((x0,y0,z0), (x1,y0,z0), (x1,y1,z0), (x0,y1,z0),
             (x0,y0,z1), (x1,y0,z1), (x1,y1,z1), (x0,y1,z1))
        for face in ((0,3,2,1),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
            self.polygon([v[i] for i in face], color)
        self.polygon([v[i] for i in (4,5,6,7)], roof or color)

    def pyramid(self, x,y,z,w,d,h,color):
        p=[(x-w/2,y-d/2,z),(x+w/2,y-d/2,z),(x+w/2,y+d/2,z),(x-w/2,y+d/2,z)]
        self.polygon([p[3],p[2],p[1],p[0]],color)
        for i in range(4):
            self.polygon([p[i],p[(i+1)%4],(x,y,z+h)],color)

    def facade(self, w, d, floors, window_pairs, wall, accent):
        body_w = w*2-.35
        body_d = d*2-.35
        floor_h = .55 if floors > 6 else .66
        height=floors*floor_h + .42
        self.box(0,0,0,body_w,body_d,height,wall)
        self.box(0,0,height,body_w+.12,body_d+.1,.19,"roof")
        front=-body_d/2-.016
        back=body_d/2+.016
        # Distinct floor bands and a front door, safely inside the footprint.
        for floor in range(floors):
            z=.22+floor*floor_h
            if floor:
                self.box(0,front+.025,z-.045,body_w-.03,.035,.06,accent)
            for ix in range(window_pairs):
                cx=(ix-(window_pairs-1)/2)*(body_w*.68/max(1,window_pairs))
                width=min(.27,body_w/(window_pairs*2.4))
                self.box(cx,front-.005,z+.12,width,.025,.27,"window2" if floor%2 else "window")
                self.box(cx,back+.005,z+.12,width,.025,.27,"window")
        self.box(-body_w*.28, front-.028, 0, .32,.06,.55, "dark")
        self.box(-body_w*.28, front-.09, .54, .52,.20,.08,accent)
        self.box(0, 0, height+.19, .37,.38,.13,accent)
        return height

    def finish(self, name, out):
        # Keep doors, awnings and railings within the authoritative tile footprint.
        sx=max(abs(v[0]) for v in self.verts)
        sy=max(abs(v[1]) for v in self.verts)
        scale=min(1.0, (self.width-.015)/sx if sx else 1.0,
                  (self.depth-.015)/sy if sy else 1.0)
        if scale < 1.0:
            self.verts=[(x*scale,y*scale,z) for x,y,z in self.verts]
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        mesh=bpy.data.meshes.new(name+"Mesh")
        mesh.from_pydata(self.verts,[],self.faces)
        mesh.update()
        color=mesh.color_attributes.new(name="Color", type="FLOAT_COLOR", domain="CORNER")
        for polygon, shade in zip(mesh.polygons,self.face_colors):
            for loop_idx in polygon.loop_indices:
                color.data[loop_idx].color=shade
        obj=bpy.data.objects.new(name,mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active=obj
        obj.select_set(True)
        material=bpy.data.materials.get("LunexAtlas")
        if material is None:
            material=bpy.data.materials.new("LunexAtlas")
            material.use_nodes=True
            nodes=material.node_tree.nodes
            bsdf=nodes.get("Principled BSDF")
            bsdf.inputs["Roughness"].default_value=.92
            attr=nodes.new("ShaderNodeVertexColor")
            attr.layer_name="Color"
            material.node_tree.links.new(attr.outputs["Color"],bsdf.inputs["Base Color"])
        mesh.materials.append(material)
        # Exporter triangulates ngons; faces here are quads and triangles.
        triangles=sum(len(f)-2 for f in self.faces)
        assert triangles<=3000, (name,triangles)
        ys=[v[2] for v in self.verts]
        xs=[v[0] for v in self.verts]
        depths=[v[1] for v in self.verts]
        assert min(ys)>=-1e-6 and max(xs)-min(xs)<=self.width*2+1e-6
        assert max(depths)-min(depths)<=self.depth*2+1e-6
        filepath=out/(name+".glb")
        bpy.ops.export_scene.gltf(filepath=str(filepath), export_format="GLB", use_selection=True,
                                  export_yup=True, export_normals=True,
                                  export_texcoords=False, export_animations=False, export_extras=False)
        return {"file":filepath.name,"kind":self.kind,"w":self.width,"h":self.depth,
                "triangles":triangles,"height_m":round(max(ys),2),"license":"Original / CC0"}


def create(name, kind, w, d):
    b=Geometry()
    b.width,b.depth,b.kind=w,d,kind
    if kind=="house":
        if w==1 and d==1:
            palette={"house_panel":("beige","teal"),"house_brick":("brick2","sand"),
                     "house_modern":("light","blue")}
            wall,accent=palette[name.rsplit("_",1)[0]]
            b.facade(w,d,9,2,wall,accent)
        else:
            b.facade(w,d,5 if d==2 else 4,2,"sand","brick")
    elif kind=="shop":
        b.box(0,0,0,3.72,3.73,2.12,"light")
        b.box(0,0,2.12,3.86,3.84,.18,"roof")
        b.box(0,-1.87,.18,2.9,.055,1.3,"window")
        b.box(0,-1.98,1.75,3.5,.25,.26,"teal")
        b.box(-.52,-1.92,.02,.5,.06,1.25,"dark")
        for x in (-1.3,1.3):
            b.box(x,-1.93,.08,.12,.07,1.42,"white")
        b.box(0,0,2.30,.7,.45,.18,"yellow")
    elif kind=="warehouse":
        b.box(0,0,0,5.7,5.65,3.6,"sand")
        b.box(0,0,3.6,5.84,5.78,.22,"roof")
        for x in (-1.6,0,1.6):
            b.box(x,-2.85,.10,1.1,.065,2.3,"dark")
            b.box(x,-2.92,1.15,1.14,.035,.08,"light")
        b.box(0,2.83,2.7,3.1,.035,.45,"window")
        b.box(0,-2.92,3.25,4.7,.12,.18,"teal")
    elif kind=="school":
        b.box(0,0,0,5.64,3.68,4.13,"sand")
        b.box(0,0,4.13,5.78,3.82,.18,"roof")
        for floor in range(3):
            for x in (-2.1,-1.35,-.55,.5,1.3,2.08):
                b.box(x,-1.85,.6+floor*1.12,.45,.05,.65,"window")
            b.box(0,-1.88,1.4+floor*1.12,5.46,.04,.09,"teal")
        b.box(0,-1.89,0,.8,.07,1.1,"dark")
        b.box(0,-1.90,1.13,1.3,.19,.11,"brick")
    elif kind=="hospital":
        b.box(0,0,0,5.65,5.65,4.6,"light")
        b.box(0,0,4.6,5.82,5.82,.16,"roof")
        for floor in range(4):
            for x in (-2.15,-1.3,.85,1.7,2.25):
                b.box(x,-2.85,.55+floor*.99,.4,.04,.55,"window2")
        b.box(-.25,-2.89,0,.8,.06,1.25,"dark")
        b.box(0,-2.96,3.93,.98,.10,.16,"red")
        b.box(0,-2.97,3.93,.16,.11,.91,"red")
    elif kind in ("grain_field","elevator","mill","bread_plant","oil_well","gas_well","sand_pit","logging_camp","factory","farm","mine"):
        W,D=w*2,d*2
        b.box(0,0,0,W-.12,D-.12,.08,"grass" if kind in ("grain_field","farm","logging_camp") else "sand")
        if kind in ("grain_field","farm"):
            for row in range(7):
                y=-D*.40+row*D*.13
                b.box(0,y,.08,W*.85,.16,.15,"yellow" if row%2 else "green")
            b.box(-W*.34,D*.29,.08,.4,.4,.48,"wood")
        elif kind=="elevator":
            for x in (-1.45,0,1.45):
                b.box(x,.55,.08,1.13,1.13,5.8,"light")
                b.pyramid(x,.55,5.88,1.14,1.14,.6,"roof")
            b.box(0,-1.5,.08,4.3,1.8,2.5,"brick2")
            b.box(0,-2.43,.12,1.1,.07,1.8,"dark")
        elif kind in ("mill","bread_plant","factory"):
            b.box(0,0,.08,W*.84,D*.78,2.8,"brick2" if kind=="bread_plant" else "light")
            b.box(0,0,2.88,W*.89,D*.83,.23,"roof")
            for x in (-W*.25,0,W*.25):
                b.box(x,-D*.39,.55,.48,.07,.95,"window")
            b.box(W*.27,D*.15,3.11,.5,.5,1.5,"dark")
            b.box(-W*.30,-D*.40,.08,.95,.08,1.65,"teal")
        elif kind in ("oil_well","gas_well"):
            b.box(0,0,.08,W*.8,D*.72,.17,"dark")
            b.box(-.45,0,.25,.18,.24,3.3,"yellow" if kind=="oil_well" else "teal")
            b.box(.45,0,.25,.18,.24,3.3,"yellow" if kind=="oil_well" else "teal")
            b.box(0,0,3.5,2.2,.27,.22,"dark")
            b.box(.35,.25,.5,.55,.8,.55,"red" if kind=="oil_well" else "blue")
            b.box(1.2,.5,.25,.24,1.8,.25,"dark")
        elif kind=="sand_pit":
            for x,y in ((-1,-.7),(.9,-.5),(0,.8)):
                b.pyramid(x,y,.08,1.7,1.6,.75,"sand")
            b.box(-1.1,1.1,.08,.8,.6,.65,"yellow")
        elif kind=="logging_camp":
            b.box(-.6,0,.08,1.5,2.4,1.7,"wood")
            b.pyramid(-.6,0,1.78,1.7,2.7,.75,"roof")
            for y in (-1.25,-.7,-.15,.4,.95):
                b.box(1.35,y,.1,1.2,.24,.24,"wood")
            b.box(1.35,0,.35,1.3,2.6,.12,"wood")
        elif kind=="mine":
            b.box(0,.45,.08,W*.75,D*.48,1.0,"dark")
            b.box(0,-D*.30,.08,W*.55,D*.18,1.3,"brick")
            b.box(0,-D*.40,.08,1.2,.07,.9,"dark")
    elif kind in ("truck", "tractor", "construction_foundation", "construction_frame", "road_corner"):
        W,D=w*2,d*2
        if kind in ("truck", "tractor"):
            # Distinct silhouette: tall glazed cab, front bonnet, visible large tyres.
            # Box-only geometry keeps the original vertex-color mobile pipeline.
            cab_color="teal" if kind=="truck" else "yellow"
            bonnet_color="teal" if kind=="truck" else "yellow"
            b.box(0,0,.52,W*.63,D*.65,.32,"dark")
            b.box(0,-D*.20,.85,W*.53,D*.29,1.04,cab_color)
            b.box(0,-D*.355,1.04,W*.40,.045,.58,"window")
            for x in (-W*.267,W*.267):
                b.box(x,-D*.20,1.07,.05,D*.20,.53,"window2")
            b.box(0,-D*.20,1.89,W*.58,D*.32,.12,"roof")
            b.box(0,D*.16,.77,W*.57,D*.32,.49,bonnet_color)
            b.box(0,D*.33,.89,W*.48,.06,.27,"dark")
            if kind=="truck":
                b.box(0,D*.30,.72,W*.68,D*.28,1.15,"light")
                b.box(0,D*.30,1.87,W*.70,D*.30,.09,"roof")
                b.box(0,D*.46,.95,W*.50,.055,.16,"brick2")
            else:
                b.box(0,D*.20,1.27,W*.49,D*.29,.08,"roof")
                b.box(0,-D*.13,2.01,.10,.10,.33,"dark")
                b.box(0,D*.34,1.06,.12,.08,.09,"window2")
            for x in (-W*.32,W*.32):
                for y in (-D*.26,D*.27):
                    wheel_h=.96 if y<0 else .72
                    b.box(x,y,0,.37,.62,wheel_h,"dark")
                    b.box(x+(-.19 if x<0 else .19),y,wheel_h*.32,.045,.32,wheel_h*.35,"roof")
            for x in (-W*.23,W*.23):
                b.box(x,D*.35,.86,.12,.055,.13,"yellow")
        elif kind=="construction_foundation":
            b.box(0,0,0,W-.14,D-.14,.10,"sand")
            b.box(0,0,.10,W*.83,D*.80,.28,"light")
            for x in (-W*.33,W*.33):
                for y in (-D*.30,D*.30):
                    b.box(x,y,.38,.12,.12,.32,"dark")
        elif kind=="construction_frame":
            b.box(0,0,0,W-.14,D-.14,.10,"sand")
            for z in (.12,1.45,2.78):
                b.box(0,0,z,W*.82,D*.80,.12,"light")
            for x in (-W*.36,W*.36):
                for y in (-D*.34,D*.34):
                    b.box(x,y,.12,.15,.15,2.78,"brick2")
            b.box(0,-D*.39,1.54,W*.66,.07,.06,"yellow")
        else:
            b.box(0,0,0,1.94,1.94,.04,"pave")
            b.box(0,-.27,.04,1.47,1.40,.015,"asphalt")
            b.box(.27,0,.04,1.40,1.47,.015,"asphalt")
            b.box(-.15,-.55,.06,.04,.24,.009,"yellow")
            b.box(.55,.15,.06,.24,.04,.009,"yellow")
    elif kind=="catalog_generic":
        W,D=w*2,d*2
        b.box(0,0,0,W-.12,D-.12,.07,"pave")
        b.box(0,0,.07,W*.78,D*.74,1.8,"light")
        b.box(0,0,1.87,W*.83,D*.79,.17,"roof")
        b.box(0,-D*.375,.07,.7,.07,1.3,"dark")
        for x in (-W*.23,0,W*.23):
            b.box(x,-D*.38,.9,.36,.045,.43,"window")
        b.box(0,0,2.04,.6,.6,.15,"teal")
    elif kind=="park":
        b.box(0,0,0,3.92,3.92,.07,"grass")
        b.box(0,0,.07,3.82,.38,.03,"pave")
        b.box(0,0,.07,.36,3.82,.03,"pave")
        for x,y,hh in ((-1.3,-1.3,1.15),(1.32,-1.25,.99),(-1.23,1.27,.90),(1.27,1.27,1.19)):
            b.box(x,y,.1,.20,.20,.46,"wood")
            b.pyramid(x,y,.52,.87,.81,hh,"canopy" if x<0 else "leaves2")
        b.box(.6,.6,.08,.7,.19,.26,"wood")
    elif kind in ("road_straight","road_cross"):
        b.box(0,0,0,1.94,1.94,.04,"pave")
        b.box(0,0,.04,1.47,1.94,.015,"asphalt")
        if kind=="road_cross":
            b.box(0,0,.04,1.94,1.47,.015,"asphalt")
            for x in (-.7,.7):
                for y in (-.7,.7):
                    b.box(x,y,.058,.10,.12,.008,"white")
        else:
            for y in (-.64,0,.64):
                b.box(0,y,.06,.035,.25,.009,"yellow")
    elif kind=="bridge":
        b.box(0,0,0,1.6,1.8,.32,"dark")
        b.box(0,0,.32,1.85,1.99,.12,"asphalt")
        for x in (-.85,.85):
            b.box(x,0,.43,.09,1.9,.22,"light")
            for y in (-.66,.66):
                b.box(x,y,.61,.08,.09,.45,"light")
            b.box(x,0,1.03,.09,1.9,.07,"teal")
        b.box(0,0,.45,.04,.34,.01,"yellow")
    return b


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    output=Path(args.output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    specs=[
        ("house_panel_1x1","house",1,1), ("house_brick_1x1","house",1,1),
        ("house_modern_1x1","house",1,1), ("house_1x2","house",1,2),
        ("house_1x3","house",1,3), ("shop_2x2","shop",2,2),
        ("warehouse_3x3","warehouse",3,3), ("school_3x2","school",3,2),
        ("hospital_3x3","hospital",3,3), ("park_2x2","park",2,2),
        ("road_straight_1x1","road_straight",1,1),
        ("road_cross_1x1","road_cross",1,1),
        ("bridge_1x1","bridge",1,1),
        ("road_corner_1x1","road_corner",1,1),
        ("truck_2x3","truck",2,3),
        ("tractor_2x2","tractor",2,2),
        ("construction_foundation_3x2","construction_foundation",3,2),
        ("construction_frame_3x2","construction_frame",3,2),
        ("grain_field_3x2","grain_field",3,2),
        ("elevator_3x3","elevator",3,3),
        ("mill_3x2","mill",3,2),
        ("bread_plant_3x2","bread_plant",3,2),
        ("oil_well_2x2","oil_well",2,2),
        ("gas_well_2x2","gas_well",2,2),
        ("sand_pit_2x2","sand_pit",2,2),
        ("logging_camp_2x3","logging_camp",2,3),
        ("factory_3x2","factory",3,2),
        ("farm_2x2","farm",2,2),
        ("mine_2x3","mine",2,3),
        ("factory","factory",3,2), ("farm","farm",2,2),
        ("mine","mine",2,3), ("oil_well","oil_well",2,2)]
    # Missing city-catalog IDs are generated as generic distinct placeholder buildings.
    # They are real GLBs with valid footprints, not claimed bespoke architectural art.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
    import city_catalog
    present_ids={name for name, _, _, _ in specs}
    for oid, entry in sorted(city_catalog.CATALOG.items()):
        if oid in present_ids or any(name.startswith(oid+"_") for name in present_ids):
            continue
        specs.append((oid,"catalog_generic",int(entry["w"]),int(entry["h"])))
    manifest=[]
    for name,kind,w,d in specs:
        mesh=create(name,kind,w,d)
        row=mesh.finish(name,output)
        manifest.append(row)
        print(name, row["triangles"], "triangles", flush=True)
    # This metadata is used only by documentation script, not the Android client.
    (output.parent.parent.parent/"tools/models_build.json").write_text(json.dumps(manifest,indent=2))
    assert len(manifest)>=28


if __name__=="__main__":
    main()