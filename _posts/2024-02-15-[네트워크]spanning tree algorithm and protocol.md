
## 스위치와 브릿지 사이 looping을 방지해주는 spanning tree protocol

#### 스위치나 브릿지를 이용하여 네트워크를 구성할 때 fault torelance를 고려하여 스위치와 스위치 사이 또는 브릿지와 브릿지 사이에 이중 경로를 연결하여 사용할 수 있다. 이때, 하나의 서버에서 다른 서버로 연결되는 네트워크 경로가 두 개 이상으로 만들어져 있는 경우 looping 현상이 발생한다.

<p align="center">
  <img src="https://github.com/secbullet2359/milliontime/tree/master/image/networklooping1.png">
</p>

위 사진은 looping이 이루어지는 과정을 요약한 것이다. CSMA/CD의 특징에 따라 **하나의 네트워크 segment에서는 packet전송은 한 번에 하나만 이용**할 수 있다는 허브의 단점을 개선하기 위해 여러 network segment를 분리할 수 있는 스위치나 브릿지를 이용하여 네트워크를 구성할 수 있지만 앞서서 얘기한 것과 같이 하나의 서버에서 다른 서버로 갈 수 있는 이중 경로가 존재하는 경우 looping이 발생한다.

##### looping이 발생하는 순차적인 단계

1. 서버에서 전달된 broadcast packet을 연결된 양쪽 스위치(또는 브릿지)가 인식(이때 broadcast packet은 다른 segemnt에 있는 서버가 목적지이기 때문에 flooding을 발생)

2. 각 스위치에서 다른 쪽 segemnt로 broadcast packet을 전송 

3. A스위치에서 전달된 broadcast packet이 목적지 서버 뿐만 아니라 B스위치에도 전달됨에 따라 **B스위치에서 다시 반대쪽 segemnt로 broadcast packet를 전송** (B에서 A로도 동일)

4. A에서 B로 다시 B에서 A로 무한히 도는 looping이 발생

위 상황이 발생하게 되면 무한히 발생되는 packet전송에 의해 각 segemnt내에서도 CSMA/CD의 특성에 따라 같은 segment내의 서버들 간 네트워크 통신이 매우 느려지거나 더 이상 통신이 이루어지지 않는 상황이 발생한다.

<p align="center">
  <img src="https://github.com/secbullet2359/milliontime/tree/master/image/networklooping2.png">
</p>

위 사진과 같이 네트워크를 구성하여도 마찬가지이다. 


