---
title: Offline release trust ceremony
summary: Root private key를 CI 또는 operator에게 노출하지 않고 FDAI public offline-kit trust root를 만들고 rotation합니다.
translation_of: offline-trust-ceremony.md
translation_source_sha: e1de8711594ee123e5b366a3e5cb35e35b8b3f00
translation_revised: 2026-07-25
---

# Offline release trust ceremony

Disconnected FDAI release의 첫 public trust root를 만들거나 기존 root를 rotation할 때 이 runbook을
사용합니다. Ceremony는 release authority를 확립합니다. Deployment approval이 아니며 test key,
repository secret 또는 operator-supplied root를 사용하면 안 됩니다.

> **현재 상태:** Production root는 아직 packaged되지 않았습니다. Ceremony와 client integration이
> 완료되기 전까지 `fdaictl provision inspect`는 offline kit를 `candidate` 또는 `fail`로 올바르게
> 보고하며 file 존재만으로 `verified`를 반환하지 않습니다.

## 역할과 prerequisite

Ceremony 일정 전에 담당자를 지정합니다.

- **Ceremony coordinator:** Agenda, evidence record, stop decision을 담당합니다. 모든 root key를
  보유하지 않습니다.
- **Root key holder:** 승인된 root threshold에 필요한 offline root key를 독립적으로 관리합니다.
  Threshold는 최소 2를 권장하며 key holder 수는 threshold보다 많게 구성하는 것이 좋습니다.
- **Release security reviewer:** Public root merge 전에 role 분리, algorithm, threshold, expiry,
  rotation evidence를 확인합니다.
- **Witness:** Private key material을 취급하지 않고 device identifier, public key fingerprint,
  시간, deviation을 기록합니다.
- **Release engineer:** Root가 확립된 뒤 delegated targets, snapshot, timestamp signing을
  구성합니다. Root private key를 받지 않습니다.

시작 전에 다음을 승인하고 기록합니다.

- TUF specification과 Python-TUF major version.
- Root, targets, snapshot, timestamp role의 threshold와 expiry 기간.
- 독립된 offline device, entropy source, encrypted backup media, physical custody.
- Key holder 분실, compromise 또는 unavailable 상황의 recovery policy.
- Clean network-isolated ceremony environment와 별도의 verification device.
- Public `root.json`을 package할 정확한 FDAI release와 wheel path.

Participant, device, 승인된 threshold, expiry, backup destination 또는 independent verification
device 중 하나라도 사용할 수 없으면 중지합니다.

## Threat control

| # | Risk | 필수 control |
|---|------|--------------|
| 1 | Test key가 production authority가 됨 | Witnessed ceremony에서 새 production key만 생성 |
| 2 | 한 명이 root를 발행할 수 있음 | 승인된 multi-key threshold와 independent custody 사용 |
| 3 | CI가 root private key를 받음 | Offline environment에서 public key와 signed metadata만 export |
| 4 | Operator가 root를 바꿈 | Public root를 wheel에 package하고 CLI root override를 추가하지 않음 |
| 5 | Stale repository가 client를 freeze함 | Timestamp와 snapshot metadata에 bounded expiry를 적용하고 renewal monitor |
| 6 | 오래된 signed release가 client를 rollback함 | Metadata version을 단조 증가시킴 |
| 7 | 서로 다른 release metadata가 섞임 | TUF snapshot/timestamp binding과 exact target hash 사용 |
| 8 | Root rotation이 client를 lockout함 | Root를 한 version씩 publish하고 old/new threshold를 모두 만족 |
| 9 | Compromised online key가 영구 authority가 됨 | Root를 offline에 유지하고 delegated key를 root authority로 rotation |
| 10 | 누락 artifact가 review를 빠져나감 | TUF 이후에도 exact manifest file set과 SHA-256 verification 유지 |
| 11 | 잘못된 CLI 또는 platform이 kit를 사용함 | `OfflineKitManifest`의 exact CLI version과 platform binding 유지 |
| 12 | Symlink 또는 path replacement가 content를 바꿈 | No-follow descriptor hashing과 regular-file check 유지 |
| 13 | Private material이 evidence로 유출됨 | Public fingerprint와 signature만 기록하고 모든 output scan |
| 14 | Client update 전에 root가 expire됨 | Expiry를 owned renewal window가 있는 release blocker로 관리 |
| 15 | Ceremony deviation이 묵인됨 | 승인된 policy가 다루지 않으면 중지하고 evidence 보존 후 재일정 |

## Initial root 생성

1. 각 offline device가 clean, disconnected, time-correct 상태이며 coordinator와 witness가
   관찰하는지 확인합니다.
2. 각 root key holder는 할당된 offline device에서 독립된 root key를 생성합니다. Private key는
   해당 device 또는 승인된 encrypted backup media에 유지하고 public key만 export합니다.
3. Isolated metadata workstation에서 다음 initial TUF root metadata를 생성합니다.
   - version `1`;
   - 승인된 future expiry;
   - 모든 root public key와 승인된 root threshold;
   - targets, snapshot, timestamp role의 분리된 public key와 threshold;
   - release repository가 요구하는 consistent-snapshot behavior.
4. Unsigned root metadata를 approved media로 각 root key holder에게 전달합니다. 각 holder는 전체
   canonical metadata를 확인하고 fingerprint 및 policy 비교 후에만 sign합니다.
5. Isolated metadata workstation에서 signature를 assemble합니다. Root threshold 충족과 unexpected
   key, role, threshold, extension, private value 부재를 확인합니다.
6. 별도 verification device에서 Python-TUF로 signed metadata를 load하고 structure, expiry, version,
   key id, role threshold, signature를 독립적으로 검증합니다.
7. Public ceremony evidence를 생성합니다. Signed `root.json` hash, public fingerprint, threshold,
   expiry, Python-TUF version, participant, device, verification outcome을 기록합니다. Private key
   byte, PIN, recovery phrase 또는 encrypted key archive는 기록하지 않습니다.
8. Independent custody 아래 encrypted backup을 만들고 isolated spare device에서 restore를
   검증한 뒤 temporary private-key copy를 안전하게 삭제합니다.

Signature mismatch, unexpected key, missing threshold signature, malformed metadata 또는 evidence의
private value가 발견되면 ceremony를 중지합니다. Unsigned 또는 partially signed candidate를
폐기하고 승인된 clean media에서 다시 시작합니다.

## Package와 delegation

1. 검증된 public `root.json`만 reviewed upstream pull request를 통해 FDAI wheel package data에
   추가합니다. Release evidence에 SHA-256을 pin합니다.
2. `fdaictl provision inspect`가 해당 package resource에서 Python-TUF를 bootstrap하도록 연결합니다.
   `--release-root`, environment-variable root, network-fetched initial root, downstream override를
   추가하지 않습니다.
3. Targets, snapshot, timestamp private key는 승인된 release signing service에 보관합니다. CI는
   delegated online key에만 접근하며 root private key에는 접근하지 않습니다.
4. 각 offline kit를 TUF target으로 build합니다. FDAI wheel, transitive wheel, signed deployment
   bundle, Terraform binary와 provider mirror, OPA, SBOM, exact-content manifest를 포함합니다.
5. Versioned root metadata, delegated metadata, target을 approved release channel로 publish합니다.
   Sequential client update에 필요한 이전 public root version을 유지합니다.
6. Clean checkout에서 wheel을 build하고 content를 검사합니다. Expected public root가 있으며
   private key, test key, signing config 또는 ceremony backup이 없는지 확인합니다.

## Acceptance drill

Preexisting FDAI trust state가 없는 disconnected disposable host를 사용합니다.

1. Release wheel을 설치하고 release-signed kit를 inspect합니다. TUF와 exact-content verification
   후 `status=ready`, exit `0`, `artifact.offline-kit=verified`를 요구합니다.
2. Target byte 하나를 바꿉니다. Artifact 실행 전에 reject되어야 합니다.
3. Expired timestamp 또는 snapshot metadata를 제시합니다. Clock 또는 expiry override 없이
   reject되어야 합니다.
4. 더 새로운 trusted version 뒤에 이전 metadata version을 제시합니다. Rollback을 reject해야 합니다.
5. 두 release의 metadata 또는 target을 섞습니다. Snapshot 또는 hash rejection이 필요합니다.
6. CLI version 또는 platform tag를 바꿉니다. Compatibility rejection이 필요합니다.
7. Unlisted file 추가, listed file 제거, artifact symlink 교체를 각각 수행합니다. 모두 reject해야 합니다.
8. 모든 network access를 제거하고 verification을 반복합니다. Public endpoint 없이 성공해야 합니다.

Sanitized command output, public metadata, artifact digest, terminal status를 release evidence record에
저장합니다. Valid kit가 통과하고 모든 negative case가 실패해야 drill이 완료됩니다.

## Root rotation

1. Trusted version $N$에서 root version $N+1$을 만듭니다. 승인된 rotation policy에 따라 key를
   추가 또는 제거하고 threshold와 expiry를 갱신합니다.
2. Version $N$의 root threshold와 새 version $N+1$ threshold를 모두 만족하는 충분한 key로
   version $N+1$을 sign합니다.
3. 각 intermediate root version을 publish합니다. Deployed client가 필요한 version을 건너뛰지 않습니다.
4. 새 root가 필요한 target을 release하기 전에 지원하는 모든 packaged root에서 newest root까지
   한 version씩 client update를 검증합니다.
5. 지원 client가 update할 수 있고 recovery evidence가 완료된 후에만 retired private key를 revoke하고
   destroy합니다.

Compromise가 발생하면 delegated signing을 중지하고 새 target을 publish하지 않으며 승인된 emergency
root rotation policy를 실행하고 public forensic evidence를 보존합니다. Normal deployment approval은
root threshold 또는 metadata expiry를 면제할 수 없습니다.

## Exit criteria

Public offline trust bootstrap은 다음 항목을 모두 확인해야 완료됩니다.

- [ ] Initial production `root.json`이 threshold-signed되고 independently verified됨.
- [ ] Root private key와 backup이 source control, CI, cloud secret, operator workstation 밖에 유지됨.
- [ ] Wheel이 verified public root만 package하고 CLI에 trust-root override가 없음.
- [ ] Delegated signing이 current expiring targets, snapshot, timestamp metadata를 생성함.
- [ ] Clean host에서 valid disconnected verification이 통과함.
- [ ] Tamper, expiry, rollback, mix-and-match, wrong-version, wrong-platform, extra-file, symlink drill이
  모두 fail closed함.
- [ ] 지원하는 모든 packaged root에서 sequential root rotation이 검증됨.
- [ ] Public ceremony와 release evidence가 named owner 및 renewal date와 함께 archive됨.
