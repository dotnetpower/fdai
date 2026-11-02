"""Two blind concept choosers over complete catalog shards for the question-form shadow.

Each chooser sees every planned shard and resolves its own finalist runoff without seeing
the other's choice, and a binding stands only where both choose the same values. Shards
and runoffs run in waves of at most two provider calls inside the chooser's call budget.
"""

from __future__ import annotations

import asyncio
import copy
import unicodedata
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from .semantic_reasoning_concepts import (
    ConceptSelectionReceipt,
    ConceptShard,
    accept_concept_selection,
    agree_concepts,
    apply_runoff,
    plan_concept_selection,
    runoff_requests,
    shard_answer_valid,
)
from .semantic_reasoning_form import MentionDomain

_MAX_SHARED_CONCEPT_CACHE = 512
_SHARED_CONCEPT_CACHE: OrderedDict[tuple[str, bool, str], tuple[str, ...]] = OrderedDict()
_LEADING_MODIFIERS = (
    "the ", "an ", "a ", "all ", "every ", "my ", "our ", "this ", "that ",
    "these ", "those ", "current ", "existing ",
    "모든 ", "전체 ", "현재 ", "기존 ", "우리 ", "내 ", "해당 ", "각 ",
)  # fmt: skip
_TRAILING_PARTICLES = (
    "목록들을", "목록들이", "목록들은", "목록들", "목록을", "목록이", "목록은", "목록",
    "리스트를", "리스트가", "리스트는", "리스트", "현황을", "현황이", "현황은", "현황",
    "개수를", "개수가", "개수는", "개수", "상태를", "상태가", "상태는", "상태인", "상태의", "상태",
    "들을", "들이", "들은", "들의", "들에", "들로", "들만", "들도", "들",
    "이란", "란", "이나", "나", "에서", "에게", "으로", "로",
    "이", "가", "을", "를", "은", "는", "의", "에", "도", "만", "와", "과",
)  # fmt: skip
_PRESERVE_S_SUFFIX = (
    "ss", "redis", "cosmos", "insights", "analytics", "kubernetes", "k8s",
    "aks", "vmss", "dns", "ddos", "ampls", "status", "series",
)  # fmt: skip
_TYPO_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("데이타베이스", "데이터베이스"), ("데이타", "데이터"),
    ("리소스그릅", "리소스그룹"), ("리소스구룹", "리소스그룹"),
    ("가상머씬", "가상머신"), ("가상머쉰", "가상머신"),
    ("컨테이나", "컨테이너"), ("콘테이너", "컨테이너"),
    ("스토리찌", "스토리지"), ("네트웍", "네트워크"), ("네트워그", "네트워크"),
    ("인시던츠", "인시던트"), ("인씨던트", "인시던트"),
    ("포스트그래스", "포스트그레스"), ("포스트그레큐엘", "포스트그레스"),
    ("쿠버네티쓰", "쿠버네티스"), ("큐버네티스", "쿠버네티스"),
    ("레디쓰", "레디스"), ("어플리케이션", "애플리케이션"), ("어플리게이션", "애플리케이션"),
    ("파이어월", "방화벽"), ("로드발란서", "로드밸런서"), ("로드벨런서", "로드밸런서"),
    ("발트", "볼트"), ("라우타", "라우터"), ("클러스타", "클러스터"),
    ("스냅샸", "스냅샷"), ("스케쥴", "스케줄"),
    ("엔트포인트", "엔드포인트"), ("앤드포인트", "엔드포인트"),
    ("virtulmachine", "virtualmachine"), ("virutalmachine", "virtualmachine"),
    ("resoucegroup", "resourcegroup"), ("resourcgroup", "resourcegroup"),
    ("postgrsql", "postgresql"), ("posgresql", "postgresql"), ("postgressql", "postgresql"),
    ("kubernets", "kubernetes"), ("kuberntes", "kubernetes"), ("kubernet", "kubernetes"),
    ("containrapp", "containerapp"), ("contianerapp", "containerapp"),
    ("storagaccount", "storageaccount"), ("databse", "database"), ("datbase", "database"),
    ("incidnet", "incident"), ("stoped", "stopped"),
)  # fmt: skip
_ONTOLOGY_CONCEPT_SEEDS: Mapping[MentionDomain, str] = {
    MentionDomain.RESOURCE_TYPE: """
group:resource-group=resourcegroup|rg|리소스그룹|자원그룹|리소스그릅
group:database=database|db|rdb|rdbms|데이터베이스|디비|데이터베이스서버|db서버
group:compute.vm=virtualmachine|vm|가상머신|가상서버|브이엠
group:compute.vm-scale-set=virtualmachinescaleset|vmscaleset|scaleset|vmss|가상머신확장집합|vm확장집합|확장집합|스케일셋
group:compute.container-app=containerapp|containerapplication|aca|컨테이너앱|컨테이너애플리케이션
group:compute.container-app-job=containerappjob|containerappsjob|컨테이너앱작업|컨테이너앱잡
group:compute.container-app-environment=containerappenvironment|managedenvironment|cae|컨테이너앱환경
group:compute.function=functionapp|azurefunction|funcapp|함수앱|펑션앱|애저함수
group:compute.web-app=webapp|appservice|웹앱|앱서비스
group:app-service-plan=appserviceplan|asp|앱서비스계획|앱서비스플랜|앱서비스요금제
group:static-web-app=staticwebapp|swa|정적웹앱
group:kubernetes-cluster=aks|akscluster|kubernetescluster|k8scluster|kubernetes|k8s|쿠버네티스|쿠버네티스클러스터|aks클러스터
group:kubernetes-node-pool=nodepool|agentpool|aksnodepool|노드풀|에이전트풀|aks노드풀
group:kubernetes.namespace=kubernetesnamespace|k8snamespace|쿠버네티스네임스페이스|네임스페이스
group:kubernetes.node=kubernetesnode|k8snode|쿠버네티스노드
group:kubernetes.pod=kubernetespod|k8spod|pod|쿠버네티스파드|파드|포드
group:kubernetes.service=kubernetesservice|k8sservice|쿠버네티스서비스
group:kubernetes.endpoints=kubernetesendpoints|쿠버네티스엔드포인트
group:kubernetes.endpoint-slice=endpointslice|엔드포인트슬라이스|쿠버네티스엔드포인트슬라이스
group:kubernetes.ingress=kubernetesingress|k8singress|ingress|쿠버네티스인그레스|인그레스
group:kubernetes.ingress-class=ingressclass|인그레스클래스
group:kubernetes.job=kubernetesjob|k8sjob|쿠버네티스잡|쿠버네티스작업
group:kubernetes.cron-job=cronjob|k8scronjob|크론잡|쿠버네티스크론잡
group:kubernetes.deployment=kubernetesdeployment|k8sdeployment|rollout|쿠버네티스디플로이먼트|쿠버네티스배포|롤아웃
group:kubernetes.replica-set=replicaset|rs|레플리카셋
group:kubernetes.daemon-set=daemonset|ds|데몬셋
group:kubernetes.stateful-set=statefulset|sts|스테이트풀셋
group:kubernetes.persistent-volume-claim=persistentvolumeclaim|pvc|영구볼륨클레임|퍼시스턴트볼륨클레임
group:kubernetes.persistent-volume=persistentvolume|pv|영구볼륨|퍼시스턴트볼륨
group:kubernetes.storage-class=storageclass|sc|스토리지클래스
group:kubernetes.horizontal-pod-autoscaler=horizontalpodautoscaler|hpa|수평파드오토스케일러|파드자동확장|오토스케일러
group:kubernetes.pod-disruption-budget=poddisruptionbudget|pdb|파드중단예산
group:kubernetes.network-policy=networkpolicy|netpol|네트워크정책|쿠버네티스네트워크정책
group:kubernetes.resource-quota=resourcequota|리소스쿼터|리소스할당량
group:kubernetes.limit-range=limitrange|리밋레인지|제한범위
group:workflow.logic-app=logicapp|로직앱|논리앱
group:ai-project=aiproject|foundryproject|ai프로젝트|foundry프로젝트|파운드리프로젝트
group:network.vnet=vnet|virtualnetwork|가상네트워크|브이넷
group:network.subnet=subnet|서브넷
group:network.nsg=nsg|networksecuritygroup|네트워크보안그룹|보안그룹
group:network.firewall=azurefirewall|firewall|fw|애저방화벽|방화벽
group:network.firewall-policy=firewallpolicy|방화벽정책
group:network.interface=networkinterface|nic|네트워크인터페이스|네트워크카드
group:network.private-endpoint=privateendpoint|pe|프라이빗엔드포인트|사설엔드포인트
group:network.load-balancer=loadbalancer|lb|로드밸런서|부하분산장치|부하분산기
group:network.application-gateway=applicationgateway|appgateway|agw|appgw|애플리케이션게이트웨이|앱게이트웨이
group:api-gateway=apimanagement|apim|apigateway|api관리|api게이트웨이
group:network.dns-zone=dnszone|publicdnszone|dns영역|dns존
group:network.private-dns-zone=privatednszone|프라이빗dns영역|사설dns영역|프라이빗dns존
group:network.public-ip=publicip|pip|publicipaddress|공인ip|퍼블릭ip|공용ip
group:network.nat-gateway=natgateway|natgw|nat게이트웨이
group:network.route-table=routetable|udr|userdefinedroute|라우트테이블|경로테이블|라우팅테이블
group:network.virtual-network-gateway=virtualnetworkgateway|vpngateway|vpngw|가상네트워크게이트웨이|vpn게이트웨이
group:network.bastion-host=bastion|bastionhost|azurebastion|베스천|배스천|배스천호스트
group:object-storage=storageaccount|blobstorage|스토리지계정|스토리지어카운트|저장소계정
group:container-registry=containerregistry|acr|컨테이너레지스트리
group:file-share=fileshare|azurefileshare|파일공유
group:disk=disk|manageddisk|osdisk|datadisk|디스크|관리디스크|관리형디스크
group:disk-snapshot=disksnapshot|snapshot|디스크스냅샷|스냅샷
group:backup-vault=backupvault|recoveryservicesvault|rsv|백업볼트|백업자격증명모음|복구서비스자격증명모음
group:sql-server=sqlserver|logicalsqlserver|mssqlserver|mssql|sql서버|mssql서버
group:sql-database=sqldatabase|sqldb|azuresqldb|sql데이터베이스|sql디비
group:sql-managed-instance=sqlmanagedinstance|sqlmi|sql관리형인스턴스
group:postgresql-server=postgres|postgresql|postgresserver|postgresqlserver|psql|pg|포스트그레스|포스트그레서버|포스트그레스서버
group:mysql-server=mysql|mysqlserver|mysqldatabase|mysql서버|mysql데이터베이스|마이에스큐엘
group:nosql-database=cosmosdb|azurecosmosdb|cosmos|nosqldatabase|코스모스db|코스모스디비|코즈모스db|cosmosdb계정
group:cache=rediscache|standardredis|redis|레디스|레디스캐시|캐시
group:redis-enterprise=redisenterprise|enterpriseredis|레디스엔터프라이즈|엔터프라이즈레디스
group:secret-store=keyvault|kv|akv|secretstore|키볼트|자격증명모음
group:managed-identity=managedidentity|userassignedidentity|uami|msi|관리형id|관리id|관리형아이덴티티|관리형신원
group:authorization.role-assignment=roleassignment|rbacassignment|역할할당|rbac할당|권한할당
group:certificate=keyvaultcertificate|tlscertificate|sslcertificate|certificate|인증서|tls인증서
group:ssh-public-key=sshkey|sshpublickey|ssh키|ssh공개키
group:log-workspace=loganalyticsworkspace|loganalytics|logworkspace|law|loganalytics작업영역|로그분석작업영역|로그애널리틱스|로그워크스페이스
group:metrics-workspace=azuremonitorworkspace|metricsworkspace|prometheusworkspace|amw|azuremonitor작업영역|메트릭워크스페이스|모니터작업영역
group:application-insights=applicationinsights|appinsights|appi|애플리케이션인사이트|앱인사이트
group:data-collection-rule=datacollectionrule|dcr|데이터수집규칙
group:data-collection-endpoint=datacollectionendpoint|dce|데이터수집엔드포인트
group:alert-rules=alertrule|경고규칙|알림규칙|얼럿규칙|알람규칙
group:alert-rule=scheduledqueryrule|logalert|logalertrule|로그경고규칙|로그알림규칙
group:metric-alert-rule=metricalert|metricalertrule|메트릭경고|메트릭경고규칙|메트릭알림규칙
group:anomaly-alert-rule=smartdetectoralertrule|anomalyalertrule|스마트감지경고규칙|이상감지경고규칙
group:activity-log-alert=activitylogalert|활동로그경고|액티비티로그경고
group:action-group=actiongroup|ag|작업그룹|액션그룹
group:observability.dashboard-service=managedgrafana|azuremanagedgrafana|grafana|grafanainstance|그라파나|관리형그라파나
group:observability.network-monitor=networkwatcher|네트워크감시자|네트워크워처
group:observability.workbook=workbook|azureworkbook|monitorworkbook|통합문서|워크북
group:llm-endpoint=azureopenai|azureopenaiaccount|openaiaccount|openairesource|cognitiveservicesaccount|aiservicesaccount|aoai|ai서비스계정|azureopenai리소스|openai리소스
group:llm-model-deployment=modeldeployment|deployedllm|llmdeployment|gptmodel|gptresource|deployedgptmodel|모델배포|배포된llm|llm배포|gpt모델|gpt리소스|배포된gpt모델
group:event-hub=eventhub|eventhubnamespace|eh|이벤트허브
group:service-bus-namespace=servicebus|servicebusnamespace|messagebroker|sb|서비스버스|메시지브로커
group:event-grid-topic=eventgridtopic|eventgridsystemtopic|systemtopic|이벤트그리드토픽|eventgrid시스템토픽
group:search-service=aisearch|azureaisearch|cognitivesearch|searchservice|검색서비스|ai검색
group:application-configuration=applicationconfigurationstore|appconfiguration|appconfig|앱구성저장소|앱컨피그
group:automation-account=automationaccount|자동화계정|오토메이션계정
group:analytics.workspace=analyticsworkspace|databricksworkspace|databricks|분석작업영역|데이터브릭스
group:iot-hub=iothub|devicehub|iot허브
group:realtime-messaging-service=signalrservice|signalr|realtimemessagingservice|실시간메시징서비스|시그널알
group:stream-analytics-job=streamanalyticsjob|streaminganalytics|스트림분석작업|스트림애널리틱스
group:diagnostic-settings=diagnosticsetting|진단설정
""",
    MentionDomain.OBJECT_TYPE: """
object:Incident=incident|인시던트|장애|사고
object:Resource=resource|azure리소스|리소스|자원|인벤토리
object:CausalHypothesis=causalhypothesis|hypothesis|인과가설|원인가설|가설
object:RecoveryPlan=recoveryplan|복구계획|회복계획
object:Change=change|변경|변경이력|변경사항
object:Rule=rule|탐지규칙|룰
object:Policy=policy|정책
object:Workflow=workflow|워크플로|워크플로우
object:Agent=agent|에이전트
object:Approval=approval|승인|승인요청
object:Budget=budget|예산
object:CostAnomaly=costanomaly|비용이상|비용이상징후
object:CapacityForecast=capacityforecast|용량예측
object:SizingRecommendation=sizingrecommendation|사이징권장|크기조정권장
object:Document=document|문서
object:Skill=skill|스킬
object:BackgroundTask=backgroundtask|백그라운드작업|백그라운드태스크
object:Decision=decision|의사결정|결정
object:Notification=notification|알림
object:DiagnosticFinding=diagnosticfinding|진단발견|진단결과
object:ConfigurationDriftFinding=configurationdriftfinding|구성드리프트|드리프트
object:CodeSecurityFinding=codesecurityfinding|코드보안발견|보안취약점
""",
    MentionDomain.STATE: """
state:stopped_or_deallocated=stop|stopped|stoppedstate|shut|shutdown|poweredoff|notrunning|down|inactive|중지|중지된|중지됨|정지|정지된|정지됨|멈춘|멈춤|꺼진|꺼짐|내려간|비활성|가동중지
state:resource_state.deallocated=deallocated|deallocate|할당해제|할당해제된|할당해제됨
state:resource_state.running=running|runningstate|active|started|up|실행중|실행중인|가동중|가동중인|동작중|켜진|켜져있는|활성
state:resource_state.failed=failed|failedstate|failure|errorstate|실패|실패한|실패됨|오류상태
state:resource_state.degraded=degraded|degradedstate|성능저하|저하된|저하됨|저하
state:resource_state.unavailable=unavailable|unavailablestate|사용불가능|이용불가|사용불가|불능
state:resource_state.available=available|availablestate|사용가능|사용가능한|가용
state:resource_state.online=online|onlinestate|온라인
state:resource_state.paused=paused|pausedstate|일시중지|일시중지된|일시정지|일시정지된
state:resource_state.ready=ready|readystate|준비됨|준비된|준비
state:resource_state.succeeded=succeeded|succeededstate|성공|성공한|성공함
""",
    MentionDomain.REGION: """
region:koreacentral=koreacentral|한국중부|서울리전|코리아센트럴
region:koreasouth=koreasouth|한국남부|부산리전|코리아사우스
region:eastus=eastus|미국동부|이스트유에스
region:eastus2=eastus2|미국동부2
region:westus=westus|미국서부|웨스트유에스
region:westus2=westus2|미국서부2
region:westus3=westus3|미국서부3
region:centralus=centralus|미국중부|센트럴유에스
region:japaneast=japaneast|일본동부|도쿄리전
region:japanwest=japanwest|일본서부|오사카리전
region:southeastasia=southeastasia|동남아시아|동남아|싱가포르리전
region:eastasia=eastasia|동아시아|홍콩리전
region:westeurope=westeurope|서유럽
region:northeurope=northeurope|북유럽
region:uksouth=uksouth|영국남부|런던리전
region:swedencentral=swedencentral|스웨덴중부
region:australiaeast=australiaeast|호주동부
region:germanywestcentral=germanywestcentral|독일서중부
region:francecentral=francecentral|프랑스중부
region:canadacentral=canadacentral|캐나다중부
region:brazilsouth=brazilsouth|브라질남부
region:centralindia=centralindia|인도중부
""",
}  # noqa: E501


def _strip_english_plural(token: str) -> str:
    if len(token) <= 2 or not token.isascii() or not token.isalnum():
        return token
    if any(token.endswith(keep) for keep in _PRESERVE_S_SUFFIX):
        return token
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def _normalize_concept_term(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    for prefix in _LEADING_MODIFIERS:
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    raw = "".join(ch for ch in normalized if ch.isalnum() or "가" <= ch <= "힣")
    for wrong, right in _TYPO_SUBSTITUTIONS:
        if wrong in raw:
            raw = raw.replace(wrong, right)
    for _ in range(2):
        stripped = False
        for suffix in _TRAILING_PARTICLES:
            if len(raw) > len(suffix) and raw.endswith(suffix):
                raw = raw[: -len(suffix)]
                stripped = True
                break
        new_raw = _strip_english_plural(raw)
        if new_raw != raw:
            raw = new_raw
            stripped = True
        if not stripped:
            break
    for wrong, right in _TYPO_SUBSTITUTIONS:
        if wrong in raw:
            raw = raw.replace(wrong, right)
    return _strip_english_plural(raw)


def _mention_cache_key(item: Mapping[str, Any]) -> str:
    return _normalize_concept_term(str(item.get("text", "")))


def _one_edit_distance(a: str, b: str) -> bool:
    min_len = 3 if any("가" <= ch <= "힣" for ch in a) else 5
    if len(a) < min_len or len(b) < min_len or a[0] != b[0] or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = diffs_count = 0
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
        else:
            diffs_count += 1
            if diffs_count > 1:
                return False
            j += 1
    return True


def _build_domain_seed_index() -> dict[MentionDomain, dict[str, str]]:
    out: dict[MentionDomain, dict[str, str]] = {}
    for domain, block in _ONTOLOGY_CONCEPT_SEEDS.items():
        index: dict[str, str] = {}
        for line in block.strip().splitlines():
            candidate_id, _, terms_spec = line.partition("=")
            for term in terms_spec.split("|"):
                norm = _normalize_concept_term(term)
                if norm:
                    index[norm] = candidate_id.strip()
        out[domain] = index
    out[MentionDomain.RESOURCE_CLASS] = dict(out[MentionDomain.RESOURCE_TYPE])
    return out


_DOMAIN_SEED_INDEX = _build_domain_seed_index()
_SHARD_LABEL_INDEX: dict[str, dict[str, str | None]] = {}


def _shard_unambiguous_labels(shard: ConceptShard) -> Mapping[str, str | None]:
    cached = _SHARD_LABEL_INDEX.get(shard.digest)
    if cached is not None:
        return cached
    index: dict[str, str | None] = {}
    for candidate in shard.candidates:
        if candidate.id == "any:resource":
            continue
        for label in (*candidate.labels, *candidate.values):
            norm = _normalize_concept_term(str(label))
            if not norm:
                continue
            if norm not in index:
                index[norm] = candidate.id
            elif index[norm] != candidate.id:
                index[norm] = None
    _SHARD_LABEL_INDEX[shard.digest] = index
    return index


def _match_seed_or_typo(key: str, table: Mapping[str, str]) -> str | None:
    if not key:
        return None
    if direct := table.get(key):
        return direct
    matched: set[str] = {
        cand_id for term, cand_id in table.items() if _one_edit_distance(key, term)
    }
    return next(iter(matched)) if len(matched) == 1 else None


def _resolve_seeded_concept_choice(shard: ConceptShard, key: str) -> list[str] | None:
    if not key:
        return None
    shard_ids = {c.id for c in shard.candidates}
    domain_seeds = _DOMAIN_SEED_INDEX.get(shard.domain, {})
    target_id = _match_seed_or_typo(key, domain_seeds)
    if target_id is None and shard.total == 1:
        unambiguous = {k: v for k, v in _shard_unambiguous_labels(shard).items() if v is not None}
        target_id = _match_seed_or_typo(key, unambiguous)
    if target_id is not None:
        if target_id in shard_ids:
            return [target_id]
        if shard.total > 1 and len(shard.candidates) >= 50:
            return []
        return None
    if shard.domain is MentionDomain.OBJECT_TYPE and shard.total == 1:
        rt_seeds = _DOMAIN_SEED_INDEX[MentionDomain.RESOURCE_TYPE]
        if _match_seed_or_typo(key, rt_seeds) is not None and not any(
            key == _normalize_concept_term(lbl)
            for c in shard.candidates
            for lbl in (*c.labels, *c.values)
        ):
            return []
    if shard.domain in (MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS) and (
        shard.total == 1 or len(shard.candidates) >= 50
    ):
        obj_seeds = _DOMAIN_SEED_INDEX[MentionDomain.OBJECT_TYPE]
        obj_hit = _match_seed_or_typo(key, obj_seeds)
        if obj_hit is not None and obj_hit != "object:Resource":
            return []
    return None


def _shard_cache_key(shard: ConceptShard | str) -> str:
    if isinstance(shard, str):
        return shard
    return f"{shard.catalog_digest}:{shard.index}:{shard.total}"


def lookup_cached_concept_choices(
    shard: ConceptShard | str,
    second: bool,
    mentions: Sequence[Mapping[str, Any]],
    *,
    live: bool,
) -> dict[str, Any] | None:
    if not live or not mentions:
        return None
    shard_key = _shard_cache_key(shard)
    shard_digest = shard if isinstance(shard, str) else shard.digest
    choices: list[dict[str, Any]] = []
    for item in mentions:
        norm_key = _mention_cache_key(item)
        key = (shard_key, second, norm_key)
        cached = _SHARED_CONCEPT_CACHE.get(key)
        if cached is not None:
            _SHARED_CONCEPT_CACHE.move_to_end(key)
            choices.append({"mention": str(item.get("mention")), "candidate_ids": list(cached)})
            continue
        if isinstance(shard, ConceptShard):
            seeded = _resolve_seeded_concept_choice(shard, norm_key)
            if seeded is not None:
                choices.append({"mention": str(item.get("mention")), "candidate_ids": seeded})
                continue
        return None
    return {"shard_digest": shard_digest, "choices": choices}


def store_cached_concept_choices(
    shard: ConceptShard | str,
    second: bool,
    mentions: Sequence[Mapping[str, Any]],
    decoded: Sequence[Mapping[str, Any]],
    *,
    live: bool,
) -> None:
    if not live or len(decoded) != len(mentions):
        return
    shard_key = _shard_cache_key(shard)
    by_id = {str(item.get("mention")): _mention_cache_key(item) for item in mentions}
    for choice in decoded:
        mention_id = str(choice.get("mention"))
        text_key = by_id.get(mention_id)
        ids = choice.get("candidate_ids")
        if text_key and isinstance(ids, list):
            key = (shard_key, second, text_key)
            _SHARED_CONCEPT_CACHE[key] = tuple(str(v) for v in ids)
            _SHARED_CONCEPT_CACHE.move_to_end(key)
            while len(_SHARED_CONCEPT_CACHE) > _MAX_SHARED_CONCEPT_CACHE:
                _SHARED_CONCEPT_CACHE.popitem(last=False)


_SHARED_CALL_CACHE: OrderedDict[tuple[str, str], Mapping[str, Any]] = OrderedDict()


def lookup_cached_call(kind: str, key: str, *, live: bool) -> dict[str, Any] | None:
    if not live or not key or kind == "semantic-concept-selection" or '"repair":' in key:
        return None
    cache_key = (kind, key)
    cached = _SHARED_CALL_CACHE.get(cache_key)
    if cached is None:
        return None
    _SHARED_CALL_CACHE.move_to_end(cache_key)
    return copy.deepcopy(dict(cached))


def store_cached_call(kind: str, key: str, value: Mapping[str, Any], *, live: bool) -> None:
    if not live or not key or kind == "semantic-concept-selection" or '"repair":' in key:
        return
    cache_key = (kind, key)
    _SHARED_CALL_CACHE[cache_key] = copy.deepcopy(dict(value))
    _SHARED_CALL_CACHE.move_to_end(cache_key)
    while len(_SHARED_CALL_CACHE) > _MAX_SHARED_CONCEPT_CACHE:
        _SHARED_CALL_CACHE.popitem(last=False)


class ConceptChooser(Protocol):
    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> Mapping[str, Any] | None: ...


async def select_concepts(
    model: ConceptChooser,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
) -> ConceptSelectionReceipt:
    """Ground every concept with two blind choosers of different model families.

    Each chooser sees every planned shard and resolves its own runoff; a binding stands
    only where both choose the same values, so no single reader grounds a concept.
    """

    primary, second = await asyncio.gather(
        select_chooser_concepts(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=False,
        ),
        select_chooser_concepts(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=True,
        ),
    )
    return agree_concepts(primary, second)


async def select_chooser_concepts(
    model: ConceptChooser,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
    second: bool,
) -> ConceptSelectionReceipt:
    """Present every planned shard to one chooser, then accept verified choices.

    A failed or cancelled wave cancels and drains its other call before the error
    propagates, so no provider call outlives the stage.
    """

    plan = plan_concept_selection(
        admission,
        catalogs=catalogs,
        max_model_calls=max_calls,
        max_shard_bytes=max_shard_bytes,
    )

    async def choose(request: Any) -> Mapping[str, Any] | None:
        return await model.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard, second=second
        )

    async def choose_wave(requests: tuple[Any, ...]) -> list[Mapping[str, Any] | None]:
        tasks = [asyncio.create_task(choose(request)) for request in requests]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    answers: list[Mapping[str, Any] | None] = []
    retries = 0
    for offset in range(0, len(plan.requests), 2):
        wave = plan.requests[offset : offset + 2]
        results = await choose_wave(wave)
        for request, answer in zip(wave, results, strict=True):
            if not shard_answer_valid(answer, request) and (
                len(plan.requests) + retries < max_calls
            ):
                retries += 1
                answer = await choose(request)
            answers.append(answer)
    receipt = accept_concept_selection(plan, answers)
    receipt = replace(receipt, model_calls=receipt.model_calls + retries)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_calls:
        return receipt
    runoff_answers: list[Mapping[str, Any] | None] = []
    for offset in range(0, len(runoff), 2):
        runoff_answers.extend(await choose_wave(runoff[offset : offset + 2]))
    return apply_runoff(receipt, runoff, runoff_answers)


__all__ = [
    "ConceptChooser",
    "lookup_cached_call",
    "lookup_cached_concept_choices",
    "select_chooser_concepts",
    "select_concepts",
    "store_cached_call",
    "store_cached_concept_choices",
]
