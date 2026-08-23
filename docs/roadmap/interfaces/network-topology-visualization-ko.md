---
title: 네트워크 토폴로지 시각화
translation_of: network-topology-visualization.md
translation_source_sha: fc0bb21ca9e22f90e0645079698e27bfdb4dd08b
translation_revised: 2026-08-23
---
# 네트워크 토폴로지 시각화

이 문서는 FDAI 아키텍처 생성 다이어그램과 읽기 전용 Console 아키텍처 경로가 공유하는
네트워크 의미 및 표현 계약을 소유합니다. 두 화면이 경계, 연결, 트래픽 경로, 라우팅 의도 및
보안 검사를 하나의 고정된 어휘로 나타내면서도 작성된 설계 의도와 관측된 인벤토리 근거를
분리합니다.

> **권한 경계:** 다이어그램은 예상 또는 관측된 토폴로지를 설명합니다. 도달 가능성을 입증하거나
> 네트워크 또는 실행 권한을 부여하지 않으며 추론한 경로를 관측된 사실로 바꾸지 않습니다.
>
> **프로바이더 범위:** 어휘는 클라우드 프로바이더 중립입니다. Azure가 유일하게 구현된 아이콘 및
> 인벤토리 어댑터이므로 Azure 리소스 타입에 첫 번째 완전한 시각 매핑을 제공합니다.

## 설계 요약

정적 컴파일러는 명시적 토폴로지와 라우팅 의도를 가진 작성된 네트워크 프로필을 받습니다.
Console은 인벤토리 리소스와 타입이 지정된 관계만으로 범위가 제한된 네트워크 포커스 변환 결과를
만듭니다. 두 화면은 같은 정본 네트워크 역할과 연결 의미를 가져오지만 별도 계약을 사용합니다.
작성된 다이어그램은 `expected`이고 Console 토폴로지는 인벤토리 증적에 따라 `observed`, `stale`,
`partial` 또는 `unknown`입니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 공유 네트워크 어휘 및 작성 계약 | implemented | `packages/network-topology-contracts`, 네트워크 스키마 및 검증, 포커스 패키지 및 컴파일러 테스트 | 의존성이 없는 어휘를 공유하면서 작성된 `expected` 상태와 관측 근거 규칙은 분리합니다. |
| 네트워크 참조 배치 및 Azure 아이콘 범위 | implemented | `layout/elk.ts`, 검토된 아이콘 매핑과 digest로 고정한 공식 Azure SVG 14개, 정본 이중 언어 fixture | 네트워크 프로필은 기존 배포 다이어그램의 배치 동작을 바꾸지 않고 압축 복합 배치를 추가합니다. 알 수 없는 리소스 타입은 매핑하지 않습니다. |
| Console 2D 포커스, 경로 추적 및 내보내기 | implemented | `architecture-network-{focus,map,tools,icons}.ts*`, 경로 통합, 집중 Console 및 세 viewport 검사 | 이 모드는 기존의 권위 있는 인벤토리 응답을 사용하고 매핑된 경우 검토된 공식 아이콘을 사용하며 타입이 지정된 관계만 추적하고 식별자가 없는 하나의 SVG 소스를 SVG 또는 PNG로 내보냅니다. |
| Console 온톨로지 인스턴스 네트워크 컨텍스트 | implemented | `ontology-instance-graph.{model.ts,tsx}`, `ontology-instance-resource-icons.ts`, 포커스 테스트, Console 타입 검사와 운영 빌드, 인증된 세 화면 크기 검사 | 선택한 분기는 피어 VNet의 분기를 확장하지 않고 VNet, Subnet, Private Endpoint 및 NIC 계층을 표현합니다. 상호 피어링은 저장된 두 레코드를 유지하면서 하나의 항목을 공유합니다. 마우스 휠 확대 및 축소, 기본 전체 화면, 빈 캔버스 이동 및 접을 수 있는 상세 패널이 그래프 작업 영역을 보존합니다. 현재 활성 스냅샷 감사에서 Resource 유형 58개 중 55개는 검토된 아이콘을 사용하고 3개는 명시적인 일반 대체 아이콘을 사용합니다. |
| 무결성, 접근성 및 시각 회귀 | implemented | 정적 컴파일러 테스트 107개 통과, 정확한 `1600x900` 산출물 검사, 세 viewport 순차 Playwright 1개 통과 | 합성 브라우저 근거는 표현 동작만 입증합니다. 관리되는 런타임 검증을 주장하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-22 | not-started | 런타임 동작을 변경하지 않고 네트워크 토폴로지 시각화를 위한 집중 소유 경계를 채택했습니다. | `current change`; 이 소유 문서입니다. | 각 범위 행을 구현하고 포커스 테스트를 통과한 뒤 상태를 높입니다. |
| 2026-08-22 | implemented | 공유 프로바이더 중립 어휘, 작성된 네트워크 프로필과 주석, 검토된 공식 Azure 아이콘 매핑, 압축 네트워크 배치와 무결성 검사, 정본 이중 언어 hub-spoke 참조, 그리고 필터, 타입 지정 경로 추적, 키보드 상호 작용, 정제된 SVG 및 PNG 내보내기를 제공하는 관측 전용 Console 2D 포커스를 추가했습니다. | `current change`; 공유 패키지 테스트 통과, 정적 컴파일러 테스트 107개와 타입 검사, 렌더링 및 산출물 376개 검사 통과, 정본 출력은 정확히 `1600x900`이고 잘린 텍스트가 없음, Console 포커스 검사 23개 통과, 합성 Playwright가 `1440x900`, `993x641`, `390x844`에서 통과, 카탈로그 동등성 17쌍 통과. | Console 범위를 `validated`로 바꾸기 전에 정확한 소스에 연결된 관리되는 데스크톱 및 모바일 Console 근거를 보존합니다. |
| 2026-08-22 | implemented | PNG 및 인증된 모바일 화면을 직접 검토한 뒤 렌더링 결과를 강화했습니다. 리소스 타입 아이콘은 0이 아닌 형상을 예약하고, 최종 복합 배치 뒤 모든 네트워크 간선을 현재 endpoint 경계로 다시 라우팅하며, `orthogonal-gap`은 형제 그룹 사이 통로를 사용합니다. 결정론적 font subset은 전체 이중 언어 다이어그램 corpus를 포함하고, Console 노드는 검토된 공식 아이콘, 경계에 닿는 halo 연결선 및 44 px 모바일 target을 사용합니다. | `current change`; 정본 endpoint, 충돌, 교차, 아이콘, font digest 및 이중 언어 PNG 검사, 집중 Console 지도 및 배치 검사, Console 타입 검사와 운영 빌드, `1440x900`, `993x641`, `390x844` 순차 Playwright 통과. 인증된 모바일에서 공식 아이콘 4개, 3 px attachment path 4개, endpoint dot 4개, 44.9 px node target, 44 px control 및 가로 overflow 0을 측정했습니다. | Console 범위를 `validated`로 바꾸기 전에 정확한 소스에 연결된 관리되는 데스크톱 및 모바일 Console 근거를 보존합니다. |
| 2026-08-22 | implemented | 두 VNet을 포함한 밀집 fixture로 live 지도와 내보내기의 남은 동등성 공백을 닫았습니다. 하나의 공유 obstacle-aware router가 두 화면에서 관련 없는 node card를 우회하고, peer VNet 경계는 직접 header corridor를 사용하며, peering 및 dependency 방향은 화살표를 유지하고 attachment endpoint는 dot을 유지합니다. 내보내기는 runtime fetch 없이 검토된 모든 SVG 원문을 포함합니다. | `current change`; 검토된 icon embedding 및 sanitizer 검사 3개, network route, map, focus, layout 및 path 검사 71개, Console 타입 검사와 운영 빌드, 데스크톱, 제한된 데스크톱 및 모바일 순차 Playwright와 직접 검토한 capture 5개. 다운로드 SVG는 포함된 공식 icon, 타입 지정 marker, legend 및 리소스 이름과 id 부재를 확인했고, 다운로드 PNG는 nonblank 기준을 넘었습니다. | Console 범위를 `validated`로 바꾸기 전에 정확한 소스에 연결된 관리되는 데스크톱 및 모바일 Console 근거를 보존합니다. |
| 2026-08-23 | implemented | 선택한 network branch를 중심으로 Ontology Instances 그래프를 강화했습니다. 이제 VNet context는 직접 포함한 Subnet과 해당 Subnet에 연결된 Private Endpoint 및 NIC만 포함하고, peer branch를 재귀적으로 확장하지 않으며, 상호 `peered_with` 레코드는 하나의 node occurrence를 공유합니다. viewport는 일반 마우스 휠 확대 및 축소, 노드를 고정한 빈 캔버스 이동, 모바일에서 10%까지 축소되는 전체 맞춤을 제공합니다. | `current change`; `npm --prefix console test -- --run src/routes/ontology-instance-graph.model.test.ts src/routes/ontology-instances.model.test.ts src/routes/ontology-instance-resource-icons.test.ts` 테스트 37개 통과, Console 타입 검사와 운영 빌드 통과, 인증된 `1440x900`, `993x641`, `390x844` 검사에서 중복 resource id 0개, node 충돌 0개, 문서 overflow 0개와 관측 branch의 VNet level 0, Subnet level 1, NIC level 2를 측정했습니다. | 이 범위의 상태를 `validated`로 올리기 전에 정확한 소스에 연결된 관리되는 receipt를 보존합니다. |
| 2026-08-23 | implemented | Private DNS zone group 아이콘을 바로잡고 활성 Resource 유형 전체를 감사했습니다. 정확한 V24 Azure asset 7개를 추가해 API Management, Disk Snapshots, NAT, SQL Database, SQL Server, Subscriptions 및 Logic Apps를 지원합니다. DNS zone group은 정확한 DNS Zones 제품군을 사용하고 Azure Monitor workspace는 Azure Monitor를 사용합니다. Role assignment, data collection endpoint 및 분류되지 않은 resource는 검증된 archive에 정확한 제품 아이콘이 없거나 유형 자체가 의도적으로 분류되지 않았으므로 명시적인 일반 대체 아이콘을 유지합니다. 그래프 도구 모음은 기본 전체 화면 명령 하나만 제공하고 일반 마우스 휠 입력이 확대 및 축소를 담당합니다. 선택한 인스턴스 상세 패널은 보기 상태를 버리지 않고 접을 수 있습니다. | `current change`; Azure asset 무결성 검사 107개, 아이콘, 보기 제어 및 지역화 포커스 테스트 통과. 인증된 `1440x900`, `993x641`, `390x844` 검사에서 각 화면 크기와 일치하는 전체 화면 경계, 44 px 모바일 컨트롤, 상세 패널 공간 회수, 마우스 휠 확대 및 축소, 문서 overflow 0을 측정했습니다. | 이 범위의 상태를 `validated`로 올리기 전에 정확한 소스에 연결된 관리되는 증적을 보존합니다. |

### 남은 작업

- [x] `1600x900` 정본 허브-스포크 fixture에서 잘린 라벨, 노드 충돌, 피할 수 있는 간선 교차
  또는 누락된 Azure 아이콘이 없음을 검증합니다.
- [x] 데스크톱, 제한된 데스크톱 및 모바일 너비에서 관측된 Console VNet
  포커스를 렌더링하고 소스-대상 경로를 강조하면서 추론한 도달 가능성을 주장하지 않습니다.
- [x] 출처 이력과 근거 상태가 보이는 접근 가능한 SVG 및 PNG 산출물을 내보냅니다.
- [ ] 런타임 검증을 주장하기 전에 정확한 소스에 연결된 관리되는 데스크톱 및 모바일 Console
  근거를 보존합니다.

## 정본 어휘

계약은 고정된 ASCII 기계 값과 지역화된 표시 라벨을 사용합니다.

### 경계 역할

| 역할 | 의미 |
|------|------|
| `external` | 렌더링된 네트워크 경계 밖의 Internet, 파트너 또는 다른 워크로드입니다. |
| `on-premises` | 클라우드 네트워크 밖에서 연결된 비공개 환경입니다. |
| `dmz` | 제어된 유입 또는 관리를 위한 전용 경계입니다. |
| `hub` | 공유 라우팅, 보안, 연결 또는 DNS 서비스입니다. |
| `spoke` | 허브 또는 피어링 관계를 통해 연결된 워크로드 네트워크입니다. |
| `virtual-network` | 프로바이더 네트워크 경계입니다. |
| `subnet` | Virtual Network 내부의 주소 세그먼트입니다. |
| `private-endpoint` | 서브넷에 연결된 비공개 데이터 플레인 엔드포인트입니다. |

### 연결 종류

| 종류 | 의미 | 기본 방향 |
|------|------|-----------|
| `vnet-peering` | 비공개 Virtual Network 피어링입니다. | bidirectional |
| `vnet-connection` | 허브 또는 Virtual WAN 연결입니다. | bidirectional |
| `expressroute` | 비공개 회선 및 게이트웨이 연결입니다. | bidirectional |
| `vpn` | 암호화된 사이트 간 또는 지점 간 연결입니다. | bidirectional |
| `private-link` | Private Endpoint에서 서비스 데이터 플레인으로 향하는 연결입니다. | forward |
| `service-endpoint` | 서브넷 범위 서비스 엔드포인트입니다. | forward |
| `routing` | 다음 홉 또는 경로 전파 관계입니다. | forward |
| `traffic` | 논리적 애플리케이션 또는 관리 트래픽 흐름입니다. | forward |

### 트래픽 및 정책 값

- `trafficClass`: `internet`, `private`, `management` 또는 `hybrid`입니다.
- `policy`: `allow`, `deny`, `inspect` 또는 `bypass`입니다.
- `direction`: `forward`, `reverse` 또는 `bidirectional`입니다.
- `protocol` 및 `port`: 선택적 표시 메타데이터이며 이것만으로 도달 가능성 근거가 되지 않습니다.
- `nextHop`: 선택적으로 작성된 다음 홉 라벨 또는 관측된 타입 지정 리소스 참조입니다.
- `sourceEvidence`: `expected`, `observed`, `stale`, `partial` 또는 `unknown`입니다.

공유 어휘에는 enum과 표시 메타데이터만 포함합니다. 배치, 인벤토리, 최신성 또는 권한 결정을
소유하지 않습니다. 작성 계약과 관측 계약은 이 값을 가져와 각자의 근거 상태별 규칙을 검증합니다.

## 작성 다이어그램 계약

`kind: network`는 범용 layered 별칭 대신 네트워크 전용 참조 프로필을 선택합니다. 작성 계약은
`posture: expected`로 고정됩니다. YAML은 픽셀 작성 방식이 아니라 의미 중심으로 유지합니다.

- 그룹은 `networkRole`, `addressPrefixes`, `region` 및 `availabilityZones`를 선언할 수 있습니다.
- 노드는 `networkRole`과 범위가 제한된 프로바이더 중립 주소, 수신기, SKU 및 보안 표시 사실을
  선언할 수 있습니다. 이 값은 문서 정보이며 자격 증명이나 유효 정책 근거가 아닙니다.
- 간선은 `connectionKind`, `direction`, `trafficClass`, `policy`, `protocol`, `port` 및 `nextHop`을
  선언할 수 있습니다.
- 참고는 지역화된 제목과 본문, 정책 또는 정보 톤, 그룹, 노드, 간선 또는 Canvas 모서리 anchor를
  가진 일급 주석입니다.
- 라우팅 의도 주석은 리소스 노드인 것처럼 보이지 않으면서 Internet 및 비공개 트래픽 처리를
  요약할 수 있습니다.

컴파일러는 `hub-spoke`, `dual-ingress` 및 `private-endpoint-fanout` preset을 제공합니다. Preset은
계층 처리, 고정 그룹 배치, 포트, 라우팅 통로 및 교차 최소화를 선택합니다. 작성자는 의미 배치와
간선 통로를 재정의할 수 있지만 원시 SVG 또는 임의 CSS를 제공하지 않습니다.

`network-azure-reference` 프로필은 `1600x900`에서 완전한 첫 화면을 목표로 합니다. 더 큰
다이어그램은 계속 이동할 수 있지만 첫 프레임에서 토폴로지 제목, 주요 경계, 연결 종류, 라우팅
의도 및 범례가 보여야 합니다. 슬라이드 지향 프로필은 서비스 라벨을 줄이거나 주요 경계를 숨기기
전에 설명 상세를 줄일 수 있습니다.

## 관측된 Console 계약

Console은 기존의 완전한 `InventoryGraphResponse` 와이어 계약을 유지하고 명시적인 `Network`
모드를 추가합니다. 관측 표현 계약은 현재 범위, 최신성, 잘림, 활성 필터 및 선택적 클라이언트 계산
경로 결과로 이 응답을 감쌉니다. 이를 다시 인벤토리로 직렬화할 수 없습니다. 이 모드는 두 번째
인벤토리 소스가 아니라 표현 변환 결과입니다.

1. VNet, 서브넷, 게이트웨이, 방화벽, Private Endpoint 또는 리소스 그룹 선택은 선택된 리소스를
   포함하는 가장 작은 관측 네트워크 포커스를 확인합니다.
2. 2D 위 보기에는 관측된 containment, `attached_to`, `depends_on` 및 `peered_with` 링크가
   유지됩니다. 배치 순서, 리소스 이름 또는 프로바이더 식별자를 트래픽으로 바꾸지 않습니다.
3. 포커스 보기는 관측된 VNet 및 서브넷 경계를 펼치고 관련 없는 구독 내용을 프레임 밖에
   유지합니다. 완전한 사실 개수와 관계 인덱스는 계속 사용할 수 있습니다.
4. 소스 및 대상 선택기는 가장 짧은 타입 지정 관계 경로를 추적합니다. 각 홉은 기록된 관계 종류와
   근거 상태를 표시합니다. 표현 결과는 `found`, `no_observed_path` 또는 `unknown`입니다. 잘리거나
   부분적이거나 stale이거나 관계가 불완전한 그래프는 `no_observed_path`를 반환할 수 없고
   `unknown`을 반환합니다. 권위 있는 정책 또는 유효 경로 근거 없이는 두 부정 결과 모두
   `Blocked` 또는 `Allowed`로 표시하지 않습니다.

이 모드는 공개 노출, 비공개 전용 리소스, 보안 경계, 게이트웨이, DNS 및 Private Endpoint 필터를
제공합니다. 선택된 경로는 해당 홉을 강조하고 관련 없는 내용을 화면에서만 흐리게 표시합니다.
경로를 지우면 기반 그래프를 변경하지 않고 완전한 포커스를 복원합니다.

## 네트워크 리소스 표현

공식 Azure 제품 아이콘은 실제 Azure 서비스에만 사용하고 제품 이름을 함께 유지합니다. 검증된
허용 목록은 최소한 Virtual Network, subnet, Virtual WAN 및 hub, Azure Firewall, Bastion,
Application Gateway, VPN Gateway, ExpressRoute gateway 및 circuit, Private Endpoint, public IP,
route table, NSG, load balancer, network interface 및 virtual machine을 포함합니다.

정적 컴파일러는 알려진 프로바이더 리소스 타입을 해당 아이콘 id에 매핑합니다. 알 수 없는 타입은
텍스트 카드 또는 고정된 abbreviation으로 남고 비슷한 Azure 제품 아이콘을 빌려 쓰지 않습니다.
Console은 2D 모드에서 같은 검토된 아이콘 파일을 사용하고 매핑되지 않은 타입에만 고정된
abbreviation을 사용합니다. 기존 isometric 모드는 형태, 색상 및 abbreviation 중복 표현을
유지합니다.

## 배치 및 무결성

네트워크 배치는 `INCLUDE_CHILDREN`, 직교 라우팅, 명시적 고정 방향 포트 및 layered 교차 최소화를
사용하는 ELK 복합 그래프를 기반으로 합니다. 네트워크 의미는 기존 그룹, 노드 및 간선 종류에
추가되는 속성으로 유지하므로 네트워크 이외의 다이어그램 종류와 호환됩니다. 컴파일러는 다음을
검증합니다.

- 노드 간, 그룹 간, 노드와 관련 없는 그룹 사이의 겹침
- 노드의 상위 경계 이탈 및 그룹 라벨 잘림
- 간선과 단계 배지가 노드, 라벨 및 주석과 겹치는지 여부
- 피할 수 있는 간선 교차 및 동일 선상 세그먼트 겹침
- 명시적인 연결 엔드포인트가 없는 경계 통과
- 대상 viewport 내부의 주석 및 범례 containment

무결성 검사는 의도적인 공유 trunk, 양방향 쌍 marker 및 같은 엔드포인트에서 만나는 간선을 제외할
수 있습니다. 각 예외는 다이어그램별 id 허용 목록이 아니라 구조적이고 결정론적이어야 합니다.

Network preset은 최종 복합 배치 뒤 모든 자동 간선을 다시 라우팅하므로 ELK route가 배치 전의
오래된 좌표를 유지할 수 없습니다. `orthogonal-gap`은 배치된 그룹에서 row 및 형제 통로를
계산합니다. 무결성 검사는 간선 양 끝이 현재 endpoint 경계에 닿도록 요구하고 관련 없는 노드
관통, 간선 간의 실제 교차 및 라벨 충돌을 거부합니다.

## 상호 작용, 접근성 및 내보내기

정적 다이어그램은 접근 가능한 SVG, 지역화된 대체 텍스트, 노드 포커스, 연결된 흐름 상세, 이동,
확대, 전체 보기, 전체 화면 및 다운로드를 유지합니다. 네트워크 연결은 상세 패널에서 종류, 방향,
트래픽 클래스, 정책, 프로토콜, 포트 및 근거 상태를 표시합니다.

Console은 Canvas 전용 작업마다 동등한 DOM 컨트롤을 제공합니다. 포커스 선택, 소스 및 대상 선택,
경로 결과, 필터, 관계 목록, fit 및 내보내기를 포함합니다. 내보내기는 현재 포커스에서 정제된 SVG
스냅샷과 선택적 PNG를 생성합니다. 자격 증명, 구독 id, 원시 프로바이더 리소스 id, 엔드포인트 또는
고객별 값을 포함하지 않습니다. 라이브 내보내기는 스냅샷 시간, 소스, 최신성, 범위, 잘림 및
`Read-only observed topology`를 표시합니다.
관측된 링크는 시각적 중심이 아니라 노드 및 영역 경계에서 끝납니다. 중립 halo와 타입이 지정된
endpoint dot은 중첩된 경계에서도 짧은 containment attachment를 보이게 하고, 모바일 icon
노드는 pointer와 키보드에 최소 44 px target을 제공합니다.
Live 지도와 정제된 내보내기는 하나의 obstacle-aware 직교 router를 공유합니다. Peer VNet
경계는 하위 node를 우회하는 대신 직접 header corridor를 사용합니다. Dependency는 정방향
화살표, peering은 양방향 화살표, attachment는 endpoint dot을 유지합니다. 내보내기는 build
시점에 검토된 SVG 원문을 포함하며 로컬 또는 원격 icon URL을 fetch하지 않습니다.

## 검증 매트릭스

| 게이트 | 필수 근거 |
|--------|-----------|
| 스키마 | 공유 어휘 동등성과 작성 다이어그램 및 관측 표현 상태의 별도 긍정 및 부정 fixture입니다. |
| 배치 | 정본 허브-스포크, 이중 유입, Private Endpoint fan-out 및 밀집 교차 fixture가 무결성 검사를 통과합니다. |
| 렌더링 | 영어 및 한국어 SVG가 모든 경계, 아이콘, 연결, 주석 및 접근 가능한 상세를 포함합니다. |
| Console 모델 | 포커스 선택, 모호성, 경로 추적, 필터링 및 관측 경로 없음 동작이 결정론적 테스트를 통과합니다. |
| Console UI | 데스크톱 `1440x900`, 제한된 데스크톱 `993x641` 및 모바일 `390x844`에서 부자연스러운 겹침이나 문서 가로 overflow가 없습니다. |
| 출처 이력 | Stale, partial, expected, observed 및 unknown 상태가 UI와 내보내기에서 구분됩니다. |

적대적 계약 테스트는 관측 표현이 추론한 간선을 `observed`로 표시하거나 불완전한 관계 범위에서
`no_observed_path`를 보고하면 거부합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 인벤토리 권위 및 제한된 네트워크 수집 | [제한된 네트워크의 Azure 인벤토리](../architecture/azure-inventory-network-paths-ko.md) |
| Console 근거 및 지도 복원력 | [Console 근거 및 복원력](console-evidence-and-resilience-ko.md#아키텍처-지도-복원력) |
| 배포 네트워크 요구 사항 | [네트워크 연결 매트릭스](../deployment/network-connectivity-matrix-ko.md) |
