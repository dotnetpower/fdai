# Workflow Builder Hardening Review

이 문서는 2026-07-18에 수행한 대화형 Workflow Builder와 workflow별 UI 노출
경로의 비평, 하드닝 결과 및 검증 근거를 기록합니다. 범위는 대화 intent 처리,
private draft 수명주기, WorkflowBinding 경계, WorkflowApp catalog, Operations 메뉴,
영한 문서 및 console localization입니다.

## Design at a glance

대화 결과는 이제 추론 직후 실행 가능한 pipeline으로 취급되지 않습니다. Operator가
plan과 safety posture를 명시적으로 확인하고 structural validation을 통과한 뒤
principal 소유 private `draft`로 저장할 수 있습니다. Draft는 publish, bind, enable,
execute 권한을 갖지 않습니다.

Workflow별 UI는 실행 정의와 분리된 `WorkflowApp` manifest로 등록됩니다. Reader-gated
API는 `published + hub` manifest만 반환하며, console은 Operations의 단일 Workflow
apps hub와 기존 Process journal 및 ViewSpec detail을 재사용합니다. Manifest는 임의
JavaScript, component import, backend route 또는 action button을 선언할 수 없습니다.

## Resolved findings

| # | Critique | Hardening result |
|---:|----------|------------------|
| 1 | Builder가 생성처럼 보이지만 결과를 저장하지 않았습니다. | Validated result를 private `draft`로 저장하는 명시적 action을 추가했습니다. |
| 2 | 자연어 추론 결과가 operator 확인 없이 다음 단계로 진행됐습니다. | `confirm_plan` 단계를 추가했습니다. |
| 3 | 3개를 넘는 action match가 조용히 버려졌습니다. | Bounded proposal 초과를 confirmation에서 경고합니다. |
| 4 | `do not restart` 같은 부정문이 mutation으로 매칭될 수 있었습니다. | Negated synonym은 action score에서 제외하고 fail closed합니다. |
| 5 | Shadow, failure stop, promotion threshold가 완료 전 보이지 않았습니다. | `confirm_safety` 단계에서 safety posture를 명시합니다. |
| 6 | Operator가 workflow의 금지 범위를 대화에서 기록할 수 없었습니다. | Safety 단계의 free text를 `anti_scope`로 보존합니다. |
| 7 | `Dry test`가 실행 simulation처럼 오해될 수 있었습니다. | UI와 문서를 `Structural validation`으로 수정했습니다. |
| 8 | Validation success가 실행 가능성을 암시했습니다. | 실행 및 simulation을 하지 않는다는 문구를 결과에 명시했습니다. |
| 9 | Catalog workflow를 draft로 옮길 때 step `params`가 유실됐습니다. | Draft model, clone, catalog projection, YAML assembly에서 params를 보존합니다. |
| 10 | Params 객체가 shallow copy되어 draft 간 참조를 공유할 수 있었습니다. | `cloneForm`이 step params를 deep copy합니다. |
| 11 | Private draft 생성 성공 응답을 무검증 cast로 받을 위험이 있었습니다. | definition id, workflow name, lifecycle을 fail-closed decode합니다. |
| 12 | Draft 저장과 publish 의미가 UI에서 섞일 수 있었습니다. | Save private draft와 GitHub catalog proposal을 별도 command로 분리했습니다. |
| 13 | 저장된 draft가 runnable로 오해될 수 있었습니다. | UI와 문서에 Operations 미노출 및 실행 불가를 명시하고 backend gate를 재검증했습니다. |
| 14 | Schedule binding이 cron 없이 저장될 수 있었습니다. | `cron_expression`과 `timezone`을 함께 요구합니다. |
| 15 | Signal binding이 signal type 없이 저장될 수 있었습니다. | `signal_type`을 필수로 검증합니다. |
| 16 | Schedule binding이 signal field도 함께 가질 수 있었습니다. | Trigger별 상호 배타 필드를 server boundary에서 차단합니다. |
| 17 | Signal binding이 schedule field도 함께 가질 수 있었습니다. | 혼합 payload를 `400`으로 거부합니다. |
| 18 | `deck_open` binding에 trigger-specific field가 섞일 수 있었습니다. | Schedule 및 signal field를 모두 차단합니다. |
| 19 | Workflow 실행 정의와 별도 UI의 discovery 책임이 정의되지 않았습니다. | 독립 `WorkflowApp` manifest 계약을 추가했습니다. |
| 20 | `ViewSpec.route`만으로 메뉴가 생길 것처럼 해석될 수 있었습니다. | ViewSpec은 run detail, WorkflowApp은 discovery라는 책임을 문서화했습니다. |
| 21 | 생성 workflow마다 compiled panel을 추가하면 메뉴가 폭증합니다. | Operations에 단일 Workflow apps hub만 등록했습니다. |
| 22 | Runtime manifest가 임의 frontend code를 주입할 위험이 있었습니다. | Schema에 executable code 필드가 없고 generic renderer만 사용합니다. |
| 23 | Manifest가 unknown workflow를 참조할 수 있었습니다. | Catalog load 시 `workflow_ref`를 cross-reference합니다. |
| 24 | Manifest가 unknown ViewSpec을 참조할 수 있었습니다. | Catalog load 시 `view_ref`를 cross-reference합니다. |
| 25 | ViewSpec과 workflow가 서로 다른 workflow를 가리킬 수 있었습니다. | 두 참조가 동일 workflow로 resolve되는지 검증합니다. |
| 26 | Duplicate app id가 route identity를 모호하게 만들 수 있었습니다. | Startup catalog validation에서 중복 id를 거부합니다. |
| 27 | 한 workflow에 app manifest가 여러 개 생길 수 있었습니다. | Duplicate `workflow_ref`를 거부합니다. |
| 28 | Manifest가 임의 route를 선언할 수 있었습니다. | Backend가 `/workflow-apps/{id}`를 파생하고 client가 일치를 재검증합니다. |
| 29 | Draft 또는 shadow app이 Operations에 노출될 수 있었습니다. | API는 `published + hub`만 반환합니다. |
| 30 | Reader API에 더 높은 audience처럼 보이는 manifest가 노출될 수 있었습니다. | 첫 버전 audience를 `reader`로 고정하고 client도 재검증합니다. |
| 31 | App이 다른 navigation group을 사칭할 수 있었습니다. | Manifest group을 `operations`로 고정합니다. |
| 32 | API의 count와 item 수가 모순될 수 있었습니다. | Frontend decoder가 exact count를 요구합니다. |
| 33 | API가 duplicate app 또는 workflow를 반환할 수 있었습니다. | Client boundary에서도 두 identity 집합의 uniqueness를 검증합니다. |
| 34 | Localized label 및 description이 비거나 malformed일 수 있었습니다. | Schema와 client decoder가 `en` 및 `ko` non-empty 값을 요구합니다. |
| 35 | Workflow app에 canonical clean URL이 없었습니다. | `/workflow-apps/{app_id}` route와 router regression test를 추가했습니다. |
| 36 | 새 메뉴가 Operations 순서에서 빠질 수 있었습니다. | Exact panel order test에 Workflow apps를 고정했습니다. |
| 37 | App detail이 전체 Process를 client에서 필터링할 수 있었습니다. | `workflow_ref` query를 server projection에 전달합니다. |
| 38 | 별도 UI가 Process audit trail을 우회할 수 있었습니다. | Run row는 기존 `/processes/{process_id}` journal 및 ViewSpec detail로 연결됩니다. |
| 39 | 새 화면이 narrator context와 glossary를 제공하지 않을 수 있었습니다. | App manifest records, facts, Process 및 ViewSpec glossary를 publish합니다. |
| 40 | 구현과 영한 설계 문서가 다른 상태 머신과 dry-run 용어를 유지했습니다. | 두 문서의 단계, draft lifecycle, structural validation, app exposure를 동기화했습니다. |
| 41 | Catalog가 validation 이후 바뀌어 draft save가 거부되면 UI가 `HTTP 422`만 표시했습니다. | Structured issue message를 최대 3개까지 보존해 수정할 원인을 보여줍니다. |

## Remaining work

다음 항목은 이번 변경에서 실행 권한이나 schema를 성급하게 넓히지 않기 위해 남겼습니다.

- Chat에서 step params를 새로 입력하는 parameter-schema-driven editor
- `wait`, `approval`, `decision`, `parallel`, `gate` step 대화 생성
- Step 삭제, 재정렬, 중간 삽입 및 failure branch 편집
- 대화 draft의 session 복구와 URL deep link
- 한국어 intent synonym 및 전체 builder string catalog 전환
- Structural validation과 구분되는 실제 behavior simulation 및 what-if
- Reader 이외 audience를 위한 server-derived role-aware manifest filtering
- Workflow app landing에서 run detail ViewSpec을 inline으로 선택하는 split view

## Verification

검증 결과는 다음과 같습니다.

- Console: 93 test files, 737 tests passed.
- Console production build: Vite build 및 entry bundle check passed.
- Backend focused suites: 59 tests passed.
- Python: Ruff check, Ruff format check, strict mypy passed for changed modules.
- Documentation: translation SHA, punctuation, and doc links passed.
- Localization: 7 English/Korean catalog pairs passed parity validation.
- Catalog and route boundaries: WorkflowApp catalog, Process view API, route collision,
  binding validation tests passed.

전체 catalog validator의 embedded full pytest는 이 변경과 무관한 동시 scripts
재배치의 root-layout test 한 건 때문에 실패했습니다. 같은 run에서 8147 tests passed,
48 tests skipped, 1 scripts-layout test failed였습니다. Global Ruff format은 기존
Alembic migration 3개를 별도로 보고했으며, 이번에 추가한 WorkflowApp loader는
format check를 통과했습니다.
