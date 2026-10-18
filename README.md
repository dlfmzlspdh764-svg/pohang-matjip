# 포항 남구 맛집 PWA
- index.html / data.json / manifest.webmanifest / sw.js : 정적 PWA (어떤 정적 호스팅에 올려도 동작)
- seeds.json : 대상 식당 목록(네이버 플레이스 ID, 태그, X 검색어)
- update.py : 매주 실행 → 네이버 플레이스에서 리뷰/블로그 수·메뉴·영업시간·사진 재수집, X 언급 수(X_BEARER_TOKEN 있을 때) 재측정, 순위 재계산 → data.json
- discover.py : 필터 칩(술집/횟집/뒷고기/직장인 가성비) 후보를 네이버 플레이스 검색으로 찾아 seeds.json에 추가
- new_openings.py : 신규 오픈 음식점 탐지 → new_openings.json, 본 목록은 new_openings_seen.json
예) 매주 월요일 9시: `0 9 * * 1 cd /workspace/pohang-app && python3 update.py && python3 new_openings.py`
사진은 네이버 플레이스의 '업체 등록 사진'을 480px 썸네일로 저장한 것 (출처 표기). 공개 배포 시 저작권은 각 업체에 있음.
