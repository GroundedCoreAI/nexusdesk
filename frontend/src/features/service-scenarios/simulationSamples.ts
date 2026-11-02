import type { ServiceScenarioSummary } from '../../shared/api/client';
import { objectTypeLabel } from './scenarioConfig';

export interface SimulatedBusinessObject {
  id: string;
  type: string;
  status: string;
  label: string;
  productName: string;
  amount: number;
  orderedAt: string;
  logisticsStatus: string;
  tone: 'purple' | 'amber';
  facts: Record<string, unknown>;
}

function firstStatus(type: string) {
  if (type === 'invoice') return '可开票';
  if (type === 'refund') return '处理中';
  if (type === 'member') return '生效中';
  return '运输中';
}

function secondStatus(type: string) {
  if (type === 'invoice') return '已开票';
  if (type === 'refund') return '已到账';
  if (type === 'member') return '有效';
  return '已完成';
}

export function simulatedBusinessObjects(
  scenario?: ServiceScenarioSummary | null,
): SimulatedBusinessObject[] {
  const type = scenario?.config.object?.type || 'order';
  const typeLabel = objectTypeLabel(type);
  const firstStatusValue = firstStatus(type);
  const secondStatusValue = secondStatus(type);
  const products = type === 'order'
    ? ['云朵咖啡机', '降噪蓝牙耳机']
    : [`${typeLabel} A`, `${typeLabel} B`];

  return [
    {
      id: `SIM-${type.toUpperCase()}-20261102`,
      type,
      status: firstStatusValue,
      label: products[0],
      productName: products[0],
      amount: 268,
      orderedAt: '2026-10-28 14:30',
      logisticsStatus: '运输中',
      tone: 'purple',
      facts: {
        status: firstStatusValue,
        created_at: '2026-10-28 14:30',
        amount: 268,
        items: [{ title: products[0] }],
        logistics: { status: '运输中', latest: '快件已到达上海转运中心' },
        invoice: { status: '可开票', title: '个人' },
      },
    },
    {
      id: `SIM-${type.toUpperCase()}-20261018`,
      type,
      status: secondStatusValue,
      label: products[1],
      productName: products[1],
      amount: 129,
      orderedAt: '2026-10-18 09:06',
      logisticsStatus: '已签收',
      tone: 'amber',
      facts: {
        status: secondStatusValue,
        created_at: '2026-10-18 09:06',
        amount: 129,
        items: [{ title: products[1] }],
        logistics: { status: '已签收', latest: '快件已由本人签收' },
        invoice: { status: '已开票', title: '个人' },
      },
    },
  ];
}
