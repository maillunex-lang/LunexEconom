#!/usr/bin/env python3
"""Validate the actual bytes of all catalog models and SHA manifest."""
import hashlib
import json
import math
import struct
from pathlib import Path
try:
    from tools.models.generate_models import ROOT, DEST, STAGES, COLORS, catalog
except ModuleNotFoundError:
    from generate_models import ROOT, DEST, STAGES, COLORS, catalog

BUDGETS = ROOT / "tools/sim/data/map3d_proposed/budgets.json"

def validate_one(path, e, record, render):
    data=path.read_bytes()
    assert len(data)<=render["max_building_glb_bytes"],path
    assert len(data)>=28, path
    magic,version,total=struct.unpack_from("<4sII",data,0)
    assert (magic,version,total)==(b"glTF",2,len(data)),path
    json_size,marker=struct.unpack_from("<I4s",data,12)
    assert marker==b"JSON" and json_size%4==0,path
    gltf=json.loads(data[20:20+json_size])
    offset=20+json_size
    bin_size,marker=struct.unpack_from("<I4s",data,offset)
    assert marker==b"BIN\0",path
    binary=data[offset+8:]
    assert bin_size==len(binary) and offset+8+bin_size==len(data),path
    assert gltf["asset"]["version"]=="2.0"
    assert gltf["scene"]==0 and gltf["scenes"][0]["nodes"]==[0]
    assert gltf["buffers"]==[{"byteLength":len(binary)}]
    assert gltf["nodes"][0]["name"]=="Root"
    assert gltf["nodes"][0]["children"]==[1,2,3,4,5]
    assert [n["name"] for n in gltf["nodes"][1:]]==list(STAGES)
    assert len(gltf["materials"])<=4
    assert len({m["name"] for m in gltf["materials"]})==len(gltf["materials"])
    assert all(m["name"] in {"lunex_"+k for k in COLORS} and
               m["doubleSided"] is False and
               len(m["pbrMetallicRoughness"]["baseColorFactor"])==4
               for m in gltf["materials"])
    views=gltf["bufferViews"]
    access=gltf["accessors"]
    for v in views:
        assert v["buffer"]==0
        assert v["byteOffset"]%4==0
        assert 0<v["byteLength"]<=len(binary)-v["byteOffset"]
        assert v["target"] in (34962,34963)
    for a in access:
        assert 0<=a["bufferView"]<len(views)
        assert a["count"]>0 and a["type"] in ("SCALAR","VEC3")
        assert a["componentType"] in (5123,5126)
        elem_size=2 if a["componentType"]==5123 else 4
        dims=3 if a["type"]=="VEC3" else 1
        assert a["count"]*elem_size*dims<=views[a["bufferView"]]["byteLength"]
    triangles=0
    bounds=[[math.inf]*3,[-math.inf]*3]
    for stage,n in enumerate(gltf["nodes"][1:]):
        mesh=gltf["meshes"][n["mesh"]]
        assert mesh["name"]==STAGES[stage]
        for p in mesh["primitives"]:
            assert p["mode"]==4 and 0<=p["material"]<len(gltf["materials"])
            pos=access[p["attributes"]["POSITION"]]
            normal=access[p["attributes"]["NORMAL"]]
            indices=access[p["indices"]]
            assert pos["type"]==normal["type"]=="VEC3"
            assert pos["componentType"]==normal["componentType"]==5126
            assert indices["type"]=="SCALAR" and indices["componentType"]==5123
            assert indices["count"]%3==0
            assert pos["count"]==normal["count"]
            pview=views[pos["bufferView"]]
            nview=views[normal["bufferView"]]
            iview=views[indices["bufferView"]]
            coords=struct.unpack_from("<%sf"%(pos["count"]*3),
                                       binary,pview["byteOffset"])
            norms=struct.unpack_from("<%sf"%(normal["count"]*3),
                                      binary,nview["byteOffset"])
            idx=struct.unpack_from("<%sH"%indices["count"],
                                    binary,iview["byteOffset"])
            assert all(i<pos["count"] for i in idx)
            for i in range(3):
                assert abs(min(coords[i::3])-pos["min"][i])<1e-4
                assert abs(max(coords[i::3])-pos["max"][i])<1e-4
            for k in range(0,len(idx),3):
                a,b,c=(tuple(coords[t*3:t*3+3]) for t in idx[k:k+3])
                ab=[b[i]-a[i] for i in range(3)]
                ac=[c[i]-a[i] for i in range(3)]
                cross=(ab[1]*ac[2]-ab[2]*ac[1],
                       ab[2]*ac[0]-ab[0]*ac[2],
                       ab[0]*ac[1]-ab[1]*ac[0])
                mag=math.sqrt(sum(v*v for v in cross))
                assert mag>1e-6,(path,"degenerate")
                norm=tuple(norms[idx[k]*3:idx[k]*3+3])
                assert sum(cross[i]*norm[i] for i in range(3))>0,(path,"flipped normal")
            for i in range(3):
                bounds[0][i]=min(bounds[0][i],min(coords[i::3]))
                bounds[1][i]=max(bounds[1][i],max(coords[i::3]))
            triangles+=indices["count"]//3
    assert 0<triangles<=render["max_building_triangles_lod0"],(path,triangles)
    target=[-e["width"]*10,0,-e["height"]*10]
    high=[e["width"]*10,30,e["height"]*10]
    for axis in (0,2):
        assert abs(bounds[0][axis]-target[axis])<=.01,(path,bounds)
        assert abs(bounds[1][axis]-high[axis])<=.01,(path,bounds)
    assert bounds[0][1]>=-.001 and bounds[1][1]<=30.001,(path,bounds)
    assert triangles==record["triangles"]
    assert len(data)==record["bytes"]
    assert hashlib.sha256(data).hexdigest()==record["sha256"]
    assert record["width"]==e["width"] and record["height"]==e["height"]
    return triangles,len(data)

def validate():
    manifest=json.loads((DEST/"manifest.json").read_text(encoding="utf-8"))
    entries=catalog()
    expected={f'{e["family"]}/{e["id"]}.glb':e for e in entries}
    assert len(expected)==64 and len(manifest["models"])==64
    assert set(manifest["models"])==set(expected)
    assert {p.relative_to(DEST).as_posix() for p in DEST.rglob("*.glb")}==set(expected)
    render=json.loads(BUDGETS.read_text(encoding="utf-8"))["render"]
    total=0
    result={}
    for rel,e in expected.items():
        tris,size=validate_one(DEST/rel,e,manifest["models"][rel],render)
        result[rel]=(tris,size)
        total+=size
    assert total<=render["max_model_pack_bytes"]
    print(f"VALID: {len(result)} models, {total} bytes, max triangles {max(t for t,_ in result.values())}")
    return result

if __name__=="__main__":
    validate()
