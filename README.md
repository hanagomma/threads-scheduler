# 쓰레드 자동 게시

정해진 시간에 Threads 공식 API로 글을 올리는 GitHub Actions 프로그램이에요.
글 내용과 예약 목록은 별도의 비공개 저장소에 두고, 실행할 때만 받아 와요. 이 저장소에는 글 내용이 없어요.

- `scripts/post_due.py` : 예약 시각이 된 글을 게시. 밀린 글은 건너뛰지 않고 다음 칸으로 민다.
- `scripts/import_drafts.py` : 원고 파일 → 예약 목록
- `scripts/check_token.py`, `scripts/recent_posts.py` : 토큰 확인, 최근 게시 확인 (글 안 올림)
- `scripts/refresh_token.py` + `refresh-token.yml` : 토큰 60일 만료 전 자동 연장

필요한 Secrets: `THREADS_ACCESS_TOKEN`, `GH_PAT`(토큰 연장용), `CONTENT_TOKEN`(비공개 저장소 읽기·쓰기)
