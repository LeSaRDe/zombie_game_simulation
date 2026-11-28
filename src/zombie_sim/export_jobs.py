"""Cancellable exports from a pinned, immutable committed history prefix."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import struct
import threading
import uuid
import zlib
from .storage import canonical, exact_time
from .visualization import project_state, populations, world_svg, view_bundle, cohort_members

FORMATS={"scene_png":("png","image/png"),"chart_png":("png","image/png"),
         "chart_svg":("svg","image/svg+xml"),"table_csv":("csv","text/csv"),
         "table_parquet":("parquet","application/vnd.apache.parquet"),"replay_animation":("html","text/html")}
COLORS={"healthy":(55,161,139),"infected":(222,159,52),"zombies":(205,80,105),"dead":(111,122,136)}
FONT={
 'A':'01110 10001 10001 11111 10001 10001 10001','B':'11110 10001 10001 11110 10001 10001 11110',
 'C':'01111 10000 10000 10000 10000 10000 01111','D':'11110 10001 10001 10001 10001 10001 11110',
 'E':'11111 10000 10000 11110 10000 10000 11111','F':'11111 10000 10000 11110 10000 10000 10000',
 'G':'01111 10000 10000 10111 10001 10001 01111','H':'10001 10001 10001 11111 10001 10001 10001',
 'I':'11111 00100 00100 00100 00100 00100 11111','J':'00111 00010 00010 00010 10010 10010 01100',
 'K':'10001 10010 10100 11000 10100 10010 10001','L':'10000 10000 10000 10000 10000 10000 11111',
 'M':'10001 11011 10101 10101 10001 10001 10001','N':'10001 11001 10101 10011 10001 10001 10001',
 'O':'01110 10001 10001 10001 10001 10001 01110','P':'11110 10001 10001 11110 10000 10000 10000',
 'Q':'01110 10001 10001 10001 10101 10010 01101','R':'11110 10001 10001 11110 10100 10010 10001',
 'S':'01111 10000 10000 01110 00001 00001 11110','T':'11111 00100 00100 00100 00100 00100 00100',
 'U':'10001 10001 10001 10001 10001 10001 01110','V':'10001 10001 10001 10001 10001 01010 00100',
 'W':'10001 10001 10001 10101 10101 11011 10001','X':'10001 10001 01010 00100 01010 10001 10001',
 'Y':'10001 10001 01010 00100 00100 00100 00100','Z':'11111 00001 00010 00100 01000 10000 11111',
 '0':'01110 10001 10011 10101 11001 10001 01110','1':'00100 01100 00100 00100 00100 00100 01110',
 '2':'01110 10001 00001 00010 00100 01000 11111','3':'11110 00001 00001 01110 00001 00001 11110',
 '4':'00010 00110 01010 10010 11111 00010 00010','5':'11111 10000 10000 11110 00001 00001 11110',
 '6':'01110 10000 10000 11110 10001 10001 01110','7':'11111 00001 00010 00100 01000 01000 01000',
 '8':'01110 10001 10001 01110 10001 10001 01110','9':'01110 10001 10001 01111 00001 00001 01110',
 '.':'00000 00000 00000 00000 00000 00110 00110','-':'00000 00000 00000 11111 00000 00000 00000',
 '(':'00010 00100 01000 01000 01000 00100 00010',')':'01000 00100 00010 00010 00010 00100 01000'}


class CancelledExport(Exception):pass


class Raster:
    """Small deterministic RGB renderer; PNG encoding uses standard library only."""
    def __init__(self,width=960,height=600):
        self.width=width;self.height=height;self.pixels=bytearray((248,250,252))*(width*height)
    def rect(self,x,y,w,h,color):
        x0,x1=max(0,int(x)),min(self.width,int(x+w));y0,y1=max(0,int(y)),min(self.height,int(y+h))
        if x1<=x0 or y1<=y0:return
        row=bytes(color)*(x1-x0)
        for yy in range(y0,y1):self.pixels[(yy*self.width+x0)*3:(yy*self.width+x1)*3]=row
    def line(self,x0,y0,x1,y1,color,width=2):
        steps=max(1,int(max(abs(x1-x0),abs(y1-y0))))
        for i in range(steps+1):self.rect(x0+(x1-x0)*i/steps,y0+(y1-y0)*i/steps,width,width,color)
    def circle(self,x,y,r,color):
        for yy in range(int(y-r),int(y+r)+1):
            span=max(0,r*r-(yy-y)**2)**.5;self.rect(x-span,yy,span*2+1,1,color)
    def text(self,x,y,text,color=(37,55,70),scale=2):
        for index,character in enumerate(str(text).upper()):
            for row,bits in enumerate(FONT.get(character,'').split()):
                for column,bit in enumerate(bits):
                    if bit=='1':self.rect(x+(index*6+column)*scale,y+row*scale,scale,scale,color)
    def png(self,metadata):
        def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
        raw=b''.join(b'\0'+self.pixels[y*self.width*3:(y+1)*self.width*3] for y in range(self.height))
        return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',self.width,self.height,8,2,0,0,0))+
                chunk(b'tEXt',b'Description\0'+canonical(metadata).encode())+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b''))













class ExportRendererRegistry:
    """Explicit export strategies; optional encoders import only when selected."""
    def __init__(self):
        self._renderers = {}

    def register(self, name, renderer, *, replace=False):
        if not isinstance(name, str) or not name or not callable(getattr(renderer, 'render', None)):
            raise ValueError('An export strategy requires a name and render method')
        if name in self._renderers and not replace:
            raise ValueError(f'Export renderer already registered: {name}')
        self._renderers[name] = renderer

    def __contains__(self, name):
        return name in self._renderers

    def render(self, name, scene, rows, frames, provenance):
        try:
            renderer = self._renderers[name]
        except KeyError:
            raise ValueError('Unknown export format') from None
        return renderer.render(scene, rows, frames, provenance)

    @classmethod
    def builtins(cls):
        result = cls()
        for name, strategy in (('scene_png', ScenePNGRenderer()), ('chart_png', PNGChartRenderer()),
                               ('chart_svg', SVGChartRenderer()), ('table_csv', CSVTableRenderer()),
                               ('table_parquet', ParquetTableRenderer()), ('replay_animation', ReplayRenderer())):
            result.register(name, strategy)
        return result


class ScenePNGRenderer:
    """Encode one portable recorded-history artifact."""
    def render(self, source_scene, rows, frames, provenance):
        scene = source_scene
        canvas=Raster();world=scene['world'];scale=min(900/float(world['length']),540/float(world['width']))
        ox=(960-float(world['length'])*scale)/2;oy=(600-float(world['width'])*scale)/2
        xy=lambda x,y:(ox+float(x)*scale,600-oy-float(y)*scale)
        canvas.rect(ox,oy,float(world['length'])*scale,float(world['width'])*scale,(227,235,239))
        for item in scene.get('barriers',{}).values():
            r=item.get('footprint');
            if not r:continue
            x,y=xy(r[0],r[3]);color=(104,125,141) if item.get('type')!='Gate' else (89,163,119) if item.get('mode')=='OPEN' else (188,146,70)
            canvas.rect(x,y,(r[2]-r[0])*scale,(r[3]-r[1])*scale,color)
        for item in scene.get('stockpiles',{}).values():
            x,y=xy(item['x'],item['y']);canvas.rect(x-3,y-3,6,6,(94,90,55))
        for item in scene.get('agents',{}).values():
            status='dead' if item.get('life',100)<=0 else 'zombies' if item['type']=='Zombie' else 'infected' if item.get('infection_episode') else 'healthy'
            canvas.circle(*xy(item['x'],item['y']),3,COLORS[status])
        canvas.text(30,8,'RECORDED WORLD');canvas.text(30,580,f"TIME {float(exact_time(provenance['time'])):g} S")
        return canvas.png(provenance)


class SVGChartRenderer:
    """Encode one portable recorded-history artifact."""
    def render(self, source_scene, rows, frames, provenance):
        maximum=max(1,max((row['total'] for row in rows),default=1));start=float(exact_time(rows[0]['time']));end=float(exact_time(rows[-1]['time']))
        xy=lambda row,key:(70+820*(float(exact_time(row['time']))-start)/max(1e-12,end-start),520-430*row[key]/maximum)
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600">',
               '<rect width="960" height="600" fill="#f8fafc"/><g font-family="sans-serif" fill="#253746">',
               '<text x="70" y="35" font-size="22">Population through recorded time</text>',
               '<path d="M70 70V520H910" fill="none" stroke="#64748b"/>',
               f'<text x="20" y="85">{maximum}</text><text x="45" y="525">0</text>',
               f'<text x="65" y="547">{start:g}</text><text x="875" y="547">{end:g}</text><text x="430" y="575">Time (s)</text>']
        for index,(key,color) in enumerate(COLORS.items()):
            value='#'+''.join(f'{part:02x}' for part in color)
            points=' '.join(f'{x:g},{y:g}' for x,y in (xy(row,key) for row in rows))
            parts.append(f'<polyline fill="none" stroke="{value}" stroke-width="3" points="{points}"/><rect x="{70+index*205}" y="55" width="12" height="12" fill="{value}"/><text x="{87+index*205}" y="66">{key.capitalize()}</text>')
        parts.append('</g><metadata>'+html.escape(canonical(provenance))+'</metadata></svg>')
        return ''.join(parts).encode()


class PNGChartRenderer:
    """Encode one portable recorded-history artifact."""
    def render(self, source_scene, rows, frames, provenance):
        canvas=Raster();canvas.line(70,70,70,520,(100,116,139));canvas.line(70,520,910,520,(100,116,139))
        maximum=max(1,max(row['total'] for row in rows));start=exact_time(rows[0]['time']);end=exact_time(rows[-1]['time'])
        canvas.text(70,15,'POPULATION THROUGH RECORDED TIME');canvas.text(400,575,'TIME (S)')
        canvas.text(10,75,str(maximum));canvas.text(45,515,'0');canvas.text(65,540,f'{float(start):g}');canvas.text(865,540,f'{float(end):g}')
        for index,(key,color) in enumerate(COLORS.items()):
            canvas.rect(70+index*205,47,12,12,color);canvas.text(90+index*205,45,key)
            points=[(70+820*float((exact_time(row['time'])-start)/(end-start or 1)),520-430*row[key]/maximum) for row in rows]
            if len(points)==1:canvas.circle(*points[0],3,color)
            for left,right in zip(points,points[1:]):canvas.line(*left,*right,color,3)
        return canvas.png({**provenance,'series':list(COLORS),'y_axis':'Identities','x_axis':'Time (s)','y_max':maximum})


class ReplayRenderer:
    """Encode one portable recorded-history artifact."""
    def render(self, source_scene, rows, frames, provenance):
        data=canonical({'provenance':provenance,'frames':frames}).replace('<','\\u003c')
        return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Recorded simulation replay</title>\n<style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:20px;background:#f8fafc;color:#253746}svg{max-width:100%;height:auto}button,input{font:inherit}#cursor{width:65%}</style>\n<h1>Recorded simulation replay</h1><div id="frame"></div><p id="time"></p><button id="play">Play</button> <input id="cursor" aria-label="Replay frame" type="range" min="0"><details><summary>Provenance</summary><pre id="provenance"></pre></details>\n<script id="replay-data" type="application/json">'+data+'''</script><script>const data=JSON.parse(document.getElementById('replay-data').textContent);let i=0,timer;const slider=document.getElementById('cursor');slider.max=data.frames.length-1;function show(){const f=data.frames[i];document.getElementById('frame').innerHTML=f.svg;document.getElementById('time').textContent='Time '+f.time+' s · revision '+f.revision;slider.value=i;}slider.oninput=()=>{i=Number(slider.value);show();};document.getElementById('play').onclick=()=>{if(timer){clearInterval(timer);timer=null;}else timer=setInterval(()=>{i=(i+1)%data.frames.length;show();},250);document.getElementById('play').textContent=timer?'Pause':'Play';};document.getElementById('provenance').textContent=JSON.stringify(data.provenance,null,2);show();</script></html>''').encode()


class CSVTableRenderer:
    def render(self, source_scene, rows, frames, provenance):
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
        return stream.getvalue().encode()


class ParquetTableRenderer:
    def render(self, source_scene, rows, frames, provenance):
        import pyarrow as pa
        import pyarrow.parquet as pq
        table=pa.Table.from_pylist(rows).replace_schema_metadata({b'zombie_provenance':canonical(provenance).encode()})
        output=pa.BufferOutputStream();pq.write_table(table,output,compression='zstd')
        return output.getvalue().to_pybytes()


class ExportService:
    """Pin export inputs, replay recorded samples and select a renderer strategy."""
    def __init__(self, *, renderers=None, visualization=None, history_factory=None):
        from .visualization import VisualizationService
        from .persistence import PersistenceBundleFactory
        self.renderers = renderers if renderers is not None else ExportRendererRegistry.builtins()
        self.visualization = visualization if visualization is not None else VisualizationService()
        self.history_factory = history_factory if history_factory is not None else PersistenceBundleFactory().open_history

    def prepare(self, manager,run_id,request):
        format=request.get('format','scene_png')
        if format not in self.renderers:raise ValueError('Unknown export format')
        history=manager.history(run_id)
        try:
            revision=history.revision;latest=history.state_at(revision=revision);frontier=exact_time(latest['time'])
            selected=exact_time(request.get('time',frontier));interval=request.get('interval',['0',str(frontier)])
            if not isinstance(interval,list) or len(interval)!=2:raise ValueError('Export interval requires start and end')
            start,end=map(exact_time,interval);spacing=exact_time(request.get('sample_interval','1'))
            if not 0<=start<=end<=frontier or not 0<=selected<=frontier:raise ValueError('Export times must lie within committed history')
            if spacing<=0 or (end-start)/spacing>2000:raise ValueError('Use a positive sample interval with at most 2001 frames')
            scene=self.visualization.project_state(history.state_at(time=selected,revision=revision),selected)
            scene=self.visualization.view_bundle(scene)['state']
            cohort=request.get('cohort','all')
            definition=None
            if cohort!='all':
                summaries=manager.cohorts(run_id,scene)
                definition=next((deepcopy(row['definition']) for row in summaries if cohort in {row['definition'].get('id'),row['definition'].get('name')}),None)
                if definition is None:raise ValueError('Unknown saved cohort')
                members=set(self.visualization.cohort_members(scene,definition));scene['agents']={key:value for key,value in scene['agents'].items() if key in members}
            provenance={'schema':'zombie-sim/export-v1','run_id':run_id,'revision':str(scene['revision']),'source_frontier_revision':str(revision),
                        'time':str(selected),'interval':[str(start),str(end)],'sample_interval':str(spacing),'cohort':cohort,'format':format}
            if definition is not None:provenance['cohort_definition']=definition
            return provenance,scene,history.reader_reference()
        finally:history.close()


    def render(self, provenance, source_scene, history_path, format):
        rows=[];frames=[]
        history=self.history_factory(history_path,read_only=True)
        try:
            t,end=map(exact_time,provenance['interval']);spacing=exact_time(provenance['sample_interval'])
            while t<=end:
                scene=self.visualization.project_state(history.state_at(time=t,revision=int(provenance['source_frontier_revision'])),t)
                if provenance.get('cohort_definition'):
                    members=set(self.visualization.cohort_members(scene,provenance['cohort_definition']));scene['agents']={key:value for key,value in scene['agents'].items() if key in members}
                rows.append({'time':str(t),**self.visualization.populations(scene)})
                if format=='replay_animation':frames.append({'time':str(t),'revision':str(scene['revision']),'svg':self.visualization.world_svg(scene,900)})
                t+=spacing
        finally:history.close()
        payload=self.renderers.render(format,source_scene,rows,frames,provenance)
        sidecar={'provenance':provenance,'source_scene':source_scene,'artifact_sha256':hashlib.sha256(payload).hexdigest(),
                 'bytes':len(payload),'sample_count':len(rows),'format':format}
        return payload,sidecar


def scene_png(scene,provenance):
    return ScenePNGRenderer().render(scene, (), (), provenance)

def chart_svg(rows,provenance):
    return SVGChartRenderer().render(None, rows, (), provenance)

def chart_png(rows,provenance):
    return PNGChartRenderer().render(None, rows, (), provenance)

def animation_html(frames,provenance):
    return ReplayRenderer().render(None, (), frames, provenance)

_default_exports = ExportService()


def prepare_export(manager,run_id,request):
    return _default_exports.prepare(manager,run_id,request)


def render_export(provenance,source_scene,history_path,format):
    return _default_exports.render(provenance,source_scene,history_path,format)


class ExportJobs:
    def __init__(self,manager, *, readers=None, executor=None):
        self.manager=manager;self.directory=manager.root/'exports';self.directory.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.pool=executor if executor is not None else ThreadPoolExecutor(max_workers=2,thread_name_prefix='simulation-export')
        from .read_tasks import ReadPool
        self.readers=readers if readers is not None else ReadPool(manager.root,size=2,name='exports');self.closing=False
        self.jobs={};self.gates={}
    def arm_pause(self,run_id):
        with self.lock:self.gates[run_id]=threading.Event()
    def release(self,run_id):
        with self.lock:
            gate=self.gates.pop(run_id,None)
            if gate:gate.set()
    def create(self,run_id,request):
        if self.closing:raise ValueError('Service is draining; new exports are disabled')
        provenance,scene,history_path=self.readers.call('prepare_export',run_id,request)
        format=provenance['format'];identifier=uuid.uuid4().hex
        job={'id':identifier,'run_id':run_id,'status':'PENDING','active_tasks':1,'format':format,
             'provenance':provenance,'source_scene':scene,'history_path':history_path,'cancel':threading.Event(),
             'artifact':self.directory/(identifier+'.'+FORMATS[format][0]),'sidecar':self.directory/(identifier+'.provenance.json')}
        with self.lock:
            if self.closing:raise ValueError('Service is draining; new exports are disabled')
            self.jobs[identifier]=job;job['future']=self.pool.submit(self._execute,job)
        return self.get(identifier)
    def _execute(self,job):
        from .application import ViewCancelled
        def check():
            if job['cancel'].is_set():raise CancelledExport()
        try:
            with self.lock:job['status']='RUNNING';gate=self.gates.get(job['run_id'])
            if gate:
                while not gate.wait(.05):check()
            check()
            payload,sidecar=self.readers.call('render_export',job['provenance'],job['source_scene'],job['history_path'],job['format'],cancel_event=job['cancel'])
            check()
            artifact_temp=job['artifact'].with_suffix('.partial');sidecar_temp=job['sidecar'].with_suffix('.partial.json')
            artifact_temp.write_bytes(payload);sidecar_temp.write_text(canonical(sidecar));check()
            artifact_temp.replace(job['artifact']);sidecar_temp.replace(job['sidecar'])
            with self.lock:
                check();job['status']='COMPLETED';job['bytes']=len(payload)
        except (CancelledExport,ViewCancelled):
            with self.lock:job['status']='CANCELLED'
        except Exception as error:
            with self.lock:job['status']='FAILED';job['error']=str(error)
        finally:
            with self.lock:
                if job['status']!='COMPLETED':
                    for path in (job['artifact'],job['sidecar'],job['artifact'].with_suffix('.partial'),job['sidecar'].with_suffix('.partial.json')):path.unlink(missing_ok=True)
                job['active_tasks']=0;job.pop('source_scene',None)
    def get(self,identifier):
        with self.lock:
            job=self.jobs[identifier]
            return {key:deepcopy(job[key]) for key in ('id','run_id','status','active_tasks','format','provenance','error','bytes') if key in job} | {
                'artifact_url':f'/api/export-jobs/{identifier}/artifact','provenance_url':f'/api/export-jobs/{identifier}/provenance'}
    def cancel(self,identifier):
        with self.lock:
            job=self.jobs[identifier]
            if job['status'] in {'COMPLETED','CANCELLED','FAILED'}:return self.get(identifier)
            job['cancel'].set();job['status']='CANCELLING';self.release(job['run_id']);future=job['future']
        try:future.result(timeout=15)
        except TimeoutError:pass
        return self.get(identifier)
    def path(self,identifier,sidecar=False):
        with self.lock:
            job=self.jobs[identifier]
            if job['status']!='COMPLETED':raise ValueError('Export is not complete')
            return job['sidecar' if sidecar else 'artifact']
    def start_draining(self):
        with self.lock:
            self.closing=True
            for job in self.jobs.values():
                if job['active_tasks'] and job['status'] not in {'COMPLETED','CANCELLED','FAILED'}:
                    job['cancel'].set();job['status']='CANCELLING'
            for gate in self.gates.values():gate.set()
        self.readers.start_draining()
    def close(self):
        self.start_draining()
        self.pool.shutdown(wait=True,cancel_futures=False)
        self.readers.close()
    def status(self):
        with self.lock:
            return {'active':sum(job['active_tasks'] for job in self.jobs.values()),'readers':self.readers.status()}


def register_export_routes(app,manager, *, jobs=None):
    from fastapi import Body
    from fastapi.responses import FileResponse
    service=jobs if jobs is not None else ExportJobs(manager);app.state.exports=service
    @app.post('/api/runs/{run_id}/exports')
    def create(run_id:str,body:dict=Body(...)):return service.create(run_id,body)
    @app.get('/api/export-jobs/{identifier}')
    def status(identifier:str):return service.get(identifier)
    @app.post('/api/export-jobs/{identifier}/cancel')
    def cancel(identifier:str):return service.cancel(identifier)
    @app.get('/api/export-jobs/{identifier}/artifact')
    def artifact(identifier:str):
        job=service.get(identifier);path=service.path(identifier)
        return FileResponse(path,media_type=FORMATS[job['format']][1],filename=path.name)
    @app.get('/api/export-jobs/{identifier}/provenance')
    def provenance(identifier:str):
        path=service.path(identifier,True);return FileResponse(path,media_type='application/json',filename=path.name)
    return service
