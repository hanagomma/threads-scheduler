"""원고 파일(drafts/*.txt)을 posts.json 예약 목록으로 옮긴다.

원고 형식:
    @@ 2026-10-23 08:30        <- 이 묶음의 첫 글 게시 시각 (KST)
    첫 번째 글
    ---
    두 번째 글                  <- 앞 글 + INTERVAL_MIN 분
    @@ 2026-10-23 20:00        <- 다음 묶음
    ...

사용법: CONTENT_DIR=../threads-content python scripts/import_drafts.py ../threads-content/drafts/파일.txt [--interval 10]
같은 시각·같은 본문의 글이 이미 있으면 건너뛴다.
"""
import argparse
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = Path(os.environ.get("CONTENT_DIR") or ROOT) / "posts.json"  # 비공개 threads-content 의 posts.json
MAX_LEN = 500  # Threads 텍스트 글자 수 한도


def parse(path: Path, interval: int):
    items = []
    for block in re.split(r"^@@\s*", path.read_text(encoding="utf-8"), flags=re.M):
        block = block.strip()
        if not block:
            continue
        head, _, body = block.partition("\n")
        start = datetime.strptime(head.strip(), "%Y-%m-%d %H:%M")
        texts = [t.strip() for t in re.split(r"^---\s*$", body, flags=re.M) if t.strip()]
        for i, text in enumerate(texts):
            if len(text) > MAX_LEN:
                raise SystemExit(f"500자 초과: {head} 묶음 {i + 1}번째 글 ({len(text)}자)")
            at = start + timedelta(minutes=interval * i)
            items.append({"scheduled_at": at.strftime("%Y-%m-%dT%H:%M:00+09:00"), "text": text})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--interval", type=int, default=10)
    args = ap.parse_args()

    data = json.loads(POSTS.read_text(encoding="utf-8")) if POSTS.exists() else {"posts": []}
    seen = {(p["scheduled_at"], p["text"]) for p in data["posts"]}
    next_id = max((p["id"] for p in data["posts"]), default=0) + 1

    added = 0
    for item in parse(Path(args.draft), args.interval):
        if (item["scheduled_at"], item["text"]) in seen:
            continue
        data["posts"].append({"id": next_id, **item, "status": "pending"})
        next_id += 1
        added += 1

    data["posts"].sort(key=lambda p: p["scheduled_at"])
    POSTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{added}개 추가, 전체 {len(data['posts'])}개")


if __name__ == "__main__":
    main()
