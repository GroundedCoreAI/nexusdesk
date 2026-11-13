import { useEffect, useState } from 'react';
import {
    CloseOutlined,
    HistoryOutlined,
    RollbackOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Popconfirm,
    Table,
    Tag,
    type TableColumnsType,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import { dateTime } from '../../../i18n/index';
import { listVersions, rollbackApplication } from '../api';
import {
    type ApplicationDetail,
    type ApplicationSummary,
    type ApplicationVersion,
    type ApplicationVersionPage,
} from '../contracts';
import { say } from '../labels';

const VERSION_PAGE_SIZE = 5;

export function VersionHistoryPanel({
    application,
    readOnly,
    onSaved,
    onClose,
}: {
    application: ApplicationDetail;
    readOnly: boolean;
    onSaved: (application: ApplicationSummary) => void;
    onClose: () => void;
}) {
    const [versions, setVersions] = useState<ApplicationVersionPage>({
        items: [],
        total: 0,
        page: 1,
        page_size: VERSION_PAGE_SIZE,
    });
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        listVersions(application.key, page, VERSION_PAGE_SIZE)
            .then(result => {
                if (active) setVersions(result);
            })
            .catch(cause => {
                if (active) {
                    setError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [
        application.draft_revision,
        application.key,
        application.published_version,
        page,
    ]);

    async function rollback(version: number) {
        setBusy(true);
        setError('');
        try {
            const summary = await rollbackApplication(
                application.key,
                version,
                application.draft_revision,
            );
            onSaved(summary);
            setPage(1);
            toast.success(say('已回滚'));
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    const columns: TableColumnsType<ApplicationVersion> = [
        {
            title: say('版本'),
            dataIndex: 'version',
            width: 140,
            render: (value, version) => <div className="sa-version-cell">
                <Tag color={version.current ? 'green' : 'default'}>v{value}</Tag>
                {version.current && <span>{say('当前发布')}</span>}
            </div>,
        },
        {
            title: say('来源'),
            dataIndex: 'source_version',
            width: 120,
            render: value => value
                ? <Tag>{say('回滚自')} v{value}</Tag>
                : <Tag>{say('直接发布')}</Tag>,
        },
        {
            title: say('发布时间'),
            dataIndex: 'created_at',
            width: 190,
            render: value => <span className="sa-version-history-date">
                {value ? dateTime(value) : '—'}
            </span>,
        },
        {
            title: say('操作'),
            key: 'actions',
            width: 120,
            render: (_, version) => version.current
                ? <span className="sa-version-history-current">{say('当前发布')}</span>
                : <Popconfirm
                    title={`${say('回滚')} v${version.version}?`}
                    description={say('回滚会生成一个新的最高版本，不修改历史版本。')}
                    disabled={readOnly || busy}
                    okText={say('回滚')}
                    cancelText={say('取消')}
                    onConfirm={() => void rollback(version.version)}
                >
                    <Button
                        type="text"
                        icon={<RollbackOutlined/>}
                        disabled={readOnly || busy}
                    >
                        {say('回滚')}
                    </Button>
                </Popconfirm>,
        },
    ];

    return <div className="sa-version-history">
        <div className="sa-version-history-head">
            <div className="sa-version-history-title">
                <h3>
                    <HistoryOutlined aria-hidden/>
                    {say('版本历史')}
                </h3>
                <p>{say('回滚会生成一个新的最高版本，不修改历史版本。')}</p>
            </div>
            <div className="sa-version-history-head-actions">
                <Tag color={application.published_version ? 'green' : 'default'}>
                    {application.published_version
                        ? `${say('当前发布')} v${application.published_version}`
                        : say('尚无发布版本')}
                </Tag>
                <Button
                    type="text"
                    icon={<CloseOutlined/>}
                    aria-label={say('关闭')}
                    onClick={onClose}
                />
            </div>
        </div>

        {error && <Alert
            className="sa-version-history-error"
            type="error"
            showIcon
            message={error}
        />}

        <Table<ApplicationVersion>
            className="sa-version-history-table"
            rowKey="id"
            columns={columns}
            dataSource={versions.items}
            loading={loading}
            size="middle"
            locale={{ emptyText: say('尚无发布版本') }}
            pagination={{
                current: page,
                pageSize: VERSION_PAGE_SIZE,
                total: versions.total,
                position: ['bottomRight'],
                hideOnSinglePage: true,
                showSizeChanger: false,
                onChange: setPage,
            }}
        />
    </div>;
}
