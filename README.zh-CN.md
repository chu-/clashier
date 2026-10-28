# Clashier：代理控制工具

Clashier 是供 shell 和 Agent 组合使用的本地代理控制工具，支持通过 TCP 或 Unix socket
查询、测速和切换正在运行的 Clash Verge / mihomo 代理。

项目包含负责执行操作的 CLI，以及帮助 Agent 发现命令、完成代理操作流程的可选 Skill。

[English](README.md) | 简体中文

## 快速开始

### 安装命令行工具

使用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Git
从 [GitHub](https://github.com/chu-/clashier) 安装：

```bash
uv tool install 'git+https://github.com/chu-/clashier.git'
clashier --version
clashier --output json capabilities
```

安装后的命令不依赖当前目录。需要 Python 3.8+；可为 `uv tool install` 添加
`--python 3.12`，由 uv 选择或下载对应解释器。
Windows、PATH、升级和验证步骤见 [安装指南](docs/install.md)。

### 交给 Agent 完成安装

可以把仓库地址或本 README 连同下面这句话发给具有目标电脑终端权限的 Codex、Claude Code 等 Agent：

> 请安装 https://github.com/chu-/clashier 的 CLI，并将其中的 skills/clashier
> 注册为你当前 Agent 的用户级 Skill。按 docs/install.md 操作，分别验证 CLI、
> Skill 发现和控制器连接，报告可执行文件路径、Skill 安装位置及各项结果。

**给安装 Agent：**先读[安装指南](https://github.com/chu-/clashier/blob/main/docs/install.md)，
其中包含仅安装 CLI、安装 CLI＋Skill，以及从本地源码安装的具体步骤。
安装后按 [Agent 使用指南](https://github.com/chu-/clashier/blob/main/docs/agent-usage.md)
发现命令和处理 JSON 结果。[Skill 入口](https://github.com/chu-/clashier/blob/main/skills/clashier/SKILL.md)
与 README 分开；只安装 CLI 不会自动注册 Skill。

通过 GitHub 安装，要求源码已发布且安装者有读取权限；发布前可以使用完整的本地源码目录安装。
安装验证只读查询即可，不需要切换订阅、重启客户端或改变节点。
Agent 需要目标电脑的执行权限；单纯在聊天中阅读 README 不会获得本机代理的控制能力。

## 命令使用指南

### 不知道订阅和节点名称时

先查看订阅，再查看指定订阅声明的策略组和节点：

```bash
clashier profile list
clashier profile show p2
clashier proxy groups --profile p2
clashier proxy list --profile p2
clashier proxy list --profile p2 --group 'Example Selector'
```

这些探索命令默认显示表格、当前项及可复制的下一步命令。通常使用名称即可；重名时列表同时显示 UID，
详情始终显示 UID。Agent 和脚本使用全局 `--output json`，例如 `clashier --output json profile list`。
后续命令提示保留当前连接参数，不显示鉴权内容。

示例 `p2` 替换成订阅的 UID 或确切名称。这些查询支持未激活的订阅，不连接内核、不切换订阅。
文本明确说明是离线配置，JSON 标记 `source: configured`、`view: declared`；不导出节点凭据或 provider URL。
provider 只列名称，不下载或展开；`complete: false` 表示 provider 或动态组的节点无法从静态声明完整列出。
Verge 脚本和合并配置也可能改变最终运行内容。

直接在 CLI 中切换订阅并验证：

```bash
clashier profile activate p2
clashier profile verify p2
```

激活会先退出官方 Clash Verge 客户端，等待进程结束，再保存目标订阅并重新启动客户端。
先退出再写入，可以避免客户端退出时把内存中的旧选择写回磁盘。脚本、合并、DNS 和 TUN 设置由客户端自身处理。
CLI 等待客户端就绪、配置重新生成，并确认内核运行图匹配后才报告成功。

客户端就绪检查只读查询 Clash Verge Rev 2.5.7、2.5.8 的本地 PAC 接口，不开启系统 PAC 设置，也不调用显示或创建窗口的命令。
macOS 启动前检查当前用户是否已有同名客户端进程，没有时直接启动程序，避免重复拉起。重启会短暂中断网络；激活默认等待 30 秒，
显式指定全局 `--timeout` 可以覆盖。结果中的 `gui_sync: restarted`、`client.status: ready` 表示客户端已重新启动并就绪；
验证范围为 `client_generated_proxy_graph`，不包含网站连通性测试。启动或验证失败会报告已经完成的步骤及部分生效状态。

`profile verify UID [--wait]` 只读比较包含增强层的运行图，不能仅凭同名节点证明客户端内存中的选择。
仅希望操作内核时，显式使用 `profile activate UID --core-only`：由 CLI 渲染增强配置、热加载并保存文件，
此时 `gui_sync: not_verified`，客户端界面不会同步。JavaScript 使用内嵌 V8，无需另装 Node.js；
脚本须同步返回配置对象，console 输出不会写入 CLI。内核加载响应丢失时返回未知结果且不改文件。

希望逐级选择时，在终端执行：

```bash
clashier choose
```

`choose` 是终端交互向导；`proxy select --group G --name N` 是目标已明确时的独立操作，适合脚本和 Agent。

按编号选择“订阅 → 实时 Selector 组 → 候选节点”，先预览所选订阅声明的组和节点。
确认后重启 Clash Verge 加载该订阅，再进入实时组和节点菜单。即使磁盘已经标记该订阅为当前项，也会重启，
以消除客户端内存中仍保留旧选择的情况。之后取消节点选择不会撤销已经完成的订阅切换。
最终确认展示订阅、策略组、原节点、新节点以及是否保存；最终结果单独显示客户端重启状态。
`choose` 默认保存节点：最终确认后，再退出客户端、写入所选节点、重新启动并验证节点已恢复。
因此，加载订阅之后还会为保存节点再重启一次，网络会再次短暂中断。
使用 `clashier choose --temporary` 临时切换节点，不更新原有的节点记忆；此参数只针对节点，所选订阅仍然生效。
提示写入 stderr，最终结果写入 stdout。
`choose` 要求终端，`--no-input` 会拒绝交互；Agent 使用上面的独立查询和操作命令。

### 查询代理、测速与切换节点

全局选项放在命令之前。以下组名和节点名均为虚构示例，使用时替换为控制器返回的实际名称：

```bash
clashier --output json proxy groups
clashier --output json proxy list
clashier --output json proxy list --group 'Example Selector'
clashier --output json proxy probe --group 'Example Selector' --name 'Example Node A'
clashier --output json proxy select --group 'Example Selector' --name 'Example Node A' --persist
clashier --output json proxy get --group 'Example Selector'
```

| 命令 | 职责 |
| --- | --- |
| `core discover` | 列出已验证的实例和失败候选的诊断 |
| `status` | 查询实时运行模式和各组当前选择 |
| `proxy groups [--profile UID]` | 查询实时组，或离线查询订阅声明的组 |
| `proxy list [--group G]` / `proxy list --profile UID [--group G]` | 查询全部实时节点及所属组、选中状态，或限定组、离线订阅 |
| `proxy get --group G` | 读取选择和可解析的代理组链 |
| `proxy probe --group G --name N [--url URL]` | 单节点测速，不切换代理 |
| `proxy select --group G --name N [--persist] [--if-current OLD]` | 设置一个明确目标并回读验证 |
| `capabilities` | 查询已实现能力，无需连接内核 |
| `schema show proxy.select` | 查询安装包内的输入和结果 Schema |

`proxy list` 展示当前内核运行配置中的全部节点（包括已加载的 provider 节点及 DIRECT 等内置动作），
标注直接所属的策略组，以及当前直接选中它的组；同一节点可以属于或被多个组选中。
策略组本身由 `proxy groups` 列出，并显示每个组的当前选择。
`proxy list --group G` 展示该组全部候选（包括嵌套组），标记当前选中项。
这些标记描述组关系，不代表全局流量正在使用该节点；列表也不执行连通测试。

`proxy select` 默认只修改运行状态。`--persist` 会等待官方客户端退出后保存节点记忆，再重新启动并验证恢复结果，
避免退出时被旧内存覆盖。此操作要求本机安装客户端并使用其原生配置目录，默认超时为 30 秒。
成功结果包含 `persistence.status: saved` 和 `persistence.gui_sync: restarted`，仅写盘成功不视为持久化成功。
重复选择同一节点会跳过多余的节点切换请求，但要求保存时仍会重启客户端以同步记忆。
重复选择相同节点会跳过 PUT，并可补齐先前失败的持久化。自动选择或故障转移组
不能冒充可手动写入的 Selector。选择成功不代表网站已连通，也不会重建已有连接。

### 控制器发现与连接设置

| 全局参数 | 环境变量 | 用途 |
| --- | --- | --- |
| `--config-dir PATH` | `CLASH_VERGE_DIR` | 配置目录，默认按平台发现 |
| `--controller ADDRESS` | `CLASH_API_URL` | HTTP(S)、host:port 或 `unix:///绝对路径` |
| `--secret TEXT` | `CLASH_API_SECRET` | 控制器密钥，优先使用配置或环境变量 |
| `--instance ID` | | 使用发现结果中的确切实例 |
| `--timeout SEC` | | 操作时间预算：默认 5 秒，客户端重启默认 30 秒 |
| `--output text/json` | | 原子能力的结果格式 |
| `--no-input` | | 显式禁止提示，拒绝 `choose` 交互入口 |

自动发现读取配置中的 TCP/TLS/Unix 地址，并在 macOS 上检查当前用户的 Verge
service socket。多个可达实例需要指定目标；显式控制器连接失败不会改连另一个实例。
Windows 支持 TCP，暂未实现 named pipe。控制器请求不继承环境代理。

### 订阅、主机设置与诊断

订阅、配置、备份与代理命令共享相同的结果协议。配置查询标明 `data.source=configured`，
尚未验证实时效果的文件修改返回 `status=pending`。主机开关只接受明确的 `on/off`，重复调用不会反转状态。

| 分类 | 命令 |
| --- | --- |
| 订阅 | `profile list/show/add/activate/verify/delete`、`profile traffic` |
| 系统代理 | `host proxy get`、`host proxy set on/off` |
| TUN | `host tun get`、`host tun set on/off` |
| 端口 | `host ports get`、`host ports set TYPE PORT [--enable/--disable]` |
| 应用管理 | `host restart`、`host open config/logs`、`host webui` |
| 配置 | `config get core/verge`、`config set KEY VALUE`、`config dns/rules/path/refresh` |
| 备份 | `backup create [NAME]`、`backup list`、`backup restore NAME` |
| 日志 | `logs read --lines N`、`logs search KEYWORD` |
| HTTP 检查 | `health --url URL [--proxy URL]` |

订阅激活会热加载内核并验证；系统代理、TUN 和端口的配置修改仍需通过 Verge 应用，改文件本身不能证明已经重载。
`config get` 明确导出原始配置，可能包含凭据；订阅列表不暴露订阅 URL。

```bash
clashier --output json profile list
clashier --output json host proxy set on
clashier --output json backup create before-change
clashier --output json health --url https://www.gstatic.com/generate_204 --proxy http://127.0.0.1:7897
```

`health` 没有内置网站，未指定 `--proxy` 时直连。非 2xx 响应和网络故障返回结构化错误。
组合工作流可参考
[可达后切换示例](examples/select-reachable.sh)，通过 `bash examples/select-reachable.sh GROUP NODE TEST_URL`
调用，示例需要 jq。

资源命令统一使用全局 `--output json`。源码入口 `clashier.py` 支持各平台。

## 开发与验证

### 准备环境与运行检查

```bash
uv sync --locked
uv run --locked pytest
uv run --locked pytest tests/integration tests/application tests/contract
uv run --locked ruff check .
uv build --wheel
```

### 源码模块与职责

CLI 按资源拆分，`cli/render.py` 统一输出，`cli/protocol.py` 处理契约和输入校验。
`application` 封装代理操作，`adapters/verge_store.py` 处理设置、备份和日志，
`adapters/profiles.py` 管理订阅，`adapters/yaml_files.py` 处理 YAML 校验和原子文件替换，
`application/profiles.py` 协调客户端重启、订阅切换与节点记忆，并验证恢复结果。测试使用临时配置和本地控制器，不修改真实代理。

贡献方式见 [贡献指南](CONTRIBUTING.md)。

## 相关项目

| 项目 | 特点与适用场景 |
| --- | --- |
| [Hsiifu3/clash-verge-skill](https://github.com/Hsiifu3/clash-verge-skill) | 纯 Python、无第三方依赖，面向 Clash Verge Rev。支持 macOS/Linux 的 Unix Socket 和 HTTP API，可查询代理组、切换节点、测速及切换 Rule/Global/Direct 模式。 |
| [Kerry1020/clash-verge-cli](https://github.com/Kerry1020/clash-verge-cli) | 支持 macOS、Windows、Linux。涵盖节点、策略组、订阅配置、系统代理开关、TUN 和延迟测试，适合从命令行管理整个 Clash Verge。 |
| [Hanyang-Li/verge-proxy](https://github.com/Hanyang-Li/verge-proxy) | Rust CLI 与 zsh 集成，可切换代理模式、策略组和节点，并管理当前终端的代理环境变量；提供 Apple Silicon 二进制。 |

## 许可证说明

项目采用 GPL-3.0 许可证，完整条款见 [LICENSE](LICENSE)。
