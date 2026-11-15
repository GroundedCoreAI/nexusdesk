import { Tag } from 'antd';
import type { ReadinessStatus } from '../contracts';
import { say, statusLabel } from '../labels';

const statusColor: Record<string, string> = {
    draft: 'gold',
    review: 'orange',
    published: 'green',
    offline: 'default',
};

export function StatusTag({ status }: { status: string }) {
    return <Tag color={statusColor[status]}>{statusLabel(status)}</Tag>;
}

export function ReadinessTag({ status }: { status: ReadinessStatus }) {
    const color = status === 'pass' ? 'green' : status === 'warning' ? 'gold' : 'red';
    const label = status === 'pass'
        ? say('通过')
        : status === 'warning'
            ? say('待处理')
            : say('阻止发布');
    return <Tag color={color}>{label}</Tag>;
}

export function CountTag({ label, value, color }: {
    label: string;
    value: number | string;
    color?: string;
}) {
    return <div className="sa-count-tag">
        <span>{label}</span>
        <strong style={{ color }}>{value}</strong>
    </div>;
}
