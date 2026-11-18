"""게시 시각이 지난 pending 글을 Threads API로 올리고 posts.json을 갱신한다.

환경 변수: THREADS_ACCESS_TOKEN (필수), DRY_RUN=1 이면 실제로 올리지 않음.
한 번에 최대 MAX_PER_RUN 개만 올려서, 밀린 글이 한꺼번에 쏟아지지 않게 한다.

발행 누락 방지 (11/18 개편):
- 실행 하나가 최대 KEEPER_MINUTES 분 동안 깨어 있으면서 예약 시각마다 바로 올린다.
  끝날 때 pending 글이 남아 있으면 워크플로가 다음 실행을 스스로 건다(post.yml 마지막 단계).
  그래서 외부 알람(cron-job.org 등) 없이도 실행이 끊기지 않고 이어진다.
- 실행이 끊겼다 다시 살아나서 글이 RESLOT_AFTER_MIN 분 넘게 밀려 있으면, 건너뛰지 않고
  남은 pending 글 전체를 순서대로 다음 게시 칸(아침 07:00~08:50, 저녁 19:00~22:50)으로 민다.
  (예전에는 6시간 넘게 밀린 글을 skipped 처리해서 글이 사라졌다.)
- 게시가 실패하면 10분 뒤 다시 시도하고, 실패가 있었던 실행은 끝날 때 실패로 표시해
  GitHub가 알림 메일을 보내게 한다.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
# 글 내용(posts.json)은 비공개 저장소 threads-content 에 있다. 워크플로가 content/ 폴더로 받아 온다.
CONTENT = Path(os.environ.get("CONTENT_DIR") or ROOT)
POSTS = CONTENT / "posts.json"
API = "https://graph.threads.net/v1.0"
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN") or 2)
GAP_SEC = 60  # 한 번 실행에서 여러 개 올릴 때 글 사이 간격
RESLOT_AFTER_MIN = 15  # 이보다 오래 밀린 글이 있으면 남은 글 전체를 다음 칸으로 민다
RETRY_MIN = 10  # 게시 실패 시 재시도 간격
SLOT_HOURS_KST = (7, 8, 19, 20, 21, 22)  # 게시 칸: 이 시각의 00,10,...,50분
KST = timezone(timedelta(hours=9))
POST_HOURS_KST = {7, 8, 9, 19, 20, 21, 22, 23}  # 이 시간대(KST)에만 게시. GitHub 실행이 밀려 새벽에 도는 경우 방지


def publish(token: str, text: str, reply_to: str | None = None) -> str:
    """글 하나를 올리고 media id 를 돌려준다. reply_to 가 있으면 그 글의 답글로 올린다."""
    data = {"media_type": "TEXT", "text": text, "access_token": token}
    if reply_to:
        data["reply_to_id"] = reply_to
    r = requests.post(f"{API}/me/threads", data=data, timeout=30)
    if not r.ok:  # Meta 오류 메시지를 남겨야 원인을 알 수 있다 (토큰 값은 응답에 없음)
        raise RuntimeError(f"{r.status_code} {r.text[:250]}")
    creation_id = r.json()["id"]
    time.sleep(10)  # 컨테이너 준비 대기 (Meta 권장)
    for attempt in range(3):
        r = requests.post(f"{API}/me/threads_publish",
                          data={"creation_id": creation_id, "access_token": token}, timeout=30)
        if r.ok:
            return r.json()["id"]
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"publish {r.status_code} {r.text[:250]}")


def git(*args):
    subprocess.run(["git", *args], cwd=CONTENT, check=True)


def pull_latest():
    """PUSH_EACH=1 이면 저장소의 최신 posts.json 을 받아온다 (실행 중에 새로 추가된 예약을 반영)."""
    if os.environ.get("PUSH_EACH") != "1":
        return
    try:
        git("pull", "-q", "--rebase", "origin", "main")
    except subprocess.CalledProcessError as e:
        print(f"[warn] 최신 상태 받기 실패: {e}", flush=True)


def load():
    return json.loads(POSTS.read_text(encoding="utf-8"))


def record(pid: int, msg: str, drop=(), **fields):
    """글 하나의 상태만 posts.json 에 반영한다."""
    def change(data):
        for q in data["posts"]:
            if q["id"] == pid:
                for k in drop:
                    q.pop(k, None)
                q.update(fields)
    save(change, msg)


def save(change, msg: str):
    """실행 중 다른 곳에서 예약이 추가·변경됐을 수 있으므로, 메모리의 목록 전체를 덮어쓰지 않고
    최신 파일을 다시 읽어 change(data) 로 필요한 부분만 고친 뒤 저장한다. PUSH_EACH=1 이면 바로 커밋·푸시한다."""
    push = os.environ.get("PUSH_EACH") == "1"
    pull_latest()
    data = load()
    change(data)
    POSTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not push:
        return
    try:
        git("commit", "-q", "-m", msg, "posts.json")
        for attempt in range(3):
            try:
                git("push", "-q")
                return
            except subprocess.CalledProcessError:
                git("pull", "-q", "--rebase", "origin", "main")
    except subprocess.CalledProcessError as e:  # 푸시 실패는 마지막 Save status 단계에서 다시 시도
        print(f"[warn] 상태 푸시 실패: {e}", flush=True)


def post_batch(data, token, dry):
    """지금 시각까지 밀린 pending 글을 MAX_PER_RUN 개까지 올린다. 반환: (올린 개수, 변경 여부)"""
    now = datetime.now(timezone.utc)
    posted = 0
    changed = False
    for p in sorted(data["posts"], key=lambda x: x["scheduled_at"]):
        if p["status"] != "pending":
            continue
        at = datetime.fromisoformat(p["scheduled_at"])
        if at > now:
            break
        if posted >= MAX_PER_RUN:
            break
        if now.astimezone(KST).hour not in POST_HOURS_KST:
            print(f"[wait] 게시 시간대가 아니라서 보류 (KST {now.astimezone(KST):%H:%M})")
            break
        if posted and not dry:
            time.sleep(GAP_SEC)
        if dry:
            print(f"[dry] #{p['id']} {p['scheduled_at']}")  # 공개 로그라 글 내용은 출력하지 않음
            posted += 1
            continue
        try:
            # 연재 글: 첫 글(text) + 답글(replies)을 같은 칸에 이어서 올린다. 답글은 바로 앞 글에 단다.
            # 중간에 실패하면 올라간 것까지 기록해 두고(media_id, reply_ids), 다음 시도에서 남은 답글부터 잇는다.
            replies = p.get("replies") or []
            media_id = p.get("media_id")
            if not media_id:
                media_id = publish(token, p["text"])
                print(f"[ok] #{p['id']} -> {media_id}", flush=True)
                done = not replies
                record(p["id"], f"posted #{p['id']}", drop=("last_error",) if done else (),
                       status="posted" if done else "pending", media_id=media_id,
                       posted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            reply_ids = list(p.get("reply_ids") or [])
            for i in range(len(reply_ids), len(replies)):
                time.sleep(5)
                rid = publish(token, replies[i], reply_to=reply_ids[-1] if reply_ids else media_id)
                reply_ids.append(rid)
                print(f"[ok] #{p['id']} 답글 {i + 1}/{len(replies)} -> {rid}", flush=True)
                record(p["id"], f"reply #{p['id']} {i + 1}/{len(replies)}", reply_ids=reply_ids)
            if replies:
                record(p["id"], f"posted #{p['id']} (답글 {len(replies)}개)", drop=("last_error",), status="posted")
            p["status"] = "posted"
        except Exception as e:  # 실패는 기록만 하고 다음 실행 때 다시 시도
            print(f"[fail] #{p['id']} {e}", flush=True)
            record(p["id"], f"failed #{p['id']}", last_error=str(e)[:300])
            changed = True
            posted = -1  # 실패 표시
            break
        changed = True
        posted += 1
    return posted, changed


def next_slot(t: datetime) -> datetime:
    """t 이후(같은 시각 포함) 첫 게시 칸 (KST 10분 단위, SLOT_HOURS_KST 안)."""
    k = t.astimezone(KST).replace(second=0, microsecond=0)
    if t.astimezone(KST) > k:
        k += timedelta(minutes=1)
    k += timedelta(minutes=(-k.minute) % 10)
    while k.hour not in SLOT_HOURS_KST:
        k += timedelta(minutes=10)
    return k


def plan_reslot(posts, now: datetime):
    """RESLOT_AFTER_MIN 분 넘게 밀린 pending 글이 있으면, pending 글 전체를 순서대로 다음 칸부터 다시 배정한다.
    원래 시각이 더 늦은 글은 그 시각을 지킨다(일부러 비워 둔 날짜 유지). 반환: {id: 새 scheduled_at}"""
    pend = sorted((p for p in posts if p["status"] == "pending" and not p.get("media_id")),  # 답글 이어 올리는 중인 글은 제외
                  key=lambda p: (p["scheduled_at"], p["id"]))
    if not pend or now - datetime.fromisoformat(pend[0]["scheduled_at"]) <= timedelta(minutes=RESLOT_AFTER_MIN):
        return {}
    moves, cursor = {}, next_slot(now)
    for p in pend:
        t = max(cursor, next_slot(datetime.fromisoformat(p["scheduled_at"])))
        new = t.strftime("%Y-%m-%dT%H:%M:00+09:00")
        if new != p["scheduled_at"]:
            moves[p["id"]] = new
        cursor = next_slot(t + timedelta(minutes=10))
    return moves


def reslot(data, now):
    moves = plan_reslot(data["posts"], now)
    if not moves:
        return False
    first = min(moves.values())
    print(f"[reslot] 밀린 글 {len(moves)}개를 다음 칸({first})부터 다시 배정", flush=True)

    def change(d):
        for q in d["posts"]:
            if q["id"] in moves and q["status"] == "pending":
                q.setdefault("original_at", q["scheduled_at"])
                q["scheduled_at"] = moves[q["id"]]
        d["posts"].sort(key=lambda q: q["scheduled_at"])
    save(change, f"밀린 글 {len(moves)}개 다음 칸으로 재배정 ({first}~)")
    return True


def main():
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    dry = os.environ.get("DRY_RUN") == "1"
    if not token and not dry:
        sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")
    deadline = datetime.now(timezone.utc) + timedelta(minutes=int(os.environ.get("KEEPER_MINUTES") or 0))
    failed = False

    while True:
        pull_latest()
        data = load()  # 매번 최신 목록을 다시 읽는다 (실행 중 추가된 예약 반영, 덮어쓰기 방지)
        if dry:
            print("[dry] 재배정 계획:", plan_reslot(data["posts"], datetime.now(timezone.utc)))
            post_batch(data, token, dry)
            break
        if reslot(data, datetime.now(timezone.utc)):
            data = load()
        posted, _ = post_batch(data, token, dry)
        now = datetime.now(timezone.utc)
        if posted < 0:
            failed = True
            nxt = now + timedelta(minutes=RETRY_MIN)
        else:
            data = load()
            due = [datetime.fromisoformat(p["scheduled_at"]) for p in data["posts"] if p["status"] == "pending"]
            if not due:
                print("[done] 남은 예약 없음", flush=True)
                break
            nxt = max(min(due), now + timedelta(seconds=30))
        if nxt > deadline:
            # 다음 글이 이번 실행 시간 밖이면, 시간 끝까지 깨어 있다가 끝낸다 → 워크플로가 다음 실행을 건다.
            # (바로 끝내면 실행이 몇 초마다 연달아 생기는 무한 반복이 된다)
            print(f"[keeper] 다음 글 {nxt.astimezone(KST):%m/%d %H:%M} 은 다음 실행이 올림. "
                  f"{deadline.astimezone(KST):%H:%M} 까지 대기", flush=True)
            time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()))
            break
        time.sleep(max(0, (nxt - datetime.now(timezone.utc)).total_seconds()) + 5)

    (ROOT / ".keeper_ok").write_text("ok")  # 정상 종료 표시 (워크플로가 다음 실행을 바로 걸지 판단)
    if failed:
        sys.exit("이번 실행 중 게시 실패가 있었음 (posts.json last_error 확인)")


if __name__ == "__main__":
    main()
