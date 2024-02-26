### SELinux (Redhat8.0 ~ 9.0)

#### SELinux 개념

> SELinux 비활성화 : selinux=0 커널 매개변수(Linux9부터 적용)
이전 버전에서는 /etc/selinux/config > SELINUX=disabled 설정

`unconfined_u:object_r:httpd_sys_content_t:s0/var/www/html/file2`

SELinux User : Role : Type : Level : File

> 유형 컨텍스트의 이름은 대개 \_t로 끝남
리소스를 나열하느 대부분의 명령은 -Z옵션을 사용하여 컨텍스트 관리

파일을 새 위치에 복사 시 해당파일의 SELinux 컨텍스트가 **새 위치의 레이블 지정 정책 또는 상위 디렉토리 상속(정책이 없는 경우)** 으로 결정된 새 컨텍스트로 변경될 수 있음

`cp -p` 명령 : 복사하기 전 모든 파일 특성을 유지
`cp -c` 명령 : 복사하는 동안 SELinux 컨텍스트만 유지

> 파일을 같은 파일시스템 내에서 이동하는 경우에는 기존의 selinux context가 그대로 유지

#### 컨텍스트 변경 

1. `chcon` 명령으로 디렉토리 파일 컨텍스트 유형 변경
2. `restorecon` 명령으로 정책에 지정된 컨텍스트를 파일에 적용
3. `semanage fcontext` 명령으로 기본 파일 컨테스트를 결정하는 정책 표시 및 수정

> SELinux 컨텍스트 관리를 위해 policycoreutils, policycoreutils-python-utils 패키지 사용

- `semanage fcontext -l` 로 설정된 올바른 정책을 찾고 의도한 파일 컨텍스트에 있는지 확인
- `semanage fcontext -a -t httpd_sys_content_t '/virtual(/.*)?` virtual 디렉토리 하위 모든 파일에 httpd_sys_content_t 컨텍스트 지정
- `restorecon -RFvv /virtual` 디렉토리 및 디렉토리 내의 모든 파일에 기본 컨텍스트 설정

※ 기본 정책에 대한 로컬 사용자 지정 확인 `semanage fcontext -l -c`

#### SELinux 위반 모니터링

SELinux 작업 거부 → /var/log/audit/audit.log 보안로그 파일에 AVC 메세지 기록

→ AVC 이벤트 모니터링 → /var/log/messages로 이벤트 요약 전송
* * *
특정 이벤트에 대한 포괄적인 보고서 세부 정보확인 `sealert -l UUID`
> 해당 UUID는 /var/log/messages에 요약된 정보에서 확인 할 수 있다.

기존 이벤트 모두 확인 `sealert -a /var/log/audit/audit.log`

#### 보안관리 시나리오

상황 : apache 서비스에서 웹 콘텐츠 제공 불가 

오류메세지 : 웹페이지 접속 시 you do not have permission to access this resource. 오류메세지 출력

1. `/var/log/messages` 내용 확인 → 해당 오류 내용에 대한 UUID 검색
2. `sealert -l <UUID>` 내용 확인 → '... preventing /usr/sbin/httpd from getattr access on file <>.html'
3. `ausearch -m AVC -ts recent` → scontext = system\_r:httpd\_t:s0 / tcontext = unconfine\_u:object\_r:default\_t:s0
4. `ls -dZ` 오류가 발생하는 디렉토리와 하위 파일 context 확인
5. `semange fcontext -a -t httpd_sys_content_t '/디렉토리명(/.*)?`으로 컨텍스트 규칙 생성
6. `restorecon -R /디렉토리명/`설정한 컨텍스트 규칙명으로 파일 컨텍스트 정책 수정










