const navGroups = [
  {
    title: '客服工作',
    items: [
      ['overview', '平台总览', 'i-overview'],
      ['scenes', '服务场景', 'i-layers', '12'],
      ['conversations', '会话工作台', 'i-chat'],
      ['tickets', '服务工单', 'i-ticket'],
      ['handoff', '人工协同', 'i-headset'],
      ['memory', '客户记忆', 'i-users'],
    ],
  },
  {
    title: '配置管理',
    items: [
      ['agents', 'Agent 管理', 'i-robot'],
      ['models', '模型网关', 'i-spark'],
      ['knowledge', '知识库', 'i-book'],
      ['tools', '工具目录', 'i-tool'],
      ['open-platform', '开放平台', 'i-plug'],
      ['access', '访问与策略', 'i-shield'],
    ],
  },
  {
    title: '质量运营',
    items: [
      ['evaluation', '质量大盘', 'i-flask'],
      ['observability', '运行与审计', 'i-pulse'],
    ],
  },
  {
    title: '系统管理',
    items: [
      ['members', '成员管理', 'i-users'],
      ['roles', '角色与权限', 'i-shield'],
      ['security', '会话与安全', 'i-gear'],
      ['extensions', '插件平台', 'i-plug'],
    ],
  },
];

function icon(id, className = '') {
  return `<svg class="ic ${className}"><use href="#${id}"></use></svg>`;
}

function renderSidebar(element) {
  const active = element.dataset.active || 'scenes';
  const groups = navGroups.map(group => `
    <div class="nav-group">
      <div class="nav-title">${group.title}</div>
      ${group.items.map(item => {
        const [id, label, iconId, count] = item;
        return `<button class="nav-item ${id === active ? 'active' : ''}" aria-current="${id === active ? 'page' : 'false'}">
          ${icon(iconId)}
          <span>${label}</span>
          ${count ? `<span class="nav-count">${count}</span>` : ''}
        </button>`;
      }).join('')}
    </div>
  `).join('');

  element.innerHTML = `
    <div class="brand">
      <div class="brand-orb"></div>
      <div class="brand-copy"><strong>nexusdesk.</strong><span>智能客服平台</span></div>
    </div>
    <div class="nav-groups">${groups}</div>
    <div class="sidebar-foot">
      <div class="env-line"><span class="env-dot"></span> local · admin</div>
    </div>
  `;
}

function showView(name) {
  const target = [...document.querySelectorAll('.screen')].find(screen => screen.dataset.screen === name);
  if (!target) return false;
  document.querySelectorAll('.screen').forEach(screen => screen.classList.toggle('is-active', screen === target));
  document.body.dataset.view = name;
  document.body.classList.toggle('is-mobile-view', target.classList.contains('mobile-screen'));
  return true;
}

document.querySelectorAll('[data-sidebar]').forEach(renderSidebar);

const requestedView = new URLSearchParams(location.search).get('view') || 'catalog';
showView(requestedView);

window.showView = showView;
