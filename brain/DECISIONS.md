# Decisions

이 문서는 검증된 결정만 누적한다. 임시 가정은 적지 않는다.

## Confirmed

- 자동화는 전체 리팩터링보다 최소 patch를 우선한다.
- target file 밖 수정은 reviewer gate에서 차단한다.
- runtime 한글 문자열 깨짐은 실제 서비스 버그로 보고 release blocker로 취급한다.
- upload 이후 restart 또는 browser verification이 실패하면 remote restore가 필요하다.
- 큰 작업은 페이지 기준이 아니라 더 작은 기능 단위 task로 쪼개야 안정적이다.
