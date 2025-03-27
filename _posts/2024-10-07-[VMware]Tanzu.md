---
categories:
  - VMWARE
---

### vmware Tanzu

##### Tanzu는 vmware의 vSphere를 하이퍼바이저 계층에서 kubernetes 워크로드를 실행하는 플랫폼으로 변환하는 역할을 수행할 수 있다.

* * *

### 현 어플리케이션 현황

보통 다수의 kubernetes 포드 및 VM을 실행하는 여러 마이크로서비스로 구성
Tanzu 기반이 아닌 kubernetes를 vm에 설치하여 배포라는 일반적인 스택은 3가지 별개의 역할로 구분된다.
- kubernetes 워크로드
- kubernetes 클러스터
- 가상환경

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/vmware/VMWARE_current_app_stack.png">
</p>

서로 다른 역할들은 서로의 환경을 확인하거나 제어 할 수 없기 때문에 전체 스택에 대한 작업이 어려울 수 있다.
예를 들어 kubernetes의 스케줄러가 VCenter Server 인벤토리에 대한 접근 방법이 없기 때문에 포드를 지능적으로 배치할 수 없다.

* * *

### vSphere Tanzu 사용 이점

Tanzu는 하이퍼바이저 계증에서 직접 kubernetes의 제어부를 생성한다.
이에 따라, kubernetes workload 관리를 기존 vSphere 클러스터를 사용하도록 설정하므로 ESXi 호스트 내부에 kubernetes 계층이 생성된다.
결과적으로 워크로드와 클러스터의 역할을 하나로 관리할 수 있으며 이렇게 설정된 클러스터를 supervisor cluster(감독자 클러스터) 라고 부른다.

vSphere Namespace을 통해 메모리, CPU 및 스토리지 용량을 구성
vSphere pod를 Namespace내 공유 리소스 풀을 사용하여 배포
Tanzu Kubernetes Grid 서비스를 이용하여 Kubernetes 클러스터 생성관리(수명주기) 
 ※ 이때 생성된 클러스터를 Tanzu kubernetes cluster라고 부름
vSphere 관리자는 Tanzu를 통해 생성된 모든 항목에 대한 확인 가능

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/vmware/VMWARE_vsphere_with_tanzu.png">
</p>

*Supervisor Cluster Architecture*
<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/vmware/VMWARE_supervisor_cluster_arch.png">
</p>

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/vmware/VMWARE_supervisor_cluster_arch(2).png">
</p>

vSphere DRS : ESXi 호스트에서 제어부 VM의 정확한 배치를 결정하고 필요할 때 마이그레이션하는 역할을 수행
VM kubernetes의 스케줄러와도 통합되어 vSphere pod의 배치를 결정
