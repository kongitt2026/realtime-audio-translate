// 弹窗：选语种 + 开始/停止。语种存 storage，运行中改语种会自动重连。
const LANG_KEY = 'liveSubLang';

// 这些数字来自 2026-11-10 /ws/audio 实测：显式 lang 时 ASR 首条 198-775ms、
// 到达 1.2-1.8s；自动嗅探固定先攒 2s 音频判语种，到达 3.9-8.3s。
const HINT = {
  auto: '自动识别：中/英约 0.3-1s 出字幕；日/韩要先听 2s 判断语种，首条约 4-8s。',
  zh: '已指定中文，跳过语种判断，首条约 1-2s。',
  en: '已指定英语，跳过语种判断，首条约 1-2s。',
  ja: '已指定日语，跳过语种判断，首条约 1-2s。音频不是日语时识别会出错。',
  ko: '已指定韩语，跳过语种判断，首条约 1-2s。音频不是韩语时识别会出错。'
};

const $ = (id) => document.getElementById(id);
let tabId = null;
let running = false;

function render() {
  $('btn').textContent = running ? '停止字幕' : '开始字幕';
  $('btn').classList.toggle('on', running);
  $('state').textContent = running ? '正在翻译当前标签页' : '未连接';
  $('state').classList.remove('warn');
  $('hint').textContent = HINT[$('lang').value] || HINT.auto;
}

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true }).catch(() => []);
  tabId = tab && tab.id;
  const saved = await chrome.storage.local.get(LANG_KEY).catch(() => ({}));
  if (saved[LANG_KEY]) $('lang').value = saved[LANG_KEY];

  const st = await chrome.runtime.sendMessage({ type: 'get-state', tabId }).catch(() => null);
  running = !!(st && st.running);
  render();
  if (!running && st && st.anyRunning) {
    $('state').textContent = '其他标签页正在翻译，点开始会切换过来';
  }
  if (!tabId) {
    $('btn').disabled = true;
    $('state').textContent = '当前窗口没有可翻译的标签页';
    $('state').classList.add('warn');
  }
}

$('btn').addEventListener('click', async () => {
  const lang = $('lang').value;
  await chrome.storage.local.set({ [LANG_KEY]: lang }).catch(() => {});
  $('btn').disabled = true;
  $('state').classList.remove('warn');
  $('state').textContent = running ? '正在停止…' : '正在启动…';

  const r = await chrome.runtime.sendMessage({ type: 'toggle', tabId, lang })
    .catch((e) => ({ ok: false, error: String(e && e.message || e) }));
  $('btn').disabled = false;

  if (!r || !r.ok) {
    running = false;
    render();
    $('state').textContent = '启动失败：' + ((r && r.error) || '请确认本地 8790 服务已启动');
    $('state').classList.add('warn');
    return;
  }
  running = !!r.running;
  render();
});

$('lang').addEventListener('change', async () => {
  const lang = $('lang').value;
  await chrome.storage.local.set({ [LANG_KEY]: lang }).catch(() => {});
  render();
  if (!running) return;

  $('state').textContent = '切换语种，重连中…';
  $('state').classList.remove('warn');
  const r = await chrome.runtime.sendMessage({ type: 'restart', tabId, lang })
    .catch((e) => ({ ok: false, error: String(e && e.message || e) }));

  if (!r || !r.ok) {
    running = false;
    render();
    $('state').textContent = '切换失败：' + ((r && r.error) || '请确认本地服务已启动');
    $('state').classList.add('warn');
    return;
  }
  running = true;
  render();
});

init();
