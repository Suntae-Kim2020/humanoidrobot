# 골드셋 검증 프로토콜 (Step 2)

목적: `schema.json` + `extract_prompt.md`로 뽑은 LLM 추출의 **신뢰도**를 측정하고
스키마를 확정한 뒤 전수(수천 편)로 확장.

## 절차
1. **표본 추출**: 정제된 CN/KR/US 코퍼스에서 층화 무작위 100편(연도·주제·국가 균형).
2. **골드 라벨링**: 사람(또는 Claude 2차 독립 추출)이 100편을 손으로 라벨링 → `gold.jsonl`.
3. **LLM 추출**: `extract_abstracts.py --limit 100`로 동일 100편 추출 → `pred.jsonl`.
4. **일치도 측정**: 필드별 정확도/일치율(범주형=exact match, 다중라벨=Jaccard).
   - 목표: 핵심 필드(task, contribution_type, platform_type) ≥ 0.85 일치.
5. **오류 분석 → 프롬프트/스키마 수정 → 재측정** (1~2회 반복).
6. 통과 시 전수 실행.

## 파일럿에서 확인된 것 (수기 골드셋 2라운드)
- 스키마 필드가 실제 초록에서 안정적으로 추출됨(방법·플랫폼·데이터생성·기여유형).
- **3중 오염을 순차 발견 → 3중 게이트로 방어:**
  1. 학부 캡스톤/STS 에세이 → 텍스트/타입 필터.
  2. 비로봇(고인류학 "bipedalism", 해부, 생명윤리, 애니메이션) → **corpus 빌드의 topic domain 게이트**(`primary_topic.domain='Physical Sciences'`) + 스키마 `is_humanoid_robotics`.
  3. 주제는 휴머노이드지만 **경영·정책·마케팅 에세이**(Tesla 공급망, 호텔 챗봇, 폐기물 정책, 홍보 백서)가 "Engineering" 필드로 통과 → 스키마 `is_engineering_research` 게이트로 배제(SQL로는 구분 불가).
- **분석 필터 규칙**: `is_humanoid_robotics AND is_engineering_research` 인 논문만 집계.
- 초기 방법론 신호(정제 후): **US=VLA/체현AI 프론티어, CN·KR=제어이론·최적화·하드웨어**, 신규 데이터셋 생성 거의 0.

## 이 환경의 제약
현재 작업 환경에는 `ANTHROPIC_API_KEY`가 없어 대규모 자동 추출을 직접 실행할 수 없다.
`extract_abstracts.py`는 **사용자가 본인 키로 실행**하도록 재현 가능하게 작성됨.
소량 골드셋은 대화 세션에서 Claude가 직접 추출·검증 가능.
