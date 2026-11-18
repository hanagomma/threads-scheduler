"""토큰이 살아 있는지 확인한다 (글은 올리지 않음). 결과: 계정 이름."""
import os
import sys

import requests

token = os.environ.get("THREADS_ACCESS_TOKEN") or sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")
r = requests.get("https://graph.threads.net/v1.0/me",
                 params={"fields": "id,username", "access_token": token}, timeout=30)
print(r.status_code, r.json())
r.raise_for_status()
