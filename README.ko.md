# 두루 (Duru)

로컬 파일, Google Drive 문서, Slack 메시지에 작은 URI 기반 Python 인터페이스로
접근하는 라이브러리입니다. 공통 제공자 계약을 구현하고, 저장소가 지원하는
기능만 선택해서 추가할 수 있습니다.

[English](README.md) · **한국어**

## 개발 상태

현재 개발 중이며 Python 3.12 이상이 필요합니다. 패키지와 import 이름은
`duru`이며 [BSD 3-Clause 라이선스](LICENSE)를 사용합니다.

런타임 의존성은 없습니다. 자격 증명과 설정은 애플리케이션이 명시적으로
전달하며, 특정 프레임워크 없이 독립적으로 사용할 수 있습니다.

## 설치

PyPI에서 설치합니다.

```sh
python -m pip install duru
```

로컬 체크아웃에서는 `python -m pip install .`로 설치할 수 있습니다.

## 빠른 시작

예제에서 임시 디렉터리와 샘플 파일을 직접 만듭니다. 변경 작업은 모두 해당
디렉터리 안에서만 이루어집니다.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from duru import LocalProvider, Registry

with TemporaryDirectory() as directory:
    root = Path(directory) / "documents"
    root.mkdir()
    (root / "guide.md").write_text("Hello, resources!", encoding="utf-8")

    provider = LocalProvider(root)
    registry = Registry()
    registry.register("local", provider)

    uri = provider.uri("guide.md")
    selected = registry.resolve(uri)
    info = selected.stat(uri)
    with selected.open(uri, expected_revision=info.revision) as content:
        print(info.name, content.read().decode("utf-8"))

    updated = provider.write(uri, b"Updated guide", expected_revision=info.revision)
    renamed = provider.rename(updated.uri, "manual.md")
    print(renamed.name)
```

실행 결과는 다음과 같습니다.

```text
guide.md Hello, resources!
manual.md
```

변경 후에는 반환된 URI로 다음 작업을 호출합니다. URI는 자원의 식별자이고,
표시 이름은 별도 값입니다. 두 값의 관계는 각 제공자가 정의합니다.
레지스트리는 URI 스킴에 맞는 제공자만 선택합니다.

## 제공자와 지원 기능

| 제공자 | 읽기·메타데이터 조회·목록 | 변경 작업 |
| --- | --- | --- |
| `ReadOnlyLocalProvider` | 지원 | 없음 |
| `LocalProvider` | 지원 | 파일 생성·쓰기·이름 변경·이동·삭제 |
| `GoogleDriveProvider` | 지원 | 없음 |
| `SlackProvider` | 지원 | 없음 |

토큰과 자원 ID는 애플리케이션에서 전달합니다. 제공자는 프레임워크 설정을
읽거나 자격 증명을 자동 탐색하지 않으며, OAuth 토큰 발급·갱신도 수행하지 않습니다.

```python
from duru import GoogleDriveProvider, SlackProvider

def configure_providers(drive_token, folder_id, slack_token, workspace_id, channel_id):
    drive = GoogleDriveProvider(
        access_token=drive_token,
        account_id="work",
        folder_id=folder_id,
        export_formats={"application/vnd.google-apps.document": "text/plain"},
    )
    slack = SlackProvider(
        token=slack_token,
        workspace_id=workspace_id,
        channel_ids=(channel_id,),
    )
    return drive, slack
```

Google Drive의 자체 문서 형식은 내보내기 형식을 명시해야 합니다. Slack
메시지는 JSON 자원으로 반환됩니다. 폴더와 채널 ID 설정은 탐색 시작 위치이며
접근권한 경계가 아닙니다. URI 규칙, 페이지네이션, API 비용, 전송 제한과 원본
문서 링크는 [제공자 안내](src/duru/providers/README.md)를 참고하세요.

## 계약 확장

`Provider`를 상속하고 `identity`, `stat(uri)`,
`open(uri, expected_revision=...)`를 구현합니다. 메타데이터는 `ResourceInfo`,
내용은 호출자가 소유하는 바이너리 스트림으로 반환합니다. 호출자가 스트림을
닫아야 하며, `with` 사용을 권장합니다.

버전을 지정한 열기는 실제 반환 바이트가 요청한 버전과 일치하는지 검증하거나
작업을 거부해야 합니다. 메타데이터만 확인한 뒤 내용이 바뀔 수 있는 미검증
스트림을 반환해서는 안 됩니다. 자원 식별과 버전의 의미도 제공자가 명시합니다.

추가 추상 클래스는 실제 지원하는 기능에 한해서 상속합니다.

| 계약 | 작업 |
| --- | --- |
| `Listable` | `list(uri, cursor=None, limit=100) -> Page` |
| `Writable` | `write(uri, content, expected_revision=None)` |
| `ConditionalWritable` | 협력하는 클라이언트 사이의 버전 확인 후 교체 |
| `Creatable` | `create(parent_uri, name, content)` |
| `Renamable` | `rename(uri, name)` |
| `Movable` | `move(uri, destination_uri)`로 상위 컬렉션에 이동 |
| `Removable` | `delete(uri)` |

`capabilities(provider)`는 구현한 계약을 알려주며, 접근권한을 판단하지 않습니다.
미지원 작업은 명시적으로 실패합니다. 자원을 반환하는 변경 작업은 변경 후의
URI와 표시 이름을 제공합니다. 제공자 간 이동은 지원하지 않으며, 원자적이지
않은 복사 후 삭제로 대신하지 않습니다.

예를 들어, 변경되지 않는 문서 하나를 제공하는 읽기 전용 제공자를 등록할 수 있습니다.

```python
import hashlib
import io

from duru import Conflict, NotFound, Provider, Registry, ResourceInfo

class GuideProvider(Provider):
    identity = "guide-demo:v1"
    uri = "guide://manual"
    content = b"A document supplied by your application."

    def stat(self, uri):
        if uri != self.uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        return ResourceInfo(
            uri, "manual.txt",
            revision=hashlib.sha256(snapshot).hexdigest(),
            size=len(snapshot),
        )

    def open(self, uri, *, expected_revision=None):
        if uri != self.uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        revision = hashlib.sha256(snapshot).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise Conflict("Guide revision changed")
        return io.BufferedReader(io.BytesIO(snapshot))

registry = Registry()
registry.register("guide", GuideProvider())
provider = registry.resolve("guide://manual")
info = provider.stat("guide://manual")
with provider.open(info.uri, expected_revision=info.revision) as content:
    print(content.read().decode("utf-8"))
```

## 일관성과 제한

- 목록 커서는 내부를 해석하지 않는 컬렉션별 값입니다. 목록은 스냅샷이 아니며,
  항목이 보이지 않는다는 사실만으로 삭제되었다고 판단할 수 없습니다.
- 제공자 오류의 공통 부모는 `ResourceError`입니다. `NotFound`는
  `FileNotFoundError`, `AccessDenied`는 `PermissionError`도 상속합니다.
  `AuthenticationRequired`, `Conflict`, `UnsupportedOperation`으로 다른 실패를
  구분합니다. 일반적인 스트림 입출력 오류는 원래 입출력 예외 형식을 유지합니다.
- `EffectUnknown`은 변경이 이미 적용되었을 수 있다는 뜻입니다. 재시도하기 전에
  자원 상태를 확인하고 조정해야 합니다. 예외 발생만으로 롤백을 가정할 수 없습니다.
- 로컬 버전은 SHA256 해시입니다. 파일 전체를 읽기 전용 스냅샷으로 버퍼링하므로
  파일 크기에 비례해 메모리를 사용합니다. 내용 변경에는 `open`으로 얻은 스트림
  대신 `write`를 사용합니다.
- Linux에서는 절대 경로의 각 디렉터리를 심볼릭 링크를 따르지 않는 디스크립터로
  열고, 심볼릭 링크와 일반 파일이 아닌 내용을 거부합니다. 쓰기는 임시 파일에
  내용을 모두 기록한 뒤 원자적으로 게시하며, 변경 후 영속성 확인에 실패하면
  `EffectUnknown`을 반환합니다. 잠금은 협력하는 제공자끼리만 조정하고, 외부 OS
  쓰기 작업까지 조정하지 않습니다. Windows는 검사된 경로를 사용하지만 동시
  디렉터리 교체에 대한 동일한 보호를 제공하지 않습니다. 보안을 강화한 배포
  대상은 Linux입니다.
- 로컬 컬렉션 변경은 지원하지 않습니다. 로컬 URI는 경로에서 유도되므로 이름
  변경이나 이동 후 달라질 수 있습니다. `.framework-state`와 `.framework-write-`
  예약 이름은 목록에서 제외합니다.

스케줄, 영속 체크포인트, 재시도 정책, 문서 권한, 파싱과 인덱싱은 사용하는
애플리케이션의 책임입니다. 실시간 파일 감시, 복사, 디렉터리 생성, 잠금 API,
POSIX 속성과 네트워크 마운트 프로토콜은 공통 인터페이스 범위에 포함하지 않습니다.

## 개발

이 체크아웃에서 개발 도구를 설치하고 검사합니다.

```sh
python -m pip install -e '.[test]'
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

제공자 교체, 이름과 URI, 버전 확인 스냅샷, 커서 범위, 변경 충돌, 동시 조건부
쓰기, 로컬 경로 격리와 변경 결과 불확실성을 테스트합니다. Linux 전용 보안·잠금
테스트는 Windows에서 건너뜁니다. 서비스 테스트는 로컬 HTTP 픽스처를 사용하며,
실제 Google Drive·Slack 계정 연동을 검증한 것은 아닙니다.

## 기여

제공자나 기능을 추가할 때 URI와 버전 규칙, 지원 작업, 변경 결과가 불확실한
경우의 동작을 설명해주세요. 자격 증명은 외부에서 전달받고, 제공자 API 구현을
애플리케이션의 스케줄·정책과 분리해주세요. 계약 테스트를 추가하고 공개 동작이
바뀌면 제공자 안내와 두 언어의 README를 함께 갱신해주세요. 변경을 공유하기
전에 위 검사를 실행해주세요. 기여 내용에는 BSD 3-Clause 라이선스를 적용합니다.

[기여 안내](docs/CONTRIBUTING.ko.md), [보안 신고](docs/SECURITY.ko.md),
[배포 절차](docs/RELEASE.ko.md)도 확인하세요.
