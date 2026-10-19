"""Request the sole cloud pipeline; a queued request is not a deployment."""
from publish_cloud_main_source import REPO,TOKEN_FILE,request_json

def request_update(token=None):
    if token is None:
        if not TOKEN_FILE.exists(): raise RuntimeError('找不到既有雲端登入憑證，未變更雲端或本機資料。')
        token=TOKEN_FILE.read_text(encoding='utf-8').strip()
    if not token: raise RuntimeError('雲端登入憑證為空，未執行發布。')
    request_json(f'repos/{REPO}/actions/workflows/tiantianle-cloud-auto-update.yml/dispatches',
                 token,data={'ref':'main'},method='POST')
    return f'https://github.com/{REPO}/actions/workflows/tiantianle-cloud-auto-update.yml'

def main():
    url=request_update()
    print('已送出雲端更新要求；只有重算、驗證、部署全部通過才會更新手機戰報。')
    print('完成前維持上一份有效戰報。執行狀態：'+url)

if __name__=='__main__': main()
