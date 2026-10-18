# 三角洲行动 · 多杀集锦自动剪辑工具

打完一局《三角洲行动》，工具自动在录像里找出「N 秒内 M 杀」的精彩片段，剪成高光放进同一个文件夹。全部在你自己的电脑上运行，不上传任何东西。

## 能做什么

- **自动找多杀**：监控 WeGame 的录像文件夹，新录像录完后自动分析，找出 N 秒内至少 M 杀的片段（默认 90 秒内 2 杀，前留 20 秒、后留 5 秒，均可在网页里改）。
- **整理成集锦包**：每局生成一个文件夹，整局原片和高光放在一起；原片默认保留 7 天后自动删除以节省空间，高光一直保留。
- **网页里操作**：可以播放整局和高光；击杀、摸金只作为时间轴上的标记，片段单独管理：在当前位置建片段、拖动调整范围、删除，再导出想要的片段。
- **手动上传**：也可以手动选其他录像文件让工具识别。

## 环境要求

- Windows 10 / 11
- Python 3.11 及以上（项目实际使用 3.13）
- Node.js LTS（构建前端、读取官方标注点都要用）
- ffmpeg，需加入 PATH：`winget install Gyan.FFmpeg`，装完 `ffmpeg -version` 能运行即可
- 可选：NVIDIA 显卡（用 CUDA 版 PyTorch 加速识别）；没有显卡也能用 CPU，只是更慢

## 安装

```powershell
git clone https://github.com/SaberAlterP/delta-force-highlights.git
cd delta-force-highlights

# 后端
cd backend
python -m venv .venv
# 先装 PyTorch。有 NVIDIA 显卡装 CUDA 版（以 cu124 为例，按自己的 CUDA 版本调整）：
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
# 没有 NVIDIA 显卡就装 CPU 版：.venv\Scripts\pip install torch torchvision
.venv\Scripts\pip install -r requirements.txt
cd ..

# 前端
cd frontend
npm install
npm run build
cd ..
```

## 启动

在 `backend` 目录运行：

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后用浏览器打开 http://127.0.0.1:8000/ 。构建好的网页由后端直接提供，不需要另外开前端服务。

仓库里也带了几个启动脚本（都使用脚本所在目录的相对路径）：

- `启动剪辑工具.vbs`：双击后台静默启动（内部调用 `start-silent.ps1`），并自动打开浏览器。该脚本会同时启动 Vite 开发服务器（端口 5173），更适合开发时使用。
- `start-monitor.ps1`：只静默启动后端监控服务（端口 8000），不开浏览器。
- `start-local.bat`：以开发模式同时启动后端和 Vite 前端。
- `backend\start.bat`：以 `--reload` 方式启动后端，开发调试用。

以上脚本需要先完成上面的安装步骤。

## 首次设置

1. 打开网页，进入 **设置**。
2. **游戏 ID**：填你在击杀信息里显示的名字。
3. **录像文件夹**：在 WeGame 的「精彩时刻」设置里指定录像导出文件夹，把同一个路径填到这里。
4. **集锦文件夹**：存放生成结果的位置，不能在录像文件夹里面。
5. 勾选 **自动监控**，保存。

之后每打完一局，工具会等录像文件稳定后自动分析并归档。工具第一次运行时，录像文件夹里已有的旧录像只会登记为历史文件，不会被自动处理或删除；需要时可以在网页上逐段点击处理。

## 官方标注点（可选加速）

WeGame「精彩时刻」会把击杀、摸金等事件的时间记在本机。工具只读地读取 `%APPDATA%\icreate-pc-df\wonderfulDb`，读到就不需要逐帧识别，更快更准。

- 确认是否存在：按 Win+R，输入 `%APPDATA%\icreate-pc-df\wonderfulDb` 回车。里面应有以账号数字命名、没有扩展名的文件。
- 读取需要 Node.js。
- 读不到（目录不存在、没装 Node.js 等）会自动回退到画面识别。
- 设置页会显示检测结果，也可以手动指定该目录。

## 什么时候处理新录像

设置 → 「什么时候处理新录像」有三种：

- **打完游戏再处理（默认）**：检测到正在玩游戏就暂停，游戏关掉后再等几分钟（可设置）才开始。识别途中开始玩，会中断这次识别，把这局放回队列，玩完后重新开始，不跟游戏抢显卡。
  - 已内置三角洲行动和常见游戏的进程名，也可以在设置里补充别的游戏进程名。
  - 可选「任何全屏程序都算在玩」，不在名单里的全屏游戏也能识别；浏览器、播放器全屏看视频不算。
- **录完马上处理**：不管在不在玩，新录像写完就开始。
- **只在我点开始时处理**：新录像只登记到列表，在网页里点「开始处理」或「全部开始处理」。

检测只用 Windows 自带的进程列表和窗口信息，不需要额外安装任何东西。

## 使用显卡加速

设置 → 识别 → **使用显卡加速**。需要已安装 CUDA 版 PyTorch；没有 NVIDIA 显卡请关闭此项，使用 CPU 识别。

## 集锦文件夹里有什么

每局一个文件夹，里面包括：

- `整局原录像.mp4`：整局原片（到期自动删除，见下）
- 高光视频：识别出的多杀片段
- `录像说明.txt`：这一局的简要说明
- `识别记录.json`：识别过程和结果的详细记录
- `剪辑工程.json`：你在网页里改过的标记和片段
- `手动剪辑/`：你手动导出的成片

## 原片保留与删除

- 默认：归档成功后保留原片 7 天，到期自动删除，高光和记录都保留。
- 想一直保留：在网页里点「保留这局原片」。
- 想手动清理：可以只删原片，或删除整个集锦包。
- 导出失败、成片损坏等情况会暂停自动清理并在网页显示原因。

## 常见问题

**集锦里的击杀数和游戏结算不一样？**
集锦按「不同干员」计数：同一个人被击倒再补杀只算一次；摸金、载具击毁不计入。结算数则按游戏自己的口径，所以可能不同。

**网页里视频黑屏？**
先按 Ctrl+F5 强制刷新页面。

**我玩 4:3 拉伸，画面比例不对？**
在导出/预览选项里打开「拉伸为 16:9」。

## 隐私说明

所有分析、剪辑和存储都在你自己的电脑上进行，不上传任何视频或数据。服务只监听 127.0.0.1，局域网和外网都访问不到。

## 开发

运行测试：

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```

其中 `test_real_feed.py` 依赖本地的真实截图 `backend/tests/fixtures/killfeed/`（不随仓库发布），目录不存在时会自动跳过。

技术栈：后端 FastAPI；前端 Vue 3 + Vite + Pinia + video.js；视频与识别用 ffmpeg、OpenCV、EasyOCR。

```
backend/
  app/            后端代码（main.py 入口，api/ 路由，services/ 识别、归档、导出等逻辑）
  assets/         识别用资源
  test_*.py       单元测试
  requirements.txt
  start.bat
frontend/
  src/            Vue 3 前端源码
  package.json
start-local.bat / start-silent.ps1 / start-monitor.ps1 / 启动剪辑工具.vbs   启动脚本
```

识别依赖当前版本游戏的击杀信息界面；修改 HUD 缩放或录像比例后，识别效果可能下降。
