// offscreen 文档：抓标签页音频 → 16kHz PCM16 → WebSocket 推给本地服务
// 字幕通过 runtime 消息回传给 background 再转发到页面内容脚本
// 语种：auto 不带参数（服务端自动嗅探，日/韩要多等 2s）；
// 显式 zh/en/ja/ko 时拼 ?lang=，服务端跳过嗅探直接进对应流式模型。
const WS_BASE = 'ws://127.0.0.1:8790/ws/audio';

let ws = null;
let ctx = null;
let proc = null;
let srcNode = null;
let stream = null;
let tabId = null;
let curLang = 'auto';

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'start') {
    start(msg).then(() => sendResponse({ ok: true }))
              .catch((e) => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;   // 异步响应
  }
  if (msg.type === 'stop') { stop(); sendResponse({ ok: true }); return true; }
});

async function start({ streamId, tabId: tid, lang }) {
  stop();
  tabId = tid;
  curLang = (lang || 'auto').toLowerCase();

  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId }
    }
  });

  // 16kHz 单声道：浏览器自动重采样，服务端 ASR 直接可用
  ctx = new AudioContext({ sampleRate: 16000 });
  srcNode = ctx.createMediaStreamSource(stream);

  // tabCapture 会把标签页声音“截走”，必须再接回扬声器，否则用户听不到原声
  const monitor = ctx.createGain();
  monitor.gain.value = 1.0;
  srcNode.connect(monitor);
  monitor.connect(ctx.destination);

  // 2048 样本/块 = 128ms@16kHz（原 4096=256ms，减半采集缓冲，首条字幕 -128ms）
  proc = ctx.createScriptProcessor(2048, 1, 1);
  const silent = ctx.createGain();
  silent.gain.value = 0;
  srcNode.connect(proc);
  proc.connect(silent);
  silent.connect(ctx.destination);

  // auto 时不带 lang：服务端走语种自动嗅探
  const q = curLang && curLang !== 'auto' ? '?lang=' + encodeURIComponent(curLang) : '';
  ws = new WebSocket(WS_BASE + q);
  ws.binaryType = 'arraybuffer';

  proc.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const f = e.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) {
      const s = Math.max(-1, Math.min(1, f[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(pcm.buffer);
  };

  ws.onopen = () => {
    chrome.runtime.sendMessage({ type: 'state', state: 'on', tabId, lang: curLang });
  };
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === 'subtitle') {
      chrome.runtime.sendMessage({ type: 'subtitle', tabId, payload: m });
    }
  };
  ws.onerror = () => {
    chrome.runtime.sendMessage({ type: 'state', state: 'off', tabId, reason: 'WS 连接失败' });
  };
  ws.onclose = (ev) => {
    chrome.runtime.sendMessage({ type: 'state', state: 'off', tabId, reason: 'WS 关闭 code=' + ev.code });
  };
}

function stop() {
  try { if (proc) proc.onaudioprocess = null; } catch (_) {}
  try {
    if (ws) { ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null; if (ws.readyState <= 1) ws.close(); }
  } catch (_) {}
  ws = null;
  try { if (proc) proc.disconnect(); } catch (_) {}
  try { if (srcNode) srcNode.disconnect(); } catch (_) {}
  try { if (ctx && ctx.state !== 'closed') ctx.close(); } catch (_) {}
  try { if (stream) stream.getTracks().forEach(t => t.stop()); } catch (_) {}
  proc = srcNode = ctx = stream = null;
}
