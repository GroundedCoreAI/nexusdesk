import { useEffect, useState } from 'react';
import {
    ApiOutlined,
    LockOutlined,
    SaveOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Drawer,
    Form,
    Input,
    InputNumber,
    Select,
    Space,
    Tabs,
    Tag,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import {
    createConnection,
    saveCredentials,
    testConnection,
    updateConnection,
} from '../api';
import type {
    ApplicationConnection,
    ConnectionInput,
    CredentialInput,
} from '../contracts';
import { authKindLabel, connectionKindLabel, say } from '../labels';

interface Values {
    key: string;
    name: string;
    executor_kind: ConnectionInput['executor_kind'];
    endpoint?: string;
    method: ConnectionInput['method'];
    auth_kind: ConnectionInput['auth_kind'];
    timeout_seconds: number;
    max_response_bytes: number;
    public_headers_json: string;
    config_json: string;
    credential_token?: string;
    credential_header?: string;
    credential_headers_json?: string;
}

function pretty(value: Record<string, unknown>) {
    return Object.keys(value).length ? JSON.stringify(value, null, 2) : '{}';
}

function parseObject(text: string | undefined, field: string) {
    try {
        const value = JSON.parse(text || '{}') as unknown;
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(field);
        return value as Record<string, unknown>;
    } catch {
        throw new Error(field);
    }
}

export function ConnectionDrawer({
    open,
    applicationKey,
    connection,
    readOnly,
    onClose,
    onSaved,
}: {
    open: boolean;
    applicationKey: string;
    connection: ApplicationConnection | null;
    readOnly: boolean;
    onClose: () => void;
    onSaved: (connection: ApplicationConnection) => void;
}) {
    const [form] = Form.useForm<Values>();
    const [activeTab, setActiveTab] = useState('basic');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const authKind = Form.useWatch('auth_kind', form);
    const executorKind = Form.useWatch('executor_kind', form);

    useEffect(() => {
        if (!open) return;
        setActiveTab('basic');
        setError('');
        form.resetFields();
        form.setFieldsValue({
            key: connection?.key || '',
            name: connection?.name || '',
            executor_kind: connection?.executor_kind || 'http',
            endpoint: connection?.endpoint || '',
            method: connection?.method || 'GET',
            auth_kind: connection?.auth_kind || 'none',
            timeout_seconds: connection?.timeout_seconds || 10,
            max_response_bytes: connection?.max_response_bytes || 16000,
            public_headers_json: pretty(connection?.public_headers || {}),
            config_json: pretty(connection?.config || {}),
            credential_token: '',
            credential_header: '',
            credential_headers_json: '',
        });
    }, [connection, form, open]);

    function credentialInput(values: Values): CredentialInput | null {
        if (values.auth_kind === 'none') return { type: 'none' };
        if (values.auth_kind === 'bearer') {
            return values.credential_token?.trim()
                ? { type: 'bearer', token: values.credential_token.trim() }
                : null;
        }
        if (values.auth_kind === 'api_key') {
            return values.credential_token?.trim() && values.credential_header?.trim()
                ? {
                    type: 'api_key',
                    header_name: values.credential_header.trim(),
                    token: values.credential_token.trim(),
                }
                : null;
        }
        return values.credential_headers_json?.trim()
            ? {
                type: 'custom',
                headers: parseObject(values.credential_headers_json, say('凭据')),
            } as CredentialInput
            : null;
    }

    async function persist(): Promise<ApplicationConnection> {
        const values = await form.validateFields();
        let publicHeaders: Record<string, string>;
        let config: Record<string, unknown>;
        try {
            const parsedHeaders = parseObject(values.public_headers_json, say('公开请求头'));
            publicHeaders = Object.fromEntries(
                Object.entries(parsedHeaders).map(([key, value]) => [key, String(value)]),
            );
        } catch {
            form.setFields([{ name: 'public_headers_json', errors: [say('配置必须是 JSON 对象')] }]);
            throw new Error(say('配置必须是 JSON 对象'));
        }
        try {
            config = parseObject(values.config_json, say('配置 JSON'));
        } catch {
            form.setFields([{ name: 'config_json', errors: [say('配置必须是 JSON 对象')] }]);
            throw new Error(say('配置必须是 JSON 对象'));
        }
        const input: ConnectionInput = {
            key: values.key.trim(),
            name: values.name.trim(),
            executor_kind: values.executor_kind,
            endpoint: (values.endpoint || '').trim() || null,
            method: values.method,
            public_headers: publicHeaders,
            auth_kind: values.auth_kind,
            timeout_seconds: values.timeout_seconds,
            max_response_bytes: values.max_response_bytes,
            config,
        };
        const saved = connection
            ? await updateConnection(applicationKey, connection.key, input, connection.revision)
            : (await createConnection(applicationKey, input)).connection;
        const credentials = credentialInput(values);
        if (credentials && credentials.type !== 'none') {
            await saveCredentials(applicationKey, saved.key, credentials);
            saved.credentials_configured = true;
        }
        return saved;
    }

    async function save() {
        setBusy(true);
        setError('');
        try {
            const saved = await persist();
            onSaved(saved);
            toast.success(say('已保存'));
            onClose();
        } catch (cause) {
            if (cause instanceof Error && cause.message) setError(cause.message);
        } finally {
            setBusy(false);
        }
    }

    async function saveAndTest() {
        setBusy(true);
        setError('');
        try {
            const saved = await persist();
            const result = await testConnection(applicationKey, saved.key);
            onSaved(saved);
            toast.success(result.status === 'passed'
                ? say('连接检测完成')
                : (result.message || say('调用失败')));
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    const basic = <div className="sa-drawer-form-grid">
        <Form.Item
            name="key"
            label={say('连接标识')}
            rules={[
                { required: true, message: say('请输入连接标识') },
                { pattern: /^[a-z][a-z0-9-]{1,63}$/, message: say('连接标识只能使用小写字母、数字和短横线') },
            ]}
        >
            <Input className="mono" disabled={Boolean(connection)} maxLength={64}/>
        </Form.Item>
        <Form.Item
            name="name"
            label={say('名称')}
            rules={[{ required: true, message: say('请输入名称') }]}
        >
            <Input maxLength={100}/>
        </Form.Item>
        <Form.Item
            name="executor_kind"
            label={say('执行器')}
            rules={[{ required: true }]}
        >
            <Select options={[
                { value: 'http', label: 'HTTP' },
                { value: 'internal', label: say('平台内置') },
                { value: 'human_queue', label: say('人工队列') },
            ]}/>
        </Form.Item>
        <Form.Item
            name="auth_kind"
            label={say('认证方式')}
            rules={[{ required: true }]}
        >
            <Select options={[
                { value: 'none', label: authKindLabel('none') },
                { value: 'bearer', label: authKindLabel('bearer') },
                { value: 'api_key', label: authKindLabel('api_key') },
                { value: 'custom', label: authKindLabel('custom') },
            ]}/>
        </Form.Item>
        {executorKind === 'http' && <>
            <Form.Item
                className="sa-form-span-2"
                name="endpoint"
                label={say('接口地址')}
                rules={[
                    { required: true, message: say('请输入接口地址') },
                    { type: 'url', message: say('请输入有效的接口地址') },
                ]}
            >
                <Input className="mono" placeholder="https://"/>
            </Form.Item>
            <Form.Item name="method" label={say('请求方法')}>
                <Select options={[
                    { value: 'GET', label: 'GET' },
                    { value: 'POST', label: 'POST' },
                ]}/>
            </Form.Item>
        </>}
        <Form.Item name="timeout_seconds" label={say('超时（秒）')}>
            <InputNumber min={1} max={60} className="sa-full-width"/>
        </Form.Item>
        <Form.Item name="max_response_bytes" label={say('响应大小上限')}>
            <InputNumber min={128} max={100000} step={128} className="sa-full-width"/>
        </Form.Item>
    </div>;

    const transport = <div className="sa-drawer-json-grid">
        <Form.Item name="public_headers_json" label={say('公开请求头 JSON')}>
            <Input.TextArea className="mono" rows={7} spellCheck={false}/>
        </Form.Item>
        <Form.Item name="config_json" label={say('配置 JSON')}>
            <Input.TextArea className="mono" rows={7} spellCheck={false}/>
        </Form.Item>
        <div className="sa-form-span-2">
            <Alert
                type="info"
                showIcon
                message={say('公开请求头不能包含 Authorization、Cookie 或 Token；敏感认证必须使用凭据。')}
            />
        </div>
    </div>;

    const credential = <div className="sa-drawer-credential">
        <Alert
            type="warning"
            showIcon
            icon={<LockOutlined/>}
            message={connection?.credentials_configured
                ? say('凭据已配置，保存后不再显示原文。留空保留现有凭据。')
                : say('密钥加密保存，保存后不再显示原文。')}
        />
        {authKind === 'bearer' && <Form.Item name="credential_token" label="Bearer Token">
            <Input.Password autoComplete="new-password" placeholder={say('输入新凭据')}/>
        </Form.Item>}
        {authKind === 'api_key' && <>
            <Form.Item name="credential_header" label={say('请求头名称')}>
                <Input className="mono" placeholder="X-API-Key"/>
            </Form.Item>
            <Form.Item name="credential_token" label={say('凭据')}>
                <Input.Password autoComplete="new-password" placeholder={say('输入新凭据')}/>
            </Form.Item>
        </>}
        {authKind === 'custom' && <Form.Item name="credential_headers_json" label={say('凭据请求头 JSON')}>
            <Input.TextArea className="mono" rows={6} spellCheck={false}/>
        </Form.Item>}
        {authKind === 'none' && <Tag color="green">{say('未认证')}</Tag>}
    </div>;

    return <Drawer
        open={open}
        width={720}
        title={connection ? `${say('编辑连接')} · ${connection.name}` : say('新建连接')}
        destroyOnHidden
        onClose={onClose}
        extra={<Space>
            <Button onClick={onClose}>{say('取消')}</Button>
            {!readOnly && <Button
                icon={<ThunderboltOutlined/>}
                loading={busy}
                onClick={() => void saveAndTest()}
            >
                {say('检测连接')}
            </Button>}
            {!readOnly && <Button
                type="primary"
                icon={<SaveOutlined/>}
                loading={busy}
                onClick={() => void save()}
            >
                {say('保存')}
            </Button>}
        </Space>}
    >
        {error && <Alert type="error" showIcon message={error}/>}
        <div className="sa-connection-summary">
            <div className="sa-overview-card-icon blue"><ApiOutlined/></div>
            <div>
                <strong>{connectionKindLabel(connection?.executor_kind || executorKind || 'http')}</strong>
                <span>{authKindLabel(connection?.auth_kind || authKind || 'none')}</span>
            </div>
            <Tag color={connection?.credentials_configured ? 'green' : 'gold'}>
                {connection?.credentials_configured ? say('凭据已配置') : say('凭据未配置')}
            </Tag>
        </div>
        <Form<Values>
            form={form}
            layout="vertical"
            requiredMark={false}
            disabled={readOnly}
        >
            <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                items={[
                    { key: 'basic', label: say('基本信息'), children: basic },
                    { key: 'transport', label: say('传输配置'), children: transport },
                    { key: 'credential', label: say('凭据'), children: credential },
                ]}
            />
        </Form>
    </Drawer>;
}
