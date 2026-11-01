"""Fresh-source File Mask live assertions; no dock creation, user package mutation or eval input."""
from pathlib import Path
import hashlib,json,shutil,struct,zlib
from unittest import mock
from substance_physics_scatter.fileio import io_path,logical_path

def image(values,width,height,bits=8):
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    rows=[]
    for y in range(height):
        row=values[y*width:(y+1)*width]
        rows.append(b"\0"+(bytes(row) if bits==8 else b"".join(struct.pack(">H",v*257) for v in row)))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,bits,0,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(rows)))+chunk(b"IEND",b"")

def run(ns):
    root,work=ns["ROOT"],ns["WORK"];core,compat,designer=ns["core"],ns["compat"],ns["designer"]
    mgr,QtCore=ns["mgr"],ns["QtCore"];generate,pixels=ns["generate"],ns["pixels"]
    test_ui,isolated_panel=ns["test_ui"],ns["isolated_panel"]
    evidence=ns["evidence"];audit={};evidence["file_mask"]=audit
    home=work/"file_mask";io_path(home).mkdir();assets=home/"original_assets";io_path(assets).mkdir()
    rows=[]
    for row in ns["asset_rows"]:
        target=assets/row["source_name"] if "source_name" in row else assets/Path(row["path"]).name
        shutil.copyfile(io_path(row["path"]),io_path(target));rows.append(dict(row,path=str(target)))
    paths={}
    for name,values,w,h,bits in (("white",[255],1,1,8),("black",[0],1,1,8),("partial8",[255]+[0]*8,3,3,8),("partial16",[255]+[0]*8,3,3,16),("axes",[255,0,0,0],2,2,8)):
        path=assets/(name+".png");io_path(path).write_bytes(image(values,w,h,bits));paths[name]=path
    def config(name):return None if name=="none" else dict(enabled=True,path=str(paths[name]),source_name=paths[name].name)
    package=ns["new_owned_package"]();parent=ns["SDSBSCompGraph"].sNew(package);parent.setIdentifier("FileMaskAcceptance")
    package_path=home/"FileMask.sbs";mgr.savePackageAs(package,str(package_path))
    ns["adopt_owned_package"](package,package_path)
    simulation=dict(count=20,width=2.3,depth=2.3,seed=123456789,seconds=.1,edges="walls")
    bake=dict(resolution=256,height_min=0,height_max=8,normal="OpenGL",samples=2)
    completed={};graphs={};expected={};topology={}
    for name in ("none","white","black","partial8","partial16","axes"):
        graph,instance=designer.create(parent);sink=parent.newNode("sbs::compositing::output")
        sink.setAnnotationPropertyValueFromId("identifier",ns["SDValueString"].sNew("mask_"+name))
        instance.newPropertyConnectionFromId("height",sink,"inputNodeOutput")
        jobs=core.Jobs(designer.result_directory(graph));candidate=generate(jobs,simulation,bake,rows=rows,graph=graph,mask=config(name))
        completed[name]=candidate;graphs[name]=graph;expected[name]=pixels(graph,"mask_"+name,candidate)
        topology[name]=ns["edge"](parent,instance,sink,graph)
        r=candidate["result"];assert r["physics_input_format_version"]==2 and r["physics_contract_version"]==2 and r["bake_contract_version"]==2
        audit[name]={"graph":graph.getIdentifier(),"job_id":candidate["job_id"],"requested":r["requested_count"],"spawned":r["spawned_count"],"status":r["spawn_status"],"reason":r["spawn_stop_reason"],"all_channels_exact":True}
        if name=="black":
            assert r["poses"]==[] and r["initial_positions"]==[] and r["execution"]==dict(physics_executed=False,body_count=0,steps=0)
            assert r["settling_status"]=="not_run" and r["spawn_stop_reason"]=="all_black"
            for channel,value in (("height",b"\0\0"),("normal",b"\x80\x80\xff"),("coverage",b"\0")):
                actual=ns["signature"](candidate["files"][channel]);assert actual["decoded_sha256"]==hashlib.sha256(value*(256*256)).hexdigest()
        if name=="axes":
            assert r["initial_positions"] and all(p[0]<0 and p[1]>0 for p in r["initial_positions"]),"Mask row0 is +Y; col0 is -X"
    for a,b in (("none","white"),("partial8","partial16")):
        assert completed[a]["result"]["poses"]==completed[b]["result"]["poses"]
        assert completed[a]["result"]["initial_positions"]==completed[b]["result"]["initial_positions"]
        assert expected[a]==expected[b]
    assert completed["none"]["simulation_key"]!=completed["white"]["simulation_key"]
    assert completed["partial8"]["result"]["spawn_status"]=="partial"
    # Save/reopen the genuine empty graph before rebaking; no manual relink/update occurs.
    states={name:designer.settings(g) for name,g in graphs.items()};ids={name:g.getIdentifier() for name,g in graphs.items()}
    mgr.savePackage(package);mgr.unloadUserPackage(package);package=mgr.loadUserPackage(str(package_path))
    ns["adopt_owned_package"](package,package_path)
    resources={r.getIdentifier():r for r in package.getChildrenResources(True)};parent=resources["FileMaskAcceptance"]
    for name,identifier in ids.items():
        graph=resources[identifier];graphs[name]=graph
        assert designer.settings(graph)==states[name] and pixels(graph,"mask_reopened_"+name)==expected[name]
        edge=topology[name];assert ns["edge"](parent,parent.getNodeFromId(edge["source"]),parent.getNodeFromId(edge["destination"]),graph)==edge
    black=graphs["black"];jobs=core.Jobs(designer.result_directory(black));old=jobs.current
    origin_path=Path(old["result_path"]).parent/old["result"]["origin"]["record_path"];origin_raw_sha=core.digest(origin_path)
    for index in range(2):
        current=generate(jobs,old["request"]["simulation"],old["request"]["bake"],True,old["request"]["assets"],black,config("black"))
        assert current["result"]["pose_origin"]==old["result"]["pose_origin"]
        for field in compat.SPAWN_FIELDS:assert current["result"][field]==old["result"][field]
        assert core.digest(origin_path)==origin_raw_sha
        assert pixels(black,"mask_empty_rebake_"+str(index))==expected["black"]
    audit["empty_save_reopen_two_rebakes"]={"all_pixels_exact":True,"origin_and_spawn_exact":True,"immutable_origin_sha256":origin_raw_sha}
    # Pre-worker failures must preserve graph metadata, current pointer and all displayed pixels.
    graph=graphs["partial8"];jobs=core.Jobs(designer.result_directory(graph));good=jobs.current
    state=designer.settings(graph);pointer=core.digest(jobs.directory/"current.json");mask=good["request"]["scatter_mask"]
    failures=[]
    def reject(value,rebake):
        with isolated_panel(lambda:test_ui.Panel()) as panel:
            panel.graph=graph;panel.jobs=jobs;panel.set_assets(good["request"]["assets"]);panel.set_mask(value)
            for field in ("count","width","depth","seconds","seed"):getattr(panel,field).setValue(good["request"]["simulation"][field])
            panel.edges.setCurrentText("walls")
            panel.run(rebake);assert panel.process is None,panel.status.text()
            assert core.digest(jobs.directory/"current.json")==pointer and designer.settings(graph)==state
            assert pixels(graph,"mask_rejected_"+str(len(failures)))==expected["partial8"]
            failures.append(panel.status.text())
    reject(None,True);reject(config("white"),True)
    invalid=assets/"invalid.png";io_path(invalid).write_bytes(b"not PNG");reject(dict(enabled=True,path=str(invalid)),False)
    owned=Path(mask["path"]);original=io_path(owned).read_bytes()
    io_path(owned).unlink()
    # A missing owned snapshot with an absent source must fail, never silently disable the mask.
    missing=dict(mask,path=str(assets/"absent_source.png"),enabled=True);reject(missing,True)
    io_path(owned).write_bytes(b"damaged");reject(missing,True);io_path(owned).write_bytes(original)
    audit["failure_lastgood"]={"rejected":failures,"starts":0,"metadata_pointer_pixels_unchanged":True}
    with isolated_panel(lambda:test_ui.Panel()) as panel:
        panel.set_mask(config("black"));before=panel.mask_config()
        with mock.patch.object(test_ui.QtWidgets.QFileDialog,"getOpenFileName",return_value=("","")):panel.browse_mask()
        assert panel.mask_config()==before
    # Own active Mask job cancellation/crash; the black last-good remains a successful empty result.
    jobs=core.Jobs(designer.result_directory(black));state=designer.settings(black);pointer=core.digest(jobs.directory/"current.json")
    with isolated_panel(lambda:test_ui.Panel()) as panel:
        panel.graph=black;panel.jobs=jobs;panel.set_assets([dict(r,scale=.08) for r in rows]);panel.set_mask(config("white"));panel.count.setValue(5000);panel.seconds.setValue(120)
        for action in ("cancel","crash"):
            loop=QtCore.QEventLoop();panel.run(False);assert panel.process is not None,panel.status.text()
            process=panel.process;process.finished.connect(loop.quit);QtCore.QTimer.singleShot(5,panel.stop if action=="cancel" else process.kill)
            timer=QtCore.QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(15000);loop.exec();timer.stop()
            assert panel.process is None,"Mask cancel/crash timed out; preserve active child"
            assert core.digest(jobs.directory/"current.json")==pointer and designer.settings(black)==state
            assert pixels(black,"mask_"+action)==expected["black"]
    audit["cancel_crash_empty_lastgood_preserved"]=True
    mgr.savePackage(package)
    moved,migration=ns["prepare_moved_fixture"](package_path,assets,home)
    mgr.unloadUserPackage(package);package=mgr.loadUserPackage(str(moved))
    ns["adopt_owned_package"](package,moved)
    assert logical_path(package.getFilePath())==logical_path(moved)
    resources={r.getIdentifier():r for r in package.getChildrenResources(True)}
    for name,identifier in ids.items():
        graph=resources[identifier];assert pixels(graph,"mask_moved_display_"+name)==expected[name]
        jobs=core.Jobs(designer.result_directory(graph));current=jobs.current
        with isolated_panel(lambda:test_ui.Panel()) as panel:
            panel.nodes.setCurrentText(identifier);panel._select();value=panel.mask_config()
            assert panel.graph.getIdentifier()==identifier
            if name!="none":assert value["enabled"] and value["source_name"]==paths[name].name
        if name!="none":
            descriptor=current["request"]["scatter_mask"];assert logical_path(descriptor["path"]).is_relative_to(logical_path(moved.parent)) and io_path(descriptor["path"]).is_file()
        # Old absolute source in metadata is unavailable; owned hash cache alone recovers the mask.
        candidate=generate(jobs,current["request"]["simulation"],current["request"]["bake"],True,current["request"]["assets"],graph,value)
        assert candidate["result"]["pose_origin"]==current["result"]["pose_origin"]
        assert pixels(graph,"mask_moved_rebake_"+name)==expected[name]
    audit["migration"]=migration;audit["cache_restored_after_source_absent"]=True
    # Actual 0.2.1 format1 fixtures remain format1 and never acquire fabricated spawn metadata.
    archive=home/"accepted021";shutil.copytree(io_path(root/"accepted-stage2A1/fixtures"),io_path(archive))
    packages=list(io_path(archive).glob("*.sbs"));assert len(packages)==1
    old_package=mgr.loadUserPackage(str(logical_path(packages[0])));ns["adopt_owned_package"](old_package,logical_path(packages[0]));checks=[]
    for graph in old_package.getChildrenResources(True):
        if not isinstance(graph,ns["SDSBSCompGraph"]) or not designer.settings(graph):continue
        jobs=core.Jobs(designer.result_directory(graph));old=jobs.current
        assert old["request"]["physics_input_format_version"]==1
        before=pixels(graph,"mask_format1_before_"+str(len(checks)),old)
        candidate=generate(jobs,old["request"]["simulation"],old["request"]["bake"],True,old["request"]["assets"],graph,None)
        assert candidate["request"]["physics_input_format_version"]==1 and "spawned_count" not in candidate["result"]
        assert candidate["result"]["pose_origin"]==old["result"]["pose_origin"] and candidate["result"]["poses"]==old["result"]["poses"]
        assert pixels(graph,"mask_format1_after_"+str(len(checks)))==before
        checks.append(candidate["job_id"])
    assert checks;audit["actual021_format1_rebakes"]=checks
    ns["report"]()
