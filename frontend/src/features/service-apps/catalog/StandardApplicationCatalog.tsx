import { useEffect, useState } from 'react';
import {
    AppstoreOutlined,
    ArrowLeftOutlined,
    ArrowRightOutlined,
    CopyOutlined,
    ReloadOutlined,
    SearchOutlined,
} from '@ant-design/icons';
import {
    Button,
    Empty,
    Form,
    Input,
    Modal,
    Pagination,
    Spin,
    Tag,
} from 'antd';
import { Alert, toast, useAccess } from '../../../shared/components/ui';
import { copyApplication, listApplications } from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationPage,
    type ApplicationSummary,
} from '../contracts';
import { say } from '../labels';

interface Props {
    onNavigate: (path: string) => void;
}

interface CopyValues {
    key: string;
    name: string;
}

const EXAMPLE_KEY_PREFIX = 'example-';

function StandardApplicationCard({
    application,
    admin,
    onOpen,
    onCopy,
}: {
    application: ApplicationSummary;
    admin: boolean;
    onOpen: () => void;
    onCopy: () => void;
}) {
    return <article className="sa-standard-card">
        <div className="sa-standard-card-top">
            <span className="sa-app-icon"><AppstoreOutlined/></span>
            <Tag color="purple">{say('标准案例')}</Tag>
        </div>
        <h3>{application.name}</h3>
        <p>{application.description || say('尚未填写应用描述')}</p>
        <div className="sa-app-numbers">
            <span><strong>{application.skill_count}</strong><small>{say('技能')}</small></span>
            <span><strong>{application.connection_count}</strong><small>{say('连接')}</small></span>
            <span>
                <strong>{application.published_version ? `v${application.published_version}` : '—'}</strong>
                <small>{say('当前版本')}</small>
            </span>
        </div>
        <div className="sa-standard-card-actions">
            <Button icon={<ArrowRightOutlined/>} onClick={onOpen}>
                {say('查看详情')}
            </Button>
            <Button
                type="primary"
                icon={<CopyOutlined/>}
                disabled={!admin}
                onClick={onCopy}
            >
                {say('复制为我的应用')}
            </Button>
        </div>
    </article>;
}

export function StandardApplicationCatalog({ onNavigate }: Props) {
    const { admin } = useAccess();
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [version, setVersion] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [data, setData] = useState<ApplicationPage>({
        items: [],
        total: 0,
        page: 1,
        page_size: DEFAULT_PAGE_SIZE,
    });
    const [copyTarget, setCopyTarget] = useState<ApplicationSummary | null>(null);
    const [copyBusy, setCopyBusy] = useState(false);
    const [copyForm] = Form.useForm<CopyValues>();

    useEffect(() => {
        setPage(1);
    }, [pageSize]);

    useEffect(() => {
        const controller = new AbortController();
        const timer = window.setTimeout(async () => {
            setLoading(true);
            setError('');
            try {
                const result = await listApplications({
                    page,
                    pageSize,
                    origin: 'example',
                    query: query.trim(),
                    archived: false,
                });
                if (!controller.signal.aborted) setData(result);
            } catch (cause) {
                if (!controller.signal.aborted) {
                    setError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        }, query ? 250 : 0);
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [page, pageSize, query, version]);

    function openCopy(application: ApplicationSummary) {
        const baseKey = application.key.startsWith(EXAMPLE_KEY_PREFIX)
            ? application.key.slice(EXAMPLE_KEY_PREFIX.length)
            : application.key;
        setCopyTarget(application);
        copyForm.setFieldsValue({
            key: `${baseKey.slice(0, 59)}-copy`,
            name: `${application.name} ${say('副本')}`,
        });
    }

    async function submitCopy() {
        if (!copyTarget) return;
        const values = await copyForm.validateFields();
        setCopyBusy(true);
        try {
            const copied = await copyApplication(copyTarget.key, {
                key: values.key.trim(),
                name: values.name.trim(),
            });
            setCopyTarget(null);
            toast.success(say('已复制'));
            onNavigate(`/service-apps/${copied.key}`);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('复制失败'));
        } finally {
            setCopyBusy(false);
        }
    }

    return <div className="sa-catalog sa-standards-catalog">
        <header className="sa-catalog-hero sa-standards-hero">
            <div>
                <span className="sa-eyebrow">{say('标准案例库')}</span>
                <h2>{say('标准案例')}</h2>
                <p>{say('标准案例由平台维护，复制后可独立编辑，修改不会影响原始案例。')}</p>
            </div>
            <div className="sa-hero-actions">
                <Button
                    icon={<ArrowLeftOutlined/>}
                    onClick={() => onNavigate('/service-apps')}
                >
                    {say('返回服务应用')}
                </Button>
                <Button
                    icon={<ReloadOutlined/>}
                    onClick={() => setVersion(value => value + 1)}
                >
                    {say('刷新')}
                </Button>
            </div>
        </header>

        <section className="sa-catalog-section-head">
            <div>
                <span className="sa-eyebrow">CURATED EXAMPLES</span>
                <h3>{say('标准案例')}</h3>
                <p>{say('共 {{v0}} 个标准案例', { v0: data.total })}</p>
            </div>
            <div className="sa-catalog-toolbar">
                <Input
                    allowClear
                    aria-label={say('搜索应用名称、标识或描述')}
                    prefix={<SearchOutlined/>}
                    placeholder={say('搜索应用名称、标识或描述')}
                    value={query}
                    onChange={event => {
                        setQuery(event.target.value);
                        setPage(1);
                    }}
                />
            </div>
        </section>

        <Alert error={error}/>

        {loading
            ? <div className="sa-loading"><Spin/></div>
            : data.items.length === 0
                ? <Empty description={query
                    ? say('没有匹配的服务应用')
                    : say('暂无标准案例')}/>
                : <div className="sa-standard-grid">
                    {data.items.map(application => <StandardApplicationCard
                        key={application.id || application.key}
                        application={application}
                        admin={admin}
                        onOpen={() => onNavigate(`/service-apps/${application.key}`)}
                        onCopy={() => openCopy(application)}
                    />)}
                </div>}

        <div className="sa-pagination-bar">
            <Pagination
                current={page}
                pageSize={pageSize}
                total={data.total}
                showSizeChanger
                pageSizeOptions={[10, 20, 50]}
                hideOnSinglePage={false}
                showTotal={(itemTotal, range) =>
                    `${range[0]}-${range[1]} / ${itemTotal} ${say('标准案例')}`
                }
                onChange={(nextPage, nextSize) => {
                    setPage(nextPage);
                    setPageSize(nextSize);
                }}
            />
        </div>

        <Modal
            open={Boolean(copyTarget)}
            title={say('复制为我的应用')}
            okText={say('复制')}
            cancelText={say('取消')}
            confirmLoading={copyBusy}
            destroyOnHidden
            onOk={() => void submitCopy()}
            onCancel={() => setCopyTarget(null)}
        >
            <p className="sa-modal-lead">
                {say('复制后得到独立可编辑应用，修改不会影响标准案例。')}
            </p>
            <Form<CopyValues>
                form={copyForm}
                layout="vertical"
                requiredMark={false}
            >
                <Form.Item
                    name="name"
                    label={say('应用名称')}
                    rules={[{ required: true, message: say('请输入名称') }]}
                >
                    <Input maxLength={100}/>
                </Form.Item>
                <Form.Item
                    name="key"
                    label={say('应用标识')}
                    rules={[
                        { required: true, message: say('请输入应用标识') },
                        {
                            pattern: /^[a-z][a-z0-9-]{1,63}$/,
                            message: say('应用标识只能使用小写字母、数字和短横线'),
                        },
                    ]}
                >
                    <Input className="mono" maxLength={64}/>
                </Form.Item>
            </Form>
        </Modal>
    </div>;
}
