/* ==========================================================================
   Studiolo 手机端原型逻辑
   ========================================================================== */
(() => {
  const N = window.Studiolo;
  const { icon: I, data: D, syncBadge, ownerBadge, fmtMoney } = N;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const view = $('#view');
  const toastHost = $('#toasts');
  const online = () => N.get().online;
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

  const ui = {
    tab: 'today',
    stack: [],               // 推入的页面 [{s, p}]
    libSeg: 'ledger',
    jobFilter: 'all',
    chatAgent: 'openclaw',
    vault: { unlocked: false, revealed: null },
    cf: 'local',
    add: { type: 'tx', amount: '0', cat: '餐饮', memo: '' },
  };
  const TABS = [
    { id: 'today', label: '今天', icon: 'today' },
    { id: 'library', label: '资料', icon: 'layers' },
    { id: '+' },
    { id: 'chat', label: '对话', icon: 'chat' },
    { id: 'tasks', label: '任务', icon: 'tasks' },
  ];
  const RUN = { ok: '成功', fail: '失败', running: '运行中', paused: '已暂停', unknown: '结果未知' };
  const TYPE = { key: ['key', 'Key'], text: ['note', '文本'], config: ['braces', '配置'], file: ['file', '文件'] };
  const cur = () => ui.stack[ui.stack.length - 1] || { s: ui.tab };

  /* ---------- 同步 ---------- */
  function pendingCount() {
    return D.ledger.tx.filter((t) => t.sync !== 'synced').length + D.websites.filter((w) => w.sync !== 'synced').length
      + D.records.filter((r) => r.sync === 'pending' || r.sync === 'local').length + D.space.items.filter((s) => s.local === 'pending').length;
  }
  const conflictCount = () => D.records.filter((r) => r.sync === 'conflict').length;
  function advance(obj) {
    obj.sync = 'local'; soft();
    setTimeout(() => {
      obj.sync = 'pending'; soft();
      if (online()) setTimeout(() => { if (online() && obj.sync === 'pending') { obj.sync = 'synced'; soft(); } }, 1700);
    }, 800);
  }
  function flushAll() {
    let n = 0;
    D.ledger.tx.forEach((t) => { if (t.sync !== 'synced') { t.sync = 'synced'; n++; } });
    D.websites.forEach((w) => { if (w.sync !== 'synced') { w.sync = 'synced'; n++; } });
    D.records.forEach((r) => { if (r.sync === 'pending' || r.sync === 'local') { r.sync = 'synced'; n++; } });
    if (n) N.toast(toastHost, `${syncBadge('synced', { label: '' })} 已同步 ${n} 项`);
    soft();
  }
  function syncPill() {
    const p = pendingCount(), c = conflictCount();
    if (!online()) return `<button class="mpill" data-act="explain-offline">${syncBadge('offline', { label: `离线 · 本机可用${p ? ` · ${p} 待同步` : ''}` })}</button>`;
    if (c) return `<button class="mpill" data-act="goto-conflict">${syncBadge('conflict', { label: `${c} 个冲突待处理` })}</button>`;
    if (p) return `<span class="mpill">${syncBadge('pending', { label: `${p} 项待同步` })}</span>`;
    return `<span class="mpill">${syncBadge('synced', { label: '已同步' })}</span>`;
  }

  /* ======================================================================
     屏幕
     ====================================================================== */
  function sToday() {
    const L = D.ledger;
    const max = Math.max(...L.daily);
    const attn = D.jobs.filter((j) => j.last === 'fail' || j.last === 'unknown').length;
    const running = D.jobs.filter((j) => j.last === 'running');
    return `<div class="mpage">
      <div class="mhead"><div><div class="date">11 月 16 日 星期一</div><h1>今天</h1></div><span class="spacer"></span>
        <button class="avatar" style="width:38px;height:38px;font-size:15px" data-push="settings" aria-label="设置">Y</button></div>
      <div style="margin:-4px 0 14px">${syncPill()}</div>

      <div class="quick">
        <button data-act="add" data-type="tx"><span class="qi">${I('ledger')}</span>记一笔</button>
        <button data-act="add" data-type="web"><span class="qi">${I('globe')}</span>收藏</button>
        <button data-tab="chat"><span class="qi">${I('chat')}</span>问 Agent</button>
        <button data-push="vault"><span class="qi">${I('shield')}</span>共享空间</button>
      </div>

      <section class="mcard mat">
        <div class="mcard-h">${I('ledger')} ${L.month}支出<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-tab="library" data-seg="ledger">账本 ${I('chevR')}</button></div>
        <div class="mbig num">${fmtMoney(L.spent, false)}<small>/ ¥${L.budget.toLocaleString()}</small></div>
        <div class="spark">${L.daily.map((v, i) => `<i style="height:${Math.max(8, (v / max) * 100)}%;animation-delay:${i * 15}ms"></i>`).join('')}</div>
      </section>

      <section class="mcard mat">
        <div class="mcard-h">${I('tasks')} 任务<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-tab="tasks">全部 ${I('chevR')}</button></div>
        <div class="task-mini">
          <button data-tab="tasks" data-filter="running"><b style="color:var(--accent)">${running.length}</b><span>运行中</span></button>
          <button data-tab="tasks" data-filter="attn"><b style="color:var(--danger)">${attn}</b><span>需要关注</span></button>
          <button data-tab="tasks" data-filter="all"><b>3</b><span>今天已完成</span></button>
        </div>
        ${running.map((j) => `<button class="mrow" style="padding:12px 2px 0;min-height:0" data-push="job" data-id="${j.id}"><span class="grow"><div class="title" style="font-size:14px">${j.name}</div><div class="sub">${ownerBadge(j.owner, j.where)}</div></span><span class="run running">${j.lastAt.replace('正在运行 · ', '')}</span></button>`).join('')}
      </section>

      <div class="sec-t">最近记录<span class="spacer"></span></div>
      <div class="mlist mat-solid">${L.tx.slice(0, 4).map((t) => `
        <div class="mrow ${t.when === '刚刚' ? 'enter' : ''}"><span class="tile-icon">${I(t.icon)}</span>
          <span class="grow"><div class="title">${t.title}</div><div class="sub">${t.when} · ${t.from}</div></span>
          <span class="end"><span class="num" style="font-weight:650;${t.amount > 0 ? 'color:var(--ok)' : ''}">${fmtMoney(t.amount)}</span>${syncBadge(t.sync, { dotOnly: t.sync === 'synced' })}</span></div>`).join('')}</div>
    </div>`;
  }

  function sLibrary() {
    const seg = ui.libSeg;
    let list = '';
    if (seg === 'ledger') list = `<div class="mlist mat-solid">${D.ledger.tx.map((t) => `
      <div class="mrow"><span class="tile-icon">${I(t.icon)}</span><span class="grow"><div class="title">${t.title}</div><div class="sub">${t.cat} · ${t.when}</div></span>
        <span class="end"><span class="num" style="font-weight:650;${t.amount > 0 ? 'color:var(--ok)' : ''}">${fmtMoney(t.amount)}</span>${syncBadge(t.sync, { dotOnly: t.sync === 'synced' })}</span></div>`).join('')}</div>`;
    if (seg === 'websites') list = `<div class="mlist mat-solid">${D.websites.map((w) => `
      <button class="mrow" data-act="toast" data-msg="在浏览器打开 ${w.url}"><span class="fav" style="width:36px;height:36px;border-radius:11px;background:${w.color};color:#fff;display:grid;place-items:center;font-weight:700">${w.name[0]}</span>
        <span class="grow"><div class="title">${w.name}</div><div class="sub">${w.url}</div></span>${syncBadge(w.sync, { dotOnly: true })}</button>`).join('')}</div>`;
    if (seg === 'data') list = `
      <div class="sec-t" style="margin-top:4px">订阅服务 · ${D.records.length} 条</div>
      <div class="mlist mat-solid">${D.records.map((r) => `
        <button class="mrow" data-push="record" data-id="${r.id}"><span class="grow"><div class="title">${r.name}</div><div class="sub">¥${r.price} / ${r.cycle} · 续费 ${r.renew}</div></span>
          ${r.sync === 'synced' ? '' : syncBadge(r.sync, { dotOnly: r.sync !== 'conflict', label: r.sync === 'conflict' ? '冲突' : undefined })}${I('chevR')}</button>`).join('')}</div>
      <div class="sec-t">其它集合</div>
      <div class="mlist mat-solid">${D.collections.slice(1).map((c) => `<button class="mrow" data-act="toast" data-msg="原型仅展开「订阅服务」"><span class="tile-icon">${I(c.icon)}</span><span class="grow"><div class="title">${c.name}</div><div class="sub">${c.count} 条</div></span>${I('chevR')}</button>`).join('')}</div>`;
    if (seg === 'devices') list = `<div class="mlist mat-solid">${D.devices.map((d) => `
      <div class="mrow"><span class="tile-icon">${I(d.icon)}</span><span class="grow"><div class="title">${d.name}</div><div class="sub">${d.os} · ${d.note}</div></span>
        <span class="conn ${online() ? (d.state === 'online' ? 'online' : '') : 'offline'}"></span></div>`).join('')}</div>`;
    return `<div class="mpage">
      <div class="mhead"><h1>资料</h1><span class="spacer"></span>${syncPill()}</div>
      <div class="msearch">${I('search')}<input placeholder="搜索账本、网站、记录…" aria-label="搜索"></div>
      <button class="vault-entry mat" data-push="vault">
        <span class="lk">${I(ui.vault.unlocked ? 'unlock' : 'lock')}</span>
        <span style="flex:1;min-width:0"><div style="font-weight:650;font-size:15px">共享空间</div><div class="faint" style="font-size:12.5px">${D.space.meta.count} 个加密对象 · 查看需输入密码</div></span>${I('chevR')}
      </button>
      <div class="seg mseg" role="group" aria-label="资料类型">${[['ledger', '账本'], ['websites', '网站'], ['data', '数据'], ['devices', '设备']].map(([k, l]) => `<button data-act="seg" data-k="${k}" aria-pressed="${seg === k}">${l}</button>`).join('')}</div>
      ${list}
    </div>`;
  }

  function navbar(title, right = '') {
    return `<div class="navbar"><button class="icon-btn" data-act="back" aria-label="返回">${I('chevL')}</button><div class="t">${title}</div>${right || '<span style="width:40px"></span>'}</div>`;
  }

  function sRecord(p) {
    const r = D.records.find((x) => x.id === p.id);
    if (r.sync === 'conflict') {
      const C = D.conflict;
      return `<div class="mpage push">${navbar('处理冲突')}
        <div class="notice danger" style="margin-bottom:14px">${I('alert')}<div><b>${r.name}</b> 的「价格」在两台设备上都被修改过。请选择保留哪一个。</div></div>
        <div class="sec-t" style="margin-top:0">价格 · 原值 ¥${C.base.price}</div>
        <div style="display:grid;gap:8px;margin-bottom:12px">
          ${[['local', C.local], ['remote', C.remote]].map(([k, v]) => `
            <button class="mrow mat-solid" style="border-radius:18px;${ui.cf === k ? 'box-shadow:inset 0 0 0 2px var(--accent)' : ''}" data-act="cf" data-k="${k}">
              <span class="grow"><div class="title num" style="font-size:20px">¥${v.price}</div><div class="sub">${v.device} · ${v.at}</div></span>
              <span class="tile-icon" style="border-radius:50%;width:24px;height:24px;${ui.cf === k ? 'background:var(--accent);color:var(--accent-ink)' : ''}">${ui.cf === k ? I('check') : ''}</span></button>`).join('')}
        </div>
        <div class="notice info" style="margin-bottom:16px">${I('checks')}<div>支付方式已自动合并为 <b>${C.remote.pay}</b>（只有 Pixel 9 修改过）</div></div>
        <button class="btn btn-primary btn-lg" style="width:100%" data-act="resolve">保留所选并同步</button>
      </div>`;
    }
    return `<div class="mpage push">${navbar('', `<button class="icon-btn" aria-label="更多">${I('more')}</button>`)}
      <div class="dhero"><div class="tile-icon">${I('receipt')}</div><h2>${r.name}</h2>${syncBadge(r.sync)}</div>
      <div class="kvl mat-solid"><div><span>价格</span><span class="num">¥${r.price} / ${r.cycle}</span></div><div><span>续费日</span><span>${r.renew}</span></div><div><span>支付方式</span><span>${r.pay}</span></div><div><span>状态</span><span>${r.status}</span></div></div>
      <div class="kvl mat-solid"><div><span>来源集合</span><span>订阅服务</span></div><div><span>最近修改</span><span>今天 11:40 · Pixel 9</span></div></div>
      <button class="btn btn-ghost btn-lg" style="width:100%" data-act="edit-record" data-id="${r.id}">${I('pencil')}修改价格（演示离线编辑）</button>
    </div>`;
  }

  function sVault() {
    if (!ui.vault.unlocked) {
      return `<div class="mpage push">${navbar('共享空间')}
        <div class="vault-m">
          <div class="lk">${I('lock')}</div>
          <h2>${D.space.name}</h2>
          <p class="muted" style="margin:0;font-size:14px">${D.space.meta.count} 个加密对象 · ${D.space.meta.size}<br>本机已下载 ${D.space.meta.local} 个，离线也能读取</p>
          <button class="btn btn-primary btn-lg" style="width:100%;margin-top:14px" data-act="vault-unlock">${I('unlock')}输入密码查看目录</button>
          <p class="faint" style="font-size:12.5px;margin:6px 0 0">每次查看都需要输入密码，包括离线时。<br>演示密码：<b class="mono">${N.DEMO_PASSWORD}</b></p>
        </div>
      </div>`;
    }
    return `<div class="mpage push">${navbar('共享空间', `<button class="icon-btn" data-act="vault-lock" aria-label="立即锁定">${I('lock')}</button>`)}
      <div class="read-chip reveal">${I('unlock')}<span>本次读取的目录 · 返回、切到后台或锁屏后立即清除</span></div>
      <div class="mlist mat-solid reveal">${D.space.items.map((s) => `
        <button class="mrow" data-act="vault-item" data-id="${s.id}"><span class="tile-icon">${I(TYPE[s.type][0])}</span>
          <span class="grow"><div class="title">${s.name}</div><div class="sub">${TYPE[s.type][1]} · ${s.size} · ${s.updated}</div></span>
          ${s.local === 'remote' ? `<span class="sync is-offline"><span class="glyph"></span>仅云端</span>` : s.local === 'pending' ? syncBadge('pending', { dotOnly: true }) : ''}${I('lock')}</button>`).join('')}</div>
      <button class="btn btn-ghost btn-lg" style="width:100%" data-act="add" data-type="share">${I('plus')}添加共享内容</button>
    </div>`;
  }

  function sVaultItem(p) {
    const s = D.space.items.find((x) => x.id === p.id);
    const c = s.content;
    const shown = ui.vault.revealed === s.id;
    return `<div class="mpage push">${navbar(s.name)}
      ${shown ? `
        <div class="read-chip reveal">${I('unlock')}<span>本次读取 · 修订 ${s.rev} · 来自 ${s.by}</span></div>
        ${c.kind === 'file' ? `<div class="secret-m reveal" style="text-align:center;font-family:var(--font-sans)">${I('file')}<br>${c.value}</div>` : `<div class="secret-m reveal">${esc(c.value)}</div>`}
        ${c.note ? `<p class="faint" style="font-size:13px;margin:0 4px 12px">${c.note}</p>` : ''}
        <div class="mbtns">
          <button class="btn btn-ghost" data-act="vault-copy" data-id="${s.id}">${I(c.kind === 'file' ? 'arrowDown' : 'copy')}${c.kind === 'file' ? '导出' : '复制'}</button>
          <button class="btn btn-ghost" data-act="vault-hide">${I('eye')}隐藏</button>
        </div>
        <p class="faint" style="font-size:12px;text-align:center">再次查看、复制或导出都需要重新输入密码</p>`
      : `<div class="vault-m"><div class="lk">${I('lock')}</div><p class="muted" style="margin:0">内容已锁定</p>
          <button class="btn btn-primary btn-lg" style="width:100%" data-act="vault-read" data-id="${s.id}">${I('unlock')}输入密码查看</button></div>`}
    </div>`;
  }

  function sChat() {
    const A = D.agents[ui.chatAgent];
    const on = online();
    return `<div class="mpage">
      <div class="mhead"><h1>对话</h1><span class="spacer"></span><button class="icon-btn" data-act="new-session" aria-label="新会话" style="width:40px;height:40px">${I('plus')}</button></div>
      <div class="agent-tabs">${['openclaw', 'hermes'].map((id) => { const a = D.agents[id]; return `
        <button class="agent-tab oc-${id}" data-act="agent" data-id="${id}" aria-pressed="${ui.chatAgent === id}">
          <span class="am">${I(N.OWNERS[id].icon)}</span><span style="min-width:0"><div style="font-weight:650">${a.name}</div><div class="conn ${on ? 'online' : 'offline'}" style="font-size:11.5px">${on ? a.instance : '未连接'}</div></span></button>`; }).join('')}</div>
      ${on ? `<div class="mlist mat-solid">${A.sessions.map((s) => `
          <button class="mrow" data-push="session" data-id="${s.id}"><span class="grow"><div class="title">${s.title}</div><div class="sub">${s.last}</div></span>${I('chevR')}</button>`).join('')}</div>
        <p class="faint" style="font-size:12px;display:flex;gap:6px;align-items:center;margin:0 4px">${I('info')}会话由 ${A.name} 提供 · Studiolo 不保存聊天内容</p>`
      : `<div class="notice">${I('wifiOff')}<div><b>离线时无法读取会话</b><br>聊天记录保存在 ${A.name}，Studiolo 不在手机上缓存。联网后会重新读取。</div></div>`}
    </div>`;
  }

  /* 会话页：流式回复与断线恢复 */
  const chat = { msgs: [], stream: null, el: null, retry: null };
  function sSession(p) {
    const A = D.agents[ui.chatAgent];
    const title = p.id ? A.sessions.find((s) => s.id === p.id)?.title : '新会话';
    return `<div class="chatpage">
      ${navbar(`<div style="font-size:15px">${esc(title)}</div><div style="font-size:11.5px;font-weight:500">${ownerBadge(ui.chatAgent, A.instance)}</div>`, `<button class="icon-btn" data-act="drop" aria-label="模拟断线">${I('wifiOff')}</button>`)}
      <div class="mbanner" id="mbanner"></div>
      <div class="mmsgs" id="mmsgs" data-scroll></div>
      <div class="mcomposer"><div class="box ${online() ? '' : 'disabled'}" id="mbox">
        <textarea id="mta" rows="1" placeholder="${online() ? `发消息给 ${A.name}` : '离线时无法发送'}" ${online() ? '' : 'disabled'}></textarea>
        <button class="send" id="msend" aria-label="发送" ${online() ? '' : 'disabled'}>${I('arrowUp')}</button></div>
        <div class="note">${I('shield')}历史保存在 ${A.name} · Studiolo 不保存正文</div></div>
    </div>`;
  }
  function msgHTML(m) {
    if (m.role === 'user') return `<div class="mmsg user"><div class="bubble">${esc(m.text)}</div></div>`;
    return `<div class="mmsg agent oc-${ui.chatAgent}"><span class="am">${I(N.OWNERS[ui.chatAgent].icon)}</span><div class="bubble">${m.tool ? `<span class="chip" style="margin-bottom:6px">${I('data')}${m.tool}</span>\n` : ''}<span class="txt">${esc(m.text)}</span></div></div>`;
  }
  function bindSession(p) {
    const box = $('#mmsgs');
    const A = D.agents[ui.chatAgent];
    if (chat.stream) { chat.stream.finish(); chat.stream = null; }
    chat.msgs = [];
    if (p.id) {
      box.innerHTML = `<div class="mmsg agent oc-${ui.chatAgent}"><span class="am">${I(N.OWNERS[ui.chatAgent].icon)}</span><div class="bubble faint">正在从 ${A.name} 读取历史 <span class="typing"><i></i><i></i><i></i></span></div></div>`;
      if (!online()) { box.innerHTML = `<div class="notice" style="margin-top:20px">${I('wifiOff')}<div>离线：无法从 ${A.name} 读取历史</div></div>`; }
      else setTimeout(() => { if (!$('#mmsgs')) return; chat.msgs = structuredClone(D.chat[p.id] || [{ role: 'agent', text: '（这段会话的历史由 ' + A.name + ' 提供）' }]); box.innerHTML = chat.msgs.map(msgHTML).join(''); box.scrollTop = 1e6; }, 600);
    }
    const ta = $('#mta');
    const send = () => {
      const text = ta.value.trim();
      if (chat.stream) { chat.stream.pause(); chat.stream = null; setSend(); return; }
      if (!text || !online()) return;
      ta.value = '';
      box.insertAdjacentHTML('beforeend', msgHTML({ role: 'user', text }) + `<div class="mmsg agent oc-${ui.chatAgent}" id="mpend"><span class="am">${I(N.OWNERS[ui.chatAgent].icon)}</span><div class="bubble"><span class="typing"><i></i><i></i><i></i></span><div class="state">${I('check')}已送达 ${A.name}</div></div></div>`);
      box.scrollTop = 1e6;
      setTimeout(() => {
        const el = $('#mpend');
        if (!el) return;
        el.removeAttribute('id');
        el.querySelector('.bubble').innerHTML = `<span class="txt"></span><div class="state" data-state hidden></div>`;
        chat.el = el;
        chat.stream = N.streamer(el.querySelector('.txt'), D.replies[ui.chatAgent], { speed: 16, onDone: () => { chat.stream = null; setSend(); } });
        setSend();
        if (!online()) chatOnline(false);
      }, 700);
    };
    $('#msend').addEventListener('click', send);
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(110, ta.scrollHeight) + 'px'; });
  }
  function setSend() {
    const b = $('#msend');
    if (!b) return;
    b.classList.toggle('stop', !!chat.stream);
    b.innerHTML = I(chat.stream ? 'stop' : 'arrowUp');
    b.setAttribute('aria-label', chat.stream ? '停止生成' : '发送');
  }
  function chatOnline(on) {
    const banner = $('#mbanner');
    if (!banner) return;
    const A = D.agents[ui.chatAgent];
    $('#mbox')?.classList.toggle('disabled', !on);
    const ta = $('#mta'); if (ta) { ta.disabled = !on; ta.placeholder = on ? `发消息给 ${A.name}` : '离线时无法发送'; }
    if (!chat.stream) $('#msend').disabled = !on;
    clearInterval(chat.retry);
    if (!on) {
      let n = 1, w = 2;
      const paint = () => { banner.className = 'mbanner show warn'; banner.innerHTML = `${I('wifiOff')}<span>连接已中断 · 第 ${n} 次重连，${w} 秒后重试</span>`; };
      paint();
      chat.retry = setInterval(() => { w--; if (w <= 0) { n++; w = Math.min(8, 2 ** n); } paint(); }, 1000);
      if (chat.stream) {
        chat.stream.pause();
        const st = chat.el.querySelector('[data-state]');
        st.hidden = false; st.className = 'state warn'; st.innerHTML = `${I('alert')}回复中断，重连后从 ${A.name} 补齐`;
      }
    } else {
      banner.className = 'mbanner show ok';
      banner.innerHTML = `${I('check')}<span>已重新连接 · ${A.caps.replay === true ? '已补齐缺失内容' : `已从 ${A.name} 重新读取`}</span>`;
      setTimeout(() => banner.classList.remove('show'), 2500);
      if (chat.stream) {
        const st = chat.el.querySelector('[data-state]');
        st.className = 'state'; st.innerHTML = `${I('checks')}已补齐`;
        chat.stream.resume();
      }
    }
  }

  function sTasks() {
    const f = ui.jobFilter;
    const jobs = D.jobs.filter((j) => f === 'all' || (f === 'attn' ? ['fail', 'unknown'].includes(j.last) : f === 'running' ? j.last === 'running' : j.owner === f));
    const chips = [['all', '全部'], ['attn', '需要关注'], ['running', '运行中'], ['studiolo', 'Studiolo'], ['openclaw', 'OpenClaw'], ['hermes', 'Hermes']];
    return `<div class="mpage">
      <div class="mhead"><h1>任务</h1><span class="spacer"></span><button class="icon-btn" data-act="toast" data-msg="原型：新建任务先选择调度所有者" style="width:40px;height:40px" aria-label="新建任务">${I('plus')}</button></div>
      <div class="mchips">${chips.map(([k, l]) => `<button class="chip" data-act="jf" data-k="${k}" aria-pressed="${f === k}">${l}</button>`).join('')}</div>
      ${!online() ? `<div class="notice" style="margin-bottom:12px">${I('wifiOff')}<div>离线：显示的是最近一次读取的状态，操作已暂停</div></div>` : ''}
      ${jobs.map((j) => `
        <button class="jobcard mat" data-push="job" data-id="${j.id}">
          <div class="top"><b>${j.name}</b><span class="run ${j.last}">${RUN[j.last]}</span></div>
          <div>${ownerBadge(j.owner, j.owner === 'studiolo' ? '' : j.where)}</div>
          <div class="meta"><span>${j.schedule}</span><span>${j.last === 'running' ? j.lastAt.replace('正在运行 · ', '') : '下次 ' + j.next}</span></div>
        </button>`).join('') || '<p class="faint" style="text-align:center;padding:30px">没有符合条件的任务</p>'}
    </div>`;
  }

  function sJob(p) {
    const j = D.jobs.find((x) => x.id === p.id);
    const O = N.OWNERS[j.owner];
    const on = online();
    const runs = D.runs[j.id] || [{ s: j.last, at: j.lastAt.split(' · ')[0], dur: '' }];
    return `<div class="mpage push">${navbar('任务详情')}
      <div style="padding:4px 4px 14px"><h2 style="margin:0 0 4px;font-size:22px">${j.name}</h2><span class="run ${j.last}">${RUN[j.last]}</span> <span class="faint" style="font-size:12.5px">· ${j.lastAt}</span></div>
      <div class="owner-box oc-${j.owner}">
        <div>${ownerBadge(j.owner, j.owner === 'studiolo' ? '' : j.where)}</div>
        <div>${j.owner === 'studiolo' ? '由 Studiolo Core 执行，历史保存在 Core。' : `由 ${O.label} 自己的 Cron 执行；手机断开时它也会按计划继续运行。`}</div>
      </div>
      ${j.limited ? `<div class="notice warn" style="margin-bottom:12px">${I('info')}<div>${j.limited}</div></div>` : ''}
      <div class="mbtns">
        ${j.last === 'unknown'
          ? `<button class="btn btn-primary" data-act="job-verify" data-id="${j.id}" ${on ? '' : 'disabled'}>${I('search')}核对结果</button>`
          : `<button class="btn btn-primary" data-act="job-run" data-id="${j.id}" ${on && j.last !== 'running' ? '' : 'disabled'}>${I('play')}立即运行</button>`}
        <button class="btn btn-ghost" data-act="job-toggle" data-id="${j.id}" ${on && j.caps.pause ? '' : 'disabled'}>${I(j.enabled ? 'pause' : 'play')}${j.enabled ? '暂停' : '恢复'}</button>
      </div>
      ${!on ? `<p class="faint" style="font-size:12px;margin:-4px 4px 12px">${j.owner === 'studiolo' ? 'Core 不可达' : `无法连接 ${j.where}`}，暂时不能操作</p>` : ''}
      <div class="kvl mat-solid"><div><span>计划</span><span>${j.schedule}</span></div><div><span>原生表达</span><span class="mono">${j.expr}</span></div><div><span>时区</span><span>${j.tz}</span></div><div><span>下次运行</span><span>${j.next}</span></div></div>
      <div class="sec-t">运行历史<span class="spacer"></span><span style="font-weight:500">来自 ${j.owner === 'studiolo' ? 'Studiolo Core' : O.label}</span></div>
      <div class="mtimeline mat-solid">${runs.map((r) => `<div class="t"><span class="run ${r.s}">${RUN[r.s]}</span><span class="faint">${r.dur || ''}</span><span class="when">${r.at}</span></div>`).join('')}</div>
    </div>`;
  }

  function sSettings() {
    const s = N.get();
    const sw = (on, act) => `<button class="switch" role="switch" aria-checked="${on}" data-act="${act}"></button>`;
    return `<div class="mpage push">${navbar('设置')}
      <div class="sec-t" style="margin-top:4px">主题</div>
      <div class="seg mseg" role="group">${[['paper', '纸墨'], ['glass', 'Liquid Glass']].map(([v, l]) => `<button data-act="theme" data-v="${v}" aria-pressed="${s.theme === v}">${l}</button>`).join('')}</div>
      <div class="kvl mat-solid">
        <div><span>深色模式</span>${sw(s.mode === 'dark', 'mode')}</div>
        <div><span>减少透明度（关闭模糊）</span>${sw(s.blur === 'off', 'blur')}</div>
        <div><span>减少动态效果</span>${sw(s.motion === 'reduced', 'motion')}</div>
      </div>
      <p class="faint" style="font-size:12.5px;margin:0 4px 12px">低端设备会自动关闭模糊；玻璃材质只用于导航、卡片和弹层，列表与输入保持实体，保证可读性。</p>
      <div class="sec-t">同步</div>
      <div class="kvl mat-solid"><div><span>Core</span><span class="conn ${online() ? 'online' : 'offline'}">${D.core.host}</span></div><div><span>待同步</span><span>${pendingCount()} 项</span></div><div><span>本设备</span><span>Pixel 9</span></div></div>
    </div>`;
  }

  const SCREENS = { today: sToday, library: sLibrary, chat: sChat, tasks: sTasks, record: sRecord, vault: sVault, vaultItem: sVaultItem, session: sSession, job: sJob, settings: sSettings };

  /* ---------- 渲染与导航 ---------- */
  function render() {
    const c = cur();
    view.innerHTML = SCREENS[c.s](c.p || {});
    if (c.s === 'session') bindSession(c.p || {});
    N.syncSeg(view);
    renderTabbar();
    renderNotes();
  }
  function soft() {
    const c = cur();
    if (c.s === 'session') { renderTabbar(); return; }
    const pg = view.querySelector('.mpage');
    const st = pg?.scrollTop || 0;
    view.innerHTML = SCREENS[c.s](c.p || {});
    N.syncSeg(view);
    const np = view.querySelector('.mpage'); if (np) np.scrollTop = st;
    renderTabbar();
  }
  function renderTabbar() {
    const hide = cur().s === 'session';
    const tb = $('#tabbar');
    tb.style.display = hide ? 'none' : '';
    const cc = conflictCount();
    const attn = D.jobs.filter((j) => j.last === 'fail' || j.last === 'unknown').length;
    tb.innerHTML = TABS.map((t) => {
      if (t.id === '+') return `<div class="tab-add"><button data-act="add" data-type="tx" aria-label="快速新增" aria-expanded="${!!sheetOpen}">${I('plus')}</button></div>`;
      const badge = t.id === 'library' && cc ? `<span class="badge">${cc}</span>` : t.id === 'tasks' && attn ? `<span class="badge">${attn}</span>` : '';
      return `<button class="tab" data-tab="${t.id}" ${ui.tab === t.id ? 'aria-current="page"' : ''}><span class="ico">${I(t.icon)}</span>${t.label}${badge}</button>`;
    }).join('');
    $('#os-ic').innerHTML = online() ? `${I('sync')}<span style="font-size:12px">5G</span>` : `${I('wifiOff')}`;
  }
  function leaveVaultIfNeeded(nextStack) {
    const inVault = (st) => st.some((x) => x.s === 'vault' || x.s === 'vaultItem');
    if (ui.vault.unlocked && inVault(ui.stack) && !inVault(nextStack)) {
      ui.vault = { unlocked: false, revealed: null };
      N.toast(toastHost, `${I('lock')} 共享空间已锁定，内容已清除`);
    }
  }
  function tab(t, opts = {}) {
    if (t === ui.tab && !ui.stack.length && !opts.force) { view.querySelector('.mpage')?.scrollTo({ top: 0, behavior: 'smooth' }); return; }
    leaveVaultIfNeeded([]);
    N.transition(() => { ui.tab = t; ui.stack = []; render(); }, ['tab']);
  }
  function push(s, p = {}) { N.transition(() => { ui.stack.push({ s, p }); render(); }, ['forward']); }
  function back() {
    const next = ui.stack.slice(0, -1);
    const top = cur();
    if (top.s === 'vaultItem') ui.vault.revealed = null;  // 离开即清除内容
    leaveVaultIfNeeded(next);
    if (top.s === 'session') { chat.stream?.pause(); chat.stream = null; clearInterval(chat.retry); }
    N.transition(() => { ui.stack = next; render(); }, ['backward']);
  }

  /* ---------- Sheet ---------- */
  let sheetOpen = null;
  const sheet = $('#sheet');
  const scrim = $('#scrim');
  function openSheet(html, kind, onClose) {
    sheet.innerHTML = `<div class="grab"></div>${html}`;
    sheetOpen = { kind, onClose };
    requestAnimationFrame(() => { sheet.classList.add('on'); scrim.classList.add('on'); });
    renderTabbar();
    setTimeout(() => sheet.querySelector('[data-autofocus]')?.focus(), 80);
  }
  function closeSheet(result) {
    if (!sheetOpen) return;
    const s = sheetOpen; sheetOpen = null;
    sheet.classList.remove('on'); scrim.classList.remove('on');
    renderTabbar();
    s.onClose?.(result);
  }
  scrim.addEventListener('click', () => closeSheet());
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && sheetOpen) closeSheet(); });

  /** 每次读取的密码 Sheet */
  function askPw({ action, item }) {
    return new Promise((resolve) => {
      let ok = false;
      openSheet(`
        <h2 id="sheet-title">输入共享空间密码</h2>
        <div class="sub">密码只用于这一次${action}，不会被记住</div>
        <div class="scope-tag" style="margin-bottom:12px">${I('key')}<span>${action}${item ? ` · <b>${esc(item.name)}</b> · 修订 ${item.rev}` : ' · <b>目录第 1 页</b>'}</span></div>
        <form id="pwf">
          <div class="pw-field">${I('lock')}<input class="input" id="pwi" type="password" autocomplete="off" aria-label="密码" data-autofocus></div>
          <div class="pw-error" id="pwe" role="alert">密码不正确</div>
          <div class="kdf-bar" id="pwk"><i></i></div>
          <div class="mbtns" style="margin-top:12px"><button type="button" class="btn btn-ghost" data-act="sheet-cancel">取消</button><button class="btn btn-primary">验证</button></div>
        </form>
        <p class="faint" style="font-size:12px;text-align:center;margin:0">${!online() ? '离线：使用本机已下载的密文验证 · ' : ''}演示密码 <b class="mono">${N.DEMO_PASSWORD}</b></p>`, 'pw', () => resolve(ok));
      $('#pwf').addEventListener('submit', async (e) => {
        e.preventDefault();
        const i = $('#pwi'), er = $('#pwe');
        er.classList.remove('show'); $('#pwk').classList.add('on');
        const good = await N.verifyPassword(i.value);
        $('#pwk').classList.remove('on');
        if (!good) { er.classList.add('show'); i.classList.remove('shake'); void i.offsetWidth; i.classList.add('shake'); i.select(); return; }
        ok = true; i.value = ''; closeSheet();
      });
    });
  }

  /** 快速新增 Sheet */
  function openAdd(type = 'tx') {
    ui.add = { type, amount: '0', cat: '餐饮', memo: '' };
    paintAdd();
  }
  function paintAdd() {
    const a = ui.add;
    const types = [['tx', '记一笔', 'ledger'], ['web', '网站', 'globe'], ['rec', '记录', 'data'], ['share', '共享', 'shield']];
    let body = '';
    if (a.type === 'tx') {
      body = `<div class="amount num" id="amt"><small>¥</small>${a.amount}</div>
        <input class="memo" id="memo" placeholder="添加备注（例如：午饭）" value="${esc(a.memo)}">
        <div class="cats">${['餐饮', '交通', '购物', '订阅', '居住', '其他'].map((c) => `<button class="chip" data-act="cat" data-v="${c}" aria-pressed="${a.cat === c}">${c}</button>`).join('')}</div>
        <div class="keypad">${['1', '2', '3', '⌫', '4', '5', '6', '7', '8', '9', '.', '0', '00'].map((k, i) => i === 3 ? `<button data-key="⌫" aria-label="删除">⌫</button>` : `<button data-key="${k}">${k}</button>`).join('').replace('<button data-key="4">', `<button class="save" data-act="save-tx" ${+a.amount > 0 ? '' : 'disabled'}>保存</button><button data-key="4">`)}</div>`;
    } else if (a.type === 'web') {
      body = `<input class="input" style="height:48px;font-size:15px;margin-bottom:10px" id="url" placeholder="https://" data-autofocus>
        <button class="btn btn-ghost btn-lg" style="width:100%;margin-bottom:8px" data-act="paste-url">${I('copy')}粘贴剪贴板中的链接</button>
        <button class="btn btn-primary btn-lg" style="width:100%" data-act="save-web">收藏</button>
        <p class="faint" style="font-size:12px;text-align:center;margin:10px 0 0">也可以在浏览器里「分享 → Studiolo」直接收藏</p>`;
    } else if (a.type === 'rec') {
      body = `<div class="kvl mat-solid"><div><span>集合</span><span>订阅服务 ${I('chevD')}</span></div></div>
        <input class="input" style="height:48px;font-size:15px;margin-bottom:10px" placeholder="名称" data-autofocus>
        <button class="btn btn-primary btn-lg" style="width:100%" data-act="save-rec">保存</button>`;
    } else {
      body = `<textarea class="input" style="height:96px;padding:12px;font-size:15px;resize:none;margin-bottom:10px" placeholder="文本、配置或 Key…" data-autofocus></textarea>
        <div class="pw-field" style="margin-bottom:10px">${I('lock')}<input class="input" type="password" placeholder="共享空间密码（用于加密）" autocomplete="off"></div>
        <button class="btn btn-primary btn-lg" style="width:100%" data-act="save-share">加密并保存</button>
        <p class="faint" style="font-size:12px;text-align:center;margin:10px 0 0">内容会先在本机加密，再以密文同步到其它设备</p>`;
    }
    const html = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><h2 id="sheet-title" style="margin:0;flex:1">快速新增</h2><button type="button" class="icon-btn" data-act="sheet-cancel" aria-label="关闭">${I('x')}</button></div>
      <div class="add-types">${types.map(([k, l, ic]) => `<button data-act="add-type" data-k="${k}" aria-pressed="${a.type === k}">${I(ic)}${l}</button>`).join('')}</div>
      ${body}
      ${!online() ? `<div class="offline-note">${I('wifiOff')}当前离线 · 保存在本机，联网后自动同步</div>` : ''}`;
    if (sheetOpen?.kind === 'add') { sheet.innerHTML = `<div class="grab"></div>${html}`; setTimeout(() => sheet.querySelector('[data-autofocus]')?.focus(), 30); }
    else openSheet(html, 'add');
  }
  sheet.addEventListener('click', (e) => {
    const k = e.target.closest('[data-key]');
    if (k && ui.add.type === 'tx') {
      let v = ui.add.amount;
      const key = k.dataset.key;
      if (key === '⌫') v = v.length > 1 ? v.slice(0, -1) : '0';
      else if (key === '.') { if (!v.includes('.')) v += '.'; }
      else if (!(v.includes('.') && v.split('.')[1].length >= 2)) v = v === '0' ? (key === '00' ? '0' : key) : v + key;
      ui.add.amount = v;
      const amt = $('#amt');
      amt.innerHTML = `<small>¥</small>${v}`;
      amt.classList.remove('bump'); void amt.offsetWidth; amt.classList.add('bump');
      sheet.querySelector('.save').disabled = !(+v > 0);
    }
  });
  sheet.addEventListener('input', (e) => { if (e.target.id === 'memo') ui.add.memo = e.target.value; });

  /* ---------- 动作 ---------- */
  const ACT = {
    toast: (b) => N.toast(toastHost, b.dataset.msg),
    back: () => back(),
    add: (b) => { if (sheetOpen?.kind === 'add') closeSheet(); else openAdd(b.dataset.type); },
    'add-type': (b) => { ui.add.type = b.dataset.k; paintAdd(); },
    cat: (b) => { ui.add.cat = b.dataset.v; $$('[data-act="cat"]', sheet).forEach((x) => x.setAttribute('aria-pressed', String(x === b))); },
    'save-tx': () => {
      const a = ui.add;
      const icon = { 餐饮: 'cup', 交通: 'car', 购物: 'bag', 订阅: 'receipt' }[a.cat] || 'receipt';
      const tx = { id: 't' + Date.now(), title: a.memo || a.cat, cat: a.cat, icon, amount: -(+a.amount), when: '刚刚', sync: 'local', from: '本机' };
      D.ledger.tx.unshift(tx); D.ledger.spent += +a.amount;
      closeSheet();
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 已在本机保存 · ${fmtMoney(tx.amount)}`);
      if (ui.tab !== 'today' || ui.stack.length) tab('today'); 
      advance(tx);
    },
    'paste-url': () => { $('#url').value = 'https://v2.tauri.app/start/'; },
    'save-web': () => {
      const v = ($('#url').value || 'example.com').replace(/^https?:\/\//, '').split('/')[0];
      const w = { name: v.split('.')[0], url: v, tag: '未分类', color: '#3d5afe', visits: 0, sync: 'local' };
      D.websites.unshift(w); closeSheet();
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 已收藏 ${v}`);
      advance(w);
    },
    'save-rec': () => { closeSheet(); N.toast(toastHost, `${syncBadge('local', { label: '' })} 记录已在本机保存`); },
    'save-share': () => { closeSheet(); N.toast(toastHost, `${I('lock')} 已在本机加密 · 密文待同步`); },
    'sheet-cancel': () => closeSheet(),
    seg: (b) => { ui.libSeg = b.dataset.k; soft(); },
    jf: (b) => { ui.jobFilter = b.dataset.k; soft(); },
    agent: (b) => { ui.chatAgent = b.dataset.id; soft(); },
    'new-session': () => push('session', { id: null }),
    drop: () => { N.set({ online: false }); setTimeout(() => N.set({ online: true }), 4000); },
    cf: (b) => { ui.cf = b.dataset.k; soft(); },
    resolve: () => {
      const r = D.records.find((x) => x.id === D.conflict.recordId);
      r.price = ui.cf === 'local' ? D.conflict.local.price : D.conflict.remote.price;
      r.pay = D.conflict.remote.pay;
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 冲突已解决 · 正在同步`);
      advance(r);
      back();
    },
    'edit-record': (b) => {
      const r = D.records.find((x) => x.id === b.dataset.id);
      r.price = Math.round(r.price * 1.1);
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 已在本机保存${online() ? '' : ' · 联网后同步'}`);
      advance(r);
    },
    'goto-conflict': () => { ui.libSeg = 'data'; N.transition(() => { ui.tab = 'library'; ui.stack = [{ s: 'record', p: { id: 'r4' } }]; render(); }, ['forward']); },
    'explain-offline': () => N.toast(toastHost, `${I('wifiOff')} 离线：已下载的数据可以照常查看和编辑`),
    'vault-unlock': async () => {
      const ok = await askPw({ action: '查看目录' });
      if (ok) N.transition(() => { ui.vault.unlocked = true; render(); });
    },
    'vault-lock': () => { ui.vault = { unlocked: false, revealed: null }; N.toast(toastHost, `${I('lock')} 已锁定，内容已清除`); N.transition(() => render()); },
    'vault-item': async (b) => {
      const s = D.space.items.find((x) => x.id === b.dataset.id);
      if (!online() && s.local === 'remote') { N.toast(toastHost, `${I('wifiOff')} 离线不可读：该对象尚未下载到本机`); return; }
      ui.vault.revealed = null;
      push('vaultItem', { id: s.id });
      const ok = await askPw({ action: '读取', item: s });
      if (ok && cur().s === 'vaultItem' && cur().p.id === s.id) { s.local = s.local === 'remote' ? 'downloaded' : s.local; ui.vault.revealed = s.id; render(); }
    },
    'vault-read': async (b) => {
      const s = D.space.items.find((x) => x.id === b.dataset.id);
      const ok = await askPw({ action: '读取', item: s });
      if (ok) { ui.vault.revealed = s.id; render(); }
    },
    'vault-hide': () => { ui.vault.revealed = null; render(); },
    'vault-copy': async (b) => {
      const s = D.space.items.find((x) => x.id === b.dataset.id);
      const what = s.content.kind === 'file' ? '导出' : '复制';
      const ok = await askPw({ action: what, item: s });
      if (ok) N.toast(toastHost, `${I('check')} 已${what}`);
    },
    'job-run': (b) => {
      const j = D.jobs.find((x) => x.id === b.dataset.id);
      j.last = 'running'; j.lastAt = '正在运行 · 刚刚';
      (D.runs[j.id] ||= []).unshift({ s: 'running', at: '刚刚', dur: '…' });
      N.toast(toastHost, `${I('play')} 已请求 ${N.OWNERS[j.owner].label} 运行`);
      soft();
      setTimeout(() => { j.last = 'ok'; j.lastAt = '刚刚 · 9 秒'; D.runs[j.id][0] = { s: 'ok', at: '刚刚', dur: '9 秒' }; soft(); }, 3000);
    },
    'job-verify': (b) => {
      const j = D.jobs.find((x) => x.id === b.dataset.id);
      N.toast(toastHost, `${I('search')} 正在查询 Hermes…`);
      setTimeout(() => { j.last = 'ok'; j.lastAt = '已在 Hermes 确认成功'; D.runs[j.id] = [{ s: 'ok', at: '今天 10:00', dur: '2 分 04 秒' }]; soft(); }, 1000);
    },
    'job-toggle': (b) => {
      const j = D.jobs.find((x) => x.id === b.dataset.id);
      j.enabled = !j.enabled; j.last = j.enabled ? 'ok' : 'paused'; j.next = j.enabled ? '按计划' : '已暂停';
      soft();
    },
    theme: (b) => N.set({ theme: b.dataset.v }),
    mode: () => N.set({ mode: N.get().mode === 'dark' ? 'light' : 'dark' }),
    blur: () => N.set({ blur: N.get().blur === 'off' ? 'on' : 'off' }),
    motion: () => N.set({ motion: N.get().motion === 'reduced' ? 'full' : 'reduced' }),
  };

  $('#screen').addEventListener('click', (e) => {
    const a = e.target.closest('[data-act]');
    if (a && !a.disabled && ACT[a.dataset.act]) { ACT[a.dataset.act](a, e); return; }
    const t = e.target.closest('[data-tab]');
    if (t) {
      if (t.dataset.seg) ui.libSeg = t.dataset.seg;
      if (t.dataset.filter) ui.jobFilter = t.dataset.filter;
      tab(t.dataset.tab, { force: !!(t.dataset.seg || t.dataset.filter) });
      return;
    }
    const p = e.target.closest('[data-push]');
    if (p) push(p.dataset.push, { id: p.dataset.id });
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && ui.vault.unlocked) { ui.vault = { unlocked: false, revealed: null }; render(); }
  });

  /* ---------- 说明面板 ---------- */
  const NOTES = {
    today: ['今天', '打开即看三件事：记账余量、任务是否跑完、同步是否正常。四个快捷入口覆盖最常见的「快速一下」。同步胶囊始终在标题下方，离线、待同步、冲突用同一套图形。'],
    library: ['资料', '账本、网站、数据、设备归到一个标签里，用顶部分段切换，共用一个搜索框。共享空间放在最上面作为独立入口，锁的图标说明它需要密码。'],
    chat: ['对话', '先选 Agent（OpenClaw / Hermes），再选会话。会话列表和历史实时来自 Agent，离线时直接说明「Studiolo 不缓存」，不做假的本地历史。'],
    tasks: ['任务', '用筛选芯片把 Studiolo 原生任务和 Agent Cron 放在同一个列表。每张卡片都显示调度所有者与实例，「需要关注」把失败和结果未知集中起来。'],
    record: ['记录详情 / 冲突', '手机也能处理冲突：只展示真正冲突的字段，另一台设备单独改过的字段自动合并并说明来源。'],
    vault: ['共享空间', '锁定页只显示数量、大小和本机副本数，不显示文件名。查看目录要输入一次密码，查看每个对象还要再输一次。返回或切到后台后立即清除。'],
    vaultItem: ['共享内容', '每次读取都会弹出密码 Sheet，并写明这次是读取、复制还是导出，以及对象和修订号。离线时用本机密文验证。'],
    session: ['会话', '流式回复，断线时横幅显示重连进度，被打断的回复会标为「中断」，重连后按 Agent 能力补齐或重新读取，不会重复发送。底栏在这里隐藏，把空间留给输入法。'],
    job: ['任务详情', '所有者卡片说明「谁在跑、断开后会怎样」；历史标明来源。离线或能力不足时按钮禁用，并说明原因。'],
    settings: ['设置 · 主题', '可以在这里或上方控制条切换 Liquid Glass，再打开「减少透明度」和「减少动态效果」，看降级后的样子。'],
  };
  function renderNotes() {
    const c = cur();
    const [t, d] = NOTES[c.s] || NOTES.today;
    $('#notes').innerHTML = `
      <h2>手机端 · 底部标签导航</h2>
      <div class="tabmap"><div>今天</div><div>资料</div><div class="add">＋</div><div>对话</div><div>任务</div></div>
      <p><b>为什么是这五个位置：</b>手机上最常做的是「记一笔、找一条、看任务、问 Agent」。<b>＋</b> 放在拇指最容易够到的正中，一按就是记账键盘，也能切到收藏网站、新建记录或共享内容。</p>
      <ul>
        <li><b>资料</b>合并账本、网站、数据、设备，靠分段切换，避免底栏超过 5 个。</li>
        <li><b>共享空间</b>不占底栏：使用频率低、每次都要密码，放在「资料」顶部和「今天」快捷入口里。</li>
        <li><b>设置 / API / 设备管理</b>属于低频配置，从头像进入。</li>
        <li>角标只用于需要处理的事：数据冲突、失败或结果未知的任务。</li>
      </ul>
      <div class="now" style="margin-top:18px"><h3>当前画面 · ${t}</h3><p style="margin:0">${d}</p></div>
      <h3>试一试</h3>
      <div class="try">
        <button data-try="add">按 ＋ 记一笔</button>
        <button data-try="vault">打开共享空间</button>
        <button data-try="chat">发消息后断网</button>
        <button data-try="conflict">处理冲突</button>
        <button data-try="glass">Liquid Glass + 关模糊</button>
        <button data-try="offline">切换离线</button>
      </div>`;
  }
  $('#notes').addEventListener('click', (e) => {
    const b = e.target.closest('[data-try]');
    if (!b) return;
    const k = b.dataset.try;
    if (k === 'add') openAdd('tx');
    if (k === 'vault') { ui.tab = 'library'; push('vault'); }
    if (k === 'chat') { ui.tab = 'chat'; ui.stack = []; push('session', { id: 'c1' }); setTimeout(() => N.toast(toastHost, '输入一句话发送，再点右上角 Wi-Fi 图标模拟断线'), 700); }
    if (k === 'conflict') ACT['goto-conflict']();
    if (k === 'glass') N.set({ theme: 'glass', blur: N.get().theme === 'glass' && N.get().blur === 'on' ? 'off' : 'on' });
    if (k === 'offline') N.set({ online: !online() });
  });

  N.on((s, prev) => {
    if (s.online !== prev.online) {
      chatOnline(s.online);
      soft();
      N.toast(toastHost, s.online ? `${I('sync')} 已联网，正在同步` : `${I('wifiOff')} 已离线 · 可以继续记录`);
      if (s.online) setTimeout(flushAll, 1400);
    } else if (cur().s === 'settings') soft();
    requestAnimationFrame(() => N.syncSeg(document));
  });

  N.protoBar($('#proto'), { page: 'mobile' });
  render();
})();
