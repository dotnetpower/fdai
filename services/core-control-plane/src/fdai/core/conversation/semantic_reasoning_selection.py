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

_MAX_SHARED_CONCEPT_CACHE = 2048
_SHARED_CONCEPT_CACHE: OrderedDict[tuple[str, bool, str], tuple[str, ...]] = OrderedDict()
_LEADING_MODIFIERS = (
    "the ", "an ", "a ", "all ", "every ", "any ", "each ", "some ", "which ", "what ",
    "my ", "our ", "this ", "that ", "these ", "those ",
    "current ", "existing ", "active ", "registered ", "deployed ", "configured ",
    "모든 ", "전체 ", "현재 ", "기존 ", "우리 ", "내 ", "해당 ", "각 ",
    "등록된 ", "생성된 ", "배포된 ", "설정된 ", "연결된 ", "사용중인 ",
)  # fmt: skip
_TRAILING_PARTICLES = (
    "목록들을", "목록들이", "목록들은", "목록들", "목록을", "목록이", "목록은", "목록",
    "리스트를", "리스트가", "리스트는", "리스트", "현황을", "현황이", "현황은", "현황",
    "내역을", "내역이", "내역은", "내역", "정보를", "정보가", "정보는", "정보",
    "개수를", "개수가", "개수는", "개수", "상태를", "상태가", "상태는", "상태인", "상태의", "상태",
    "인가요", "입니까", "인가", "인지", "이야", "중에서", "중에", "별로", "전부", "모두",
    "들을", "들이", "들은", "들의", "들에", "들로", "들만", "들도", "들",
    "이란", "란", "이나", "나", "이랑", "랑", "하고", "부터", "까지", "마다",
    "에서", "에게", "으로", "로",
    "이", "가", "을", "를", "은", "는", "의", "에", "도", "만", "와", "과", "별", "중", "야",
)  # fmt: skip
_PRESERVE_S_SUFFIX = (
    "ss", "redis", "cosmos", "insights", "analytics", "kubernetes", "k8s",
    "aks", "vmss", "dns", "ddos", "ampls", "status", "series", "acs", "avs",
)  # fmt: skip
_TYPO_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("데이타베이스", "데이터베이스"), ("데이타", "데이터"),
    ("리소스그릅", "리소스그룹"), ("리소스구룹", "리소스그룹"),
    ("가상머씬", "가상머신"), ("가상머쉰", "가상머신"),
    ("컨테이나", "컨테이너"), ("콘테이너", "컨테이너"),
    ("스토리찌", "스토리지"), ("네트웍", "네트워크"), ("네트워그", "네트워크"),
    ("인시던츠", "인시던트"), ("인씨던트", "인시던트"), ("인시던드", "인시던트"),
    ("포스트그래스", "포스트그레스"), ("포스트그레큐엘", "포스트그레스"),
    ("쿠버네티쓰", "쿠버네티스"), ("큐버네티스", "쿠버네티스"),
    ("레디쓰", "레디스"), ("어플리케이션", "애플리케이션"), ("어플리게이션", "애플리케이션"),
    ("파이어월", "방화벽"), ("방화벅", "방화벽"),
    ("로드발란서", "로드밸런서"), ("로드벨런서", "로드밸런서"),
    ("발트", "볼트"), ("라우타", "라우터"), ("클러스타", "클러스터"),
    ("스냅샸", "스냅샷"), ("스케쥴", "스케줄"),
    ("엔트포인트", "엔드포인트"), ("앤드포인트", "엔드포인트"),
    ("메트릭스", "메트릭"), ("매트릭", "메트릭"), ("패스워드", "비밀"),
    ("게이트웨히", "게이트웨이"), ("워크스패이스", "워크스페이스"),
    ("네임스패이스", "네임스페이스"), ("오토스케일라", "오토스케일러"),
    ("프로메태우스", "프로메테우스"), ("그라파냐", "그라파나"),
    ("서브스크립션", "구독"), ("섭스크립션", "구독"),
    ("아키택처", "아키텍처"), ("컴피그레이션", "컨피규레이션"),
    ("인프라스트럭춰", "인프라스트럭처"), ("오케스트래이션", "오케스트레이션"),
    ("리파지토리", "레지스트리"), ("서티피케이트", "인증서"),
    ("노티피케이션", "알림"), ("익스텐숀", "익스텐션"), ("디플로이먼드", "디플로이먼트"),
    ("virtulmachine", "virtualmachine"), ("virutalmachine", "virtualmachine"),
    ("resoucegroup", "resourcegroup"), ("resourcgroup", "resourcegroup"),
    ("postgrsql", "postgresql"), ("posgresql", "postgresql"), ("postgressql", "postgresql"),
    ("kubernets", "kubernetes"), ("kuberntes", "kubernetes"), ("kubernet", "kubernetes"),
    ("containrapp", "containerapp"), ("contianerapp", "containerapp"),
    ("storagaccount", "storageaccount"), ("databse", "database"), ("datbase", "database"),
    ("incidnet", "incident"), ("stoped", "stopped"), ("deallocted", "deallocated"),
    ("unavailble", "unavailable"), ("degraed", "degraded"), ("subscrption", "subscription"),
)  # fmt: skip
_ONTOLOGY_CONCEPT_SEEDS: Mapping[MentionDomain, str] = {
    MentionDomain.RESOURCE_TYPE: """
any:resource=resource|resources|anyresource|anyresourcetype|resourcesingeneral|azure리소스|리소스|전체리소스|모든리소스|모든종류의리소스|리소스전체|자원|인벤토리|클라우드리소스
group:compute=compute|computeresource|컴퓨트|컴퓨팅|컴퓨팅리소스|연산리소스;group:network=network|networking|networkresource|네트워크|네트워킹|네트워크리소스|망리소스
group:storage=storage|storageresource|스토리지|스토리지리소스|저장소|저장소리소스;group:security=security|securityresource|보안|보안리소스
group:observability=observability|monitoring|monitoringresource|관측성|모니터링|모니터링리소스|관제리소스;group:governance=governance|governanceresource|거버넌스|거버넌스리소스
group:cache-services=cacheservice|캐시서비스;group:function-container-applications=functionorcontainerapplication|functionandcontainerapplication|함수또는컨테이너앱|함수및컨테이너앱
value:subscription=subscription|azuresubscription|sub|구독|애저구독;value:unclassified-resource=unclassifiedresource|미분류리소스|기타리소스
group:resource-group=resourcegroup|rg|리소스그룹|자원그룹|리소스그릅|rg목록;group:database=database|db|rdb|rdbms|데이터베이스|디비|데이터베이스서버|db서버|관계형데이터베이스|디비서버
group:compute.vm=virtualmachine|vm|가상머신|가상서버|브이엠|클라우드서버|vm인스턴스|가상머신인스턴스;group:compute.vm-scale-set=virtualmachinescaleset|vmscaleset|scaleset|vmss|가상머신확장집합|vm확장집합|확장집합|스케일셋
group:compute.container-app=containerapp|containerapplication|aca|컨테이너앱|컨테이너애플리케이션|도커컨테이너앱;group:compute.container-app-job=containerappjob|containerappsjob|컨테이너앱작업|컨테이너앱잡
group:compute.container-app-environment=containerappenvironment|managedenvironment|cae|컨테이너앱환경;group:compute.function=functionapp|azurefunction|funcapp|함수앱|펑션앱|애저함수|서버리스함수|펑션
group:compute.web-app=webapp|appservice|웹앱|앱서비스|웹서버|웹애플리케이션;group:app-service-plan=appserviceplan|asp|앱서비스계획|앱서비스플랜|앱서비스요금제;group:static-web-app=staticwebapp|swa|정적웹앱
group:compute.app-slot=deploymentslot|applicationslot|appslot|배포슬롯|앱슬롯|슬롯;group:compute.batch-account=batchaccount|azurebatch|배치계정|일괄처리계정
group:compute.desktop-host-pool=desktophostpool|hostpool|avdhostpool|데스크톱호스트풀|호스트풀;group:compute.desktop-scaling-plan=desktopscalingplan|desktopautoscale|데스크톱크기조정계획|데스크톱스케일링플랜
group:compute.gallery-image=galleryimagedefinition|갤러리이미지정의|갤러리이미지;group:compute.gallery-image-version=galleryimageversion|imageversion|갤러리이미지버전|이미지버전
group:compute.image=managedimage|machineimage|vmimage|관리형이미지|머신이미지|vm이미지;group:compute.image-gallery=computeimagegallery|imagegallery|sharedimagegallery|sig|컴퓨팅이미지갤러리|이미지갤러리
group:compute.image-template=imagetemplate|imagebuildertemplate|이미지템플릿;group:compute.private-virtualization-cloud=privatevirtualizationcloud|azurevmwaresolution|avs|프라이빗가상화클라우드|vmware솔루션
group:compute.vm-extension=vmextension|virtualmachineextension|vm확장|가상머신확장|익스텐션;group:compute.vm-run-command=vmruncommand|runcommand|vm실행명령|실행명령|런커맨드
group:compute.vm-shutdown-schedule=vmshutdownschedule|vmautoshutdownschedule|가상머신자동종료일정|vm자동종료일정|자동종료일정;group:bot-service=botservice|azurebot|봇서비스|애저봇|챗봇서비스
group:communication-service=communicationservice|azurecommunicationservices|acs|커뮤니케이션서비스;group:kubernetes-cluster=aks|akscluster|kubernetescluster|k8scluster|kubernetes|k8s|쿠버네티스|쿠버네티스클러스터|aks클러스터|k8s클러스터
group:kubernetes-node-pool=nodepool|agentpool|aksnodepool|노드풀|에이전트풀|aks노드풀|k8s노드풀;group:kubernetes.namespace=kubernetesnamespace|k8snamespace|쿠버네티스네임스페이스|네임스페이스|k8s네임스페이스
group:kubernetes.node=kubernetesnode|k8snode|쿠버네티스노드|k8s노드|워커노드;group:kubernetes.pod=kubernetespod|k8spod|pod|쿠버네티스파드|파드|포드|k8s파드
group:kubernetes.service=kubernetesservice|k8sservice|쿠버네티스서비스|k8s서비스;group:kubernetes.endpoints=kubernetesendpoints|쿠버네티스엔드포인트|k8s엔드포인트
group:kubernetes.endpoint-slice=endpointslice|엔드포인트슬라이스|쿠버네티스엔드포인트슬라이스;group:kubernetes.ingress=kubernetesingress|k8singress|ingress|쿠버네티스인그레스|인그레스|k8s인그레스
group:kubernetes.ingress-class=ingressclass|인그레스클래스;group:kubernetes.job=kubernetesjob|k8sjob|쿠버네티스잡|쿠버네티스작업|k8s잡
group:kubernetes.cron-job=cronjob|k8scronjob|크론잡|쿠버네티스크론잡|k8s크론잡;group:kubernetes.deployment=kubernetesdeployment|k8sdeployment|rollout|쿠버네티스디플로이먼트|쿠버네티스배포|롤아웃|k8s디플로이먼트
group:kubernetes.replica-set=replicaset|rs|레플리카셋|k8s레플리카셋;group:kubernetes.daemon-set=daemonset|ds|데몬셋|k8s데몬셋;group:kubernetes.stateful-set=statefulset|sts|스테이트풀셋|k8s스테이트풀셋
group:kubernetes.persistent-volume-claim=persistentvolumeclaim|pvc|영구볼륨클레임|퍼시스턴트볼륨클레임;group:kubernetes.persistent-volume=persistentvolume|pv|영구볼륨|퍼시스턴트볼륨
group:kubernetes.storage-class=storageclass|sc|스토리지클래스;group:kubernetes.horizontal-pod-autoscaler=horizontalpodautoscaler|hpa|수평파드오토스케일러|파드자동확장|오토스케일러
group:kubernetes.pod-disruption-budget=poddisruptionbudget|pdb|파드중단예산;group:kubernetes.network-policy=networkpolicy|netpol|네트워크정책|쿠버네티스네트워크정책
group:kubernetes.resource-quota=resourcequota|리소스쿼터|리소스할당량;group:kubernetes.limit-range=limitrange|리밋레인지|제한범위
group:workflow.logic-app=logicapp|로직앱|논리앱;group:workflow.api-connection=apiconnection|logicappconnection|api연결|로직앱연결
group:ai-project=aiproject|foundryproject|ai프로젝트|foundry프로젝트|파운드리프로젝트;group:ml-model-registry=machinelearningregistry|modelregistry|기계학습레지스트리|모델레지스트리
group:ml-workspace=machinelearningworkspace|mlworkspace|aml|기계학습작업영역|ml워크스페이스;group:web-search-service=bingsearch|bingsearchaccount|bing검색|웹검색서비스
group:network.vnet=vnet|virtualnetwork|가상네트워크|브이넷|가상망;group:network.subnet=subnet|서브넷|하위네트워크;group:network.nsg=nsg|networksecuritygroup|네트워크보안그룹|보안그룹|방화벽그룹
group:network.firewall=azurefirewall|firewall|fw|애저방화벽|방화벽;group:network.firewall-policy=firewallpolicy|방화벽정책
group:network.interface=networkinterface|nic|네트워크인터페이스|네트워크카드|랜카드;group:network.private-endpoint=privateendpoint|pe|프라이빗엔드포인트|사설엔드포인트|프라이빗링크엔드포인트
group:network.load-balancer=loadbalancer|lb|로드밸런서|부하분산장치|부하분산기|엘비;group:network.application-gateway=applicationgateway|appgateway|agw|appgw|애플리케이션게이트웨이|앱게이트웨이
group:api-gateway=apimanagement|apim|apigateway|api관리|api게이트웨이;group:network.dns-zone=dnszone|publicdnszone|dns영역|dns존|퍼블릭dns영역
group:network.private-dns-zone=privatednszone|프라이빗dns영역|사설dns영역|프라이빗dns존;group:network.private-dns-zone-group=privatednszonegroup|dnszonegroup|프라이빗dns영역그룹|dns영역그룹
group:network.private-dns-zone-link=privatednszonelink|virtualnetworklink|프라이빗dns영역링크|dns영역링크|가상네트워크링크;group:network.public-ip=publicip|pip|publicipaddress|공인ip|퍼블릭ip|공용ip|공인아이피|퍼블릭아이피
group:network.nat-gateway=natgateway|natgw|nat게이트웨이;group:network.route-table=routetable|udr|userdefinedroute|라우트테이블|경로테이블|라우팅테이블
group:network.virtual-network-gateway=virtualnetworkgateway|vpngateway|vpngw|가상네트워크게이트웨이|vpn게이트웨이;group:network.bastion-host=bastion|bastionhost|azurebastion|베스천|배스천|배스천호스트
group:network.cdn-profile=cdnprofile|contentdeliveryprofile|콘텐츠배달프로필|cdn프로필;group:network.cdn-origin-group=cdnorigingroup|origingroup|원본그룹|오리진그룹
group:network.connection=gatewayconnection|networkconnection|게이트웨이연결|네트워크연결;group:network.ddos-protection-plan=ddosprotectionplan|ddosplan|ddos보호계획|디도스보호계획|디도스플랜
group:network.dns-resolver=dnsresolver|privatednsresolver|dns리졸버|dns확인자;group:network.dns-resolver-inbound-endpoint=dnsresolverinboundendpoint|inboundendpoint|인바운드엔드포인트
group:network.dns-routing-profile=trafficmanagerprofile|dnsroutingprofile|트래픽매니저|dns라우팅프로필;group:network.private-access-scope=privatelinkscope|azuremonitorprivatelinkscope|ampls|프라이빗링크범위
group:network.private-circuit=expressroutecircuit|privatenetworkcircuit|익스프레스라우트|프라이빗네트워크회선|전용회선;group:network.private-circuit-gateway=privatecircuitgateway|virtualhubexpressroutegateway|프라이빗회선게이트웨이
group:network.private-peering-port=expressrouteport|privatepeeringport|프라이빗피어링포트;group:network.registered-domain=registereddomain|appservicedomain|등록된도메인
group:network.site-vpn-gateway=sitevpngateway|sitetositevpngateway|사이트vpn게이트웨이;group:network.user-vpn-gateway=uservpngateway|pointtositevpngateway|사용자vpn게이트웨이
group:network.virtual-hub=virtualhub|vhub|가상허브;group:network.virtual-router=virtualrouter|가상라우터;group:network.vpn-site=vpnsite|vpn사이트
group:object-storage=storageaccount|blobstorage|스토리지계정|스토리지어카운트|저장소계정|오브젝트스토리지|블롭스토리지;group:container-registry=containerregistry|acr|컨테이너레지스트리|이미지레지스트리
group:file-share=fileshare|azurefileshare|파일공유|공유파일;group:file-volume=managedfilevolume|netappvolume|anfvolume|관리형파일볼륨|넷앱볼륨
group:storage.file-account=managedfilestorageaccount|netappaccount|관리형파일저장소계정|넷앱계정;group:storage.file-capacity-pool=filestoragecapacitypool|filecapacitypool|파일저장소용량풀
group:disk=disk|manageddisk|osdisk|datadisk|디스크|관리디스크|관리형디스크|매니지드디스크;group:disk-snapshot=disksnapshot|snapshot|디스크스냅샷|스냅샷
group:backup-vault=backupvault|recoveryservicesvault|rsv|백업볼트|백업자격증명모음|복구서비스자격증명모음|백업저장소;group:sql-server=sqlserver|logicalsqlserver|mssqlserver|mssql|sql서버|mssql서버
group:sql-database=sqldatabase|sqldb|azuresqldb|sql데이터베이스|sql디비;group:sql-managed-instance=sqlmanagedinstance|sqlmi|sql관리형인스턴스
group:postgresql-server=postgres|postgresql|postgresserver|postgresqlserver|psql|pg|포스트그레스|포스트그레서버|포스트그레스서버|포스트그레스큐엘;group:mysql-server=mysql|mysqlserver|mysqldatabase|mysql서버|mysql데이터베이스|마이에스큐엘|마이sql
group:nosql-database=cosmosdb|azurecosmosdb|cosmos|nosqldatabase|코스모스db|코스모스디비|코즈모스db|cosmosdb계정|nosql디비;group:database.dedicated-infrastructure=dedicateddatabaseinfrastructure|oracledatabaseinfrastructure|전용데이터베이스인프라
group:database.vm-cluster=databasevmcluster|databasevirtualmachinecluster|데이터베이스vm클러스터;group:cache=rediscache|standardredis|redis|레디스|레디스캐시|캐시|인메모리캐시
group:redis-enterprise=redisenterprise|enterpriseredis|레디스엔터프라이즈|엔터프라이즈레디스;group:secret-store=keyvault|kv|akv|secretstore|키볼트|자격증명모음|시크릿스토어|비밀저장소
group:managed-identity=managedidentity|userassignedidentity|uami|msi|관리형id|관리id|관리형아이덴티티|관리형신원|매니지드아이덴티티;group:authorization.role-assignment=roleassignment|rbacassignment|역할할당|rbac할당|권한할당|권한부여
group:certificate=keyvaultcertificate|tlscertificate|sslcertificate|certificate|인증서|tls인증서|ssl인증서;group:managed-certificate=managedcertificate|관리형인증서
group:ssh-public-key=sshkey|sshpublickey|ssh키|ssh공개키;group:directory.managed-domain=manageddomain|관리형도메인
group:devops-account=azuredevopsaccount|devopsaccount|ado|azuredevops계정|데브옵스계정;group:email-domain=emaildomain|senderdomain|이메일도메인|발신도메인
group:email-service=emailservice|emailcommunicationservice|이메일서비스;group:event-topic=eventgridcustomtopic|customeventtopic|사용자지정이벤트토픽|커스텀토픽
group:log-workspace=loganalyticsworkspace|loganalytics|logworkspace|law|loganalytics작업영역|로그분석작업영역|로그애널리틱스|로그워크스페이스|로그분석워크스페이스;group:metrics-workspace=azuremonitorworkspace|metricsworkspace|prometheusworkspace|amw|azuremonitor작업영역|메트릭워크스페이스|모니터작업영역|모니터링워크스페이스
group:application-insights=applicationinsights|appinsights|appi|애플리케이션인사이트|앱인사이트;group:data-collection-rule=datacollectionrule|dcr|데이터수집규칙
group:data-collection-endpoint=datacollectionendpoint|dce|데이터수집엔드포인트;group:alert-rules=alertrule|경고규칙|알림규칙|얼럿규칙|알람규칙|경고룰|알람룰|얼럿룰
group:alert-rule=scheduledqueryrule|logalert|logalertrule|로그경고규칙|로그알림규칙|로그알람;group:metric-alert-rule=metricalert|metricalertrule|메트릭경고|메트릭경고규칙|메트릭알림규칙|메트릭알람
group:anomaly-alert-rule=smartdetectoralertrule|anomalyalertrule|스마트감지경고규칙|이상감지경고규칙;group:activity-log-alert=activitylogalert|활동로그경고|액티비티로그경고|활동로그알람
group:action-group=actiongroup|ag|작업그룹|액션그룹|수신자그룹;group:prometheus-rule-group=prometheusrulegroup|prometheusrule|프로메테우스규칙그룹
group:managed-sre-agent=sreagent|azuresreagent|sre에이전트;group:observability.dashboard-service=managedgrafana|azuremanagedgrafana|grafana|grafanainstance|그라파나|관리형그라파나|그라파나대시보드
group:observability.dashboard=portaldashboard|azuredashboard|shareddashboard|포털대시보드|애저대시보드;group:observability.network-monitor=networkwatcher|네트워크감시자|네트워크워처
group:observability.network-flow-log=networkflowlog|flowlog|네트워크흐름로그|플로우로그;group:observability.query-pack=querypack|logquerypack|쿼리팩
group:observability.solution=monitoringsolution|loganalyticssolution|모니터링솔루션;group:observability.traffic-collector=trafficcollector|트래픽수집기
group:observability.workbook=workbook|azureworkbook|monitorworkbook|통합문서|워크북;group:llm-endpoint=azureopenai|azureopenaiaccount|openaiaccount|openairesource|cognitiveservicesaccount|aiservicesaccount|aoai|ai서비스계정|azureopenai리소스|openai리소스|오픈ai|애저오픈ai
group:llm-model-deployment=modeldeployment|deployedllm|llmdeployment|gptmodel|gptresource|deployedgptmodel|모델배포|배포된llm|llm배포|gpt모델|gpt리소스|배포된gpt모델|llm모델
group:event-hub=eventhub|eventhubnamespace|eh|이벤트허브;group:service-bus-namespace=servicebus|servicebusnamespace|messagebroker|sb|서비스버스|메시지브로커|메시지큐
group:event-grid-topic=eventgridtopic|eventgridsystemtopic|systemtopic|이벤트그리드토픽|eventgrid시스템토픽|이벤트브로커;group:search-service=aisearch|azureaisearch|cognitivesearch|searchservice|검색서비스|ai검색
group:application-configuration=applicationconfigurationstore|appconfiguration|appconfig|앱구성저장소|앱컨피그;group:automation-account=automationaccount|자동화계정|오토메이션계정
group:analytics.workspace=analyticsworkspace|databricksworkspace|databricks|분석작업영역|데이터브릭스;group:iot-hub=iothub|devicehub|iot허브
group:realtime-messaging-service=signalrservice|signalr|realtimemessagingservice|실시간메시징서비스|시그널알;group:stream-analytics-job=streamanalyticsjob|streaminganalytics|스트림분석작업|스트림애널리틱스
group:diagnostic-settings=diagnosticsetting|진단설정
""",
    MentionDomain.OBJECT_TYPE: """
object:Incident=incident|인시던트|장애|사고;object:Resource=resource|azure리소스|리소스|자원|인벤토리
object:CausalHypothesis=causalhypothesis|hypothesis|인과가설|원인가설|가설;object:RecoveryPlan=recoveryplan|복구계획|회복계획
object:Change=change|변경|변경이력|변경사항;object:Rule=rule|탐지규칙|룰;object:Policy=policy|정책
object:Workflow=workflow|워크플로|워크플로우;object:Agent=agent|에이전트;object:Approval=approval|승인|승인요청
object:Budget=budget|예산;object:CostAnomaly=costanomaly|비용이상|비용이상징후;object:CapacityForecast=capacityforecast|용량예측
object:SizingRecommendation=sizingrecommendation|사이징권장|크기조정권장;object:Document=document|문서;object:Skill=skill|스킬
object:BackgroundTask=backgroundtask|백그라운드작업|백그라운드태스크;object:Decision=decision|의사결정|결정;object:Notification=notification|알림
object:DiagnosticFinding=diagnosticfinding|진단발견|진단결과;object:ConfigurationDriftFinding=configurationdriftfinding|구성드리프트|드리프트
object:CodeSecurityFinding=codesecurityfinding|코드보안발견|보안취약점;object:AccessGrant=accessgrant|접근권한부여|액세스권한
object:AccessGrantRequest=accessgrantrequest|접근권한요청|액세스요청;object:ActionOption=actionoption|액션옵션|대응옵션
object:ActionRun=actionrun|액션실행|작업실행이력;object:ActionType=actiontype|액션타입|작업유형
object:ArchitectureConstraint=architectureconstraint|아키텍처제약|설계제약;object:AuthorizationCapability=authorizationcapability|권한역량|인가기능
object:AuthorizationDecision=authorizationdecision|인가결정|권한결정;object:AuthorizationObservation=authorizationobservation|권한관찰|유효권한증적
object:AuthorizationPolicyAssignment=authorizationpolicyassignment|권한정책할당;object:AuthorizationRequirement=authorizationrequirement|권한요구사항
object:BenchmarkValidation=benchmarkvalidation|벤치마크검증;object:BriefingRun=briefingrun|브리핑실행;object:BriefingSubscription=briefingsubscription|브리핑구독
object:BusinessCapability=businesscapability|비즈니스역량;object:BusinessService=businessservice|비즈니스서비스
object:CapacityGraduationRecommendation=capacitygraduationrecommendation|용량졸업권장;object:ChangeSummary=changesummary|변경요약
object:ChangeWindow=changewindow|변경윈도우|변경허용시간;object:ConfigurationBaseline=configurationbaseline|구성베이스라인|기준구성
object:ConfigurationDriftCheck=configurationdriftcheck|구성드리프트검사|드리프트점검;object:ConfigurationDriftEvidence=configurationdriftevidence|구성드리프트증적
object:ControlObjective=controlobjective|통제목표|제어목표;object:Conversation=conversation|대화세션|대화;object:ConversationPolicy=conversationpolicy|대화정책
object:CostObjective=costobjective|비용목표;object:CostObservation=costobservation|비용관찰|비용측정;object:DecisionCase=decisioncase|의사결정케이스|결정사례
object:DiagnosticEvidence=diagnosticevidence|진단증적|진단근거;object:DiagnosticMechanism=diagnosticmechanism|진단메커니즘
object:Environment=environment|운영환경|배포환경;object:EquivalenceValidationReceipt=equivalencevalidationreceipt|동치검증증적
object:EvidenceArtifact=evidenceartifact|증적아티팩트|근거아티팩트;object:EvidenceConflict=evidenceconflict|증적충돌|근거충돌
object:ExecutionProfile=executionprofile|실행프로파일;object:ExpectedEffect=expectedeffect|기대효과|예상효과;object:Experiment=experiment|카오스실험|실험
object:Finding=finding|탐지결과|발견사항|파인딩;object:Forecast=forecast|위반예측|예측;object:Framework=framework|프레임워크
object:FrameworkControl=frameworkcontrol|프레임워크통제;object:HandoffEscalation=handoffescalation|핸드오프에스컬레이션|이관요청
object:ImpactEnvelope=impactenvelope|영향범위포락선|블라스트반경;object:Issue=issue|깃허브이슈|이슈;object:Observation=observation|관찰값|측정값
object:ObservedOutcome=observedoutcome|관찰된결과|실제효과;object:Ownership=ownership|소유권|담당자매핑;object:Pattern=pattern|패턴
object:PolicyArtifact=policyartifact|정책아티팩트;object:PostTurnReview=postturnreview|사후턴리뷰;object:Principal=principal|보안주체|프린시펄
object:Process=process|프로세스|워크플로실행;object:Property=property|속성정의|프로퍼티;object:ProspectiveLineage=prospectivelineage|사전계보
object:ProviderPermissionSet=providerpermissionset|프로바이더권한셋;object:PythonTask=pythontask|파이썬태스크
object:RecoveryObjective=recoveryobjective|복구목표|rto|rpo;object:ResourceClass=resourceclass|리소스클래스|리소스분류
object:ResourceType=resourcetype|리소스타입정의;object:ReviewCase=reviewcase|리뷰케이스|검토사례;object:ReviewCheck=reviewcheck|리뷰체크|검토항목
object:RuleCandidate=rulecandidate|규칙후보|룰후보;object:RuleObjectiveBinding=ruleobjectivebinding|규칙목표바인딩
object:SecurityEvent=securityevent|보안이벤트|보안신호;object:ServiceObjective=serviceobjective|서비스목표|slo
object:Signal=signal|이벤트신호|신호;object:SignalType=signaltype|신호타입|신호유형;object:Turn=turn|대화턴|턴
object:UserMemoryFact=usermemoryfact|사용자메모리|장기메모리;object:UserPreference=userpreference|사용자선호설정;object:VmTaskRun=vmtaskrun|vm작업실행
object:WorkflowBinding=workflowbinding|워크플로바인딩;object:WorkflowDefinition=workflowdefinition|워크플로정의;object:Workload=workload|워크로드
""",
    MentionDomain.STATE: """
state:stopped_or_deallocated=stop|stopped|stoppedstate|shut|shutdown|poweredoff|notrunning|down|inactive|offline|중지|중지된|중지됨|정지|정지된|정지됨|멈춘|멈춤|멈춰있는|꺼진|꺼짐|꺼져있는|내려간|죽은|죽어있는|비활성|가동중지|작동안하는
state:resource_state.stopped=allocatedstopped|할당유지중지
state:resource_state.deallocated=deallocated|deallocate|할당해제|할당해제된|할당해제됨
state:resource_state.running=running|runningstate|active|started|up|alive|실행중|실행중인|가동중|가동중인|동작중|동작중인|돌아가는|살아있는|켜진|켜져있는|활성|작동중인
state:resource_state.failed=failed|failedstate|failure|errorstate|broken|실패|실패한|실패됨|오류상태|에러난|장애난|고장난|문제있는|문제가있는|이상있는|이상이있는
state:resource_state.degraded=degraded|degradedstate|성능저하|성능이저하된|성능저하된|성능이저하|상태가저하된|성능떨어진|저하된|저하됨|저하|느려진
state:resource_state.unavailable=unavailable|unavailablestate|사용불가능|이용불가|사용불가|불능
state:resource_state.available=available|availablestate|사용가능|사용가능한|가용
state:resource_state.online=online|onlinestate|온라인
state:resource_state.paused=paused|pausedstate|일시중지|일시중지된|일시정지|일시정지된
state:resource_state.ready=ready|readystate|준비됨|준비된|준비
state:resource_state.succeeded=succeeded|succeededstate|성공|성공한|성공함
state:lifecycle:CausalHypothesis.status=candidate=candidate|candidatehypothesis|후보가설;state:lifecycle:CausalHypothesis.status=closed=hypothesisclosed|종료된가설
state:lifecycle:CausalHypothesis.status=supported=supported|지지됨|뒷받침됨;state:lifecycle:CausalHypothesis.status=refuted=refuted|기각됨|반박됨;state:lifecycle:CausalHypothesis.status=inconclusive=inconclusive|판정보류|미결
state:lifecycle:Incident.status=open=open|openincident|열린|열려있는|오픈|열린인시던트|오픈인시던트|진행중인인시던트;state:lifecycle:Incident.status=closed=incidentclosed|종료된인시던트|닫힌인시던트
state:lifecycle:Incident.status=triaging=triaging|분류중|트리아지|분석중;state:lifecycle:Incident.status=mitigated=mitigated|완화됨|완화된|완화;state:lifecycle:Incident.status=resolved=resolved|해결됨|해결된|해결
state:lifecycle:RecoveryPlan.status=draft=draft|초안;state:lifecycle:RecoveryPlan.status=escalated=escalated|에스컬레이션됨;state:lifecycle:RecoveryPlan.status=ready=recoveryplanready|준비된복구계획
state:lifecycle:RecoveryPlan.status=executing=executing|실행중인복구계획;state:lifecycle:RecoveryPlan.status=verifying=verifying|검증중;state:lifecycle:RecoveryPlan.status=failed=recoveryplanfailed|실패한복구계획
state:lifecycle:RecoveryPlan.status=recovered=recovered|복구완료|복구됨;state:lifecycle:RecoveryPlan.status=stale=stale|만료됨|오래됨
state:lifecycle:Process.status=pending=pending|대기중|보류중;state:lifecycle:Process.status=waiting=waiting|승인대기중;state:lifecycle:Process.status=running=processrunning|실행중인프로세스
state:lifecycle:Process.status=timed_out=timedout|타임아웃됨|시간초과됨;state:lifecycle:Process.status=cancelled=cancelled|canceled|취소됨|취소된
state:lifecycle:Process.status=compensating=compensating|보상중;state:lifecycle:Process.status=compensated=compensated|보상완료
state:lifecycle:Process.status=failed=processfailed|실패한프로세스;state:lifecycle:Process.status=succeeded=processsucceeded|성공한프로세스
""",
    MentionDomain.REGION: """
region:koreacentral=koreacentral|한국중부|서울리전|코리아센트럴;region:koreasouth=koreasouth|한국남부|부산리전|코리아사우스
region:eastus=eastus|미국동부|이스트유에스;region:eastus2=eastus2|미국동부2;region:eastus2euap=eastus2euap|미국동부2euap;region:eastusstg=eastusstg|미국동부stg
region:westus=westus|미국서부|웨스트유에스;region:westus2=westus2|미국서부2;region:westus3=westus3|미국서부3;region:westcentralus=westcentralus|미국서중부
region:centralus=centralus|미국중부|센트럴유에스;region:centraluseuap=centraluseuap|미국중부euap
region:northcentralus=northcentralus|미국북중부;region:southcentralus=southcentralus|미국남중부;region:southcentralusstg=southcentralusstg|미국남중부stg
region:japaneast=japaneast|일본동부|도쿄리전;region:japanwest=japanwest|일본서부|오사카리전
region:southeastasia=southeastasia|동남아시아|동남아|싱가포르리전;region:eastasia=eastasia|동아시아|홍콩리전
region:westeurope=westeurope|서유럽;region:northeurope=northeurope|북유럽;region:uksouth=uksouth|영국남부|런던리전;region:ukwest=ukwest|영국서부
region:swedencentral=swedencentral|스웨덴중부;region:australiaeast=australiaeast|호주동부;region:australiacentral=australiacentral|호주중부
region:australiacentral2=australiacentral2|호주중부2;region:australiasoutheast=australiasoutheast|호주남동부
region:germanywestcentral=germanywestcentral|독일서중부;region:germanynorth=germanynorth|독일북부
region:francecentral=francecentral|프랑스중부;region:francesouth=francesouth|프랑스남부
region:canadacentral=canadacentral|캐나다중부;region:canadaeast=canadaeast|캐나다동부
region:brazilsouth=brazilsouth|브라질남부;region:brazilsoutheast=brazilsoutheast|브라질남동부
region:centralindia=centralindia|인도중부;region:southindia=southindia|인도남부;region:westindia=westindia|인도서부
region:indiasouthcentral=indiasouthcentral|인도남중부;region:jioindiacentral=jioindiacentral|지오인도중부;region:jioindiawest=jioindiawest|지오인도서부
region:austriaeast=austriaeast|오스트리아동부;region:belgiumcentral=belgiumcentral|벨기에중부;region:chilecentral=chilecentral|칠레중부
region:denmarkeast=denmarkeast|덴마크동부;region:global=global|글로벌|전역;region:indonesiacentral=indonesiacentral|인도네시아중부
region:israelcentral=israelcentral|이스라엘중부;region:italynorth=italynorth|이탈리아북부;region:malaysiawest=malaysiawest|말레이시아서부
region:mexicocentral=mexicocentral|멕시코중부;region:newzealandnorth=newzealandnorth|뉴질랜드북부
region:norwayeast=norwayeast|노르웨이동부;region:norwaywest=norwaywest|노르웨이서부;region:polandcentral=polandcentral|폴란드중부
region:qatarcentral=qatarcentral|카타르중부;region:southafricanorth=southafricanorth|남아프리카북부;region:southafricawest=southafricawest|남아프리카서부
region:spaincentral=spaincentral|스페인중부;region:switzerlandnorth=switzerlandnorth|스위스북부;region:switzerlandwest=switzerlandwest|스위스서부
region:uaecentral=uaecentral|아랍에미리트중부|uae중부;region:uaenorth=uaenorth|아랍에미리트북부|uae북부
""",
    MentionDomain.METRIC: """
metric:resource.cpu.utilization_pct=cpuutilization|cpuusage|cpu|processorutilization|cpu사용률|cpu사용량|cpu점유율|프로세서사용률|시피유사용률|시피유;metric:resource.memory.usage_pct=memoryusage|memoryutilization|ramusage|메모리사용률|메모리사용량|메모리점유율|램사용률|메모리
metric:resource.memory.available_pct=availablememory|freememory|가용메모리|남은메모리|여유메모리|남은램;metric:resource.saturation=resourcesaturation|cpusaturation|리소스포화도|cpu포화도
metric:resource.activation.failure=activationfailure|containeractivationfailure|활성화실패|컨테이너활성화실패;metric:service.latency=servicelatency|responselatency|responsetime|서비스지연시간|응답지연시간|응답시간|응답속도|처리지연|레이턴시
metric:dependency.latency=dependencylatency|의존성지연시간|외부호출지연;metric:request.errors=requesterror|errorcount|servererror|요청오류|오류수|에러수|500에러
metric:request.timeout=requesttimeout|timeoutcount|요청타임아웃|시간초과요청|타임아웃수;metric:request.volume=requestvolume|requestcount|trafficvolume|요청량|트래픽양|트래픽볼륨|초당요청|요청수
metric:pod.restart.history=podrestart|podrestarthistory|restartcount|파드재시작|파드재시작횟수|파드재기동|컨테이너재시작|재시작이력;metric:deployment.change=deploymentchange|배포변경|배포이벤트
metric:network.change=networkchange|네트워크변경;metric:storage.write.success=storagewritesuccess|스토리지쓰기성공
metric:database.mysql.cpu.utilization_pct=mysqlcpu|mysqlcpuutilization|mysqlcpu사용률;metric:database.mysql.active_connections=mysqlactiveconnection|activeconnection|mysql활성연결|활성커넥션수|db커넥션수
metric:database.mysql.query.count=mysqlquerycount|mysql쿼리수;metric:database.mysql.slow_query.count=mysqlslowquery|slowquery|슬로우쿼리|슬로우쿼리개수|느린쿼리수
metric:api_gateway.request.count=apigatewayrequestcount|api게이트웨이요청수;metric:api_gateway.duration=apigatewayduration|api게이트웨이응답시간
metric:api_gateway.backend.duration=apigatewaybackendduration|api게이트웨이백엔드지연;metric:api_gateway.response.429.count=apigateway429|api게이트웨이429|429에러
metric:api_gateway.response.500.count=apigateway500|api게이트웨이500;metric:api_gateway.response.503.count=apigateway503|api게이트웨이503|503에러
metric:api_gateway.backend.response.429.count=apigatewaybackend429|백엔드429;metric:api_gateway.backend.response.500.count=apigatewaybackend500|백엔드500
metric:api_gateway.backend.response.503.count=apigatewaybackend503|백엔드503;metric:gateway.total_time=gatewaytotaltime|게이트웨이총소요시간
metric:gateway.response.5xx.count=gateway5xx|게이트웨이5xx;metric:gateway.backend.response.5xx.count=gatewaybackend5xx|게이트웨이백엔드5xx
metric:gateway.backend.connect_time=gatewaybackendconnecttime|백엔드연결시간;metric:gateway.backend.first_byte_time=gatewaybackendfirstbytetime|ttfb|첫바이트응답시간
metric:gateway.backend.last_byte_time=gatewaybackendlastbytetime|마지막바이트응답시간;metric:gateway.backend.healthy_host_count=healthyhostcount|정상백엔드호스트수
metric:gateway.backend.unhealthy_host_count=unhealthyhostcount|비정상백엔드호스트수;metric:model.request.count=modelrequestcount|llmrequestcount|모델요청수|llm호출수
metric:model.token.count=modeltokencount|tokenconsumption|tokenusage|토큰사용량|모델토큰수|llm토큰소모량;metric:model.time_to_response=modeltimetoresponse|모델응답시간
metric:model.time_to_last_byte=modeltimetolastbyte|모델마지막토큰시간;metric:model.response.200.count=modelresponse200|모델200응답수
metric:model.response.429.count=modelresponse429|모델429응답수|모델스로틀링|스로틀링횟수;metric:model.response.500.count=modelresponse500|모델500응답수;metric:model.response.503.count=modelresponse503|모델503응답수
""",
    MentionDomain.HEALTH: """
health:resource_health.degraded=degraded|resourcehealthdegraded|성능저하|성능이저하된|성능저하된|성능이저하|일부장애|저하상태;health:resource_health.not_ready=notready|resourcehealthnotready|준비안됨|미준비
health:resource_health.unavailable=unavailable|resourcehealthunavailable|사용불가|서비스불가|다운상태;health:resource_health.unhealthy=unhealthy|resourcehealthunhealthy|비정상|불건전|문제있는|문제가있는|문제생긴|이상있는|이상이있는|장애있는|장애가있는|불량|불량인|건강하지않은|언헬시
""",
    MentionDomain.PROPERTY: """
property:Resource.location=location|region|리전|위치|지역;property:Resource.type=type|resourcetype|리소스유형|리소스타입|종류
property:capacity.instance.count=instancecount|capacityinstancecount|인스턴스수|인스턴스개수;property:governance.resource.tags=tags|resourcetags|requiredtag|태그|리소스테그|필수태그
property:governance.rbac.role_assignments=roleassignments|rbacroleassignments|역할할당속성;property:identity.managed.type=managedidentitytype|identitytype|관리형id유형
property:lifecycle.secret.age=secretage|agedays|시크릿수명|비밀경과일;property:observability.diagnostic.settings=diagnosticsettings|진단설정여부
property:resilience.availability.zones=availabilityzones|zones|az|가용성영역;property:resilience.database.geo_backup.enabled=geobackup|georedundantbackup|지역중복백업|지오백업
property:resilience.database.ha.mode=hamode|highavailabilitymode|고가용성모드|ha모드;property:resilience.database.zone_redundant.enabled=zoneredundant|영역중복
property:resilience.secret_store.purge_protection.enabled=purgeprotection|영구삭제보호|퍼지보호;property:resilience.secret_store.soft_delete.enabled=secretsoftdelete|키볼트소프트딜리트|일시삭제보호
property:resilience.snapshot.policy.present=snapshotpolicy|스냅샷정책;property:resilience.storage.soft_delete.enabled=blobsoftdelete|storagesoftdelete|블롭소프트딜리트
property:resilience.storage.versioning.enabled=blobversioning|storageversioning|블롭버전관리|버저닝;property:retention.backup.days=backupretention|backupretentiondays|백업보존일수|백업보관기간
property:retention.log.days=logretention|retentiondays|로그보존일수|로그보관기간;property:runtime.vm.power_state=powerstate|vmpowerstate|전원상태|파워스테이트
property:security.database.audit.enabled=databaseaudit|auditenabled|데이터베이스감사|db감사;property:security.database.encryption_at_rest.enabled=encryptionatrest|tde|tdeenabled|저장데이터암호화
property:security.database.ssl.enforcement=sslenforcement|tls강제|ssl강제;property:security.kubernetes.azure_rbac.enabled=azurerbacenabled|aksrbac|쿠버네티스rbac
property:security.kubernetes.network_policy.enabled=kubernetesnetworkpolicy|쿠버네티스네트워크정책설정;property:security.kubernetes.private_cluster.enabled=privatecluster|privateclusterenabled|프라이빗클러스터여부
property:security.network.ddos.plan.id=ddosprotectionplanid|ddos계획연결;property:security.network.inbound_rules=inboundsecurityrules|inboundrules|인바운드보안규칙|인바운드룰
property:security.network.private_endpoints=privateendpoints|프라이빗엔드포인트연결;property:security.network.public_access=publicaccess|공용액세스
property:security.network.public_ip.sku_tier=publicipskutier|skutier|공인ipsku;property:security.network.public_network_access.enabled=publicnetworkaccess|publicnetworkaccessenabled|공용네트워크접근|퍼블릭네트워크액세스
property:security.network.rules=securityrules|networkrules|보안규칙;property:security.secret_store.rbac.enabled=keyvaultrbac|rbacauthorizationenabled|키볼트rbac
property:security.storage.https_only.enabled=httpsonly|enablehttpstrafficonly|https전용;property:security.storage.infrastructure_encryption.enabled=infrastructureencryption|인프라암호화
property:security.storage.shared_key.enabled=sharedkeyaccess|allowsharedkeyaccess|공유키액세스;property:security.transport.minimum_tls=minimumtls|mintlsversion|최소tls버전|tls버전
property:topology.resource.association.id=associatedresourceid|managedby|연결된리소스id;property:utilization.cache.hit_rate=cachehitrate|hitrate|캐시적중률
property:utilization.cache.server_load.p95=cacheserverloadp95|serverloadp95|캐시서버부하p95;property:utilization.cpu.p95=cpup95|cpup95percent|95백분위수cpu
property:utilization.database.dtu.p95=dtup95|dtup95percent|dtu사용률;property:utilization.memory.p95=memoryp95|memoryp95percent|메모리p95;property:utilization.network.p95=networkp95|networkp95bytes|네트워크p95
property:control_plane.event.terminal=controlplaneeventterminal|이벤트종단여부;property:control_plane.event.type=controlplaneeventtype|이벤트유형;property:control_plane.request.kind=controlplanerequestkind|요청종류
""",
    MentionDomain.DECLARATION_KIND: """
kind:action=action|actiondeclaration|액션선언|작업선언;kind:function=function|functiondeclaration|함수선언|쿼리함수선언
kind:interface=interface|interfacedeclaration|인터페이스선언;kind:link=link|linkdeclaration|링크선언|관계선언;kind:object=object|objectdeclaration|오브젝트선언|객체선언
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


def _jamo_seq(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            cho = offset // 588
            jung = (offset % 588) // 28
            jong = offset % 28
            if jung == 1:
                jung = 5
            elif jung == 3:
                jung = 7
            out.append(f"c{cho:02d}v{jung:02d}b{jong:02d}")
        else:
            out.append(ch)
    return "".join(out)


def _one_edit_distance(a: str, b: str) -> bool:
    has_ko = any("가" <= ch <= "힣" for ch in a)
    min_len = 3 if has_ko else 5
    if len(a) < min_len or len(b) < min_len or a[0] != b[0] or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        if (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        ):
            return True
        if has_ko and len(diffs) == 1:
            return _jamo_seq(a) == _jamo_seq(b)
        return False
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
        for entry in block.replace("\n", ";").split(";"):
            entry = entry.strip()
            if not entry:
                continue
            candidate_id, _, terms_spec = entry.rpartition("=")
            cid = candidate_id.strip()
            for term in terms_spec.split("|"):
                norm = _normalize_concept_term(term)
                if norm:
                    index[norm] = cid
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
