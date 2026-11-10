// 内容脚本：在视频页叠加字幕层（Shadow DOM 隔离站点样式），并跟随全屏切换
(() => {
  if (window.__liveSubtitleReady) return;
  window.__liveSubtitleReady = true;

  const HOST_ID = '__live_subtitle_host__';
  let host = null, shadow = null, origEl = null, tranEl = null, tipEl = null;
  let clearTimer = null;

  // 语种 → 字体栈：雅黑能覆盖部分假名，但片假名长音「ー」、々、〜、①② 等
  // 特殊字符会缺字或回退到不等宽字体，日文必须显式优先系统日文字体。
  // 本机实测可用：Yu Gothic(YuGoth*.ttc) / MS Gothic(msgothic.ttc)，无 Meiryo。
  function langClass(lang) {
    const l = (lang || '').toLowerCase();
    if (l.startsWith('ja')) return 'lang-ja';
    if (l.startsWith('ko')) return 'lang-ko';
    return '';
  }

  function applyLang(el, lang) {
    el.classList.remove('lang-ja', 'lang-ko');
    const c = langClass(lang);
    if (c) el.classList.add(c);
  }

  function build() {
    host = document.createElement('div');
    host.id = HOST_ID;
    host.style.cssText = 'all:initial;position:fixed;left:0;right:0;bottom:9%;z-index:2147483647;' +
      'pointer-events:none;display:flex;justify-content:center;';
    shadow = host.attachShadow({ mode: 'open' });
    shadow.innerHTML = `
      <style>
        :host { all: initial; }
        .wrap { max-width: 86vw; text-align: center;
                font-family: "Microsoft YaHei","PingFang SC","Noto Sans SC",
                             "Yu Gothic","Meiryo","MS Gothic",sans-serif; }
        .orig, .tran { font-family: inherit; }
        .orig.lang-ja, .tran.lang-ja {
                font-family: "Yu Gothic","Hiragino Kaku Gothic ProN","Meiryo",
                             "MS Gothic","Noto Sans CJK JP",
                             "Microsoft YaHei","PingFang SC",sans-serif; }
        .orig.lang-ko, .tran.lang-ko {
                font-family: "Malgun Gothic","Yu Gothic","Microsoft YaHei",sans-serif; }
        .orig { font-size: 15px; line-height: 1.35; color: rgba(255,255,255,.72);
                text-shadow: 0 1px 3px rgba(0,0,0,.95); }
        .tran { display: inline-block; margin-top: 4px; padding: 5px 14px;
                border-radius: 6px; background: rgba(0,0,0,.62);
                font-size: 23px; line-height: 1.4; color: #fff;
                text-shadow: 0 1px 2px rgba(0,0,0,.8); }
        .tip { display: inline-block; margin-top: 6px; padding: 3px 10px; border-radius: 4px;
               background: rgba(26,115,232,.85); color: #fff; font-size: 13px; }
        .hidden { display: none !important; }
      </style>
      <div class="wrap">
        <div class="orig hidden"></div>
        <div class="tran hidden"></div>
        <div class="tip hidden"></div>
      </div>`;
    origEl = shadow.querySelector('.orig');
    tranEl = shadow.querySelector('.tran');
    tipEl = shadow.querySelector('.tip');
    mount();
    document.addEventListener('fullscreenchange', mount, true);
  }

  // 全屏时普通 fixed 元素会被压在 top layer 下面，需要挂进全屏元素里
  function mount() {
    if (!host) return;
    const fs = document.fullscreenElement;
    if (fs) {
      host.style.position = 'absolute';
      if (host.parentNode !== fs) fs.appendChild(host);
    } else {
      host.style.position = 'fixed';
      if (host.parentNode !== document.documentElement) document.documentElement.appendChild(host);
    }
  }

  function activeFrame() {
    // 只在“有视频的画面”或顶层页面显示，避免 iframe 广告里冒字幕
    if (document.querySelector('video')) return true;
    if (window === window.top) return true;
    return false;
  }

  function show(p) {
    if (!activeFrame()) return;
    if (!host) build();
    const original = (p && p.original) || '';
    const translated = (p && p.translated) || '';
    if (!original && !translated) return;

    // 主行永远显示「可读内容」：翻译为空或与原文相同时（翻译失败/同语种），
    // 直接把原文放进大字号主行——否则日语等小语种只剩 15px 的弱化小字，
    // 看起来就像「字幕没出来」。
    const primary = (translated && translated !== original) ? translated : original;

    applyLang(origEl, p && p.lang);
    applyLang(tranEl, p && p.target);

    if (primary !== original) {
      origEl.textContent = original;
      origEl.classList.remove('hidden');
    } else {
      origEl.textContent = '';
      origEl.classList.add('hidden');
    }

    tranEl.textContent = primary;
    tranEl.classList.remove('hidden');
    host.style.display = 'flex';

    clearTimeout(clearTimer);
    clearTimer = setTimeout(clear, 6000);
  }

  function clear() {
    if (!host) return;
    origEl.textContent = ''; tranEl.textContent = '';
    origEl.classList.add('hidden'); tranEl.classList.add('hidden');
  }

  function tip(text, ms) {
    if (!host) build();
    tipEl.textContent = text;
    tipEl.classList.remove('hidden');
    setTimeout(() => tipEl.classList.add('hidden'), ms || 2500);
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'ping') { sendResponse({ ok: true }); return; }
    if (msg.type === 'subtitle') { show(msg.payload); sendResponse({ ok: true }); return; }
    if (msg.type === 'error') { tip('字幕服务未连接：' + (msg.message || '请先启动 8790 服务'), 8000); return; }
    if (msg.type === 'info') { tip(msg.message || '', 3000); return; }
    if (msg.type === 'clear') { clear(); }
  });
})();
