/* ==========================================================================
   Studiolo 桌面端原型逻辑
   ========================================================================== */
(() => {
  const N = window.Studiolo;
  const { icon: I, data: D, syncBadge, ownerBadge, fmtMoney } = N;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const win = $('#win');
  const main = $('#main');
  const toastHost = $('#toasts');
  const online = () => N.get().online;

  const ui = {
    page: 'today',
    dataCol: 'subs', recordId: 'r4', recordFilter: 'all', cfChoice: 'local',
    vault: { unlocked: false, sel: null, revealed: null },
    jobOwner: 'all', jobStatus: null, jobId: 'j3', newJobOwner: 'studiolo',
    settingsSec: 'appearance',
  };

  /* ---------- 导航结构 ---------- */
  const NAV = [
    { sec: null, items: [{ id: 'today', label: '今天', icon: 'today' }] },
    { sec: '资料', items: [
      { id: 'ledger', label: '账本', icon: 'ledger' },
      { id: 'websites', label: '网站', icon: 'globe' },
      { id: 'data', label: '数据', icon: 'data' },
      { id: 'devices', label: '设备', icon: 'device' },
    ] },
    { sec: '协同', items: [
      { id: 'space', label: '共享空间', icon: 'shield' },
      { id: 'agent', label: 'Agent', icon: 'chat' },
      { id: 'tasks', label: '任务', icon: 'tasks' },
    ] },
  ];
  const FOOT = [
    { id: 'api', label: '集成与 API', icon: 'api' },
    { id: 'settings', label: '设置', icon: 'settings' },
  ];
  const ALL = [...NAV.flatMap((g) => g.items), ...FOOT];
  const labelOf = (id) => ALL.find((x) => x.id === id)?.label || '';
  const secOf = (id) => NAV.find((g) => g.items.some((x) => x.id === id))?.sec;

  /* ---------- 同步统计 ---------- */
  function queue() {
    const q = [];
    D.ledger.tx.forEach((t) => (t.sync === 'pending' || t.sync === 'local') && q.push({ kind: '账本', icon: 'ledger', name: t.title, s: t.sync }));
    D.websites.forEach((w) => (w.sync === 'pending' || w.sync === 'local') && q.push({ kind: '网站', icon: 'globe', name: w.name, s: w.sync }));
    D.records.forEach((r) => r.sync !== 'synced' && q.push({ kind: '数据', icon: 'data', name: r.name, s: r.sync, id: r.id }));
    // 共享空间：锁定状态下不显示对象名，只显示数量
    const sp = D.space.items.filter((x) => x.local === 'pending').length;
    if (sp) q.push({ kind: '共享空间', icon: 'shield', name: `${sp} 个加密对象`, s: 'pending' });
    return q;
  }
  const counts = () => {
    const q = queue();
    return { pending: q.filter((x) => x.s !== 'conflict').length, conflict: q.filter((x) => x.s === 'conflict').length, q };
  };

  /** 新建 / 修改后的状态推进：本机保存 → 待同步 → 已同步（在线时） */
  function advance(obj, key = 'sync', after) {
    obj[key] = 'local';
    refresh();
    setTimeout(() => {
      obj[key] = 'pending'; refresh();
      if (online()) setTimeout(() => { if (online() && obj[key] === 'pending') { obj[key] = 'synced'; refresh(); after?.(); } }, 1700);
    }, 700);
  }
  function flushAll(silent) {
    if (!online()) return;
    let n = 0;
    D.ledger.tx.forEach((t) => { if (t.sync === 'pending' || t.sync === 'local') { t.sync = 'synced'; n++; } });
    D.websites.forEach((w) => { if (w.sync === 'pending' || w.sync === 'local') { w.sync = 'synced'; n++; } });
    D.records.forEach((r) => { if (r.sync === 'pending' || r.sync === 'local') { r.sync = 'synced'; n++; } });
    D.space.items.forEach((s) => { if (s.local === 'pending') { s.local = 'downloaded'; n++; } });
    refresh();
    if (!silent || n) N.toast(toastHost, `${syncBadge('synced', { label: '' })} 已同步 ${n} 项更改到 Core`);
  }

  /* ---------- 外壳渲染 ---------- */
  function renderChrome() {
    $('#tb-brand').innerHTML = `${N.logoSvg}<span>Studiolo</span>`;
    $('#btn-nav').innerHTML = I('panel');
    $('#btn-cmdk').innerHTML = `${I('search')}<span>搜索或执行命令</span><span class="kbd">${N.get().platform === 'mac' ? '⌘' : 'Ctrl'}</span><span class="kbd">K</span>`;
    $('#btn-dock').innerHTML = I('sidebar');
    renderSidebar(); renderCrumbs(); renderStatus();
  }
  function renderSidebar() {
    const c = counts();
    const item = (x) => {
      let extra = '';
      if (x.id === 'data' && c.conflict) extra = `<span class="count alert">${c.conflict}</span>`;
      if (x.id === 'space') extra = ui.vault.unlocked ? `<svg class="i lockmark" viewBox="0 0 24 24" style="color:var(--accent)">${''}<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 7.7-1.5"/></svg>` : I('lock', 'lockmark');
      if (x.id === 'tasks') extra = `<span class="count">${D.jobs.filter((j) => j.last === 'fail' || j.last === 'unknown').length ? '<span style="color:var(--danger)">●</span>' : ''}</span>`;
      return `<button class="nav-item" data-go="${x.id}" ${ui.page === x.id ? 'aria-current="page"' : ''} title="${x.label}">${I(x.icon)}<span class="label">${x.label}</span>${extra}</button>`;
    };
    $('#sidebar').innerHTML = `
      ${NAV.map((g) => `${g.sec ? `<div class="nav-sec">${g.sec}</div>` : ''}${g.items.map(item).join('')}`).join('')}
      <div class="nav-foot">
        ${FOOT.map(item).join('')}
        <div class="me"><span class="avatar">Y</span><span class="meta"><div class="who">${D.user.name}</div><div class="ws">${D.user.workspace}</div></span></div>
      </div>`;
  }
  function renderCrumbs() {
    const sec = secOf(ui.page);
    $('#crumbs').innerHTML = `${sec ? `<span>${sec}</span>${I('chevR')}` : ''}<b>${labelOf(ui.page)}</b>`;
  }
  function renderStatus() {
    const c = counts();
    const on = online();
    let syncHtml;
    if (!on) syncHtml = `${syncBadge('offline', { label: '离线' })}<span class="faint">更改保存在本机${c.pending ? ` · ${c.pending} 项待同步` : ''}</span>`;
    else if (c.pending) syncHtml = syncBadge('pending', { label: `${c.pending} 项待同步` });
    else syncHtml = syncBadge('synced', { label: '全部已同步' });
    if (c.conflict) syncHtml += `<span class="sync is-conflict"><span class="glyph"><b style="font-size:10px">!</b></span>${c.conflict} 个冲突</span>`;
    $('#statusbar').innerHTML = `
      <button class="sb-item" id="sb-sync" aria-haspopup="true" aria-controls="sync-panel">${syncHtml}</button>
      <span class="sb-item"><span class="conn ${on ? 'online' : 'offline'}">${on ? `Core · ${D.core.host}` : 'Core 不可达'}</span></span>
      <span class="spacer"></span>
      ${!on ? `<span class="sb-item sb-offline">${I('wifiOff')}离线模式</span>` : ''}
      <span class="sb-item"><span class="conn ${on ? 'online' : 'offline'}">OpenClaw · studio</span></span>
      <span class="sb-item"><span class="conn ${on ? 'online' : 'offline'}">Hermes · nas-01</span></span>
      <span class="sb-item faint">${N.get().theme === 'glass' ? 'Liquid Glass' : '纸墨'} · ${N.get().mode === 'dark' ? '深色' : '浅色'}</span>
      <span class="sb-item faint">Studiolo ${D.core.version}</span>`;
    // 标题栏同步胶囊
    $('#tb-sync').innerHTML = !on ? syncBadge('offline', { label: '离线 · 本机可用' })
      : c.conflict ? syncBadge('conflict', { label: `${c.conflict} 个冲突` })
      : c.pending ? syncBadge('pending', { label: `${c.pending} 项待同步` }) : syncBadge('synced');
    if (!$('#sync-panel').hidden) renderSyncPanel();
  }
  function renderSyncPanel() {
    const c = counts();
    const on = online();
    $('#sync-panel').innerHTML = `
      <h3>同步</h3>
      <div class="faint" style="font-size:12.5px">${on ? `已连接 ${D.core.host} · 最近一次同步 2 分钟前` : '离线：所有更改都已保存在本机，联网后自动同步'}</div>
      <div class="queue">
        ${c.q.length ? c.q.map((x) => `
          <div class="row"><span class="tile-icon" style="width:26px;height:26px">${I(x.icon)}</span>
            <span class="grow"><div class="title" style="font-size:12.5px">${x.name}</div><div class="sub">${x.kind}</div></span>
            ${x.s === 'conflict' ? `<button class="btn btn-sm btn-danger" data-act="goto-conflict" data-id="${x.id}">处理冲突</button>` : syncBadge(x.s === 'local' ? 'local' : 'pending', { dotOnly: false })}
          </div>`).join('') : `<div class="cleared" style="padding:20px">${I('checks')}所有更改均已同步</div>`}
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="faint" style="font-size:11.5px;flex:1">共享空间只同步密文，这里不会显示内容名称。</span>
        <button class="btn btn-primary btn-sm" data-act="flush" ${on && c.pending ? '' : 'disabled'}>${I('sync')}立即同步</button>
      </div>`;
  }
  function refresh() {
    renderSidebar(); renderStatus();
    // 局部刷新当前页里依赖同步状态的部分
    if (['today', 'data', 'ledger', 'websites'].includes(ui.page)) renderPage(true);
  }

  /* ---------- 路由 ---------- */
  function go(page, opts = {}) {
    if (page === ui.page && !opts.force) return;
    if (ui.page === 'space' && page !== 'space' && ui.vault.unlocked) lockVault(true);
    N.transition(() => {
      ui.page = page;
      renderPage();
      renderSidebar(); renderCrumbs();
      main.scrollTop = 0;
    });
  }
  function renderPage(soft) {
    // 软刷新：保留输入框焦点与滚动
    const st = main.scrollTop;
    const focusId = soft && document.activeElement?.id;
    if (ui.page === 'agent') { if (!soft) mountAgentPage(); return; }
    // 软刷新时保留输入中的文字
    const vals = {};
    if (soft) $$('input[id]', main).forEach((i) => { if (i.type !== 'password') vals[i.id] = i.value; });
    main.innerHTML = (PAGES[ui.page] || PAGES.today)();
    BIND[ui.page]?.();
    N.syncSeg(main);
    if (soft) {
      Object.entries(vals).forEach(([id, v]) => { const el = $('#' + id); if (el && el.value !== v) { el.value = v; el.dispatchEvent(new Event('input')); } });
      main.scrollTop = st; if (focusId) $('#' + focusId)?.focus();
    }
  }

  /* ======================================================================
     页面：今天
     ====================================================================== */
  function pToday() {
    const L = D.ledger;
    const pct = Math.min(100, Math.round((L.spent / L.budget) * 100));
    const max = Math.max(...L.daily);
    const c = counts();
    const on = online();
    const total = 48;
    const synced = total - c.pending - c.conflict;
    const circ = 2 * Math.PI * 21;
    const ringColor = c.conflict ? 'var(--danger)' : c.pending ? 'var(--warn)' : 'var(--ok)';
    const jobs = ['j3', 'j4', 'j1'].map((id) => D.jobs.find((j) => j.id === id));
    const runLabel = { ok: '成功', fail: '失败', running: '运行中', paused: '已暂停', unknown: '结果未知' };
    const sessions = [
      { a: 'openclaw', ...D.agents.openclaw.sessions[0] },
      { a: 'hermes', ...D.agents.hermes.sessions[0] },
      { a: 'openclaw', ...D.agents.openclaw.sessions[1] },
    ];
    return `<div class="page">
      <header class="ph">
        <div><div class="eyebrow">11 月 16 日 · 星期一</div><h1>晚上好，${D.user.name}</h1></div>
        <div class="actions"><button class="btn btn-ghost" data-act="toast" data-msg="原型：首页卡片可拖拽调整与增删">${I('grid')}调整布局</button></div>
      </header>

      <label class="capture mat">
        ${I('sparkle')}
        <input id="cap" placeholder="记一笔「午饭 32」，粘贴网址收藏，或直接问 Agent…" autocomplete="off">
        <span class="intent" id="cap-intent" hidden></span>
        <span class="kbd">Enter</span>
      </label>

      <div class="bento">
        <section class="card mat s5" aria-labelledby="h-ledger">
          <h2 class="card-h" id="h-ledger">${I('ledger')} ${L.month}支出<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-go="ledger">账本 ${I('chevR')}</button></h2>
          <div class="big-num num">${fmtMoney(L.spent, false)}<small>预算 ¥${L.budget.toLocaleString()}</small></div>
          <div class="meter"><i style="width:${pct}%"></i></div>
          <div class="faint" style="font-size:12px">已用 ${pct}% · 剩余 14 天 · 日均 ¥405</div>
          <div class="bars" aria-hidden="true">${L.daily.map((v, i) => `<i class="${i === L.daily.length - 1 ? 'hi' : ''}" style="height:${Math.max(6, (v / max) * 100)}%;animation-delay:${i * 18}ms"></i>`).join('')}</div>
          <div class="legend">${L.cats.map((x) => `<span style="--c:${x.c}">${x.name} ¥${x.v.toLocaleString()}</span>`).join('')}</div>
        </section>

        <section class="card mat s4" aria-labelledby="h-tasks">
          <h2 class="card-h" id="h-tasks">${I('tasks')} 任务<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-go="tasks">全部 ${I('chevR')}</button></h2>
          <div class="list">
            ${jobs.map((j) => `
              <button class="row" data-act="open-job" data-id="${j.id}" style="padding:9px 8px">
                <span class="grow"><div class="title">${j.name}</div><div class="sub">${ownerBadge(j.owner, j.where)}</div></span>
                <span style="text-align:right"><span class="run ${j.last}">${runLabel[j.last]}</span><div class="sub">${j.last === 'running' ? '已 38 秒' : j.last === 'ok' ? '下次 ' + j.next : j.lastAt.split(' · ')[0]}</div></span>
              </button>`).join('')}
          </div>
        </section>

        <section class="card mat s3" aria-labelledby="h-sync">
          <h2 class="card-h" id="h-sync">${I('sync')} 同步</h2>
          <div class="sync-ring">
            <div class="ring"><svg viewBox="0 0 52 52"><circle class="bgc" cx="26" cy="26" r="21"/><circle class="fg" cx="26" cy="26" r="21" style="stroke:${ringColor};stroke-dasharray:${circ};stroke-dashoffset:${circ * (1 - synced / total)}"/></svg>
              <span class="c" style="color:${ringColor}">${on ? I(c.conflict ? 'alert' : c.pending ? 'sync' : 'checks') : I('wifiOff')}</span></div>
            <div><div style="font-weight:650">${!on ? '离线 · 本机可用' : c.conflict ? '有冲突待处理' : c.pending ? '正在排队同步' : '全部已同步'}</div><div class="faint" style="font-size:12px">${on ? '2 分钟前 · ' + D.core.host : '联网后自动同步'}</div></div>
          </div>
          <div class="kv">
            <div>${syncBadge('local')}<span class="faint">全部</span></div>
            <div>${syncBadge('pending')}<span class="num">${c.pending} 项</span></div>
            <div>${syncBadge('conflict')}${c.conflict ? `<button class="btn btn-sm btn-danger" data-act="goto-conflict" data-id="r4">处理</button>` : '<span class="faint">无</span>'}</div>
          </div>
        </section>

        <section class="card mat s5" aria-labelledby="h-web">
          <h2 class="card-h" id="h-web">${I('globe')} 常用网站<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-go="websites">全部 ${I('chevR')}</button></h2>
          <div class="site-grid">${D.websites.slice(0, 8).map((w) => `
            <button class="site" data-act="toast" data-msg="打开 ${w.url}"><span class="fav" style="background:${w.color}">${w.name[0]}</span><span style="min-width:0"><div class="n">${w.name}</div><div class="u">${w.url}</div></span></button>`).join('')}</div>
        </section>

        <section class="card mat s3" aria-labelledby="h-vault">
          <h2 class="card-h" id="h-vault">${I('shield')} 共享空间</h2>
          <div class="vault-tile">
            <span class="lk">${I('lock')}</span>
            <div style="font-weight:650">已加密 · ${D.space.meta.count} 个对象</div>
            <div class="faint" style="font-size:12px">${D.space.meta.size} · 本机已下载 ${D.space.meta.local} 个</div>
            <button class="btn btn-ghost btn-sm" data-go="space" style="margin-top:6px">${I('unlock')}输入密码查看</button>
          </div>
        </section>

        <section class="card mat s4" aria-labelledby="h-agent">
          <h2 class="card-h" id="h-agent">${I('chat')} 最近对话<span class="spacer"></span><button class="btn btn-sm btn-subtle" data-go="agent">打开 ${I('chevR')}</button></h2>
          ${on ? `<div class="list">${sessions.map((s) => `
              <button class="row" data-act="open-session" data-agent="${s.a}" data-id="${s.id}" style="padding:9px 8px">
                <span class="grow"><div class="title">${s.title}</div><div class="sub">${ownerBadge(s.a)}</div></span><span class="faint" style="font-size:12px">${s.last}</span>
              </button>`).join('')}</div>
            <div class="faint" style="font-size:11.5px;margin-top:6px;display:flex;gap:6px;align-items:center">${I('info')}会话列表实时来自各 Agent，Studiolo 不缓存</div>`
          : `<div class="notice">${I('wifiOff')}<div><b>离线时无法读取 Agent 会话</b><br>Studiolo 不在本机保存聊天内容，联网后会从 OpenClaw / Hermes 重新读取。</div></div>`}
        </section>
      </div>
    </div>`;
  }
  function parseIntent(v) {
    v = v.trim();
    if (!v) return null;
    if (/^(https?:\/\/)?[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/i.test(v)) {
      const host = v.replace(/^https?:\/\//, '').split('/')[0];
      return { type: 'web', host, label: `收藏网站 · ${host}`, icon: 'globe' };
    }
    const m = v.match(/^(.+?)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(元|块)?$/);
    if (m) {
      const t = m[1].trim();
      const cat = /饭|餐|面|咖啡|奶茶|菜|早|晚|午/.test(t) ? '餐饮' : /地铁|打车|油|公交|停车/.test(t) ? '交通' : /会员|订阅/.test(t) ? '订阅' : '其他';
      return { type: 'tx', title: t, amount: +m[2], cat, label: `记账 · ${cat} · ¥${(+m[2]).toFixed(2)}`, icon: 'ledger' };
    }
    return { type: 'ask', label: '发给 Agent', icon: 'chat' };
  }
  function bindToday() {
    const cap = $('#cap');
    const intent = $('#cap-intent');
    cap.addEventListener('input', () => {
      const it = parseIntent(cap.value);
      intent.hidden = !it;
      if (it) intent.innerHTML = `${I(it.icon)}${it.label}`;
    });
    cap.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' || e.isComposing) return;
      const it = parseIntent(cap.value);
      if (!it) return;
      if (it.type === 'tx') {
        const tx = { id: 't' + Date.now(), title: it.title, cat: it.cat, icon: it.cat === '交通' ? 'car' : it.cat === '餐饮' ? 'cup' : 'receipt', amount: -it.amount, when: '刚刚', sync: 'local', from: '本机' };
        D.ledger.tx.unshift(tx);
        D.ledger.spent += it.amount;
        N.toast(toastHost, `${syncBadge('local', { label: '' })} 已记一笔：${it.title} ¥${it.amount.toFixed(2)}${online() ? '' : ' · 联网后同步'}`);
        cap.value = ''; intent.hidden = true;
        advance(tx);
      } else if (it.type === 'web') {
        const w = { name: it.host.split('.')[0].replace(/^\w/, (c) => c.toUpperCase()), url: it.host, tag: '未分类', color: '#3d5afe', visits: 0, sync: 'local' };
        D.websites.unshift(w);
        N.toast(toastHost, `${syncBadge('local', { label: '' })} 已收藏 ${it.host}`);
        cap.value = ''; intent.hidden = true;
        advance(w);
      } else {
        const text = cap.value.trim();
        cap.value = ''; intent.hidden = true;
        openDock();
        setTimeout(() => dockChat.send(text), 250);
      }
    });
  }

  /* ======================================================================
     页面：账本
     ====================================================================== */
  function pLedger() {
    const L = D.ledger;
    const tot = L.cats.reduce((a, b) => a + b.v, 0);
    return `<div class="page">
      <header class="ph"><div><h1>账本</h1><div class="sub">${L.month} · 个人账本 · 时区 Asia/Shanghai</div></div>
        <div class="actions"><div class="seg"><button aria-pressed="true">本月</button><button>上月</button><button>今年</button></div><button class="btn btn-primary" data-act="focus-capture">${I('plus')}记一笔</button></div></header>
      <div class="stats4">
        <div class="card mat"><div class="l">支出</div><div class="v num">${fmtMoney(L.spent, false)}</div></div>
        <div class="card mat"><div class="l">收入</div><div class="v num amt-pos">${fmtMoney(L.income, false)}</div></div>
        <div class="card mat"><div class="l">结余</div><div class="v num">${fmtMoney(L.income - L.spent, false)}</div></div>
        <div class="card mat"><div class="l">预算使用</div><div class="v num">${Math.round((L.spent / L.budget) * 100)}%</div><div class="meter" style="margin:8px 0 0"><i style="width:${Math.round((L.spent / L.budget) * 100)}%"></i></div></div>
      </div>
      <div class="bento">
        <section class="card mat s8">
          <h2 class="card-h">${I('receipt')} 流水<span class="spacer"></span><span class="faint" style="font-weight:400">每条都标明同步状态与来源设备</span></h2>
          <table class="tbl"><thead><tr><th>项目</th><th>分类</th><th>时间</th><th>来源</th><th>同步</th><th class="r">金额</th></tr></thead>
            <tbody>${L.tx.map((t) => `<tr class="${t.when === '刚刚' ? 'flash' : ''}"><td><span style="display:inline-flex;align-items:center;gap:10px"><span class="tile-icon" style="width:28px;height:28px">${I(t.icon)}</span>${t.title}</span></td><td class="muted">${t.cat}</td><td class="muted">${t.when}</td><td class="faint">${t.from}</td><td>${syncBadge(t.sync)}</td><td class="r num ${t.amount > 0 ? 'amt-pos' : ''}" style="font-weight:600">${fmtMoney(t.amount)}</td></tr>`).join('')}</tbody></table>
        </section>
        <section class="card mat s4">
          <h2 class="card-h">${I('layers')} 分类</h2>
          <div class="cat-bar">${L.cats.map((c) => `<i style="--c:${c.c};flex:${c.v}"></i>`).join('')}</div>
          <div class="kv">${L.cats.map((c) => `<div><span style="width:8px;height:8px;border-radius:2px;background:${c.c}"></span>${c.name}<span class="num muted">¥${c.v.toLocaleString()} · ${Math.round((c.v / tot) * 100)}%</span></div>`).join('')}</div>
        </section>
      </div>
    </div>`;
  }

  /* ======================================================================
     页面：网站
     ====================================================================== */
  function pWebsites() {
    const tags = ['全部', ...new Set(D.websites.map((w) => w.tag))];
    return `<div class="page">
      <header class="ph"><div><h1>网站</h1><div class="sub">${D.websites.length} 个收藏 · 手机分享的链接也会出现在这里</div></div>
        <div class="actions"><button class="btn btn-primary" data-act="focus-capture">${I('plus')}收藏网站</button></div></header>
      <div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">${tags.map((t, i) => `<button class="chip" aria-pressed="${i === 0}">${t}</button>`).join('')}</div>
      <div class="web-grid">${D.websites.map((w) => `
        <button class="web-card mat" data-act="toast" data-msg="打开 ${w.url}">
          <div class="top"><span class="fav" style="background:${w.color};width:36px;height:36px;border-radius:10px">${w.name[0]}</span><div style="min-width:0"><div style="font-weight:600">${w.name}</div><div class="faint" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${w.url}</div></div></div>
          <div class="foot"><span class="chip">${w.tag}</span><span>${w.visits} 次访问</span>${syncBadge(w.sync, { dotOnly: w.sync === 'synced' })}</div>
        </button>`).join('')}</div>
    </div>`;
  }

  /* ======================================================================
     页面：数据（三栏：集合 · 表格 · 检查器 / 冲突）
     ====================================================================== */
  function pData() {
    const col = D.collections.find((c) => c.id === ui.dataCol);
    const f = ui.recordFilter;
    const recs = D.records.filter((r) => f === 'all' || (f === 'pending' ? ['pending', 'local'].includes(r.sync) : r.sync === f));
    const isSubs = ui.dataCol === 'subs';
    return `<div class="page full"><div class="split" style="grid-template-columns:220px minmax(0,1fr) 360px">
      <aside class="pane-side">
        <div class="pane-h"><h2>数据</h2><span class="spacer"></span><button class="icon-btn" title="新建集合" data-act="toast" data-msg="原型：新建集合">${I('plus')}</button></div>
        <div class="list" style="padding:0 8px">${D.collections.map((c) => `
          <button class="row ${c.id === ui.dataCol ? 'is-selected' : ''}" data-act="col" data-id="${c.id}">
            <span class="tile-icon">${I(c.icon)}</span><span class="grow"><div class="title">${c.name}</div><div class="sub">${c.count} 条 · ${c.updated}</div></span>
          </button>`).join('')}</div>
      </aside>
      <section style="display:flex;flex-direction:column;min-width:0;overflow:hidden">
        <div class="toolbar">
          <h2 style="margin:0;font-size:16px">${col.name}</h2><span class="faint">${col.count} 条</span>
          <span class="spacer"></span>
          <div class="search">${I('search')}<input class="input" placeholder="在集合中搜索"></div>
          <div class="seg" role="group" aria-label="同步筛选">
            ${[['all', '全部'], ['pending', '待同步'], ['conflict', '冲突']].map(([k, l]) => `<button data-act="rfilter" data-k="${k}" aria-pressed="${f === k}">${l}</button>`).join('')}
          </div>
          <button class="btn btn-primary" data-act="new-record">${I('plus')}新建记录</button>
        </div>
        <div style="overflow:auto;flex:1">
          ${isSubs ? `<table class="tbl"><thead><tr><th>名称</th><th class="r">价格</th><th>周期</th><th>续费日</th><th>支付方式</th><th>状态</th><th>同步</th></tr></thead>
            <tbody>${recs.map((r) => `<tr data-act="rec" data-id="${r.id}" class="${r.id === ui.recordId ? 'is-selected' : ''} ${r._flash ? 'flash' : ''}">
              <td style="font-weight:550">${r.name}</td><td class="r num">¥${r.price}</td><td class="muted">${r.cycle}</td><td class="muted">${r.renew}</td><td class="muted">${r.pay}</td>
              <td>${r.status === '已取消' ? `<span class="chip">${r.status}</span>` : `<span class="muted">${r.status}</span>`}</td><td>${syncBadge(r.sync, { dotOnly: r.sync === 'synced' })}</td></tr>`).join('')}</tbody></table>`
          : `<div class="cleared">${I('table')}原型仅展示「订阅服务」集合的记录</div>`}
        </div>
      </section>
      <aside class="pane-inspector">${isSubs ? inspector() : ''}</aside>
    </div></div>`;
  }
  function inspector() {
    const r = D.records.find((x) => x.id === ui.recordId);
    if (!r) return `<div class="cleared">${I('table')}选择一条记录查看详情</div>`;
    if (r.sync === 'conflict') return conflictView(r);
    const tl = {
      synced: [['ok', '已同步到 Core', '今天 11:40'], ['', '在 Pixel 9 上修改', '今天 11:38']],
      pending: [['warn', online() ? '排队等待同步' : '等待联网后同步', '—'], ['', '已在本机保存', '昨天 22:10']],
      local: [['', '已在本机保存', '刚刚']],
    }[r.sync] || [];
    return `<div class="insp">
      <div style="display:flex;align-items:center;gap:8px"><h3>${r.name}</h3><span style="margin-left:auto">${syncBadge(r.sync)}</span></div>
      ${[['name', '名称', r.name], ['price', '价格（¥）', r.price], ['renew', '续费日', r.renew], ['pay', '支付方式', r.pay], ['status', '状态', r.status]].map(([k, l, v]) => `
        <div class="field"><label for="f-${k}">${l}</label><input class="input" id="f-${k}" data-field="${k}" value="${v}"></div>`).join('')}
      <div><div class="card-h" style="margin-bottom:10px">${I('history')} 同步记录</div>
        <div class="timeline">${tl.map(([d, t, w]) => `<div class="t"><span class="dot ${d}"></span><span>${t}</span><span class="when">${w}</span></div>`).join('')}</div></div>
      <dl class="meta-grid"><dt>UUID</dt><dd class="mono">7c1e…${r.id}a9</dd><dt>修订</dt><dd>rev 14</dd><dt>集合</dt><dd>订阅服务</dd></dl>
    </div>`;
  }
  function conflictView(r) {
    const C = D.conflict;
    const pick = ui.cfChoice;
    return `<div class="insp conflict">
      <div class="conflict-h">${I('alert')}<div><h3 style="font-size:15px">${r.name} · 需要处理冲突</h3><div class="faint" style="font-size:12.5px;margin-top:2px">离线期间两台设备都修改了「价格」。其它字段已自动合并。</div></div></div>
      <div class="cf-field">
        <div class="fname">价格（原值 ¥${C.base.price}）</div>
        <div class="cf-opts">
          <button class="cf-opt" data-act="cf" data-k="local" aria-pressed="${pick === 'local'}"><span class="v num">¥${C.local.price}</span><span class="src">${C.local.device}</span><span class="src">${C.local.at}</span></button>
          <button class="cf-opt" data-act="cf" data-k="remote" aria-pressed="${pick === 'remote'}"><span class="v num">¥${C.remote.price}</span><span class="src">${C.remote.device}</span><span class="src">${C.remote.at}</span></button>
        </div>
      </div>
      <div class="notice info">${I('checks')}<div><b>已自动合并</b> 支付方式 → ${C.remote.pay}（仅 ${C.remote.device} 修改过）</div></div>
      <div class="cf-same">续费日、周期、状态三端一致</div>
      <div class="btn-row"><button class="btn btn-primary" data-act="resolve">${I('check')}保留所选并同步</button><button class="btn btn-ghost" data-act="toast" data-msg="原型：查看两个版本的完整差异">查看完整差异</button></div>
      <div class="faint" style="font-size:11.5px">处理结果会先保存在本机，再按修订号提交到 Core；其它设备会收到同一结果。</div>
    </div>`;
  }
  function bindData() {
    $$('[data-field]', main).forEach((inp) => inp.addEventListener('change', () => {
      const r = D.records.find((x) => x.id === ui.recordId);
      r[inp.dataset.field] = inp.dataset.field === 'price' ? +inp.value || r.price : inp.value;
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 已在本机保存「${r.name}」`);
      advance(r);
    }));
  }

  /* ======================================================================
     页面：设备
     ====================================================================== */
  function pDevices() {
    return `<div class="page">
      <header class="ph"><div><h1>设备</h1><div class="sub">已授权的 Studiolo 客户端与遥测设备 · 每台设备独立绑定、可单独吊销</div></div>
        <div class="actions"><button class="btn btn-primary" data-act="toast" data-msg="原型：显示配对二维码">${I('plus')}添加设备</button></div></header>
      <div class="dev-grid">${D.devices.map((d) => `
        <section class="dev-card mat">
          <div class="top"><span class="tile-icon" style="width:40px;height:40px">${I(d.icon)}</span>
            <div class="grow" style="min-width:0"><div style="font-weight:650">${d.name}${d.me ? ' <span class="chip" style="height:20px">本机</span>' : ''}</div><div class="faint" style="font-size:12px">${d.os}</div></div>
            <span class="conn ${online() ? (d.state === 'online' ? 'online' : '') : (d.me ? 'online' : 'offline')}">${online() ? (d.state === 'online' ? '在线' : '空闲') : (d.me ? '本机' : '未知')}</span></div>
          <div class="faint" style="font-size:12.5px">${d.note}</div>
          <div class="btn-row"><button class="btn btn-sm btn-ghost">详情</button>${d.me ? '' : '<button class="btn btn-sm btn-danger">吊销</button>'}</div>
        </section>`).join('')}</div>
    </div>`;
  }

  /* ======================================================================
     页面：共享空间（每次读取都要密码）
     ====================================================================== */
  const TYPE = { key: ['key', 'Key'], text: ['note', '文本'], config: ['braces', '配置'], file: ['file', '文件'] };
  function pSpace() {
    if (!ui.vault.unlocked) {
      return `<div class="page full"><div class="vault-lock"><div class="vault-card mat">
        <div class="lk">${I('lock')}</div>
        <h2>${D.space.name}</h2>
        <p class="muted" style="margin:0;font-size:13px">每次查看内容都需要输入密码，离线时也一样。<br>Studiolo 和 Core 都不保存你的密码。</p>
        <form id="vault-form" novalidate>
          <div class="pw-field">${I('lock')}<input class="input" id="vault-pw" type="password" placeholder="共享空间密码" autocomplete="off" aria-label="共享空间密码" aria-describedby="vault-err"></div>
          <div class="pw-error" id="vault-err" role="alert">密码不正确</div>
          <div class="kdf-bar" id="vault-kdf"><i></i></div>
          <button class="btn btn-primary btn-lg" style="width:100%;margin-top:10px">${I('unlock')}查看目录</button>
        </form>
        <div class="demo-hint">演示密码：<code>${N.DEMO_PASSWORD}</code></div>
        <div class="vault-facts">
          <div><b>${D.space.meta.count}</b>加密对象</div><div><b>${D.space.meta.size}</b>总大小</div><div><b>${D.space.meta.local} / ${D.space.meta.count}</b>本机副本</div><div><b>epoch 3</b>密钥世代</div>
        </div>
      </div></div></div>`;
    }
    const v = ui.vault;
    return `<div class="page full" style="display:grid;grid-template-rows:auto 1fr;height:100%">
      <div class="read-banner">${I('unlock')}<span>正在显示<b>本次读取</b>的目录 · 离开此页、切到后台或锁屏后立即清除</span><span class="spacer"></span>
        <button class="btn btn-sm btn-ghost" data-act="vault-lock">${I('lock')}立即锁定</button></div>
      <div class="split" style="grid-template-columns:minmax(0,1fr) 380px">
        <section style="display:flex;flex-direction:column;overflow:hidden">
          <div class="toolbar"><h2 style="margin:0;font-size:16px">${D.space.name}</h2><span class="faint">${D.space.items.length} 个对象</span><span class="spacer"></span>
            ${['文本', 'Key', '配置', '文件'].map((t) => `<button class="btn btn-ghost btn-sm" data-act="toast" data-msg="原型：新建${t}，保存后先在本机加密">${I('plus')}${t}</button>`).join('')}</div>
          <div style="overflow:auto;flex:1"><table class="tbl reveal"><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>更新</th><th>来自</th><th>本机副本</th></tr></thead>
            <tbody>${D.space.items.map((s) => `<tr data-act="vault-open" data-id="${s.id}" class="${v.sel === s.id ? 'is-selected' : ''}">
              <td><span style="display:inline-flex;align-items:center;gap:10px;font-weight:550"><span class="tile-icon" style="width:28px;height:28px">${I(TYPE[s.type][0])}</span>${s.name}</span></td>
              <td class="muted">${TYPE[s.type][1]}</td><td class="muted num">${s.size}</td><td class="muted">${s.updated}</td><td class="faint">${s.by}</td>
              <td>${s.local === 'downloaded' ? `<span class="sync is-local"><span class="glyph">${I('check')}</span>已在本机</span>` : s.local === 'pending' ? syncBadge('pending') : `<span class="sync is-offline"><span class="glyph"></span>仅云端</span>`}</td></tr>`).join('')}</tbody></table></div>
        </section>
        <aside class="pane-inspector" id="vault-detail">${vaultDetail()}</aside>
      </div>
    </div>`;
  }
  function vaultDetail() {
    const v = ui.vault;
    const s = D.space.items.find((x) => x.id === v.sel);
    if (!s) return `<div class="cleared">${I('lock')}<div>选择一个对象<br>每次查看内容都会再次要求输入密码</div></div>`;
    const head = `<div style="display:flex;align-items:center;gap:10px"><span class="tile-icon">${I(TYPE[s.type][0])}</span><div><h3>${s.name}</h3><div class="faint" style="font-size:12px">${TYPE[s.type][1]} · ${s.size} · 修订 ${s.rev}</div></div></div>`;
    if (!online() && s.local === 'remote') {
      return `<div class="insp">${head}<div class="notice warn">${I('wifiOff')}<div><b>离线不可读</b><br>这个对象还没有下载到本机。联网后可下载密文，再输入密码读取。</div></div></div>`;
    }
    if (v.revealed !== s.id) {
      return `<div class="insp">${head}<div class="cleared" style="padding:30px 10px">${I('lock')}<div>内容已锁定</div><button class="btn btn-primary" data-act="vault-read" data-id="${s.id}">${I('unlock')}输入密码查看</button></div></div>`;
    }
    const c = s.content;
    const body = c.kind === 'file'
      ? `<div class="file-prev">${I('file')}<div>${c.value}</div><button class="btn btn-sm btn-ghost" data-act="vault-copy" data-id="${s.id}" data-what="导出">${I('arrowDown')}导出（需再次输入密码）</button></div>`
      : `<div class="secret-box">${c.value.replace(/</g, '&lt;')}</div>`;
    return `<div class="insp reveal">${head}
      <div class="scope-tag">${I('unlock')}<span>本次读取 · <b>${s.rev}</b> · 来自 ${s.by}</span></div>
      ${body}
      ${c.note ? `<div class="faint" style="font-size:12.5px">${c.note}</div>` : ''}
      <div class="btn-row">
        ${c.kind !== 'file' ? `<button class="btn btn-ghost" data-act="vault-copy" data-id="${s.id}" data-what="复制">${I('copy')}复制</button>` : ''}
        <button class="btn btn-ghost" data-act="vault-hide">${I('eye')}隐藏</button>
        <button class="btn btn-subtle" data-act="toast" data-msg="原型：编辑后在本机重新加密并生成新修订">${I('pencil')}编辑</button>
      </div>
      <div class="faint" style="font-size:11.5px">再次查看、复制或导出时都需要重新输入密码。</div>
    </div>`;
  }
  function bindSpace() {
    const form = $('#vault-form');
    if (!form) return;
    $('#vault-pw').focus();
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const pw = $('#vault-pw'), err = $('#vault-err'), kdf = $('#vault-kdf');
      err.classList.remove('show'); kdf.classList.add('on');
      const ok = await N.verifyPassword(pw.value);
      kdf.classList.remove('on');
      if (!ok) { err.classList.add('show'); pw.classList.remove('shake'); void pw.offsetWidth; pw.classList.add('shake'); pw.select(); return; }
      pw.value = '';
      N.transition(() => { ui.vault.unlocked = true; ui.vault.sel = null; ui.vault.revealed = null; renderPage(); renderSidebar(); });
    });
  }
  function lockVault(leaving) {
    ui.vault = { unlocked: false, sel: null, revealed: null };
    renderSidebar();
    N.toast(toastHost, `${I('lock')} 共享空间已锁定，屏幕上的内容已清除`);
    if (!leaving) N.transition(() => renderPage());
  }

  /** 每次读取：弹出密码对话框，绑定到具体对象、操作与修订 */
  function askPassword({ action, item }) {
    const dlg = $('#pw-dlg');
    const input = $('#pw-input');
    const err = $('#pw-err');
    $('#pw-scope').innerHTML = `${I('key')}<span>${action} · <b>${item.name}</b> · 修订 ${item.rev}</span>`;
    $('#pw-foot').innerHTML = `${I('shield')}${item.local === 'remote' ? `将先下载 ${item.size} 密文到本机，` : ''}密码只用于这一次读取，不会被记住`;
    $('#pw-ok').textContent = action === '复制' ? '验证并复制' : action === '导出' ? '验证并导出' : '验证并读取';
    input.value = ''; err.classList.remove('show');
    return new Promise((resolve) => {
      let done = false;
      const form = $('#pw-form');
      const onSubmit = async (e) => {
        if (e.submitter?.value !== 'ok') return;
        e.preventDefault();
        $('#pw-kdf').classList.add('on');
        const ok = await N.verifyPassword(input.value);
        $('#pw-kdf').classList.remove('on');
        if (!ok) { err.classList.add('show'); input.classList.remove('shake'); void input.offsetWidth; input.classList.add('shake'); input.select(); return; }
        done = true; input.value = ''; dlg.close('ok');
      };
      const onClose = () => { form.removeEventListener('submit', onSubmit); dlg.removeEventListener('close', onClose); dlg.returnValue = ''; resolve(done); };
      form.addEventListener('submit', onSubmit);
      dlg.addEventListener('close', onClose);
      dlg.showModal();
    });
  }
  async function vaultRead(id) {
    const s = D.space.items.find((x) => x.id === id);
    ui.vault.sel = id; ui.vault.revealed = null;
    refreshVaultTable();
    if (!online() && s.local === 'remote') return;
    const ok = await askPassword({ action: '读取', item: s });
    if (!ok || ui.vault.sel !== id) return;
    if (s.local === 'remote') s.local = 'downloaded';
    ui.vault.revealed = id;
    refreshVaultTable();
  }
  function refreshVaultTable() {
    $$('tr[data-act="vault-open"]', main).forEach((tr) => tr.classList.toggle('is-selected', tr.dataset.id === ui.vault.sel));
    $('#vault-detail').innerHTML = vaultDetail();
  }

  /* ======================================================================
     Agent Chat：同一组件用于 Agent 页面与停靠侧板
     ====================================================================== */
  class Chat {
    constructor({ compact = false } = {}) {
      this.compact = compact;
      this.agent = 'openclaw';
      this.session = 'c1';
      this.msgs = structuredClone(D.chat.c1);
      this.stream = null; this.streamMsg = null; this.retry = null; this.loading = false;
    }
    get A() { return D.agents[this.agent]; }
    mount(root) { this.root = root; this.render(); }
    openSession(agent, id) {
      this.stream?.finish();
      this.agent = agent; this.session = id; this.msgs = [];
      this.loading = true; this.render();
      // 模拟：从上游 Agent 读取历史
      setTimeout(() => { this.loading = false; this.msgs = structuredClone(D.chat[id] || []); this.render(); }, 600);
    }
    newSession() {
      this.stream?.finish();
      this.session = null; this.msgs = []; this.render();
      this.root.querySelector('textarea')?.focus();
    }
    msgHTML(m) {
      if (m.role === 'user') return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
      return `<div class="msg agent oc-${this.agent}"><span class="am">${I(N.OWNERS[this.agent].icon)}</span><div class="bubble">${m.tool ? `<div class="tool">${I('data')}${m.tool}</div><br>` : ''}<span class="txt">${esc(m.text)}</span></div></div>`;
    }
    render() {
      if (!this.root) return;
      const A = this.A, on = online();
      const title = this.session ? (A.sessions.find((s) => s.id === this.session)?.title || '新会话') : '新会话';
      let body;
      if (this.loading) body = `<div class="msg agent oc-${this.agent}"><span class="am">${I(N.OWNERS[this.agent].icon)}</span><div class="bubble faint">正在从 ${A.name} 读取会话历史… <span class="typing"><i></i><i></i><i></i></span></div></div>`;
      else if (!this.msgs.length && !on) body = `<div class="cleared">${I('wifiOff')}<div>离线：无法从 ${A.name} 读取历史<br>Studiolo 不在本机保存聊天内容</div></div>`;
      else if (!this.msgs.length) body = `<div class="cleared">${I(N.OWNERS[this.agent].icon)}<div>和 ${A.name} 开始新对话<br><span style="font-size:12px">实例 ${A.instance} · ${A.profile}</span></div></div>`;
      else body = this.msgs.map((m) => this.msgHTML(m)).join('');
      this.root.innerHTML = `<div class="chat">
        <div class="chat-h">
          <div><h2>${esc(title)}</h2><div class="faint" style="font-size:12px">${ownerBadge(this.agent, `${A.instance} · ${A.profile}`)}</div></div>
          <span class="spacer"></span>
          <button class="btn btn-ghost btn-sm" data-chat="drop" title="演示断线与恢复">${I('wifiOff')}模拟断线 4 秒</button>
        </div>
        <div class="conn-banner" data-banner></div>
        <div class="msgs" data-scroll><div class="msgs-inner" data-list>${body}</div></div>
        <div class="composer">
          <div class="composer-box ${on ? '' : 'disabled'}">
            <textarea data-input rows="1" placeholder="${on ? `发消息给 ${A.name}…` : '离线时无法发送'}" ${on ? '' : 'disabled'}></textarea>
            <div class="composer-row"><span>${this.compact ? '' : 'Enter 发送 · Shift + Enter 换行'}</span><span class="spacer"></span>
              <span class="chip" title="附件能力待定（TBD-07）">${I('file')}附件 · 待定</span>
              <button class="send ${this.stream ? 'stop' : ''}" data-send aria-label="${this.stream ? '停止生成' : '发送'}" ${on ? '' : 'disabled'}>${I(this.stream ? 'stop' : 'arrowUp')}</button></div>
          </div>
          <div class="privacy">${I('shield')}历史保存在 ${A.name} · Studiolo 不保存聊天正文</div>
        </div>
      </div>`;
      const ta = this.root.querySelector('[data-input]');
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(ta.value); }
      });
      ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(160, ta.scrollHeight) + 'px'; });
      this.root.querySelector('[data-send]').addEventListener('click', () => this.stream ? this.cancel() : this.send(ta.value));
      this.root.querySelector('[data-chat="drop"]').addEventListener('click', () => {
        N.set({ online: false });
        setTimeout(() => N.set({ online: true }), 4000);
      });
      this.scroll();
      if (!on && this.stream) this.showBanner('warn');
    }
    scroll() { const s = this.root?.querySelector('[data-scroll]'); if (s) s.scrollTop = s.scrollHeight; }
    send(text) {
      text = (text || '').trim();
      if (!text || !online() || this.stream) return;
      const list = this.root.querySelector('[data-list]');
      if (!this.msgs.length) list.innerHTML = '';
      this.msgs.push({ role: 'user', text });
      list.insertAdjacentHTML('beforeend', this.msgHTML({ role: 'user', text }) + `<div class="msg agent oc-${this.agent}" data-pending><span class="am">${I(N.OWNERS[this.agent].icon)}</span><div class="bubble"><span class="typing"><i></i><i></i><i></i></span><div class="state">${I('check')}已送达 ${this.A.name}</div></div></div>`);
      const ta = this.root.querySelector('[data-input]'); ta.value = ''; ta.style.height = 'auto';
      this.scroll();
      setTimeout(() => {
        const pend = list.querySelector('[data-pending]');
        if (!pend) return;
        pend.removeAttribute('data-pending');
        pend.querySelector('.bubble').innerHTML = `<span class="txt"></span><div class="state" data-state hidden></div>`;
        const reply = D.replies[this.agent];
        const m = { role: 'agent', text: reply };
        this.streamMsg = pend;
        this.stream = N.streamer(pend.querySelector('.txt'), reply, {
          onDone: () => { this.msgs.push(m); this.stream = null; this.streamMsg = null; this.updateSend(); },
        });
        this.updateSend();
        if (!online()) this.onOnline(false);
      }, 700);
    }
    cancel() {
      if (!this.stream) return;
      this.stream.pause();
      const st = this.streamMsg?.querySelector('[data-state]');
      if (st) { st.hidden = false; st.innerHTML = `${I('stop')}已停止生成（已通知 ${this.A.name} 取消）`; }
      this.stream = null; this.streamMsg = null; this.updateSend();
    }
    updateSend() {
      const b = this.root?.querySelector('[data-send]');
      if (!b) return;
      b.classList.toggle('stop', !!this.stream);
      b.innerHTML = I(this.stream ? 'stop' : 'arrowUp');
      b.setAttribute('aria-label', this.stream ? '停止生成' : '发送');
    }
    showBanner(kind, text) {
      const b = this.root?.querySelector('[data-banner]');
      if (!b) return;
      b.className = `conn-banner show ${kind}`;
      b.innerHTML = text || '';
    }
    onOnline(on) {
      if (!this.root) return;
      const A = this.A;
      const box = this.root.querySelector('.composer-box');
      const ta = this.root.querySelector('[data-input]');
      const send = this.root.querySelector('[data-send]');
      box?.classList.toggle('disabled', !on);
      if (ta) { ta.disabled = !on; ta.placeholder = on ? `发消息给 ${A.name}…` : '离线时无法发送'; }
      if (send && !this.stream) send.disabled = !on;
      clearInterval(this.retry);
      if (!on) {
        let n = 1, wait = 2;
        const paint = () => this.showBanner('warn', `${I('wifiOff')}<span>与 ${A.name}（${A.instance}）的连接已中断 · 第 ${n} 次重连，${wait} 秒后重试</span>`);
        paint();
        this.retry = setInterval(() => { wait--; if (wait <= 0) { n++; wait = Math.min(8, 2 ** n); } paint(); }, 1000);
        if (this.stream) {
          this.stream.pause();
          const st = this.streamMsg?.querySelector('[data-state]');
          if (st) { st.hidden = false; st.className = 'state warn'; st.innerHTML = `${I('alert')}回复中断 · 重连后从 ${A.name} 补齐，不会重复发送`; }
        }
      } else {
        const how = A.caps.replay === true ? `已按游标从 ${A.name} 补齐缺失内容` : `已从 ${A.name} 重新读取会话`;
        this.showBanner('ok', `${I('check')}<span>已重新连接 · ${how}</span>`);
        setTimeout(() => this.root?.querySelector('[data-banner]')?.classList.remove('show'), 2600);
        if (this.stream) {
          const st = this.streamMsg?.querySelector('[data-state]');
          if (st) { st.className = 'state'; st.innerHTML = `${I('checks')}已补齐`; }
          this.stream.resume();
        }
      }
    }
  }
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

  const pageChat = new Chat();
  const dockChat = new Chat({ compact: true });
  dockChat.agent = 'hermes'; dockChat.session = null; dockChat.msgs = [];

  function mountAgentPage() {
    const on = online();
    const A = D.agents[pageChat.agent];
    const capRow = (label, v) => {
      const cls = v === true ? 'cap-yes' : v === false ? 'cap-no' : v === '待定' ? 'cap-tbd' : 'cap-yes';
      const txt = v === true ? '支持' : v === false ? '不支持' : v;
      return `<div><span class="${cls}">${I(v === false ? 'x' : v === '待定' ? 'info' : 'check')}</span>${label}<span>${txt}</span></div>`;
    };
    main.innerHTML = `<div class="page full"><div class="split" style="grid-template-columns:270px minmax(0,1fr) 280px">
      <aside class="pane-side">
        <div class="pane-h"><h2>Agent</h2><span class="spacer"></span><button class="icon-btn" title="新会话" data-act="chat-new">${I('plus')}</button></div>
        <div class="agent-switch">${['openclaw', 'hermes'].map((id) => { const a = D.agents[id]; return `
          <button class="agent-card oc-${id}" data-act="agent" data-id="${id}" aria-pressed="${pageChat.agent === id}">
            <span class="am">${I(N.OWNERS[id].icon)}</span><span class="grow"><div class="nm">${a.name}</div><div class="in">${a.instance} · ${a.profile}</div></span>
            <span class="conn ${on ? 'online' : 'offline'}"></span></button>`; }).join('')}</div>
        <div class="nav-sec" style="margin:8px 16px 4px">会话</div>
        ${on ? `<div class="list" style="padding:0 8px">${A.sessions.map((s) => `
          <button class="row ${pageChat.session === s.id ? 'is-selected' : ''}" data-act="session" data-id="${s.id}"><span class="grow"><div class="title">${s.title}</div><div class="sub">${s.last}</div></span></button>`).join('')}</div>`
        : `<div class="notice" style="margin:0 12px">${I('wifiOff')}<div>离线：无法读取会话列表</div></div>`}
        <div class="src-note">${I('info')}会话列表由 ${A.name} 提供</div>
      </aside>
      <section id="chat-root" style="min-width:0;overflow:hidden"></section>
      <aside class="pane-inspector" style="padding:16px;display:grid;gap:18px;align-content:start">
        <div><div class="card-h">${I('server')} 连接</div>
          <dl class="meta-grid"><dt>实例</dt><dd>${A.instance}</dd><dt>Profile</dt><dd>${A.profile}</dd><dt>地址</dt><dd class="mono" style="font-size:11px;word-break:break-all">${A.endpoint}</dd><dt>状态</dt><dd><span class="conn ${on ? 'online' : 'reconnecting'}">${on ? '已认证 · 在线' : '重连中'}</span></dd></dl></div>
        <div><div class="card-h">${I('layers')} 能力</div>
          <div class="caps">${capRow('历史', A.caps.history)}${capRow('流式回复', A.caps.stream)}${capRow('取消生成', A.caps.cancel)}${capRow('断线恢复', A.caps.replay)}${capRow('发送幂等', A.caps.idem)}${capRow('附件', A.caps.attach)}${capRow('Cron 管理', A.caps.cron)}</div></div>
        <div class="notice">${I('shield')}<div>聊天内容只在内存中显示。离开会话或退出 Studiolo 后释放，下次从 ${A.name} 重新读取。</div></div>
      </aside>
    </div></div>`;
    pageChat.mount($('#chat-root'));
  }

  /* 停靠侧板 */
  function renderDock() {
    $('#dock').innerHTML = `<div class="dock-inner">
      <div class="dock-h">
        <div class="seg" role="group" aria-label="选择 Agent">${['openclaw', 'hermes'].map((id) => `<button data-act="dock-agent" data-id="${id}" aria-pressed="${dockChat.agent === id}">${N.OWNERS[id].label}</button>`).join('')}</div>
        <span class="spacer" style="flex:1"></span>
        <button class="icon-btn" title="在 Agent 页打开" data-go="agent">${I('external')}</button>
        <button class="icon-btn" title="关闭" data-act="dock-close">${I('x')}</button>
      </div>
      <div id="dock-chat" style="min-height:0"></div>
    </div>`;
    dockChat.mount($('#dock-chat'));
    N.syncSeg($('#dock'));
  }
  function openDock() {
    if (win.classList.contains('dock-open')) return;
    win.classList.add('dock-open');
    $('#btn-dock').setAttribute('aria-pressed', 'true');
    renderDock();
  }
  function toggleDock() {
    if (win.classList.contains('dock-open')) {
      win.classList.remove('dock-open');
      $('#btn-dock').setAttribute('aria-pressed', 'false');
    } else openDock();
  }

  /* ======================================================================
     页面：任务（统一管理 Studiolo 自动化与 Agent Cron）
     ====================================================================== */
  const RUN = { ok: '成功', fail: '失败', running: '运行中', paused: '已暂停', unknown: '结果未知' };
  function pTasks() {
    const jobs = D.jobs.filter((j) => (ui.jobOwner === 'all' || j.owner === ui.jobOwner) && (!ui.jobStatus || j.last === ui.jobStatus));
    const cnt = (s) => D.jobs.filter((j) => j.last === s).length;
    const oc = (o) => D.jobs.filter((j) => o === 'all' || j.owner === o).length;
    return `<div class="page">
      <header class="ph"><div><h1>任务</h1><div class="sub">Studiolo 自动化与 Agent Cron 在这里统一管理 · 每个任务只由一个所有者调度</div></div>
        <div class="actions"><button class="btn btn-primary" data-act="new-job">${I('plus')}新建任务</button></div></header>
      <div class="stat-strip">
        ${[['running', '运行中', 'var(--accent)'], ['fail', '失败', 'var(--danger)'], ['unknown', '结果未知', 'var(--warn)'], ['paused', '已暂停', 'var(--text-3)']].map(([k, l, c]) => `
          <button class="stat mat" data-act="jstatus" data-k="${k}" aria-pressed="${ui.jobStatus === k}"><span class="n num" style="color:${c}">${cnt(k)}</span><span class="l">${l}</span></button>`).join('')}
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
        <div class="seg" role="group" aria-label="按所有者筛选">${[['all', '全部'], ['studiolo', 'Studiolo'], ['openclaw', 'OpenClaw'], ['hermes', 'Hermes']].map(([k, l]) => `<button data-act="jowner" data-k="${k}" aria-pressed="${ui.jobOwner === k}">${l} <span class="faint">${oc(k)}</span></button>`).join('')}</div>
        ${!online() ? `<span class="chip" style="color:var(--danger)">${I('wifiOff')}离线 · 显示最近一次读取的状态</span>` : ''}
      </div>
      <div class="tasks-wrap">
        <div class="tasks-table mat-solid"><table class="tbl">
          <thead><tr><th>任务</th><th>调度所有者</th><th>计划</th><th>下次运行</th><th>最近结果</th></tr></thead>
          <tbody>${jobs.map((j) => `<tr data-act="job" data-id="${j.id}" class="${ui.jobId === j.id ? 'is-selected' : ''}">
            <td><div class="task-name"><b>${j.name}</b><span>${j.trigger}</span></div></td>
            <td>${ownerBadge(j.owner, j.owner === 'studiolo' ? '' : j.where)}</td>
            <td><div class="task-name"><span style="color:var(--text);font-size:13px">${j.schedule}</span><span>${j.tz}</span></div></td>
            <td class="muted">${j.next}</td>
            <td><div class="task-name"><span class="run ${j.last}">${RUN[j.last]}</span><span>${j.lastAt}</span></div></td></tr>`).join('') || `<tr><td colspan="5" class="faint" style="text-align:center;height:80px">没有符合条件的任务</td></tr>`}</tbody>
        </table></div>
        <aside class="task-detail mat-solid" id="job-detail">${jobDetail()}</aside>
      </div>
    </div>`;
  }
  function jobDetail() {
    const j = D.jobs.find((x) => x.id === ui.jobId);
    if (!j) return `<div class="cleared">${I('tasks')}选择一个任务</div>`;
    const on = online();
    const O = N.OWNERS[j.owner];
    const runs = D.runs[j.id] || [{ s: j.last, at: j.lastAt.split(' · ')[0], dur: '—', note: '' }];
    const ownerText = j.owner === 'studiolo'
      ? '由 Studiolo Core 的自动化引擎执行，运行记录保存在 Core。'
      : `由 ${O.label} 自己的 Cron 执行。Studiolo 只做查看和管理：即使 Studiolo 关闭或断开，任务也会按 ${O.label} 的规则继续运行。`;
    const offMsg = j.owner === 'studiolo' ? 'Core 不可达' : `无法连接 ${j.where}`;
    const dis = (cap) => (!on ? `disabled title="${offMsg}"` : !cap ? 'disabled title="该所有者不支持此操作"' : '');
    const dot = { ok: 'ok', fail: 'danger', running: 'accent', paused: '', unknown: 'unknown' };
    return `<div style="display:flex;align-items:flex-start;gap:10px"><div class="grow"><h3 style="margin:0;font-size:17px">${j.name}</h3><div class="faint" style="font-size:12px;margin-top:2px">${j.trigger} · <span class="run ${j.last}">${RUN[j.last]}</span></div></div>
        <button class="switch" role="switch" aria-checked="${j.enabled}" aria-label="启用" data-act="job-toggle" ${dis(j.caps.pause)}></button></div>
      <div class="owner-card oc-${j.owner}">
        <div class="ttl">${ownerBadge(j.owner)}<span class="faint" style="font-weight:500;font-size:12px">${j.owner === 'studiolo' ? '' : `实例 ${j.where.split(' / ')[0]}${j.where.includes('/') ? ' · profile ' + j.where.split(' / ')[1] : ''}`}</span></div>
        <p>${ownerText}</p>
      </div>
      ${j.limited ? `<div class="notice warn">${I('info')}<div>${j.limited}</div></div>` : ''}
      ${!on ? `<div class="notice danger">${I('wifiOff')}<div><b>${offMsg}</b>，写操作已禁用。显示的是最近一次读取的状态。</div></div>` : ''}
      <dl class="sched"><dt>计划</dt><dd>${j.schedule}</dd><dt>原生表达</dt><dd class="mono">${j.expr}</dd><dt>所有者时区</dt><dd>${j.tz}</dd><dt>下次运行</dt><dd>${j.next}</dd></dl>
      <div class="btn-row">
        ${j.last === 'unknown'
          ? `<button class="btn btn-primary" data-act="job-verify" ${dis(true)}>${I('search')}向 ${O.label} 核对结果</button>`
          : `<button class="btn btn-primary" data-act="job-run" ${dis(j.caps.run)} ${j.last === 'running' ? 'disabled' : ''}>${I('play')}立即运行</button>`}
        <button class="btn btn-ghost" data-act="toast" data-msg="原型：编辑表单按所有者的原生字段展示" ${dis(j.caps.edit)}>${I('pencil')}编辑</button>
        ${j.owner !== 'studiolo' ? `<button class="btn btn-subtle" data-act="toast" data-msg="在 ${O.label} 中打开">${I('external')}在 ${O.label} 中查看</button>` : ''}
      </div>
      <div><div class="card-h" style="margin-bottom:6px">${I('history')} 运行历史<span class="spacer"></span><span class="chip">来源：${j.owner === 'studiolo' ? 'Studiolo Core' : O.label} · ${j.caps.history}</span></div>
        <div class="timeline" style="margin-top:10px">${runs.map((r) => `<div class="t"><span class="dot ${dot[r.s]}"></span><span><span class="run ${r.s}" style="font-weight:600">${RUN[r.s]}</span> <span class="faint">· ${r.dur}</span><div class="faint" style="font-size:12px">${r.note}</div></span><span class="when">${r.at}</span></div>`).join('')}</div></div>`;
  }
  function refreshJobs() {
    const st = main.scrollTop;
    main.innerHTML = pTasks();
    N.syncSeg(main);
    main.scrollTop = st;
    renderSidebar();
  }

  /* ======================================================================
     页面：集成与 API、设置
     ====================================================================== */
  function pApi() {
    const keys = [
      ['Home Assistant', 'nc_live_7Hq…', '读：Data、设备', '3 分钟前'],
      ['NAS 遥测', 'nd_live_m2K…', '设备遥测', '刚刚'],
      ['OpenClaw 数据动作', 'na_live_Zp0…', 'Ledger / Website / Record 白名单', '昨天'],
      ['只读脚本', 'nx_ro_q91…', '只读', '上周'],
    ];
    return `<div class="page">
      <header class="ph"><div><h1>集成与 API</h1><div class="sub">令牌按身份隔离，可单独轮换和吊销</div></div><div class="actions"><button class="btn btn-primary">${I('plus')}新建令牌</button></div></header>
      <div class="notice info" style="margin-bottom:14px">${I('shield')}<div><b>任何令牌都无法读取共享空间的明文。</b>读取内容必须由人当次输入密码，包括 CLI 与 SDK。</div></div>
      <div class="mat-solid" style="border-radius:var(--r-lg);overflow:hidden"><table class="tbl"><thead><tr><th>名称</th><th>令牌</th><th>权限范围</th><th>最近使用</th><th></th></tr></thead>
        <tbody>${keys.map((k) => `<tr><td style="font-weight:550">${k[0]}</td><td class="mono muted">${k[1]}</td><td class="muted">${k[2]}</td><td class="faint">${k[3]}</td><td class="r"><button class="btn btn-sm btn-subtle">轮换</button><button class="btn btn-sm btn-danger">吊销</button></td></tr>`).join('')}</tbody></table></div>
    </div>`;
  }
  function pSettings() {
    const s = N.get();
    const secs = [['appearance', '外观'], ['sync', '同步'], ['account', '账户与设备'], ['privacy', '隐私与安全'], ['about', '关于']];
    return `<div class="page"><header class="ph"><div><h1>设置</h1></div></header>
      <div class="settings">
        <nav class="set-nav">${secs.map(([k, l]) => `<button class="nav-item" ${ui.settingsSec === k ? 'aria-current="page"' : ''} data-act="set-sec" data-k="${k}">${l}</button>`).join('')}</nav>
        <div>
          <section class="set-sec"><h2>主题</h2>
            <div class="theme-cards">
              <button class="theme-card" data-act="set-theme" data-v="paper" aria-pressed="${s.theme === 'paper'}"><div class="pv paper"><i style="left:8px;top:8px;bottom:8px;width:40px"></i><i style="left:56px;top:8px;right:8px;height:40px"></i><i style="left:56px;top:56px;right:8px;bottom:8px"></i></div><div class="nm">纸墨（默认）</div><div class="ds">实体表面，信息密度高，适合长时间使用</div></button>
              <button class="theme-card" data-act="set-theme" data-v="glass" aria-pressed="${s.theme === 'glass'}"><div class="pv glass"><i style="left:8px;top:8px;bottom:8px;width:40px"></i><i style="left:56px;top:8px;right:8px;height:40px"></i><i style="left:56px;top:56px;right:8px;bottom:8px"></i></div><div class="nm">Liquid Glass</div><div class="ds">导航、卡片与浮层使用玻璃材质，列表与输入保持实体</div></button>
            </div>
          </section>
          <section class="set-sec"><h2>显示</h2>
            <div class="mat-solid" style="border-radius:var(--r-lg)">
              <div class="set-row"><div class="grow"><div class="t">外观模式</div><div class="d">跟随系统或手动选择</div></div><div class="seg">${[['light', '浅色'], ['dark', '深色']].map(([v, l]) => `<button data-act="set-mode" data-v="${v}" aria-pressed="${s.mode === v}">${l}</button>`).join('')}</div></div>
              <div class="set-row"><div class="grow"><div class="t">减少透明度</div><div class="d">关闭模糊，玻璃材质改为不透明表面；低性能设备会自动开启</div></div><button class="switch" role="switch" aria-checked="${s.blur === 'off'}" data-act="set-blur"></button></div>
              <div class="set-row"><div class="grow"><div class="t">减少动态效果</div><div class="d">去掉位移与缩放，只保留淡入淡出与颜色变化</div></div><button class="switch" role="switch" aria-checked="${s.motion === 'reduced'}" data-act="set-motion"></button></div>
            </div>
          </section>
          <section class="set-sec"><h2>同步</h2>
            <div class="mat-solid" style="border-radius:var(--r-lg)">
              <div class="set-row"><div class="grow"><div class="t">Core 服务器</div><div class="d">${D.core.host} · HTTPS 证书已验证</div></div><span class="conn ${online() ? 'online' : 'offline'}">${online() ? '已连接' : '不可达'}</span></div>
              <div class="set-row"><div class="grow"><div class="t">后台自动同步</div><div class="d">本机更改会先保存，再在后台推送</div></div><button class="switch" role="switch" aria-checked="true"></button></div>
              <div class="set-row"><div class="grow"><div class="t">冲突中心</div><div class="d">${counts().conflict} 个冲突待处理</div></div><button class="btn btn-ghost btn-sm" data-act="goto-conflict" data-id="r4">查看</button></div>
            </div>
          </section>
        </div>
      </div></div>`;
  }

  const PAGES = { today: pToday, ledger: pLedger, websites: pWebsites, data: pData, devices: pDevices, space: pSpace, tasks: pTasks, api: pApi, settings: pSettings };
  const BIND = { today: bindToday, data: bindData, space: bindSpace };

  /* ---------- 命令面板 ---------- */
  const CMDS = [
    ...ALL.map((x) => ({ g: '跳转', label: x.label, icon: x.icon, run: () => go(x.id), kw: x.id })),
    { g: '操作', label: '记一笔', icon: 'ledger', hint: '在「今天」快速输入', run: () => { go('today'); setTimeout(() => $('#cap')?.focus(), 380); } },
    { g: '操作', label: '收藏网站', icon: 'globe', run: () => { go('today'); setTimeout(() => $('#cap')?.focus(), 380); } },
    { g: '操作', label: '打开 Agent 侧板', icon: 'sidebar', hint: 'Ctrl/⌘ J', run: () => openDock() },
    { g: '操作', label: '新 Agent 会话', icon: 'chat', run: () => { go('agent'); setTimeout(() => pageChat.newSession(), 380); } },
    { g: '操作', label: '立即同步', icon: 'sync', run: () => flushAll() },
    { g: '操作', label: '处理同步冲突', icon: 'alert', run: () => gotoConflict('r4') },
    { g: '操作', label: '锁定共享空间', icon: 'lock', run: () => ui.vault.unlocked && lockVault(ui.page !== 'space') },
    { g: '外观', label: '切换深色 / 浅色', icon: 'moon', run: () => N.set({ mode: N.get().mode === 'dark' ? 'light' : 'dark' }) },
    { g: '外观', label: '切换 Liquid Glass', icon: 'layers', run: () => N.set({ theme: N.get().theme === 'glass' ? 'paper' : 'glass' }) },
    { g: '记录', label: 'Spotify 家庭', icon: 'data', hint: '订阅服务', run: () => gotoConflict('r4') },
    { g: '记录', label: 'Notion 年费', icon: 'receipt', hint: '账本', run: () => go('ledger') },
  ];
  let palSel = 0, palItems = [];
  function renderPalette() {
    const q = $('#pal-q').value.trim().toLowerCase();
    palItems = CMDS.filter((c) => !q || c.label.toLowerCase().includes(q) || c.kw?.includes(q) || c.g.includes(q));
    palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
    let last = '';
    $('#pal-list').innerHTML = palItems.map((c, i) => {
      const g = c.g !== last ? `<div class="pal-group">${c.g}</div>` : '';
      last = c.g;
      return `${g}<button class="pal-item" role="option" data-i="${i}" aria-selected="${i === palSel}">${I(c.icon)}${c.label}${c.hint ? `<span class="hint">${c.hint}</span>` : ''}</button>`;
    }).join('') || `<div class="cleared" style="padding:30px">没有匹配的命令</div>`;
  }
  function openPalette() {
    const p = $('#palette');
    $('#pal-q').value = ''; palSel = 0; renderPalette();
    p.showModal();
  }
  function runPal(i) { const c = palItems[i]; if (!c) return; $('#palette').close(); c.run(); }
  $('#pal-q').addEventListener('input', () => { palSel = 0; renderPalette(); });
  $('#pal-q').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); palSel = (palSel + 1) % palItems.length; renderPalette(); $(`.pal-item[data-i="${palSel}"]`)?.scrollIntoView({ block: 'nearest' }); }
    if (e.key === 'ArrowUp') { e.preventDefault(); palSel = (palSel - 1 + palItems.length) % palItems.length; renderPalette(); $(`.pal-item[data-i="${palSel}"]`)?.scrollIntoView({ block: 'nearest' }); }
    if (e.key === 'Enter') { e.preventDefault(); runPal(palSel); }
  });
  $('#pal-list').addEventListener('click', (e) => { const b = e.target.closest('.pal-item'); if (b) runPal(+b.dataset.i); });

  /* ---------- 动作 ---------- */
  function gotoConflict(id) {
    ui.dataCol = 'subs'; ui.recordId = id; ui.recordFilter = 'all';
    $('#sync-panel').hidden = true;
    if (ui.page === 'data') { N.transition(() => renderPage()); } else go('data');
  }
  const ACT = {
    toast: (b) => N.toast(toastHost, b.dataset.msg),
    'focus-capture': () => { go('today'); setTimeout(() => $('#cap')?.focus(), 380); },
    'open-job': (b) => { ui.jobId = b.dataset.id; go('tasks'); },
    'open-session': (b) => { go('agent'); pageChat.openSession(b.dataset.agent, b.dataset.id); },
    'goto-conflict': (b) => gotoConflict(b.dataset.id),
    flush: () => flushAll(),
    col: (b) => { ui.dataCol = b.dataset.id; N.transition(() => renderPage()); },
    rfilter: (b) => { ui.recordFilter = b.dataset.k; renderPage(true); },
    rec: (b) => { ui.recordId = b.dataset.id; renderPage(true); },
    'new-record': () => {
      const r = { id: 'r' + Date.now(), name: '新订阅', price: 0, cycle: '月', renew: '—', pay: '—', status: '使用中', sync: 'local' };
      D.records.unshift(r); ui.recordId = r.id; ui.recordFilter = 'all';
      advance(r); renderPage(true); setTimeout(() => $('#f-name')?.select(), 50);
    },
    cf: (b) => { ui.cfChoice = b.dataset.k; renderPage(true); },
    resolve: () => {
      const r = D.records.find((x) => x.id === D.conflict.recordId);
      r.price = ui.cfChoice === 'local' ? D.conflict.local.price : D.conflict.remote.price;
      r.pay = D.conflict.remote.pay;
      r._flash = true; setTimeout(() => { r._flash = false; }, 1300);
      N.toast(toastHost, `${syncBadge('local', { label: '' })} 冲突已解决 · 已在本机保存，正在同步`);
      N.transition(() => advance(r));
    },
    'vault-lock': () => lockVault(false),
    'vault-open': (b) => vaultRead(b.dataset.id),
    'vault-read': (b) => vaultRead(b.dataset.id),
    'vault-hide': () => { ui.vault.revealed = null; refreshVaultTable(); },
    'vault-copy': async (b) => {
      const s = D.space.items.find((x) => x.id === b.dataset.id);
      const what = b.dataset.what;
      const ok = await askPassword({ action: what, item: s });
      if (ok) N.toast(toastHost, `${I('check')} 已${what}「${s.name}」${what === '复制' ? ' · 剪贴板清理策略待定（TBD-09）' : ''}`);
    },
    agent: (b) => { const id = b.dataset.id; pageChat.openSession(id, D.agents[id].sessions[0].id); mountAgentPage(); },
    session: (b) => { pageChat.openSession(pageChat.agent, b.dataset.id); $$('[data-act="session"]', main).forEach((x) => x.classList.toggle('is-selected', x === b)); },
    'chat-new': () => pageChat.newSession(),
    'dock-agent': (b) => { dockChat.agent = b.dataset.id; dockChat.session = null; dockChat.msgs = []; renderDock(); },
    'dock-close': () => toggleDock(),
    jstatus: (b) => { ui.jobStatus = ui.jobStatus === b.dataset.k ? null : b.dataset.k; refreshJobs(); },
    jowner: (b) => { ui.jobOwner = b.dataset.k; refreshJobs(); },
    job: (b) => { ui.jobId = b.dataset.id; $$('tr[data-act="job"]', main).forEach((t) => t.classList.toggle('is-selected', t === b)); $('#job-detail').innerHTML = jobDetail(); $('#job-detail').classList.remove('enter'); void $('#job-detail').offsetWidth; $('#job-detail').classList.add('enter'); },
    'job-run': () => {
      const j = D.jobs.find((x) => x.id === ui.jobId);
      const O = N.OWNERS[j.owner];
      j.last = 'running'; j.lastAt = '正在运行 · 刚刚触发';
      (D.runs[j.id] ||= []).unshift({ s: 'running', at: '刚刚', dur: '…', note: j.owner === 'studiolo' ? '手动触发 · request_id 9c2e' : `已请求 ${O.label} 运行 · runId 8f3a` });
      N.toast(toastHost, `${I('play')} 已请求 ${O.label} 立即运行「${j.name}」`);
      refreshJobs();
      setTimeout(() => {
        j.last = 'ok'; j.lastAt = '刚刚 · 9 秒';
        D.runs[j.id][0] = { ...D.runs[j.id][0], s: 'ok', dur: '9 秒' };
        if (ui.page === 'tasks') refreshJobs();
      }, 3200);
    },
    'job-verify': () => {
      const j = D.jobs.find((x) => x.id === ui.jobId);
      N.toast(toastHost, `${I('search')} 正在查询 Hermes 执行账本…`);
      setTimeout(() => {
        j.last = 'ok'; j.lastAt = '今天 10:00 · 已在 Hermes 确认';
        D.runs[j.id] = [{ s: 'ok', at: '今天 10:00', dur: '2 分 04 秒', note: '已从 Hermes 确认成功，无需重跑' }];
        if (ui.page === 'tasks') refreshJobs();
      }, 1100);
    },
    'job-toggle': () => {
      const j = D.jobs.find((x) => x.id === ui.jobId);
      j.enabled = !j.enabled;
      j.last = j.enabled ? 'ok' : 'paused';
      j.next = j.enabled ? '按计划' : '已暂停';
      N.toast(toastHost, `${j.enabled ? '已恢复' : '已暂停'}「${j.name}」· 由 ${N.OWNERS[j.owner].label} 执行`);
      refreshJobs();
    },
    'new-job': () => {
      const opts = [
        ['studiolo', 'Studiolo Core', '定时、数据变化、Agent 完成后、手动'],
        ['openclaw', 'OpenClaw · studio', '原生 Cron（cron.add）'],
        ['hermes', 'Hermes · nas-01 / default', '原生 Cron（jobs）'],
      ];
      const paint = () => { $('#nj-owners').innerHTML = opts.map(([k, n, d]) => `<button type="button" class="owner-opt oc-${k}" data-k="${k}" aria-pressed="${ui.newJobOwner === k}"><span class="am">${I(N.OWNERS[k].icon)}</span><span><div class="nm">${n}</div><div class="ds">${d}</div></span></button>`).join(''); };
      paint();
      $('#nj-owners').onclick = (e) => { const b = e.target.closest('.owner-opt'); if (b) { ui.newJobOwner = b.dataset.k; paint(); } };
      const d = $('#new-job');
      d.onclose = () => { if (d.returnValue === 'ok') N.toast(toastHost, `原型：接下来显示 ${N.OWNERS[ui.newJobOwner].label} 的原生字段表单`); d.returnValue = ''; };
      d.showModal();
    },
    'set-sec': (b) => { ui.settingsSec = b.dataset.k; renderPage(true); },
    'set-theme': (b) => N.set({ theme: b.dataset.v }),
    'set-mode': (b) => N.set({ mode: b.dataset.v }),
    'set-blur': () => N.set({ blur: N.get().blur === 'off' ? 'on' : 'off' }),
    'set-motion': () => N.set({ motion: N.get().motion === 'reduced' ? 'full' : 'reduced' }),
  };

  win.addEventListener('click', (e) => {
    const g = e.target.closest('[data-go]');
    if (g) { go(g.dataset.go); return; }
    const a = e.target.closest('[data-act]');
    if (a && !a.disabled && ACT[a.dataset.act]) { ACT[a.dataset.act](a, e); return; }
    if (e.target.closest('#sb-sync') || e.target.closest('#tb-sync')) {
      const p = $('#sync-panel');
      if (p.hidden) { renderSyncPanel(); p.hidden = false; } else p.hidden = true;
      return;
    }
    if (!e.target.closest('#sync-panel')) $('#sync-panel').hidden = true;
  });
  $('#btn-cmdk').addEventListener('click', openPalette);
  $('#btn-dock').addEventListener('click', toggleDock);
  $('#btn-nav').addEventListener('click', () => win.classList.toggle('nav-collapsed'));
  document.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); toggleDock(); }
    if (e.key === 'Escape') $('#sync-panel').hidden = true;
  });
  // 应用切到后台：共享空间立即锁定
  document.addEventListener('visibilitychange', () => { if (document.hidden && ui.vault.unlocked) lockVault(ui.page !== 'space'); });

  /* ---------- 原型状态变化 ---------- */
  N.on((s, prev) => {
    if (s.online !== prev.online) {
      pageChat.onOnline(s.online); dockChat.onOnline(s.online);
      renderStatus(); renderSidebar();
      if (ui.page !== 'agent') renderPage(true);
      else mountAgentPageSoft();
      N.toast(toastHost, s.online ? `${I('sync')} 已重新联网，正在同步本机更改` : `${I('wifiOff')} 已离线 · 可以继续记录，更改会保存在本机`);
      if (s.online) setTimeout(() => flushAll(true), 1400);
    }
    if (s.theme !== prev.theme || s.mode !== prev.mode || s.blur !== prev.blur || s.motion !== prev.motion) {
      renderStatus();
      if (ui.page === 'settings') renderPage(true);
      requestAnimationFrame(() => N.syncSeg(document));
    }
    if (s.platform !== prev.platform) renderChrome();
  });
  // Agent 页在网络变化时只更新侧栏，不打断正在进行的流式回复
  function mountAgentPageSoft() {
    const chatRoot = $('#chat-root');
    const keep = chatRoot && chatRoot.firstElementChild;
    if (!keep) return mountAgentPage();
    const tmp = document.createElement('div');
    const saved = pageChat.root;
    // 重新渲染外框，再把原聊天 DOM 挂回
    mountAgentPage.call(null);
    const newRoot = $('#chat-root');
    newRoot.replaceChildren(keep);
    pageChat.root = newRoot;
    pageChat.onOnline(online());
    void tmp; void saved;
  }

  N.protoBar($('#proto'), { page: 'desktop' });
  renderChrome();
  renderPage();
  requestAnimationFrame(() => N.syncSeg(document));
  window.addEventListener('resize', () => N.syncSeg(document));
})();
