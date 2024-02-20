
### spanning tree protocol의 Hardware 동작

##### STP protocol은 physical redundancy(안정성을 위한 이중화 및 추가 자원할당)를 구성하였을 때 L1 영역에서 Mac address instability, Broadcast storm, Duplicate unicast frame 같은 redundant issue가 발생할 때 사용한다. STP는 RSTP(Rapid STP), MSTP(Multiple STP)의 확장 프로토콜이 존재한다.

STP는 L2 data link layer에 사용되는 protocol로 L1 physical layer에서의 redundant 구성을 안정화(looping 방지) 시켜주는 목표로 사용이 된다. L3 Layer에서는 TTL(time to live) field 정보가 packet header에 추가되기 때문에 목적지에 도달하지 못하고 네트워크 상에서 자원을 소모하며 계속 전달되는 packet들을 버리기 때문에 looping을 방지하는 역할을 수행할 수 있다. 하지만 L3 하위 layer에서는 TTL 정보가 포함되지 않기 때문에 STP protocol로 looping을 방지해 주어야 한다.

#### Mac address instability, Broadcast storming

L2 스위치와 같은 하위 layer 장비에서는 ARP table이 아닌 MAC address table로 통신해야 될 서버들을 관리한다. 

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/OSI_l2_frame_structure.png">
  <figcaption align="center">L2 frame의 구조</figcaption>
</p>

> ARP table은 L3 - L2간 정보인 ip와 mac address를 연결한다. 반면 MAC address table은 L2 - L1사이 정보를 연결하기 때문에 Mac address정보와 하드웨어 포트의 interface 정보를 서로 연결하여 관리한다.

broadcast된 정보들이 계속하여 looping이 발생되면 매번 다른 interface에서 Mac address를 받게 된다. 이 때문에 지속적으로 Mac address table이 업데이트가 되어 Mac address table이 불안정해지게 된다. 이 looping에 포함되는 서버들은 목적지를 계속 찾지 못하기 때문에 broacast storming을 일으키는 원인이 된다.

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/MACaddressTableInconsistencies.png">
  <figcaption align="center">https://www.oreilly.com/ MAC address table inconsistencies</figcaption>
</p>

>switch A에서 지속적으로 frame을 받게 될 때 위와 같이 looping 구조에서는 다른 스위치 B와 C에서 똑같이 broadcast propagation이 발생하므로 마치 요청 서버가 SwitchB와 switchC에 연결된 Fa0/2, Fa0/3 interface와 연결된 것과 Mac address table이 업데이트가 되게 된다.

braodcast storming이 발생하면 legitimate traffic을 보내기 위한 유휴자원(bandwith)을 모두 사용해버리기 때문에 DoS(Denial of Service)의 원인이 된다. 

#### Duplicat unicast frame

Mac address table의 불안정은 목적지를 알고 unicast를 보내는 서버들에도 영향을 미치게 된다. 연결된 Mac address와 interface의 연결이 계속 변경되기 때문에 unicast frame을 보내게 되면 제대로 목적지까지 도달할 수 없게 된다. 결과적으로 다시 목적지를 확인하기 위해 broacast frame을 네트워크 상에 뿌리게 되어 새로운 looping이 만들어지는 악순환이 반복된다.

### STP, MSTP, RSTP

ST algorithm을 통해 확인하였듯이 STP는 스위치 사이 cycle을 만드는 port를 비활성화 시키고 Minimum Spannig Tree를 만드는 역할을 수행한다. 이때 네트워크에서 각 스위치의 정보와 연결 정보들을 지속적으로 파악해야 ST를 구성할 수 있는데 이 정보를 알아내기 위해 스위치 간 전파되는 frame을 BPDU(Bridge Protocol Data Unit)이라고 부른다.

1. Configuration BPDU : Switch 및 Port의 역할을 결정(init) → root switch에서 2초마다 전파
2. TCN(Topology Change Notification) BPDU : 스위치 네트워크가 변경되었을 때 내용을 전파하기 위해 사용

BPDU가 전파되었을 때 switch에서는 다음과 같은 방식으로 STP를 따른다.

1. Root switch 선출








