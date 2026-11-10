# 实时音视频翻译模块 v1.0

本地部署的实时音视频播放 + 实时翻译字幕模块。打开播放器网页，粘贴视频地址，即播即出中文字幕。

> **项目定位（2026-11-10）**：本地优先的实时字幕翻译工具，**不上架 Chrome 应用商店**（省 $5 注册费与审核风险），通过开发者模式加载扩展使用；全链路本地推理、零云依赖、零 API 费用。
>
> **开源**：本项目以 MIT 许可证开源，欢迎 issue / PR。开发过程日志与验证截图含本机环境信息，不随仓库发布。

## 与同类方案的关系

动手前先做过同类方案探查（方法见下），完整对比与可复用点见 [docs/同类方案对比_v1.0.md](docs/同类方案对比_v1.0.md)。

| 方案 | 形态 | 许可证 | 与本项目的差异 |
|---|---|---|---|
| Chrome 内置实时字幕 + 翻译 | 浏览器原生 | 闭源免费 | 仅 Chrome 支持且需要站点有音轨；翻译走云端 |
| [sokuji](https://github.com/kizuna-ai-lab/sokuji) 1484★ | Chrome 扩展 + 多种云/本地引擎 | AGPL-3.0 | 本项目只取架构思路，**不复用其代码**（AGPL 传染） |
| [crx-live-translate](https://github.com/botbahlul/crx-live-translate) 126★ | Chrome 扩展 | MIT | 可借鉴其扩展侧音频采集写法 |
| [youtube-subtitle-translator](https://github.com/orange2ai/youtube-subtitle-translator) 41★ | 扩展 | MIT | 仅限 YouTube 有字幕轨的场景 |
| [kami-subs](https://github.com/MohammdKopa/kami-subs) 8★ | Python 本地服务 | MIT | 同类形态，可借鉴流式管线组织 |

**本项目立足点**：①不依赖站点字幕轨（无字幕轨也能出字幕）②端侧流式 ASR（sherpa-onnx）+ 本地 CT2 翻译，全程离线、0 元 ③中文优先的悬浮字幕浮层 ④Windows 一键 `启动.bat`。
**已知劣势**：端到端 1.66–2.54s（未达 ≤1s）、需本机 Python 环境、仅 Windows、无 TTS 播报。

## 目录结构

```
实时音视频翻译模块/
├─ 启动.bat                  # 一键启动（服务 + 打开播放器页）
├─ README.md                 # 使用说明、实测数据、已知限制
├─ LICENSE                   # MIT
├─ .gitignore
├─ pyproject.toml            # 包元数据（offline_translate 可 pip install -e . 独立安装）
├─ install_offline_models.py # 一键安装 Argos ja→en / ko→en / en→zh 离线翻译模型（约 225MB）
├─ docs/                     # 设计、同类方案对比、验证报告
│   ├─ 同类方案对比_v1.0.md
│   ├─ 插件化封装方案_v1.0.md
│   └─ 字幕显示问题_根因与验证报告_v1.7.md
├─ server/                   # FastAPI 服务（8790）：WS 音频管道、流式 ASR、轨道路由
├─ offline_translate/        # 本地翻译引擎（CT2 / Argos / Google 备选）
├─ chrome_ext/               # Chrome MV3 扩展（tabCapture → 本地服务 → 悬浮字幕）
├─ web/                      # 播放器页
├─ models/                   # sherpa-onnx 流式模型 + CT2 翻译模型（体积大，不入库）
├─ tests/
│   ├─ test_*.py             # 单元/集成测试入口
│   ├─ e2e/                  # 端到端脚本（CDP 装扩展 + 真视频实测）
│   ├─ bench/                # 性能基准（ASR / MT 线程数 / 流式管道）
│   ├─ manual/               # 一次性探针（延迟、路由、退化解、模型下载）
│   ├─ legacy_gui/           # 旧 GUI 点击方案（已被 CDP 取代，仅本地留档、不入库）
│   ├─ fixtures/             # 测试素材（字幕编码样本、TTS 音频、测试视频）
│   └─ _tmp/                 # 临时运行目录（日志/缓存，不入库）
├─ logs/                     # 运行日志 logs/server.log（不入库）
└─ static_hls/               # RTMP 转 HLS 的运行期切片目录（不入库）
```

## 从零安装（首次使用）

仓库**不含** Python 虚拟环境、ASR 模型与翻译模型（体积大、与机器相关），clone 后按三步准备。实测环境：Windows 11 + Python 3.13 + 纯 CPU，**无需显卡、无需系统 ffmpeg**（用 imageio-ffmpeg 内置二进制）。

### ① 建虚拟环境、装依赖

```powershell
cd <本项目根目录>
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install fastapi uvicorn httpx websockets numpy charset-normalizer sherpa-onnx ctranslate2 sentencepiece faster-whisper imageio-ffmpeg argostranslate edge-tts pyttsx3
```

以上为 2026-11-10 实测版本：fastapi 0.162.2 / uvicorn 0.54.0 / httpx 0.28.1 / websockets 17.4 / numpy 2.5.4 / sherpa-onnx 2.0.1 / ctranslate2 4.8.5 / sentencepiece 0.2.3 / faster-whisper 1.2.1 / imageio-ffmpeg 0.8.1 / argostranslate 1.11.0 / edge-tts 7.3.1 / pyttsx3 2.99。

### ② 放模型（两套，缺了会降级）

**a) 翻译模型（必须有，否则出不来中文）** —— 本地 CT2 翻译直接复用 Argos 模型包目录 `%USERPROFILE%\.local\share\argos-translate\packages`：

```powershell
.venv\Scripts\python.exe install_offline_models.py
```

装完 `ja→en`、`ko→en`、`en→zh` 三个包（约 225MB，官方免费源），`local_ct2` 引擎即可离线出中文；细节见下方「离线日/韩翻译模型安装」。

**b) 流式 ASR 模型（要低延迟才需要）** —— 从 [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) 下载对应 `tar.bz2`，解压到 `models/` 并**保持目录名不变**：

| 语种 | 目录名 | int8 encoder |
|---|---|---|
| 中/英 | `sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16` | 约 50MB |
| 日 | `sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10`（sherpa 无日语单语流式模型，用八语种包） | 296.6MB |
| 韩 | `sherpa-onnx-streaming-zipformer-korean-2024-06-16` | 127MB |

不放模型服务也能起，会自动回落 faster-whisper（首次运行自动下载 small 模型），代价是首条字幕 2.7-8.1s。

### ③ 启动

双击 `启动.bat`，浏览器自动打开 http://127.0.0.1:8790。健康检查：`/api/status`、`/api/engines`（看翻译链与离线可译语种）。

## 环境变量（可选调参，不设即用默认值）

改法是启动前设环境变量，例如 `set LIVESUB_DEBUG=1` 后再双击 `启动.bat`，或写进系统环境变量。**默认值已按 4 核 CPU 调过，改之前先看「作用」列。**

| 变量 | 默认 | 作用 | 定义位置 |
|---|---|---|---|
| `LIVESUB_ASR` | `auto` | `auto` 自动路由 / `stream` 强制流式 / `whisper` 强制 whisper | `server/browser_audio.py` |
| `LIVESUB_LANG` | 空 | 全局语种提示（等价于所有连接都带 `?lang=`），跳过嗅探 | `server/browser_audio.py` |
| `LIVESUB_MODEL` | `tiny` | whisper 通道模型档位，`base`/`small` 提精度但更慢 | `server/browser_audio.py` |
| `LIVESUB_SNIFF_SEC` | `2.0` | 自动识别时先攒多少秒音频做语种嗅探 | `server/browser_audio.py` |
| `LIVESUB_LANG_MIN_PROB` | `0.5` | 嗅探置信度低于此值改走 whisper 通道 | `server/browser_audio.py` |
| `LIVESUB_RMS_GATE` | `250` | 静音门限，低于此 RMS 的窗口不送 ASR（防 tiny 在静音处瞎编） | `server/browser_audio.py` |
| `LIVESUB_DEBUG` | 空 | 设任意值即输出 `[dbg]` / `[asr]` 逐块日志 | `server/streaming_asr.py`、`server/main.py` |
| `LIVESUB_STREAM_MODEL` | 内置 zh/en 目录 | 覆盖中/英流式模型目录 | `server/streaming_asr.py` |
| `LIVESUB_STREAM_MODEL_JA` / `_KO` | 内置 ja/ko 目录 | 覆盖日/韩流式模型目录 | `server/streaming_asr.py` |
| `LIVESUB_STREAM_THREADS` | `2` | sherpa-onnx 推理线程数（与翻译抢核，2 线程够用） | `server/streaming_asr.py` |
| `LIVESUB_PARTIAL_MS` | `600` | 中间结果最短刷新间隔（毫秒） | `server/streaming_asr.py` |
| `LIVESUB_PARTIAL_MIN_CHARS` | `3` | 少于该字符数的 partial 不推送 | `server/streaming_asr.py` |
| `LIVESUB_RULE1_SILENCE` / `RULE2_SILENCE` | `1.0` / `0.4` | 断句规则：停顿多久判一句结束（秒） | `server/streaming_asr.py` |
| `LIVESUB_RULE3_LEN` | `12` | 断句规则：单句最长字符数 | `server/streaming_asr.py` |
| `LIVESUB_MT_GOOGLE` | `0` | 设 `1` 时流式管道优先走 Google 翻译（需该网络可达） | `server/streaming_asr.py` |
| `LIVESUB_MT_TIMEOUT` | `1.2` | 流式管道单次翻译超时（秒） | `server/streaming_asr.py` |

测试脚本另有 `LIVESUB_EXT`（扩展目录）、`CDP_PROFILE`（CDP 用户目录），见 `tests/e2e/cdp_e2e.py`。

## 开箱使用

**双击 `启动.bat`** → 浏览器自动打开 http://127.0.0.1:8790 → 在输入框粘贴视频地址 → 回车播放。


支持的视频源：

| 类型 | 示例 | 播放方式 |
|---|---|---|
| 本地文件 | `D:\videos\lecture.mp4` | 浏览器直链 |
| HTTP(S) 直链/HLS | `https://example.com/live.m3u8` | 浏览器直链（hls.js） |
| RTMP/RTSP 流 | `rtmp://live.example.com/app/key` | 服务端自动转本地 HLS |

## Chrome 扩展：任意网站视频实时字幕

扩展目录 `chrome_ext/`（MV3，v1.1.0，7 个文件），抓取当前标签页音频 → 本机 8790 服务 → 识别+翻译 → 页面悬浮字幕。**不依赖站点是否提供字幕，B 站/YouTube/任意 HTML5 视频都适用；支持在弹窗里自选视频语种（自动/中/英/日/韩）。**

**安装（Chrome 137+ 已移除 `--load-extension`，只能走界面）**

1. 先启动服务（双击 `启动.bat`，保持 8790 常驻）
2. Chrome 地址栏开 `chrome://extensions/` → 右上角打开「开发者模式」
3. 点「加载未打包的扩展程序」→ 选本项目下的 `chrome_ext` 目录
4. 列表出现「实时字幕翻译（本地）」即成功（**已在本机 Chrome 156.0.8078.80 实测装好并启用**）

**使用**

- 打开任意视频页并播放 → 点工具栏扩展图标（灰底「实」字块）→ 弹窗里选语种 → 点「开始字幕」
- 语种下拉（v1.1.0 新增）：`自动识别` / `中文` / `英语` / `日语` / `韩语`，选择会记在本地，下次打开弹窗仍是你上次选的；点「开始字幕」时生效，**运行中改语种会自动重连**（字幕会中断约 1-2s 后恢复）
- 按钮出现蓝色「译」角标 = 正在翻译；再点一次「停止字幕」= 结束
- 字幕：上方灰色小字＝识别原文，下方黑底白字＝中文译文，6s 无新内容自动消失；全屏时自动跟随
- tabCapture 会"截走"标签页声音，扩展已把音频回接扬声器，**原声照常可听**
- **语种为什么重要**：选 `自动识别` 时服务端要先攒 2s 音频再判断语种，首条字幕从音频起始算约 **4.3s**；**显式指定语种会跳过嗅探**，直接进对应流式模型，首条约 **1.2-1.9s** 到达（ASR+翻译侧仅 128-903ms，`LIVESUB_DEBUG=1` 实测，见下方「流式 ASR」小节）。代价是识别结果被锁死——选了日语而音频其实是英语，就会识别错，所以只在你确定视频语言时手选。
- **每个标签页要点一次图标**：Chrome 的 tabCapture 安全模型要求扩展先在该标签页被"用户调用"（activeTab）。用 CDP 直接调扩展内部 `start(tab)` 会被 Chrome 拒绝，一手报错（2026-11-09 实测）：
  `Extension has not been invoked for the current page (see activeTab permission).`
- 快捷键 **Alt+Shift+S 尚未生效**：manifest 里声明了 `commands.toggle`，但 Chrome 未自动绑定（Secure Preferences 中只有 `_execute_action`，且 Alt+Shift+S 与系统输入法冲突）。需手动去 `chrome://extensions/shortcuts` 绑定，或直接用图标。快捷键路径会使用**上次存储的语种**。
- **改动扩展代码后必须手动重载**：`chrome://extensions/` → 找到「实时字幕翻译（本地）」→ 点圆形刷新「重新加载」（扩展 ID `pfijeighbbpkejnpkgmlngbhnfcmiaii` 不变），否则仍在跑旧版本。

**实测（2026-11-09）**

| 项 | 结果 | 证据 |
|---|---|---|
| 装入真机 Chrome 156.0.8078.80 | 成功，扩展列表 v1.0.0、无报错徽标；扩展 ID `pfijeighbbpkejnpkgmlngbhnfcmiaii`（LOAD_UNPACKED） | 实测（截图本地留存） |
| 音频上行链路 | `ws://127.0.0.1:8790/ws/audio` 建连成功（netstat 新增 Established） | — |
| 第三方站点出字幕 | B 站视频播放中，浮层先后出现「You just put your lips together / 你刚刚把嘴唇放在一起」等多条，内容随播放更新 | 实测（截图本地留存） |
| 旧链路单条耗时（whisper tiny） | `asr_mt` **5168ms / 5744ms**，端到端约 7-9s | 已弃用 |

**v1.1.0 语种选择（2026-11-10，仅静态验证，端到端待补测）**

| 项 | 结果 | 方式 |
|---|---|---|
| 三个脚本语法 | `node --check` popup.js / background.js / offscreen.js 全部 exit 0 | 实跑 |
| manifest 合法性 | `JSON.parse` 通过，`version=1.1.0`、`permissions` 含 `storage`、`action.default_popup=popup.html` | 实跑 |
| WS URL 拼接 | `auto`→`ws://127.0.0.1:8790/ws/audio`；`zh/en/ja/ko`→末尾追加 `?lang=<code>` | 实跑（node 打印五语种输出） |
| 真实浏览器点「开始字幕」 | **已实测**（2026-11-10 晚，见下方「浏览器端到端实测」） | 实跑 |

**浏览器端到端实测（2026-11-10 晚，真 Chrome + 真扩展 + B 站第三方视频）**

测试盘：独立 Chrome 157.0.8103.39 实例通过 CDP `Extensions.loadUnpacked` 装载 `chrome_ext/`，`Extensions.triggerAction` 授予 activeTab 后由后台 `toggle(tabId,'ja')` 启动，全程无人手点击。

| 场景 | 视频 | 首条字幕到达（从点「开始字幕」算） | 服务端 `latency_ms` | 翻译 | 浮层 |
|---|---|---|---|---|---|
| 中文解说视频 + ja 模型（语种选错，对照） | B 站 `BV1zcWH6sEXv`（2:19） | **1663ms**（55s 内出 73 条） | partial 14-226ms | 跳过（`engine=None`，被判为中文） | 只出主行 |
| **日语 NHK 新闻 + ja 模型（正测）** | B 站 `BV17mWJ6LE7C`（30:00） | **1964ms**（首条是片头 `♪`；45s 内出 22 条） | final 131/219/490ms；partial 中位 ≈207ms | `engine=local_ct2`，`mt_ms` 18-638ms | 日文原文小字 + 中文主行，正常 |
| 韩语 SBS 新闻 + ko 模型 | B 站 `BV1NEWs66EK3`（37:06） | **2535ms**（40s 内出 33 条） | 多数 501-975ms，最差 1 次 **6382ms** | `engine=local_ct2`（ko→en→zh 两跳），多条译文不通顺 | 韩文原文 + 中文主行，正常 |
| 英语 TED 演讲 + en 模型 | YouTube `iCvmsMzlF7o`（20:04） | **13546ms**（片头 10s 是音乐+掌声，无语音） | partial 180-800ms | `engine=local_ct2`（en→zh 直连），`mt_ms` 20-197ms | 英文原文 + 中文主行，正常 |
| **日语 NHK 新闻 + ja（v1.14 复测：采集 4096→2048 + 翻译深暖后）** | B 站 `BV17mWJ6LE7C`（与第 2 行同片复测） | **3849ms**（本轮片头无 ♪，首条=首句人声「七です」，与 1964ms 不可直接比；45s 出 24 条） | partial 91-586ms（中位 ≈244ms）；final 119-500ms | `engine=local_ct2`，`mt_ms` **19-465 全程无尖峰**（深暖已消除首次翻译冷启动） | 日文原文 + 中文主行，正常 |

- **v1.14（2026-11-10）管道侧两项优化已生效并有证据**：①采集缓冲 256ms→128ms/块（`[dbg] chunk#N` 节奏实测 128ms）；②翻译深暖（`warm()` 末尾对每个语言对跑一次 dummy 推理），复测 `mt_ms` 19-465ms、无 v1.11 的 1032ms 冷启动尖峰。端到端 ≤1s 仍未达成，且首条到达受片头有无人声主导（同片两轮 1964ms/3849ms 之差即由此来），管道对比只看服务端 latency/mt_ms。
- **v1.14 退化解拦截增强**：`is_degenerate()` 由「特殊字符占比 ≥20%」一层扩为四层——⓪ `⁇`(U+2047) 出现 ≥1 个即拦截（复测抓到「临 ⁇ 县和 ⁇ 冈县」占比仅 ≈11% 的漏网形态）①占比 ≥20% ②同一子串（2-16 字符）连续重复 ≥4 次（拦 v1.13「活佛」×200+）③纯标点（拦「. . .」）。单测 12/12 通过，不误伤正常中/日/英短句。

- 站点覆盖：B 站（中/日/韩三条）+ YouTube（英语）均跑通，说明链路不绑定特定播放器。
- **YouTube 前置广告陷阱**：首次测试时 `video.duration=56.4`，识别出的全是广告歌词（`STYLE COUNTS SO GIVE IT YOUR TOUCH`）——tabCapture 抓的是标签页正在响的声音。脚本已加等待：`#movie_player.ad-showing` 消失且 `duration>120` 后才点「开始字幕」。
- **「首条到达」不是纯链路指标**：NHK 1964ms / SBS 2535ms / TED 13546ms 的差异主要来自**片头有没有人声**，不是管道快慢（TED 前 10s 是音乐+掌声）。比较优化效果时应统一以「音频出现人声」为起点。
- **ko→zh 质量明显差于 ja→zh**：ko 走 `ko→en→zh` 两跳，实测多条明显错译；并出现两类未被拦截的退化解——①「活佛」重复 200+ 次（`mt_ms=6324`）②整条只剩 `. . .`。现有 `is_degenerate()` 只按特殊字符占比 ≥20% 判断，对重复循环与纯标点无效。

- 采集侧确认：`[dbg] chunk#N dec=1-224ms` 与真实节奏一致（256ms/块），说明 tabCapture → offscreen → WS 整条上行链路通。
- **踩坑记录**：把 `<video>` 设成 `muted=true` 去骗自动播放，tabCapture 抓到的是**静音**（`[dbg] ... text=''`，浮层零字幕）。tabCapture 抓的是标签页实际输出的声音，测试时必须保持 `muted=false`。
- **结论（如实）**：有语音开头的三条（中/日/韩）端到端首条 **1.66-2.54s**，**未达到 ≤1 秒**（TED 的 13.5s 是片头 10s 无语音，不计入管道延迟）。多出来的 1.2-2.2s 主要不是翻译慢，而是 ① `ScriptProcessor(4096)≈256ms` 采集缓冲；② 流式 ASR 需要先攒到足够的音频才吐第一条 partial；③ 视频开头无语音时还要等嗓音出现。


**流式 ASR 复测（2026-11-09，sherpa-onnx，替代 whisper 窗口方案）**

服务端 `/ws/audio` 收到真实 16kHz PCM16 字节流（0.25s/块，模拟浏览器推流）时的**音频到达 → 字幕产出**延迟：

| 指标 | 实测值 |
|---|---|
| 首条字幕 `first_subtitle_ms` | **63ms** |
| 中位延迟 p50 | **约 200-350ms**（多条 partial：63/153/189/205/277/347/528ms） |
| 最差单条 | 1006ms（高负载瞬时，1 次） |
| 翻译耗时 `mt_avg_ms` | 291ms（local_ct2，intra_threads=2） |
| 引擎 | `local_ct2`（本地 CT2 int8，0 元） |

> 口径说明：以上是**服务端链路**（音频字节进入 → 字幕 JSON 推出）的实测值。**浏览器端到端**（tabCapture 采集 256ms 缓冲 + WS + 服务端 + 渲染）尚缺一次真实点击后的实测记录，见下条。

**日/韩流式 ASR 接入（2026-11-10，替代 ja/ko 的 whisper 回落）**

ja/ko 原先只有 whisper 通道（首条 2.7-8.1s）。现已下载两套 sherpa-onnx 流式模型接入同一管道，ja/ko 与 zh/en 一样逐块增量解码：

| 语种 | 模型（`models/` 下，官方 release 原样解压） | encoder | 启动预热 |
|---|---|---|---|
| ja | `sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10`（八语种包，sherpa 无日语单语流式模型） | int8 296.6MB | 16.9s |
| ko | `sherpa-onnx-streaming-zipformer-korean-2024-06-16` | int8 127MB | 5.3s |

实测（`/ws/audio` 真字节流；`latency` = **产出该文本的那个音频块到达 → 字幕推出**，不含该句更早部分已经播过的时间）：

**A. 批量快推探针（2026-11-10 上午，旧口径）**：音频一次性灌入，多数走 `queue.Empty` 的「断供 flush」而非真实 endpoint，只代表服务端处理能力：

| 路径 | 首条 latency | 首条到达（含等待） | 识别→译文 |
|---|---|---|---|
| ja · 显式 `?lang=ja` | 218 / 520 / 775ms | 1.3-1.8s | 今日はとてもよい天気です → 今天天气不错 |
| ko · 显式 `?lang=ko` | 198 / 202 / 295ms | 1.2-1.4s | 오늘은 날씨가 정말 좋습니다. → 今天天气不错 |
| ja · 自动嗅探 | 1572 / 1818 / 3274ms | 4.9-8.3s | 同上（短句只出 1 条 final） |
| ko · 自动嗅探 | 698 / 899 / 1948ms | 3.9-5.1s | 同上 |
| zh / en · 自动嗅探（回归） | 286-463 / 335-3949ms | — | 正常，仍为 `asr=stream` |

**B. 真实节奏复测（2026-11-10 晚，`LIVESUB_DEBUG=1`，0.25s/块逐块推送，5.5-5.7s 音频）**：这才是浏览器推流的口径，**走的是真实 endpoint 分支**（`ep=True`），不是 flush：

| 路径 | 首条 partial | 首条 final | final 触发 | 从音频起始算的首条到达（推算） | partial 序列 |
|---|---|---|---|---|---|
| ja · 显式 `?lang=ja` | 215ms | **128ms** | endpoint（chunk#13 `ep=True`） | ≈1.2s | 215 / 106 / 151 |
| ko · 显式 `?lang=ko` | 903ms | **188ms**（第2句 89ms） | 第1句 endpoint（chunk#14）；第2句 断供 flush | ≈1.9s | 903 / 315 / 144；178 / 127 / 104 |
| ja · 自动嗅探 | 2327ms（进程内首次）/ 721ms（热态） | 1937ms / 1205ms | endpoint（chunk#3） | 首轮 ≥4.3s；热态 ≈2.7-3.5s（均不含 whisper 判语种耗时） | 2327（单条）/ 721（单条） |

> 单块解码耗时：ja（八语种模型）54-135ms、ko 24-104ms。ja 自动组的 `chunk#1 dec=554-1177ms` 是把嗅探期攒的约 2s 音频**合并成一次解码**的代价（三轮波动来自 CPU 争抢，非冷启动）。另外**进程内第一次**调用某语言对的 partial 翻译有明显冷启动：ja→zh 首次 1032ms、之后均值 161.6ms；ko→zh 首次 795ms、之后 68-196ms。

要点（都是实测踩出来的）：

- **显式 `?lang=` 跳过 2s 嗅探**，首条稳定在 1.2-1.9s 到达、ASR+翻译侧 128-903ms；不加提示时仍固定付「攒 2s 音频 + whisper 判语种 + 重喂 blob 一次性解码（实测 554-1177ms）」三重成本，首条首轮 ≥4.3s、热态 ≈2.7-3.5s。
- **`latency_ms` 的计时起点是「产出该文本的那个音频块」**，不是整句开头。所以看到 903ms 并不等于翻译慢了 0.9s——ko 那句的 `오늘은` 是在第 5 块（音频已播 1s）才攒够 3 个字符触发 partial，其中翻译占 795ms 才是真正要优化的部分。
- **显式语种在真实节奏下走 endpoint 分支**（`[dbg] chunk#N ep=True` 紧随 `[stream] final`），不是音频推完后的断供 flush；flush 分支只在客户端停止推流或句末没人再说话时兜底。
- 韩语必须用 `OnlineRecognizer.tokens()` 拼接还原词间空格：`get_result()` 返回连写 `오늘은날씨가정말좋습니다.`，本地 CT2 会翻成乱码 `今取为所取之所取.`；按 token 拼接 → `오늘은 날씨가 정말 좋습니다.` → `今天天气不错`。
- 识别器创建后做 0.6s 静音空跑预热，否则首个真实音频块有 500-800ms 图初始化尖峰（正好落在首条字幕上）。
- 翻译链启动时**全量**预热（含 ja→en / ko→en 中转段），否则首条日语字幕要现载 113MB 包（实测 +1-2s）。
- 三套识别器同进程常驻，内存增量实测：zh 118MB / ja 498MB / ko 653MB。可用 `LIVESUB_STREAM_MODEL_JA` / `_KO` 改路径；目录缺失时该语种自动回落 whisper（日志打印「模型缺失」），服务不受影响。
- 模型来源：sherpa-onnx 官方 GitHub release 的 `tar.bz2`（0 元）；HF `resolve` 端点本机不可用（401）。

**已知限制（如实标注）**

1. **"字幕延迟 ≤1 秒"未达成**：服务端链路达标（音频块到达 → 字幕推出：final 128-490ms、partial 中位 ≈207ms，`LIVESUB_DEBUG=1` 真节奏实测），但**浏览器端到端首条字幕实测 1.66-2.54s**（2026-11-10 晚，真 Chrome + 真扩展 + B 站中/日/韩 + YouTube 英语，见「浏览器端到端实测」）。缺口来自采集缓冲（v1.14 已由 256ms 减半至 128ms/块）+ 流式 ASR 需要先攒到足够音频才吐首条 + 视频开头无语音时的等待，不是翻译慢。优化方向见 issue 讨论。
2. **韩语译文质量弱于日/英**：ko 走 `ko→en→zh` 两跳（无 ko→zh 直连模型），实测多条明显错译。~~退化解未拦截~~问题已在 v1.14 修复：`is_degenerate()` 扩为四层判定（`⁇` 单字符黑名单 / 特殊字符占比 / 子串重复循环 / 纯标点），单测 12/12 通过。**韩语方向自 2026-11-10 起冻结**，ko 两跳质量暂不修（改善需要 ko→zh 直连模型，欢迎 issue 讨论）。
3. **ASR 语种**：流式 zipformer 已覆盖**中/英/日/韩**（三套模型，见上节）。`LangRoutePipeline` 未指定语种时先攒 2s 音频用 whisper 判语种，`zh/en/ja/ko` 且置信度 ≥0.5 走对应流式模型，其它语种或低置信回落 whisper 通道。已知语种用 `LIVESUB_LANG=ja` 或 `?lang=ja` 可**跳过嗅探**（首条 1.2-1.9s 到达）；自动嗅探除 2s 嗅探外，还要为重喂的缓存音频付一次整体解码（实测 554-1177ms），首条首轮 ≥4.3s、热态 ≈2.7-3.5s。未覆盖语种走 whisper 通道时仍是 2.7-8.1s。
4. **翻译引擎**：本机访问 Google 两个免费端点均不通，默认只用 `local_ct2`；要启用 Google 需设环境变量 `LIVESUB_MT_GOOGLE=1`（会白等超时，不建议）。
5. **一个标签页一次点击**不可绕过（Chrome 安全模型，见上）。
6. **线程数**：CT2 `intra_threads` 默认 2（4 核 8 线程机器实测 1/2/4 线程平均 130/89/205ms，4 线程与流式 ASR 抢核反而最慢）。
7. **YouTube 有前置广告**：广告期间 tabCapture 抓到的是广告音频，测试/使用需等正片开始（脚本判定 `#movie_player.ad-showing` 消失且 `duration>120`）。

## 字幕文件加载（SRT / VTT / ASS，多语言编码）v1.7

播放器页新增「加载字幕文件」入口：选本地 `.srt/.vtt/.ass/.ssa` → 前端把**原始字节** POST 到 `/api/subtitle/parse` → 服务端自动识别编码并解析 → 按 `video.currentTime` 过滤 `start<=t<end` 渲染到 `#fileSubs`（置顶层，不影响实时字幕层）。

为什么必须走服务端解码：日文字幕大量是 Shift_JIS(CP932)/EUC-JP，浏览器 `TextDecoder` 只能按调用方指定编码解码，无法自动判定。服务端用 `charset_normalizer` + 多编码打分兜底。

**实测支持矩阵（2026-11-09，8 样本 × 9 断言 = 72/72 通过）**

| 样本 | 格式 | 编码 | 条数 |
|---|---|---|---|
| ja_utf8.srt | SRT | UTF-8 | 4 |
| ja_utf8bom.vtt | VTT | UTF-8 BOM | 4 |
| ja_cp932.srt | SRT | CP932 | 4 |
| ja_cp932.vtt | VTT | CP932 | 4 |
| ja_eucjp.ass | ASS | EUC-JP | 3 |
| zh_utf8.srt / en_utf8.vtt / ko_utf8.srt | SRT/VTT | UTF-8 | 2 |

**编码归一（关键坑）**：Shift_JIS 的 `～`(U+FF5E) 与 JIS X 0213 的 `〜`(U+301C) 同字节不同码位，`charset_normalizer` 会把 cp932 误判成 `shift_jis_2004` 导致波浪线错字。`server/subtitle_file.py` 用 `_ENC_NORMALIZE` 先把 `shift_jis_2004/shift_jisx0213 → cp932`、`euc_jis_2004/euc_jisx0213 → euc_jp` 归一，再插候选编码。

## 多语言字体 fallback（v1.7）

本机字体实测（canvas 宽度度量，同字号同文本）：Meiryo **317.24px == 不存在字体的测量值**（未安装）；Yu Gothic 319.99px、MS Gothic 333.5px 可用；另有 `NotoSansSC-VF.ttf`。

| 字幕层 | 字体栈 |
|---|---|
| `#subs.lang-ja` / `#fileSubs.lang-ja` | Yu Gothic → Hiragino Kaku Gothic ProN → Meiryo → MS Gothic → Noto Sans CJK JP → Microsoft YaHei → PingFang SC → sans-serif |
| `#subs.lang-ko` / `#fileSubs.lang-ko` | Malgun Gothic → Yu Gothic → Microsoft YaHei |

**验证**：17 个特殊字符（`々 ～ 〜 ① 「 」 ・ ー ヴ ァ ィ ゥ ェ ォ ぁ ゃ ≒`）与必然缺字码位 `U+10FFFD` 做 canvas 像素签名比对，`missing=[]`（无豆腐块）；8 个样本在每条 cue 中点 + cue 间空隙 + t=9.5s 采样，`#fileSubs.textContent` 与期望值逐点一致（50/50）。

## 架构

两条链路并存，按输入方式自动选择：

**① 浏览器扩展链路（推荐，低延迟）**

```
标签页音频 ──tabCapture──> AudioContext 16kHz → ScriptProcessor(4096≈256ms/块) → PCM16
                      │ ws://127.0.0.1:8790/ws/audio
                      ▼
        流式 ASR：sherpa-onnx OnlineRecognizer（按语种选模型）
        （zh/en 小双语模型 · ja 八语种包 · ko 韩语模型，int8/CPU，边收边出 partial）
        未指定语种时：先攒 2s 用 whisper 判语种 → 再进对应流式模型；?lang=xx 跳过嗅探
                      │ 每 600ms 或全文变化 ≥3 字即出 partial
                      ▼
              翻译：LocalCT2（ctranslate2 int8 + sentencepiece，0 元）
                      │
                      ▼ 同一 WebSocket 回推 JSON
              页面字幕层（Shadow DOM：原文小字 + 中文主行，6s 自动清空，全屏跟随）
```

**② 服务端拉流链路（播放器页，兼容 RTMP/RTSP/HLS）**

```
视频源 ──ffmpeg──> PCM 16kHz 单声道
                      │ 5s 窗口 / 0.5s 重叠（满 4 丢最旧，保实时）
                      ▼
              faster-whisper ASR（small / int8 / CPU，非流式）
                      │
                      ▼
              翻译链（Google gtx → clients5 → Argos 离线兜底）
                      │
                      ▼ WebSocket /ws
              播放器页字幕（原文小字 + 中文主行，6s 自动清空）
```

- 服务端：FastAPI + uvicorn，端口 8790（`server/main.py`；流式 ASR 在 `server/streaming_asr.py`）
- 播放器：原生 + hls.js 低延迟模式（`web/index.html`）
- 字幕推送：扩展用 `/ws/audio`（双向），播放器用 `/ws`（单向推送），均断线自动重连
- 延迟量级：扩展流式链路**服务端实测 p50 约 200-350ms**（见上表，浏览器端到端待补测）；播放器拉流链路因 5s 窗口，首条约 **7-8s**，之后每 4.5s 一条滚动

## 目录

```
server/    main.py(服务) pipeline.py(拉流→ASR→翻译) browser_audio.py(扩展音频/语种路由/whisper通道)
           streaming_asr.py(中/英/日/韩流式ASR) subtitle_file.py(字幕文件编码识别+解析) translator.py(转发到 offline_translate 的兼容层) ffmpegbin.py(ffmpeg定位)
offline_translate/  翻译内核插件（core/engines/lang/cli，可独立 pip 安装，详见 docs/插件化封装方案_v1.0.md）
web/       index.html 播放器页
chrome_ext/  Chrome MV3 扩展（manifest/background/offscreen/content + popup 语种弹窗，抓标签页音频→8790→页面浮字幕）
tests/     test_units.py 单元(12项) test_translate_ja_ko.py 日韩翻译端到端(16项) test_integration.py TTS→ASR→翻译 test_asr_ja_ko.py 日韩ASR专项 test_e2e.py 端到端冒烟(支持 en/ja/ko) verify_encoding.ps1 终端/文件/网络编码验证(16项)
static_hls/ RTMP/RTSP 转 HLS 的临时分片目录
启动.bat    一键启动
install_offline_models.py  安装日/韩离线翻译模型（可选，0 元）
pyproject.toml  插件打包元数据（name=offline-translate）
docs/插件化封装方案_v1.0.md  插件目录/接口/安装/兼容性完整说明
docs/同类方案对比_v1.0.md    开工前的同类开源方案横向对比与可复用点
```

## 测试验证

**怎么跑**（全部是独立脚本，直接 `python` 跑，**不需要 pytest**）：

| 脚本 | 覆盖 | 前置 |
|---|---|---|
| `tests\test_units.py` | 语种识别、翻译缓存与降级、管道去重（12 项） | 无，不起服务 |
| `tests\test_integration.py` | pyttsx3 合成英文语音 → faster-whisper → 翻译 | 需要本机 SAPI 英文语音 |
| `tests\test_e2e.py en\|ja\|ko` | 合成测试视频 → 起服务 → WS 收中文字幕 | 无，脚本自己拉起服务；ja/ko 需联网（edge-tts） |
| `tests\test_asr_ja_ko.py` | 日/韩 ASR 精度（edge-tts 合成语料） | 需联网 |
| `tests\test_translate_ja_ko.py` | 日/韩翻译 16 项 | 需联网（Google 免费端点） |
| `tests\e2e\test_ja_subtitle.py all` | 字幕解析 72 + HTTP 8 + 实时 15 | **需先另开窗口启动服务** |
| `tests\verify_encoding.ps1` | PowerShell 编码 16 项 | 见下方「PowerShell 5.1 编码配置」 |

统一前置：`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`，否则 Windows 控制台输出日/韩文会乱码。

以下数字均为 2026-11-09 本机实测：

- 单元测试 **12/12 通过**：四语识别（中/日/韩/英）、翻译缓存、中文跳过
- 集成测试通过：pyttsx3 合成英文语音 → ASR 逐字正确（语种 en，置信度 0.98，关键词 4/4）→ 中文译文
- 端到端冒烟通过：起服务 → 播放测试视频 → WS 收到 2 条字幕且均含中文译文
- **日/韩语专项（2026-11-09 追加）**：`tests/test_asr_ja_ko.py`（edge-tts 合成 ja-JP/ko-KR 语音，免费无 Key）

  | 语种 | 整段识别 | 语种判定 | 字错率 | 加噪 10dB | 5s 窗 | 译中（clients5 端点） |
  |---|---|---|---|---|---|---|
  | 日语 | 今日はとても良い天気です これから公園へ行きます | ja 1.00 | **0.0%** | 0.0% | 通过 | 今天天气很好。我现在要去公园。 |
  | 韩语 | 오늘은 날씨가 정말 좋습니다.우리는 공원에 갈 거예요. | ko 0.99 | **0.0%** | 0.0% | 通过 | 今天天气真好。我们要去公园。 |

- **端到端三语实测**：`tests\test_e2e.py ja|ko|en` 均通过，WS 各收到 2 条字幕、全部为真中文（已排除「日文汉字被误判为中文」的假通过）
- **日/韩翻译专项（2026-11-09 抽包后复测）**：`tests\test_translate_ja_ko.py` **16/16 通过**（J1–J7 日、K1–K7 韩、E1 中文跳过、E2 空文本 400），全部 `engine=google_chrome`；校验原文回显、语种判定、关键词命中、数字保真（230/100）、换行与 `%` 保留、响应字节可 UTF-8 解码且无 U+FFFD/HTML 实体；`test_units.py` 同步 12/12
- **编码与 Chrome 播放复验（2026-11-09，v1.4）**：`tests\verify_encoding.ps1` **16/16 通过**；Chrome 实测 HLS 与韩文视频均正常播放（`readyState=4`、`currentTime` 递增、`video.error=null`），字幕「Hello everyone…→大家好。今天天气很好。」「안녕하세요 여러분…→大家好。今天天气真好。」，控制台仅 `favicon.ico` 404（无编码影响）

## HTTP 端点（服务）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 播放器页 |
| POST | `/api/play` `{url}` | 起拉流翻译；RTMP/RTSP 自动转本地 HLS |
| POST | `/api/stop` | 停止 |
| GET | `/api/status` | 运行状态 |
| GET | `/api/engines` | 翻译链、目标语种、离线可译语种、缓存条数 |
| POST | `/api/translate` `{text}` | 直接翻译一段文本，返回 `{original, translated, lang, target, engine}` |
| POST | `/api/subtitle/parse?name=xx.srt` | 请求体为字幕文件原始字节；自动识别编码（UTF-8/BOM/CP932/EUC-JP）并解析 SRT/VTT/ASS，返回 `{format, encoding, lines[], lang_hint}` |
| WS | `/ws` | 字幕推送 |
| WS | `/ws/audio` | 扩展上行 PCM16 + 下行字幕；`?lang=ja` 可跳过语种嗅探 |

响应头为 `application/json; charset=utf-8`。PowerShell 5 的 `Invoke-WebRequest` 在缺 charset 时会按 Latin-1 解码导致中文乱码，故显式声明。

## 翻译插件用法（offline_translate）

翻译内核已从服务中解耦成独立包，服务与插件共用同一份实现（`server/translator.py` 只做转发）。

**Python**

```python
from offline_translate import translate
translate("今日は良い天気です。")
# {'original': ..., 'translated': '今天天气很好。', 'lang': 'ja', 'target': 'zh-CN', 'engine': 'google_chrome'}
```

**命令行**

```powershell
.venv\Scripts\python.exe -m offline_translate "안녕하세요" --json
.venv\Scripts\python.exe -m offline_translate --check        # 引擎链 / 离线语种 / 缓存
.venv\Scripts\xlate.exe "こんにちは"                          # pip install -e . 之后的短命令
```

**安装到别的项目**

```powershell
.venv\Scripts\pip.exe install -e .              # 仅在线（httpx）
.venv\Scripts\pip.exe install -e ".[offline]"   # 加 Argos 离线兜底
```

目录结构、引擎扩展、接口字段、兼容性矩阵见 [插件化封装方案_v1.0.md](docs/插件化封装方案_v1.0.md)。

## 环境事实（已实测）

- Python 3.13（项目自带 `.venv`，依赖已装齐：fastapi/uvicorn/httpx/faster-whisper/argostranslate/pyttsx3/imageio-ffmpeg/websockets/edge-tts）
- ffmpeg 用 imageio-ffmpeg 内置二进制，**无需装系统 ffmpeg**
- ASR 走 CPU：sherpa-onnx 流式 zipformer（zh/en 小双语 50MB + ja 八语种包 + ko 韩语，均 int8），未覆盖语种回落 faster-whisper small int8；GTX 1650 不参与，无显卡也能跑
- 翻译 0 费用：Google gtx 端点优先 → clients5 端点（gtx 被 429 限流时自动换上）→ Argos 本地兜底（en→zh、ja→en、ko→en 已装，日/韩经英文中转，见下节）
- 本机 SAPI 只有 zh-CN/en-US 语音，**无日/韩语音包**；日韩测试语料用 edge-tts 在线合成（免费、无 Key）

## 离线日/韩翻译模型安装（可选，0 元）

默认联网走 Google 免费端点，**不装离线模型也能用**；只有本机断网、或两个 Google 端点都被限流时才需要 Argos 兜底。

Argos 官方索引**没有 ja→zh / ko→zh 直连包**，正确做法是装 `ja→en`、`ko→en`，由 argostranslate 在 `get_installed_languages()` 里自动拼出 `ja→en→zh` / `ko→en→zh`（`CompositeTranslation` 中转），因此 `en→zh` 必须同时存在。

**一键安装（下载约 225MB，源为 argos-net.com 官方免费地址）**

```powershell
cd <本项目根目录>
.venv\Scripts\python.exe install_offline_models.py
```

**只看现状、不下载**

```powershell
.venv\Scripts\python.exe install_offline_models.py --check
```

脚本流程：① 更新官方索引 → ② 缺哪个装哪个（已装自动跳过）→ ③ 清语言缓存 → ④ 用日/韩样句各译一次中文自检（缺包时退出码 1）。

**实测输出（2026-11-09 本机）**

```
[1] 更新 Argos 官方模型索引…
    ja → en：待安装
    ko → en：待安装
    en → zh：已安装
[2] 下载并安装 ja → en（v1.1）…  完成，用时 5s
[2] 下载并安装 ko → en（v1.1）…  完成，用时 3s
[3] ja → zh：今天天气不错 去公园。
[3] ko → zh：今天真的很不错。 我们去公园
[4] 结论：离线日/韩→中可用（经英文中转）
```

**要点**

- 安装位置：`C:\Users\<用户>\.local\share\argos-translate\packages`（实测 ja_en 129MB / ko_en 130MB / en_zh 83MB）
- 装完**重启服务**（`启动.bat`）：`Translator` 初始化时才探测可用语种并缓存，运行中的进程不会自动感知新包
- 查/卸：`.venv\Scripts\argospm.exe list`、`.venv\Scripts\argospm.exe remove translate-ja_en`
- 首次加载模型会有 `WARNING: Language en package default expects mwt, which has been added`，属 Argos 正常提示，不影响翻译
- 质量：两次中转损耗大，明显弱于 Google 直译，只作最后兜底

## PowerShell 5.1 编码配置（v1.4，全局持久化）

本机只有 PowerShell 5.1（无 pwsh 7）。PowerShell 默认按系统 ANSI（中文机为 GBK）解码管道与文件，中文/韩文会乱码。已做三处**持久化**配置，重启终端或系统后自动生效：

| 位置 | 内容 | 作用 |
|---|---|---|
| `%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` | 控制台 `OutputEncoding/InputEncoding/$OutputEncoding` = UTF-8 无 BOM、`chcp 65001`、`$PSDefaultParameterValues` 六项文件 cmdlet 默认 `utf8` | 每个新会话自动加载 |
| `HKCU:\Console\CodePage = 65001` | DWORD | 新建控制台窗口默认代码页 |
| 用户级环境变量 `PYTHONIOENCODING=utf-8` | 字符串 | Python 子进程 stdout/stdin 走 UTF-8 |

profile 另外提供三个函数（脚本内直接可用）：

```powershell
Save-Utf8 -Path out.txt -InputObject "中文/한국어"   # 严格 UTF-8 无 BOM（[IO.File]::WriteAllText）
Read-Utf8 out.txt                                   # 严格 UTF-8 无 BOM 读取
Post-JsonUtf8 http://127.0.0.1:8790/api/translate @{ text = "안녕하세요" }   # UTF-8 字节 + charset=utf-8
```

**PS 5.1 的两个硬限制（实测）**：① `Out-File -Encoding` 只接受 `utf8`（**必带 BOM**），传 `UTF8Encoding` 对象会参数验证失败 —— 需要无 BOM 就用 `Save-Utf8`；② 解析器把中文弯引号 `“ ”` 当字符串定界符，字面量写进 `"..."` 会被吞，特殊字符须用码点 `[char]0x201C` 构造。脚本文件本身须带 UTF-8 BOM，否则按 ANSI 解码可能吞引号破坏语法。

**验证脚本（三类场景，16 项）**

```powershell
powershell -ExecutionPolicy Bypass -File "tests\verify_encoding.ps1"
```

覆盖终端输入输出/管道 stdin、文件读写（无 BOM、往返、自动识别）、网络请求（韩文/中文 body、响应无 U+FFFD 与 HTML 实体）；**不要加 `-NoProfile`**，该脚本本身就是用来证明 profile 持久化生效的。

## 已知边界

- Argos 兜底译文质量弱于 Google，偶见直译腔；日/韩还要经英文中转（ja/ko→en→zh）二次损耗更大（实测「今日はとても良い天気です」→「今天天气不错」），仅在两个 Google 端点都不可用时启用，不影响出字幕
- 日/韩语 ASR 准确率已实测（合成朗读音 0% 字错率），但**合成音比真实口语干净，真实场景会下降**；真实影视剧对白、方言、快语速未实测
- 日语音同音字会按假名输出（如「午後は」识别成「ごごは」），语义不受影响但字面不一致
- 纯汉字无假名的日语句子会被 `detect_lang` 判成中文而跳过翻译（四语识别的固有取舍）
- 本地文件源 ffmpeg 不限速会瞬时读完，首条字幕等待偏长（窗口排队串行 ASR）；真实流式源无此现象

## 常见问题（FAQ）

| 现象 | 原因 | 处理 |
|---|---|---|
| 双击 `启动.bat` 闪退 | `.venv` 不存在或依赖没装全 | 按「从零安装」①② 重建环境；窗口跑不起来时先手动执行 `.venv\Scripts\python.exe server\main.py` 看完整报错 |
| 页面能开，但一直没有字幕 | 视频本身没声音／标签页被静音／`<video muted>` | tabCapture 抓的是标签页实际输出的声音，测试时必须保持有声且未静音 |
| 首条字幕要等 4 秒以上 | 语种选了「自动识别」，服务端要先攒 2s 音频做嗅探 | 在扩展弹窗里显式选中文/英语/日语/韩语，可省掉嗅探（首条约 1.2-1.9s） |
| 端口 8790 被占用 | 上一次服务没退干净 | `netstat -ano \| findstr 8790` 找到 PID 后 `taskkill /PID <pid> /F`；端口目前是硬编码，要换需同时改 `server/main.py` 末尾 `uvicorn.run(..., port=8790)` 与 `启动.bat` 里的两处地址 |
| 扩展点「开始字幕」报 `Extension has not been invoked for the current page` | Chrome 的 activeTab 安全模型要求先在该标签页手动点一次扩展图标 | 每个新标签页都要点一次图标，无法用脚本代劳 |
| 改了 `chrome_ext/` 代码但行为没变 | 扩展没重载，仍在跑旧版本 | `chrome://extensions/` → 对应扩展 → 点圆形「重新加载」 |
| 日语字幕出现「豆腐块」方框 | 系统缺日文字形 | 见「多语言字体 fallback（v1.7）」；Windows 装「日语补充字体」即可 |
| 服务日志报 `model not found` / 直接回落 whisper | `models/` 下目录名被改名，或模型包没解压 | 目录名必须与「从零安装 ②b」表格完全一致；不放模型也能跑，只是首条延迟升到 2.7-8.1s |
| 全屏播放时字幕看不见 | 站点全屏层级高于浮层 | 已在扩展里做全屏跟随；若个别站点仍被遮挡，可先退出全屏或反馈 issue |

## 后续优化方向

按优先级排列，欢迎针对任意一条提 PR：

1. **端到端 ≤1s**（当前 1.66-2.54s）：继续压缩采集缓冲（`ScriptProcessor(4096)≈256ms` 已降到 2048）、评估 AudioWorklet 替代、ASR 侧缩短首条 partial 的攒帧窗口。
2. **长句不分句**：流式 ASR 目前按块吐 partial，长句会被切成碎片；计划引入基于标点/停顿的分句合并，让译文成句。
3. **短词幻觉**：静音段或极短音频偶尔会吐出无意义词；计划加 VAD 前置门限与最短语音时长判定。
4. **ko 直连翻译**：韩语当前走 `ko→en→zh` 两跳，质量明显弱于 ja→zh；需要可离线部署的 ko→zh 直连模型（CT2 或 sherpa 生态内的可用权重）。
5. **多语种嗅探提速**：自动识别模式下 2s 嗅探窗口偏保守，评估用更短窗口 + 置信度回退策略。
6. **跨平台**：`启动.bat` 与部分路径处理是 Windows 专用；计划补 Linux/macOS 的启动脚本与 ffmpeg 兜底路径。
7. **免 Python 体验**：参考同类项目的 Native Messaging 思路，让扩展一键拉起后端，用户不必手动双击启动脚本。

## 许可证

本项目以 [MIT](LICENSE) 许可证发布，© 2026 kongitt2026。

第三方组件遵循各自许可证：sherpa-onnx（Apache-2.0）、CTranslate2（MIT）、Argos Translate（MIT）、faster-whisper（MIT）、FastAPI（MIT）、hls.js（Apache-2.0）。模型权重不在本仓库内分发，下载与使用请遵守其原始发布页的许可条款。

## 贡献

- 提 issue 请附：操作系统与 Python 版本、是否放了 ASR 模型、`logs/server.log` 相关片段、复现步骤。
- 提 PR 前请确保 `tests/` 下相关用例通过，并说明改动对应「后续优化方向」的哪一条，或新增了什么场景。
- 涉及模型、采样率、WS 协议格式的改动，请在 PR 描述里说明兼容性影响（浏览器扩展与服务端需要同步升级）。
