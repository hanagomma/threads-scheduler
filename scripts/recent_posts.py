"""쓰레드 계정에 실제로 올라간 최근 글을 확인한다 (글은 올리지 않음)."""
import os
import sys

import requests

token = os.environ.get("THREADS_ACCESS_TOKEN") or sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")
r = requests.get("https://graph.threads.net/v1.0/me/threads",
                 params={"fields": "id,timestamp,permalink", "limit": 15, "access_token": token}, timeout=30)
if not r.ok:
    sys.exit(f"{r.status_code} {r.text[:300]}")
for p in r.json().get("data", []):
    print(p.get("timestamp"), p.get("id"), p.get("permalink"))  # 공개 로그라 글 내용은 출력하지 않음
