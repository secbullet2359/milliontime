---
title: spanning tree protocol
categories:
- 네트워크
---
### spanning tree protocol

##### 스위치나 브릿지를 이용하여 네트워크를 구성할 때 fault torelance를 고려하여 스위치와 스위치 사이 또는 브릿지와 브릿지 사이에 이중 경로를 연결하여 사용할 수 있다. 이때, 하나의 서버에서 다른 서버로 연결되는 네트워크 경로가 두 개 이상으로 만들어져 있는 경우 looping 현상이 발생한다.

* * *

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/networklooping1.png">
</p>
(사진 출처를 깜빡했다.. 퀄높은 그림을 제공하는 많은 분들께 무한한 감사를 드린다.)

위 사진은 looping이 이루어지는 과정을 요약한 것이다. CSMA/CD의 특징에 따라 **하나의 네트워크 segment에서는 packet전송은 한 번에 하나만 이용**할 수 있다는 허브의 단점을 개선하기 위해 여러 network segment를 분리할 수 있는 스위치나 브릿지를 이용하여 네트워크를 구성할 수 있지만 앞서서 얘기한 것과 같이 하나의 서버에서 다른 서버로 갈 수 있는 이중 경로가 존재하는 경우 looping이 발생한다.

--- looping이 발생하는 순차적인 단계 ---

1. 서버에서 전달된 broadcast packet을 연결된 양쪽 스위치(또는 브릿지)가 인식(이때 broadcast packet은 다른 segemnt에 있는 서버가 목적지이기 때문에 flooding을 발생)

2. 각 스위치에서 다른 쪽 segemnt로 broadcast packet을 전송 

3. A스위치에서 전달된 broadcast packet이 목적지 서버 뿐만 아니라 B스위치에도 전달됨에 따라 **B스위치에서 다시 반대쪽 segemnt로 broadcast packet를 전송** (B에서 A로도 동일)

4. A에서 B로 다시 B에서 A로 무한히 도는 looping이 발생

위 상황이 발생하게 되면 무한히 발생되는 packet전송에 의해 각 segemnt내에서도 CSMA/CD의 특성에 따라 같은 segment내의 서버들 간 네트워크 통신이 매우 느려지거나 더 이상 통신이 이루어지지 않는 상황이 발생한다.

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/networklooping2.png">
</p>

위 사진과 같이 네트워크를 구성하여도 마찬가지이다. 

sw1 - sw2 - sw3 가 하나의 cycle을 구성하고 있기 때문에 어떤 segemnt에서 출발하여도 다른 segment에 있는 서버로 무조건 2개의 경로를 가지게 된다. 이러한 looping을 해결하기 위한 protocol이 STP(spanning tree protocol)이다. 

* * *

### Spanning Tree algorithm

STP에 대해 자세히 살펴보기 전에 Spanning Tree Algorithm에 대해 먼저 살펴보겠다.

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/sta1.png">
  <figcaption align="center">no cylcle, include all node</figcaption>
</p>

https://4legs-study.tistory.com/111

Spanning Tree는 그래프의 최소 연결 부분 그래프로 빨간선으로 이루어진 그래프를 의미한다.

looping이 발생하는 이유는 결과적으로 그래프의 노드간 cycle이 만들어지게 되면 이중 경로가 형성되기 때문이므로, 여러 개의 스위치나 브릿지로 이루어진 네트워크에서 cylce을 구성하지 않는 경로 그래프 즉 Spanning Tree를 만들 수 있다면 이러한 looping의 발생을 방지할 수 있다.

그렇다면 spanning tree를 어떤 방식으로 생성해야할까? 라는 의문이 생긴다. 만약 특정 segment에 있는 서버들이 사용자가 많은 서비스를 제공하고 있다면 굉장히 많은 트래픽이 발생할 것이다. 빠르게 최종 목적지까지 packet을 전송하기 위해서는 이러한 segemnt로 broadcast를 하는 것보다 여유로운 segment를 통하는 것이 더 유리하다. 따라서 이러한 부하를 간선의 가중치로 하는 MST(Minimum Spanning Tree)를 구성하는 것이 필요하다.

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/sta2.png">
  <figcaption align="center">no cylcle, include all node</figcaption>
</p>

MST를 구하는 알고리즘은 Kruskal, Prim이 존재하는데 간단하게 두 알고리즘의 pseudo code만 첨부한다.

- Kruscal Algorithm : 여러 집합을 합쳐가며 Tree를 만드는 방식

```
Kruskal(G)
// G = (V, E) : Given Graph
// T = Spanning Tree
{
	T = empty_set();
    for(v ∈ V)
    	make_set(v); // 처음에는 하나의 vertices가 하나의 집합을 구성
       
    A[1...|E|] = sort_by_weight(E); // sort by ascending order
    
    while(|T| < n-1){
    	(u, v) = pop(A); // u,v = Vertices that compose the edge (u, v)
        if(find_set(u) ∩ find_set(v) == empty_set()) { // u and v are disjoint
        	T = T ∪ {(u,v)}; // edge에 포함되어 있는 Vertices를 spannig tree에 추가
            find_set(u) ∪ find_set(v); // u와 v가 포함되어 있는 set를 서로 합침
		}
    }
}
```

> Kruscal의 핵심은 반복적으로 집합을 만드는 과정을 수행할 때 **하나의 집합에 포함되는 두개의 Vertices를 선택하지 않는다는 것(Union-Find 알고리즘)에 있다.** 

<p align="center">
  <img src="https://secbullet2359.github.io/milliontime/image/sta3.png">
</p>

> 위 그림은 Kruscal Algorithm을 수행하는 일부분을 가져온 것이다. e 단계에서 이미 3개의 집합이 구성되어 있는 것을 확인할 수 있다.(회색으로 묶여진 Vertices가 하나의 집합, 가장 먼저 추가된 vertices를 root로 설정하여 같은 root를 가지면 같은 집합에 존재하는 Vertices로 인식) f 단계에서 가장 하단 집합에 속해있는 두개의 Vertices를 선택하려 할 때 cycle이 만들어지기 때문에 집합에 추가하지 않고 넘어간다.

- Prim Algorithm : 하나의 Vertices에서 집합을 늘려나가며 Tree를 만드는 방식

```
Prim(G,r)
// G = (V,E) : Given Graph
// r : Starting Vertex
// S : Set of Vertex in Minimum Spanning Tree
// L(u) : Set for Adjacency Vertices of Vertex 'u'
// d[v] : Minimum Cost to connect with Vertex 'v' and Spanning Tree
// w(a, b) : Cost of Edge from Vertex 'a' to Vertex 'b'
{
	S = emptySet();
    for(u ∈ V)
    	d[u] = INT_MAX;
    
    d[r] = 0;
    
    while(S != V) {
    	u = extractMin(V-S, d); // 집합에 인접해있는 Vertice 중 최소 edge를 갖는 Vertice를 찾음
        S = S ∪ {u};
        
        for(v ∈ L(u)) // 집합에 포함한 u와 V-S에 존재하는 v간 edge정보로 d[v] 갱신
        	if(v ∈ V-S && w(u, v) < d[v]) {
            	d[v] = w(u, v);
                tree[v] = u;
            }
    }
}

extractMin(Q, d[])
{
	// 집합 Q에서 d값이 가장 작은 정점 u를 리턴
}
```

> Prim Algorithm의 핵심은 **하나의 집합에 다른 Vertices를 계속해서 포함해나가는 방식**의 알고리즘이다. 
Prim Algorithm의 구현은 2가지 방식으로 가능한데 하나는 Spanning Tree의 집합인 S와 S에 포함되어 있지 않은 Vertices 집합V-S의 두개의 관점에서 구현이 가능하다.
