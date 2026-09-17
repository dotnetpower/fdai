---
translation_of: conversation-attachments.md
translation_source_sha: 5ee244add2afd7a79c0182032e52ff0699ad0f1c
translation_revised: 2026-09-17
title: 대화 첨부파일
---
# 대화 첨부파일

이 문서는 Slack, Teams 및 web 채팅에서 문서와 이미지를 FDAI 대화에 첨부하면서
문서 안전성, 권한 확인, grounding 및 ownership-handover 거버넌스를 우회하지 않는
방법을 정의합니다.

> 대화 채널은 페이로드가 제공한 download URL을 신뢰하지 않으며 파일 바이트를 모델
> 프롬프트에 넣지 않습니다. 모든 출처는 먼저 통제된 document-ingestion 파이프라인에 들어갑니다.
> 대화에는 변경할 수 없는 `doc:<document_id>:<version_id>` 인용만 전달됩니다.

## 설계 개요

모든 채널 타입은 동일한 문서 수명 주기로 수렴합니다.

![설계 개요. 주요 단계는 Slack opaque file id, Server-authenticated fetcher, Teams opaque attachment id, Web upload session, Ingestion gateway, Malware and protection checks, Text, Office, or optional OCR extraction, Immutable document version and index, Authorized doc citation, Conversation evidence, Ownership draft and governance PR입니다.](../../diagrams/generated/fdai-roadmap-interfaces-conversation-attachments-01.ko.svg)

파일 출처는 채널마다 다릅니다. 안전성, 저장소, 용도, 인용, 보존 및 감사는
동일합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 벤더 중립 첨부 메타데이터 | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | `ChannelAttachment`와 `InboundTurn`은 범위가 제한된 opaque 메타데이터를 강제합니다. 이 계약이 벤더 어댑터 구현을 의미하지는 않습니다. |
| 명시적 첨부 용도 | implemented | [`attachment_directive.py`](../../../services/core-control-plane/src/fdai/core/conversation/attachment_directive.py), [`test_attachment_directive.py`](../../../services/core-control-plane/tests/core/conversation/test_attachment_directive.py) | 정확한 선행 directive만 담당 체계 인수인계 의도를 선택하며 일반 문장과 파일 이름은 선택하지 않습니다. 조직도 가져오기는 `report_line_bootstrap`을 사용하는 전용 Console 업로드를 통해 처리하며 일반 채널 첨부에서 추론하지 않습니다. |
| 채널 인제스트 gateway seam | implemented | [`channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | Gateway는 주입된 ingestor를 받고 없으면 실패 시 차단합니다. 구체적인 protected-ingestion 구현은 아닙니다. |
| Slack 첨부 전달 | implemented | Operator `channel_edge/{slack_ingress,attachment_handoff}.py`, 집중 전달, 환경 및 파이프라인 검사 | 서명된 어댑터는 범위가 제한된 불투명 메타데이터를 유지하고 페이로드 URL을 버립니다. 고정 HTTPS 호스트를 통해 `files.info`를 해석하고 비공개 바이트를 이름이 없는 범위 제한 스풀로 스트리밍합니다. |
| Teams 첨부 전달 | implemented | Operator `channel_edge/{teams_ingress,attachment_handoff}.py`, 집중 전달, 환경 및 파이프라인 검사 | 인증된 어댑터는 범위가 제한된 불투명 메타데이터를 유지하고 페이로드 URL을 버립니다. 구성된 HTTPS 해석기, 호스트 허용 목록 및 토큰 대상 허용 목록만 사용합니다. |
| 보호된 채널 인제스트 조립 | implemented | `fdai_ingestion_api_service/channel_attachment*.py`, Operator `channel_edge/{composition,pipeline}.py`, 인제스트 집중 테스트 28개와 Operator 집중 테스트 236개 | 별도 내부 인제스트 워크로드가 허용, 정본 업로드, 영속 재생, 최종 상태 관측 및 인용 반환을 담당합니다. 프로바이더 바이트는 Kafka에 들어가지 않습니다. |
| 채널 전달 호환성 승격 | in-progress | `compatibility-manifest.json`, 전이 인증 범위, 집중 및 독립 서비스 호환성 검사 | 현재 계약 9개는 모두 집중 호환성 검사를 통과합니다. 보존된 전이 근거는 이전에 배포한 edge 7개만 인증하며, 첨부 HTTP edge 2개는 새로운 보호된 N/N-1 근거가 생길 때까지 전이 인증에서 제외됩니다. |
| Core 정확한 문서 조회 | implemented | `governed_document_reader.py`, `postgres_governed_document_read.py`, `semantic_turn_processor.py`, Core 및 담당 체계 집중 테스트 377개 | Core는 요청에 결속된 모든 버전을 다시 권한 확인하고 정확한 식별자 집합만 검색합니다. 최종 결과는 문서 맥락 다이제스트와 실제 반환된 정확한 인용 집합을 되돌려야 합니다. |
| Web 채팅 문서 참조 | implemented | Operator `document_refs.py`, `postgres_document_refs.py`, `factory.py`, Operator 이행 `20260914_operator_conversation_document_refs.py`, 집중 Operator 및 이행 검사 | Operator는 영속 semantic 게시 전에 원시 참조를 서버 소유 `web_reference` 맥락으로 바꿉니다. 범위가 제한된 `SECURITY DEFINER` 함수는 원시 테이블 읽기 권한을 부여하지 않으면서 문서 테이블 소유권을 보존하고 업로더 또는 읽기 그룹 접근을 권한 확인합니다. |
| Web 채팅 인라인 이미지 해석 경로 | in-progress | [`composer-attachments.view.tsx`](../../../console/src/deck/composer-attachments.view.tsx), [`backend-context.ts`](../../../console/src/deck/backend-context.ts), [`conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/conversation_images.py), [`postgres_conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_conversation_images.py) | Console 캡처, 요청 직렬화, 범위가 제한된 이미지 저장소, 이행 및 과거 이미지 렌더링은 존재합니다. 서버의 이미지 해석, 의미 요청 전달 및 운영 저장소 연결은 미완료입니다. 지원하지 않는 이미지는 거부해야 하며, 이미지를 버린 뒤 텍스트만으로 답해서는 안 됩니다. |
| 문서 이미지 OCR | implemented | [`processing.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/processing.py), [`production.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/production.py), [`test_ingestion_adapter_readiness.py`](../../../services/document-processing-worker/tests/test_ingestion_adapter_readiness.py) | Document worker는 OCR endpoint가 설정되면 범위가 제한된 Document Intelligence `prebuilt-read`를 연결하고 그렇지 않으면 실패 시 차단합니다. 이 구현만으로 채널 또는 inline 채팅 인제스트가 완성되지는 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-17 | implemented | 통합으로 판테온 원본 다이제스트가 바뀐 뒤 공유 의미 의도 출처 이력을 다시 생성했습니다. 첨부 원본, 계약, 개수, 데이터 접근 및 권한은 바뀌지 않았습니다. | `current change`; 공식 의미 의도 생성기; 집중 산출물 동등성 검사. | 이 결정론적 다이제스트 갱신과 관련해 남은 대화 첨부 작업은 없습니다. |
| 2026-09-16 | implemented | 브라우저 근거 지역화 문구를 Console 카탈로그 사이에서 옮긴 뒤 공유 의미 의도 원본 다이제스트를 갱신했습니다. 첨부 원본, 계약, 개수, 데이터 접근 또는 권한은 변경하지 않았습니다. | PR #1109 CI 실행 `34988599311`, 생성된 의미 의도 범위, 집중 산출물 동일성 검사 4개 통과 | 이 결정론적 다이제스트 갱신과 관련해 남은 대화 첨부 작업은 없습니다. |
| 2026-09-14 | implemented | 이미지 전달을 활성화하지 않고 두 HTTP 채팅 경로와 직접 의미 요청 및 서술기 경계의 이미지 누락을 차단했습니다. 잘못된 필드가 섞인 입력은 사용 가능 여부를 판단하기 전에 실패하며, 거부된 이미지는 서술기 자격 증명을 얻을 수 없습니다. | [이슈 #985](https://github.com/dotnetpower/fdai/issues/985), `current change`, 집중 Operator 경로, 의미 요청 연결, 로컬 서술기 및 정확한 문서 검사 245개가 3.65초에 통과했습니다. Ruff 7개 파일 및 strict mypy 소스 4개 검사가 통과했습니다. | 전체 인라인 이미지 지원은 진행 중입니다. [이슈 #303](https://github.com/dotnetpower/fdai/issues/303)에는 보호된 공급자, OCR, 배포 및 효과 증적이 여전히 필요합니다. |
| 2026-09-14 | in-progress | 두 HTTP 채팅 경로, 의미 요청 묶음 생성기, 로컬 서술기의 Console 첨부 필드에서 이미지가 조용히 누락되는 현상을 재현했습니다. 원시 이미지 전달이나 근거 없는 텍스트 대체 대신 명시적인 사용 불가 경계를 선택했습니다. | `current change`, 집중 Operator 경로, 의미 요청 묶음 및 서술기 회귀 테스트를 두 번 실행해 실패 8건을 재현했습니다. 기존 서술기의 `images` 및 `image_ids` 차단 검사는 통과했습니다. | 수정된 경계를 검증합니다. 전체 인라인 이미지 해석과 이슈 #303의 보호된 공급자 검증은 남아 있습니다. |
| 2026-09-14 | implemented | 첨부 전달의 CI 소유권과 구조를 정합화했습니다. 출처에서 파생되는 의미 의도 다이제스트를 갱신하고, 범위가 제한된 Core 호출 맥락 모듈을 등록했으며, PostgreSQL 문서 해석기 조립을 PostgreSQL family adapter facade 뒤로 옮겨 Operator 조립 root가 검토된 fan-out 상한 아래에 머물게 했습니다. | `current change`, 의미 의도 범위 테스트, 조립 패키지 분리 테스트, Operator 문서 참조 테스트, Operator 경계 및 파일 LOC 검사 | 보호된 배포 근거를 추가할 때 같은 경계를 유지합니다. 이 구조 보완만으로 실제 운영 검증을 추론하지 않습니다. |
| 2026-09-14 | implemented | 과거 로컬 및 실제 운영 근거에 새 이름을 붙이지 않고 현재 9개 계약 집중 검사 행렬과 보존된 7개 edge 전이 인증을 분리했습니다. | `current change`, 호환성 manifest와 검증기, 집중 호환성 및 독립 서비스 검사, 인증 범위 부정 테스트 | 보호된 N/N-1 배포가 정확한 스키마, 신원, 상태, offset, 출처, 이미지 및 토폴로지 관측을 기록한 뒤에만 첨부 HTTP edge 2개를 전이 인증에 추가합니다. |
| 2026-09-14 | implemented | 비공개 Slack 및 Teams 가져오기 경로, 내부 채널 인제스트 워크로드, 영속 허용 및 커밋 재생, 해시에 결속된 최종 증적, 정확한 Web 및 Core 권한 확인, 로컬 및 Terraform 토폴로지, 보호된 전환 검증과 인증된 워크로드 준비 상태 확인을 추가했습니다. | `current change`, 계약 93개, 인제스트 28개, Operator 236개, Core 및 담당 체계 377개, Entra 40개, 정확 참조 이행 2개, 배포, 워크플로 및 로컬 시작 집중 테스트 345개, 소유 영역별 strict mypy 검사 4개, 변경 파일 Ruff 및 생성 산출물 검사 | 테넌트 관리자가 애플리케이션 역할 선행 조건을 완료한 뒤 보호된 운영 배포 근거를 기록합니다. 별도 inline vision 경로를 완성합니다. |
| 2026-09-14 | implemented | 서비스 분해 이후의 Operator edge를 이 owner와 정합화했습니다. 비활성화된 프로바이더 첨부는 queue 유입 전에 실패하고, 직접 queue 주입은 의미 게시 전에 실패하며, 지원되지 않는 활성화는 시작에 실패합니다. | `current change`, 집중 Operator 환경, 조립, Slack, Teams 및 파이프라인 검사 | 에이전트 소유 문서 인제스트로 전달하는 버전이 지정된 계약을 정의하고 비공개 벤더 가져오기 도구, 최종 인용 반환 및 통제된 런타임 근거를 연결합니다. |
| 2026-08-13 | in-progress | 이전 출처 이력을 재구성하지 않고 현재 계약, 어댑터, 조립, Console 코드 및 테스트와 설계를 대조했습니다. | 구현 범위 표에 나열한 현재 소스와 집중 검사입니다. | 벤더 어댑터, protected 인제스트, web 문서 해석, 서버 inline 이미지 경로 및 통제된 runtime 증적이 남아 있습니다. |
| 2026-08-16 | in-progress | 범위가 제한된 `document_refs` 요청 계약과 semantic 처리 전에 동작하는 principal 범위의 닫힘 실패 해석 경계를 추가했습니다. | `pytest services/operator-service/tests/test_conversation_document_refs.py`가 구문 및 비정규 UUID 거부, 참조 8개 상한, 고유성, 동일한 거부 응답, resolver 부재 501, 격리된 resolver 실패, 순서 변경 및 대체 인용 거부를 다루는 집중 테스트 12개를 통과했습니다. | 해석된 인용을 버전이 지정된 semantic envelope로 전달하고 PostgreSQL 문서 메타데이터 기반 운영 resolver를 연결해야 합니다. |

### 남은 작업

- [x] 범위가 제한된 불투명 첨부 메타데이터만 유지하는 서명된 Slack 및 인증된 Teams
  유입 어댑터를 구현하고 보호된 인제스트가 꺼진 동안 queue 유입 전에 차단합니다.
- [x] 서버 소유 endpoint 해석, credential 범위 제한, redirect 거절, host allowlist 및 streamed
  byte 상한을 적용하는 비공개 벤더 fetcher를 구현합니다.
- [x] Malware, protection, 추출, 인덱싱, 권한 확인, 인용 및 인계 경로를 통과하는 구체적인
  채널 ingestor를 조립합니다.
- [x] Operator 대화 family에 범위가 제한된 `document_refs` 요청 계약을 추가하고 semantic 처리
  전에 principal 범위 문서 권한 확인을 통해 해석합니다.
- [x] 해석된 `document_refs` 인용을 버전이 지정된 semantic envelope로 전달하고, 권위 있는
  PostgreSQL 문서 메타데이터 기반 운영 resolver를 연결하며, 경로 수준 테스트를 추가합니다.
- [x] 텍스트 전용 채팅 요청을 수락하기 전에 지원하지 않는 이미지 필드를 거부합니다. [이슈 #985](https://github.com/dotnetpower/fdai/issues/985)에 집중 경계 근거를 기록합니다.
- [ ] 서버 inline 이미지 parser, byte 및 media 검증, 저장소 연결, semantic transport, vision
  narrator 입력, 이력 메타데이터 및 인증된 조회 경로를 완성합니다.
- [ ] 내부 인제스트를 먼저 활성화하고, edge 서비스 principal에 정확히
  `Document.ChannelAttachment.Submit`을 할당하고, 인증된 준비 상태 확인을 통과한 뒤 Slack 또는
  Teams 첨부 하나가 조회 가능한 인용에 도달하는 보호된 배포 기록을 남깁니다.
- [ ] 보호된 N/N-1 실행이 정확한 7종 관측을 보존한 뒤에만
  `channel-attachment-admission`과 `channel-attachment-receipt`를 전이 인증 범위로 승격합니다.
- [ ] 정확한 인용과 `document_context_digest`가 Core 최종 결과까지 보존되는 인증된 Web
  `document_refs` 턴을 기록합니다.

## 용도 및 권한 확인

### 기본 근거

Directive가 없는 첨부는 `knowledge_base`를 사용합니다. Attachment-only 메시지도 valid하며
인용과 함께 결정론적 protected-ingestion 확인 응답을 반환합니다. 일반 산문에서
인계를 언급해도 용도는 바뀌지 않습니다.

### 소유권 인계

소유권 인계에는 정확한 leading directive가 필요합니다.

```text
/handover
/handover transfer Thor and Heimdall ownership
/attach handover
인수인계 문서: Thor 담당자 변경
```

인계 역할 하한은 기여자입니다. 역할 검사는 벤더 download 전에 실행되므로 읽기 담당이
fetch, 검사, OCR, 임베딩 또는 GitOps 용량을 사용할 수 없습니다. Successful 인계는
서술기를 호출하지 않습니다. 기존 인계 소비자가 근거에 기반한 초안과, 활성화된인 경우 거버넌스
pull 요청을 만든 뒤 결정론적 검토 확인 응답을 반환합니다.

업로더는 업로드했다는 이유로 소유자가 되지 않습니다. 후보는 가산이므로 기존
소유권이 유지됩니다. 배포가 새 값을 부하하기 전에 사람이 Git 변경을 검토하고
병합해야 합니다.

## 버전이 지정된 서비스 전달

### 초기 설계

초기 cross-service 선택지는 공개 create, content, complete 및 status 경로를 재사용하는
방식이었습니다. Operator edge가 자체 workload token으로 해당 경로를 호출하고 매핑된 사람
principal을 request header에 첨부합니다.

### 설계 비평

이 선택지는 수락하지 않습니다. 공개 인증기는 bearer token subject를 upload actor로 취급하므로
edge workload와 attributed human을 분리할 수 없습니다. Caller가 role, group, collection, access
또는 retention을 제공하면 ingestion API가 confused deputy가 됩니다. Slack과 Teams 메타데이터는
download 전에 신뢰할 SHA-256을 제공하지 않지만 정본 upload session에는 선행 hash가 필요합니다.
또한 응답이 선택한 upload URL은 edge에 불필요한 network destination 결정을 추가합니다.

### 보강된 설계

수락한 전달은 기존 Document Ingestion API distribution의 internal-only workload를 사용합니다.
동일한 서비스 owner가 독립적으로 확장할 수 있는 또 하나의 process이며 새로운 service
distribution이나 document writer가 아닙니다. 공개 drop-zone 경로는 변경하지 않습니다.

Intake는 네 가지 신원을 독립적으로 인증합니다.

1. Slack signature 또는 Teams service token이 provider request를 입증합니다.
2. Channel principal mapping이 attributed FDAI human을 식별합니다.
3. 전용 Operator edge Managed Identity가 HTTPS caller를 인증합니다.
4. Internal intake는 PostgreSQL, object storage 및 lifecycle publication에 document-ingestion
  identity를 사용합니다. 이 경로의 어떤 identity도 Thor executor identity가 아닙니다.

Workload token에는 exact ingestion audience, issuer, application identity 및 하나의
attachment-submit App Role이 필요합니다. Delegated scope, group claim, 다른 application 또는
human token은 이 경계를 충족하지 않습니다. Request는 human principal id와 principal-manifest
digest만 attribution으로 전달합니다. Ingestion은 동일한 versioned manifest를 독립적으로 로드하고
현재 role을 직접 해석하며 admission 전에 document Contributor access를 요구합니다. Request는
role, group, collection, access descriptor, retention, URL, token audience 또는 endpoint를 제공할
수 없습니다.

일반 대화 근거는 `session_ephemeral`, conversation scope 및 배포의 server-owned attachment
policy를 사용합니다. Handover directive는 requested purpose만 선택합니다. Ingestion은 이를
server-owned handover policy에 매핑하고 Contributor 검사를 반복합니다. Collection, reader group,
storage mode, access descriptor 및 retention은 항상 해당 policy에서 가져옵니다.

서비스 계약은 다음과 같은 변경 불가능하고 권한이 없는 record를 사용합니다.

| Record | 책임 |
|--------|------|
| `ChannelAttachmentAdmissionRequest` `1.0.0` | 결정적 handoff id, origin digest, attachment ordinal, attributed principal, manifest digest, requested purpose, safe name, media hint, declared size, deadline 및 request digest를 결속합니다. |
| `ChannelAttachmentAdmissionReceipt` `1.0.0` | URL 또는 storage credential 없이 수락한 policy digest, server limit, expiry 및 receipt digest를 반환합니다. |
| `ChannelAttachmentCommitReceipt` `1.0.0` | 영속 `received` 상태 이후 독립적으로 관측한 size와 SHA-256을 정본 upload, document 및 version id에 결속합니다. |
| `ChannelAttachmentTerminalReceipt` `1.0.0` | 영속 commit receipt digest, 관측 크기, SHA-256, 수명 주기 및 index 상태와 관측 시간을 결속합니다. active, available, live-retention 상태이며 active index를 가진 version에만 정확히 하나의 citation을 반환합니다. |

각 record는 알 수 없는 field를 거부하고 변경할 수 없으며 `execution_authority=false`와 canonical
content digest를 포함합니다. HTTP major version은 고정 internal path에 유지합니다. Additive minor
version은 N 및 N-1 reader를 유지하며 지원하지 않는 version은 reservation 또는 content I/O 전에
실패합니다.

Admission은 vendor download 전에 실행됩니다. Admission 이후 edge는 size와 SHA-256을 계산하면서
vendor response를 이름이 없고 quota로 제한된 ephemeral spool로 streaming합니다. Spool은 전체
파일 memory buffering을 방지하고 정본 upload session이 요구하는 predeclared hash를 제공합니다.
그런 다음 edge는 admission digest, content length 및 hash와 함께 같은 byte를 고정 internal HTTPS
origin으로 streaming합니다. Intake가 제공한 URL을 따르지 않습니다. 암호화된 scratch가 없거나
cleanup이 실패하면 기능을 unavailable로 유지합니다.

Intake는 handoff마다 안정적인 upload identity 하나를 파생하고 기존 create 및 streaming-content
경계를 호출하며 object-store size와 hash가 일치한 뒤에만 기존 completion 경계를 호출합니다.
`document.received`는 ingestion API만 publish합니다. Network ambiguity는 retry 전에 handoff status를
읽어 해소합니다. Edge는 content PUT을 확인 없이 반복하지 않습니다. 같은 handoff id와 request
digest를 replay하면 보존된 상태를 반환합니다. 다른 content 또는 metadata로 id를 재사용하면
conflict를 반환하고 새로운 document event를 publish하지 않습니다.

상태 경로는 마지막 영속 단계를 반환합니다. Commit 저장이 끝날 때까지 admission을 재생하고,
메타데이터가 관측될 때까지 commit을 재생하며, 두 항목이 모두 존재한 뒤에만 최종 증적을
반환합니다. 모든 최종 관측은 같은 commit digest, 정본 id, 크기, SHA-256 및 용도를 유지합니다.
진행 중 값이 바뀌면 인용을 수락하기 전에 실패 시 차단됩니다.

예약 commit을 영속하기 전에 정본 upload completion이 성공하면 상태 재생이 정본 upload 상태에서
commit을 재구성합니다. 벤더 download 또는 content upload를 다시 수행하지 않습니다.

Edge는 document table access가 아니라 intake status surface를 통해 대기합니다. Knowledge
attachment는 document와 index 상태가 retrieval predicate를 충족할 때만 성공합니다. Handover
attachment에는 기존 grounded draft projection과, 활성화된 경우 governance delivery receipt도
필요합니다. Timeout, hold, failure, deletion, expiry 또는 index failure는 citation을 반환하지 않으며
inline worker를 시작하지 않습니다.

Attachment-only turn은 결정적 acknowledgement에 입력 순서의 citation을 반환합니다. Text turn은
ordered `document_context`를 포함한 additive `operator-core-request` `1.8.0`을 사용합니다. Core는
모든 exact version을 다시 authorize하고 governed-document query를 해당 set으로 제한합니다. 참조
하나가 unavailable 또는 unauthorized이면 document lane을 hold하며 collection search로 넓히지
않습니다. Terminal semantic result는 document-context digest를 결속하고 해당 context가 admit한
reference만 cite할 수 있습니다. 함수 근거의 인용은 요청 집합을 복사하지 않고 정확 검색이
실제로 반환한 `source_ref`에서 파생합니다. 인용이 누락되거나 대체되거나 형식이 잘못되면 답변을
보류합니다.

[구조화된 클라우드 문서 확장](cloud-resource-knowledge-structured-rag-ko.md)은 개발 중입니다.
의미 판단 `1.2.0`의 `document_query`는 수락된 모델 판단에서만 프레임에 전달되며, 다이제스트로
정확한 원래 질문에 연결됩니다. 검색어는 문서 맥락이나 클라우드 적용 조건을 넓힐 수 없으며,
원본 문서 본문은 의미 처리 전송에 포함하지 않습니다.

## Slack download 계약

Slack 이벤트 페이로드 URL은 신뢰할 수 없는이므로 폐기합니다. 가져오기 도구는 다음을 수행합니다.

1. 정규화된 opaque 파일 id만 받습니다.
2. Injected 시크릿 프로바이더에서 bot 토큰을 읽습니다.
3. 자격 증명, 조회, 조각 또는 redirect 없이 server-configured HTTPS Slack API
  `files.info` 엔드포인트를 호출하고 HTTP 200을 요구하며 구성된 바이트 상한을 넘는 즉시 메타데이터
  읽기를 중단합니다. API 출처는 fixed metadata-host 허용 목록과 일치하고 기본값 HTTPS 포트를
  사용해야 합니다.
4. 반환된 Slack 파일 id가 요청한 opaque id와 exact 일치하도록 요구합니다.
5. 구성된 허용 목록과 호스트가 정확히 일치하고 기본값 HTTPS 포트를 사용하는 비공개 download
  URL만 허용합니다.
6. 검증된 호스트에만 bot 토큰을 전송합니다.
7. Redirect를 비활성화하고 잘못된 또는 부정 `Content-Length`를 거부하며 decoded 내용에
  streamed-byte 한도를 적용합니다.
8. Protected 인제스트에 바이트를 반환하며 인제스트는 SHA-256을 다시 계산하고 메타데이터 크기를
   확인합니다.

Slack 앱에는 선택한 Slack API가 요구하는 narrow file-read 권한만 부여하는 것이 좋습니다.
토큰 값은 Key Vault 또는 다른 `SecretProvider`에 유지하며 구성, 감사, 오류에 기록하지
않습니다.

## Teams download 계약

Teams 페이로드의 `contentUrl` 및 `serviceUrl`은 폐기합니다. 배포는 opaque id를 서버가 소유한
Bot 또는 Graph 상태를 통해 URL 및 토큰 대상이 포함된 `AttachmentDownloadLocation`으로
매핑하는 `TeamsAttachmentEndpointResolver`를 제공합니다.

가져오기 도구는 다음을 수행합니다.

- HTTPS 및 exact 구성된 호스트를 요구합니다.
- 토큰을 요청하기 전에 server-resolved 토큰 대상이
  `FDAI_TEAMS_ATTACHMENT_AUDIENCES`와 exact 일치하도록 요구합니다.
- URL 자격 증명과 redirect를 거부합니다.
- Injected 워크로드 신원에서 audience-scoped 토큰을 요청합니다.
- Slack과 동일한 바이트 상한 안에서 스트림합니다.
- 실행기 신원을 전송하지 않으며 caller-selected 대상을 받지 않습니다.

이 해석기 경계는 신뢰할 수 없는 페이로드가 네트워크 대상을 선택하지 못하게 하면서 Bot
Framework, Microsoft Graph 및 sovereign-cloud 배포를 지원합니다.

## Web 채팅 계약

인라인 이미지 기능은 아직 완성되지 않았습니다. 두 채팅 POST 경로는 비어 있지 않은
`attachments`, `images`, `image_ids` 배열을 `501 inline_images_unavailable`로 거부합니다.
이는 문서 해석, 영속 요청 수락 및 스트림 시작보다 먼저 수행됩니다. 필드 부재, null 및
빈 배열은 텍스트 전용 호환성을 유지하며 다른 값은 `400 invalid_inline_images`를 반환합니다.
직접 의미 요청 묶음을 생성할 때도 같은 검사를 적용하고, 로컬 서술기는 토큰을 얻기 전에
세 필드를 모두 확인합니다. 오류에는 입력한 이름, 식별자 또는 이미지 바이트를 넣지 않습니다.

이 실패 시 차단 보완은 인라인 이미지 해석의 완성이나 문서 인용 생성을 뜻하지 않습니다.
원시 데이터 URL을 Kafka로 보내면 검토된 저장소와 근거 경계를 우회하며, 이미지를 조용히
버리면 다른 질문에 답하게 됩니다. 전체 지원에는 principal 범위 저장소, 미디어 검증,
의미 요청 전달, 서술 및 보존 작업이 여전히 필요합니다.

Operator API는 multipart 파일, raw 바이트, 저장소 URL 또는 채널 첨부 id를 받지 않습니다.
SPA 흐름은 다음과 같습니다.

1. 인증된 인제스트 업로드 세션을 만듭니다.
2. 인제스트 게이트웨이를 통해 파일을 업로드하고 완료합니다.
3. 버전이 `ready` 또는 `ready_with_warnings`가 될 때까지 poll합니다.
4. Chat 턴에 `document_refs`를 보냅니다.

```json
{
  "prompt": "Summarize the attached evidence",
  "document_refs": [
    {
      "document_id": "<document-uuid>",
      "version_id": "<version-uuid>"
    }
  ]
}
```

JSON 및 SSE 경로는 고유 참조를 최대 8개 허용합니다. 운영은 검증된 principal과 현재 그룹을
범위가 제한된 PostgreSQL `SECURITY DEFINER` 함수 하나에 전달합니다. 이 함수는 principal이
업로더이거나 구성된 읽기 그룹 구성원일 때만 active, available, 만료되지 않은
`governed_knowledge` 버전 중 active index, live retention, collection scope 및
`knowledge_base` 용도를 충족하는 항목을 반환합니다. Operator 역할은 원시
`document_version` 테이블 읽기 권한을 보유하지 않습니다.

해석기는 요청된 각 인용을 동일한 순서와 exact 정본 양식인
`doc:<document_id>:<version_id>`로 반환해야 합니다. Substituted, reordered, 중복 또는 malformed
프로바이더 결과는 화면 맥락나 검증에 들어가기 전에 실패 시 차단됩니다.

Resolved 참조는 서버가 소유한 화면 맥락과 최종 검증에 들어갑니다. 잘못된 UUID
구문은 400, 해석기가 없는 배포는 501을 반환합니다. 누락된, 사용 불가, held, 실패한,
deleted 또는 다른 principal의 버전은 문서 존재 여부를 노출하지 않도록 동일한 접근
denial을 반환합니다.

Inline vision 이미지는 문서 인제스트와 분리된 범위가 제한된 저장소를 사용합니다. 저장된 이미지는
인증된 principal, 대화 및 opaque 이미지 id로 키를 구성합니다. Operator 턴에는 id,
display 이름 및 검증된 매체 타입만 저장하고 base64 본문은 저장하지 않습니다. Console은 인증된
`GET /me/conversations/{conversation_id}/images/{image_id}`를 통해 이력 이미지를 읽고 표시용 브라우저
객체 URL을 만듭니다. 다른 principal, 대화 또는 알 수 없는 id는 모두 같은 `404` 응답을
반환합니다. Owning 대화를 삭제하면 해당 이미지 행도 cascade로 삭제됩니다.
대화가 활성 상태를 유지해도 각 이미지는 90일 후 만료되며, scheduled user-context
보존 작업이 만료된 이미지 바이트를 독립적으로 삭제합니다. principal은 대화 이미지를 최대
1,000개 또는 256 MiB 중 먼저 도달하는 한도까지만 보관할 수 있습니다. Exact 재시도는 할당량을 중복
소비하지 않으며, 할당량 거절은 턴 메타데이터 저장 전에 `429`를 반환합니다. 이미지는 운영자
턴이 영속해질 때까지 15분 pending 만료를 유지한 뒤 90일 만료로 전환됩니다. Immediate
보상도 실패하면 다음 업로드 또는 보존 통과가 이 짧은 간격 이후 pending 바이트를
삭제합니다.

작성기는 staged 이미지를 파일 이름, 바이트 크기 또는 준비된 라벨을 반복하지 않는 fixed thumbnail로
표시합니다. 포인터 hover, keyboard focus 또는 touch는 shared 툴팁 계층을 통해 뷰포트 범위의 큰
미리 보기를 엽니다. 정규화가 진행 중이면 tile은 shared neutral top-edge shimmer를 사용하며,
reduced-motion 선호 설정은 이 animation을 비활성화합니다. Non-image 파일과 rejected 첨부는
간결한 메타데이터 및 actionable 사유를 유지합니다.

## 이미지 OCR

Standard 추출기는 OCR 전에 이미지 서명을 인식합니다. OCR 프로바이더가 없으면 기존
metadata-only 이미지 버전을 유지합니다. `FDAI_OCR_ENDPOINT`를 설정하면 운영이
`AzureDocumentIntelligenceOcr`을 연결합니다.

1. 구성된 Cognitive Services 대상용 managed-identity 토큰을 얻습니다.
2. HTTPS로 이미지를 `prebuilt-read`에 제출합니다.
3. 암묵적 HTTPS 포트와 명시적 `:443`을 동등하게 취급하면서 `Operation-Location`이 exact
  구성된 출처인지 validate합니다.
4. 구성된 시도 및 시간 한도 안에서 poll합니다.
5. 각 poll 응답을 스트리밍하는 동안 `FDAI_OCR_MAX_RESPONSE_BYTES`를 적용하고 later 조각을
  읽기 전에 중단한 다음 parsed 결과에 줄 및 character 한도를 적용합니다.
6. 범위가 제한된 페이지 줄을 `page:1:line:2` 같은 위치 지정자를 가진 `StructuralUnit`으로 변환합니다.
7. Redirect를 거부하고 신원, 전송 계층, malformed, 실패한, 알 수 없음, cross-origin 또는
  over-budget 실패를 OCR 프로바이더 오류로 정규화합니다.

구성된 OCR 실패는 추출 단계를 실패시키며 searchable 또는 인계 근거를 만들지
않습니다. OCR 텍스트는 신뢰할 수 없는 근거로 유지되며 instruction 또는 도구 권한을 재정의할 수
없습니다.

Terraform은 `document_ocr_endpoint`와 matching `document_ocr_resource_id`, 활성화된 문서
인제스트를 함께 요구합니다. 인제스트 managed 신원에 해당 리소스 범위의 `Cognitive
Services User`만 부여합니다. 빈 엔드포인트는 metadata-only 행동을 유지하고 OCR 역할을 만들지
않습니다.

## 운영 조립

독립 Operator edge는 엄격한 `FDAI_CHANNEL_ATTACHMENTS_ENABLED` 스위치를 소유합니다. 설정하지
않거나 `0`이면 기능을 사용할 수 없으며 첨부 턴은 queue 유입 전에
`422 attachments_unavailable`을 반환합니다. `1`은 완전한 고정 intake origin과 audience, 전용
첨부 credential, 암호화된 절대 scratch 경로, 바이트 상한, principal-manifest digest 및 활성화된
각 프로바이더의 endpoint와 host policy를 요구합니다. 누락되거나 일부만 설정되거나 로컬 및
배포 신원이 혼합된 구성은 채널 consumer가 시작되기 전에 시작을 실패시킵니다.

구성된 edge 바이트 상한은 intake admission 한도와 독립적입니다. 각 벤더 stream은 두 값 중 더
낮은 상한을 사용하므로 intake policy가 커져도 edge download 권한이 조용히 넓어지지 않습니다.

Document Ingestion API 배포 단위는 `fdai-document-channel-intake`를 별도의 내부 전용 Container
App 및 로컬 프로세스로 제공합니다. 이 프로세스는 인제스트 데이터베이스 역할, 정본 문서 객체
저장소, 수명 주기 publisher 및 영속 `state_kv` reservation record를 사용합니다. Live와 ready
probe는 분리되어 있으며, 어댑터를 사용할 수 없거나 감독 중인 outbox task가 중지되면 준비 상태가
닫힙니다. Operator edge는 프로바이더 download와 intake traffic에 별도 HTTP pool을 사용하고,
구성된 scratch 디렉터리 아래의 이름 없는 임시 파일 및 전용 audience credential 하나를
사용합니다. 벤더 첨부 이름에는 경로 구분자, 점만 있는 이름, 제어 문자 또는 서식 문자를 사용할
수 없습니다. Operator의 전송 및 spool 동작은 `attachment_handoff.py`에 유지하고, 재생, 최종 상태
관측 및 semantic context 조정은 `attachment_ingestion.py`에 유지합니다.

Intake는 admission 및 content와 동일한 audience 및 App Role 경계에 인증된 no-op probe를
제공합니다. Edge는 준비 상태를 보고하기 전에 이 probe를 호출합니다. 다음과 같은 보호된 rollout
순서를 사용합니다.

1. Edge의 채널 첨부를 비활성 상태로 유지한 채 내부 intake를 활성화합니다.
2. `FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE`를 노출하는 Entra 애플리케이션에 `Application`
  구성원용 `Document.ChannelAttachment.Submit` App Role을 정의하고 해당 역할만 전용 edge
  서비스 principal에 할당합니다. 이 테넌트 디렉터리 작업에는 권한이 있는 관리자가 필요하며
  Terraform plan 승인에서 추론하지 않습니다.
3. Operator edge에서 첨부를 활성화합니다. 시작 과정은 정확한 audience의 token을 얻고 인증된
  probe가 `204`를 반환하도록 요구합니다. 정의, 할당, audience 또는 client 결속이 없으면 준비
  상태를 닫고 새로 활성화한 edge의 보호된 rollback을 실행합니다.

Intake와 edge의 활성화 및 비활성화 전환은 서로 독립적으로 guard, plan sealing 및 health
verification을 거칩니다. Intake를 edge보다 먼저 활성화하고 intake를 제거하기 전에 edge를
비활성화하는 것이 좋습니다. 로컬 parity는 같은 audience와 정확한 App Role에 명시적 client
credential을 사용합니다. 배포 모드는 구성된 Managed Identity만 허용하고 로컬 secret 설정을
거부합니다.

Protected 인제스트 완료 후 게이트웨이는 실제 민감정보가 제거된 조정기 활동을 타입이 지정된 채널 진행 상황
스냅샷으로 변환 결과할 수 있습니다. 이는 표현만 변경합니다. 첨부 바이트, 용도,
권한 확인, 검사, 최종 인용 검사 및 에이전트 소유권은 변경되지 않으며 진행 상황 텍스트는
instruction 또는 근거 권한이 되지 않습니다.
Running 개정 번호는 요약 텍스트만 표시합니다. 정본 민감정보가 제거된 활동 근거는 protected
인제스트 및 조정기 완료 후 최종 confirmed 개정 번호에 표시됩니다.
진행 상황 메트릭은 잘림 및 최종 전달을 집계할 수 있지만 파일 이름, 문서 id,
인용, 출처 참조, 수집, 채널 id 또는 extracted 내용을 포함하지 않습니다.
Teams card-budget 활동 omission은 메트릭에 생략된 활동 개수 또는 내용을 추가하지 않고
잘림으로 집계됩니다.
Teams canonical-answer clipping도 메트릭에 답변 텍스트 또는 length를 추가하지 않고 잘림으로
집계됩니다. Multibyte serialized 카드 바이트로 더 일찍 잘리는 경우도 포함됩니다. 두 표현
한도 모두 첨부 근거 권한 또는 영속 응답 데이터를 변경하지 않습니다. Slack
canonical-answer clipping 메트릭도 답변 텍스트 또는 length를 보관하지 않습니다.
채널 발행기는 전송 계층 및 확인 응답 처리를 pure 렌더링과 분리합니다. 이 구조적
분리는 protected 인제스트 또는 민감정보 제거 경계를 변경하지 않습니다.

채널 intake는 각 정본 업로드를 완료하고 `document.received`를 publish하며 처리 worker를 직접
호출하지 않습니다. Edge는 인증된 상태 경로를 통해 기존 event pipeline이 만든 최종 버전을
기다립니다. 대기는 고정된 양의 deadline과 범위가 제한된 polling interval을 사용합니다. 시간
초과 시 인용을 반환하지 않으며 inline worker 대체 경로를 실행하지 않습니다.

배포된 handover에서 intake는 타입이 지정된 draft의 upload, document, version, drafted outcome 및
비어 있지 않은 mapping을 검증합니다. Core와 같은 content-addressed governance key를 파생하고 PR
reference가 포함된 matching published receipt가 있어야 `handover_draft_ready=true`로 설정합니다.
증적이 없으면 pending을 유지하며 대체되거나 malformed인 증적은 실패 시 차단됩니다.

첨부가 여러 개인 메시지는 파일마다 통제된 `UploadSession` 하나를 만듭니다. 파일은
독립적인 수명 주기, 보존, 감사 기록을 유지하며 채널 메시지는 저장소 트랜잭션이
아닙니다. 파일 하나가 held 또는 실패한 상태가 되면 턴은 인용을 반환하지 않습니다. 파이프라인이
이미 수락한 형제는 조용히 삭제되지 않고 document-ingestion operations에서 계속 확인할 수
있습니다. 허용, 가져오기, commit 및 최종 상태 관측은 8-file 메시지 상한 안에서 안정적인 ordinal
순서로 실행되므로 반환 인용은 입력 순서를 유지하고 실패한 턴 뒤에 분리된 background poll이
남지 않습니다.

## 실패 행동

| 실패 | 동작 |
|---------|------|
| 누락된 벤더 가져오기 도구 | 인제스트 전에 첨부 거부 |
| 읽기 담당이 `/handover` 제출 | 벤더 download 전에 거부 |
| 첨부 메타데이터 하나라도 바이트 상한 초과 | 첫 fetch 전에 전체 턴 거부 |
| 벤더 메타데이터 크기 mismatch | 거부하고 인용 미생성 |
| Redirect 또는 호스트 mismatch | 토큰 공개 또는 download 전에 거부 |
| 바이트 상한 초과 | 스트림 중단 및 거부 |
| Malware 또는 protected-content 보류 | 인용 없이 반환하고 서술기 미호출 |
| 에이전트 파이프라인이 최종 wait 한계 초과 | Turn 거부, inline 워커 미실행 |
| Intake 최종 증적의 commit digest, id, 크기, hash 또는 용도가 변경됨 | 증적을 수락하지 않고 인용 미반환 |
| 워크로드 App Role 또는 audience 누락 | Edge 준비 상태를 닫고 활성화 전환 차단 |
| 첨부 완료 전 unexpected 실패 | 메시지 점유 release, 정제된 처리 전이 발행, 다음 대기 중 턴 계속 처리 |
| 첨부 완료 후 세션/도구 실패 | 메시지 점유 유지, 범용 오류 한 번 반환, 동일 벤더 메시지 재인제스트 방지 |
| 영속 채널 전달 전 취소 | 취소를 전파하고 메시지 점유 release, 재시도 시 영속 첨부 상태 재사용 |
| OCR 구성된 상태에서 사용 불가 또는 malformed | 추출 실패, searchable 근거 미생성 |
| Web 참조 malformed | 400 반환 |
| Web 해석기 absent | 501 반환 |
| Web 버전이 다른 principal 소유 또는 사용 불가 | 접근 거부 |
| 중복 채널 메시지 | 기존 채널 원장이 repeated 처리 방지 |

채널 게이트웨이는 사용 불가, rejected 및 준비된 결과에 대해 `attachment.ingestion`
전이를 발행합니다. 파일 이름, 출처 참조, 문서 내용 또는 프로바이더 오류는 포함하지
않습니다. Unexpected 턴 실패는 해당 턴으로 격리되며 Slack 또는 Teams 수신 루프를
종료하지 않습니다.

## 검증

Focused 검증은 다음과 같습니다.

```bash
python -m pytest -q --no-cov \
  packages/service-contracts/tests/test_channel_attachment.py \
  packages/service-contracts/tests/test_semantic_turn.py \
  services/document-ingestion-api/tests/test_channel_attachment_http.py \
  services/document-ingestion-api/tests/test_channel_attachment_intake.py \
  services/operator-service/tests/test_channel_attachment_handoff.py \
  services/operator-service/tests/test_channel_edge_pipeline.py \
  services/core-control-plane/tests/core/knowledge/test_governed_document_reader.py \
  services/core-control-plane/tests/test_semantic_turn_processor.py
```

현재 회귀 테스트는 요청 및 증적 digest, 영속 restart replay, content 및 terminal hash 결속,
Slack 및 Teams 대상 제어, 인증된 워크로드 준비 상태, 취소, handover draft 준비 상태, 정확한 참조
상한, Web resolver denial, Core no-widening 조회, 최종 인용 동일성, 이행 소유권, 로컬 parity 및
보호된 배포 rollback을 다룹니다. 배포된 프로바이더 근거와 end-to-end inline vision 테스트는
열린 상태입니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 문서 안전성 및 저장소 | [document-ingestion-ko.md](document-ingestion-ko.md) |
| Conversational 채널 권한 | [operator-console-ko.md](operator-console-ko.md) |
| 소유권 초안 및 병합 수명 주기 | [agent-stewardship-operations-ko.md](agent-stewardship-operations-ko.md) |
| 조직도 가져오기 및 보고 승인 경로 | [사람 보고선 및 승인 라우팅](human-report-lines-and-approval-routing-ko.md) |
| 영속 채널 전달 | [durable-conversation-delivery-ko.md](durable-conversation-delivery-ko.md) |
