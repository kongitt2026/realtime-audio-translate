// 后台 Service Worker：弹窗/快捷键 → tabCapture 取 streamId → 交给 offscreen 抓音频 + 推字幕
// 语种由弹窗选择后透传给 offscreen，最终拼成 /ws/audio?lang=xx；auto 不传参走自动嗅探。
const activeTabs = new Set();          // 正在翻译的 tabId
const tabLangs = new Map();            // tabId → 语种（auto/zh/en/ja/ko）
const OFFSCREEN_URL = 'offscreen.html';
const LANG_KEY = 'liveSubLang';
const LANG_NAME = { auto: '自动识别', zh: '中文', en: '英语', ja: '日语', ko: '韩语' };

async function savedLang() {
  try {
    const o = await chrome.storage.local.get(LANG_KEY);
    return o[LANG_KEY] || 'auto';
  } catch (_) {
    return 'auto';
  }
}

async function hasOffscreen() {
  if (!chrome.runtime.getContexts) return false;
  const ctxs = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  return ctxs.length > 0;
}

async function ensureOffscreen() {
  if (await hasOffscreen()) return;
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ['USER_MEDIA'],
    justification: '捕获标签页音频，送到本机 127.0.0.1:8790 做实时语音识别与翻译'
  });
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: 'ping' });
  } catch (e) {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content.js']
    });
  }
}

function badge(tabId, on) {
  chrome.action.setBadgeText({ tabId, text: on ? '译' : '' }).catch(() => {});
  if (on) chrome.action.setBadgeBackgroundColor({ tabId, color: '#1a73e8' }).catch(() => {});
}

async function start(tabId, lang) {
  lang = lang || 'auto';
  await ensureContentScript(tabId);
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  await ensureOffscreen();
  const resp = await chrome.runtime.sendMessage({ type: 'start', streamId, tabId, lang });
  if (!resp || !resp.ok) throw new Error((resp && resp.error) || 'offscreen 启动失败');
  activeTabs.add(tabId);
  tabLangs.set(tabId, lang);
  badge(tabId, true);
}

async function stop(tabId) {
  try { await chrome.runtime.sendMessage({ type: 'stop', tabId }); } catch (e) { /* offscreen 可能已关 */ }
  activeTabs.delete(tabId);
  tabLangs.delete(tabId);
  badge(tabId, false);
}

async function toggle(tabId, lang) {
  if (!tabId) throw new Error('当前窗口没有可翻译的标签页');
  if (activeTabs.has(tabId)) {
    await stop(tabId);
    return { ok: true, running: false, lang: lang || null };
  }
  for (const id of [...activeTabs]) await stop(id);
  const use = lang || (await savedLang());
  await start(tabId, use);
  return { ok: true, running: true, lang: use };
}

async function restart(tabId, lang) {
  if (!tabId) throw new Error('当前窗口没有可翻译的标签页');
  if (activeTabs.has(tabId)) await stop(tabId);
  await start(tabId, lang || 'auto');
  return { ok: true, running: true, lang: lang || 'auto' };
}

// 没有 content script 注入时（例如页面刚刷新）由 popup 的启动流程兜底；这里保留原有图标点击行为。
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;
  try {
    await toggle(tab.id, await savedLang());
  } catch (e) {
    console.error('[字幕翻译] 启动失败', e);
    await ensureContentScript(tab.id).catch(() => {});
    chrome.tabs.sendMessage(tab.id, { type: 'error', message: String(e.message || e) }).catch(() => {});
  }
});

chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== 'toggle') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;
  try {
    await toggle(tab.id, await savedLang());
  } catch (e) {
    await ensureContentScript(tab.id).catch(() => {});
    chrome.tabs.sendMessage(tab.id, { type: 'error', message: String(e.message || e) }).catch(() => {});
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'toggle') {
    toggle(msg.tabId, msg.lang)
      .then(sendResponse)
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;
  }
  if (msg.type === 'restart') {
    restart(msg.tabId, msg.lang)
      .then(sendResponse)
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;
  }
  if (msg.type === 'get-state') {
    const tid = msg.tabId !== undefined ? msg.tabId : (sender.tab && sender.tab.id);
    sendResponse({
      running: activeTabs.has(tid),
      lang: tabLangs.get(tid) || null,
      anyRunning: activeTabs.size > 0
    });
    return true;
  }
  if (msg.type === 'subtitle') {
    chrome.tabs.sendMessage(msg.tabId, { type: 'subtitle', payload: msg.payload }).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === 'state') {
    if (msg.tabId) {
      if (msg.state === 'off') {
        activeTabs.delete(msg.tabId);
        tabLangs.delete(msg.tabId);
        badge(msg.tabId, false);
        chrome.tabs.sendMessage(msg.tabId, { type: 'error', message: msg.reason || '连接断开' }).catch(() => {});
      } else if (msg.state === 'on') {
        const name = LANG_NAME[tabLangs.get(msg.tabId)] || '自动识别';
        chrome.tabs.sendMessage(msg.tabId, { type: 'info', message: `音频已连接（${name}），等待语音…` }).catch(() => {});
      }
    }
    sendResponse({ ok: true });
    return true;
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (activeTabs.has(tabId)) stop(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (activeTabs.has(tabId) && info.status === 'complete') {
    ensureContentScript(tabId).catch(() => {});
  }
});
