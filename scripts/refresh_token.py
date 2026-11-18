"""60일짜리 토큰을 연장해 새 토큰을 표준 출력으로 내보낸다 (발급 24시간 이후부터 가능)."""
import os
import sys

import requests

token = os.environ.get("THREADS_ACCESS_TOKEN") or sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")
r = requests.get("https://graph.threads.net/refresh_access_token",
                 params={"grant_type": "th_refresh_token", "access_token": token}, timeout=30)
r.raise_for_status()
body = r.json()
print(body["access_token"])
print(f"expires_in={body.get('expires_in')}", file=sys.stderr)
