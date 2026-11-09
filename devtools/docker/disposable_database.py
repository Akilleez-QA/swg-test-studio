"""Strict identity checks for isolated cold-start Oracle fixtures."""
import re
from pathlib import Path


def validate(metadata, deployment, volume):
    match=re.fullmatch(r"(swg-cold-test-[a-f0-9]{8})_oracle26_data", volume or "")
    if not match:
        raise ValueError("Expected a uniquely named disposable cold-start volume")
    root=Path(deployment).resolve()
    if str(root).startswith('/mnt/') or not str(root).startswith('/tmp/') or root.name!=match.group(1):
        raise ValueError("Disposable schema inputs must use their matching Linux-native test root")
    labels=metadata.get('Config',{}).get('Labels') or {}
    if labels.get('com.docker.compose.project')!=match.group(1) or labels.get('whitengold.test.kind')!='cold-start':
        raise ValueError("Target lacks matching disposable cold-start identity labels")
    if metadata.get('Config',{}).get('Image')!='gvenzl/oracle-free:23.26.3-slim-faststart':
        raise ValueError("Unexpected isolated Oracle image")
    if not any(m.get('Type')=='volume' and m.get('Name')==volume and m.get('Destination')=='/opt/oracle/oradata'
               for m in metadata.get('Mounts',[])):
        raise ValueError("Target does not mount its exact disposable volume")
    if any(m.get('Name','').startswith('starwarsgalaxies_') for m in metadata.get('Mounts',[])):
        raise ValueError("Disposable database must not mount canonical storage")
    return volume
