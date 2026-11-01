"""Read-only actual example and temporary snapshot tests; no prepare CLI/SDK."""
from pathlib import Path
import ast,copy,json,struct,sys,tempfile,unittest,re
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'local_review'))
import designer_review as D


class DesignerReview(unittest.TestCase):
    def test_mask_budget_and_sha_are_checked_before_existing_mask_readers(self):
        from substance_physics_scatter import compat,graph_companion,maskio
        latest=D.doc(D.read(D.LATEST));directory=Path(latest['directory']);graph=latest['target']['graph_identifier']
        current=D.doc(D.read(directory/'Scatter_PhysicsScatter'/graph/'current.json'))
        request=D.doc(D.read(directory/'Scatter_PhysicsScatter'/graph/'runs'/current['job_id']/'request.json'))
        path=Path(request['scatter_mask']['path']);original_read=D.read;legacy_read=maskio.read;events=[]
        def bounded_read(value,limit=D.MAX_FILE):
            if Path(value)==path:
                self.assertEqual(limit,2*1024*1024);raw=original_read(value,limit)
                self.assertEqual(D.digest(raw),request['scatter_mask']['content_hash']);events.append('bounded+sha');return raw
            return original_read(value,limit)
        def reader(*args,**kwargs):
            self.assertTrue(events);self.assertEqual(events[0],'bounded+sha');events.append('legacy read')
            return legacy_read(*args,**kwargs)
        with patch.object(D,'read',side_effect=bounded_read),patch.object(maskio,'read',side_effect=reader):D.source_files()
        self.assertIn('legacy read',events)
        for failure in ('size','sha'):
            def rejected(value,limit=D.MAX_FILE):
                if Path(value)==path:
                    self.assertEqual(limit,2*1024*1024)
                    if failure=='size':raise ValueError('TEST_ONLY mask over2MiB')
                    return b'wrong mask bytes'
                return original_read(value,limit)
            with patch.object(D,'read',side_effect=rejected),patch.object(compat,'source') as source,patch.object(graph_companion,'read') as companion:
                with self.assertRaisesRegex(ValueError,'over2MiB|Mask bytes differ'):D.source_files()
                source.assert_not_called();companion.assert_not_called()

    def test_original_maps_twenty_poses_and_float32_geometry_origin_are_exact(self):
        job,files,watch,display,mesh,meta,le=D.source_files()
        original=D.doc(files['raw/result.json'])
        self.assertEqual(display['poses'],original['poses']);self.assertEqual(len(display['poses']),len(original['poses']))
        self.assertEqual(mesh['triangles'],4998);self.assertEqual(mesh['origin_shift'],[0,0,0]);self.assertEqual(mesh['scale_applied'],1)
        self.assertEqual(len(le),meta['width']*meta['height']*2);self.assertEqual(D.digest(files['raw/height.png']),meta['source_png_sha256'])
        current=D.doc(files['raw/current.json'])
        for channel in ('height','normal','coverage'):
            self.assertEqual(D.digest(files['raw/'+channel+'.png']),current['hashes'][channel])
            self.assertEqual(display['map_descriptors'][channel]['byte_sha256'],current['hashes'][channel])
        D.check_source_watch(watch)
        raw=b'v -0 2 3\nv 2 2 3\nv 2 4 3\nf 1 2 3\n';small=D.geometry(raw)
        self.assertEqual(struct.pack('<f',small['positions'][0][0]),struct.pack('<f',-0.))
        self.assertEqual(small['positions'][0][1:],[2.,3.]);self.assertEqual(small['indices'],[0,1,2])
        self.assertNotIn('producer',display);self.assertFalse(display['PBR']);self.assertEqual(display['hull_status'],'absent')

    def test_copied_snapshot_get_keeps_sealed_bytes_and_rejects_tamper(self):
        job,files,watch,display,mesh,meta,le=D.source_files()
        files.update({'display.json':D.encoded(display),'geometry.json':D.encoded(mesh),'height.json':D.encoded(meta),'height.u16le':le})
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);parent=work/'designer-review';root=parent/job;root.mkdir(parents=True);entries=[]
            for name,raw in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                entries.append(dict(name=name,sha256=D.digest(raw),bytes=len(raw)))
            manifest=D.encoded(dict(version=1,kind='designer_graph_readonly',job_id=job,files=entries,source_watch=watch))
            (root/'manifest.json').write_bytes(manifest);(parent/'latest.json').write_bytes(D.encoded(dict(version=1,job_id=job,manifest_sha256=D.digest(manifest))))
            value=D.load(work)
            self.assertEqual(value['maps']['height'],files['raw/height.png']);self.assertEqual(value['display']['poses'],display['poses'])
            (root/'raw/height.png').write_bytes(files['raw/height.png']+b'changed')
            with self.assertRaisesRegex(ValueError,'Designer copied bytes|budget|bounded'):D.load(work)
            self.assertEqual(value['maps']['height'],files['raw/height.png'])

    def test_path_obj_and_pixel_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'inside';path.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError,'escapes'):D.owned(root/'..'/'outside',root)
            original=Path.is_symlink
            with patch.object(Path,'is_symlink',lambda value:value==path or original(value)):
                with self.assertRaisesRegex(ValueError,'symlink'):D.owned(path,root)
        for raw in (b'v nan 0 0\nf 1 1 1\n',b'v 0 0 0\nf 1 2 3\n',b'v 0 0 0\nf 1 1 1 1\n',b'UNKNOWN x\n'):
            with self.assertRaises(ValueError):D.geometry(raw)
        for x,y in ((-1,0),(128,0),(0,128),(True,0)):
            with self.assertRaises(ValueError):D.pixel({'height':{'width':128,'height':128}},'height',x,y)

    def test_source_saved_after_capture_is_context_not_an_authored_gate(self):
        original=D.read
        def after_save(path,limit=D.MAX_FILE):
            raw=original(path,limit)
            return raw+b'\n' if Path(path).name=='Source.sbs' else raw
        with patch.object(D,'read',side_effect=after_save):
            job,files,watch,display,mesh,meta,le=D.source_files()
        context=display['source']['disk_context']
        self.assertEqual(context['current_file_sha256'],D.digest(files['raw/Source.sbs']))
        self.assertFalse(context['matches_capture_disk'])
        self.assertEqual(display['poses'],D.doc(files['raw/result.json'])['poses'])

    def test_refresh_promotes_once_preserves_lastgood_and_pins_all_old_urls(self):
        # TEST_ONLY validated-model seam: no SDK/native job is synthesized or run.
        initial=D.source_files();old=initial[0];new='f'*32
        if new==old:new='e'*32
        following=copy.deepcopy(initial);following=list(following);following[0]=new
        following[3]['job_id']=new;following[5]['job_id']=new
        following[3]['poses'][0]['position'][0]+=.25
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            with patch.object(D,'check_source_watch'):
                D._commit(work,initial)
                before=(work/'designer-review/latest.json').read_bytes()
                with patch.object(D,'input_hint',return_value=(('failed-input',),new)),patch.object(D,'source_files',side_effect=ValueError('partial/cancelled/changed mask')) as validate:
                    one=D.state(work);two=D.state(work)
                    self.assertEqual(validate.call_count,1);self.assertEqual(one['job_id'],old);self.assertEqual(two['sync']['status'],'error')
                    self.assertEqual((work/'designer-review/latest.json').read_bytes(),before)
                with patch.object(D,'input_hint',return_value=(('complete-input',),new)),patch.object(D,'source_files',return_value=tuple(following)) as validate:
                    state=D.state(work);D.state(work);self.assertEqual(validate.call_count,1)
                self.assertEqual(state['job_id'],new);self.assertEqual(state['sync']['status'],'updated')
            # Snapshot GET no longer depends on mutable/missing original files.
            with patch.object(D,'check_source_watch',side_effect=AssertionError('GET must not read original source')):
                previous=D.load(work,old);latest=D.load(work,new)
            self.assertEqual(previous['display']['poses'],initial[3]['poses'])
            self.assertNotEqual(previous['display']['poses'],latest['display']['poses'])
            for data,job in ((previous,old),(latest,new)):
                shown=data['display']
                for url in (shown['geometry_url'],*shown['maps'].values(),*shown['height_field'].values()):self.assertIn('?job='+job,url)
            with self.assertRaisesRegex(ValueError,'Unknown'):D.load(work,'a'*32)
            with patch.object(D,'source_files') as validate:
                D._sync_lock.acquire()
                try:self.assertEqual(D.state(work)['sync']['status'],'syncing')
                finally:D._sync_lock.release()
                validate.assert_not_called()

    def test_server_changes_are_get_only_and_surface_reuses_uint16_origin_once(self):
        source=(ROOT/'local_review/server.py').read_text(encoding='utf8');tree=ast.parse(source)
        routes=[]
        for node in tree.body:
            if isinstance(node,ast.AsyncFunctionDef) and node.name.startswith('designer_review_'):
                for decorator in node.decorator_list:
                    if isinstance(decorator,ast.Call):routes.append(decorator.func.attr)
        self.assertTrue(routes);self.assertEqual(set(routes),{'get'})
        js=(ROOT/'local_review/web/designer-review.js').read_text(encoding='utf8')
        self.assertIn("import {loadSurface} from '/web/surface.js'",js)
        self.assertRegex(js,r'mesh\.position\.z=(?:s\.)?surface\.meta\.height_min')
        self.assertIn('.quaternion.fromArray(',js);self.assertNotRegex(js,r'quaternion\.fromArray\([^)]*\)\.normalize')
        self.assertIn("world.rotation.x=-Math.PI/2",js);self.assertNotIn('getImageData',js)
        self.assertIn("document.body.dataset.ready='true'",js)


if __name__=='__main__':unittest.main()
