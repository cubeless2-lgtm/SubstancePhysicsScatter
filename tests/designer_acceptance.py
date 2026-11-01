"""Actual Designer lane, invoked only by the explicit local test bridge."""
from pathlib import Path
import hashlib,importlib,importlib.util,json,marshal,platform,shutil,subprocess,sys,traceback,types,uuid
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"));sys.path.insert(0,str(ROOT/"tests"))
STAGE2=globals().get("STAGE2",False)
POSE_COMPAT=globals().get("POSE_COMPAT",False)
FILE_MASK=globals().get("FILE_MASK",False)
WORK=ROOT/("output/designer_file_mask" if FILE_MASK else "output/designer_pose_compat" if POSE_COMPAT else "output/designer_stage2" if STAGE2 else "output/designer_runs")/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=ROOT/"output/designer_smoke.json"
def fingerprint():
    authored={}
    for folder in ("plugin","worker","tests","schemas","scripts","docs","third_party"):
        for path in (ROOT/folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                authored[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    worker=ROOT/"build/Release/scatter_worker.exe"
    authored["build/Release/scatter_worker.exe"]=hashlib.sha256(worker.read_bytes()).hexdigest()
    for archive in ("accepted-stage2A/fixtures","accepted-stage2A1/fixtures"):
        for path in (ROOT/archive).rglob("*"):
            if path.is_file():authored[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("accepted-stage1/scatter_worker.exe","accepted-stage1/candidate.json","accepted-stage2A1/scatter_worker.exe","accepted-stage2A1/candidate-pose-compat.json","accepted-stage2A1/archive-evidence.json","CMakeLists.txt","README.md","build/downloads/zlib-1.3.2.tar.gz","build/_deps/lodepng-src/lodepng.h","build/_deps/lodepng-src/lodepng.cpp"):
        authored[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    return authored
before_fingerprint=fingerprint()
evidence={"status":"running","stage":"File Mask 0.3.0" if FILE_MASK else "2A.1" if POSE_COMPAT else "2A" if STAGE2 else "1","run_directory":str(WORK),"test_job_id":WORK.name,"environment":{"python":sys.version,"platform":platform.platform()},"input_fingerprint_before":before_fingerprint}

def fresh_helper(stem):
    """Inline in the freshly run lane: never import a cached helper or consume a pyc."""
    assert stem in ("png_pixels","moved_fixture","designer_file_mask_lane")
    lane_path=Path(__file__);lane_bytes=lane_path.read_bytes()
    lane_sha=hashlib.sha256(lane_bytes).hexdigest()
    assert lane_sha==before_fingerprint["tests/designer_acceptance.py"]
    lane_code=compile(lane_bytes,str(lane_path),"exec")
    expected_loader=next(c for c in lane_code.co_consts if isinstance(c,types.CodeType) and c.co_name=="fresh_helper")
    assert fresh_helper.__code__==expected_loader,"Helper loader does not match current lane source"
    evidence["helper_loader_freshness"]={"source_sha256":lane_sha,"bytecode_sha256":hashlib.sha256(marshal.dumps(fresh_helper.__code__)).hexdigest(),"matches_source_compile":True,"inline":True}
    path=ROOT/"tests"/(stem+".py");source=path.read_bytes();source_sha=hashlib.sha256(source).hexdigest()
    assert source_sha==before_fingerprint["tests/"+stem+".py"],"Helper source changed after fingerprint"
    compiled=compile(source,str(path),"exec")
    name="_scatter_acceptance_"+stem+"_"+WORK.name+"_"+uuid.uuid4().hex
    module=types.ModuleType(name);module.__file__=str(path);module.__package__="";sys.modules[name]=module
    exec(compiled,module.__dict__)
    functions={}
    for expected in compiled.co_consts:
        if isinstance(expected,types.CodeType) and expected.co_name in module.__dict__ and isinstance(module.__dict__[expected.co_name],types.FunctionType):
            actual=module.__dict__[expected.co_name]
            assert actual.__code__==expected and actual.__globals__ is module.__dict__,"Helper function differs from current source"
            functions[expected.co_name]={"matches_source_compile":True,"bytecode_sha256":hashlib.sha256(marshal.dumps(actual.__code__)).hexdigest()}
    assert functions,"Helper has no verified functions"
    evidence.setdefault("helper_freshness",{})[stem]={"module":name,"source_file":str(path),"source_sha256":source_sha,"compile_exec_without_pyc":True,"functions":functions}
    return module
def report():
    current=fingerprint()
    evidence["input_fingerprint_after"]=current
    evidence["inputs_unchanged"]=current==before_fingerprint
    if evidence["status"]=="pass" and not evidence["inputs_unchanged"]:
        evidence.update(status="failed",reason="Inputs changed during acceptance run")
    data=json.dumps(evidence,indent=2);REPORT.write_text(data,encoding="utf-8");(WORK/"report.json").write_text(data,encoding="utf-8")
report()
try:
    import sd
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
    from sd.api.sdvaluestring import SDValueString
    from sd.api.sdproperty import SDPropertyCategory
    from sd.api.sdproperty import SDPropertyInheritanceMethod
    from sd.api.sdvalueint2 import SDValueInt2
    from sd.api.sdvalueenum import SDValueEnum
    from sd.api.sdbasetypes import int2
    from sd.api.sdapiobject import SDApiError
    from PySide6 import QtCore, __version__ as pyside_version
    import substance_physics_scatter
    from substance_physics_scatter import errors,fileio,maskio,compat,core,connections,designer
    for module in (errors,fileio,maskio,compat,core,connections,designer):importlib.reload(module)
    from substance_physics_scatter import ui
    existing_user_panel=substance_physics_scatter._panel
    # Load a separate module for the test widget; existing user widgets keep their class/module.
    ui_path=ROOT/"plugin/substance_physics_scatter/ui.py"
    test_module_name="substance_physics_scatter._acceptance_ui_"+WORK.name
    spec=importlib.util.spec_from_file_location(test_module_name,str(ui_path))
    test_ui=importlib.util.module_from_spec(spec);sys.modules[test_module_name]=test_ui;spec.loader.exec_module(test_ui)
    compiled=compile(ui_path.read_text(encoding="utf-8"),str(ui_path),"exec")
    panel_code=next(c for c in compiled.co_consts if isinstance(c,types.CodeType) and c.co_name=="Panel")
    expected_run=next(c for c in panel_code.co_consts if isinstance(c,types.CodeType) and c.co_name=="run")
    actual_code=marshal.dumps(test_ui.Panel.run.__code__);expected_code=marshal.dumps(expected_run)
    # CodeType equality compares code/constants/names/flags without marshal's string-intern encoding.
    assert test_ui.Panel.run.__code__==expected_run,"Test Panel code does not match current candidate"
    assert Path(test_ui.__file__).resolve()==ui_path.resolve()
    evidence["test_panel_freshness"]={"module":test_module_name,"ui_source_sha256":hashlib.sha256(ui_path.read_bytes()).hexdigest(),"run_bytecode_sha256":hashlib.sha256(actual_code).hexdigest(),"matches_candidate":True}
    from substance_physics_scatter.testing import isolated_panel
    signature=fresh_helper("png_pixels").signature
    HOST_ERRORS=errors.HOST_ERRORS
    app=sd.getContext().getSDApplication();mgr=app.getPackageMgr()
    evidence["environment"].update(designer=app.getVersion(),qt=QtCore.qVersion(),pyside=pyside_version)
    baseline_packages=[{"uid":p.getUID(),"path":p.getFilePath()} for p in mgr.getUserPackages()]
    evidence["baseline_packages"]=baseline_packages
    def new_owned_package():
        value=mgr.newUserPackage()
        assert value.getUID() and value.getUID() not in {p["uid"] for p in baseline_packages},"New package reused baseline user UID"
        assert not value.getFilePath(),"New package unexpectedly refers to a saved user package"
        evidence.setdefault("owned_package_creation",[]).append({"uid":value.getUID(),"initial_path":value.getFilePath()})
        return value
    def adopt_owned_package(value,path):
        expected=fileio.logical_path(path)
        assert expected.is_relative_to(fileio.logical_path(WORK)),"Package ownership escaped unique WORK"
        assert value.getFilePath() and fileio.logical_path(value.getFilePath())==expected,"SDK returned a different package path"
        assert not any(p["path"] and fileio.logical_path(p["path"])==expected for p in baseline_packages),"Package path existed in user baseline"
        evidence.setdefault("owned_package_paths",[]).append({"uid":value.getUID(),"path":str(expected)})
        return value
    package=new_owned_package();parent=SDSBSCompGraph.sNew(package);parent.setIdentifier("PhysicsScatterDemo")
    for name,value in (("$outputsize",SDValueInt2.sNew(int2(11,11))),("$format",SDValueEnum.sFromValueId("sbs::compositing::format","16_bits_per_channel"))):
        prop=parent.getPropertyFromId(name,SDPropertyCategory.Input)
        parent.setPropertyInheritanceMethod(prop,SDPropertyInheritanceMethod.Absolute);parent.setPropertyValue(prop,value)
    package_path=WORK/"PhysicsScatterDemo.sbs";mgr.savePackageAs(package,str(package_path))
    adopt_owned_package(package,package_path)
    graphs=[];completed=[]

    def pixels(graph,label,expected=None):
        directory=WORK/label;designer.export_outputs(graph,directory)
        values={channel:signature(directory/(channel+".png")) for channel in designer.CHANNELS}
        if expected:
            for channel in designer.CHANNELS:assert values[channel]==signature(expected["files"][channel]),(label,channel,values[channel])
        return values

    def edge(graph,instance,sink,referenced_graph):
        prop=sink.getPropertyFromId("inputNodeOutput",SDPropertyCategory.Input)
        edges=connections.incoming_sources(graph,sink.getIdentifier(),"inputNodeOutput");assert len(edges)==1
        source,source_prop=edges[0]
        assert source.getIdentifier()==instance.getIdentifier()
        assert source_prop.getId()=="height"
        assert source.getReferencedResource().getUrl()==referenced_graph.getUrl()
        return {"source":source.getIdentifier(),"source_property":source_prop.getId(),"destination":sink.getIdentifier(),"destination_property":prop.getId(),"referenced_graph":referenced_graph.getIdentifier()}

    asset_rows=[{"asset_id":"00000000000040008000000000000001","path":str(ROOT/"tests/fixtures/cube.obj"),"format":"obj","weight":1,"scale":.25},
                {"asset_id":"00000000000040008000000000000002","path":str(ROOT/"tests/fixtures/pyramid.obj"),"format":"obj","weight":1,"scale":.25}]
    if STAGE2:
        original_assets=WORK/"original_assets";original_assets.mkdir()
        for row in asset_rows:
            original=Path(row["path"]);owned=original_assets/original.name;shutil.copyfile(original,owned);row["path"]=str(owned)
    def generate(jobs,simulation,bake,rebake=False,rows=None,graph=None,mask=None):
        simulation=dict(simulation)
        if STAGE2:simulation.pop("scale",None)
        if STAGE2 and graph is not None:
            # Exercise the real multi-asset table + QProcess + transactional successful promotion.
            panel=test_ui.Panel();panel.graph=graph;panel.jobs=jobs;panel.set_assets(rows or asset_rows)
            panel.set_mask(mask)
            try:
                for name in ("count","width","depth","seed","seconds"):getattr(panel,name).setValue(simulation[name])
                panel.edges.setCurrentText(simulation["edges"]);panel.resolution.setCurrentText(str(bake["resolution"]))
                panel.normal.setCurrentText(bake["normal"]);panel.height.setValue(bake["height_max"])
                assert [panel.assets.item(i,0).text() for i in range(panel.assets.rowCount())]==[r.get("source_name",Path(r["path"]).name) for r in (rows or asset_rows)]
                loop=QtCore.QEventLoop();panel.run(rebake);assert panel.process is not None,panel.status.text()
                assert all(not w.isEnabled() for w in panel.editable_controls),"Inputs remain editable during execution"
                assert not panel.simulate.isEnabled() and not panel.rebake.isEnabled() and panel.cancel.isEnabled()
                launched_job=jobs.active["job_id"]
                process=panel.process;process.finished.connect(loop.quit)
                watchdog=QtCore.QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(loop.quit);watchdog.start(90000)
                loop.exec();watchdog.stop()
                assert panel.process is None,"Successful UI worker exceeded timeout"
                current=jobs.current;assert current and current["job_id"]==launched_job and current["request"]["schema_version"]==2,panel.status.text()
                if "spawned_count" in current["result"]:
                    r=current["result"];assert ("Created "+str(r["spawned_count"])+" of "+str(r["requested_count"])) in panel.status.text(),panel.status.text()
                assert designer.settings(graph)["config"]["assets"]
                assert all(w.isEnabled() for w in panel.editable_controls) and not panel.cancel.isEnabled()
                evidence.setdefault("successful_qprocess",[]).append({"operation":"rebake" if rebake else "simulate_bake","job_id":current["job_id"],"asset_count":len(rows or asset_rows),"inputs_locked":True,"status":panel.status.text(),"mask_snapshot":panel.mask_snapshot.text()})
                return current
            finally:
                if panel.process is None:panel.close();panel.deleteLater()
                else:
                    # Keep our own still-active widget alive for explicit coordinator recovery; no forced deletion.
                    globals().setdefault("_timed_out_test_panels",[]).append(panel)
        path=jobs.prepare((rows or asset_rows) if STAGE2 else ROOT/"tests/fixtures/cube.obj",simulation,bake,rebake=rebake,scatter_mask=mask)
        process=subprocess.run([str(ui.worker_path()),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=90)
        assert process.returncode==0,process.stdout+process.stderr
        return jobs.validate(path.parent/"result.json",jobs.active["job_id"])

    for index,res in enumerate((512,1024)):
        graph,instance=designer.create(parent)
        sink=parent.newNode("sbs::compositing::output");sink.setAnnotationPropertyValueFromId("identifier",SDValueString.sNew("scatter_height_"+str(index)))
        instance.newPropertyConnectionFromId("height",sink,"inputNodeOutput")
        simulation={"count":5,"scale":.3,"width":2,"depth":2,"seconds":8,"edges":"walls","seed":index+1}
        bake={"resolution":res,"height_min":0,"height_max":2,"normal":"DirectX","samples":1}
        jobs=core.Jobs(designer.result_directory(graph));candidate=generate(jobs,simulation,bake,graph=graph if STAGE2 else None)
        config={"assets":asset_rows,"simulation":candidate["request"]["simulation"],"bake":bake} if STAGE2 else None
        if not STAGE2:designer.update(graph,candidate,config);jobs.promote(candidate)
        if STAGE2:assert {p["asset_id"] for p in candidate["result"]["poses"]}=={a["asset_id"] for a in asset_rows},"Both shapes must be selected in fixture"
        values=pixels(graph,"initial_"+str(index),candidate)
        assert values["height"]["header"][:3]==(res,res,16)
        graphs.append((graph,instance,sink,jobs));completed.append(candidate)
    untouched=pixels(graphs[1][0],"node2_before")
    graph,instance,sink,jobs=graphs[0]
    topology_before=edge(parent,instance,sink,graph)
    request=completed[0]["request"];bake=dict(request["bake"]);bake.update(resolution=2048,normal="OpenGL")
    candidate=generate(jobs,request["simulation"],bake,True,graph=graph if STAGE2 else None)
    assert candidate["result"]["poses"]==completed[0]["result"]["poses"],"Rebake changed cached poses"
    if not STAGE2:designer.update(graph,candidate);jobs.promote(candidate)
    completed[0]=candidate
    assert edge(parent,instance,sink,graph)==topology_before
    assert pixels(graphs[1][0],"node2_after")==untouched
    pixels(graph,"rebaked",candidate)
    parent.compute();value=sink.getPropertyValue(sink.getProperties(SDPropertyCategory.Output)[0]);value.get().save(str(WORK/"downstream_height.png"))
    assert signature(WORK/"downstream_height.png")==signature(candidate["files"]["height"])
    evidence["pixels_and_topology"]={"exact_all_channels":True,"node2_unchanged":True,"downstream_exact":True,"topology":topology_before};report()

    baseline=pixels(graph,"fault_baseline");baseline_state=designer.settings(graph);baseline_pointer=core.digest(jobs.directory/"current.json")
    changed=dict(bake);changed["height_max"]=3;alternate=generate(jobs,request["simulation"],changed,True)
    fault_results=[]
    for kind in ("compute","store","promotion"):
        seen=[False]
        def fail_once(original):
            def injected(*args,**kwargs):
                if not seen[0]:seen[0]=True;raise errors.APIException(SDApiError.NotSupported)
                return original(*args,**kwargs)
            return injected
        try:
            if kind=="compute":
                original=graph.compute
                with mock.patch.object(graph,"compute",side_effect=fail_once(original)):designer.update(graph,alternate)
            elif kind=="store":
                original=designer.store
                with mock.patch.object(designer,"store",side_effect=fail_once(original)):designer.update(graph,alternate)
            else:
                rollback=designer.update(graph,alternate)
                try:
                    with mock.patch.object(core,"atomic_json",side_effect=OSError("injected promotion failure")):jobs.promote(alternate)
                except HOST_ERRORS as original:errors.rollback_or_raise(original,rollback)
            raise AssertionError("Injected error did not propagate: "+kind)
        except HOST_ERRORS as error:assert not isinstance(error,AssertionError),str(error)
        assert pixels(graph,"restored_"+kind)==baseline
        assert designer.settings(graph)==baseline_state
        assert core.digest(jobs.directory/"current.json")==baseline_pointer
        assert edge(parent,instance,sink,graph)==topology_before
        fault_results.append(kind)
    jobs.cancel();evidence["fault_injection"]=fault_results;report()

    with isolated_panel(lambda:test_ui.Panel()) as test_panel:
        test_panel.graph=graph;test_panel.jobs=jobs
        test_panel.set_mask(None)
        test_panel.mesh.setText(str(ROOT/"tests/fixtures/cube.obj"));test_panel.count.setValue(5000);test_panel.scale.setValue(.08);test_panel.seconds.setValue(120)
        if STAGE2:test_panel.set_assets([dict(row,scale=.08) for row in asset_rows])
        for kind in ("cancel","crash"):
            loop=QtCore.QEventLoop();test_panel.run(False);assert test_panel.process is not None
            process=test_panel.process;process.finished.connect(loop.quit)
            QtCore.QTimer.singleShot(5,test_panel.stop if kind=="cancel" else process.kill)
            watchdog=QtCore.QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(loop.quit);watchdog.start(15000)
            loop.exec();watchdog.stop()
            assert test_panel.process is None,"Worker did not finish before timeout"
            assert core.digest(jobs.directory/"current.json")==baseline_pointer
            assert pixels(graph,"qprocess_"+kind)==baseline
            assert designer.settings(graph)==baseline_state
    assert substance_physics_scatter._panel is existing_user_panel
    evidence["qprocess"]={"cancel_preserved":True,"crash_preserved":True,"existing_panel_preserved":True};report()

    expected_states={g.getIdentifier():designer.settings(g) for g,_,_,_ in graphs}
    expected_pixels={g.getIdentifier():pixels(g,"save_before_"+str(index)) for index,(g,_,_,_) in enumerate(graphs)}
    expected_edges=[edge(parent,i,s,g) for g,i,s,_ in graphs]
    mgr.savePackage(package);ids=[g.getIdentifier() for g,_,_,_ in graphs]
    mgr.unloadUserPackage(package);package=mgr.loadUserPackage(str(package_path))
    adopt_owned_package(package,package_path)
    resources={r.getIdentifier():r for r in package.getChildrenResources(True)};restored_parent=resources["PhysicsScatterDemo"]
    for index,identifier in enumerate(ids):
        restored=resources[identifier]
        assert designer.settings(restored)==expected_states[identifier]
        assert pixels(restored,"reopened_"+str(index))==expected_pixels[identifier]
        topology=expected_edges[index]
        source=restored_parent.getNodeFromId(topology["source"]);destination=restored_parent.getNodeFromId(topology["destination"])
        assert edge(restored_parent,source,destination,restored)==topology
    if STAGE2:
        prepare_moved_fixture=fresh_helper("moved_fixture").prepare
        moved_package,migration_audit=prepare_moved_fixture(package_path,original_assets,WORK)
        relocated=moved_package.parent;evidence["migration_fixture"]=migration_audit;report()
        # Only our main test package is unloaded. The never-loaded staging source is already parked.
        mgr.unloadUserPackage(package)
        package=mgr.loadUserPackage(str(moved_package));resources={r.getIdentifier():r for r in package.getChildrenResources(True)}
        adopt_owned_package(package,moved_package)
        assert Path(package.getFilePath()).resolve()==moved_package.resolve(),"SDK did not load the moved package"
        moved_parent=resources["PhysicsScatterDemo"]
        linked=[]
        for resource in package.getChildrenResources(True):
            if isinstance(resource,designer.SDResourceBitmap):
                raw=resource.getFilePath();actual=Path(raw)
                if not actual.is_absolute():actual=relocated/actual
                actual=actual.resolve()
                assert actual.is_relative_to(relocated) and actual.is_file(),("Moved Linked resource escaped/missing",raw,str(actual))
                linked.append({"identifier":resource.getIdentifier(),"getFilePath":raw,"resolved":str(actual)})
        assert len(linked)==len(migration_audit["relative_linked"])
        evidence["moved_linked_resources_before_relink"]=linked;report()
        for index,identifier in enumerate(ids):
            restored=resources[identifier];moved_jobs=core.Jobs(designer.result_directory(restored));current=moved_jobs.current
            assert all(Path(a["path"]).is_relative_to(relocated) and Path(a["path"]).is_file() for a in current["request"]["assets"])
            # The genuine relative Linked save must display correctly before any update/relink.
            assert pixels(restored,"moved_display_"+str(index))==expected_pixels[identifier]
            with isolated_panel(lambda:test_ui.Panel()) as restored_panel:
                restored_panel.nodes.setCurrentText(identifier);restored_panel._select()
                recovered=restored_panel.asset_rows()
                assert len(recovered)==2 and all(Path(a["path"]).is_relative_to(relocated) and Path(a["path"]).is_file() for a in recovered)
                assert [restored_panel.assets.item(i,0).text() for i in range(2)]==["cube.obj","pyramid.obj"]
            moved_candidate=generate(moved_jobs,current["request"]["simulation"],current["request"]["bake"],True,current["request"]["assets"],graph=restored)
            assert moved_candidate["result"]["poses"]==current["result"]["poses"]
            pixels(restored,"moved_rebake_"+str(index),moved_candidate)
            topology=expected_edges[index]
            assert edge(moved_parent,moved_parent.getNodeFromId(topology["source"]),moved_parent.getNodeFromId(topology["destination"]),restored)==topology
        evidence["moved_copy"]={"all_assets_rebased":True,"staging_results_unavailable":True,"staging_original_meshes_unavailable":True,"main_proof_folders_untouched":True,"relative_linked_pre_relink_display_exact":True,"ui_original_filenames_preserved":True,"display_exact":True,"rebake_poses_unchanged":True}
        # A genuine archived v1 result remains displayable, while UI rebake starts no QProcess/job directory.
        legacy_graph,_=designer.create(moved_parent);legacy_jobs=core.Jobs(designer.result_directory(legacy_graph))
        legacy_id=uuid.uuid4().hex;legacy_run=legacy_jobs.directory/"runs"/legacy_id;legacy_run.mkdir(parents=True)
        source=ROOT/"tests/fixtures/cube.obj";sha=core.digest(source);cache=legacy_jobs.directory/"assets"/(sha+".obj");cache.parent.mkdir();shutil.copyfile(source,cache)
        legacy_request={"schema_version":1,"job_id":legacy_id,"operation":"simulate_bake","asset_path":str(cache),"input_hash":sha,"simulation_key":"legacy_fixture","output_directory":str(legacy_run),"simulation":{"count":1,"scale":.25,"seconds":8},"bake":{"resolution":256,"normal":"DirectX"}}
        core.atomic_json(legacy_run/"request.json",legacy_request)
        process=subprocess.run([str(ROOT/"accepted-stage1/scatter_worker.exe"),str(legacy_run/"request.json")],capture_output=True,text=True,encoding="utf-8",timeout=60)
        assert process.returncode==0,process.stdout+process.stderr
        legacy_result=json.loads((legacy_run/"result.json").read_text(encoding="utf-8"))
        legacy={"job_id":legacy_id,"request":legacy_request,"result":legacy_result,"result_path":str(legacy_run/"result.json"),"simulation_key":"legacy_fixture","files":{c:str(legacy_run/(c+".png")) for c in designer.CHANNELS}}
        core.atomic_json(legacy_jobs.directory/"current.json",legacy);designer.update(legacy_graph,legacy,{"mesh":str(cache),"simulation":legacy_request["simulation"],"bake":legacy_request["bake"]})
        pixels(legacy_graph,"v1_display",legacy);legacy_pointer=core.digest(legacy_jobs.directory/"current.json")
        with isolated_panel(lambda:test_ui.Panel()) as test_panel:
            test_panel.graph=legacy_graph;test_panel.jobs=legacy_jobs;test_panel.set_assets(asset_rows)
            before_runs=sorted(p.name for p in (legacy_jobs.directory/"runs").iterdir())
            test_panel.run(True)
            assert test_panel.process is None and legacy_jobs.active is None
            assert test_panel.status.text()==core.LEGACY_REBAKE,test_panel.status.text()
            assert sorted(p.name for p in (legacy_jobs.directory/"runs").iterdir())==before_runs
            assert core.digest(legacy_jobs.directory/"current.json")==legacy_pointer
        evidence["v1_compatibility"]={"actual_v1_pixels_exact":True,"rebake_process_starts":0,"rebake_job_directories":0,"pointer_unchanged":True}
        mgr.savePackage(package)
    if POSE_COMPAT:
        # Real accepted 0.2 files are read-only inputs. Work only in this unique copy.
        accepted=ROOT/"accepted-stage2A/fixtures";archive_work=WORK/"archived0_2";shutil.copytree(accepted,archive_work)
        immutable_initial={str(path.relative_to(archive_work)):core.digest(path) for path in archive_work.rglob("*") if path.is_file() and path.name not in ("current.json","PhysicsScatterDemo.sbs")}
        archive_path=archive_work/"PhysicsScatterDemo.sbs";archive_package=mgr.loadUserPackage(str(archive_path))
        adopt_owned_package(archive_package,archive_path)
        assert Path(archive_package.getFilePath()).resolve()==archive_path.resolve(),"SDK did not load owned archived copy"
        archived_graphs=[r for r in archive_package.getChildrenResources(True) if isinstance(r,SDSBSCompGraph) and designer.settings(r)]
        assert len(archived_graphs)==2
        legacy_checks=[];archive_expected={}
        for index,legacy_graph in enumerate(archived_graphs):
            legacy_jobs=core.Jobs(designer.result_directory(legacy_graph));old=legacy_jobs.current
            assert old["result"]["worker_version"]=="0.2.0"
            expected=pixels(legacy_graph,"accepted0_2_before_"+str(index),old);archive_expected[legacy_graph.getIdentifier()]=expected
            first=generate(legacy_jobs,old["request"]["simulation"],old["request"]["bake"],True,old["request"]["assets"],graph=legacy_graph)
            second=generate(legacy_jobs,old["request"]["simulation"],old["request"]["bake"],True,old["request"]["assets"],graph=legacy_graph)
            for candidate in (first,second):
                assert candidate["result"]["poses"]==old["result"]["poses"]
                assert candidate["result"]["execution"]=={"physics_executed":False,"body_count":0,"steps":0}
                assert candidate["result"]["worker_version"]==core.VERSION
                assert candidate["simulation_key"]==old["simulation_key"]
            assert first["result"]["pose_origin"]==second["result"]["pose_origin"]
            assert first["result"]["rebake_source"]["job_id"]==old["job_id"]
            assert second["result"]["rebake_source"]["job_id"]==first["job_id"]
            assert pixels(legacy_graph,"accepted0_2_after_"+str(index),second)==expected
            legacy_checks.append({"initial_operation":old["request"]["operation"],"original_job":old["job_id"],"origin":second["result"]["pose_origin"],"immediate_source":second["result"]["rebake_source"],"exact_poses_pixels":True,"execution":second["result"]["execution"]})
        assert {check["initial_operation"] for check in legacy_checks}=={"simulate_bake","bake"}
        assert all(core.digest(archive_work/path)==digest for path,digest in immutable_initial.items())
        mgr.savePackage(archive_package)
        moved_legacy,moved_audit=prepare_moved_fixture(archive_path,archive_work/"original_assets",WORK,namespace="legacy_migration")
        assert moved_audit["immutable_json_rewritten_count"]==0
        mgr.unloadUserPackage(archive_package);archive_package=mgr.loadUserPackage(str(moved_legacy))
        adopt_owned_package(archive_package,moved_legacy)
        assert Path(archive_package.getFilePath()).resolve()==moved_legacy.resolve()
        moved_resources={r.getIdentifier():r for r in archive_package.getChildrenResources(True)}
        for identifier,expected in archive_expected.items():
            restored=moved_resources[identifier];assert pixels(restored,"legacy_moved_display_"+identifier)==expected
            jobs=core.Jobs(designer.result_directory(restored));old=jobs.current
            candidate=generate(jobs,old["request"]["simulation"],old["request"]["bake"],True,old["request"]["assets"],graph=restored)
            assert candidate["result"]["poses"]==old["result"]["poses"] and candidate["result"]["pose_origin"]==old["result"]["pose_origin"]
            assert candidate["result"]["execution"]=={"physics_executed":False,"body_count":0,"steps":0}
            assert pixels(restored,"legacy_moved_rebaked_"+identifier)==expected
        mgr.savePackage(archive_package);mgr.unloadUserPackage(archive_package);archive_package=mgr.loadUserPackage(str(moved_legacy))
        adopt_owned_package(archive_package,moved_legacy)
        reopened={r.getIdentifier():r for r in archive_package.getChildrenResources(True)}
        for identifier,expected in archive_expected.items():assert pixels(reopened[identifier],"legacy_reopened_"+identifier)==expected
        evidence["pose_compatibility"]={"accepted0_2":legacy_checks,"moved_legacy_chain":moved_audit,"immutable_input_files_unchanged":True,"reopen_exact":True};report()
    if FILE_MASK:fresh_helper("designer_file_mask_lane").run(globals())
    evidence.update(status="pass",save_reopen_exact_pixels_settings_topology=True,nodes=ids,worker_sha256=core.digest(ui.worker_path()))
    evidence["source_sha256"]=hashlib.sha256(json.dumps(before_fingerprint,sort_keys=True).encode()).hexdigest();report()
except (Exception, errors.APIException if "errors" in globals() else Exception):
    evidence.update(status="failed",traceback=traceback.format_exc());report()
    raise RuntimeError("Designer acceptance failed; details: "+str(REPORT))
