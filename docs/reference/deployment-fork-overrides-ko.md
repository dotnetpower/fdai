---
title: 배포 포크 재정의
translation_of: deployment-fork-overrides.md
translation_source_sha: 001655c5e5480e9e939030934c56bd38a3643ba1
translation_revised: 2026-09-07
---

# 배포 포크 재정의

이 참조 문서는 포크가 소유하는 지원 배포 입력을 설명합니다. FDAI는 고객에 종속되지 않으며,
포크는 `core/`를 변경하지 않고 배포를 사용자 지정합니다.

## 재정의 지점

포크는 다음 항목을 구성할 수 있습니다.

- 리전 및 규정 준수 재정의를 포함한 자체 `llm-registry.yaml`을 제공합니다.
- 포크 구독을 가리키는 `AZURE_TENANT_ID` 및 `AZURE_SUBSCRIPTION_ID` 환경 값을 제공합니다.
  업스트림 저장소는 해당 값을 저장하지 않습니다.
- 포크 소유 `CrossCheckModel` 구현을 조립 루트에 바인딩하여 추가 LLM 프로바이더를 등록합니다.
  [혼합 모델 계열 전략](../roadmap/architecture/llm-strategy-ko.md#mixed-model-family-strategies)에
  설명된 `azure-foundry`, `external` 또는 `hil-only` 전략을 사용합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 로컬 및 배포 동등성 | [개발 및 배포 동등성](../roadmap/deployment/dev-and-deploy-parity-ko.md) |
