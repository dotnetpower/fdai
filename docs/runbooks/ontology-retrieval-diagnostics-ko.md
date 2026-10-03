---
translation_of: ontology-retrieval-diagnostics.md
translation_source_sha: 6c1b75c68119bc14dccca39c87c9c7d9abe0b912
translation_revised: 2026-10-03
---

# 온톨로지 검색 진단

이 합성 데이터셋으로 인스턴스 후보 검색을 진단한 뒤 런타임 활성화를 검토하세요.
데이터셋, 오프라인 재생, 진단 통과만으로 운영 품질 자격이나 실행 권한을 얻지는 않습니다.

## 파일

| 파일 | 용도 |
|------|------|
| [instance-corpus.v1.json](../../eval/ontology-retrieval/instance-corpus.v1.json) | 네 ObjectType에 걸친 객체 24개의 고정된 테스트 자료입니다. |
| [instance-calibration.v1.json](../../eval/ontology-retrieval/instance-calibration.v1.json) | 과거의 24문항 보정 자료입니다. 질문과 정답을 보존합니다. |
| [instance-calibration.v2.json](../../eval/ontology-retrieval/instance-calibration.v2.json) | v1 보정 문항을 모두 변경 없이 포함한 64문항 확장 보정 자료입니다. |
| [instance-holdout.v1.json](../../eval/ontology-retrieval/instance-holdout.v1.json) | 이미 사용한 홀드아웃입니다. 근거는 보존하되 튜닝이나 새 자격 검증에 사용하지 않습니다. |

v2 보정 자료에는 단일 대상 정답 32개, 복수 대상 정답 8개와 일치 대상이 없는 문항 24개가
있습니다. 각 언어의 단일 대상 문항은 유형별 서로 다른 대상 네 개를 포함하며, 측정하는
모든 코호트 지표에 최소 네 표본을 제공합니다. 별도 문맥의 에이전트가 원본 객체와 선언을
기준으로 64개 라벨을 모두 검토했습니다. 처음에 모호했던 대체 조건 지시 두 개는 측정 전에
수정했습니다. 이는 라벨 검토일 뿐이며, 합성 자료가 운영 대표성이나 사람 승인을 입증하지는
않습니다. 자격과 관련된 메타데이터 플래그 두 개는 모두 `false`로 유지합니다.

## 홀드아웃을 열지 않고 보정 평가 실행

`prepare_ontology_retrieval_campaign`과 `execute_ontology_retrieval_campaign`에
`calibration_only=True`, `holdout_cases=()`를 전달하세요. v2 보정 문항, 실제 정규 문서
빌드, 권한 검증 게이트웨이, 격리된 저장소와 정확히 검토된 ResourceType 용어를 제공합니다.
독립 보정 실행은 임베딩 전에 정책의 모든 코호트와 표본 하한을 확인합니다.

입력 식별자는 문항 순서, 라벨, 원본 문서와 두 정책을 포함합니다. 예상 임베딩 요청 상한은
문서 28개와 질문 64개를 합한 92회입니다. 기존 실행 한도인 128회, 전체 600초, 준비 120초,
호출당 5초는 유지합니다. 준비와 원본 및 모델 검증은 전체 평가 실행과 같은 경로를 사용합니다.

보정 결과는 `report.campaign.calibration.passed`로 확인하세요. 보정 전용 보고서에는
홀드아웃이 없으므로, 보정 평가가 통과해도 전체 평가의 `passed`는 `False`입니다.
이후 자격 검증에는 새로 고정하고 독립 검토한 별도의 홀드아웃을 사용하세요.

## 벡터를 비공개로 보존하고 재생

별도로 승인된 실제 진단에서는
`OntologyEvaluationEvidence(new_private_path, source_commit=attested_sha, retain_vectors=True)`를
선택하세요. 벡터 보존은 명시적으로 선택해야 하며 기본 기록기는 벡터를 보존하지 않습니다.
대상 확인, 동의, 비공개 저장소와 정리는 계속 호출자가 책임집니다.

각 임베딩이 완료되면 정확한 UTF-8 입력의 다이제스트, 모델 식별 정보, 차원, 호출 번호와
검증된 벡터를 기록합니다. 이 기록에 입력 본문은 복사하지 않습니다. 다만 벡터도 파생
데이터이므로 Git 밖의 비공개 근거로 보존하세요. 기록기는 권한 `0600`으로 파일을 배타적으로
생성하고 다음 호출 전에 결과를 디스크에 반영합니다. 기록당 4 MiB, 파일당 16 MiB 한도는
유지하며, 벡터 보존을 선택한 128회 제한 실행은 최대 262개 기록을 허용합니다.

`OntologyEvaluationReplayEmbedder.from_evidence`에 예상 전체 파일 SHA-256 다이제스트
(`sha256:<hex>`), 전체 소스 커밋과 `(space_id, model_version, dimension)` 튜플을 전달하세요.
새로운 격리 상태와 변경되지 않은 원본 문서를 준비하고 같은 실행기에 이 어댑터를 제공합니다.
재생은 호출 의도와 결과가 짝을 이루고 모델 식별 정보가 일치하는 완성된 비공개 일반 파일만
받습니다. 벡터 누락, 입력 바이트 변경, 손상된 기록이나 고정 식별자 불일치는 제공자 호출로
대체하지 않고 중단합니다. 오프라인 출력을 다시 기록해 원래 수집 출처를 갱신할 수는 없습니다.

보고서는 `embedding_source="offline_replay"`와 `caller_supplied`를 구분하고
`replay_evidence_digest`를 보존합니다. 재생 시 `embedding_calls`는 실제 제공자 호출이
아니라 인터페이스 요청 횟수입니다. `caller_supplied`만으로 실제 제공자 실행을 증명할 수도
없습니다. 파일과 모델 식별자는 일관성을 검증할 뿐, 제공자 진위, 대표성이나 활성화 권한을
입증하지 않습니다.

## 형식화된 조건으로 후보 포함 여부 진단

선택적으로 사용하는 `OntologyCandidateSelection` 경로는 이미 제안된 조건을 현재 권한이
적용된 ObjectSet 조회로 평가합니다. 자연어 단어를 해석하거나 모델을 호출하지 않습니다.
제안의 의미는 계속 호출자가 책임집니다. 조건과 일치한다는 사실만으로 질문을 올바르게
이해했다고 볼 수는 없습니다.

`OntologyCandidateSelection.bind`로 제안을 연결하고 준비된 판독기의
`search(selection=...)`에 전달하세요. 연결 정보에는 정확한 질문, 매니페스트와 스냅샷이
포함됩니다. 한 절 안의 조건은 AND로 결합하고, 절별 결과는 합집합으로 모아 중복 식별자를
제거합니다. 판독기는 조회를 기다리기 전에 중첩된 피연산자의 복사본을 고정합니다.

- 제안은 32 KiB, 절 8개, 절당 조건 16개와 명시적 ID 100개로 제한합니다.
  빈 제안과 한도를 넘은 입력은 잘라서 사용하지 않고 차단합니다.
- principal, 목적, 기준 시점, 관계 제외와 ObjectSet의 1,000행 한도는 서비스가 정합니다.
  조건식 속성에 대한 접근에는 게이트웨이의 기존 권한 검사를 적용합니다.
- 각 조회 범위는 완전하고 최신이어야 하며 숨겨진 식별자가 없어야 합니다. 표시 한도 밖의
  일치 객체도 포함하여 모든 일치 객체의 정규 내용이 준비된 원본과 같아야 합니다.
- 판독기는 정규 문서 ID 순서로 정렬하고 표시할 객체의 권한을 다시 확인합니다. 결과가
  비어 있어도 조회 범위의 근거를 남기며, 범위 조회와 최종 권한 검증의 증적 다이제스트를
  보존합니다. 후보가 없다는 결과만으로 그래프에 대상이 없다고 단정하지 않습니다.
- `score_kind="predicate_membership"`은 포함 여부를 나타내는 상수 `1.0`을 뜻하며
  유사도 점수나 신뢰도가 아닙니다. `selection_digest`에는
  `secured-objectset-membership.v1` 전략과 고정된 제안이 연결됩니다. 기존 순위 검색과
  정확한 ID 조회는 동작을 유지하며 각자의 점수 종류를 표시합니다.

`typed_selection_available`의 기본값은 `False`이며, 의미 검색도 사용 가능한 상태여야 합니다.
이전에 임베딩 순위 검색의 품질을 검증했더라도 새 전략을 활성화할 수는 없습니다. 런타임
활성화는 계속 차단된 상태입니다. 고정된 기존 순위 검색 보고서로 이 경로의 품질을 인정하지
않습니다. 모델과 프롬프트 출처, 실제 의미 제안 평가와 새로 검토한 홀드아웃이 여전히 필요합니다.

## 테스트

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_assets.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_campaign.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_execution.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_replay.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_evidence.py
```

이 검사는 결정적 벡터를 사용합니다. 실행 구조와 데이터 수락 조건은 검증하지만 실제
임베딩의 검색 관련성은 입증하지 않습니다.

형식화된 조건의 후보 판정 경계와 기존 후보 및 평가 소비 경로는 다음 명령으로 검사합니다.

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_selection.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidates.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_vector_deadlines.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_runner.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_execution.py
```

이 검사는 형식화된 조건을 직접 제공하며 실제 모델을 호출하지 않습니다. 자연어 이해
품질을 측정하는 검사가 아닙니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 질의 계약과 진단 경계 | [온톨로지 질의 범위](../roadmap/interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| 현재 근거와 남은 검증 조건 | [구현 원장](../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md) |
