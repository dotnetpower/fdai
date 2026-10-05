---
translation_of: ontology-retrieval-diagnostics.md
translation_source_sha: 2e8d1aa2adfa703b6f77b25a03138ef4e96021d8
translation_revised: 2026-10-05
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
| [instance-holdout.v2.json](../../eval/ontology-retrieval/instance-holdout.v2.json) | 이미 사용한 홀드아웃입니다. 독립 작성과 검토를 거쳤고 `2572f9a1b1`에서 한 번 측정했습니다. 이 문항으로 튜닝하거나 자격 검증에 다시 사용하지 않습니다. |

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
- 정확한 ID 경로는 `object:<ObjectType>:<id>` 문서 ID를 형식화된 신원 토큰으로
  처리합니다. 쿼리에 이 토큰이 있지만 준비된 문서에 같은 ID가 없으면 판독기는
  의미 순위 검색으로 넘어가지 않고 `score_kind="exact_identity"`와 함께 후보 없음으로
  반환합니다. 이는 신원 검증일 뿐이며 별칭, 레이블 또는 구문에서 의미를 추론하지
  않습니다.

`typed_selection_available`의 기본값은 `False`이며, 의미 검색도 사용 가능한 상태여야 합니다.
이전에 임베딩 순위 검색의 품질을 검증했더라도 새 전략을 활성화할 수는 없습니다. 런타임
활성화는 계속 차단된 상태입니다. 고정된 기존 순위 검색 보고서로 이 경로의 품질을 인정하지
않습니다. 모델과 프롬프트 출처, 실제 의미 제안 평가와 새로 검토한 홀드아웃이 여전히 필요합니다.

## 진단용 모델 어댑터로 의미 제안

`FileSystemPromptRegistry`에서 `semantic.query.plan`의
`diagnostic.ontology-candidate-selection`을 명시적으로 선택하고 `PromptAssembler`로
컴파일하세요. 이 프로필은 관찰 모드(`shadow`)이며 현재 활성 계획 프로필을 대체하지 않습니다.

컴파일된 계획 본문과 재생 매니페스트, 정확히 한 대상, 10초 이하의 제한 시간으로 별도의
`AzureOpenAISemanticPlanningModel`을 구성하세요. 질문, 매니페스트, 완전한 정규 빌드와
준비된 스냅샷을 `propose_candidate_selection`에 전달합니다. 원본 검증기는 호출 전에
세대와 principal 매니페스트를 확인합니다. 문맥이 128 KiB를 넘거나 입력 최소화 후 내용이
바뀌거나 프롬프트 한도를 넘으면 호출을 보류합니다. 문서를 알리지 않고 빼지 않습니다.

후보 제안은 Azure OpenAI 구조화된 출력을 사용합니다. 요청은
`response_format.type="json_schema"`와 `OntologyCandidateProposal`과 동등하거나 더 엄격한
strict 스키마를 전송하며, 같은 principal 매니페스트와 프롬프트 페이로드의 허용된 조건식
속성 카탈로그에서 `object_type` 및 유형별 조건식 `property` 열거형을 도출합니다. 확인된
대상의 기본 API 버전이 구조화된 출력보다 오래된 경우 어댑터는 요청 API 버전을 `2024-10-21`로
올립니다. 요청 매개변수 다이제스트에는 실제 응답 형식, API 버전, 제한 시간과 출력 토큰
한도가 포함되므로 보존된 의미 근거는 같은 구조화 계약에서만 재생됩니다.

결과에는 입력 다이제스트와 전송된 프롬프트 및 스키마의 재생 매니페스트를 포함한 모델
관측 정보가 남습니다. 선택 결과에는 형식화된 절과 절마다 정확한 원문 인용이 포함됩니다.
인용 검증은 출처를 확인할 뿐 의미가 올바르게 해석됐음을 입증하지 않습니다. 명확화
결과에는 명시적 사유가 있으며 선택 정보는 없습니다. **판독기를 호출하기 전에 명확화를
처리하세요.** `search(selection=...)`에 `None`을 전달하면 명확화가 아니라 기존 순위
검색 경로가 선택됩니다.

진단 프롬프트는 질문이 제공된 정규 문서에 이미 있는 특정 인스턴스를 식별할 때 정확한
`object_ids`를 사용하도록 지시합니다. 심각도, 중요도, 유형, 상태 또는 종류처럼 실제
속성으로 제한된 집합에만 조건식을 사용합니다. 이렇게 하면 신원 해석은 모델이 제안하되
코드가 검증하며, 구문 목록이나 어휘 조회 로직을 추가하지 않습니다.

실제 의미 보정을 실행하기 전에 정확한 매니페스트 기반 응답 스키마와 프롬프트 프로필로
예정된 모든 보정 문항을 dry-run 하세요. dry-run은 예상 요청 토큰의 최댓값과 중앙값을
보고하고, 어떤 문항이라도 요청 토큰 예산을 넘으면 제공자 호출 전에 실패해야 합니다. 인용
출처 표시의 경우 각 절은 인용 하나를 포함합니다. 제공자에 전달하는 스키마에서는 매니페스트
기준 구조화 출력 문법이 일정하게 유지되도록 이를 자유 텍스트로 두고, 이후 정확한 구간 검증기가
잘못 출처 표시된 절을 멤버십 평가 전에 제거합니다. 모든 절이 제거되면 해당 문항은 후보 없음으로
기록됩니다.
진단 프로필은 모델 역할과 선택적 reasoning effort를 소유합니다. 현재 검토된 진단 후보 선택
역할은 `t2.reasoner.primary`이며, 이 필드를 지원하는 모델에는 `reasoning_effort="low"`를
사용합니다. effort 값은 요청 매개변수 다이제스트에 포함됩니다.

의미 평가는 제안 호출 하나를 10초로 제한하고 단계 전체 600초 한도는 유지합니다. 임베딩 보정은
호출당 5초 한도를 그대로 사용합니다. 이전의 5초 상한은 임베딩 예산에서 온 값입니다. 검토된
역할의 보정 근거를 보면 출력 크기로 설명되지 않는 프로바이더 쪽 꼬리 지연이 있습니다. p50은 약
2.2초, p95는 약 3.4~3.5초이며, 24~36회 호출마다 한 번꼴로 5초 상한에 도달했습니다.
`84d7d1a26b`의 자격 검증 시도는 품질 결과가 나오기 전에 두 단계 모두 이 제한 시간으로
중단되었습니다. 이 값은 진단용 한도일 뿐 프로덕션 지연 시간을 승인하지 않습니다. 어디서든 의미
순위 검색을 활성화하려면 별도의 지연 시간 자격 검증이 여전히 필요합니다.

2026-10-05 개발 의미 보정은 소스 `91d537c36b`와 커밋되지 않은 변경을 사용해 제안 호출
64회를 151.7초에 완료했으며 근거 다이제스트는
`sha256:b0ece2df7a47f3ed280035822b9331fab3f9ca853fc2dca441b9eaab47c70ebb`입니다.
모든 v2 보정 코호트 지표가 `1.0`이었고 `passed=True`였으며 오프라인 검증도 성공했습니다.
북키핑을 포함한 호출별 지연 시간은 p50 2.23초, p90 3.08초, p95 3.38초, 최대 5.10초였습니다.
5.10초의 한도 근접 꼬리 지연은 최종 실행의 잔여 위험으로 다루세요. 이 측정은 병합된 불변
커밋이 아니라 개발 상태에서 수행했으므로 개발 근거일 뿐입니다.

이 진단 메서드는 한 번만 시도합니다. 제공자 실패, 잘못된 JSON, 불완전한 모델 응답,
잘못된 인용과 제한 시간 초과를 빈 검색 성공으로 바꾸지 않습니다. 일반 프레임 및 계획
제안의 재시도 동작은 변경하지 않습니다. 실제 호출 승인, 모델과 버전의 실측 확인, 호출별
영속 근거, 평가 연결 정보와 전체 예산은 계속 호출자가 책임집니다. 모의 어댑터 검사는
실제 품질이나 런타임 활성화 자격을 입증하지 않습니다.

이전 진단 이력도 계속 중요합니다. 원시 임베딩 순위 검색은 v2 보정을 통과하지 못했고, mini
의미 모델은 필터링한 실패 8건 중 5건만 통과했으며, 더 강한 역할의 시도에서는 5초 꼬리 시간
초과가 발생했습니다. `reasoning_effort="minimal"`은 배포/API 경로에서 거부되었고, 상수
매니페스트 기반 구조화 스키마와 `reasoning_effort="low"` 조합은 개발 v2 보정을 통과했습니다.

병합된 `2572f9a1b1`에서 실행한 자격 검증 진단은 보정 v2와 독립 검토를 거친
`instance-holdout.v2`를 각각 한 번씩 엄격한 재생 검증으로 측정했습니다. 보정은 모든 코호트에서
`1.0`으로 통과했습니다. 홀드아웃은 통과하지 못했습니다. en-positive와 ko-positive의 recall@5와
MRR은 `0.938`(각각 16건 중 15건)이고, ko-adversarial의 일치 없음 정밀도는 `0.5`였습니다. 나머지
코호트는 모두 `1.0`이었습니다. 호출당 지연 시간은 10초 한도 안에 있었고 홀드아웃 최댓값은
8.3초였습니다. 의미 순위 검색은 계속 비활성화 상태입니다. 두 홀드아웃은 모두 이미 사용되었습니다.
이후 변경은 보정, 말뭉치, 새로 검토한 보정 샘플만으로 실패 유형을 진단한 다음, 새로 작성한 독립
`instance-holdout.v3`로 검증해야 합니다.

## 의미 제안을 별도로 측정

준비된 형식화 후보 판독기와 `OntologyEvaluationEvidence(..., semantic_proposals=True)`를
사용하여 `prepare_ontology_semantic_evaluation`과 `run_ontology_semantic_evaluation`을
실행하세요. 전체 소스 커밋 식별자가 필요합니다. 이 모드는 임베딩 벡터를 보존하거나 기존
벡터 재생의 근거로 사용할 수 없습니다. 준비 작업에는 별도의 실행 한도를 적용합니다.

평가 계획에는 문항 순서, 변경되지 않은 라벨과 정책, 정규 원본, 스냅샷, 선택 전략, 대상,
전송할 프롬프트와 스키마, 출력 토큰과 제한 시간을 포함한 실제 요청 매개변수가 연결됩니다.
모델 이름과 버전은 호출자가 확인했다고 제공하는 정보입니다. 실제 배포 상태 확인과 범위를
명시한 실행 승인은 계속 호출자가 책임집니다.

- **한도:** 제안 인터페이스 호출은 최대 64회, 측정은 전체 600초, 문항당 10초입니다.
  측정 전후에 현재 원본을 검증하며, 각 검증은 전체 한도 안에서 최대 120초로 제한합니다.
- **영속 기록 순서:** 다음 단계로 진행하기 전에 호출 의도, 수락한 제안과 측정값을 각각
  디스크에 반영합니다. 제안 근거에는 인용문 전체가 아니라 형식화된 조건과 원문에서 인용한
  위치를 보존합니다. 이 파생 데이터는 비공개로 보관하세요. 명확화는 별도로 기록하며 기존
  순위 검색으로 넘어가지 않습니다.
- **실패:** 입력이나 대상 및 요청 연결 정보가 바뀌거나, 형식화 후보 선택을 사용할 수
  없거나, 제공자 호출, 출력 검증 또는 저장에 실패하면 중단합니다. 취소는 취소로 유지하며,
  기록기를 사용할 수 있으면 이전 측정값을 보존합니다.
- **별도 결과:** 의미 평가 보고서는 자체 식별자와 기존 코호트 지표 계산 및 임계값을
  사용합니다. 한 단계의 `passed`는 전체 평가의 자격을 뜻하지 않습니다.
  `production_qualification`과 `execution_authority`는 계속 `False`입니다.

### 최종 근거의 결과 해석

의미 평가 근거는 스키마 `1.1.0`을 사용하며 최대 198개 기록을 허용합니다. 기존 비공개 파일,
기록 크기와 파일 크기 제한도 유지합니다. 보고서의 측정 경과 시간은 종료 기록 저장 전에
계산하며, 실행기는 저장이 끝난 뒤 전체 제한 시간을 다시 확인합니다. 저장 완료가 늦으면
실행기는 오류를 반환하고 `completed` 뒤에 `aborted` 정정 기록을 한 번 추가하여 측정값을
보존합니다. **앞선 완료 기록이 아니라 마지막 종료 결과를 기준으로 판단하세요.**
정정 후에는 호출을 재개하거나 중단 결과를 성공으로 바꿀 수 없습니다. 기존 근거 형식의
종료 규칙은 변경하지 않습니다. 실패 기록 자체를 저장하지 못하면 종료 결과의 저장 완료가
확인되지 않은 것이므로 성공으로 취급할 수 없습니다.

### 보존한 의미 평가 근거를 오프라인으로 검산

[verify_ontology_semantic_evidence](../../services/core-control-plane/src/fdai/delivery/catalog_search/ontology_semantic_evidence.py)에
독립적으로 고정한 파일 다이제스트와 원래 준비한 계획, 빌드, 매니페스트, 준비된 스냅샷,
문항, 보정 질의, 순위 정책, 평가 정책 및 필수 객체 유형을 전달하세요. 신뢰하지 않는 근거에서
예상 계획과 파일 다이제스트를 읽었다는 이유로 이를 승인된 값으로 취급하지 마세요.

- **일관성:** 검증기는 고정한 입력 연결 정보를 다시 계산하고 완전한 기록 순서를 확인합니다.
  질의의 인용 위치에서 제안을 복원하고 호출별 측정값을 최종 보고서와 대조합니다.
  반환 ID는 중복 없이 정렬되어 한도 안에 있어야 하며 준비한 인스턴스 문서에 존재해야 합니다.
  코호트 지표와 실패 코드는 변경하지 않은 정답을 기준으로 다시 계산합니다.
- **실패 보존:** 일관된 실패 보고서는 그대로 반환합니다. 연결 정보 변경, 잘못된 기록,
  호출 누락 또는 마지막 중단 정정 기록이 있으면 비공개 값을 숨긴 `ValueError`를 발생시킵니다.
- **한계:** 제공자를 호출하거나 그래프를 다시 관측하지 않습니다. 모델 응답이나 결과
  다이제스트의 진위, 종료 기록 저장의 확인 여부도 입증하지 않습니다.
  `production_qualification`과 `execution_authority`는 계속 `False`이며 런타임 활성화는 바뀌지 않습니다.

예: 재현율이 임계값보다 낮으면 검산 후에도 `passed=False`입니다. 실패 코드를 지우고
요약 지표를 고쳐도 보존된 측정값을 통과 결과로 바꿀 수 없습니다.

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

모델 경계, 실제 진단 프로필과 기존 계획 동작은 다음 명령으로 검사합니다.

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_semantic_evidence.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_semantic_evaluation.py \
  services/core-control-plane/tests/delivery/azure/llm/test_ontology_candidate_proposal.py \
  services/core-control-plane/tests/delivery/azure/llm/test_semantic_planning.py \
  services/core-control-plane/tests/core/prompts/test_profiles.py
```

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 질의 계약과 진단 경계 | [온톨로지 질의 범위](../roadmap/interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| 현재 근거와 남은 검증 조건 | [구현 원장](../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md) |
