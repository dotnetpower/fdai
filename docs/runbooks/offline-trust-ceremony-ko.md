---
title: Offline release trust ceremony
summary: Root private key를 CI 또는 operator에게 노출하지 않고 FDAI public offline-kit trust root를 만들고 rotation합니다.
translation_of: offline-trust-ceremony.md
translation_source_sha: e1de8711594ee123e5b366a3e5cb35e35b8b3f00
translation_revised: 2026-08-11
---

# Offline release trust 의식

Disconnected FDAI release의 첫 공개 trust 루트를 만들거나 기존 루트를 교대할 때 이 런북을
사용합니다. 의식은 release 권한을 확립합니다. 배포 승인이 아니며 테스트 키,
저장소 시크릿 또는 operator-supplied 루트를 사용하면 안 됩니다.

> **현재 상태:** 운영 루트는 아직 packaged되지 않았습니다. 의식과 클라이언트 통합이
> 완료되기 전까지 `fdaictl provision inspect`는 offline 키트를 `candidate` 또는 `fail`로 올바르게
> 보고하며 파일 존재만으로 `verified`를 반환하지 않습니다.

## 역할과 선행 조건

의식 일정 전에 담당자를 지정합니다.

- **의식 조정기:** Agenda, 근거 기록, stop 결정을 담당합니다. 모든 루트 키를
  보유하지 않습니다.
- **루트 키 보유자:** 승인된 루트 임계값에 필요한 offline 루트 키를 독립적으로 관리합니다.
  임계값은 최소 2를 권장하며 키 보유자 수는 임계값보다 많게 구성하는 것이 좋습니다.
- **release security 검토자:** 공개 루트 병합 전에 역할 분리, algorithm, 임계값, 만료,
  교대 근거를 확인합니다.
- **입회자:** 비공개 키 자료를 취급하지 않고 장치 식별자, 공개 키 지문,
  시간, deviation을 기록합니다.
- **release engineer:** 루트가 확립된 뒤 delegated targets, 스냅샷, 시각 서명을
  구성합니다. 루트 비공개 키를 받지 않습니다.

시작 전에 다음을 승인하고 기록합니다.

- TUF 명세와 Python-TUF major 버전.
- 루트, targets, 스냅샷, 시각 역할의 임계값과 만료 기간.
- 독립된 offline 장치, entropy 출처, encrypted 백업 매체, physical 보관.
- Key 보유자 분실, 침해 또는 사용 불가 상황의 복구 정책.
- Clean network-isolated 의식 환경과 별도의 검증 장치.
- 공개 `root.json`을 패키지할 정확한 FDAI release와 휠 경로.

Participant, 장치, 승인된 임계값, 만료, 백업 대상 또는 독립적인 검증
장치 중 하나라도 사용할 수 없으면 중지합니다.

## Threat 컨트롤

| # | Risk | 필수 컨트롤 |
|---|------|--------------|
| 1 | 테스트 키가 운영 권한이 됨 | Witnessed 의식에서 새 운영 키만 생성 |
| 2 | 한 명이 루트를 발행할 수 있음 | 승인된 multi-key 임계값과 독립적인 보관 사용 |
| 3 | CI가 루트 비공개 키를 받음 | Offline 환경에서 공개 키와 signed 메타데이터만 내보내기 |
| 4 | Operator가 루트를 바꿈 | 공개 루트를 휠에 패키지하고 CLI 루트 재정의를 추가하지 않음 |
| 5 | Stale 저장소가 클라이언트를 freeze함 | 시각과 스냅샷 메타데이터에 범위가 제한된 만료를 적용하고 갱신 monitor |
| 6 | 오래된 signed release가 클라이언트를 롤백함 | 메타데이터 버전을 단조 증가시킴 |
| 7 | 서로 다른 release 메타데이터가 섞임 | TUF 스냅샷/시각 연결과 exact 대상 해시 사용 |
| 8 | 루트 교대가 클라이언트를 lockout함 | 루트를 한 버전씩 publish하고 old/new 임계값을 모두 만족 |
| 9 | Compromised online 키가 영구 권한이 됨 | 루트를 offline에 유지하고 delegated 키를 루트 권한으로 교대 |
| 10 | 누락 산출물이 검토를 빠져나감 | TUF 이후에도 exact 매니페스트 파일 집합과 SHA-256 검증 유지 |
| 11 | 잘못된 CLI 또는 platform이 키트를 사용함 | `OfflineKitManifest`의 exact CLI 버전과 platform 연결 유지 |
| 12 | Symlink 또는 경로 replacement가 내용을 바꿈 | No-follow 서술자 hashing과 regular-file 검사 유지 |
| 13 | 비공개 자료가 근거로 유출됨 | 공개 지문과 서명만 기록하고 모든 출력 검사 |
| 14 | 클라이언트 갱신 전에 루트가 expire됨 | 만료를 owned 갱신 구간이 있는 release 차단 요인으로 관리 |
| 15 | 의식 deviation이 묵인됨 | 승인된 정책이 다루지 않으면 중지하고 근거 보존 후 재일정 |

## Initial 루트 생성

1. 각 offline 장치가 clean, disconnected, time-correct 상태이며 조정기와 입회자가
   관찰하는지 확인합니다.
2. 각 루트 키 보유자는 할당된 offline 장치에서 독립된 루트 키를 생성합니다. 비공개 키는
   해당 장치 또는 승인된 encrypted 백업 매체에 유지하고 공개 키만 내보내기합니다.
3. Isolated 메타데이터 workstation에서 다음 initial TUF 루트 메타데이터를 생성합니다.
   - 버전 `1`;
   - 승인된 future 만료;
   - 모든 루트 공개 키와 승인된 루트 임계값;
   - targets, 스냅샷, 시각 역할의 분리된 공개 키와 임계값;
   - release 저장소가 요구하는 consistent-snapshot 행동.
4. Unsigned 루트 메타데이터를 approved 매체로 각 루트 키 보유자에게 전달합니다. 각 보유자는 전체
   정본 메타데이터를 확인하고 지문 및 정책 비교 후에만 sign합니다.
5. Isolated 메타데이터 workstation에서 서명을 assemble합니다. 루트 임계값 충족과 unexpected
   키, 역할, 임계값, 확장, 비공개 값 부재를 확인합니다.
6. 별도 검증 장치에서 Python-TUF로 signed 메타데이터를 부하하고 structure, 만료, 버전,
   키 id, 역할 임계값, 서명을 독립적으로 검증합니다.
7. 공개 의식 근거를 생성합니다. Signed `root.json` 해시, 공개 지문, 임계값,
   만료, Python-TUF 버전, participant, 장치, 검증 결과를 기록합니다. 비공개 키
   바이트, PIN, 복구 문구 또는 encrypted 키 보관은 기록하지 않습니다.
8. 독립적인 보관 아래 encrypted 백업을 만들고 isolated spare 장치에서 복원을
   검증한 뒤 temporary private-key copy를 안전하게 삭제합니다.

서명 mismatch, unexpected 키, 누락된 임계값 서명, malformed 메타데이터 또는 근거의
비공개 값이 발견되면 의식을 중지합니다. Unsigned 또는 partially signed 후보를
폐기하고 승인된 clean 매체에서 다시 시작합니다.

## 패키지와 위임

1. 검증된 공개 `root.json`만 검토된 업스트림 pull 요청을 통해 FDAI 휠 패키지 데이터에
   추가합니다. release 근거에 SHA-256을 pin합니다.
2. `fdaictl provision inspect`가 해당 패키지 리소스에서 Python-TUF를 초기화하도록 연결합니다.
   `--release-root`, environment-variable 루트, network-fetched initial 루트, 다운스트림 재정의를
   추가하지 않습니다.
3. Targets, 스냅샷, 시각 비공개 키는 승인된 release 서명 서비스에 보관합니다. CI는
   delegated online 키에만 접근하며 루트 비공개 키에는 접근하지 않습니다.
4. 각 offline 키트를 TUF 대상으로 빌드합니다. FDAI 휠, transitive 휠, signed 배포
   번들, Terraform binary와 프로바이더 mirror, OPA, SBOM, exact-content 매니페스트를 포함합니다.
5. Versioned 루트 메타데이터, delegated 메타데이터, 대상을 approved release 채널로 publish합니다.
   순차 클라이언트 갱신에 필요한 이전 공개 루트 버전을 유지합니다.
6. Clean 체크아웃에서 휠을 빌드하고 내용을 검사합니다. 예상 공개 루트가 있으며
   비공개 키, 테스트 키, 서명 구성 또는 의식 백업이 없는지 확인합니다.

## Acceptance 훈련

Preexisting FDAI trust 상태가 없는 disconnected disposable 호스트를 사용합니다.

1. release 휠을 설치하고 release-signed 키트를 inspect합니다. TUF와 exact-content 검증
   후 `status=ready`, exit `0`, `artifact.offline-kit=verified`를 요구합니다.
2. 대상 바이트 하나를 바꿉니다. 산출물 실행 전에 거부되어야 합니다.
3. 만료된 시각 또는 스냅샷 메타데이터를 제시합니다. 시계 또는 만료 재정의 없이
   거부되어야 합니다.
4. 더 새로운 trusted 버전 뒤에 이전 메타데이터 버전을 제시합니다. Rollback을 거부해야 합니다.
5. 두 release의 메타데이터 또는 대상을 섞습니다. 스냅샷 또는 해시 거절이 필요합니다.
6. CLI 버전 또는 platform tag를 바꿉니다. 호환성 거절이 필요합니다.
7. Unlisted 파일 추가, listed 파일 제거, 산출물 symlink 교체를 각각 수행합니다. 모두 거부해야 합니다.
8. 모든 네트워크 접근을 제거하고 검증을 반복합니다. 공개 엔드포인트 없이 성공해야 합니다.

정제된 명령 출력, 공개 메타데이터, 산출물 다이제스트, 최종 상태를 release 근거 기록에
저장합니다. Valid 키트가 통과하고 모든 부정 사례가 실패해야 훈련이 완료됩니다.

## 루트 교대

1. Trusted 버전 $N$에서 루트 버전 $N+1$을 만듭니다. 승인된 교대 정책에 따라 키를
   추가 또는 제거하고 임계값과 만료를 갱신합니다.
2. 버전 $N$의 루트 임계값과 새 버전 $N+1$ 임계값을 모두 만족하는 충분한 키로
   버전 $N+1$을 sign합니다.
3. 각 intermediate 루트 버전을 publish합니다. Deployed 클라이언트가 필요한 버전을 건너뛰지 않습니다.
4. 새 루트가 필요한 대상을 release하기 전에 지원하는 모든 packaged 루트에서 newest 루트까지
   한 버전씩 클라이언트 갱신을 검증합니다.
5. 지원 클라이언트가 갱신할 수 있고 복구 근거가 완료된 후에만 retired 비공개 키를 철회하고
   destroy합니다.

침해가 발생하면 delegated 서명을 중지하고 새 대상을 publish하지 않으며 승인된 emergency
루트 교대 정책을 실행하고 공개 forensic 근거를 보존합니다. Normal 배포 승인은
루트 임계값 또는 메타데이터 만료를 면제할 수 없습니다.

## Exit criteria

공개 offline trust 초기화는 다음 항목을 모두 확인해야 완료됩니다.

- [ ] Initial 운영 `root.json`이 threshold-signed되고 independently 검증된됨.
- [ ] 루트 비공개 키와 백업이 출처 컨트롤, CI, cloud 시크릿, 운영자 workstation 밖에 유지됨.
- [ ] 휠이 검증된 공개 루트만 패키지하고 CLI에 trust-root 재정의가 없음.
- [ ] Delegated 서명이 현재 expiring targets, 스냅샷, 시각 메타데이터를 생성함.
- [ ] Clean 호스트에서 valid disconnected 검증이 통과함.
- [ ] Tamper, 만료, 롤백, mix-and-match, wrong-version, wrong-platform, extra-file, symlink 훈련이
  모두 실패 시 차단함.
- [ ] 지원하는 모든 packaged 루트에서 순차 루트 교대가 검증됨.
- [ ] 공개 의식과 release 근거가 named 소유자 및 갱신 date와 함께 보관됨.
