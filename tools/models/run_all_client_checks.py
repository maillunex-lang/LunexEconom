"""Execute every client-check.yml smoke and layout locally, with bounded timeouts."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
GODOT="/opt/game-tools/godot/4.7.2-stable/Godot_v4.7.2-stable_linux.x86_64"
text=(ROOT/".github/workflows/client-check.yml").read_text()
smokes=re.search(r'for test in ([^;]+); do',text).group(1).split()
layouts=re.findall(r'-s tests/([a-z0-9_]+_layout_smoke).gd',text)
layouts=list(dict.fromkeys(layouts))
# ui1 uses five sizes, all others four; models layout uses four
extra_layout=["scale_smoke"]
def execute(args,env=None,seconds=80):
    cmd=args
    try:
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=seconds,env=env)
        output=p.stdout+"\n"+p.stderr
        problems=[line for line in output.splitlines() if
                  "SCRIPT ERROR" in line or "Assertion failed" in line or "Parse Error" in line]
        return p.returncode,problems[-8:],output[-450:]
    except subprocess.TimeoutExpired:
        return 124,["TIMEOUT"],""

fail=[]
for script in smokes:
    rc,errors,tail=execute([GODOT,"--headless","--path","client","-s",f"tests/{script}.gd"],seconds=65)
    print("SMOKE",script,rc,errors,flush=True)
    if rc or errors:
        fail.append(("smoke",script,rc,errors,tail))
for script in extra_layout+layouts:
    limit=5 if script=="ui1_layout_smoke" else 4
    for i in range(limit):
        env=os.environ.copy()
        env.update({"LUNEX_TEST_SIZE_INDEX":str(i),"LUNEX_SCREENSHOT_DIR":"/tmp/lunex-models-shots"})
        rc,errors,tail=execute(["xvfb-run","-a",GODOT,"--path","client",
            "--rendering-driver","opengl3","-s",f"tests/{script}.gd"],env,seconds=70)
        print("LAYOUT",script,i,rc,errors,flush=True)
        if rc or errors:
            fail.append(("layout",script,i,rc,errors,tail))
print("TOTAL",len(smokes),"smokes",len(layouts)+len(extra_layout),"layout scripts",
      "FAILURES",len(fail),flush=True)
for item in fail:
    print("FAIL",item,flush=True)
sys.exit(1 if fail else 0)
