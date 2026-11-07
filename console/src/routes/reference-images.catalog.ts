import type { GuidanceReferenceImage, GuidanceText } from "./wara-guidance.model";

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

type McsbControlTuple = readonly [
  string, string, string, string, string, string, string, string, string, string, string, string,
];

const MCSB_CONTROL_TUPLES: Readonly<Record<string, McsbControlTuple>> = {
  "IM-1": ["Central authentication supplies a consistent identity source for supported applications.", "중앙 인증은 지원 애플리케이션에 일관된 신원 원천을 제공합니다.", "Account lifecycle and authentication review can follow shared controls.", "계정 수명 주기와 인증 검토에 공통 통제를 적용할 수 있습니다.", "Each application maintains unrelated local user passwords.", "각 애플리케이션이 별개의 로컬 사용자 암호를 관리합니다.", "Integrate supported applications with the approved central identity provider.", "지원 애플리케이션을 승인된 중앙 신원 공급자와 연동합니다.", "Test user authentication and account disablement across integrated applications.", "연동 애플리케이션의 사용자 인증과 계정 비활성화를 시험합니다.", "Central identity becomes a critical dependency needing protection and recovery.", "중앙 신원은 보호와 복구가 필요한 핵심 의존성이 됩니다."],
  "IM-2": ["Protecting identity administration and configuration guards the root of access trust.", "신원 관리와 구성을 보호하면 접근 신뢰의 근간을 지킬 수 있습니다.", "Compromise of authentication infrastructure is less likely to spread unchecked.", "인증 인프라 침해가 통제 없이 확산할 가능성을 줄일 수 있습니다.", "Identity administrators use broadly accessible sessions without dedicated monitoring.", "신원 관리자가 전용 모니터링 없이 광범위하게 접근 가능한 세션을 사용합니다.", "Harden identity administration and monitor sensitive authentication configuration changes.", "신원 관리를 강화하고 민감한 인증 구성 변경을 모니터링합니다.", "Review privileged identity changes and test the expected alert and access restriction.", "권한 신원 변경을 검토하고 예상 경고 및 접근 제한을 시험합니다.", "Emergency identity recovery must not depend solely on the failed control.", "비상 신원 복구를 실패한 통제에만 의존하지 않습니다."],
  "IM-3": ["Managed workload identities reduce manually distributed application credentials.", "관리되는 워크로드 신원은 수동 배포하는 애플리케이션 자격 증명을 줄입니다.", "Credential lifetime and application access can be managed more consistently.", "자격 증명 수명과 애플리케이션 접근을 더 일관되게 관리할 수 있습니다.", "An application shares a long-lived service password across environments.", "애플리케이션이 여러 환경에서 장기 서비스 암호를 공유합니다.", "Use supported managed or federated identities with scoped resource permissions.", "제한된 리소스 권한을 갖춘 지원 관리형 또는 연합 신원을 사용합니다.", "Confirm the application authenticates without embedded secrets and cannot exceed its role.", "내장 비밀 없이 인증하고 배정 역할을 넘지 못하는지 확인합니다.", "A managed identity can still be overprivileged.", "Managed Identity도 과도한 권한을 가질 수 있습니다."],
  "IM-4": ["Service authentication verifies the peer before trusting machine-to-machine requests.", "서비스 인증은 시스템 간 요청을 신뢰하기 전에 상대를 검증합니다.", "Traffic origin is not mistaken for authenticated service identity.", "트래픽 출발지를 인증된 서비스 신원으로 오인하지 않을 수 있습니다.", "A backend trusts any caller from the private network.", "백엔드가 사설 네트워크의 모든 호출자를 신뢰합니다.", "Require supported service credentials or certificate-based peer authentication.", "지원 서비스 자격 증명이나 인증서 기반 상대 인증을 요구합니다.", "Test valid peers and rejection of missing, expired or wrong-audience credentials.", "유효한 상대와 누락, 만료, 잘못된 대상의 자격 증명 거부를 시험합니다.", "Trust-store and certificate rotation errors can interrupt service communication.", "신뢰 저장소와 인증서 교체 오류는 서비스 통신을 중단시킬 수 있습니다."],
  "IM-5": ["Single sign-on reuses approved authentication instead of multiplying application passwords.", "SSO는 애플리케이션 암호를 늘리는 대신 승인된 인증을 재사용합니다.", "Users and administrators can manage access with fewer separate credentials.", "사용자와 관리자는 더 적은 별도 자격 증명으로 접근을 관리할 수 있습니다.", "Users maintain separate passwords for every supported business application.", "사용자가 지원 업무 애플리케이션마다 별도 암호를 관리합니다.", "Integrate approved applications with the organization's supported SSO flow.", "승인 애플리케이션을 조직이 지원하는 SSO 흐름과 연동합니다.", "Verify sign-in, session expiry and revoked-user access for a representative application.", "대표 애플리케이션에서 로그인, 세션 만료, 철회 사용자의 접근을 확인합니다.", "A central session compromise can affect several applications.", "중앙 세션이 침해되면 여러 애플리케이션에 영향을 줄 수 있습니다."],
  "IM-6": ["Stronger authentication requires more assurance than possession of a reusable password.", "강력한 인증은 재사용 암호 보유보다 높은 신원 확인 수준을 요구합니다.", "Stolen passwords alone become less useful for account takeover.", "도난당한 암호만으로 계정을 탈취하기 어렵게 할 수 있습니다.", "Sensitive access accepts a password with no additional assurance.", "추가 확인 없이 암호만으로 민감한 접근을 허용합니다.", "Apply approved strong authentication requirements to relevant users and sensitive actions.", "해당 사용자와 민감한 작업에 승인된 강력한 인증 요구를 적용합니다.", "Test the required authentication challenge and review excluded accounts.", "필수 인증 확인 절차를 시험하고 제외 계정을 검토합니다.", "Recovery and enrollment flows need protection comparable to normal authentication.", "복구 및 등록 흐름도 일반 인증에 준하는 보호가 필요합니다."],
  "IM-7": ["Conditional access evaluates relevant identity and device context before admission.", "조건부 접근은 허용 전에 신원과 기기의 관련 맥락을 평가합니다.", "Access can reflect current risk rather than a static password check alone.", "정적인 암호 확인뿐 아니라 현재 위험을 반영해 접근을 결정할 수 있습니다.", "A valid login permits access regardless of device or sign-in risk.", "로그인이 유효하면 기기나 로그인 위험과 무관하게 접근을 허용합니다.", "Define reviewed access conditions and test them before broad enforcement.", "접근 조건을 검토해 정하고 광범위한 강제 적용 전에 시험합니다.", "Exercise an allowed context and a denied or challenged context.", "허용하는 상황과 거부하거나 추가 확인하는 상황을 시험합니다.", "An overly broad policy can lock out administrators and recovery paths.", "과도하게 넓은 정책은 관리자와 복구 경로를 차단할 수 있습니다."],
  "IM-8": ["Secret handling controls keep credentials out of code, logs and distributed files.", "비밀 처리 통제는 자격 증명이 코드, 로그, 배포 파일에 들어가지 않게 합니다.", "Accidental disclosure has fewer persistent copies to exploit.", "우발적 노출 시 악용할 수 있는 잔여 사본을 줄일 수 있습니다.", "A connection password appears in a repository and pipeline output.", "연결 암호가 저장소와 파이프라인 출력에 나타납니다.", "Remove exposed credentials, rotate them and use approved secret references.", "노출된 자격 증명을 제거하고 교체한 뒤 승인된 비밀 참조를 사용합니다.", "Scan relevant artifacts and verify retired credentials can no longer authenticate.", "해당 산출물을 검사하고 폐기 자격 증명으로 인증할 수 없는지 확인합니다.", "Never include live credentials in remediation or test evidence.", "수정이나 테스트 근거 자료에 실제 자격 증명을 넣지 않습니다."],
  "IR-1": ["An updated response plan defines roles, decisions and handling before an incident.", "최신 대응 계획은 인시던트 전에 역할, 결정, 처리를 정합니다.", "Responders can coordinate without inventing their process under pressure.", "대응자는 긴급 상황에서 절차를 새로 만들지 않고 협력할 수 있습니다.", "The response plan names former staff and obsolete systems.", "대응 계획에 퇴사자와 더 이상 쓰지 않는 시스템이 적혀 있습니다.", "Review response roles, severity rules, escalation and evidence handling with owners.", "담당자와 대응 역할, 심각도 규칙, 보고, 증거 처리를 검토합니다.", "Run a tabletop and verify current roles and decision paths.", "모의 훈련으로 현재 역할과 결정 경로를 확인합니다.", "Response procedures do not bypass approval or legal obligations.", "대응 절차가 승인이나 법적 의무를 우회하지는 않습니다."],
  "IR-2": ["Maintained contact routes connect incident decisions to reachable responders.", "관리하는 연락 경로는 인시던트 결정을 연락 가능한 대응자와 연결합니다.", "Escalation is less likely to stall on an obsolete contact.", "오래된 연락처 때문에 보고가 멈출 가능성을 줄일 수 있습니다.", "An emergency contact list has no tested primary or backup route.", "비상 연락처 목록에 시험한 기본 또는 대체 경로가 없습니다.", "Assign contact ownership and maintain primary and backup escalation routes.", "연락처 담당자를 정하고 기본 및 대체 보고 경로를 유지합니다.", "Perform an authorized contact drill and verify acknowledgement and fallback.", "승인된 연락 훈련으로 수신 확인과 대체 경로를 검증합니다.", "A delivered message is not proof that a responder accepted ownership.", "메시지 전달이 대응자의 책임 수락을 입증하지는 않습니다."],
  "IR-3": ["Triage criteria convert actionable signals into incidents with enough context.", "분류 기준은 대응 가능한 신호를 충분한 맥락이 있는 인시던트로 바꿉니다.", "Responders spend less time reconstructing basic alert context.", "대응자가 기본 경고 맥락을 다시 구성하는 시간을 줄일 수 있습니다.", "Every raw alert becomes an incident without deduplication or impact context.", "중복 제거나 영향 정보 없이 모든 원시 경고가 인시던트가 됩니다.", "Define incident creation criteria, deduplication and minimum investigation context.", "인시던트 생성 기준, 중복 제거, 최소 조사 맥락을 정합니다.", "Replay representative alerts and inspect incident quality and ownership.", "대표 경고를 재현하고 인시던트 품질과 담당자를 확인합니다.", "Over-filtering can suppress real incidents; retain reviewable disposition records.", "과도한 필터링은 실제 인시던트를 숨길 수 있으므로 검토 가능한 처리 기록을 남깁니다."],
  "IR-4": ["Correlated timelines and preserved evidence support a bounded investigation.", "연결한 시간 기록과 보존한 증거는 범위가 제한된 조사를 뒷받침합니다.", "Conclusions can be traced to observed facts rather than assumptions.", "결론을 가정이 아니라 관측 사실까지 추적할 수 있습니다.", "An incident is closed from one dashboard screenshot.", "화면 캡처 하나만 보고 인시던트를 종료합니다.", "Collect authorized logs and state with timestamps, provenance and explicit gaps.", "시간, 출처, 명시적인 공백과 함께 승인된 로그 및 상태를 수집합니다.", "Trace a finding to original records and check alternative explanations.", "판단을 원본 기록까지 추적하고 다른 설명을 검토합니다.", "Evidence handling must preserve integrity, privacy and chain of custody where required.", "증거 처리는 필요한 경우 무결성, 개인정보, 보관 이력을 보존해야 합니다."],
  "IR-5": ["Impact and urgency criteria order incident response work.", "영향과 긴급도 기준은 인시던트 대응 작업의 순서를 정합니다.", "Limited responders can focus on the most consequential incidents.", "제한된 대응 인력을 영향이 가장 큰 인시던트에 집중할 수 있습니다.", "The loudest alert receives priority without business impact review.", "사업 영향 검토 없이 가장 시끄러운 경고를 우선합니다.", "Define severity criteria using affected services, data sensitivity and active impact.", "영향 서비스, 데이터 민감도, 현재 영향을 바탕으로 심각도 기준을 정합니다.", "Compare representative triage decisions with the declared severity criteria.", "대표 분류 결정을 선언한 심각도 기준과 비교합니다.", "Priority must be revisited as impact evidence changes.", "영향 근거가 바뀌면 우선순위를 다시 검토해야 합니다."],
  "IR-6": ["Bounded playbooks automate approved containment and recovery steps.", "제한된 대응 절차서는 승인된 격리 및 복구 단계를 자동화합니다.", "Repeatable response steps can execute with consistent audit and recovery behavior.", "반복 대응 단계를 일관된 감사 및 복구 동작과 함께 실행할 수 있습니다.", "A script isolates every host from a broad alert without target review.", "스크립트가 광범위한 경고만 보고 대상 검토 없이 모든 호스트를 격리합니다.", "Design approved playbooks with exact targets, stop conditions and rollback.", "정확한 대상, 중지 조건, 롤백을 포함해 승인된 대응 절차서를 설계합니다.", "Exercise a safe incident and inspect authorization, target scope and independently observed effect.", "안전한 인시던트를 시험하고 권한, 대상 범위, 독립적으로 관측한 효과를 확인합니다.", "False positives can cause legitimate service outages when automated aggressively.", "오탐을 급격히 자동 처리하면 정상 서비스가 중단될 수 있습니다."],
  "IR-7": ["Post-incident review connects contributing factors to owned improvements and retained evidence.", "사후 검토는 기여 요인을 담당자가 있는 개선 및 보존 증거와 연결합니다.", "Lessons can change future operations instead of remaining narrative summaries.", "교훈을 서술형 요약에 그치지 않고 이후 운영에 반영할 수 있습니다.", "The incident closes without action owners or evidence retention decisions.", "조치 담당자나 증거 보존 결정 없이 인시던트를 종료합니다.", "Review the timeline, assign improvement actions and apply approved retention rules.", "시간 기록을 검토하고 개선 작업을 배정하며 승인된 보존 규칙을 적용합니다.", "Trace an improvement to completion and verify protected evidence remains retrievable.", "개선을 완료까지 추적하고 보호한 증거를 계속 조회할 수 있는지 확인합니다.", "Retention must balance investigation needs with privacy and deletion obligations.", "보존은 조사 요구와 개인정보 및 삭제 의무를 함께 고려해야 합니다."],
  "LT-1": ["Enabled detection capabilities analyze supported resource signals for suspicious activity.", "활성 감지 기능은 지원 리소스 신호에서 의심스러운 활동을 분석합니다.", "Relevant threats can produce owned, investigable alerts.", "해당 위협을 담당자가 조사할 수 있는 경고로 만들 수 있습니다.", "Threat detection is assumed active from a product subscription alone.", "제품 구독만으로 위협 감지가 활성 상태라고 가정합니다.", "Review supported detection coverage and activate approved capabilities with alert owners.", "지원 감지 범위를 검토하고 경고 담당자가 있는 승인 기능을 활성화합니다.", "Run a supported benign detection test and inspect resulting alert routing.", "지원하는 안전한 감지 시험을 실행하고 경고 전달을 확인합니다.", "Detection settings may affect cost, privacy and alert volume.", "감지 설정은 비용, 개인정보, 경고 수에 영향을 줄 수 있습니다."],
  "LT-2": ["Identity detections examine authentication and privilege activity for suspicious patterns.", "신원 감지는 인증 및 권한 활동에서 의심스러운 패턴을 검사합니다.", "Account attacks can be investigated with identity-specific context.", "신원별 맥락으로 계정 공격을 조사할 수 있습니다.", "Sign-in failures and privileged changes are collected but never analyzed.", "로그인 실패와 권한 변경을 수집하지만 분석하지 않습니다.", "Enable approved identity detections and route risky-sign-in or privilege alerts.", "승인된 신원 감지를 활성화하고 위험 로그인 또는 권한 경고를 전달합니다.", "Test a supported identity alert and trace identity, context and triage ownership.", "지원 신원 경고를 시험하고 신원, 맥락, 분류 담당자를 추적합니다.", "Conditional access and detection have different decisions and failure modes.", "조건부 접근과 감지는 서로 다른 결정과 실패 유형을 가집니다."],
  "LT-3": ["Security audit logging records relevant access and administrative activity.", "보안 감사 로그는 관련 접근 및 관리 활동을 기록합니다.", "Investigators can reconstruct events beyond current resource state.", "조사자는 현재 리소스 상태를 넘어 과거 이벤트를 재구성할 수 있습니다.", "Only application errors are retained; administrative changes are missing.", "애플리케이션 오류만 보존하고 관리 변경은 빠뜨립니다.", "Enable required resource and administrative audit categories with protected collection.", "필수 리소스 및 관리 감사 범주를 활성화하고 수집을 보호합니다.", "Perform an authorized administrative action and locate its attributed audit event.", "승인된 관리 작업을 수행하고 행위자가 표시된 감사 이벤트를 찾습니다.", "Audit payloads must avoid credentials and unnecessary sensitive data.", "감사 내용에 자격 증명과 불필요한 민감 데이터를 넣지 않습니다."],
  "LT-4": ["Network telemetry records connectivity and flow context for investigations.", "네트워크 원격 분석은 조사에 필요한 연결 및 흐름 맥락을 기록합니다.", "Responders can examine communication paths instead of relying on topology alone.", "대응자는 토폴로지에만 의존하지 않고 통신 경로를 조사할 수 있습니다.", "A network diagram exists but no supported flow records are retained.", "네트워크 그림은 있지만 지원하는 흐름 기록을 보존하지 않습니다.", "Collect supported network security and flow telemetry for the reviewed scope.", "검토한 범위의 지원 네트워크 보안 및 흐름 원격 분석을 수집합니다.", "Generate an authorized connection and trace its path in retained network records.", "승인된 연결을 만들고 보존 네트워크 기록에서 경로를 추적합니다.", "Packet-level capture needs separate scope, privacy review and storage planning.", "패킷 수준 수집에는 별도 범위, 개인정보 검토, 저장 계획이 필요합니다."],
  "LT-5": ["Central collection joins security events while retaining source and access boundaries.", "중앙 수집은 출처와 접근 경계를 유지하면서 보안 이벤트를 묶습니다.", "Cross-service investigations can use a coherent searchable timeline.", "서비스 간 조사에서 일관되게 검색 가능한 시간 기록을 사용할 수 있습니다.", "Each team stores logs in an isolated console with unrelated identifiers.", "각 팀이 서로 다른 식별자로 별도 화면에 로그를 저장합니다.", "Route approved security logs to centralized analysis with scoped access and provenance.", "승인 보안 로그를 제한된 접근과 출처 기록을 갖춘 중앙 분석으로 전달합니다.", "Correlate a test event across sources and verify ingestion completeness and permissions.", "테스트 이벤트를 여러 원천에서 연결하고 수집 완전성과 권한을 확인합니다.", "A central store concentrates sensitive information and needs strong isolation.", "중앙 저장소는 민감한 정보를 집중시키므로 강한 격리가 필요합니다."],
  "LT-6": ["Retention policies keep investigation records available for the required window.", "보존 정책은 필요한 조사 구간의 기록을 사용할 수 있게 유지합니다.", "Historical events remain searchable when delayed incidents are discovered.", "늦게 인시던트를 발견해도 과거 이벤트를 검색할 수 있습니다.", "Default retention deletes audit records before the agreed investigation window ends.", "기본 보존이 합의한 조사 기간 전에 감사 기록을 삭제합니다.", "Set reviewed retention and archival rules for each security-log class.", "보안 로그 등급별로 검토된 보존 및 보관 규칙을 설정합니다.", "Query a record near the retention boundary and inspect expiry and deletion behavior.", "보존 경계 근처의 기록을 조회하고 만료 및 삭제 동작을 확인합니다.", "Immutability and legal holds can delay deletion and increase cost.", "불변성과 법적 보존은 삭제를 늦추고 비용을 늘릴 수 있습니다."],
  "LT-7": ["Consistent trusted time makes security-event ordering comparable across systems.", "일관된 신뢰 시간은 시스템 간 보안 이벤트 순서를 비교할 수 있게 합니다.", "Investigation timelines are less likely to confuse clock drift with event order.", "조사 시간 기록에서 시계 오차와 이벤트 순서를 혼동할 가능성을 줄일 수 있습니다.", "Hosts use unrelated time sources with unmeasured clock offsets.", "호스트가 서로 다른 시간 원천을 사용하고 시계 오차를 측정하지 않습니다.", "Use approved time sources and monitor synchronization health and drift.", "승인된 시간 원천을 사용하고 동기화 상태 및 오차를 모니터링합니다.", "Compare representative host offsets and verify loss-of-sync alerting.", "대표 호스트의 오차를 비교하고 동기화 손실 경고를 확인합니다.", "Record event time and collection time separately where available.", "가능한 경우 이벤트 시간과 수집 시간을 별도로 기록합니다."],
  "NS-1": ["Segmentation limits reachability between components with different trust requirements.", "네트워크 분할은 신뢰 요구가 다른 구성 요소 사이의 연결을 제한합니다.", "Compromise has fewer unrestricted lateral paths.", "침해 후 제한 없이 내부로 이동할 수 있는 경로를 줄일 수 있습니다.", "Unrelated workloads share unrestricted network access.", "관련 없는 워크로드가 제한 없는 네트워크 접근을 공유합니다.", "Define trust segments and explicitly allow only required cross-segment flows.", "신뢰 구역을 정하고 필요한 구역 간 흐름만 명시적으로 허용합니다.", "Test permitted and prohibited paths from each relevant segment.", "각 해당 구역에서 허용 및 금지 경로를 시험합니다.", "Shared management and recovery paths need explicit allowance.", "공용 관리 및 복구 경로는 명시적으로 허용해야 합니다."],
  "NS-2": ["Service-level network restrictions reduce unnecessary public reachability.", "서비스 수준의 네트워크 제한은 불필요한 공개 연결을 줄입니다.", "Managed-service access can follow workload trust boundaries.", "관리형 서비스 접근을 워크로드 신뢰 경계에 맞출 수 있습니다.", "A managed data service accepts connections from every public network.", "관리형 데이터 서비스가 모든 공용 네트워크의 연결을 받습니다.", "Review public access and supported private or restricted service endpoints.", "공개 접근과 지원하는 비공개 또는 제한된 서비스 엔드포인트를 검토합니다.", "Test allowed clients and rejected clients outside the approved network scope.", "허용 클라이언트와 승인 네트워크 범위 밖의 거부 클라이언트를 시험합니다.", "Endpoint changes can break DNS resolution and existing integrations.", "엔드포인트 변경으로 DNS 확인과 기존 연동이 중단될 수 있습니다."],
  "NS-3": ["Edge filtering inspects traffic crossing the enterprise trust boundary.", "경계 필터링은 조직의 신뢰 경계를 통과하는 트래픽을 검사합니다.", "Inbound and outbound exposure can follow explicit reviewed rules.", "인바운드와 아웃바운드 노출에 명시적으로 검토한 규칙을 적용할 수 있습니다.", "Internet-bound traffic bypasses a defined inspection point.", "인터넷 트래픽이 정해진 검사 지점을 우회합니다.", "Design reviewed ingress and egress filtering and ensure routing uses it.", "검토된 인바운드 및 아웃바운드 필터링을 설계하고 라우팅이 이를 사용하게 합니다.", "Trace representative traffic through the edge and test a denied destination.", "대표 트래픽의 경계 통과를 추적하고 금지 목적지를 시험합니다.", "Asymmetric routing and capacity limits can disrupt legitimate traffic.", "비대칭 라우팅과 용량 제한은 정상 트래픽을 방해할 수 있습니다."],
  "NS-4": ["Network intrusion detection analyzes traffic patterns for recognized attack behavior.", "네트워크 침입 감지는 트래픽 패턴에서 알려진 공격 동작을 분석합니다.", "Suspicious network activity can produce investigated or blocked events.", "의심스러운 네트워크 활동을 조사하거나 차단할 이벤트로 만들 수 있습니다.", "Network security relies only on port rules with no intrusion inspection.", "침입 검사 없이 포트 규칙에만 네트워크 보안을 의존합니다.", "Enable approved intrusion detection or prevention at suitable inspection points.", "적합한 검사 지점에서 승인된 침입 탐지 또는 방지를 활성화합니다.", "Use a supported harmless test to verify detection and reviewed blocking behavior.", "지원하는 무해한 시험으로 감지와 검토된 차단 동작을 확인합니다.", "Prevention rules can create false-positive outages and need tuning.", "방지 규칙은 오탐으로 중단을 일으킬 수 있으므로 조정이 필요합니다."],
  "NS-5": ["Denial-of-service protection addresses volumetric attack exposure at supported endpoints.", "서비스 거부 보호는 지원 엔드포인트의 대량 공격 노출에 대응합니다.", "Availability planning can include attack traffic rather than normal load alone.", "가용성 계획에 정상 부하뿐 아니라 공격 트래픽도 포함할 수 있습니다.", "Public endpoints have no reviewed denial-of-service protection or response plan.", "공개 엔드포인트에 검토된 서비스 거부 보호나 대응 계획이 없습니다.", "Assess public endpoint exposure and enable suitable supported protection with response ownership.", "공개 엔드포인트 노출을 평가하고 담당자가 있는 적합한 지원 보호를 활성화합니다.", "Verify covered endpoints, alert routes and an authorized provider-supported exercise.", "보호 엔드포인트, 경고 경로, 승인된 공급자 지원 연습을 확인합니다.", "Never generate an uncontrolled denial-of-service attack as a validation shortcut.", "검증을 간단히 하려고 통제되지 않은 서비스 거부 공격을 만들지 않습니다."],
  "NS-6": ["Application-layer filtering evaluates HTTP requests against reviewed protection rules.", "애플리케이션 계층 필터링은 검토된 보호 규칙으로 HTTP 요청을 평가합니다.", "Common web attack patterns can be detected or blocked before application processing.", "애플리케이션 처리 전에 흔한 웹 공격 패턴을 감지하거나 차단할 수 있습니다.", "A public web origin is directly reachable without reviewed request filtering.", "검토된 요청 필터 없이 공개 웹 원본에 직접 접근할 수 있습니다.", "Place supported WAF protection on intended web paths and restrict origin bypass.", "의도한 웹 경로에 지원 WAF 보호를 배치하고 원본 우회를 제한합니다.", "Test a benign detection case, legitimate traffic and direct-origin restrictions.", "안전한 감지 사례, 정상 트래픽, 원본 직접 접근 제한을 시험합니다.", "Overbroad rules can block users; detection-only mode does not imply blocking.", "과도한 규칙은 사용자를 차단할 수 있으며 감지 전용 모드는 차단을 뜻하지 않습니다."],
  "NS-7": ["Reusable reviewed rule patterns reduce manual inconsistency and rule sprawl.", "재사용하는 검토 규칙은 수동 불일치와 규칙 난립을 줄입니다.", "Operators can understand effective connectivity more reliably.", "운영자가 실제 연결 상태를 더 확실하게 이해할 수 있습니다.", "Many overlapping rules obscure which path permits access.", "겹치는 규칙이 많아 어떤 경로로 접근을 허용하는지 알기 어렵습니다.", "Consolidate equivalent rules using supported logical groups and versioned patterns.", "지원하는 논리 그룹과 버전 관리 패턴으로 동등한 규칙을 정리합니다.", "Compare effective permitted flows before and after the simplification.", "단순화 전후의 실제 허용 흐름을 비교합니다.", "Rule precedence and inheritance can change apparent equivalence.", "규칙 우선순위와 상속은 겉보기의 동등성을 바꿀 수 있습니다."],
  "NS-8": ["Protocol review removes obsolete or plaintext paths where supported alternatives exist.", "프로토콜 검토는 지원 대안이 있는 구식 또는 평문 경로를 제거합니다.", "Avoidable weak transport and service exposure can be reduced.", "피할 수 있는 약한 전송과 서비스 노출을 줄일 수 있습니다.", "Unused legacy listeners remain open beside the supported secure endpoint.", "지원 보안 엔드포인트 옆에 쓰지 않는 기존 수신 포트가 열려 있습니다.", "Inventory listeners and disable reviewed insecure or unnecessary services.", "수신 서비스를 목록화하고 검토한 안전하지 않거나 불필요한 서비스를 비활성화합니다.", "Scan the authorized scope and verify removed listeners and working replacements.", "승인 범위를 검사하고 제거한 수신 경로 및 대체 기능의 동작을 확인합니다.", "A protocol can remain exposed through alternate ports or proxy paths.", "다른 포트나 프록시 경로를 통해 프로토콜이 계속 노출될 수 있습니다."],
  "NS-9": ["Private connectivity defines controlled paths between connected environments.", "비공개 연결은 연결 환경 사이의 통제된 경로를 정합니다.", "Required cross-environment traffic can avoid unnecessary public exposure.", "환경 간 필수 트래픽의 불필요한 공개 노출을 피할 수 있습니다.", "Cross-environment services use publicly reachable routes by default.", "환경 간 서비스가 기본적으로 공개 접근 가능한 경로를 사용합니다.", "Review approved private connectivity, routes, authentication and failover.", "승인된 비공개 연결, 경로, 인증, 장애 조치를 검토합니다.", "Test name resolution, intended routes and failure behavior between approved environments.", "승인 환경 사이의 이름 확인, 의도한 경로, 장애 동작을 시험합니다.", "Shared routes can unintentionally enable transit between trust domains.", "공용 경로는 의도하지 않게 신뢰 영역 간 중계를 허용할 수 있습니다."],
  "NS-10": ["Controlled resolution and protected DNS administration preserve trusted name mapping.", "통제된 이름 확인과 보호된 DNS 관리는 신뢰할 수 있는 이름 매핑을 유지합니다.", "Name resolution is less likely to become an unmonitored redirection path.", "이름 확인이 모니터링되지 않는 우회 경로가 될 가능성을 줄일 수 있습니다.", "Workloads use arbitrary resolvers and DNS changes are not audited.", "워크로드가 임의 확인자를 사용하고 DNS 변경을 감사하지 않습니다.", "Define approved resolvers and protect zone changes, resolution paths and DNS logging.", "승인 확인자를 정하고 영역 변경, 이름 확인 경로, DNS 로그를 보호합니다.", "Test intended name resolution and verify unauthorized DNS changes are blocked or alerted.", "의도한 이름 확인을 시험하고 승인하지 않은 DNS 변경의 차단 또는 경고를 확인합니다.", "DNS misconfiguration can cause immediate service-wide outage.", "DNS 설정 오류는 서비스 전체 중단을 즉시 일으킬 수 있습니다."],
  "PA-1": ["Dedicated administrative identities separate privileged duties from everyday activity.", "전용 관리 신원은 권한 업무와 일상 활동을 구분합니다.", "Routine account compromise has fewer direct administrative consequences.", "일상 계정 침해가 직접 관리 권한 침해로 이어질 가능성을 줄일 수 있습니다.", "The same account handles email and broad production administration.", "같은 계정으로 이메일과 광범위한 운영 관리를 수행합니다.", "Limit administrative membership and separate approved privileged identities.", "관리자 구성원을 제한하고 승인한 권한 신원을 분리합니다.", "Review privileged memberships and verify routine identities lack administrative access.", "권한 구성원을 검토하고 일상 신원에 관리 접근이 없는지 확인합니다.", "Administrative recovery paths must remain attributable and protected.", "관리 복구 경로도 행위자를 식별할 수 있고 보호되어야 합니다."],
  "PA-2": ["Time-bounded activation reduces the duration of available privilege.", "기한이 있는 활성화는 권한을 사용할 수 있는 시간을 줄입니다.", "Unused administrative access is less likely to remain continuously exploitable.", "쓰지 않는 관리 접근이 계속 악용 가능한 상태로 남을 가능성을 줄일 수 있습니다.", "Administrators retain permanent active access between rare tasks.", "관리자가 드문 작업 사이에도 상시 활성 접근을 유지합니다.", "Use reviewed eligible or time-bound access with required activation checks.", "필수 활성화 검사를 갖춘 검토된 자격 기반 또는 기한부 접근을 사용합니다.", "Activate a test role and verify expiry removes active access.", "테스트 역할을 활성화하고 만료 후 활성 접근이 사라지는지 확인합니다.", "Eligibility itself is sensitive and requires ownership and periodic review.", "권한 자격 자체도 민감하므로 담당자와 정기 검토가 필요합니다."],
  "PA-3": ["Joiner, mover and leaver workflows keep access aligned with current duties.", "입사, 이동, 퇴사 절차는 접근을 현재 업무와 맞춥니다.", "Obsolete accounts and accumulated entitlements can be removed.", "오래된 계정과 누적된 권한을 제거할 수 있습니다.", "A transferred employee retains access from every previous role.", "부서를 옮긴 직원이 이전 모든 역할의 접근을 유지합니다.", "Tie account creation, role changes and removal to approved lifecycle events.", "계정 생성, 역할 변경, 제거를 승인된 수명 주기 이벤트와 연결합니다.", "Sample a departure and role transfer and verify timely access reconciliation.", "퇴사와 역할 이동을 표본 확인하고 적시에 접근을 조정했는지 검증합니다.", "Automation must handle failed downstream revocations explicitly.", "자동화는 하위 시스템의 철회 실패를 명시적으로 처리해야 합니다."],
  "PA-4": ["Periodic attestation compares existing access with current business need.", "정기 확인은 기존 접근과 현재 업무 필요를 비교합니다.", "Excess entitlements can be found after organizational or workload changes.", "조직이나 워크로드 변경 뒤의 과도한 권한을 찾을 수 있습니다.", "An access review is approved in bulk without checking role purpose.", "역할 목적을 확인하지 않고 접근 검토를 일괄 승인합니다.", "Assign reviewers and reconcile users, roles and justified exceptions.", "검토자를 배정하고 사용자, 역할, 타당한 예외를 대조합니다.", "Trace a revoked entitlement to its actual removal and verify a retained one has rationale.", "철회한 권한의 실제 제거를 추적하고 유지 권한의 이유를 확인합니다.", "Reviewers need enough context and independence to make meaningful decisions.", "검토자에게 의미 있는 결정을 위한 충분한 맥락과 독립성이 필요합니다."],
  "PA-5": ["Protected emergency access provides recovery when normal administration is unavailable.", "보호된 비상 접근은 일반 관리가 불가능할 때 복구 경로를 제공합니다.", "Identity outages need not remove every recovery option.", "신원 장애가 모든 복구 방안을 없애지 않게 할 수 있습니다.", "Emergency credentials are unknown, untested or used for routine work.", "비상 자격 증명이 알려지지 않았거나 시험하지 않았거나 일상 작업에 사용됩니다.", "Define protected emergency access, ownership, monitoring and periodic authorized drills.", "보호된 비상 접근, 담당자, 모니터링, 정기 승인 훈련을 정합니다.", "Run an authorized recovery drill and verify alerting and post-use review.", "승인된 복구 훈련을 실행하고 경고 및 사용 후 검토를 확인합니다.", "Do not expose emergency credentials in reports or automated tests.", "보고서나 자동 테스트에 비상 자격 증명을 노출하지 않습니다."],
  "PA-6": ["A hardened administrative channel isolates privileged sessions from everyday exposure.", "강화된 관리 경로는 권한 세션을 일상적인 노출에서 격리합니다.", "Compromised browsing or email environments have fewer routes to administrative sessions.", "침해된 웹 사용이나 이메일 환경에서 관리 세션으로 이어지는 경로를 줄일 수 있습니다.", "Production administration uses the same unmanaged device as personal browsing.", "개인 웹 사용과 같은 비관리 기기로 운영 환경을 관리합니다.", "Use approved hardened workstations or administration channels with scoped access.", "제한된 접근을 갖춘 승인된 강화 워크스테이션이나 관리 경로를 사용합니다.", "Test administrative access through the approved channel and rejection of an unapproved path.", "승인 경로의 관리 접근과 미승인 경로의 거부를 시험합니다.", "Recovery access must be designed if the dedicated channel is unavailable.", "전용 경로가 불가능할 때를 위한 복구 접근을 설계해야 합니다."],
  "PA-7": ["Task-scoped roles limit administration to the permissions required for the job.", "작업 범위 역할은 관리를 업무에 필요한 권한으로 제한합니다.", "An operator error or compromise has a smaller authorized reach.", "운영자 오류나 침해가 영향을 줄 수 있는 권한 범위를 줄일 수 있습니다.", "A routine support task requires a subscription-wide owner role.", "일상 지원 작업에 구독 전체 소유자 역할을 요구합니다.", "Define a reviewed role and target scope matching the actual administrative task.", "실제 관리 작업에 맞는 검토된 역할과 대상 범위를 정합니다.", "Perform the intended task and verify unrelated privileged operations are denied.", "의도한 작업을 수행하고 무관한 권한 작업이 거부되는지 확인합니다.", "Custom roles can drift and need versioned review.", "사용자 지정 역할은 달라질 수 있으므로 버전 관리 검토가 필요합니다."],
  "PA-8": ["A support-access process defines approval, scope and audit for provider-assisted access.", "지원 접근 절차는 공급자 지원 접근의 승인, 범위, 감사를 정합니다.", "External support can be reviewed without granting indefinite broad access.", "무기한 광범위한 접근을 주지 않고 외부 지원을 검토할 수 있습니다.", "A support request is assumed to authorize unrestricted provider access.", "지원 요청만으로 공급자의 무제한 접근을 허가했다고 가정합니다.", "Document supported provider-access approval, duration, data handling and audit review.", "지원하는 공급자 접근의 승인, 기간, 데이터 처리, 감사 검토를 문서화합니다.", "Review a support-access case for attributed approval, bounded scope and closure.", "지원 접근 사례의 책임이 기록된 승인, 제한 범위, 종료를 검토합니다.", "Troubleshooting artifacts must not expose secrets or unnecessary customer data.", "문제 해결 자료에 비밀이나 불필요한 고객 데이터를 노출하지 않습니다."],
  "PV-1": ["A reviewed configuration baseline defines expected security settings.", "검토된 구성 기준선은 예상 보안 설정을 정합니다.", "Configuration decisions can be tested against a consistent reference.", "구성 결정을 일관된 기준과 비교해 시험할 수 있습니다.", "Resources rely on undocumented defaults that differ across deployments.", "리소스가 배포마다 다른 문서화되지 않은 기본값에 의존합니다.", "Define versioned secure settings and reviewed applicability or exceptions.", "버전 관리한 안전 설정과 검토된 적용 범위 또는 예외를 정합니다.", "Compare representative resource settings with the approved baseline revision.", "대표 리소스 설정을 승인한 기준선 리비전과 비교합니다.", "Baseline adoption needs compatibility and recovery review.", "기준선 채택에는 호환성과 복구 검토가 필요합니다."],
  "PV-2": ["Drift assessment compares effective settings with the approved configuration baseline.", "드리프트 평가는 실제 설정을 승인한 구성 기준선과 비교합니다.", "Nonconforming settings can reach an owned remediation decision.", "기준에 맞지 않는 설정을 담당자가 수정 여부를 결정하도록 전달할 수 있습니다.", "A policy is assigned but its evaluation coverage and exceptions are unknown.", "정책은 배정했지만 평가 범위와 예외를 알 수 없습니다.", "Audit supported settings and stage approved enforcement with exception tracking.", "지원 설정을 감사하고 예외를 추적하며 승인된 강제 적용을 단계적으로 진행합니다.", "Verify evaluation freshness and test a known compliant and noncompliant setting.", "평가 최신 여부를 확인하고 적합 및 부적합 설정을 시험합니다.", "Enforcement can block deployment and must not be enabled without authority.", "강제 적용은 배포를 막을 수 있으므로 권한 없이 활성화하지 않습니다."],
  "PV-3": ["Compute baselines define operating-system and runtime hardening expectations.", "컴퓨팅 기준선은 운영체제와 실행 환경의 강화 기준을 정합니다.", "Images and hosts can share reviewable security defaults.", "이미지와 호스트가 검토 가능한 보안 기본값을 공유할 수 있습니다.", "VM images retain unreviewed operating-system defaults.", "VM 이미지에 검토하지 않은 운영체제 기본값이 남아 있습니다.", "Define compute hardening for supported images, services and management access.", "지원 이미지, 서비스, 관리 접근의 컴퓨팅 강화 기준을 정합니다.", "Inspect a built image and a running host against the same approved baseline.", "빌드 이미지와 실행 호스트를 같은 승인 기준선에 따라 확인합니다.", "Guest hardening may disable required agents or application features.", "게스트 강화는 필수 에이전트나 애플리케이션 기능을 끌 수 있습니다."],
  "PV-4": ["Guest configuration assessment exposes drift from the approved compute baseline.", "게스트 구성 평가는 승인한 컴퓨팅 기준선의 이탈을 드러냅니다.", "Host hardening can be checked after provisioning rather than assumed permanent.", "호스트 강화를 생성 시점의 영구 상태로 가정하지 않고 이후에도 확인할 수 있습니다.", "A secure image drifts after manual host changes with no reassessment.", "안전한 이미지가 수동 호스트 변경 후 달라져도 다시 평가하지 않습니다.", "Audit supported guest settings and review authorized correction or exemptions.", "지원 게스트 설정을 감사하고 승인된 수정이나 예외를 검토합니다.", "Introduce a safe test drift and confirm detection and approved correction.", "안전한 테스트 이탈을 만들고 감지 및 승인된 수정을 확인합니다.", "Automatic correction can conflict with application configuration management.", "자동 수정은 애플리케이션 구성 관리와 충돌할 수 있습니다."],
  "PV-5": ["Current vulnerability assessment identifies exposed software and configuration weaknesses.", "최신 취약점 평가는 노출된 소프트웨어 및 구성 취약점을 식별합니다.", "Remediation can be prioritized using observed exposure and affected versions.", "관측한 노출과 영향 버전을 바탕으로 수정 우선순위를 정할 수 있습니다.", "Hosts are inventoried but vulnerability results are stale or absent.", "호스트 목록은 있지만 취약점 결과가 오래되었거나 없습니다.", "Run approved supported assessments and assign triage for in-scope findings.", "승인된 지원 평가를 실행하고 범위 내 발견 사항의 분류 담당자를 정합니다.", "Check scan coverage, freshness and a finding's affected version or configuration.", "검사 범위, 최신 여부, 발견 사항의 영향 버전이나 구성을 확인합니다.", "Authenticated scans may need privileged access and careful credential handling.", "인증 검사는 권한 접근과 신중한 자격 증명 처리가 필요할 수 있습니다."],
  "PV-6": ["Risk-based remediation connects findings to tested patches or bounded mitigations.", "위험 기반 수정은 발견 사항을 시험한 패치나 제한된 완화 조치와 연결합니다.", "Known exposure can be reduced without treating deployment success as verification.", "배포 성공을 검증으로 간주하지 않으면서 알려진 노출을 줄일 수 있습니다.", "Patches are deployed without checking the vulnerable version or service health afterward.", "패치를 배포한 뒤 취약 버전이나 서비스 상태를 확인하지 않습니다.", "Prioritize exposure, test the fix and use an approved staged remediation path.", "노출 우선순위를 정하고 수정을 시험한 뒤 승인된 단계적 수정 경로를 사용합니다.", "Reassess the affected version and independently verify workload health.", "영향 버전을 다시 평가하고 워크로드 상태를 독립적으로 확인합니다.", "A patch may require reboot or introduce incompatibility; retain stop conditions.", "패치에는 재시작이 필요하거나 호환 문제가 생길 수 있으므로 중지 조건을 유지합니다."],
  "PV-7": ["Authorized adversarial exercises examine detection and response against realistic attack paths.", "승인된 공격자 관점 훈련은 현실적인 공격 경로에 대한 감지와 대응을 검사합니다.", "Teams can find gaps that isolated configuration checks miss.", "팀은 개별 구성 검사가 놓치는 공백을 찾을 수 있습니다.", "Security assurance relies only on scans with no adversarial exercise.", "공격자 관점 훈련 없이 검사에만 보안 확인을 의존합니다.", "Define approved rules of engagement, target scope and safety limits for an exercise.", "훈련의 승인된 수행 규칙, 대상 범위, 안전 한계를 정합니다.", "Compare exercised paths with detection, response and remediation outcomes.", "시험한 경로를 감지, 대응, 수정 결과와 비교합니다.", "Never conduct intrusive testing without explicit authorization and stop conditions.", "명시적 승인과 중지 조건 없이 침투성 테스트를 수행하지 않습니다."],
  "AM-1": ["An owned inventory connects discovered assets with exposure and risk context.", "담당자가 있는 목록은 발견한 자산과 노출 및 위험 정보를 연결합니다.", "Unknown or abandoned assets become visible for review.", "알려지지 않았거나 방치된 자산을 검토할 수 있습니다.", "A resource export lacks ownership and exposure classification.", "리소스 내보내기 목록에 담당자와 노출 분류가 없습니다.", "Reconcile discovered assets with owners, purpose and risk classification.", "발견한 자산을 담당자, 목적, 위험 분류와 대조합니다.", "Sample assets from discovery and verify their inventory record and risk owner.", "발견 자산을 표본 추출하고 목록 기록과 위험 담당자를 확인합니다.", "Inventory metadata may reveal sensitive topology and needs scoped access.", "자산 목록 정보는 민감한 토폴로지를 드러낼 수 있으므로 접근을 제한해야 합니다."],
  "AM-2": ["An approved-service catalog constrains which cloud capabilities enter the workload.", "승인 서비스 목록은 워크로드가 도입할 수 있는 클라우드 기능을 제한합니다.", "New services receive security review before becoming dependencies.", "새 서비스가 의존성이 되기 전에 보안 검토를 받을 수 있습니다.", "Teams introduce services without checking an approved list.", "팀이 승인 목록을 확인하지 않고 서비스를 도입합니다.", "Maintain approved services and review actual deployments against that list.", "승인 서비스를 관리하고 실제 배포를 목록과 비교합니다.", "Identify a deployed service outside the list and trace its exception or remediation.", "목록 밖의 배포 서비스를 찾아 예외나 수정 조치를 추적합니다.", "Blanket blocking can interrupt existing dependencies and needs staged review.", "일괄 차단은 기존 의존성을 중단시킬 수 있으므로 단계적 검토가 필요합니다."],
  "AM-3": ["Lifecycle records preserve ownership through provisioning, transfer and retirement.", "수명 주기 기록은 생성, 이전, 폐기 과정의 책임을 유지합니다.", "Retired assets are less likely to retain data or usable access.", "폐기한 자산에 데이터나 사용 가능한 접근 권한이 남을 가능성을 줄일 수 있습니다.", "Retired resources retain credentials and unmanaged data copies.", "폐기 리소스에 자격 증명과 관리하지 않는 데이터 사본이 남아 있습니다.", "Define secure provisioning and decommissioning with data and access disposition.", "데이터 및 접근 처리 결과를 포함해 안전한 생성 및 폐기 절차를 정합니다.", "Inspect a retired asset's deletion, retained-data decision and access revocation.", "폐기 자산의 삭제, 데이터 보존 결정, 접근 철회를 확인합니다.", "Deleting compute does not necessarily remove disks, snapshots or identities.", "컴퓨팅을 삭제해도 디스크, 스냅샷, 신원이 남을 수 있습니다."],
  "AM-4": ["Scoped management permissions separate asset administration from ordinary use.", "제한된 관리 권한은 자산 관리와 일반 사용을 구분합니다.", "Unauthorized inventory changes and resource administration can be reduced.", "승인하지 않은 자산 목록 변경과 리소스 관리를 줄일 수 있습니다.", "All contributors can change asset records and management settings.", "모든 기여자가 자산 기록과 관리 설정을 바꿀 수 있습니다.", "Assign asset-management roles according to administrative duties.", "관리 업무에 따라 자산 관리 역할을 배정합니다.", "Test read-only inventory access and denied administrative changes separately.", "자산 목록 읽기 접근과 관리 변경 거부를 각각 시험합니다.", "Inherited roles can silently widen management permissions.", "상속 역할은 관리 권한을 눈에 띄지 않게 넓힐 수 있습니다."],
  "AM-5": ["Application approval limits executable software on virtual machines.", "애플리케이션 승인은 가상 머신에서 실행할 소프트웨어를 제한합니다.", "Unexpected software has fewer opportunities to become an unmanaged entry point.", "예상 밖의 소프트웨어가 관리되지 않는 진입점이 될 가능성을 줄일 수 있습니다.", "A VM runs unreviewed utilities installed outside the image process.", "VM이 이미지 관리 절차 밖에서 설치한 미검토 도구를 실행합니다.", "Define approved applications and review executable inventory or application controls.", "승인 애플리케이션을 정하고 실행 파일 목록이나 애플리케이션 통제를 검토합니다.", "Compare a VM's installed and running software with approved applications.", "VM의 설치 및 실행 소프트웨어를 승인 애플리케이션과 비교합니다.", "Enforcement without testing can block recovery tools or workload startup.", "시험 없는 강제 적용은 복구 도구나 워크로드 시작을 차단할 수 있습니다."],
  "BR-1": ["Scheduled backups create recovery points without relying on manual memory.", "예정된 백업은 수동 작업을 기억하는 데 의존하지 않고 복구 시점을 만듭니다.", "Data recovery can use a documented sequence of recent copies.", "데이터 복구에 최근 사본의 문서화된 기록을 사용할 수 있습니다.", "A database is backed up only when an operator remembers.", "운영자가 기억할 때만 데이터베이스를 백업합니다.", "Assign backup policies with schedules and retention tied to recovery objectives.", "복구 목표에 맞춰 일정과 보존 기간이 있는 백업 정책을 배정합니다.", "Inspect recent completed jobs and recovery-point age for an in-scope asset.", "범위 내 자산의 최근 완료 작업과 복구 시점의 나이를 확인합니다.", "A successful backup job does not prove a usable restore.", "백업 작업 성공만으로 실제 복원 가능성을 입증할 수 없습니다."],
  "BR-2": ["Separate access and protection controls reduce the chance that production compromise destroys backups.", "별도 접근 및 보호 통제는 운영 환경 침해로 백업까지 파괴될 가능성을 줄입니다.", "Recovery copies can remain available when primary resources are compromised.", "기본 리소스가 침해되어도 복구 사본을 사용할 수 있게 할 수 있습니다.", "The same broad administrator can alter production and erase every recovery copy.", "같은 광범위한 관리자가 운영 환경을 변경하고 모든 복구 사본을 지울 수 있습니다.", "Review backup access, encryption and deletion protection separately from primary storage.", "기본 저장소와 별도로 백업 접근, 암호화, 삭제 보호를 검토합니다.", "Test unauthorized backup deletion denial and verify recovery-copy accessibility.", "승인하지 않은 백업 삭제의 거부와 복구 사본의 접근 가능성을 확인합니다.", "Retention locks may be irreversible and require explicit approval.", "보존 잠금은 되돌릴 수 없을 수 있으므로 명시적 승인이 필요합니다."],
  "BR-3": ["Backup monitoring turns failed jobs and stale recovery points into owned alerts.", "백업 모니터링은 실패한 작업과 오래된 복구 시점을 담당자 경고로 바꿉니다.", "Protection gaps can be investigated before a restore is needed.", "복원이 필요해지기 전에 보호 공백을 조사할 수 있습니다.", "Backup failures accumulate without alert routing.", "백업 실패가 경고 전달 없이 쌓입니다.", "Alert on job failure, missed schedules and recovery-point freshness.", "작업 실패, 일정 누락, 복구 시점의 최신 여부에 경고를 설정합니다.", "Simulate a missed backup and confirm alert delivery and owner follow-up.", "백업 누락을 모의 실행하고 경고 전달 및 담당자 후속 조치를 확인합니다.", "A green last-job status can hide unprotected assets or partial coverage.", "최근 작업의 정상 상태는 미보호 자산이나 부분 적용을 가릴 수 있습니다."],
  "BR-4": ["Restore exercises verify that retained copies can reconstruct needed data.", "복원 연습은 보존 사본으로 필요한 데이터를 재구성할 수 있는지 검증합니다.", "Recovery assumptions can be checked before an actual data-loss event.", "실제 데이터 손실 전에 복구 가정을 확인할 수 있습니다.", "Backups are retained for months without any restore test.", "복원 시험 없이 수개월 동안 백업만 보관합니다.", "Schedule isolated restore tests with integrity and recovery-time acceptance.", "무결성 및 복구 시간 수용 기준을 갖춘 격리 복원 시험을 계획합니다.", "Restore a representative copy and compare data integrity and elapsed time with targets.", "대표 사본을 복원하고 데이터 무결성 및 걸린 시간을 목표와 비교합니다.", "Restore dependencies include keys, credentials and compatible infrastructure.", "복원에는 키, 자격 증명, 호환 인프라도 필요합니다."],
  "DP-1": ["Discovery and labels connect data sensitivity to handling rules.", "탐색과 표시는 데이터 민감도를 처리 규칙과 연결합니다.", "Protection reviews can focus on where sensitive information actually resides.", "민감한 정보가 실제로 있는 위치에 보호 검토를 집중할 수 있습니다.", "Sensitive exports exist outside the documented data inventory.", "문서화한 데이터 목록 밖에 민감한 내보내기 사본이 있습니다.", "Discover relevant stores and apply owner-reviewed sensitivity classifications.", "해당 저장소를 탐색하고 담당자가 검토한 민감도 분류를 적용합니다.", "Sample discovered sensitive records and verify labels and downstream handling.", "발견한 민감 기록을 표본 확인하고 표시 및 후속 처리를 검증합니다.", "Scanning results themselves may contain sensitive samples.", "검사 결과 자체에도 민감한 표본이 들어갈 수 있습니다."],
  "DP-2": ["Data-access signals reveal suspicious reads, exports and changes involving sensitive information.", "데이터 접근 신호는 민감한 정보의 의심스러운 읽기, 내보내기, 변경을 드러냅니다.", "Responders can investigate potential misuse with data-specific context.", "대응자는 데이터별 맥락을 바탕으로 잠재적인 악용을 조사할 수 있습니다.", "Sensitive stores log availability but not unusual access.", "민감한 저장소가 가용성만 기록하고 비정상 접근을 기록하지 않습니다.", "Enable relevant data-access monitoring and route reviewed anomaly detections.", "해당 데이터 접근 모니터링을 활성화하고 검토된 이상 감지를 전달합니다.", "Exercise an authorized detection test and trace it to triage.", "승인된 감지 시험을 수행하고 분류 처리까지 추적합니다.", "Monitoring must preserve privacy and limit access to sensitive audit details.", "모니터링은 개인정보를 보호하고 민감한 감사 정보의 접근을 제한해야 합니다."],
  "DP-3": ["Authenticated transport encryption protects data moving between endpoints.", "인증된 전송 암호화는 엔드포인트 사이를 이동하는 데이터를 보호합니다.", "Interception and endpoint impersonation opportunities can be reduced.", "도청과 엔드포인트 사칭 기회를 줄일 수 있습니다.", "A backend hop sends sensitive records over plaintext.", "백엔드 한 구간이 민감한 기록을 평문으로 보냅니다.", "Require approved encrypted protocols and validate endpoint certificates on sensitive paths.", "민감한 경로에서 승인된 암호화 프로토콜을 요구하고 엔드포인트 인증서를 검증합니다.", "Test negotiated protocol security and rejection of an invalid certificate.", "협상한 프로토콜 보안과 잘못된 인증서 거부를 시험합니다.", "Disabling certificate validation defeats endpoint authenticity checks.", "인증서 검증을 끄면 엔드포인트 진위 확인이 무력화됩니다."],
  "DP-4": ["Storage encryption protects persisted data independently of transport encryption.", "저장 암호화는 전송 암호화와 별개로 저장된 데이터를 보호합니다.", "Exposed storage media is less useful without the required keys.", "노출된 저장 매체를 필요한 키 없이 활용하기 어렵게 할 수 있습니다.", "New data stores have no verified at-rest encryption setting.", "새 저장소의 저장 암호화 설정을 확인하지 않습니다.", "Verify encryption defaults and effective settings for each supported store.", "지원하는 저장소별 암호화 기본값과 실제 설정을 확인합니다.", "Read encryption state and confirm new persisted data uses the intended protection.", "암호화 상태를 조회하고 새로 저장한 데이터가 의도한 보호를 받는지 확인합니다.", "Encryption at rest does not prevent misuse by an authorized reader.", "저장 암호화는 권한 있는 읽기 사용자의 악용을 막지 못합니다."],
  "DP-5": ["Customer-managed keys separate key lifecycle decisions from service-managed defaults.", "고객 관리 키는 키 수명 주기 결정을 서비스 관리 기본값과 분리합니다.", "Explicit key-control requirements can be addressed where applicable.", "해당하는 경우 명시적인 키 통제 요구에 대응할 수 있습니다.", "A required customer-key policy is assumed satisfied by default encryption.", "기본 암호화만으로 필수 고객 키 정책을 충족했다고 가정합니다.", "Confirm the key-control requirement, service support and approved customer-key design.", "키 통제 요구, 서비스 지원, 승인된 고객 키 설계를 확인합니다.", "Verify the store's key reference and an authorized rotation or recovery rehearsal.", "저장소의 키 참조와 승인된 교체 또는 복구 연습을 확인합니다.", "Losing or disabling the key can make encrypted data unavailable.", "키를 잃거나 비활성화하면 암호화 데이터를 사용할 수 없게 됩니다."],
  "DP-6": ["Key generation, rotation and recovery controls preserve confidentiality throughout the key lifecycle.", "키 생성, 교체, 복구 통제는 키 수명 주기 전반의 기밀성을 유지합니다.", "Key compromise and loss have defined response paths.", "키 침해와 손실에 정해진 대응 경로를 마련할 수 있습니다.", "Keys are created manually with no rotation owner or recovery procedure.", "교체 담당자나 복구 절차 없이 키를 수동 생성합니다.", "Define approved key creation, access, rotation, retirement and recovery procedures.", "승인된 키 생성, 접근, 교체, 폐기, 복구 절차를 정의합니다.", "Rehearse rotation and recovery without exposing key material in evidence.", "근거 자료에 키 내용을 노출하지 않고 교체와 복구를 연습합니다.", "Deleting a key before protected data expires can cause irreversible loss.", "보호 데이터의 보존 기간이 끝나기 전에 키를 삭제하면 되돌릴 수 없는 손실이 생길 수 있습니다."],
  "DP-7": ["Certificate inventory and renewal controls preserve trusted endpoint identity.", "인증서 목록과 갱신 통제는 신뢰할 수 있는 엔드포인트 신원을 유지합니다.", "Expiry and unowned certificate changes are easier to prevent.", "인증서 만료와 담당자 없는 변경을 예방하기 쉬워집니다.", "A certificate expires unexpectedly because no renewal owner exists.", "갱신 담당자가 없어 인증서가 예고 없이 만료됩니다.", "Inventory certificate use and define issuance, renewal, revocation and private-key protection.", "인증서 사용을 목록화하고 발급, 갱신, 철회, 개인 키 보호를 정합니다.", "Rehearse renewal and confirm clients trust the replacement certificate chain.", "갱신을 연습하고 클라이언트가 교체한 인증서 체인을 신뢰하는지 확인합니다.", "Renewal can fail when applications cache certificates or pin an old key.", "애플리케이션이 인증서를 캐시하거나 이전 키를 고정하면 갱신이 실패할 수 있습니다."],
  "DP-8": ["Repository access, network and audit controls protect high-value cryptographic material.", "저장소 접근, 네트워크, 감사 통제는 중요한 암호 자료를 보호합니다.", "A single weak repository boundary is less likely to expose many protected services.", "약한 저장소 경계 하나로 여러 보호 서비스가 노출될 가능성을 줄일 수 있습니다.", "Many identities can read cryptographic material without audit review.", "많은 신원이 감사 검토 없이 암호 자료를 읽을 수 있습니다.", "Limit repository data-plane access and review network exposure, audit and recovery settings.", "저장소 데이터 접근을 제한하고 네트워크 노출, 감사, 복구 설정을 검토합니다.", "Test unauthorized material access denial and inspect permitted access audit events.", "승인하지 않은 자료 접근의 거부를 시험하고 허용된 접근 감사 이벤트를 확인합니다.", "Repository access changes can interrupt every dependent application.", "저장소 접근 변경은 의존하는 모든 애플리케이션을 중단시킬 수 있습니다."],
  "DS-1": ["Threat modeling relates trust boundaries and misuse cases to design decisions.", "위협 모델링은 신뢰 경계와 악용 사례를 설계 결정에 연결합니다.", "Security work can address plausible attack paths before implementation hardens them.", "구현이 굳어지기 전에 현실적인 공격 경로에 대응할 수 있습니다.", "Architecture review records components but not attacker goals or trust boundaries.", "아키텍처 검토가 구성 요소만 기록하고 공격자 목표나 신뢰 경계를 빠뜨립니다.", "Model data flows, entry points and threats with design owners.", "설계 담당자와 데이터 흐름, 진입점, 위협을 모델링합니다.", "Trace a high-risk threat to mitigation and an acceptance or test record.", "위험이 큰 위협을 완화 조치 및 수용 또는 테스트 기록까지 추적합니다.", "Models become stale when dependencies or trust boundaries change.", "의존성이나 신뢰 경계가 바뀌면 모델이 오래된 상태가 됩니다."],
  "DS-2": ["Verified dependencies and artifact provenance constrain untrusted build inputs.", "검증한 의존성과 산출물 출처는 신뢰하지 않는 빌드 입력을 제한합니다.", "Delivered software can be traced to reviewed components.", "전달한 소프트웨어를 검토한 구성 요소까지 추적할 수 있습니다.", "Builds retrieve mutable dependencies without integrity records.", "빌드가 무결성 기록 없이 변경 가능한 의존성을 가져옵니다.", "Pin and review dependencies and retain artifact integrity and provenance records.", "의존성을 고정해 검토하고 산출물 무결성 및 출처 기록을 보존합니다.", "Resolve a release to its dependency manifest, digest and source revision.", "배포를 의존성 매니페스트, 다이제스트, 소스 리비전과 연결합니다.", "Build credentials and signing authority need separate protection.", "빌드 자격 증명과 서명 권한은 별도로 보호해야 합니다."],
  "DS-3": ["Isolated build agents and scoped pipeline identities protect the delivery environment.", "격리된 빌드 에이전트와 제한된 파이프라인 신원은 전달 환경을 보호합니다.", "Untrusted build work has fewer paths to privileged release credentials.", "신뢰하지 않는 빌드 작업이 권한 있는 배포 자격 증명에 접근할 경로를 줄일 수 있습니다.", "Untrusted pull requests run on a privileged persistent agent.", "신뢰하지 않는 풀 리퀘스트가 권한 있는 상시 에이전트에서 실행됩니다.", "Separate trust levels and restrict agent persistence, secrets and deployment permissions.", "신뢰 수준을 구분하고 에이전트 유지 상태, 비밀, 배포 권한을 제한합니다.", "Test an untrusted build's inability to read release secrets or deploy.", "신뢰하지 않는 빌드가 배포 비밀을 읽거나 배포할 수 없는지 시험합니다.", "Agent cleanup must preserve required evidence without retaining credentials.", "에이전트 정리는 자격 증명을 남기지 않으면서 필요한 근거를 보존해야 합니다."],
  "DS-4": ["Static analysis examines code and configuration before execution.", "정적 분석은 실행 전에 코드와 구성을 검사합니다.", "Common implementation weaknesses can be reviewed during development.", "개발 중에 흔한 구현 취약점을 검토할 수 있습니다.", "Security linting runs only on an engineer's machine.", "보안 린트 검사가 개발자 컴퓨터에서만 실행됩니다.", "Run reviewed static checks in the pipeline and route findings to code owners.", "파이프라인에서 검토된 정적 검사를 실행하고 발견 사항을 코드 담당자에게 전달합니다.", "Use a safe test fixture to confirm detection, gating and exception review.", "안전한 테스트 예제로 감지, 차단 기준, 예외 검토를 확인합니다.", "False positives need documented triage rather than blanket rule suppression.", "오탐에는 규칙 일괄 해제 대신 기록한 분류 처리가 필요합니다."],
  "DS-5": ["Dynamic tests inspect a running application's externally observable behavior.", "동적 테스트는 실행 중인 애플리케이션의 외부에서 관측 가능한 동작을 검사합니다.", "Runtime weaknesses can be found that source-only checks miss.", "소스 검사만으로 놓치는 실행 중 취약점을 찾을 수 있습니다.", "A web application is released without testing authenticated runtime behavior.", "인증된 실행 동작을 시험하지 않고 웹 애플리케이션을 배포합니다.", "Run authorized dynamic security tests in a representative isolated environment.", "대표적인 격리 환경에서 승인된 동적 보안 테스트를 실행합니다.", "Verify test scope, authenticated coverage and triage of a known safe finding.", "테스트 범위, 인증 구간 포함 여부, 알려진 안전한 발견 사항의 분류를 확인합니다.", "Never run intrusive dynamic tests against unapproved targets.", "승인하지 않은 대상에 침투성 동적 테스트를 실행하지 않습니다."],
  "DS-6": ["Lifecycle security gates preserve required decisions from design through deployment.", "수명 주기 보안 검토 단계는 설계부터 배포까지 필요한 결정을 유지합니다.", "Security requirements are less likely to disappear between stages.", "단계 사이에서 보안 요구가 사라질 가능성을 줄일 수 있습니다.", "A finding is accepted in development but not tracked into release.", "개발 중 발견 사항을 수용하지만 배포까지 추적하지 않습니다.", "Define security acceptance, exception and remediation responsibilities across delivery stages.", "전달 단계 전반의 보안 수용, 예외, 수정 책임을 정의합니다.", "Trace an unresolved issue to an approved disposition before the release decision.", "배포 결정 전에 미해결 문제를 승인한 처리 결과까지 추적합니다.", "Emergency release paths still require explicit risk ownership and audit.", "긴급 배포 경로에도 명시적인 위험 담당과 감사가 필요합니다."],
  "DS-7": ["Delivery audit events expose changes to source, pipelines and release permissions.", "전달 감사 이벤트는 소스, 파이프라인, 배포 권한의 변경을 드러냅니다.", "Suspicious delivery activity can be investigated with an attributable timeline.", "행위자를 식별할 수 있는 시간 기록으로 의심스러운 전달 활동을 조사할 수 있습니다.", "Pipeline permission changes leave no centrally reviewed audit trail.", "파이프라인 권한 변경에 중앙 검토 감사 기록이 없습니다.", "Collect source and pipeline audit events with owned alerts for sensitive changes.", "소스 및 파이프라인 감사 이벤트를 수집하고 민감한 변경의 경고 담당자를 정합니다.", "Exercise a safe pipeline-permission change and trace its audit and alert records.", "안전한 파이프라인 권한 변경을 시험하고 감사 및 경고 기록을 추적합니다.", "Logs must redact credentials and restrict access to sensitive build metadata.", "로그는 자격 증명을 가리고 민감한 빌드 정보의 접근을 제한해야 합니다."],
  "ES-1": ["Endpoint detection correlates host activity with suspicious behavior and response workflows.", "엔드포인트 감지는 호스트 활동을 의심스러운 동작 및 대응 절차와 연결합니다.", "Host-level threats can be investigated beyond basic resource health.", "기본 리소스 상태를 넘어 호스트 위협을 조사할 수 있습니다.", "Compute instances have health metrics but no endpoint detection coverage.", "컴퓨팅 인스턴스에 상태 메트릭은 있지만 엔드포인트 감지 적용이 없습니다.", "Deploy a supported endpoint detection capability and assign triage ownership.", "지원하는 엔드포인트 감지 기능을 배포하고 분류 담당자를 정합니다.", "Check agent health and route a vendor-supported benign detection test.", "에이전트 상태를 확인하고 공급자가 지원하는 안전한 감지 시험을 전달합니다.", "Endpoint response actions can interrupt legitimate workloads and need authority.", "엔드포인트 대응 조치는 정상 워크로드를 중단시킬 수 있으므로 권한이 필요합니다."],
  "ES-2": ["Malware protection examines files and execution for recognized harmful content.", "맬웨어 보호는 파일과 실행에서 알려진 악성 내용을 검사합니다.", "Common malicious payloads can be blocked or isolated earlier.", "흔한 악성 내용을 더 일찍 차단하거나 격리할 수 있습니다.", "A supported host has no active malware protection policy.", "지원하는 호스트에 활성 맬웨어 보호 정책이 없습니다.", "Enable supported malware protection with reviewed policy and alert routing.", "검토된 정책과 경고 경로를 갖춘 지원 맬웨어 보호를 활성화합니다.", "Confirm protection health and run only a vendor-approved harmless test.", "보호 상태를 확인하고 공급자가 승인한 무해한 시험만 실행합니다.", "Overbroad exclusions can defeat protection; untested scanning can affect performance.", "과도한 제외는 보호를 무력화하고 시험하지 않은 검사는 성능에 영향을 줄 수 있습니다."],
  "ES-3": ["Current engines and signatures maintain protection against newly recognized threats.", "최신 엔진과 서명은 새로 알려진 위협에 대한 보호를 유지합니다.", "Installed protection is less likely to become ineffective through stale updates.", "설치한 보호 기능이 오래된 업데이트 때문에 무력해질 가능성을 줄일 수 있습니다.", "Agents report installed status while their signatures are months old.", "에이전트가 설치됨으로 표시되지만 서명은 수개월 전 상태입니다.", "Define update policy and monitor engine and signature freshness.", "갱신 정책을 정하고 엔진 및 서명의 최신 여부를 모니터링합니다.", "Sample version age and confirm a failed-update alert reaches an owner.", "버전의 나이를 표본 확인하고 갱신 실패 경고가 담당자에게 도달하는지 확인합니다.", "Update connectivity and compatibility failures need an owned recovery path.", "갱신 연결이나 호환성 실패에는 담당자가 있는 복구 경로가 필요합니다."],
};

export interface McsbControlAuthoredGuidance {
  readonly mechanism: GuidanceText;
  readonly benefits: GuidanceText;
  readonly before: GuidanceText;
  readonly after: GuidanceText;
  readonly verify: GuidanceText;
  readonly caution: GuidanceText;
}

export function resolveMcsbControlAuthoredGuidance(controlId: string): McsbControlAuthoredGuidance | undefined {
  const tuple = MCSB_CONTROL_TUPLES[controlId];
  if (!tuple) return undefined;
  return {
    mechanism: { en: tuple[0], ko: tuple[1] },
    benefits: { en: tuple[2], ko: tuple[3] },
    before: { en: tuple[4], ko: tuple[5] },
    after: { en: tuple[6], ko: tuple[7] },
    verify: { en: tuple[8], ko: tuple[9] },
    caution: { en: tuple[10], ko: tuple[11] },
  };
}

export function resolveControlReferenceImage(
  scope: "azure-wara" | "azure-waf" | "azure-caf" | "azure-mcsb" | "mcsb-v2-preview" | "msrc-csaf" | "rule",
  id: string,
  _resourceType?: string,
): GuidanceReferenceImage | undefined {
  if (scope !== "azure-wara") return undefined;
  return PACKAGED_REFERENCE_IMAGES[id] ?? Object.values(PACKAGED_REFERENCE_IMAGES).find((item) => item.asset_id === id);
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
