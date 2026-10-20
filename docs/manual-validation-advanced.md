# 進階手動驗證：隔離、錯誤處理與刪除保護

[回 README](../README.md) · [CLI 參考](management.md) · [Console 使用方式](console.md)

第一次使用請先走完 [已安裝版本的網站操作教學](manual-validation.md)。
本篇是較完整的開發驗證流程，需要 Lodex 原始碼工作區。

這份流程驗證你與 coding agent 共用的環境工具：建立 worktree、執行命令、管理服務與清理資源。
透過 CLI 與 Console 操作，檢查同一環境的狀態與結果是否一致；agent 搭配 skills 的用法見前述教學。
建議預留 30–45 分鐘，依序完成；只想快速看介面，可先用
[現有瀏覽器 fixture](../console/f2e/README.md#manual-verification)。

全程使用臨時 Git 專案、獨立管理資料庫、假 secret 及本機 HTTP 服務。
不需要 Docker、Ollama、其他應用專案或真實憑證。這能驗證 Lodex 的操作流程與基本隔離，
但不代表真實專案的資料庫、Redis、migration 或業務功能也通過驗證。

## 1. 準備測試場地（終端 A）

以下以 macOS 的 zsh／bash 與目前原始碼工作目錄為準。先在 Lodex 根目錄準備開發環境：

```sh
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
pnpm --dir console/f2e run build
```

這是使用目前分支的程式，不會更新全域安裝。接著在**同一個終端**貼上整段：

```sh
export LODEX_MANUAL_BIN="$PWD/.venv/bin/lodex"
export LODEX_MANUAL_ROOT="$(mktemp -d /tmp/lodex-manual.XXXXXX)"

lx() {
  LODEX_HOME="${LODEX_MANUAL_ROOT:?}/manager" "${LODEX_MANUAL_BIN:?}" "$@"
}

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["LODEX_MANUAL_ROOT"]).resolve()
repo = root / "repo"
(repo / ".lodex/scripts").mkdir(parents=True)
(repo / "README.md").write_text("# Disposable Lodex manual check\n")
(repo / ".gitignore").write_text(".runtime/\n.env\n")
(repo / ".lodex/scripts/demo.py").write_text('''import json
import os
from pathlib import Path
import shutil
import sys
import time

action = sys.argv[1]
runtime = Path(".runtime")
identity = os.environ["LODEX_TASKENV_ID"]
if action == "prepare":
    runtime.mkdir(exist_ok=True)
    (runtime / "index.html").write_text(f"<h1>Lodex manual check</h1><p>{identity}</p>")
elif action == "verify":
    assert identity in (runtime / "index.html").read_text(), "Run prepare first"
elif action == "fail":
    print("Intentional failure for manual verification", flush=True)
    sys.exit(7)
elif action == "slow":
    print("Started once; wait 8 seconds", flush=True)
    time.sleep(8)
    with (runtime / "runs.txt").open("a") as stream:
        stream.write("completed once\\n")
elif action == "cleanup":
    shutil.rmtree(runtime, ignore_errors=True)
else:
    raise SystemExit("Unknown action")
if action in ("prepare", "cleanup"):
    Path(os.environ["LODEX_RESULT_FILE"]).write_text(json.dumps({"resources": [{
        "name": "demo-files", "kind": "directory", "id": str(runtime.resolve()),
        "scope": "exclusive", "state": "removed" if action == "cleanup" else "present"
    }]}))
print(f"{action} succeeded for {identity}")
''')
recipe = '''schema_version = 1
[env]
DEMO_LABEL = "manual_${LODEX_TASKENV_ID}"
[ports]
PORT = 0
[secrets]
DEMO_TOKEN = "secret:manual-token"
'''
for action in ("prepare", "verify", "fail", "slow", "cleanup"):
    recipe += f"\n[commands.{action}]\n"
    recipe += "argv = " + json.dumps([sys.executable, ".lodex/scripts/demo.py", action]) + "\n"
    recipe += 'scripts = [".lodex/scripts/demo.py"]\n'
recipe += '\n[services.http]\nargv = ' + json.dumps([
    sys.executable, "-m", "http.server", "${PORT}", "--bind", "127.0.0.1",
    "--directory", ".runtime",
]) + '\nready_port = "PORT"\nurl = "http://127.0.0.1:${PORT}"\n'
(repo / ".lodex/project.toml").write_text(recipe)
for args in (
    ("init", "-q"), ("add", "."),
    ("-c", "user.name=Lodex Manual", "-c", "user.email=manual@example.invalid",
     "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
     "commit", "-qm", "Add disposable manual fixture"),
):
    subprocess.run(["git", "-C", str(repo), *args], check=True)
print(f"Register this repository in Console: {repo}")
PY

printf '\nPaste this command into terminal B:\nLODEX_HOME=%q %q console\n' \
  "$LODEX_MANUAL_ROOT/manager" "$LODEX_MANUAL_BIN"
```

保留輸出的 repo 絕對路徑與 Console 啟動命令。`lx` 是只存在於終端 A 的簡寫，
每次都指定測試用 `LODEX_HOME`；後續 CLI 步驟請使用 `lx`。
不要在這個流程中改用未指定 `LODEX_HOME` 的 `lodex`，以免看到正式管理資料。

HTTP 服務只公開 `.runtime`，不公開 repo 根目錄或匯出的 `.env`。
fixture 的 Python 路徑固定為目前 workspace 的直譯器，測試途中不要刪除 `.venv`。

## 2. 開啟 Console、註冊與建立 A／B

在**終端 B**執行剛才印出的命令，開啟它印出的完整 `#token=...` URL。
Console 自動挑選可用 port，終端 B 要保持開啟。

1. 確認 Overview 沒有環境、側欄沒有專案、Secrets 為空；若出現既有專案，先停下並檢查啟動命令的 `LODEX_HOME`。
2. 在側欄 Projects 旁按「＋」，Path 填剛才的 repo 絕對路徑，Name 填 `Manual demo`；展開 Options，Project ID 改為 `manual-demo`，Config source 留空，按 Add。
   專案選單或標題旁的 Edit 可以修改顯示名稱；後續 CLI 仍使用固定 ID `manual-demo`。
   選單的 Pin／Unpin 應在重新整理後保留排序；專案已有環境時，Delete 應明確阻擋。
3. 確認側欄有新專案，但仍沒有環境。點專案名稱，確認頁首來源路徑與 Details 中的設定來源。註冊不會自動 attach、prepare 或啟動服務。
4. 按 Manual demo 右側「＋ → New worktree」，Start from 填 `HEAD`，Branch 填 `manual/a`；Config source 留空，按 Create。
5. 再建立 `manual/b`。開啟兩個環境，確認 ID、worktree 路徑不同，且沒有已啟動的服務。

將環境 A／B 詳情頁顯示的 **ID 與 Path** 填入終端 A（Path 是 worktree 的絕對路徑；替換四個佔位字串）：

```sh
LODEX_MANUAL_A='環境 A 的 ID'
LODEX_MANUAL_B='環境 B 的 ID'
LODEX_MANUAL_A_PATH='環境 A 的 Worktree 絕對路徑'
LODEX_MANUAL_B_PATH='環境 B 的 Worktree 絕對路徑'
lx project list
lx worktree list
lx context --target "$LODEX_MANUAL_A"
```

**通過條件：** CLI 顯示的專案、ID、路徑與 Console 一致，且兩個 worktree 都在測試根目錄下。
畫面的 `Available` 只代表目錄存在，不代表 prepare 成功。

## 3. 缺少 secret → 明確修復 → prepare／verify

1. 在 A 的 Configuration 檢查 `DEMO_LABEL`、`PORT`、`DEMO_TOKEN` 引用。
2. 尚未新增 secret 時，在 A 的 Operations 執行 `prepare`；預期缺少 `manual-token` 的明確錯誤，不能顯示成功。
   這種執行前錯誤不一定建立 operation 記錄。
3. 前往 Secrets，新增名稱 `manual-token`、值 `manual-only-dummy-value`。使用這個假值即可。
4. 確認儲存後輸入值清空，列表不顯示值；Configuration 仍只顯示引用。
5. 回 A 明確再次執行 `prepare`，再執行 `verify`。不要期待自動重試。
6. 在 Operations 開啟輸出，確認成功；Resources 應出現 `demo-files`、`exclusive`、`present`。
7. 在終端 A 準備 B：

```sh
lx prepare --target "$LODEX_MANUAL_B"
lx run verify --target "$LODEX_MANUAL_B"
lx operation list --target "$LODEX_MANUAL_B"
lx secret list
```

**通過條件：** B 的 CLI 操作也出現在 Console；A 與 B 資源 ID 指向各自 `.runtime`。
這些 resource 是 recipe 回報的觀察記錄，不是 Lodex 自動掃描所有外部資源。

## 4. 啟動兩個服務、比較隔離與生命週期

1. 在 A 的 Services 對 `http` 按 Start；在終端 A 啟動 B：

   ```sh
   lx service start http --target "$LODEX_MANUAL_B"
   lx service list --target "$LODEX_MANUAL_A"
   lx service list --target "$LODEX_MANUAL_B"
   ```

2. 在 Console 分別開啟 A／B 的服務 URL。兩個頁面都應顯示 `Lodex manual check`，但 ID 不同，port 也不同。
3. 重新整理 HTTP 頁面後查看服務 logs，確認請求有記錄。
4. 只 Stop A：A 的 URL 應無法連線，B 仍可重新整理；再 Start A。
5. 在終端 B 按 Ctrl+C 關閉 Console。A／B HTTP URL 應仍可連線，終端 A 的 `service list` 也應顯示 running。
6. 在終端 B 重跑原本命令，開啟**新印出的 token URL**；既有環境與服務狀態仍存在。

**通過條件：** 兩個環境能同時執行、單獨停止；Console 關閉不會停止 managed services。
服務狀態通常約每 3 秒更新一次；實際開啟 URL 才是此示範的 HTTP 驗證。

## 5. 失敗紀錄與重新整理不重複執行

1. 在 A 的 Operations 執行 `fail`。預期 failed；輸出含 `Intentional failure`，原始退出碼為 7。
   若用 CLI 執行，Lodex 本身回傳 1，operation 記錄才是 recipe 的原始退出資訊。
2. 查看失敗紀錄後執行 `verify`，應成功；前一次失敗紀錄仍保留。
3. 執行 `slow` 一次，8 秒內重新整理 Console，等完成後檢查 Operations。
4. 在終端 A 檢查執行次數：

   ```sh
   wc -l "$LODEX_MANUAL_A_PATH/.runtime/runs.txt"
   lx operation list --target "$LODEX_MANUAL_A"
   ```

**通過條件：** 首次測試 `slow` 的檔案只有 1 行，僅有一筆該次 operation。
重複測試時每次手動執行才多 1 行；重新整理不應新增執行。
本步只測頁面重新整理，請勿在執行期間關閉 Console server。

## 6. 設定、匯出與 port

1. 在 A 的 Configuration 匯出 `.env`。於終端 A 執行：

   ```sh
   lx env show --target "$LODEX_MANUAL_A"
   ls -l "$LODEX_MANUAL_A_PATH/.env"
   git -C "$LODEX_MANUAL_A_PATH" check-ignore .env
   ```

   預期 `env show` 不含 secret 值、檔案權限 `-rw-------`，且 `.env` 被 Git 忽略。
   匯出的檔案本身包含已解析的假 secret，這是匯出功能的預期行為。
2. 用編輯器修改 A 的 `.env`，再匯出一次。應拒絕覆蓋已手動修改的檔案，而非悄悄覆寫。
   此檔只用於測試匯出；示範程式不讀 `.env`。
3. 停止 A 的 `http`，在 Configuration 將 PORT 改成另一個可用 port，例如 `24567`。
   若該 port 被占用，應顯示錯誤；改用另一個可用 port，不要停止不明程式。
4. 明確 Start A。新 URL 應可連線；B 的 port 與頁面不變。

**通過條件：** 改 port 不會自動重啟服務；CLI 與 Console 看到同一份設定。
改 port 後既有 `.env` 不會自動更新。一般值與 secret 引用需編輯各 worktree 的
`.lodex/project.toml`，目前沒有 Console 一般設定編輯器或 DB 覆寫層。

## 7. 配色、導覽、鍵盤與窄螢幕

| 操作 | 觀察重點 |
| --- | --- |
| 分別切換 Light、Dark、System | 列表、詳情、表單、確認框都可讀；黑白灰用於主要導覽，狀態仍有文字而非只靠顏色。System 跟隨既有 OS 外觀。 |
| 切換主題後重新整理 | 同一 origin 保留選擇；自動換 port 重啟是不同 origin，可能回到 System，並非儲存失敗。 |
| 搜尋 `manual/a`、切換專案／狀態篩選 | 顯示正確環境；清除篩選可找回 A／B。開啟詳情再返回，檢查篩選與位置是否容易理解。 |
| 開啟 Configuration／Operations 後重新整理、前進／返回 | URL 與選中分頁一致，不突然跳回 Services。 |
| 用 Tab 操作 New worktree、按 Esc 取消 | 焦點可見、不跑到遮罩後方，關閉後回到開啟按鈕。詳情 tabs 方向鍵移動焦點，Enter／Space 才切換。 |
| 瀏覽器縮至約 390px | 可展開導覽；表單、logs、確認按鈕可用；整頁不橫向溢出，寬表格可在容器內捲動。 |

除了是否通過，也記下「哪個詞看不懂、哪個按鈕找不到、資訊太多或太淡」。
這些是下一輪 UX 調整的依據。

## 8. 刪除保護、cleanup／remove／forget

### A：先驗證保護，再移除

1. A 仍有 running service 時，開啟 Cleanup & removal 的 Remove 預覽。
   確認路徑、服務、資源範圍清楚，Force 預設未勾選；先 Cancel 一次。
   再以一般模式確認移除，應拒絕並提示仍有服務。
2. Stop A 的 `http`。在終端 A 加入一個未追蹤檔：

   ```sh
   printf 'Keep this until I explicitly remove it.\n' > "$LODEX_MANUAL_A_PATH/keep-me.txt"
   ```

3. 再嘗試一般 Remove，應因 Git 未追蹤內容拒絕；檔案仍存在。不要勾 Force。
4. 確認該檔只有上述測試文字後，刪除它：

   ```sh
   rm -- "$LODEX_MANUAL_A_PATH/keep-me.txt"
   ```

5. 執行 Run cleanup。Resources 最新觀察應為 `removed`，worktree 與紀錄仍在。
6. 再 Remove A，應成功。A 的目錄（包含 ignored `.env`）被移除，紀錄仍可檢查，Git 分支仍保留。
7. **立即重新整理 B 的 HTTP URL**，仍應正常且 ID 為 B。
8. 對 A 執行 Unregister；它才從環境列表消失。

### 主 worktree：只能取消註冊，不能移除

1. 按 Manual demo 右側「＋ → Use existing」，Path 填最初測試 repo，按 Register。
2. 詳情應標示 Main，Preview removal 按鈕應停用，並說明只有 Lodex 建立且仍存在的 worktree 可移除；repo 仍存在。
3. 對它執行 Unregister，repo 與檔案仍應存在。不要對它執行 prepare 或啟動服務。

### B：完成正常清理

依序 Stop `http` → Run cleanup → Remove worktree → Unregister。
到 Secrets 確認 `manual-token` 仍在，再手動刪除該假 secret。

**通過條件：** cleanup 執行 repo 清理、remove 刪除 owned worktree、forget 取消註冊，三者效果不同。
Secrets 不隨環境清理而刪除，因為同一管理資料庫中的名稱可以被其他環境共用。

## 9. 收尾與記錄

1. 在終端 A 執行 `lx worktree list`、`lx secret list`，都應為空。
2. 關閉終端 B 的 Console（Ctrl+C）。先停止服務才能刪除管理資料，否則會失去正常 stop 所需的 handle。
3. 可先保留 `$LODEX_MANUAL_ROOT` 內的 operation／service logs，供回報問題。
   確認 A／B 服務皆已停止、環境已移除後，再清除測試根目錄：

   ```sh
   printf 'Disposable directory: %s\n' "$LODEX_MANUAL_ROOT"
   # 僅在確認上面是本次建立的目錄、且已完成服務清理後執行：
   case "$LODEX_MANUAL_ROOT" in
     /tmp/lodex-manual.*) rm -rf -- "$LODEX_MANUAL_ROOT" ;;
     *) printf 'Unexpected path; keep it for manual inspection.\n' ;;
   esac
   unset -f lx
   unset LODEX_MANUAL_ROOT LODEX_MANUAL_BIN LODEX_MANUAL_A LODEX_MANUAL_B
   unset LODEX_MANUAL_A_PATH LODEX_MANUAL_B_PATH
   ```

中途遇到意外時先保留測試目錄，記錄失敗步驟與錯誤訊息，使用
`lx service list --target ID`／`lx service stop http --target ID` 處理本次服務。
不要只刪目錄，也不要用廣泛的 `pkill` 或 Docker prune 清理。

建議回報格式（不要附完整 token URL 或真實 secret）：

| 步驟 | 結果（通過／失敗／不直覺） | 實際現象、截圖或 operation ID |
| --- | --- | --- |
| 註冊與建立 A／B | | |
| Secrets、prepare、verify、Resources | | |
| 雙服務隔離與 Console 重啟 | | |
| 失敗與重新整理 | | |
| 匯出與 port | | |
| Light／Dark、導覽、鍵盤、窄螢幕 | | |
| 刪除保護與完整清理 | | |

若要改測已安裝版本，先依 [更新 Console](console.md#update-the-installed-console)
安裝最新套件，再將第 1 步的 `LODEX_MANUAL_BIN` 改成 `"$(command -v lodex)"`。
保留同一套獨立測試資料流程；不要把工作區 build 成功當成已安裝副本也已更新。
