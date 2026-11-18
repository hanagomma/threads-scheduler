"""답글 권한 확인 (글은 올리지 않음). 답글 컨테이너만 만들어 보고 게시(publish)는 하지 않는다.
만들어진 컨테이너는 게시하지 않으면 Meta 쪽에서 저절로 만료된다."""
import os
import sys

import requests

token = os.environ.get("THREADS_ACCESS_TOKEN") or sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")
target = os.environ.get("REPLY_TO") or sys.exit("REPLY_TO 가 없습니다.")
r = requests.post("https://graph.threads.net/v1.0/me/threads",
                  data={"media_type": "TEXT", "text": "권한 확인", "reply_to_id": target, "access_token": token},
                  timeout=30)
print("답글 컨테이너 생성:", r.status_code, "OK" if r.ok else r.text[:300])
sys.exit(0 if r.ok else 1)
