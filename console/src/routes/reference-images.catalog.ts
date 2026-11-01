import type { GuidanceReferenceImage } from "./wara-guidance.model";

export const PACKAGED_REFERENCE_IMAGES: Readonly<Record<string, GuidanceReferenceImage>> = {
  "vmbackup-architecture": {
    "alt": {
      "en": "Extension-based Azure VM backup: the VM agent and backup extension capture OS and data-disk snapshots and transfer backup data to a vault. The temporary disk has no snapshot.",
      "ko": "확장 기반 Azure VM 백업: VM 에이전트와 백업 확장이 OS 및 데이터 디스크의 스냅샷을 만들고 백업 데이터를 vault로 전송합니다. 임시 디스크에는 스냅샷이 없습니다."
    },
    "asset_id": "sha256-50960288bb63db67a0510019914bc27d3ca2709cee8c459f263e8b7331b70012",
    "attribution": "Microsoft and contributors, About Azure VM backup. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official extension-based VM backup architecture. Temporary disks are excluded. This image does not describe agentless backup or prove policy compliance, application consistency or a successful restore; use the supplementary diagram and verification steps for those distinctions.",
      "ko": "확장 기반 VM 백업의 공식 아키텍처입니다. 임시 디스크는 제외됩니다. 이 그림은 에이전트 없는 백업을 설명하거나 정책 준수, 애플리케이션 일관성 또는 복원 성공을 입증하지 않습니다. 보충 도식과 검증 절차에서 이 차이를 확인합니다."
    },
    "digest": "sha256:50960288bb63db67a0510019914bc27d3ca2709cee8c459f263e8b7331b70012",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/backup/media/backup-azure-vms-introduction/vmbackup-architecture.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction",
    "source_revision": "6e232e43ce97e38e61c9a265b3148485e5414892"
  },
  "point-in-time-restore-diagram": {
    "alt": {
      "en": "Point-in-time restore: after write and delete operations over n days, some or all containers of a storage account are restored to the container state from n days earlier.",
      "ko": "시점 복원: n일 동안 쓰기와 삭제 작업이 일어난 뒤, 스토리지 계정의 일부 또는 모든 컨테이너를 n일 전의 컨테이너 상태로 복원합니다."
    },
    "asset_id": "sha256-e3ad0b659fb4639b890b971d2219f1348659fbad310f423f4d94661f171a7752",
    "attribution": "Microsoft and contributors, Point-in-time restore for block blobs. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official point-in-time restore concept for block blobs. It illustrates the restore effect only; it does not show that point-in-time restore and its prerequisites are enabled in your storage account or that a restore has succeeded.",
      "ko": "블록 Blob 시점 복원의 공식 개념도입니다. 복원 효과만 보여 주며, 사용자의 스토리지 계정에서 시점 복원과 필수 선행 설정이 켜져 있다거나 복원이 성공했다는 사실은 입증하지 않습니다."
    },
    "digest": "sha256:e3ad0b659fb4639b890b971d2219f1348659fbad310f423f4d94661f171a7752",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/storage/blobs/media/point-in-time-restore-overview/point-in-time-restore-diagram.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/storage/blobs/point-in-time-restore-overview",
    "source_revision": "456398bb35f5b0e51b7b8e983e020271fa00b9cb"
  },
  "front-door-overview": {
    "alt": {
      "en": "Web Application Firewall on Azure Front Door: a client request to www.contoso.com reaches a Front Door edge location where the Web Application Firewall inspects it, and path-based routes such as /search/* and /statics/* then cross the Microsoft global network to backends in an Azure region, on-premises or another cloud.",
      "ko": "Azure Front Door의 Web Application Firewall입니다. www.contoso.com으로 가는 클라이언트 요청이 Front Door 에지 위치에 도달하면 Web Application Firewall이 요청을 검사하고, /search/*와 /statics/* 같은 경로 기반 경로가 Microsoft 글로벌 네트워크를 지나 Azure 지역, 온-프레미스 또는 다른 클라우드의 백 엔드로 이어집니다."
    },
    "asset_id": "sha256-b2c634fa1bc51512b43b4c03cecaa0e8400ecb49855d24eff87b0486080f7c77",
    "attribution": "Microsoft and contributors, Web Application Firewall (WAF) on Azure Front Door. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official Front Door overview with Web Application Firewall. It illustrates where WAF sits; it does not show that a WAF policy is attached to your Front Door profile or its mode.",
      "ko": "Web Application Firewall을 포함한 Front Door에 대한 공식 개요 그림입니다. WAF의 위치만 보여 주며, 사용자의 Front Door 프로필에 WAF 정책이 연결되어 있다거나 그 모드가 무엇인지는 보여 주지 않습니다."
    },
    "digest": "sha256:b2c634fa1bc51512b43b4c03cecaa0e8400ecb49855d24eff87b0486080f7c77",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/frontdoor/media/overview/front-door-overview.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/frontdoor/web-application-firewall",
    "source_revision": "c1de83e06a7c13b2cea091b33703dc8fcca099ed"
  },
  "main-diagram": {
    "alt": {
      "en": "ExpressRoute Traffic Collector receives flow logs from two ExpressRoute circuits carrying Microsoft peering and Azure private peering traffic and sends them to an Azure Log Analytics workspace.",
      "ko": "ExpressRoute Traffic Collector가 Microsoft 피어링과 Azure 프라이빗 피어링 트래픽을 전달하는 ExpressRoute 회로 두 개에서 흐름 로그를 받아 Azure Log Analytics 작업 영역으로 보냅니다."
    },
    "asset_id": "sha256-a525023b9aa547ceca247305a458e34252e24aff1e797e567343ce88995db21b",
    "attribution": "Microsoft and contributors, Azure ExpressRoute Traffic Collector. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official Traffic Collector architecture. It illustrates the log flow only; it does not show that Traffic Collector is deployed, linked to your circuits or sending logs to a workspace.",
      "ko": "Traffic Collector 아키텍처에 대한 공식 그림입니다. 로그 흐름만 보여 주며, Traffic Collector가 배포되어 있거나 사용자의 회로에 연결되어 있거나 작업 영역으로 로그를 보내고 있다는 사실은 입증하지 않습니다."
    },
    "digest": "sha256:a525023b9aa547ceca247305a458e34252e24aff1e797e567343ce88995db21b",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/expressroute/media/traffic-collector/main-diagram.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/expressroute/traffic-collector",
    "source_revision": "c45518826ad7ab602da30c52f6f746862b7e7cf2"
  },
  "bfd-need": {
    "alt": {
      "en": "An ExpressRoute private peering HA pair between the partner or customer edge and the Microsoft edge. When one link fails, detection takes less than a second with BFD and a minimum of a few tens of seconds (default 3 minutes) without it.",
      "ko": "파트너 또는 고객 에지와 Microsoft 에지 사이의 ExpressRoute 프라이빗 피어링 HA 쌍입니다. 링크 하나에 장애가 나면 BFD를 사용할 때는 1초 미만, 사용하지 않을 때는 최소 수십 초(기본 3분)가 걸려 장애를 감지합니다."
    },
    "asset_id": "sha256-5a3b2ec8a7dbd8aa7b43bf32f1a1a70e1b7f513b3090f8ba8eaeec54af8fed46",
    "attribution": "Microsoft and contributors, Configure BFD over ExpressRoute. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official BFD failure-detection illustration. The timings are the documented values for the pictured peering; they do not show that BFD is configured on your edge devices or ExpressRoute circuits.",
      "ko": "BFD 장애 감지에 대한 공식 그림입니다. 표시된 시간은 그림의 피어링에 대해 문서화된 값이며, 사용자의 에지 장치나 ExpressRoute 회로에 BFD가 구성되어 있다는 사실은 입증하지 않습니다."
    },
    "digest": "sha256:5a3b2ec8a7dbd8aa7b43bf32f1a1a70e1b7f513b3090f8ba8eaeec54af8fed46",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/expressroute/media/expressroute-bfd/bfd-need.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/expressroute/expressroute-bfd",
    "source_revision": "0743e25153baeb5d31b1b7f0b3eb0497309002a3"
  },
  "network-watcher-capabilities": {
    "alt": {
      "en": "Azure Network Watcher capabilities: monitoring (Connection monitor, Topology), network diagnostic tools (NSG diagnostics, Effective security rules, VPN troubleshoot, Connection troubleshoot, IP flow verify, Packet capture, Next hop) and traffic (Flow logs, Traffic analytics).",
      "ko": "Azure Network Watcher 기능입니다. 모니터링(연결 모니터, 토폴로지), 네트워크 진단 도구(NSG 진단, 유효 보안 규칙, VPN 문제 해결, 연결 문제 해결, IP 흐름 확인, 패킷 캡처, 다음 홉), 트래픽(흐름 로그, 트래픽 분석)으로 구성됩니다."
    },
    "asset_id": "sha256-9ad9006a7b1cdfc7fe4ceaeece94368d07e480b3f82c47c1fa8f5489df9b4993",
    "attribution": "Microsoft and contributors, What is Azure Network Watcher?. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official Network Watcher capability overview. It lists the capabilities; it does not show in which regions Network Watcher is enabled for your subscription.",
      "ko": "Network Watcher 기능에 대한 공식 개요 그림입니다. 기능만 나열하며, 사용자의 구독에서 어떤 지역에 Network Watcher가 사용 설정되어 있는지는 보여 주지 않습니다."
    },
    "digest": "sha256:9ad9006a7b1cdfc7fe4ceaeece94368d07e480b3f82c47c1fa8f5489df9b4993",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/network-watcher/media/network-watcher-overview/network-watcher-capabilities.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/network-watcher/network-watcher-overview",
    "source_revision": "72d285d0aefe1746c6b2c92672e049d20885583b"
  },
  "aks-node-pools": {
    "alt": {
      "en": "AKS node pool placement across three availability zones: a zone-spanning pool (A) has nodes in all three zones, zone-aligned pools (X, Y and Z) each stay within one zone, and a regional pool (R) is not tied to a zone.",
      "ko": "세 가용성 영역에 걸친 AKS 노드 풀 배치입니다. 영역 확장 풀(A)은 세 영역 모두에 노드를 두고, 영역 정렬 풀(X, Y, Z)은 각각 한 영역에 머물며, 지역 풀(R)은 특정 영역에 묶이지 않습니다."
    },
    "asset_id": "sha256-c03871eac4d20e8f14868f455c5488658b1df6dd71da5ccc519d4798855d0f7b",
    "attribution": "Microsoft and contributors, Configure availability zones in Azure Kubernetes Service (AKS). CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official AKS node pool placement models. It illustrates the options only; it does not show how your cluster's node pools are configured or that they run across zones.",
      "ko": "AKS 노드 풀 배치 모델에 대한 공식 그림입니다. 선택 가능한 방식만 보여 주며, 사용자 클러스터의 노드 풀 구성이나 여러 영역에서의 실행 여부는 보여 주지 않습니다."
    },
    "digest": "sha256:c03871eac4d20e8f14868f455c5488658b1df6dd71da5ccc519d4798855d0f7b",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/aks/media/availability-zones/aks-node-pools.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/aks/reliability-availability-zones-configure",
    "source_revision": "cda7b5779592a630164709f17de3bf20baaf4429"
  },
  "scheduled-events-timeline": {
    "alt": {
      "en": "Maintenance events timeline. The customer view through Scheduled Events shows scheduled, approve event, started, completed and restore workload; the Azure system view shows other tenants approving or reaching the timeout, the update operation, impact, and probation and stabilization. The timeline is expanded and not to scale.",
      "ko": "유지 관리 이벤트 타임라인입니다. 고객 관점(예약된 이벤트)에서는 예약됨, 이벤트 승인, 시작됨, 완료됨, 워크로드 복원이 표시되고, Azure 시스템 관점에서는 다른 테넌트의 승인 또는 제한 시간 도달, 업데이트 작업, 영향, 관찰 및 안정화가 표시됩니다. 타임라인은 세부 정보를 위해 확장되어 있으며 간격은 실제 비율이 아닙니다."
    },
    "asset_id": "sha256-d567b9abc08e2ba295d4f7e3f45060108205313866cdc3fe39761d31491b9022",
    "attribution": "Microsoft and contributors, Azure Metadata Service: Scheduled Events for Linux VMs. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official maintenance event timeline. It is not to scale and does not show that your workload queries Scheduled Events or handles them.",
      "ko": "유지 관리 이벤트에 대한 공식 타임라인입니다. 실제 비율이 아니며, 사용자의 워크로드가 예약된 이벤트를 조회하거나 처리한다는 사실은 보여 주지 않습니다."
    },
    "digest": "sha256:d567b9abc08e2ba295d4f7e3f45060108205313866cdc3fe39761d31491b9022",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/virtual-machines/linux/media/scheduled-events/scheduled-events-timeline.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events",
    "source_revision": "533281db10ee91cfabc771d583b49541e3713ad6"
  },
  "avs-interconnect": {
    "alt": {
      "en": "Three Azure VMware Solution private clouds (A, B and C) in a single Azure region connected as an AVS Interconnect mesh by three AVS Interconnect links; AVS Interconnect gives the highest throughput and lowest latency between private clouds in the same region.",
      "ko": "하나의 Azure 지역에 있는 Azure VMware Solution 프라이빗 클라우드 세 개(A, B, C)가 AVS Interconnect 링크 세 개로 메시를 이룹니다. AVS Interconnect는 같은 지역의 프라이빗 클라우드 사이에서 가장 높은 처리량과 가장 낮은 대기 시간을 제공합니다."
    },
    "asset_id": "sha256-4968915ed4ee1d5e2813645e01067524a11da64f698a5da9b0d133e9c4eefae9",
    "attribution": "Microsoft and contributors, Connect multiple Azure VMware Solution private clouds in the same region. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official AVS Interconnect topology. It illustrates the topology only; it does not show that your private clouds are connected this way.",
      "ko": "AVS Interconnect 토폴로지에 대한 공식 그림입니다. 토폴로지만 보여 주며, 사용자의 프라이빗 클라우드가 이렇게 연결되어 있다는 사실은 입증하지 않습니다."
    },
    "digest": "sha256:4968915ed4ee1d5e2813645e01067524a11da64f698a5da9b0d133e9c4eefae9",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/azure-vmware/media/networking/avs-interconnect.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/azure-vmware/connect-multiple-private-clouds-same-region",
    "source_revision": "1e20d2893220e1380fa8c4ec47860f233bdc81ff"
  },
  "appgatewayprobe": {
    "alt": {
      "en": "Application Gateway sends health probes to each VM in a backend pool: VM1 and VM2 answer HTTP 200 OK and are healthy, VM3 answers HTTP 500 and is unhealthy, so user requests are sent only to VM1 and VM2.",
      "ko": "Application Gateway가 백 엔드 풀의 각 VM에 상태 프로브를 보냅니다. VM1과 VM2는 HTTP 200 OK로 응답해 정상이고 VM3은 HTTP 500으로 응답해 비정상이므로 사용자 요청은 VM1과 VM2로만 전달됩니다."
    },
    "asset_id": "sha256-d9c1ec2b4d7e0f4d6f2f33172745b38856960e8f7f46465996f173228f492813",
    "attribution": "Microsoft and contributors, Application Gateway health probes overview. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official health probe illustration. It explains probe behavior; it does not show your probe configuration or the current health of your backend pool.",
      "ko": "상태 프로브에 대한 공식 그림입니다. 프로브 동작을 설명할 뿐, 사용자의 프로브 구성이나 백 엔드 풀의 현재 상태는 보여 주지 않습니다."
    },
    "digest": "sha256:d9c1ec2b4d7e0f4d6f2f33172745b38856960e8f7f46465996f173228f492813",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/application-gateway/media/application-gateway-probe-overview/appgatewayprobe.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/application-gateway/application-gateway-probe-overview",
    "source_revision": "b2e4b658942eb64385821ad7f8067ab40631a79c"
  },
  "backup-item-delete-flow": {
    "alt": {
      "en": "Soft delete flow for a backup item: stopping backup and deleting data makes an active item soft-deleted and retained for the soft delete retention period. Undeleting within the period leads to stop backup with retain data, resuming returns the item to active, and purging after the period makes it permanently deleted.",
      "ko": "백업 항목의 일시 삭제 흐름입니다. 백업을 중지하고 데이터를 삭제하면 활성 항목이 일시 삭제 상태가 되어 보존 기간 동안 유지됩니다. 보존 기간 안에 삭제를 취소하면 데이터 보존 상태의 백업 중지가 되고, 다시 시작하면 활성으로 돌아가며, 보존 기간이 지난 뒤 제거하면 영구 삭제됩니다."
    },
    "asset_id": "sha256-0724dde3117044b1847e3b3ddeed1d755c608f7bfa353cd09f371e7999c899a3",
    "attribution": "Microsoft and contributors, Secure by default with soft delete for Azure Backup. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official soft delete state flow for Azure Backup items. It explains states and transitions; it does not show the soft delete setting, the retention period or the state of any item in your vaults.",
      "ko": "Azure Backup 항목의 일시 삭제 상태 흐름에 대한 공식 그림입니다. 상태와 전환을 설명할 뿐, 일시 삭제 설정, 보존 기간 또는 사용자 자격 증명 모음에 있는 항목의 상태는 보여 주지 않습니다."
    },
    "digest": "sha256:0724dde3117044b1847e3b3ddeed1d755c608f7bfa353cd09f371e7999c899a3",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/backup/media/secure-by-default/backup-item-delete-flow.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/backup/secure-by-default",
    "source_revision": "b9232a1ad4bbe6362e55876eb0f04fa2fd717526"
  },
  "data-export-overview": {
    "alt": {
      "en": "Log Analytics data export: incoming data enters the Azure Monitor ingestion pipeline and the Log Analytics workspace, and the pipeline exports data to a storage account or an event hub.",
      "ko": "Log Analytics 데이터 내보내기입니다. 들어오는 데이터는 Azure Monitor 수집 파이프라인과 Log Analytics 작업 영역으로 들어가고, 파이프라인이 데이터를 스토리지 계정이나 이벤트 허브로 내보냅니다."
    },
    "asset_id": "sha256-795267949ff8e0fd6db715cb0bfd3c47d8c19f2f1628fa00f382969db2c3491c",
    "attribution": "Microsoft and contributors, Log Analytics data export rules in Azure Monitor. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official data export overview. It shows the export destinations; it does not show that an export rule exists or that your destination account uses geo-redundant storage.",
      "ko": "데이터 내보내기에 대한 공식 개요 그림입니다. 내보내기 대상만 보여 주며, 내보내기 규칙이 있다거나 대상 계정이 지역 중복 스토리지를 쓴다는 사실은 보여 주지 않습니다."
    },
    "digest": "sha256:795267949ff8e0fd6db715cb0bfd3c47d8c19f2f1628fa00f382969db2c3491c",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/media/logs-data-export/data-export-overview.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-data-export",
    "source_revision": "022db371850311fc1d3db8923b5de1ab38cfbbaa"
  },
  "aks-monitor-data-v2": {
    "alt": {
      "en": "AKS monitoring by level: network, cluster-level components, managed cluster components, Kubernetes objects and workloads, and application. Each level lists its monitoring tools, such as Managed service for Prometheus, Container insights, resource logs, Application insights, Network Watcher and Traffic Analytics, which feed Azure Managed Grafana and the Azure portal.",
      "ko": "수준별 AKS 모니터링입니다. 네트워크, 클러스터 수준 구성 요소, 관리형 클러스터 구성 요소, Kubernetes 개체와 워크로드, 애플리케이션 수준마다 Managed service for Prometheus, Container insights, 리소스 로그, Application insights, Network Watcher, Traffic Analytics 같은 모니터링 도구가 나열되고, 그 데이터는 Azure Managed Grafana와 Azure Portal에 표시됩니다."
    },
    "asset_id": "sha256-0d63a1470f1366817ee9fb29241ace785e3cec91d9feb35f1afb2ded6d4a4380",
    "attribution": "Microsoft and contributors, Monitor Azure Kubernetes Service (AKS). CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official AKS monitoring overview. It describes which tools collect data at each level; it does not show that any of them is enabled on your cluster.",
      "ko": "AKS 모니터링에 대한 공식 개요 그림입니다. 수준별로 어떤 도구가 데이터를 수집하는지 설명할 뿐, 사용자의 클러스터에서 이들이 사용 설정되어 있다는 사실은 보여 주지 않습니다."
    },
    "digest": "sha256:0d63a1470f1366817ee9fb29241ace785e3cec91d9feb35f1afb2ded6d4a4380",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/aks/media/monitor-aks/aks-monitor-data-v2.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/aks/monitor-aks",
    "source_revision": "1276ea53ec778a63718a761ca94906814c54c227"
  },
  "geo-zone-redundant-storage": {
    "alt": {
      "en": "Geo-zone-redundant storage: three copies of the data are kept in separate availability zones of the primary region (ZRS) and geo-replicated to a single datacenter in the secondary region, where three copies are kept with locally redundant storage (LRS).",
      "ko": "지역 영역 중복 스토리지입니다. 데이터 복사본 세 개를 주 지역의 서로 다른 가용성 영역에 보관하고(ZRS), 보조 지역의 데이터센터 한 곳으로 지역 복제하여 로컬 중복 스토리지(LRS)로 복사본 세 개를 보관합니다."
    },
    "asset_id": "sha256-d71506844ebe24f11933e2a269deaab48d584730a2ae40561642fc1e456ba78b",
    "attribution": "Microsoft and contributors, Azure Storage redundancy. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official GZRS illustration. It shows one redundancy option; it does not describe other options and does not show which redundancy your storage accounts use.",
      "ko": "GZRS에 대한 공식 그림입니다. 중복 옵션 하나만 보여 주며, 다른 옵션을 설명하지 않고 사용자의 스토리지 계정이 어떤 중복 방식을 쓰는지도 보여 주지 않습니다."
    },
    "digest": "sha256:d71506844ebe24f11933e2a269deaab48d584730a2ae40561642fc1e456ba78b",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/storage/common/media/storage-redundancy/geo-zone-redundant-storage.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/storage/common/storage-redundancy",
    "source_revision": "600b459b67367f93f8426065bac787d0b7766c3e"
  },
  "02-soft-delete": {
    "alt": {
      "en": "Azure Container Registry soft delete lifecycle: deleting an artifact moves it from Active to Soft-Deleted, restoring returns it to Active, and when the retention period expires it becomes permanently deleted.",
      "ko": "Azure Container Registry 일시 삭제 수명 주기입니다. 아티팩트를 삭제하면 활성에서 일시 삭제 상태가 되고, 복원하면 활성으로 돌아가며, 보존 기간이 끝나면 영구 삭제됩니다."
    },
    "asset_id": "sha256-9d44541aede5c5f44ee776e643d7f54c240a0e9845aebf408c469dc0b317ffc9",
    "attribution": "Microsoft and contributors, Recover deleted artifacts with the soft delete policy in Azure Container Registry (preview). CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official artifact lifecycle for the registry soft delete policy. It explains the states; it does not show that the policy is enabled on your registry or how long artifacts are retained.",
      "ko": "레지스트리 일시 삭제 정책의 아티팩트 수명 주기에 대한 공식 그림입니다. 상태를 설명할 뿐, 사용자의 레지스트리에서 정책이 사용 설정되어 있거나 아티팩트를 얼마나 보존하는지는 보여 주지 않습니다."
    },
    "digest": "sha256:9d44541aede5c5f44ee776e643d7f54c240a0e9845aebf408c469dc0b317ffc9",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/container-registry/media/container-registry-soft-delete/02-soft-delete.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/container-registry/container-registry-soft-delete-policy",
    "source_revision": "77ed42b078ffffc9096cb8d860b62a165b788f57"
  },
  "fastpath-vnet-peering": {
    "alt": {
      "en": "ExpressRoute with FastPath and virtual network peering: traffic from the on-premises network through the ExpressRoute circuit and the Microsoft edge reaches VMs in spoke virtual networks directly over FastPath, instead of through the hub virtual network's ExpressRoute gateway and Azure Firewall.",
      "ko": "FastPath와 가상 네트워크 피어링을 사용하는 ExpressRoute입니다. 온-프레미스 네트워크에서 ExpressRoute 회로와 Microsoft 에지를 거친 트래픽이 허브 가상 네트워크의 ExpressRoute 게이트웨이와 Azure Firewall을 거치지 않고 FastPath로 스포크 가상 네트워크의 VM에 직접 도달합니다."
    },
    "asset_id": "sha256-33ad4a34ec84e57d5a9f02c3abcfb2aee232984728c8b813a877d2173db8be5f",
    "attribution": "Microsoft and contributors, Azure ExpressRoute FastPath: Features, availability, and limitations. CC BY 4.0. Original image, unchanged. Microsoft trademarks remain with their owners.",
    "caption": {
      "en": "Official FastPath data-path diagram. It illustrates the path only; it does not show that FastPath is enabled on your connection or that your traffic uses it.",
      "ko": "FastPath 데이터 경로에 대한 공식 그림입니다. 경로만 보여 주며, 사용자의 연결에서 FastPath가 사용 설정되어 있거나 트래픽이 이를 사용한다는 사실은 입증하지 않습니다."
    },
    "digest": "sha256:33ad4a34ec84e57d5a9f02c3abcfb2aee232984728c8b813a877d2173db8be5f",
    "english_in_image_notice": {
      "en": "The original image contains English labels. The Korean alternative text and caption explain its scope; the image itself has not been translated.",
      "ko": "원본 이미지의 표시는 영어입니다. 한국어 대체 텍스트와 캡션으로 설명 범위를 안내하며, 이미지 자체를 번역한 것은 아닙니다."
    },
    "image_url": "https://learn.microsoft.com/en-us/azure/expressroute/media/about-fastpath/fastpath-vnet-peering.png",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_document_url": "https://learn.microsoft.com/en-us/azure/expressroute/about-fastpath",
    "source_revision": "1cfd566ef5e78b557a6a05c19ecf6726b375d204"
  }
};

export const FRAMEWORK_TITLES_BY_KEY: Readonly<Record<string, { readonly en: string; readonly ko: string }>> = {
  "azure-waf:CO:01": {
    "en": "Create a culture of financial responsibility",
    "ko": "재무 책임을 공유하는 문화 조성"
  },
  "azure-waf:CO:02": {
    "en": "Create and maintain a cost model",
    "ko": "비용 모델 작성과 유지"
  },
  "azure-waf:CO:03": {
    "en": "Collect and review cost data",
    "ko": "비용 데이터 수집과 검토"
  },
  "azure-waf:CO:04": {
    "en": "Set spending guardrails",
    "ko": "비용 한도와 경고 설정"
  },
  "azure-waf:CO:05": {
    "en": "Obtain the best available provider rates",
    "ko": "적합한 공급자 요금 선택"
  },
  "azure-waf:CO:06": {
    "en": "Align usage to billing increments",
    "ko": "사용 패턴과 청구 단위 정렬"
  },
  "azure-waf:CO:07": {
    "en": "Optimize component costs",
    "ko": "구성 요소별 비용 최적화"
  },
  "azure-waf:CO:08": {
    "en": "Optimize environment costs",
    "ko": "환경별 비용 최적화"
  },
  "azure-waf:CO:09": {
    "en": "Optimize flow costs",
    "ko": "사용자 흐름별 비용 최적화"
  },
  "azure-waf:CO:10": {
    "en": "Optimize data costs",
    "ko": "데이터 비용 최적화"
  },
  "azure-waf:CO:11": {
    "en": "Optimize code costs",
    "ko": "코드 실행 비용 최적화"
  },
  "azure-waf:CO:12": {
    "en": "Optimize scaling costs",
    "ko": "확장 비용 최적화"
  },
  "azure-waf:CO:13": {
    "en": "Optimize personnel time",
    "ko": "운영 인력의 시간 최적화"
  },
  "azure-waf:CO:14": {
    "en": "Consolidate resources and responsibility",
    "ko": "리소스와 책임의 적절한 통합"
  },
  "azure-waf:OE:01": {
    "en": "Define standard workload development and operating practices",
    "ko": "표준 개발 및 운영 관행 정의"
  },
  "azure-waf:OE:02": {
    "en": "Standardize routine ad-hoc and emergency operations",
    "ko": "일상 및 비상 운영의 표준화"
  },
  "azure-waf:OE:03": {
    "en": "Formalize practices across the software development lifecycle",
    "ko": "소프트웨어 수명 주기 관행 정립"
  },
  "azure-waf:OE:04": {
    "en": "Standardize development tools and quality processes",
    "ko": "개발 도구와 품질 절차 표준화"
  },
  "azure-waf:OE:05": {
    "en": "Use a standardized infrastructure-as-code approach",
    "ko": "코드형 인프라 접근 방식 표준화"
  },
  "azure-waf:OE:06": {
    "en": "Build a predictable workload supply chain",
    "ko": "예측 가능한 공급 체인 구축"
  },
  "azure-waf:OE:07": {
    "en": "Design a workload monitoring stack",
    "ko": "워크로드 모니터링 체계 설계"
  },
  "azure-waf:OE:08": {
    "en": "Establish a structured incident management process",
    "ko": "체계적인 인시던트 관리 정립"
  },
  "azure-waf:OE:09": {
    "en": "Adopt testing practices aligned with business objectives",
    "ko": "사업 목표에 맞춘 테스트"
  },
  "azure-waf:OE:10": {
    "en": "Design reliable secure and maintainable automation",
    "ko": "안정적이고 안전한 자동화 설계"
  },
  "azure-waf:OE:11": {
    "en": "Define safe deployment practices",
    "ko": "안전한 배포 관행 정의"
  },
  "azure-waf:PE:01": {
    "en": "Define numerical performance targets for workload flows",
    "ko": "흐름별 수치형 성능 목표 정의"
  },
  "azure-waf:PE:02": {
    "en": "Conduct capacity planning before predicted demand changes",
    "ko": "수요 변화에 앞선 용량 계획"
  },
  "azure-waf:PE:03": {
    "en": "Select services and tiers that meet performance targets",
    "ko": "성능 목표에 맞는 서비스와 계층 선택"
  },
  "azure-waf:PE:04": {
    "en": "Establish consistent performance measurement",
    "ko": "일관된 성능 측정 확립"
  },
  "azure-waf:PE:05": {
    "en": "Optimize scaling and partitioning",
    "ko": "확장과 분할 최적화"
  },
  "azure-waf:PE:06": {
    "en": "Test performance in a production-like environment",
    "ko": "운영 환경에 가까운 성능 테스트"
  },
  "azure-waf:PE:07": {
    "en": "Optimize code and infrastructure",
    "ko": "코드와 인프라 성능 최적화"
  },
  "azure-waf:PE:08": {
    "en": "Optimize data usage and data-store performance",
    "ko": "데이터 사용과 저장소 성능 최적화"
  },
  "azure-waf:PE:09": {
    "en": "Prioritize performance of critical flows",
    "ko": "핵심 흐름의 성능 우선 관리"
  },
  "azure-waf:PE:10": {
    "en": "Minimize operational task performance impact",
    "ko": "운영 작업의 성능 영향 최소화"
  },
  "azure-waf:PE:11": {
    "en": "Respond effectively to live performance issues",
    "ko": "실시간 성능 문제 대응"
  },
  "azure-waf:PE:12": {
    "en": "Continuously optimize deteriorating performance",
    "ko": "지속적인 성능 저하 개선"
  },
  "azure-waf:RE:01": {
    "en": "Focus workload design on simplicity and efficiency",
    "ko": "단순하고 효율적인 워크로드 설계"
  },
  "azure-waf:RE:02": {
    "en": "Identify and rate user and system flows",
    "ko": "사용자 및 시스템 흐름 식별과 등급화"
  },
  "azure-waf:RE:03": {
    "en": "Perform failure mode analysis",
    "ko": "장애 유형 분석"
  },
  "azure-waf:RE:04": {
    "en": "Define reliability and recovery targets",
    "ko": "안정성과 복구 목표 정의"
  },
  "azure-waf:RE:05": {
    "en": "Add redundancy for critical flows",
    "ko": "핵심 흐름에 중복성 추가"
  },
  "azure-waf:RE:06": {
    "en": "Implement timely and reliable scaling",
    "ko": "적시에 안정적으로 확장"
  },
  "azure-waf:RE:07": {
    "en": "Implement self-preservation and self-healing",
    "ko": "자체 보호와 자체 복구 구현"
  },
  "azure-waf:RE:08": {
    "en": "Test resiliency and availability scenarios",
    "ko": "복원력과 가용성 시나리오 테스트"
  },
  "azure-waf:RE:09": {
    "en": "Implement tested disaster recovery plans",
    "ko": "검증된 재해 복구 계획"
  },
  "azure-waf:RE:10": {
    "en": "Continuously measure and track system health",
    "ko": "시스템 상태의 지속 측정"
  },
  "azure-waf:SE:01": {
    "en": "Establish and continuously improve a security baseline",
    "ko": "보안 기준선 수립과 지속 개선"
  },
  "azure-waf:SE:02": {
    "en": "Apply a secure development lifecycle",
    "ko": "보안 개발 수명 주기 적용"
  },
  "azure-waf:SE:03": {
    "en": "Classify workload data and systems",
    "ko": "데이터와 시스템 분류"
  },
  "azure-waf:SE:04": {
    "en": "Design intentional segmentation and perimeters",
    "ko": "의도적인 분할과 경계 설계"
  },
  "azure-waf:SE:05": {
    "en": "Implement strict conditional and auditable identity and access management",
    "ko": "엄격하고 조건부이며 감사 가능한 접근 관리"
  },
  "azure-waf:SE:06": {
    "en": "Isolate filter and control network traffic",
    "ko": "네트워크 트래픽 격리와 필터링"
  },
  "azure-waf:SE:07": {
    "en": "Encrypt data with modern methods",
    "ko": "현대적인 방식으로 데이터 암호화"
  },
  "azure-waf:SE:08": {
    "en": "Harden workload resources",
    "ko": "워크로드 리소스 강화"
  },
  "azure-waf:SE:09": {
    "en": "Protect and rotate application secrets",
    "ko": "애플리케이션 비밀 보호와 교체"
  },
  "azure-waf:SE:10": {
    "en": "Implement holistic threat monitoring",
    "ko": "종합적인 위협 모니터링"
  },
  "azure-waf:SE:11": {
    "en": "Establish comprehensive security testing",
    "ko": "포괄적인 보안 테스트"
  },
  "azure-waf:SE:12": {
    "en": "Define and test security incident response",
    "ko": "보안 인시던트 대응 정의와 테스트"
  },
  "azure-mcsb:AM-1": {
    "en": "Track asset inventory and their risks",
    "ko": "자산 목록과 위험 추적"
  },
  "azure-mcsb:AM-2": {
    "en": "Use only approved services",
    "ko": "승인된 서비스만 사용"
  },
  "azure-mcsb:AM-3": {
    "en": "Ensure security of asset lifecycle management",
    "ko": "자산 수명 주기 보안"
  },
  "azure-mcsb:AM-4": {
    "en": "Limit access to asset management",
    "ko": "자산 관리 접근 제한"
  },
  "azure-mcsb:AM-5": {
    "en": "Use only approved applications in virtual machine",
    "ko": "가상 머신에서 승인된 애플리케이션만 사용"
  },
  "azure-mcsb:BR-1": {
    "en": "Ensure regular automated backups",
    "ko": "정기 자동 백업 보장"
  },
  "azure-mcsb:BR-2": {
    "en": "Protect backup and recovery data",
    "ko": "백업 및 복구 데이터 보호"
  },
  "azure-mcsb:BR-3": {
    "en": "Monitor backups",
    "ko": "백업 모니터링"
  },
  "azure-mcsb:BR-4": {
    "en": "Regularly test backup",
    "ko": "정기 백업 복원 시험"
  },
  "azure-mcsb:DP-1": {
    "en": "Discover, classify, and label sensitive data",
    "ko": "민감한 데이터 탐색과 분류 및 표시"
  },
  "azure-mcsb:DP-2": {
    "en": "Monitor anomalies and threats targeting sensitive data",
    "ko": "민감한 데이터 대상 위협 모니터링"
  },
  "azure-mcsb:DP-3": {
    "en": "Encrypt sensitive data in transit",
    "ko": "전송 중 민감한 데이터 암호화"
  },
  "azure-mcsb:DP-4": {
    "en": "Enable data at rest encryption by default",
    "ko": "기본 저장 암호화 활성화"
  },
  "azure-mcsb:DP-5": {
    "en": "Use customer-managed key option in data at rest encryption when required",
    "ko": "필요한 경우 고객 관리 키 사용"
  },
  "azure-mcsb:DP-6": {
    "en": "Use a secure key management process",
    "ko": "안전한 키 관리 절차"
  },
  "azure-mcsb:DP-7": {
    "en": "Use a secure certificate management process",
    "ko": "안전한 인증서 관리 절차"
  },
  "azure-mcsb:DP-8": {
    "en": "Ensure security of key and certificate repository",
    "ko": "키와 인증서 저장소 보안"
  },
  "azure-mcsb:DS-1": {
    "en": "Conduct threat modeling",
    "ko": "위협 모델링 수행"
  },
  "azure-mcsb:DS-2": {
    "en": "Ensure software supply chain security",
    "ko": "소프트웨어 공급 체인 보안"
  },
  "azure-mcsb:DS-3": {
    "en": "Secure DevOps infrastructure",
    "ko": "DevOps 인프라 보안"
  },
  "azure-mcsb:DS-4": {
    "en": "Integrate static application security testing into DevOps pipeline",
    "ko": "파이프라인에 정적 보안 분석 통합"
  },
  "azure-mcsb:DS-5": {
    "en": "Integrate dynamic application security testing into DevOps pipeline",
    "ko": "파이프라인에 동적 보안 분석 통합"
  },
  "azure-mcsb:DS-6": {
    "en": "Enforce security of workload throughout DevOps lifecycle",
    "ko": "DevOps 수명 주기 전반의 보안 적용"
  },
  "azure-mcsb:DS-7": {
    "en": "Enable logging and monitoring in DevOps",
    "ko": "DevOps 로그와 모니터링 활성화"
  },
  "azure-mcsb:ES-1": {
    "en": "Use Endpoint Detection and Response (EDR)",
    "ko": "엔드포인트 탐지 및 대응 사용"
  },
  "azure-mcsb:ES-2": {
    "en": "Use modern anti-malware software",
    "ko": "최신 맬웨어 방지 사용"
  },
  "azure-mcsb:ES-3": {
    "en": "Ensure anti-malware software and signatures are updated",
    "ko": "맬웨어 방지 소프트웨어와 서명 갱신"
  },
  "azure-mcsb:GS-1": {
    "en": "Align organization roles, responsibilities and accountabilities",
    "ko": "보안 역할과 책임 정렬"
  },
  "azure-mcsb:GS-10": {
    "en": "Define and implement DevOps security strategy",
    "ko": "DevOps 보안 전략 수립"
  },
  "azure-mcsb:GS-11": {
    "en": "Define and implement multi-cloud security strategy",
    "ko": "다중 클라우드 보안 전략 수립"
  },
  "azure-mcsb:GS-2": {
    "en": "Define and implement enterprise segmentation/separation of duties strategy",
    "ko": "분할과 직무 분리 전략 수립"
  },
  "azure-mcsb:GS-3": {
    "en": "Define and implement data protection strategy",
    "ko": "데이터 보호 전략 수립"
  },
  "azure-mcsb:GS-4": {
    "en": "Define and implement network security strategy",
    "ko": "네트워크 보안 전략 수립"
  },
  "azure-mcsb:GS-5": {
    "en": "Define and implement security posture management strategy",
    "ko": "보안 태세 관리 전략 수립"
  },
  "azure-mcsb:GS-6": {
    "en": "Define and implement identity and privileged access strategy",
    "ko": "신원과 권한 접근 전략 수립"
  },
  "azure-mcsb:GS-7": {
    "en": "Define and implement logging, threat detection and incident response strategy",
    "ko": "로그와 위협 감지 및 대응 전략 수립"
  },
  "azure-mcsb:GS-8": {
    "en": "Define and implement backup and recovery strategy",
    "ko": "백업과 복구 전략 수립"
  },
  "azure-mcsb:GS-9": {
    "en": "Define and implement endpoint security strategy",
    "ko": "엔드포인트 보안 전략 수립"
  },
  "azure-mcsb:IM-1": {
    "en": "Use centralized identity and authentication system",
    "ko": "중앙 신원 및 인증 체계 사용"
  },
  "azure-mcsb:IM-2": {
    "en": "Protect identity and authentication systems",
    "ko": "신원 및 인증 체계 보호"
  },
  "azure-mcsb:IM-3": {
    "en": "Manage application identities securely and automatically",
    "ko": "애플리케이션 신원의 안전한 자동 관리"
  },
  "azure-mcsb:IM-4": {
    "en": "Authenticate server and services",
    "ko": "서버와 서비스 인증"
  },
  "azure-mcsb:IM-5": {
    "en": "Use single sign-on (SSO) for application access",
    "ko": "애플리케이션 접근에 SSO 사용"
  },
  "azure-mcsb:IM-6": {
    "en": "Use strong authentication controls",
    "ko": "강력한 인증 통제 사용"
  },
  "azure-mcsb:IM-7": {
    "en": "Restrict resource access based on  conditions",
    "ko": "조건에 따른 리소스 접근 제한"
  },
  "azure-mcsb:IM-8": {
    "en": "Restrict the exposure of credential and secrets",
    "ko": "자격 증명과 비밀 노출 제한"
  },
  "azure-mcsb:IM-9": {
    "en": "Secure user access to  existing applications",
    "ko": "기존 애플리케이션 사용자 접근 보호"
  },
  "azure-mcsb:IR-1": {
    "en": "Preparation - update incident response plan and handling process",
    "ko": "인시던트 대응 계획과 절차 준비"
  },
  "azure-mcsb:IR-2": {
    "en": "Preparation - setup incident contact information",
    "ko": "인시던트 연락처 준비"
  },
  "azure-mcsb:IR-3": {
    "en": "Detection and analysis - create incidents based on high-quality alerts",
    "ko": "양질의 경고로 인시던트 생성"
  },
  "azure-mcsb:IR-4": {
    "en": "Detection and analysis - investigate an incident",
    "ko": "인시던트 조사"
  },
  "azure-mcsb:IR-5": {
    "en": "Detection and analysis - prioritize incidents",
    "ko": "인시던트 우선순위 결정"
  },
  "azure-mcsb:IR-6": {
    "en": "Containment, eradication and recovery - automate the incident handling",
    "ko": "인시던트 처리 자동화"
  },
  "azure-mcsb:IR-7": {
    "en": "Post-incident activity - conduct lesson learned and retain evidence",
    "ko": "사후 학습과 증거 보존"
  },
  "azure-mcsb:LT-1": {
    "en": "Enable threat detection capabilities",
    "ko": "위협 감지 기능 활성화"
  },
  "azure-mcsb:LT-2": {
    "en": "Enable threat detection for  identity and access management",
    "ko": "신원 및 접근 위협 감지 활성화"
  },
  "azure-mcsb:LT-3": {
    "en": "Enable logging for security investigation",
    "ko": "보안 조사를 위한 로그 활성화"
  },
  "azure-mcsb:LT-4": {
    "en": "Enable network logging for security investigation",
    "ko": "보안 조사를 위한 네트워크 로그 활성화"
  },
  "azure-mcsb:LT-5": {
    "en": "Centralize security log management and analysis",
    "ko": "보안 로그 관리와 분석 중앙화"
  },
  "azure-mcsb:LT-6": {
    "en": "Configure log storage retention",
    "ko": "로그 저장 보존 기간 구성"
  },
  "azure-mcsb:LT-7": {
    "en": "Use approved time synchronization sources",
    "ko": "승인된 시간 동기화 원천 사용"
  },
  "azure-mcsb:NS-1": {
    "en": "Establish network segmentation boundaries",
    "ko": "네트워크 분할 경계 수립"
  },
  "azure-mcsb:NS-10": {
    "en": "Ensure Domain Name System (DNS) security",
    "ko": "DNS 보안 보장"
  },
  "azure-mcsb:NS-2": {
    "en": "Secure cloud native services with network controls",
    "ko": "클라우드 기본 서비스의 네트워크 통제"
  },
  "azure-mcsb:NS-3": {
    "en": "Deploy firewall at the edge of enterprise network",
    "ko": "네트워크 경계에 방화벽 배치"
  },
  "azure-mcsb:NS-4": {
    "en": "Deploy intrusion detection/intrusion prevention systems (IDS/IPS)",
    "ko": "침입 탐지 및 방지 배치"
  },
  "azure-mcsb:NS-5": {
    "en": "Deploy DDOS protection",
    "ko": "DDoS 보호 배치"
  },
  "azure-mcsb:NS-6": {
    "en": "Deploy web application firewall",
    "ko": "웹 애플리케이션 방화벽 배치"
  },
  "azure-mcsb:NS-7": {
    "en": "Simplify network security configuration",
    "ko": "네트워크 보안 구성 단순화"
  },
  "azure-mcsb:NS-8": {
    "en": "Detect and disable insecure services and  protocols",
    "ko": "안전하지 않은 서비스와 프로토콜 비활성화"
  },
  "azure-mcsb:NS-9": {
    "en": "Connect on-premises or cloud network privately",
    "ko": "온프레미스 또는 클라우드 네트워크의 비공개 연결"
  },
  "azure-mcsb:PA-1": {
    "en": "Separate and limit highly privileged/administrative users",
    "ko": "고권한 관리자 분리와 제한"
  },
  "azure-mcsb:PA-2": {
    "en": "Avoid standing access for user accounts and permissions",
    "ko": "상시 사용자 권한 방지"
  },
  "azure-mcsb:PA-3": {
    "en": "Manage lifecycle of identities and entitlements",
    "ko": "신원과 권한 수명 주기 관리"
  },
  "azure-mcsb:PA-4": {
    "en": "Review and reconcile user access regularly",
    "ko": "사용자 접근의 정기 검토와 조정"
  },
  "azure-mcsb:PA-5": {
    "en": "Set up emergency access",
    "ko": "비상 접근 준비"
  },
  "azure-mcsb:PA-6": {
    "en": "Use privileged access workstations / channel for administrative tasks",
    "ko": "관리 작업용 보안 워크스테이션과 경로 사용"
  },
  "azure-mcsb:PA-7": {
    "en": "Follow just enough administration (least privilege) principle",
    "ko": "필요한 최소 관리 권한 적용"
  },
  "azure-mcsb:PA-8": {
    "en": "Determine access process for cloud provider support",
    "ko": "클라우드 공급자 지원 접근 절차 결정"
  },
  "azure-mcsb:PV-1": {
    "en": "Define and establish secure configurations",
    "ko": "안전한 구성 기준 수립"
  },
  "azure-mcsb:PV-2": {
    "en": "Audit and enforce secure configurations",
    "ko": "안전한 구성 감사와 강제 적용"
  },
  "azure-mcsb:PV-3": {
    "en": "Define and establish secure configurations for compute resources",
    "ko": "컴퓨팅 리소스의 안전 구성 수립"
  },
  "azure-mcsb:PV-4": {
    "en": "Audit and enforce secure configurations for compute resources",
    "ko": "컴퓨팅 안전 구성 감사와 강제 적용"
  },
  "azure-mcsb:PV-5": {
    "en": "Perform vulnerability assessments",
    "ko": "취약점 평가 수행"
  },
  "azure-mcsb:PV-6": {
    "en": "Rapidly and automatically remediate vulnerabilities",
    "ko": "취약점의 신속하고 자동화된 수정"
  },
  "azure-mcsb:PV-7": {
    "en": "Conduct regular red team operations",
    "ko": "정기적인 레드팀 활동 수행"
  },
  "azure-caf:adopt": {
    "en": "Adopt",
    "ko": "클라우드 도입 실행"
  },
  "azure-caf:govern": {
    "en": "Govern",
    "ko": "클라우드 거버넌스 운영"
  },
  "azure-caf:landing-zone.billing-tenant": {
    "en": "Landing zone: billing and tenant",
    "ko": "랜딩 존 청구 및 테넌트 설계"
  },
  "azure-caf:landing-zone.governance": {
    "en": "Landing zone: governance",
    "ko": "랜딩 존 거버넌스 설계"
  },
  "azure-caf:landing-zone.identity-access": {
    "en": "Landing zone: identity and access",
    "ko": "랜딩 존 신원 및 접근 설계"
  },
  "azure-caf:landing-zone.management": {
    "en": "Landing zone: management",
    "ko": "랜딩 존 관리 설계"
  },
  "azure-caf:landing-zone.network-connectivity": {
    "en": "Landing zone: network topology and connectivity",
    "ko": "랜딩 존 네트워크와 연결 설계"
  },
  "azure-caf:landing-zone.platform-automation-devops": {
    "en": "Landing zone: platform automation and DevOps",
    "ko": "랜딩 존 플랫폼 자동화와 DevOps 설계"
  },
  "azure-caf:landing-zone.resource-organization": {
    "en": "Landing zone: resource organization",
    "ko": "랜딩 존 리소스 구성"
  },
  "azure-caf:landing-zone.security": {
    "en": "Landing zone: security",
    "ko": "랜딩 존 보안 설계"
  },
  "azure-caf:manage": {
    "en": "Manage",
    "ko": "클라우드 운영 관리"
  },
  "azure-caf:plan": {
    "en": "Plan",
    "ko": "클라우드 도입 계획"
  },
  "azure-caf:ready": {
    "en": "Ready",
    "ko": "클라우드 환경 준비"
  },
  "azure-caf:secure": {
    "en": "Secure",
    "ko": "클라우드 보안 운영 체계"
  },
  "azure-caf:strategy": {
    "en": "Strategy",
    "ko": "클라우드 도입 전략"
  }
};

const CONTROL_IMAGE_BINDINGS: Readonly<Record<string, string>> = {
  "azure-waf:RE:02": "point-in-time-restore-diagram",
  "azure-waf:RE:04": "geo-zone-redundant-storage",
  "azure-waf:RE:05": "bfd-need",
  "azure-waf:RE:06": "aks-node-pools",
  "azure-waf:RE:07": "appgatewayprobe",
  "azure-waf:RE:08": "scheduled-events-timeline",
  "azure-waf:RE:09": "vmbackup-architecture",
  "azure-waf:RE:10": "aks-monitor-data-v2",
  "azure-waf:SE:04": "fastpath-vnet-peering",
  "azure-waf:SE:06": "front-door-overview",
  "azure-waf:SE:09": "backup-item-delete-flow",
  "azure-waf:SE:10": "main-diagram",
  "azure-waf:OE:05": "02-soft-delete",
  "azure-waf:OE:07": "network-watcher-capabilities",
  "azure-waf:OE:09": "scheduled-events-timeline",
  "azure-waf:PE:03": "appgatewayprobe",
  "azure-waf:PE:05": "aks-node-pools",
  "azure-waf:PE:07": "front-door-overview",
  "azure-caf:ready": "avs-interconnect",
  "azure-caf:manage": "network-watcher-capabilities",
  "azure-caf:landing-zone.network-connectivity": "fastpath-vnet-peering",
  "azure-caf:landing-zone.security": "front-door-overview",
  "azure-caf:landing-zone.management": "vmbackup-architecture",
  "azure-caf:landing-zone.governance": "data-export-overview",
  "azure-caf:landing-zone.platform-automation-devops": "02-soft-delete",
  "azure-mcsb:NS-2": "fastpath-vnet-peering",
  "azure-mcsb:NS-3": "fastpath-vnet-peering",
  "azure-mcsb:NS-4": "network-watcher-capabilities",
  "azure-mcsb:NS-5": "front-door-overview",
  "azure-mcsb:NS-6": "front-door-overview",
  "azure-mcsb:NS-9": "bfd-need",
  "azure-mcsb:DP-4": "geo-zone-redundant-storage",
  "azure-mcsb:LT-1": "aks-monitor-data-v2",
  "azure-mcsb:LT-3": "data-export-overview",
  "azure-mcsb:LT-4": "main-diagram",
  "azure-mcsb:LT-5": "data-export-overview",
  "azure-mcsb:LT-6": "data-export-overview",
  "azure-mcsb:IR-3": "aks-monitor-data-v2",
  "azure-mcsb:PV-3": "aks-node-pools",
  "azure-mcsb:PV-6": "scheduled-events-timeline",
  "azure-mcsb:BR-1": "vmbackup-architecture",
  "azure-mcsb:BR-2": "backup-item-delete-flow",
  "azure-mcsb:BR-3": "vmbackup-architecture",
  "azure-mcsb:BR-4": "point-in-time-restore-diagram",
  "azure-mcsb:DS-2": "02-soft-delete",
  "azure-mcsb:DS-6": "02-soft-delete"
};

export function resolveControlReferenceImage(
  scope: "azure-waf" | "azure-caf" | "azure-mcsb" | "mcsb-v2-preview" | "msrc-csaf" | "rule",
  id: string,
  resourceType?: string,
): GuidanceReferenceImage | undefined {
  const direct = CONTROL_IMAGE_BINDINGS[`${scope}:${id}`];
  if (direct) return PACKAGED_REFERENCE_IMAGES[direct];
  if (scope === "mcsb-v2-preview") {
    const v1Mapped = CONTROL_IMAGE_BINDINGS[`azure-mcsb:${id}`];
    if (v1Mapped) return PACKAGED_REFERENCE_IMAGES[v1Mapped];
  }
  const lower = `${id} ${resourceType ?? ""}`.toLowerCase();
  if (lower.includes("node-pool") || lower.includes("multi-zone") || lower.includes("aks") && lower.includes("zone")) {
    return PACKAGED_REFERENCE_IMAGES["aks-node-pools"];
  }
  if (lower.includes("kubernetes") && (lower.includes("diagnostic") || lower.includes("monitor") || lower.includes("audit"))) {
    return PACKAGED_REFERENCE_IMAGES["aks-monitor-data-v2"];
  }
  if (lower.includes("point-in-time") || lower.includes("versioning") || lower.includes("soft-delete-blob")) {
    return PACKAGED_REFERENCE_IMAGES["point-in-time-restore-diagram"];
  }
  if (lower.includes("object-storage") || lower.includes("storage") && (lower.includes("geo") || lower.includes("redundan") || lower.includes("encryption"))) {
    return PACKAGED_REFERENCE_IMAGES["geo-zone-redundant-storage"];
  }
  if (lower.includes("snapshot") || lower.includes("backup") && lower.includes("vm")) {
    return PACKAGED_REFERENCE_IMAGES["vmbackup-architecture"];
  }
  if (lower.includes("purge-protection") || lower.includes("soft-delete") && lower.includes("secret")) {
    return PACKAGED_REFERENCE_IMAGES["backup-item-delete-flow"];
  }
  if (lower.includes("containerregistry") || lower.includes("acr")) {
    return PACKAGED_REFERENCE_IMAGES["02-soft-delete"];
  }
  if (lower.includes("frontdoor") || lower.includes("waf") || lower.includes("ddos")) {
    return PACKAGED_REFERENCE_IMAGES["front-door-overview"];
  }
  if (lower.includes("applicationgateway") || lower.includes("probe")) {
    return PACKAGED_REFERENCE_IMAGES["appgatewayprobe"];
  }
  if (lower.includes("nsg") || lower.includes("network-watcher") || lower.includes("network-policy")) {
    return PACKAGED_REFERENCE_IMAGES["network-watcher-capabilities"];
  }
  if (lower.includes("private-endpoint") || lower.includes("private-cluster") || lower.includes("vnet") || lower.includes("peering")) {
    return PACKAGED_REFERENCE_IMAGES["fastpath-vnet-peering"];
  }
  if (lower.includes("diagnostic-settings") || lower.includes("log") && lower.includes("workspace")) {
    return PACKAGED_REFERENCE_IMAGES["data-export-overview"];
  }
  return undefined;
}

export function frameworkDisplayTitle(
  frameworkId: "azure-waf" | "azure-caf" | "azure-mcsb",
  control: { readonly control_id: string; readonly title: string; readonly title_ko?: string | null },
  locale: string,
): string {
  if (locale !== "ko") return control.title;
  if (control.title_ko) return control.title_ko;
  const entry = FRAMEWORK_TITLES_BY_KEY[`${frameworkId}:${control.control_id}`];
  if (entry && entry.en === control.title) return entry.ko;
  return control.title;
}
