/* ==========================================================================
   Studiolo 原型 · 共享脚本
   - 原型状态（主题 / 模式 / 模糊 / 动效 / 网络 / 平台），桌面与手机共享并持久化
   - 图标、模拟数据、通用工具（Toast、视图过渡、流式文本）
   ========================================================================== */
window.Studiolo = (() => {
  const KEY = 'studiolo-proto-v1';
  const mq = (q) => window.matchMedia(q).matches;
  const defaults = {
    theme: 'paper',
    mode: mq('(prefers-color-scheme: dark)') ? 'dark' : 'light',
    blur: 'on',
    motion: mq('(prefers-reduced-motion: reduce)') ? 'reduced' : 'full',
    online: true,
    platform: /Mac/i.test(navigator.platform) ? 'mac' : 'win',
  };
  let state = { ...defaults };
  try { state = { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { /* 忽略 */ }
  const listeners = new Set();

  function apply() {
    const r = document.documentElement;
    r.dataset.theme = state.theme;
    r.dataset.mode = state.mode;
    r.dataset.blur = state.blur;
    r.dataset.motion = state.motion;
    r.dataset.online = state.online ? 'yes' : 'no';
    r.dataset.platform = state.platform;
  }
  function set(patch) {
    const prev = { ...state };
    state = { ...state, ...patch };
    localStorage.setItem(KEY, JSON.stringify(state));
    apply();
    listeners.forEach((fn) => fn(state, prev));
  }
  const get = () => state;
  const on = (fn) => listeners.add(fn);
  apply();

  /* ---------- 图标（24 网格，线性） ---------- */
  const P = {
    home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    today: '<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M3 9h18M8 2v4M16 2v4"/><circle cx="12" cy="15" r="2"/>',
    ledger: '<path d="M4 7a2 2 0 0 1 2-2h12v3"/><path d="M4 7v11a2 2 0 0 0 2 2h14V8H6a2 2 0 0 1-2-1z"/><path d="M16 14h1"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z"/>',
    data: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    device: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    unlock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 7.7-1.5"/>',
    shield: '<path d="M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6z"/><path d="m9 12 2 2 4-4"/>',
    chat: '<path d="M20.5 12a8.5 8.5 0 0 1-12.3 7.6L3.5 20.5l1-4.4A8.5 8.5 0 1 1 20.5 12z"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13.5h.01M15 13.5h.01M9.5 17h5"/>',
    tasks: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
    zap: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    api: '<path d="M8 5 3 12l5 7M16 5l5 7-5 7M14 4l-4 16"/>',
    settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
    checks: '<path d="m2 12.5 4.5 4.5L16 7M12 16l1 1 9.5-10"/>',
    chevR: '<path d="m9 5 7 7-7 7"/>',
    chevL: '<path d="m15 5-7 7 7 7"/>',
    chevD: '<path d="m5 9 7 7 7-7"/>',
    sync: '<path d="M20 12a8 8 0 0 1-14.4 4.8M4 12a8 8 0 0 1 14.4-4.8"/><path d="M19 3v4.5h-4.5M5 21v-4.5h4.5"/>',
    wifiOff: '<path d="m3 3 18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.6a10 10 0 0 1 4.2-2.3M19 12.6a10 10 0 0 0-2.4-1.6M2 8.8a15 15 0 0 1 4.3-2.6M22 8.8A15 15 0 0 0 11 5.1M12 20h.01"/>',
    cloud: '<path d="M7 18a4.5 4.5 0 1 1 .9-8.9A6 6 0 0 1 19.4 11 3.5 3.5 0 0 1 18 18z"/>',
    cloudDown: '<path d="M7 17a4.5 4.5 0 1 1 .9-8.9A6 6 0 0 1 19.4 10 3.5 3.5 0 0 1 18 17"/><path d="M12 12v8M9 17l3 3 3-3"/>',
    alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    file: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14.5 8.5l2 2"/>',
    note: '<path d="M5 4h14v16H5z"/><path d="M8.5 9h7M8.5 13h7M8.5 17h4"/>',
    braces: '<path d="M8 4c-2 0-3 1-3 3v2c0 1.5-.8 3-2 3 1.2 0 2 1.5 2 3v2c0 2 1 3 3 3M16 4c2 0 3 1 3 3v2c0 1.5.8 3 2 3-1.2 0-2 1.5-2 3v2c0 2-1 3-3 3"/>',
    play: '<path d="M7 4.5v15l12.5-7.5z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    send: '<path d="M5 12h13M12 5l7 7-7 7"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5M12 7.5V12l3 2"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    filter: '<path d="M4 5h16l-6 7.5V19l-4 2v-8.5z"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    table: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10"/>',
    layers: '<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="m2.5 12.5 9.5 5 9.5-5M2.5 17l9.5 5 9.5-5"/>',
    sidebar: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/>',
    panel: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
    arrowUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    arrowDown: '<path d="M12 5v14M5 12l7 7 7-7"/>',
    sparkle: '<path d="M12 3c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7z"/>',
    claw: '<path d="M6 20c0-6 2-10 6-14M11 20c0-5 1.5-8 5-11M16 20c0-3 1-5 3-7"/>',
    hermes: '<path d="M12 3v18M7 7c2 1.5 3.5 2 5 2s3-.5 5-2M8 13c1.5 1 2.8 1.4 4 1.4s2.5-.4 4-1.4"/>',
    studiolo: '<path style="fill:currentColor;stroke:none" d="M4 4h16v4.96h-2.88V6.08h-1.76v2.88H8.32v2.72H20V20H8.64v-3.04H6.88V20H4v-4.32h11.36v-2.56H4Z"/>',
    logout: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
    pin: '<path d="M9 4h6l-1 6 3 3v1H7v-1l3-3z"/><path d="M12 14v6"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    hash: '<path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16"/>',
    receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    cup: '<path d="M5 8h11v5a5 5 0 0 1-5 5H10a5 5 0 0 1-5-5zM16 10h1.5a2.5 2.5 0 0 1 0 5H16M8 3v2M12 3v2"/>',
    cart: '<path d="M3 4h2l2.4 11h10.4L20 8H6.2"/><circle cx="9" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/>',
    car: '<path d="M5 16V11l2-5h10l2 5v5M5 16h14M5 16v2M19 16v2M3.5 11h17"/><circle cx="8" cy="13.5" r=".6"/><circle cx="16" cy="13.5" r=".6"/>',
    bag: '<path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    command: '<path d="M9 6v12M15 6v12M6 9h12M6 15h12"/>',
  };
  const icon = (name, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || P.info}</svg>`;

  const logoSvg = `<span class="logo" aria-hidden="true"><svg viewBox="0 0 100 100" fill="currentColor"><path d="M 0 0 100 0 100 31 82 31 82 13 71 13 71 31 27 31 27 48 100 48 100 100 29 100 29 81 18 81 18 100 0 100 0 73 71 73 71 57 0 57 Z"/></svg></span>`;

  /* ---------- 同步 / 归属片段 ---------- */
  const SYNC = {
    local: { cls: 'is-local', label: '已在本机保存', glyph: 'check' },
    pending: { cls: 'is-pending', label: '待同步', glyph: '' },
    synced: { cls: 'is-synced', label: '已同步', glyph: 'checks' },
    conflict: { cls: 'is-conflict', label: '需处理冲突', glyph: '' },
    offline: { cls: 'is-offline', label: '离线', glyph: '' },
  };
  function syncBadge(kind, { label, dotOnly } = {}) {
    const s = SYNC[kind] || SYNC.synced;
    const g = kind === 'conflict' ? '<b style="font-size:10px;line-height:1">!</b>' : s.glyph ? icon(s.glyph) : '';
    return `<span class="sync ${s.cls} ${dotOnly ? 'dot-only' : ''}" title="${label || s.label}"><span class="glyph">${g}</span><span class="label">${label || s.label}</span></span>`;
  }
  const OWNERS = {
    studiolo: { label: 'Studiolo', icon: 'studiolo', cls: 'o-studiolo' },
    openclaw: { label: 'OpenClaw', icon: 'claw', cls: 'o-openclaw' },
    hermes: { label: 'Hermes', icon: 'hermes', cls: 'o-hermes' },
  };
  function ownerBadge(owner, where = '') {
    const o = OWNERS[owner];
    return `<span class="owner ${o.cls}"><span class="mark">${icon(o.icon)}</span>${o.label}${where ? `<span class="where">${where}</span>` : ''}</span>`;
  }

  /* ---------- 模拟数据 ---------- */
  const data = {
    user: { name: 'Yuan', workspace: '个人工作区' },
    core: { host: 'core.yuan.home', version: '0.8.1' },
    ledger: {
      month: '11 月', spent: 6482.3, income: 18000, budget: 8000,
      daily: [120, 86, 240, 60, 310, 95, 180, 420, 75, 130, 260, 88, 140, 205, 66, 172],
      cats: [
        { name: '餐饮', v: 1820, c: '#e0542b' }, { name: '居住', v: 2600, c: '#3d5afe' },
        { name: '交通', v: 640, c: '#17824f' }, { name: '订阅', v: 412, c: '#7656dc' }, { name: '其他', v: 1010, c: '#a8690c' },
      ],
      tx: [
        { id: 't1', title: '午餐 · 老街牛肉面', cat: '餐饮', icon: 'cup', amount: -32, when: '今天 12:31', sync: 'synced', from: 'Pixel 9' },
        { id: 't2', title: '地铁', cat: '交通', icon: 'car', amount: -6, when: '今天 09:02', sync: 'synced', from: 'Pixel 9' },
        { id: 't3', title: 'Notion 年费', cat: '订阅', icon: 'receipt', amount: -768, when: '昨天 22:10', sync: 'pending', from: '本机' },
        { id: 't4', title: '盒马 · 周末采购', cat: '餐饮', icon: 'cart', amount: -214.6, when: '11 月 15 日', sync: 'synced', from: 'MacBook Air' },
        { id: 't5', title: '11 月工资', cat: '收入', icon: 'ledger', amount: 18000, when: '11 月 10 日', sync: 'synced', from: 'MacBook Air' },
        { id: 't6', title: '优衣库', cat: '购物', icon: 'bag', amount: -299, when: '11 月 9 日', sync: 'synced', from: '本机' },
      ],
    },
    websites: [
      { name: 'Linear', url: 'linear.app', tag: '工作', color: '#5e6ad2', visits: 42, sync: 'synced' },
      { name: 'Hermes Docs', url: 'hermes-agent.nousresearch.com', tag: 'Agent', color: '#7656dc', visits: 18, sync: 'synced' },
      { name: 'OpenClaw Gateway', url: 'docs.openclaw.ai', tag: 'Agent', color: '#e0542b', visits: 15, sync: 'synced' },
      { name: 'Grafana · NAS', url: 'nas.yuan.home:3000', tag: '家庭', color: '#f2a03d', visits: 31, sync: 'synced' },
      { name: 'Figma', url: 'figma.com', tag: '设计', color: '#1abc9c', visits: 12, sync: 'pending' },
      { name: 'RSSHub', url: 'rsshub.app', tag: '阅读', color: '#f5712c', visits: 9, sync: 'synced' },
      { name: 'Tauri Docs', url: 'v2.tauri.app', tag: '开发', color: '#24c8db', visits: 27, sync: 'synced' },
      { name: '少数派', url: 'sspai.com', tag: '阅读', color: '#d71a1b', visits: 6, sync: 'synced' },
    ],
    collections: [
      { id: 'subs', name: '订阅服务', icon: 'receipt', count: 23, updated: '刚刚' },
      { id: 'books', name: '读书清单', icon: 'note', count: 128, updated: '昨天' },
      { id: 'plants', name: '阳台植物', icon: 'sparkle', count: 14, updated: '3 天前' },
      { id: 'gear', name: '家用设备保修', icon: 'shield', count: 31, updated: '上周' },
    ],
    records: [
      { id: 'r1', name: 'ChatGPT Plus', price: 140, cycle: '月', renew: '11 月 28 日', pay: '招行信用卡', status: '使用中', sync: 'synced' },
      { id: 'r2', name: 'iCloud+ 200GB', price: 21, cycle: '月', renew: '12 月 3 日', pay: 'Apple ID', status: '使用中', sync: 'synced' },
      { id: 'r3', name: 'Notion Plus', price: 768, cycle: '年', renew: '2027 年 11 月 15 日', pay: '招行信用卡', status: '使用中', sync: 'pending' },
      { id: 'r4', name: 'Spotify 家庭', price: 25, cycle: '月', renew: '11 月 20 日', pay: '支付宝', status: '使用中', sync: 'conflict' },
      { id: 'r5', name: 'Cloudflare R2', price: 6.8, cycle: '月', renew: '12 月 1 日', pay: 'Visa', status: '按量', sync: 'synced' },
      { id: 'r6', name: '1Password 家庭', price: 418, cycle: '年', renew: '2027 年 3 月 2 日', pay: 'Visa', status: '使用中', sync: 'synced' },
      { id: 'r7', name: 'Netflix 标准', price: 68, cycle: '月', renew: '—', pay: '支付宝', status: '已取消', sync: 'synced' },
      { id: 'r8', name: 'GitHub Copilot', price: 70, cycle: '月', renew: '11 月 22 日', pay: 'Visa', status: '使用中', sync: 'synced' },
    ],
    conflict: {
      recordId: 'r4',
      base: { price: 25, pay: '支付宝', renew: '11 月 20 日' },
      local: { price: 30, pay: '支付宝', renew: '11 月 20 日', device: '本机 · Yuan 的台式机', at: '今天 10:12（离线时修改）' },
      remote: { price: 28, pay: '微信支付', renew: '11 月 20 日', device: 'Pixel 9', at: '今天 11:40' },
    },
    devices: [
      { name: 'Yuan 的台式机', os: 'Windows 11', icon: 'device', state: 'online', note: '本机 · Studiolo Local 运行中', me: true },
      { name: 'MacBook Air', os: 'macOS 15', icon: 'device', state: 'online', note: '2 分钟前同步' },
      { name: 'Pixel 9', os: 'Android 16', icon: 'phone', state: 'idle', note: '1 小时前同步 · 0 待同步' },
      { name: 'NAS-01', os: 'Debian · 遥测', icon: 'server', state: 'online', note: 'CPU 23% · 磁盘 61%' },
    ],
    space: {
      name: '个人共享空间',
      meta: { count: 5, size: '2.4 MB', local: 4 },
      items: [
        { id: 's1', type: 'key', name: 'OpenAI API Key', size: '164 B', rev: 'r7', updated: '2 天前', by: 'MacBook Air', local: 'downloaded',
          content: { kind: 'key', value: 'sk-proj-4f9Q…demo…T7xLm2', note: '用于 Hermes research profile' } },
        { id: 's2', type: 'text', name: '访客 Wi-Fi', size: '58 B', rev: 'r2', updated: '上周', by: 'Pixel 9', local: 'downloaded',
          content: { kind: 'text', value: '网络：Yuan-Guest\n密码：sunflower-2741\n有效期至 12 月底' } },
        { id: 's3', type: 'config', name: 'ssh_config', size: '1.1 KB', rev: 'r12', updated: '昨天', by: '本机', local: 'pending',
          content: { kind: 'config', value: 'Host nas\n  HostName nas.yuan.home\n  User yuan\n  IdentityFile ~/.ssh/id_ed25519\n\nHost studio\n  HostName 10.0.0.42\n  ForwardAgent no' } },
        { id: 's4', type: 'file', name: '护照扫描.pdf', size: '1.2 MB', rev: 'r1', updated: '3 个月前', by: 'MacBook Air', local: 'downloaded',
          content: { kind: 'file', value: 'PDF · 2 页 · 1.2 MB' } },
        { id: 's5', type: 'file', name: 'home-assistant.yaml', size: '1.1 MB', rev: 'r4', updated: '5 天前', by: 'NAS-01', local: 'remote',
          content: { kind: 'file', value: 'YAML · 1.1 MB' } },
      ],
    },
    agents: {
      openclaw: {
        id: 'openclaw', name: 'OpenClaw', instance: 'studio', profile: 'operator', endpoint: 'wss://studio.yuan.home:18789',
        caps: { history: '游标分页', stream: true, cancel: true, replay: true, idem: true, attach: '待定', cron: '读写' },
        sessions: [
          { id: 'c1', title: '整理订阅服务记录', last: '10 分钟前' },
          { id: 'c2', title: '周报草稿 · 第 46 周', last: '昨天' },
          { id: 'c3', title: '家里网络排障', last: '周三' },
          { id: 'c4', title: '仓库依赖巡检失败分析', last: '11 月 10 日' },
        ],
      },
      hermes: {
        id: 'hermes', name: 'Hermes', instance: 'nas-01', profile: 'default', endpoint: 'https://nas.yuan.home:8642',
        caps: { history: '有界 REST', stream: true, cancel: true, replay: '服务端重新填充', idem: false, attach: '待定', cron: '读写' },
        sessions: [
          { id: 'h1', title: '晨间简报 · 11 月 16 日', last: '07:00' },
          { id: 'h2', title: '研究：本地向量库选型', last: '昨天' },
          { id: 'h3', title: 'RSS 摘要格式调整', last: '周一' },
        ],
      },
    },
    chat: {
      c1: [
        { role: 'user', text: '帮我看下订阅服务里这个月要续费的有哪些？' },
        { role: 'agent', text: '本月还有 4 项待续费：\n• Spotify 家庭 · 11 月 20 日 · ¥25\n• GitHub Copilot · 11 月 22 日 · ¥70\n• ChatGPT Plus · 11 月 28 日 · ¥140\n• iCloud+ · 12 月 3 日（下月初）\n合计约 ¥235。需要我给 Spotify 加一个提前 2 天的提醒吗？', tool: '读取 Data · 订阅服务（只读）' },
      ],
      h1: [
        { role: 'user', text: '今天的简报里加上 NAS 磁盘的情况。' },
        { role: 'agent', text: '好的。已在晨间简报模板里加入「NAS-01 磁盘使用」段落，下次 07:00 生效。当前读数：61%，比上周增长 3%。' },
      ],
    },
    replies: {
      openclaw: '可以。我建议这样处理 Spotify 家庭的续费提醒：\n\n1. 在 Studiolo 自动化里新建一个「数据变化时」任务，监听「订阅服务」中续费日字段；\n2. 续费前 2 天推送通知到手机；\n3. 提醒只包含服务名和金额，不带账户信息。\n\n这个任务会由 Studiolo 调度，我这边不会再创建重复的 Cron。要我现在帮你起草吗？',
      hermes: '我查了一下 research profile 最近的运行：论文 RSS 摘要在 03:00 那次没有回执，状态未知。为避免重复执行，我没有自动重试。建议你在任务页查看 Hermes 执行账本确认后再手动运行。',
    },
    jobs: [
      { id: 'j1', name: '每日账本备份', owner: 'studiolo', where: 'Studiolo Core', trigger: '定时', schedule: '每天 03:00', expr: '0 3 * * *', tz: 'Asia/Shanghai', next: '明天 03:00', last: 'ok', lastAt: '今天 03:00 · 12 秒', enabled: true,
        caps: { edit: true, pause: true, run: true, history: '完整历史' } },
      { id: 'j2', name: 'Spotify 续费提醒', owner: 'studiolo', where: 'Studiolo Core', trigger: '数据变化', schedule: '订阅服务 · 续费日前 2 天', expr: 'data_changed', tz: 'Asia/Shanghai', next: '11 月 18 日 09:00', last: 'ok', lastAt: '10 月 18 日', enabled: true,
        caps: { edit: true, pause: true, run: true, history: '完整历史' } },
      { id: 'j3', name: '晨间简报', owner: 'hermes', where: 'nas-01 / default', trigger: 'Cron', schedule: '工作日 07:00', expr: '0 7 * * 1-5', tz: 'Asia/Shanghai', next: '明天 07:00', last: 'running', lastAt: '正在运行 · 已 38 秒', enabled: true,
        caps: { edit: true, pause: true, run: true, history: '执行账本 · 最近 50 条' } },
      { id: 'j4', name: '仓库依赖巡检', owner: 'openclaw', where: 'studio', trigger: 'Cron', schedule: '每 6 小时', expr: 'every 6h', tz: 'UTC', next: '今天 22:00', last: 'fail', lastAt: '今天 16:00 · 退出码 1', enabled: true,
        caps: { edit: true, pause: true, run: true, history: 'cron.runs 分页' } },
      { id: 'j5', name: '周报汇总', owner: 'openclaw', where: 'studio', trigger: 'Cron', schedule: '周五 17:30', expr: '30 17 * * 5', tz: 'Asia/Shanghai', next: '已暂停', last: 'paused', lastAt: '11 月 8 日 · 成功', enabled: false,
        caps: { edit: true, pause: true, run: true, history: 'cron.runs 分页' } },
      { id: 'j6', name: '论文 RSS 摘要', owner: 'hermes', where: 'nas-01 / research', trigger: 'Cron', schedule: '每天 03:00', expr: '0 3 * * *', tz: 'Europe/Berlin', next: '明天 10:00（本地）', last: 'unknown', lastAt: '今天 10:00 · 无回执', enabled: true,
        caps: { edit: false, pause: true, run: true, history: '仅最后状态' }, limited: '该 Hermes 版本未开放历史接口，只能读取最后一次状态；定义为只读。' },
      { id: 'j7', name: '清理过期网站标签', owner: 'studiolo', where: 'Studiolo Core', trigger: '手动', schedule: '仅手动运行', expr: 'manual', tz: '—', next: '—', last: 'ok', lastAt: '11 月 2 日', enabled: true,
        caps: { edit: true, pause: false, run: true, history: '完整历史' } },
    ],
    runs: {
      j3: [
        { s: 'running', at: '今天 07:00', dur: '38 秒…', note: 'Hermes 会话 h1' },
        { s: 'ok', at: '昨天 07:00', dur: '1 分 12 秒', note: '输出 1.2 KB' },
        { s: 'ok', at: '11 月 14 日 07:00', dur: '58 秒', note: '输出 1.1 KB' },
        { s: 'fail', at: '11 月 13 日 07:00', dur: '4 秒', note: '模型限流 · 已按 Hermes 规则补跑' },
        { s: 'ok', at: '11 月 13 日 07:06', dur: '1 分 03 秒', note: 'catch-up 补跑' },
      ],
      j4: [
        { s: 'fail', at: '今天 16:00', dur: '2 分 41 秒', note: 'npm audit 退出码 1' },
        { s: 'ok', at: '今天 10:00', dur: '2 分 12 秒', note: '无新增风险' },
        { s: 'ok', at: '今天 04:00', dur: '2 分 09 秒', note: '无新增风险' },
      ],
      j1: [
        { s: 'ok', at: '今天 03:00', dur: '12 秒', note: '快照 2.1 MB' },
        { s: 'ok', at: '昨天 03:00', dur: '11 秒', note: '快照 2.1 MB' },
        { s: 'ok', at: '11 月 14 日 03:00', dur: '12 秒', note: '快照 2.0 MB' },
      ],
      j6: [{ s: 'unknown', at: '今天 10:00', dur: '—', note: '提交后未收到回执，Studiolo 不会自动重试' }],
    },
  };

  /* ---------- 工具 ---------- */
  const fmtMoney = (n, sign = true) => {
    const s = Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (sign ? (n < 0 ? '−' : '+') : '') + '¥' + s;
  };
  const motionOK = () => state.motion === 'full' && !mq('(prefers-reduced-motion: reduce)');

  /** 视图过渡：支持时用 View Transitions，否则直接更新 */
  function transition(update, types = []) {
    if (!document.startViewTransition || !motionOK()) { update(); return Promise.resolve(); }
    try {
      return document.startViewTransition({ update, types }).finished.catch(() => {});
    } catch {
      return document.startViewTransition(update).finished.catch(() => {});
    }
  }

  /** Toast：host 为定位容器内的 .toast-host */
  function toast(host, html, ms = 2600) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.setAttribute('role', 'status');
    el.innerHTML = html;
    host.appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 360); }, ms);
    return el;
  }

  /** 流式输出文本，可暂停（断线）与恢复 */
  function streamer(el, text, { speed = 18, onDone } = {}) {
    let i = 0, timer = null, paused = false;
    el.classList.add('caret');
    const tick = () => {
      if (paused) return;
      const step = 1 + Math.floor(Math.random() * 3);
      i = Math.min(text.length, i + step);
      el.textContent = text.slice(0, i);
      el.closest('[data-scroll]')?.scrollTo({ top: 1e6 });
      if (i >= text.length) { el.classList.remove('caret'); onDone?.(); return; }
      timer = setTimeout(tick, speed + Math.random() * 30);
    };
    tick();
    return {
      pause() { paused = true; clearTimeout(timer); el.classList.remove('caret'); },
      resume() { if (!paused) return; paused = false; el.classList.add('caret'); tick(); },
      finish() { clearTimeout(timer); el.textContent = text; el.classList.remove('caret'); onDone?.(); },
      get progress() { return i / text.length; },
    };
  }

  /** 分段控件滑块定位 */
  function syncSeg(root = document) {
    root.querySelectorAll('.seg').forEach((seg) => {
      let thumb = seg.querySelector('.thumb');
      if (!thumb) { thumb = document.createElement('i'); thumb.className = 'thumb'; seg.prepend(thumb); }
      const on = seg.querySelector('button[aria-pressed="true"]');
      if (!on) { thumb.style.width = '0'; return; }
      thumb.style.width = on.offsetWidth + 'px';
      thumb.style.translate = on.offsetLeft + 'px 0';
    });
  }

  /** 模拟 KDF 验证（演示密码 studiolo） */
  const DEMO_PASSWORD = 'studiolo';
  const verifyPassword = (pw) => new Promise((res) => setTimeout(() => res(pw === DEMO_PASSWORD), 650));

  /* ---------- 原型控制条 ---------- */
  function protoBar(el, { page }) {
    const seg = (key, opts) => `<div class="pseg" role="group">${opts.map(([v, l]) =>
      `<button type="button" data-proto="${key}" data-v="${v}" aria-pressed="${String(state[key]) === String(v)}">${l}</button>`).join('')}</div>`;
    el.innerHTML = `
      <span class="brand">${logoSvg} Studiolo 设计原型</span>
      <nav class="group" aria-label="原型页面">
        <a href="index.html" ${page === 'index' ? 'aria-current="page"' : ''}>方案说明</a>
        <a href="desktop.html" ${page === 'desktop' ? 'aria-current="page"' : ''}>桌面端</a>
        <a href="mobile.html" ${page === 'mobile' ? 'aria-current="page"' : ''}>手机端</a>
      </nav>
      <span class="spacer"></span>
      <div class="group"><span>主题</span>${seg('theme', [['paper', '纸墨'], ['glass', 'Liquid Glass']])}</div>
      <div class="group"><span>外观</span>${seg('mode', [['light', '浅色'], ['dark', '深色']])}</div>
      <div class="group"><span>模糊</span>${seg('blur', [['on', '开'], ['off', '关']])}</div>
      <div class="group"><span>动效</span>${seg('motion', [['full', '完整'], ['reduced', '减少']])}</div>
      <div class="group"><span>网络</span>${seg('online', [['true', '在线'], ['false', '离线']])}</div>
      ${page === 'desktop' ? `<div class="group"><span>平台</span>${seg('platform', [['mac', 'macOS'], ['win', 'Windows']])}</div>` : ''}`;
    el.addEventListener('click', (e) => {
      const b = e.target.closest('[data-proto]');
      if (!b) return;
      let v = b.dataset.v;
      if (b.dataset.proto === 'online') v = v === 'true';
      set({ [b.dataset.proto]: v });
    });
    on(() => el.querySelectorAll('[data-proto]').forEach((b) => {
      b.setAttribute('aria-pressed', String(String(state[b.dataset.proto]) === b.dataset.v));
    }));
  }

  return { get, set, on, icon, logoSvg, syncBadge, ownerBadge, OWNERS, data, fmtMoney, transition, toast, streamer, syncSeg, verifyPassword, DEMO_PASSWORD, protoBar, motionOK };
})();
