"""Compatibility entry: branch replacement and Pages mode mutation are retired."""
from pathlib import Path
BASE=Path(__file__).resolve().parent

def approved_files():
    return [(p.relative_to(BASE/'site').as_posix(),p) for p in (BASE/'site').rglob('*')
            if p.is_file() and not any(s in p.name.lower() for s in ('token','secret','credential','password'))]

def main():
    from cloud_update_request import main as request_update
    request_update()

if __name__=='__main__': main()
