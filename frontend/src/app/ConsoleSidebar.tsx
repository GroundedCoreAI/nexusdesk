import { useEffect, useState, type ReactNode } from 'react';
import { Button, Dropdown, Tooltip } from 'antd';
import {
  AccountBookOutlined,
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BookOutlined,
  CheckOutlined,
  CheckSquareOutlined,
  CodeOutlined,
  CustomerServiceOutlined,
  DeploymentUnitOutlined,
  DollarOutlined,
  DownOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  FundOutlined,
  HistoryOutlined,
  HomeOutlined,
  IdcardOutlined,
  LineChartOutlined,
  LinkOutlined,
  LockOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  NodeIndexOutlined,
  PartitionOutlined,
  RightOutlined,
  RobotOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { t } from '../i18n';
import { BrandMark } from '../shared/components/BrandMark';

export interface SidebarExtensionGroup {
  title: string;
  ids: string[];
}

interface ConsoleSidebarProps {
  page: string;
  role: string;
  collapsed: boolean;
  mobile: boolean;
  extensionGroups: SidebarExtensionGroup[];
  labelFor: (id: string) => string;
  onNavigate: (id: string) => void;
  onCollapsedChange: (collapsed: boolean) => void;
}

interface NavLeaf {
  id: string;
  label: string;
  icon: ReactNode;
  planned?: boolean;
  children?: never;
}

interface NavBranch {
  id: string;
  label: string;
  icon: ReactNode;
  children: NavLeaf[];
}

type NavItem = NavLeaf | NavBranch;

interface NavSection {
  title?: string;
  items: NavItem[];
}

const businesses = () => [
  {
    id: 'customer-service',
    name: t('AI 客服'),
    description: t('会话、工单与客户服务'),
    icon: <CustomerServiceOutlined />,
    available: true,
  },
  {
    id: 'finance',
    name: t('AI 财务运营'),
    description: t('智能财务处理'),
    icon: <AccountBookOutlined />,
    available: false,
  },
  {
    id: 'sales',
    name: t('AI 销售'),
    description: t('挖掘更多商机'),
    icon: <LineChartOutlined />,
    available: false,
  },
  {
    id: 'development',
    name: t('AI 研发'),
    description: t('加速产品交付'),
    icon: <CodeOutlined />,
    available: false,
  },
];

function BusinessSwitcher({ collapsed }: { collapsed: boolean }) {
  const items = businesses();
  const current = items[0];
  return (
    <Dropdown
      trigger={['click']}
      placement={collapsed ? 'bottomLeft' : 'bottom'}
      overlayClassName="business-switcher-dropdown"
      dropdownRender={menu => (
        <div className="business-switcher-menu">
          <div className="business-switcher-menu-title">{t('切换业务')}</div>
          {menu}
        </div>
      )}
      menu={{
        items: items.map(business => ({
          key: business.id,
          disabled: !business.available,
          label: (
            <div className="business-option">
              <span className="business-option-icon">{business.icon}</span>
              <span className="business-option-copy">
                <strong>{business.name}</strong>
                <small>{business.description}</small>
              </span>
              {business.available
                ? <CheckOutlined className="business-option-check" aria-hidden />
                : <span className="business-option-status">{t('待接入')}</span>}
            </div>
          ),
        })),
      }}
    >
      <Button
        type="text"
        className="business-switcher"
        aria-label={`${t('切换业务')}：${current.name}`}
      >
        <span className="business-switcher-icon">{current.icon}</span>
        <span className="business-switcher-copy">
          <small className="business-switcher-eyebrow">{t('当前业务应用')}</small>
          <strong>{current.name}</strong>
          <small>{t('当前业务应用')}</small>
        </span>
        <DownOutlined className="business-switcher-arrow" aria-hidden />
      </Button>
    </Dropdown>
  );
}

export function ConsoleSidebar({
  page,
  role,
  collapsed,
  mobile,
  extensionGroups,
  labelFor,
  onNavigate,
  onCollapsedChange,
}: ConsoleSidebarProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const extensionIds = extensionGroups.flatMap(group => group.ids);
  const leaf = (id: string, icon: ReactNode, label?: string): NavLeaf => ({
    id,
    icon,
    label: label ?? labelFor(id),
  });
  const planned = (id: string, icon: ReactNode, label: string): NavLeaf => ({
    id,
    icon,
    label,
    planned: true,
  });
  const sections: NavSection[] = [
    {
      items: [leaf('overview', <HomeOutlined />, t('工作台'))],
    },
    {
      title: t('业务工作'),
      items: [
        leaf('conversations', <MessageOutlined />),
        leaf('tickets', <FileTextOutlined />),
        leaf('memory', <IdcardOutlined />),
        planned('business-analytics', <FundOutlined />, t('数据分析')),
        {
          id: 'service-policy',
          label: t('服务策略'),
          icon: <SafetyOutlined />,
          children: [
            leaf('service-apps', <AppstoreOutlined />),
            leaf('handoff', <CustomerServiceOutlined />),
          ],
        },
      ],
    },
    {
      title: t('平台工作空间'),
      items: [
        {
          id: 'ai-employees',
          label: t('AI 员工'),
          icon: <RobotOutlined />,
          children: [
            leaf('agents', <RobotOutlined />),
            planned('employee-teams', <TeamOutlined />, t('员工团队')),
            planned('agent-releases', <DeploymentUnitOutlined />, t('发布与版本')),
          ],
        },
        {
          id: 'tasks',
          label: t('任务中心'),
          icon: <AuditOutlined />,
          children: extensionIds.length
            ? extensionIds.map(id => leaf(id, <AuditOutlined />))
            : [
              planned('task-list', <UnorderedListOutlined />, t('全部任务')),
              planned('task-runs', <HistoryOutlined />, t('执行记录')),
              planned('task-approvals', <CheckSquareOutlined />, t('审批与待办')),
            ],
        },
        {
          id: 'resources',
          label: t('资源中心'),
          icon: <BookOutlined />,
          children: [
            leaf('skills', <ThunderboltOutlined />, t('Skill 能力库')),
            leaf('knowledge', <BookOutlined />),
            leaf('tools', <ToolOutlined />),
            leaf('models', <ApiOutlined />),
            planned('workflows', <PartitionOutlined />, t('Workflow')),
            planned('connectors', <LinkOutlined />, t('Connector')),
          ],
        },
        {
          id: 'operations',
          label: t('运营中心'),
          icon: <LineChartOutlined />,
          children: [
            leaf('evaluation', <ExperimentOutlined />, t('质量评估')),
            leaf('observability', <AuditOutlined />, t('运行监控与审计')),
            planned('cost-analytics', <DollarOutlined />, t('成本分析')),
          ],
        },
      ],
    },
    {
      items: [
        leaf('open-platform', <ApiOutlined />),
        {
          id: 'system',
          label: t('系统管理'),
          icon: <SettingOutlined />,
          children: [
            leaf('access', <SafetyOutlined />),
            ...(role === 'admin'
              ? [
                leaf('members', <TeamOutlined />),
                leaf('roles', <SafetyOutlined />),
                leaf('extensions', <NodeIndexOutlined />, t('插件与扩展')),
              ]
              : []),
            leaf('security', <LockOutlined />),
          ],
        },
      ],
    },
  ];
  const branches = sections.flatMap(section => section.items).filter(
    (item): item is NavBranch => Boolean(item.children),
  );
  const activeBranch = branches.find(branch => branch.children.some(child => child.id === page));

  useEffect(() => {
    if (!activeBranch) return;
    setExpanded(previous => previous.has(activeBranch.id)
      ? previous
      : new Set(previous).add(activeBranch.id));
  }, [activeBranch?.id]);

  function toggleBranch(branch: NavBranch) {
    if (collapsed) onCollapsedChange(false);
    setExpanded(previous => {
      const next = new Set(previous);
      if (next.has(branch.id) && !collapsed) next.delete(branch.id);
      else next.add(branch.id);
      return next;
    });
  }

  function renderLeaf(item: NavLeaf, nested = false) {
    const selected = page === item.id;
    const button = (
      <Button
        block
        type="text"
        icon={item.icon}
        className={`${selected ? 'nav-selected' : ''} ${nested ? 'nav-child' : ''} ${item.planned ? 'nav-planned' : ''}`}
        aria-label={item.label}
        aria-current={selected ? 'page' : undefined}
        disabled={item.planned}
        onClick={() => {
          if (item.planned) return;
          onNavigate(item.id);
          if (mobile) onCollapsedChange(true);
        }}
      >
        <span className="nav-label">{item.label}</span>
        {item.planned && <span className="nav-status">{t('规划中')}</span>}
      </Button>
    );
    return (
      <div className={`console-nav-item nav-item-${item.id}`} key={item.id}>
        {collapsed ? <Tooltip title={item.label} placement="right">{button}</Tooltip> : button}
      </div>
    );
  }

  function renderBranch(branch: NavBranch) {
    const open = !collapsed && expanded.has(branch.id);
    const active = activeBranch?.id === branch.id;
    const button = (
      <Button
        block
        type="text"
        icon={branch.icon}
        className={`nav-parent ${active ? 'nav-parent-selected' : ''}`}
        aria-label={branch.label}
        aria-expanded={open}
        aria-controls={`sidebar-group-${branch.id}`}
        onClick={() => toggleBranch(branch)}
      >
        <span className="nav-label">{branch.label}</span>
        <RightOutlined className={`nav-parent-arrow ${open ? 'is-open' : ''}`} aria-hidden />
      </Button>
    );
    return (
      <div className={`console-nav-item nav-item-${branch.id}`} key={branch.id}>
        {collapsed ? <Tooltip title={branch.label} placement="right">{button}</Tooltip> : button}
        {!collapsed && open && (
          <div className="nav-children" id={`sidebar-group-${branch.id}`}>
            {branch.children.map(child => renderLeaf(child, true))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="console-sidebar-inner">
      <div className="console-brand"><BrandMark /></div>
      <BusinessSwitcher collapsed={collapsed} />
      <nav aria-label={t('主导航')} className="console-nav">
        {sections.map((section, sectionIndex) => (
          <div className="console-nav-section" key={section.title ?? sectionIndex}>
            {section.title && <div className="nav-group-title">{section.title}</div>}
            {section.items.map(item => item.children ? renderBranch(item) : renderLeaf(item))}
          </div>
        ))}
      </nav>
      <div className="console-sidebar-footer">
        <div className="console-sidebar-edition">
          <span>{t('企业版')}</span>
          <small>v2.0.0</small>
        </div>
        <Button
          type="text"
          className="console-sidebar-collapse"
          aria-label={collapsed ? t('展开导航') : t('收起导航')}
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={() => onCollapsedChange(!collapsed)}
        />
      </div>
    </div>
  );
}
