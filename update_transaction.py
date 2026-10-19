"""Process locking, isolated calculation, and recoverable promotion of verified output."""
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

class UpdateBusy(RuntimeError):
    pass

class UpdateLock:
    def __init__(self,path): self.path=Path(path); self.handle=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=self.path.open('a+b')
        if self.path.stat().st_size==0: self.handle.write(b'0'); self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close();self.handle=None
            raise UpdateBusy('已有更新程序執行中，未啟動第二次運算。')
        return self
    def __exit__(self,*args):
        if self.handle:
            self.handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
            self.handle.close();self.handle=None

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2);handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)

def safe_remove(path,root):
    path=Path(path).resolve();work=(Path(root)/'work').resolve()
    if path==work or not path.is_relative_to(work): raise ValueError('Refusing cleanup outside update workspace')
    if path.is_dir(): shutil.rmtree(path)
    elif path.exists(): path.unlink()

def recover(root):
    root=Path(root);journal=root/'work/promotion.json'
    if not journal.exists(): return False
    state=json.loads(journal.read_text(encoding='utf-8'))
    backup=Path(state['backup']).resolve();stage=Path(state['stage']).resolve()
    work=(root/'work').resolve()
    if backup==work or stage==work or not backup.is_relative_to(work) or not stage.is_relative_to(work): raise ValueError('Invalid recovery paths')
    allowed={'data','reports','site','fantasy5_full_history.csv'}
    if any(e['name'] not in allowed for e in state['entries']): raise ValueError('Invalid recovery entry')
    if state['phase']!='committed':
        for item in reversed(state['entries']):
            name=item['name'];live=root/name;old=backup/name
            if old.exists():
                if live.exists():
                    displaced=backup/(name+'.incomplete')
                    os.replace(live,displaced)
                os.replace(old,live)
            elif not item['existed'] and not (stage/name).exists() and live.exists():
                os.replace(live,backup/(name+'.incomplete'))
    journal.unlink()
    # Keep the last backup for review; only incomplete staging is discarded here.
    safe_remove(stage,root)
    return True

def promote(stage,root,fail_after=None):
    stage=Path(stage);root=Path(root)
    names=['data','reports','site','fantasy5_full_history.csv']
    for name in names:
        if not (stage/name).exists(): raise RuntimeError('Verified output missing: '+name)
    backup=root/'work'/('rollback-'+uuid.uuid4().hex);backup.mkdir(parents=True)
    entries=[{'name':n,'existed':(root/n).exists()} for n in names]
    journal=root/'work/promotion.json'
    atomic_json(journal,{'phase':'moving','stage':str(stage.resolve()),'backup':str(backup.resolve()),'entries':entries})
    try:
        for index,item in enumerate(entries,1):
            name=item['name']
            if item['existed']: os.replace(root/name,backup/name)
            os.replace(stage/name,root/name)
            if fail_after==index: raise OSError('Injected promotion failure')
        atomic_json(journal,{'phase':'committed','stage':str(stage.resolve()),'backup':str(backup.resolve()),'entries':entries})
    except BaseException:
        recover(root)
        raise
    recover(root)
    # One previous good version is retained; old backup cleanup is bounded to this workspace.
    for old in (root/'work').glob('rollback-*'):
        if old!=backup: safe_remove(old,root)

def prepare_stage(root):
    root=Path(root);stage=root/'work'/('stage-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    for source in root.glob('*.py'): shutil.copy2(source,stage/source.name)
    for name in ('data','history_import','validation_sources'):
        source=root/name
        if source.exists(): shutil.copytree(source,stage/name,ignore=shutil.ignore_patterns('*-wal','*-shm'))
    db=root/'data/california_fantasy5.sqlite'
    if db.exists():
        with sqlite3.connect(db) as source,sqlite3.connect(stage/'data/california_fantasy5.sqlite') as target:
            source.backup(target)
    for name in ('fantasy5_full_history.csv','tiantianle-mobile-cloud-url.txt'):
        if (root/name).exists(): shutil.copy2(root/name,stage/name)
    return stage

def isolated_update(root,mode='realtime'):
    root=Path(root)
    with UpdateLock(root/'work/update.lock'):
        recover(root)
        stage=prepare_stage(root)
        status=root/'work/update_status.json'
        started=datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
        atomic_json(status,{'status':'running','started_at':started,'mode':mode})
        log=root/'logs/last_update.log';log.parent.mkdir(parents=True,exist_ok=True)
        try:
            with log.open('w',encoding='utf-8') as handle:
                environment=os.environ.copy()
                environment['TIANTIANLE_STAGE_ROOT']=str(stage.resolve())
                result=subprocess.run([sys.executable,'-u',str(stage/'system_update.py'),'--worker','--mode',mode],
                                      cwd=stage,env=environment,stdout=handle,stderr=subprocess.STDOUT,timeout=1200)
            print(log.read_text(encoding='utf-8',errors='replace'),flush=True)
            if result.returncode: raise RuntimeError(f'隔離更新失敗（{result.returncode}），上一份有效戰報已保留。')
            promote(stage,root)
            atomic_json(status,{'status':'passed','started_at':started,'finished_at':datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds'),'mode':mode})
        except BaseException as exc:
            atomic_json(status,{'status':'failed','started_at':started,'mode':mode,'error':str(exc),'last_good_report_preserved':True})
            raise
        finally:
            if stage.exists(): safe_remove(stage,root)
