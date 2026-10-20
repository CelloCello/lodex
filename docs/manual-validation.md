# 用 Lodex 開發第一個小網站

[回 README](../README.md) · [Console 使用方式](console.md)

從**已安裝好包含 Console 的 Lodex**開始，花約 10–15 分鐘走完一次實際操作：
下載專案、用 CLI 註冊，再由 coding agent 完成設定、建立環境、啟停服務、查看 logs、修改與收尾。
Console 主要用來查看同步後的狀態，不必在 Console 重複執行操作。
本文以「任務環境」稱呼 Lodex 的 Environment／taskenv；worktree 指實際 Git 工作目錄，
兩者的關係見[用語對照](management.md#terminology)。
需要 Git、可在終端執行的 `python3`，以及能使用本機 skills 的 Codex。
網站本身不需要 Docker、Node.js 或 API key；你不需要手動編寫 TOML。

範例採用 MDN 的 [beginner-html-site-styled](https://github.com/mdn/beginner-html-site-styled)，
是一個只有 HTML、CSS 與圖片的入門網站。Lodex 設定交給 `lodex-project-setup` skill 產生。
本流程使用平常的 Lodex 管理資料庫，只操作新建的 `mdn-demo` 專案。

若要將目前原始碼工作目錄 的變更安裝到電腦，先依 [更新已安裝 Console](console.md#update-the-installed-console)
重建並重新安裝；即使版本號相同，也需要更新已安裝的套件副本。

## 1. 下載網站

在終端執行（第一次下載用 `git clone`）：

```sh
mkdir -p ~/dev/lodex-tutorial
cd ~/dev/lodex-tutorial
git clone https://github.com/mdn/beginner-html-site-styled.git website
cd website
pwd
```

記下 `pwd` 顯示的絕對路徑，等一下註冊專案時會用到。
若 `website` 已存在，改用另一個新目錄名稱即可，不必刪除原本的資料。

## 2. 用 project add 註冊專案

在剛下載的 `website` 目錄執行：

```sh
lodex project add mdn-demo "$PWD"
```

這一步會註冊 `mdn-demo`，並自動建立 `.lodex/project.toml` 的基本設定檔。
首次建立時輸出會包含 `configuration.method = initialized` 與下一步提示。
若已有設定，則驗證並保留，顯示 `existing`。
此時尚未建立任務環境，也尚未定義網站的啟動方式；不需要自己建立 `.lodex` 目錄。

## 3. 安裝並使用 project setup skill

先在終端一次安裝這份教學會用到的三個 skills：

```sh
lodex skill install lodex-project-setup
lodex skill install lodex-worktree
lodex skill install lodex-services
```

成功時會顯示各自的安裝位置 `~/.agents/skills/<skill 名稱>`；
已有相同版本會顯示 `already up to date`。這是使用者層級的安裝，其他專案也能使用。
更新 Lodex 後可以重跑同一命令更新 skill；它會替換有差異的已安裝副本，包含自行修改的內容。
想先預覽可加 `--dry-run`。

| Skill | 在本流程的用途 |
| --- | --- |
| `lodex-project-setup` | 產生專案設定並試跑 |
| `lodex-worktree` | 建立、檢查、移除與取消註冊任務環境 |
| `lodex-services` | 啟動、檢查、讀取 logs 與停止服務；配合 repo cleanup 收尾 |

**安裝只讓 AI 能使用 skill，尚未替網站產生設定。** 接著在 Codex 開啟剛下載的
`website` 資料夾，確認工作目錄是它，然後把下面整段貼到 **Codex 對話**（不是終端）：

```text
$lodex-project-setup

請替目前這個 MDN 靜態網站完成 Lodex 初始設定。
我已用 lodex project add 註冊為 mdn-demo，請沿用這個專案。

先檢查專案規則與檔案，再說明並直接實作所需設定，不要只給我 TOML 範例。
請提供名為 web 的本機網站服務，使用 Python 標準函式庫的 HTTP server，
只綁定 127.0.0.1，由 Lodex 分配各環境的 port，並提供可開啟的服務 URL。
提供名為 verify 的命令，確認 HTML、CSS 與圖片檔案存在。
這個網站不需要額外套件、secret、prepare 或 cleanup，請不要加入無用途的步驟。

請用 Lodex CLI 驗證設定並試跑 verify、web，確認 HTTP 頁面可開啟。
若為驗證而 attach 原始 worktree，完成後先停止本次啟動的服務，再 forget 該環境的註冊，
保留原始 repo 與 mdn-demo 專案，讓我稍後用 lodex-worktree skill 建立任務環境。
只將這次新增或修改的 Lodex 整合檔案提交到本機 Git，不要 push 或修改網站內容。
最後回報設定摘要、驗證結果與 commit，確認後續從 HEAD 建立的 worktree 可直接使用。
```

若 Codex 沒有辨識到 skill，確認安裝命令印出的 `SKILL.md` 存在，並重啟 Codex 後再試。
也可以在訊息中附上該 `SKILL.md` 的完整路徑，明確要求讀取並依照它執行。
Codex 支援明確指定 skill；CLI／IDE 可用 `$` 選取，安裝後未出現時可重啟。
參考 [OpenAI 的 skills 說明](https://learn.chatgpt.com/docs/build-skills)。

完成後，你只需要確認 AI 的回報：`web` 可啟動、`verify` 成功、設定已提交，
且試跑服務已停止。設定與必要腳本會放在 `.lodex/`；不必自己編寫。
本機 commit 讓後續 worktree 繼承完整設定，不需要 fork 或 push 到 GitHub。

## 4. 請 agent 建立環境並啟動網站

在剛才設定網站的 Codex 對話中貼上：

```text
$lodex-worktree

請為目前這個網站的 Lodex 專案 mdn-demo 建立任務環境。
先確認註冊的來源 worktree 路徑與目前網站一致，且前一步產生的 Lodex 設定已提交。
從來源 worktree 的 HEAD 建立分支 demo/change-title。
沿用專案的 Lodex 設定，這一步只建立環境，先不要啟動服務或修改網站。
若分支或環境已存在，先檢查並回報，不要刪除或重建它。
完成後回報 taskenv ID、分支與 worktree 絕對路徑，讓我稍後開啟該目錄進行修改。
```

AI 會透過 `lodex worktree create` 建立環境。確認它回報新的 ID 與路徑即可。
新目錄名稱例如 `demo-change-title--a3f19c82`，由建立時的 branch 名稱與短 ID 組成。
`/` 會轉成 `-`，Git branch 本身仍是 `demo/change-title`。請保留回報的完整 taskenv ID；
目錄尾端的 8 碼不是完整 ID。既有環境不會改名，之後切換或改名 branch 也不會搬動目錄。
**不需要再去 Console 按 New worktree**。建立成功不會自動切換目前 Codex 的工作目錄；
之後修改網站時，要開啟回報的新 worktree，或明確要求 AI 操作該絕對路徑。

接著在同一對話貼上以下提示詞，把 ID 與路徑換成剛才回報的值：

```text
$lodex-services

請操作 mdn-demo 的以下既有環境：
taskenv ID：<貼上 taskenv ID>
Worktree：<貼上 worktree 絕對路徑>
預期分支：demo/change-title

先核對路徑、分支與 taskenv ID，讀取該 worktree 的 Lodex 設定及既有服務狀態。
先用 lodex run verify --target <上述 taskenv ID> --json 檢查網站檔案；
若失敗，讀取該次 operation logs 並回報原因，先不要啟動服務。
若 verify 成功，請透過 Lodex 啟動 web；已 running 時先檢查並沿用，
若狀態 unknown 或先前啟動被中斷，先檢查並回報，不要盲目重啟。
確認服務 URL 的 HTTP 回應與頁面標題，並讀取 web 的近期 logs。
最後回報 taskenv ID、服務狀態、觀察時間、URL 與驗證結果，保持 web 運行供我開啟。
```

開啟 agent 回報的 URL，應看到 **Mozilla is cool** 的網站。
你現在已經有一份獨立 worktree 和它自己的 HTTP 服務。
原本 clone 的 `website` 是專案來源；接下來的修改要在新 worktree 中進行。

想同時看 Console，可在另一個終端執行：

```sh
lodex console
```

保持終端開啟，在瀏覽器開啟它印出的**完整 URL（含 `#token=...`）**。
側欄應能看到先前註冊的 `mdn-demo` 與 skill 建立的 `demo/change-title`。
點專案名稱可開啟完整環境清單，頁首顯示來源路徑；展開 Details 可查看設定來源。
CLI 與 Console 在相同 `LODEX_HOME` 下共用資料；本教學沿用預設值。
若看不到專案，先確認兩邊沒有使用不同的 `LODEX_HOME`。

在側欄開啟 `demo/change-title`，到 Operations 查看 `verify` 的結果，
到 Services 查看 `web` 的 running 狀態、URL 與 logs。這些是 agent 操作後共用的紀錄，
不必再按 Run 或 Start。Console 關閉不會停止服務；服務啟停仍交給 agent 明確執行。

## 5. 在 coding agent 中繼續開發

Lodex 的 taskenv 包含 Git worktree、設定與服務紀錄；coding agent 的對話則有自己的工作目錄。
**建立 taskenv 不會自動搬移既有對話。** 接下來讓 agent 使用剛建立的 Worktree 路徑，
就能在同一個環境修改程式，不需要另一個 Lodex「進入環境」命令。

### 建議：將既有 worktree 開成 Codex 本機專案

1. 從 skill 回報或 Console 詳情複製 **taskenv ID 與 Worktree 絕對路徑**。
2. 在 Codex 桌面版新增／開啟本機專案資料夾，選擇這個 Worktree 路徑。
   macOS 若已安裝 Codex CLI，也可以從終端開啟桌面版：

   ```sh
   codex app "/任務環境的完整路徑"
   ```

3. 在這個專案開啟新的 Codex 對話，使用 **Local／This computer**，保留現有 worktree。
   此處不要再選建立新的 Worktree，否則會產生另一份 worktree，與剛才的 taskenv 不同。
4. 新對話不會自動帶入先前設定網站的完整對話內容；將下方提示詞中的 ID 與路徑換成實際值再貼上。

如果使用 **Codex CLI**，可以直接從終端啟動：

```sh
codex -C "/任務環境的完整路徑"
```

如果使用 IDE 裡的 coding agent，就把該 worktree 開成 IDE 的專案／workspace，
再啟動 agent。這些方式都是使用同一份既有 worktree。
Codex 的工作目錄與模式可參考 [專案說明](https://learn.chatgpt.com/docs/projects)
及 [Local／Worktree 模式](https://learn.chatgpt.com/docs/environments/modes)；
開啟命令可參考 [CLI 文件](https://learn.chatgpt.com/docs/cli/reference)。

### 貼給 agent 的開發提示詞

```text
請在以下既有 Lodex 任務環境繼續開發：
專案：mdn-demo
taskenv ID：<貼上 taskenv ID>
Worktree：<貼上 worktree 絕對路徑>
預期分支：demo/change-title

先讀取此 worktree 的專案規則，確認 Git 頂層路徑、目前分支與 git status，
再用 lodex context --target <上述 worktree 絕對路徑> --json 核對 taskenv ID。
若不一致，先回報，不要修改來源 repo 或建立另一個 worktree。

請只修改這份 worktree 的 index.html，將 h1 標題由 Mozilla is cool 改成 Hello from Lodex。
保留其他現有變更，完成後用 lodex run verify --target <上述 taskenv ID> --json 驗證，
並檢查 git diff，回報修改檔案與驗證結果。這一步先不要 commit、push 或移除環境。
web 已由 Lodex 啟動，沿用既有服務，不要額外啟動另一個 HTTP server。
```

一般程式修改不必再呼叫 `lodex-worktree`；該 skill 用來管理環境，開發任務直接交給 agent 即可。
本例的 `verify` 只檢查網站檔案，畫面結果還要由你確認：
重新整理第 4 步開啟的服務 URL，應看到 **Hello from Lodex**，不需要重啟這個靜態 HTTP 服務。
最初 clone 的 `website/index.html` 應仍保留原標題。

若想留在原本的 Codex 對話，也可以貼同一段提示詞，明確指定目標 worktree。
但該對話必須有此目錄的讀寫權限，且每次命令都要指定正確路徑或 `--target`；
口頭要求或單次 shell 的 `cd` 不代表對話工作目錄已切換。
若無法寫入，改用上述開啟 worktree 的方式。

### 請 agent 查看服務狀態與 logs

在開發對話中貼上（ID 使用同一個任務環境）：

```text
$lodex-services
請檢查 taskenv <貼上 taskenv ID> 的 web，回報目前狀態、觀察時間、URL 與近期 logs 摘要。
請區分實際錯誤與一般 HTTP 請求紀錄，這一步只讀取，不要啟動、停止或重啟服務。
```

`service logs` 讀取近期輸出，不是持續追蹤；需要更新時再請 agent 查一次。
切換或重開對話時也可以用這段提示詞確認狀態，不需要重新啟動服務。
可順便在 Console 切換 Light／Dark、查看同步紀錄，再重新整理 Console。
環境與服務仍在，重新整理不會重新執行 `verify`。

想感受兩個任務同時開發，可**選做**：在 Codex 貼上：

```text
$lodex-worktree
請為 mdn-demo 從註冊來源 worktree 的 HEAD 再建立分支 demo/original 的任務環境。
先確認來源路徑，保留第一個環境，回報新環境的 ID 與絕對路徑；先不要啟動服務。
若分支或環境已存在，先檢查並回報，不要刪除或重建它。
```

然後重用第 4 步的 `lodex-services` 提示詞，換成**第二個環境的 ID、路徑與 `demo/original` 分支**，
請 agent 啟動它的 `web`；不要沿用第一個環境的目標 ID。
兩個 URL 的 port 應不同；新環境仍顯示原標題，第一個顯示修改後標題。
這裡的 `HEAD` 是註冊專案來源 worktree 的 HEAD，不是第一個任務環境的分支。

## 6. 完成工作，停止並移除環境

確認畫面與修改結果後，在剛才的開發對話請 agent 保留成果：

```text
請先核對仍在上述 taskenv 的 worktree 與 demo/change-title 分支，檢查 git diff。
只提交這次修改網站標題的 index.html，commit message 使用 Change demo website heading。
若該檔混有其他人的變更，先回報，不要一起提交；不要 push。
完成後回報 commit 與剩餘未提交變更，先不要移除環境。
```

等 agent 完成本次工作、確認成果已提交後，回到最初以 `website` 來源 repo 為工作目錄的
Codex 對話執行清理，避免 agent 的工作目錄正是即將刪除的 worktree。
保留並填入目標 ID 與路徑；不要只說「清理目前環境」。貼上：

```text
$lodex-services
$lodex-worktree

我已完成並提交這個教學環境的修改，請清理以下目標：
專案：mdn-demo
taskenv ID：<貼上要清理的 taskenv ID>
Worktree：<貼上要清理的 worktree 絕對路徑>
預期分支：demo/change-title

請從來源 repo 或其他仍存在的目錄執行，每個 Lodex 操作都明確指定目標 ID。
先核對 ID、路徑、分支、Git 狀態、服務與已知資源，只處理這個 Lodex-owned worktree。
若有未提交／未追蹤內容、不明服務或資源、目標不一致，先停下回報，不要 force 或丟棄資料。
請依序完成：
1. 透過 Lodex 停止此環境的 managed services，並確認已停止。
2. 檢查是否有 repo cleanup 命令；這個靜態網站預期沒有，沒有就回報不適用。
   若存在，先檢查其作用範圍；僅清除此教學環境的資源時才執行，確認成功後再繼續。
3. 取得 worktree remove 預覽，摘要說明將刪除的 worktree（含 ignored files）與保留內容。
   確認上述條件都符合後，直接以一般模式移除，不使用 --force。
4. 確認 worktree 已移除且 Git 分支與 commit 仍保留，再 forget 這個 taskenv 註冊紀錄。
不要刪除來源 repo、mdn-demo 專案、Git 分支、shared secrets 或其他環境。
最後回報停止、cleanup、remove、forget 各步結果；若有一步失敗，保留註冊紀錄並回報，勿繼續 forget。
```

若有建立 `demo/original`，等不再使用它時，再貼同一段並替換第二個環境的 ID、路徑與分支。
清理第一個環境後，第二個服務應仍能開啟。Console 可以用來觀察服務停止及環境從列表消失，
無須再按 Stop、Remove 或 Unregister。

這裡的順序是 **Stop → cleanup（如適用）→ Remove → Unregister**：
cleanup 是 repo 的資源清理，remove 刪除 worktree 但保留註冊紀錄，forget 才取消註冊。
三者不會互相代替；本例沒有 cleanup 命令，不能把「跳過」回報成「清理命令成功」。

**結果：** HTTP 服務停止、worktree 目錄移除，Git 分支與已提交的修改仍保留在本機 repo。
原始 `website` 目錄與 `mdn-demo` 專案註冊仍在，可以下次繼續建立環境。
若有開啟 Console，最後在其終端按 Ctrl+C 關閉它。
worktree 目錄移除後，該路徑上的 agent 對話無法繼續編輯原 worktree；
保留對話作紀錄即可，之後開發時再開啟有效的任務環境。

這條流程由 CLI 註冊、setup skill 產生並驗證設定、worktree skill 管理環境，
services skill 啟停服務與讀取 logs，coding agent 修改與提交程式。
Console 主要用來查看狀態；它的操作按鈕是替代入口，不必與 agent 重複執行。
skill 需要由 AI 執行；`project add` 或 `skill install` 本身不會呼叫 AI。
程式修改與 Git commit 則由開啟該 worktree 的 coding agent 完成。

第一次走完，先記下三件事就好：網站是否順利啟動、是否分得清楚來源與任務環境、
哪些按鈕或文字讓你猶豫。Secrets、錯誤注入、匯出保護等進階情境，可之後再看
[進階手動驗證](manual-validation-advanced.md)。
