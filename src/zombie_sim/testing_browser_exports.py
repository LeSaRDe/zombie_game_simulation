"""Decode actual downloaded export files and their integrity-bound provenance."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zlib


def read_artifact(artifact,run_aliases=None):
    path=Path(artifact['path']);payload=path.read_bytes()
    sidecar=json.loads(Path(artifact['provenance_path']).read_text())
    if hashlib.sha256(payload).hexdigest()!=sidecar['artifact_sha256'] or len(payload)!=sidecar['bytes']:
        raise ValueError('Downloaded artifact does not match its provenance checksum')
    format=sidecar['format'];decoded={}
    if format.endswith('_png'):
        if payload[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Artifact is not a PNG')
        offset=8;compressed=bytearray();metadata={}
        while offset<len(payload):
            length=struct.unpack('!I',payload[offset:offset+4])[0];kind=payload[offset+4:offset+8];data=payload[offset+8:offset+8+length]
            if zlib.crc32(kind+data)&0xffffffff!=struct.unpack('!I',payload[offset+8+length:offset+12+length])[0]:raise ValueError('PNG chunk checksum mismatch')
            if kind==b'IHDR':decoded['width'],decoded['height']=struct.unpack('!II',data[:8])
            if kind==b'IDAT':compressed.extend(data)
            if kind==b'tEXt' and data.startswith(b'Description\0'):metadata=json.loads(data.split(b'\0',1)[1])
            offset+=length+12
        pixels=zlib.decompress(compressed)
        if len(pixels)!=(decoded['width']*3+1)*decoded['height']:raise ValueError('PNG scanline length mismatch')
        if metadata.get('run_id')!=sidecar['provenance']['run_id'] or metadata.get('time')!=sidecar['provenance']['time']:raise ValueError('PNG metadata does not match provenance')
        decoded['decoded_pixel_bytes']=len(pixels)
    elif format=='chart_svg':
        root=ET.fromstring(payload);decoded['root']=root.tag;decoded['series']=len(root.findall('.//{http://www.w3.org/2000/svg}polyline'))
        metadata=json.loads(root.find('{http://www.w3.org/2000/svg}metadata').text)
        if metadata!=sidecar['provenance']:raise ValueError('SVG metadata does not match provenance')
    elif format=='table_csv':
        decoded['rows']=list(csv.DictReader(io.StringIO(payload.decode())))
        if not decoded['rows'] or 'time' not in decoded['rows'][0]:raise ValueError('CSV contains no sampled population rows')
    elif format=='table_parquet':
        import pyarrow.parquet as pq
        table=pq.read_table(io.BytesIO(payload));decoded['rows']=table.to_pylist()
        if json.loads(table.schema.metadata[b'zombie_provenance'])!=sidecar['provenance']:raise ValueError('Parquet metadata does not match provenance')
    elif format=='replay_animation':
        match=re.search(r'<script id="replay-data" type="application/json">(.*?)</script>',payload.decode(),re.S)
        if not match:raise ValueError('Replay contains no actual frame data')
        data=json.loads(match.group(1));decoded['frame_count']=len(data['frames']);decoded['frame_times']=[frame['time'] for frame in data['frames']]
        for frame in data['frames']:ET.fromstring(frame['svg'])
        if data['provenance']!=sidecar['provenance'] or not data['frames']:raise ValueError('Replay provenance or frames are invalid')
    else:raise ValueError('Unsupported artifact format')
    provenance=dict(sidecar['provenance']);aliases=run_aliases or {}
    if provenance['run_id'] in aliases:provenance['run_alias']=aliases[provenance['run_id']]
    else:
        provenance['run_alias']=next((alias for alias,identifier in aliases.items() if identifier==provenance['run_id']),provenance['run_id'])
    from .testing import normalize_snapshot
    return {'bytes':len(payload),'format':format,'provenance':provenance,'source_scene':normalize_snapshot(sidecar['source_scene']),'decoded':decoded}
