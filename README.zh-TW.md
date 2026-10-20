<p align="center">
  <img src="docs/assets/lodex-logo.svg" width="112" height="112" alt="Lodex 標誌" />
</p>

<h1 align="center">Lodex</h1>

<p align="center">
  <strong>配合 coding agent 使用的本機開發工具。</strong><br />
  準備任務環境、執行專案、找回先前的開發脈絡。
</p>

<p align="center">
  <a href="#安裝">安裝</a> ·
  <a href="#快速開始">快速開始</a> ·
  <a href="#文件導覽">文件導覽</a> ·
  <a href="#選用herdr-整合">Herdr 整合</a>
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>繁體中文</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-20332f?style=flat-square" alt="授權：Apache 2.0" /></a>
  <a href="cli/pyproject.toml"><img src="https://img.shields.io/badge/version-0.2.0-20332f?style=flat-square" alt="版本 0.2.0" /></a>
  <a href="#安裝"><img src="https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11 以上" /></a>
  <a href="docs/history.md#connect-codex-through-mcp"><img src="https://img.shields.io/badge/MCP-read--only_history-626b68?style=flat-square" alt="MCP：唯讀歷史查詢" /></a>
</p>

---

Lodex 是一套配合 coding agent 使用的本機工具，協助你與 agent 為任務準備工作目錄、
執行專案命令與服務，並從過去的 agent 對話中找回有用的脈絡。

- **準備任務環境**：註冊 Git 儲存庫、建立或掛接 worktree，為各個工作目錄配置獨立的設定與連接埠。
- **執行並查看專案狀態**：執行儲存庫定義的準備與驗證命令、啟動或停止服務，並查看結果與日誌。
- **找回先前的脈絡**：搜尋 coding agent 的歷史對話，查找決策、先前嘗試與佐證。
  目前內建的歷史來源介接器支援讀取 Codex sessions。

## 搭配 coding agent 使用

**CLI** 提供本機操作工具；選用的 **agent skills** 引導 agent 使用這些工具，
處理專案設定、worktree、服務與歷史查詢。**MCP** 將唯讀的歷史搜尋能力提供給 agent；
選用的 **Console** 則讓你在瀏覽器中查看與操作同一批任務環境。

例如，你可以請 agent 使用 `lodex-project-setup` 設定儲存庫、使用 `lodex-worktree`
建立任務工作目錄，再透過 `lodex-services` 啟動專案服務。Agent 在該目錄中修改程式碼，
Lodex 負責執行設定好的命令，並保存環境狀態、執行結果與日誌，供後續 session 繼續使用。
需要先前討論的背景時，再透過 `lodex-history` 查詢。

想跟著 agent 一起操作，可從[第一個網站教學](docs/manual-validation.md)開始；
想直接使用 CLI，請看[快速開始](#快速開始)。
Skill 的安裝方式見 [Agent skills](#agent-skills)；多個 agent 協作的流程則見
[選用的 Herdr 整合](#選用herdr-整合)。

環境管理不依賴特定 coding agent，也不需要 Ollama。歷史功能使用獨立的設定與資料庫，
建立索引與混合搜尋時會使用本機的 Ollama 模型。目前 MCP 僅提供歷史查詢；
環境操作則透過 CLI 或 Console 進行。

## 文件導覽

- [本機任務環境：設定與命令參考](docs/management.md)
- [對話歷史：索引、篩選、設定與 MCP](docs/history.md)
- [選用的本機 Console](docs/console.md)
- [搭配 Herdr：總管與 worker 的設定及完整流程（英文）](docs/herdr.md)
- [第一個 coding agent 工作流程：製作小型網站](docs/manual-validation.md)
- [Monorepo 結構、開發與套件建置](docs/architecture.md)
- [獨立可執行的多服務範例與隔離驗證](examples/multi_service/README.md)

## 安裝

請先準備 Python 3.11 以上版本與 `uv`。這個儲存庫使用 workspace 結構，包含 Core、CLI
與 Console Server 三個套件。先在原始碼工作目錄建置整組套件，再安裝 CLI wheel，
並讓安裝工具從同一個目錄取得其他相依 wheel。

建置 Console 需要 Node.js 20.19 以上或 22.12 以上，以及 pnpm
（版本固定於 `console/f2e/package.json`）；使用已安裝的版本則不需要這些工具。

```bash
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv tool install --find-links dist dist/lodex-0.2.0-py3-none-any.whl
lodex --version
lodex --help
```

環境管理需要 Git；目前的程序監管與鎖定機制使用 POSIX API。
歷史功能另外需要 [Ollama](https://ollama.com/download)，設定方式見下方的歷史搜尋快速開始。

若要使用選用的瀏覽器 Console，請從前面建置的套件安裝 `console` extra。
安裝後即可在任意目錄啟動：

```bash
uv tool install --force --find-links dist 'dist/lodex-0.2.0-py3-none-any.whl[console]'
lodex console --port 8765
```

開啟終端印出的完整網址，包含 `#token=...`，並保持該終端持續執行。
在終端按 Ctrl+C 會停止 Console，受管理的服務仍會繼續運作。
省略 `--port` 時，系統會自動選擇可用的連接埠。

Console 與 CLI 共用管理狀態，並內附建置好的前端資源，一般使用不需要 Node.js 或 Vite server。
頁首提供 System、Light 與 Dark 三種主題；使用相同的主機名稱與連接埠時，瀏覽器會保留主題選擇。
存取方式、導覽與生命週期詳見 [Console 指南](docs/console.md)。
若要將原始碼的變更更新到已安裝版本，請看[更新已安裝的 Console](docs/console.md#update-the-installed-console)。

## 快速開始

### 管理本機任務環境

專案是已註冊的本機 Git 儲存庫。任務環境（Console 稱 Environment，內部名稱為 `taskenv`）
將一份 Git worktree 與設定、配置的連接埠、命令紀錄及服務關聯起來。
Worktree 是實際的 Git 工作目錄，包含主工作目錄與額外建立的 linked worktree；
目錄移除後，任務環境紀錄仍可保留。註冊專案時，不會自動為主工作目錄註冊任務環境。
完整定義見[用語對照](docs/management.md#terminology)。

`project add` 會驗證並保留既有的 `.lodex/project.toml`；若檔案不存在，
則建立最小設定骨架，或複製 `--config PATH` 指定的設定檔。
使用新建立的骨架時，請先編輯檔案、定義儲存庫的命令與服務，再開始操作。
設定範例見[設定格式第 1 版](docs/management.md#version-1-configuration)。
Lodex 自己的內建設定已定義 `prepare` 與 `verify`：

```bash
lodex project add lodex /absolute/path/to/lodex
lodex worktree attach lodex /absolute/path/to/lodex
cd /absolute/path/to/lodex
lodex context
lodex prepare
lodex run verify
```

若想使用新的工作目錄，可以指定既有 Git ref 作為起點，建立分支：

```bash
lodex worktree create lodex --ref main --branch feature-one --json
lodex worktree list --json
```

建立完成後會回傳任務環境 ID 與工作目錄路徑，但不會執行 `prepare`。
新目錄名稱由建立時的分支名稱轉成易讀的 slug，再加上 ID 的前八碼，
例如 `feature-one--a3f19c82`；既有路徑不會因此改動。
即使後續切換分支，完整 taskenv ID 仍是該環境的固定識別碼。

對於接受目標參數的命令，可以使用 `--target TASKENV_ID`、工作目錄或其子目錄的絕對路徑，
也可以直接在已註冊的目錄內執行：

```bash
lodex prepare --target TASKENV_ID
lodex run verify --target TASKENV_ID
```

命令與服務名稱都來自該工作目錄的設定檔。例如，`lodex service start web`
需要先設定 `services.web`；前述 Lodex 自身的設定並未定義服務或 cleanup 命令。

### 搜尋對話歷史

啟動 Ollama（若尚未執行，可使用 `ollama serve`），接著下載模型並建立索引：

```bash
ollama pull qwen3-embedding:0.6b
lodex status
lodex index
lodex search "why was the parser changed?" --project current --limit 5
lodex show CHUNK_ID --context 1
```

再次執行 `lodex index` 即可增量更新索引。`lodex status` 檢查的是**歷史功能的執行環境與索引**；
任務環境狀態請使用 `context`、`worktree inspect` 與 `service list` 查詢。
篩選條件、純文字搜尋與 MCP 用法詳見[歷史功能指南](docs/history.md)。

## 命令總覽

使用 `lodex <command> --help` 或 `lodex <command> <subcommand> --help` 查看選項。
範例中的大寫佔位符，請替換為實際的 ID、名稱或路徑。

### 環境管理

| 命令 | 用途 |
| --- | --- |
| `project add NAME PATH`, `project list` | 註冊儲存庫、初始化缺少的設定，並列出已註冊專案。 |
| `worktree create PROJECT --ref REF --branch BRANCH` | 在新分支上建立並註冊由 Lodex 管理的工作目錄。 |
| `worktree attach PROJECT PATH` | 註冊既有工作目錄，不接管其所有權。 |
| `worktree list`, `worktree inspect` | 查看已註冊的環境，也會列出工作目錄已不存在的環境。 |
| `worktree remove`, `worktree forget` | 預覽刪除工作目錄或取消註冊的範圍；加上 `--yes` 才會執行。 |
| `context` | 解析目前或明確指定的環境；對應工作目錄必須存在。 |
| `prepare`, `run NAME`, `cleanup` | 執行儲存庫定義的對應命令，並記錄結果。 |
| `service start NAME`, `service stop NAME` | 啟動或停止設定好的服務。 |
| `service list`, `service inspect NAME`, `service logs NAME` | 查詢已保存的服務狀態與近期日誌。 |
| `operation list`, `operation inspect ID`, `operation logs ID` | 查詢儲存庫命令的執行紀錄與近期日誌。 |
| `env show` | 查看解析後的 TOML 設定、配置的值與 secret 參照。 |
| `env export` | 寫入受保護的 dotenv 檔案（預設為 `.env`）；可能包含 secret 值。 |
| `port set KEY VALUE` | 調整已宣告的連接埠配置；請先停止受影響的服務。 |
| `secret list`, `secret set NAME`, `secret remove NAME` | 列出已儲存的名稱、私密輸入值，或預覽／刪除共用值；不需指定專案或 taskenv。 |

環境管理命令支援 `--json`，請將它放在命令名稱之後。
接受目標參數的命令可使用 `--target TASKENV_ID` 或工作目錄的絕對路徑；省略時會解析目前目錄。
`operation inspect/logs` 接受的是 **operation ID**。
Secret 命令操作中央儲存區，不接受 `--target`。
完整參數與生命週期說明見[環境管理命令參考](docs/management.md#command-reference)。

`cleanup` 只會執行儲存庫定義的清理命令，不會自動停止服務或移除工作目錄。
`worktree remove` 只會刪除由 Lodex 擁有的工作目錄，並保留 Git 分支；
`worktree forget` 則只會移除註冊紀錄。

一般設定值與 secret 對應關係，都直接在工作目錄的 `.lodex/project.toml` 中編輯，
沒有額外的資料庫覆寫層。例如：

```toml
[env]
APP_MODE = "development"
[secrets]
API_TOKEN = "secret:app-dev-token"
```

再透過 `lodex secret set app-dev-token` 獨立儲存實際值（輸入內容會隱藏）。
這裡的 secret 名稱是 `app-dev-token`，`API_TOKEN` 則是應用程式收到的環境變數名稱。
之後每次啟動命令或服務，或執行 `env export` 時，都會解析當下儲存的值；
已執行中的程序不會自動更新。

`env show` 不會讀取既有的 `.env`。需要 dotenv 檔案時，請使用 `env export` 產生；
由 Lodex 啟動的程序會直接收到環境變數，不需要透過該檔案。

### 對話歷史

| 命令 | 用途與範例 |
| --- | --- |
| `index` | 建立或增量更新索引：`lodex index --session SESSION_ID`。 |
| `search QUERY` | 搜尋已索引的歷史：`lodex search "parser" --project current --limit 5`。 |
| `show CHUNK_ID` | 展開搜尋結果與相鄰對話：`lodex show CHUNK_ID --context 1`。 |
| `status` | 診斷 Ollama、模型與索引的相容性：`lodex status --json`。 |
| `rebuild --yes` | 重設歷史索引；之後需執行 `lodex index` 重新建立內容。 |
| `mcp` | 透過 stdio，向 MCP client 提供唯讀的歷史 `status`、`search` 與 `show` 工具。 |

上表除 `mcp` 外的歷史命令都支援 `--json`；輸出格式與環境管理使用的 `ok`／`result`
結構不同。更多範例與篩選規則見[歷史命令參考](docs/history.md#commands)。

### Agent skills

Skills 是搭配 CLI 使用的選用 agent 指引。透過 `lodex skill install NAME` 安裝或更新，
透過 `lodex skill remove NAME` 移除。兩者都支援 `--dry-run`；省略 `NAME` 時預設為 `lodex-history`。

若想讓 agent 配合 `project add`、`lodex-project-setup`、`lodex-worktree` 與
`lodex-services` 完成開發流程，請跟著[網站教學](docs/manual-validation.md)操作。
教學包含 skill 安裝，以及設定專案、建立 worktree、管理服務、查看日誌、修改程式、
提交與清理的提示詞範例；Console 主要用來觀察共用狀態。

| Skill | 用途 |
| --- | --- |
| `lodex-history` | 透過 MCP 或 CLI 搜尋先前 session 的佐證。 |
| `lodex-worktree` | 透過 CLI 建立、掛接、查看與移除任務環境。 |
| `lodex-services` | 操作任務環境中的服務，並查看狀態與日誌。 |
| `lodex-project-setup` | 為儲存庫設定 `.lodex/project.toml`。 |
| `lodex-herdr` | 選用：透過 Herdr 協調 Lodex 任務環境中的多個 agent。詳見 [Herdr 整合](#選用herdr-整合)。 |

```bash
lodex skill install lodex-worktree --dry-run
lodex skill install lodex-worktree
```

Skills 會以受管理的副本安裝，因此移動或刪除原始碼工作目錄，也不會影響使用。
重裝相同內容時不會產生變更；更新則會替換整份已安裝 skill，包含本機修改，並移除過時檔案。
歷史 MCP 的設定方式見[透過 MCP 連接 Codex](docs/history.md#connect-codex-through-mcp)。

## 選用：Herdr 整合

需要多個 coding agent 分工時，可以將 Lodex 與 Herdr 搭配使用。
由 manager agent 為各個 worker 準備獨立的任務工作目錄、分派工作並彙整結果。
Lodex 管理工作目錄與服務，Herdr 提供 panes 與 agent 程序；
`lodex-herdr` skill 引導 manager 串起環境準備、worker 啟動與後續協調。
Lodex 的 CLI、Console、歷史工具與其他 skills 都能獨立於 Herdr 使用。

總管留在原始 repo，每個 worker 使用自己的任務 checkout。
Codex 的建議設定名稱為 `lodex-manager`、`lodex-worker`；它們是設定 profile，
不是 Lodex 子命令或服務。由你先以總管設定啟動 agent，再由總管依 skill 啟動 worker。
安裝 skill 不會替 agent 安裝設定或重新啟動。

角色設定、選用的總管快捷鍵，以及派工、驗證到收尾，見
[Herdr 完整指南（英文）](docs/herdr.md)。也請保留 Herdr 自己的 skill，以取得目前 CLI 與互動式操作方式。
給 agent 的詳細指引與權限範本，則見內建的
[整合 skill](cli/src/lodex_cli/bundled_skills/lodex-herdr/SKILL.md)
與 [Codex 設定參考](cli/src/lodex_cli/bundled_skills/lodex-herdr/references/codex.md)。

```bash
lodex skill install lodex-herdr --dry-run
lodex skill install lodex-herdr
```

## 設定與資料儲存

| 功能 | 設定位置 | 預設資料位置 |
| --- | --- | --- |
| 環境管理 | 各工作目錄的 `.lodex/project.toml`；配置的連接埠與中央 secrets 存於 registry | `~/.lodex/management.db`；日誌與服務控制資料位於 `~/.lodex`（`LODEX_HOME`） |
| 對話歷史 | `~/.lodex/history/config.toml`（`LODEX_CONFIG`） | `~/.lodex/history/lodex.db`（`LODEX_DATA_DIR`／`LODEX_DB_PATH`） |

`LODEX_HOME` 可調整兩項功能的預設根目錄（預設為 `~/.lodex`）。
若 `$LODEX_HOME/history/config.toml` 存在，歷史功能就會讀取它；索引預設存放於
`$LODEX_HOME/history/`。明確指定的歷史路徑設定優先於預設值，解析順序詳見
[歷史功能設定](docs/history.md#configuration)。

環境管理的 secrets **以明文儲存在 SQLite 中**，並透過 POSIX 檔案權限保護，
不依賴加密、金鑰檔或作業系統的 Keychain。請將管理資料庫與備份視為敏感資料。
一般環境查詢只會顯示參照；`secret list` 也只列出已儲存的名稱。
`secret set` 接受隱藏輸入或 `--stdin`，不接受透過命令列參數傳入實際值。
共用參照、匯出保護與設定編輯方式見[環境管理設定](docs/management.md#version-1-configuration)。

歷史功能只讀取來源對話，不會修改原始檔案。Embedding 只會送往本機 loopback Ollama 端點，
衍生索引也保留在本機。詳見[歷史功能設定](docs/history.md#configuration)
與[隱私與自動化](docs/history.md#privacy-and-automation)。

## 更新或移除安裝

在原始碼工作目錄重新建置整組套件並安裝，再更新你使用的各個 skill。
若要保留選用的 Console，請在 wheel 參數後加上 `[console]`：

```bash
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv tool install --force --reinstall --find-links dist dist/lodex-0.2.0-py3-none-any.whl
lodex skill install lodex-history --dry-run
lodex skill install lodex-history
```

若已安裝 Console，請將上面的 `uv tool install` 命令替換為：

```bash
uv tool install --force --reinstall --find-links dist 'dist/lodex-0.2.0-py3-none-any.whl[console]'
```

已安裝的 Console 會提供 Server wheel 內附的前端資源。
只修改原始碼或單獨建置前端，都不會更新這份安裝。
重新安裝後，請先在舊 Console 程序的終端按 Ctrl+C，再次執行
`lodex console --port 8765`，並開啟新印出的 token 網址。

既有歷史資料庫的更新方式見[索引升級指引](docs/history.md#updating-an-existing-history-index)。
環境管理資料庫的 schema 升級則另見環境管理指南。

使用以下命令移除已安裝的 skill 或 CLI：

```bash
lodex skill remove lodex-history --dry-run
lodex skill remove lodex-history
uv tool uninstall lodex
```

移除 CLI 或 skill 不會清除受管理的環境、資料庫、日誌或來源對話。
若要清理環境，請在解除安裝 CLI 之前先停止服務，並完成預期的清理操作。

## 開發

建立或同步專案環境後，即可在原始碼工作目錄中執行 Lodex；開發不需要安裝使用者層級的工具。

```bash
uv sync --locked
uv run lodex --help
```

Workspace 套件會以 editable 模式安裝至根目錄的 `.venv`。
若要在其他專案中使用獨立安裝的 CLI，請使用前述 wheel 安裝方式。
根目錄僅負責協調 workspace，本身不是可安裝的 Python 套件。

在原始碼工作目錄執行本機驗證：

```bash
uv run pytest -m "not ollama"
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

CLI 使用 Typer，程式碼位於 `cli/src/lodex_cli/`；它與 `console/server/src/lodex_console/`
中的 HTTP server 都直接呼叫 `core/src/lodex_core/`。前端位於 `console/f2e/`。
各子專案維護自己的測試、fixtures 與測試輔助程式；Console 生命週期測試位於
`console/tests/`，多服務隔離測試則位於 `examples/multi_service/tests/`。

執行 `uv run python scripts/verify_environments.py` 可透過獨立的 CLI 驗收流程進行驗證，
不需要其他儲存庫或 Docker。相依關係與命令詳見[架構指南](docs/architecture.md)。
歷史功能的執行期相依套件，只會在執行歷史命令時才載入。

實際連線至 Ollama 的契約測試另有標記：

```bash
uv run pytest -m ollama core/tests/test_ollama_integration.py
```

## 授權

Lodex 採用 [Apache License 2.0](LICENSE) 授權。
