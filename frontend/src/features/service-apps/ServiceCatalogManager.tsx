import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Input, Modal, Popconfirm, Select, Tag } from 'antd';
import {
    ArrowDownOutlined,
    ArrowUpOutlined,
    DeleteOutlined,
    MergeCellsOutlined,
    PlusOutlined,
} from '@ant-design/icons';
import type {
    ApplicationServiceCategory,
    ServiceApplicationSummary,
    ServiceScenarioSummary,
} from '../../shared/api/client';
import { updateServiceCatalog } from '../../shared/api/client';
import { effectiveServiceCategories } from '../service-scenarios/scenarioConfig';

interface Props {
    open: boolean;
    application: ServiceApplicationSummary;
    scenes: ServiceScenarioSummary[];
    onClose: () => void;
    onSaved: (updated: ServiceApplicationSummary) => void;
}

interface CatalogRow {
    uid: string;
    originalName: string | null;
    name: string;
    sceneCount: number;
}

function rowKey(row: CatalogRow) {
    return row.originalName || row.uid;
}

function uid() {
    return `category-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function ServiceCatalogManager({
    open,
    application,
    scenes,
    onClose,
    onSaved,
}: Props) {
    const [rows, setRows] = useState<CatalogRow[]>([]);
    const [aliases, setAliases] = useState<Record<string, string>>({});
    const [mergeSourceUid, setMergeSourceUid] = useState('');
    const [mergeTargetUid, setMergeTargetUid] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const signature = useMemo(
        () => JSON.stringify({
            categories: application.config.service_categories || [],
            scenes: scenes.map(scene => [scene.key, scene.config.category || scene.config.domain || '其他服务']),
        }),
        [application.config.service_categories, scenes],
    );

    useEffect(() => {
        if (!open) return;
        const categories = effectiveServiceCategories(application, scenes);
        setRows(categories.map(category => ({
            uid: uid(),
            originalName: category.name,
            name: category.name,
            sceneCount: category.scenarioCount,
        })));
        setAliases({});
        setMergeSourceUid('');
        setMergeTargetUid('');
        setError('');
    }, [application, open, scenes, signature]);

    const mergeSource = rows.find(row => row.uid === mergeSourceUid);
    const mergeTargets = rows.filter(row => row.uid !== mergeSourceUid);

    function updateName(uidValue: string, name: string) {
        setRows(current => current.map(row => row.uid === uidValue ? { ...row, name } : row));
        setError('');
    }

    function move(index: number, offset: number) {
        const nextIndex = index + offset;
        if (nextIndex < 0 || nextIndex >= rows.length) return;
        setRows(current => {
            const next = [...current];
            [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
            return next;
        });
    }

    function addCategory() {
        setRows(current => [
            ...current,
            {
                uid: uid(),
                originalName: null,
                name: '',
                sceneCount: 0,
            },
        ]);
        setError('');
    }

    function removeCategory(row: CatalogRow) {
        setRows(current => current.filter(item => item.uid !== row.uid));
        setError('');
    }

    function openMerge(row: CatalogRow) {
        const target = rows.find(item => item.uid !== row.uid);
        setMergeSourceUid(row.uid);
        setMergeTargetUid(target?.uid || '');
        setError('');
    }

    function mergeCategory() {
        const source = rows.find(row => row.uid === mergeSourceUid);
        const target = rows.find(row => row.uid === mergeTargetUid);
        if (!source || !target) {
            setError('请选择要合并到的目标分类。');
            return;
        }
        setAliases(current => ({
            ...current,
            [rowKey(source)]: rowKey(target),
        }));
        setRows(current => current
            .filter(row => row.uid !== source.uid)
            .map(row => row.uid === target.uid
                ? { ...row, sceneCount: row.sceneCount + source.sceneCount }
                : row));
        setMergeSourceUid('');
        setMergeTargetUid('');
    }

    async function save() {
        const names = rows.map(row => row.name.trim());
        if (names.some(name => !name)) {
            setError('分类名称不能为空。');
            return;
        }
        const duplicate = names.find((name, index) => names.indexOf(name) !== index);
        if (duplicate) {
            setError(`分类名称「${duplicate}」重复，请先合并或重命名。`);
            return;
        }

        const categories: ApplicationServiceCategory[] = names.map((name, index) => ({
            name,
            order: (index + 1) * 10,
        }));
        const currentRows = new Map(rows.map(row => [rowKey(row), row]));
        const changes: Record<string, string> = {};
        for (const row of rows) {
            if (row.originalName && row.name.trim() !== row.originalName) {
                changes[row.originalName] = row.name.trim();
            }
        }
        for (const [source, rawTarget] of Object.entries(aliases)) {
            let target = rawTarget;
            const visited = new Set<string>();
            while (aliases[target]) {
                if (visited.has(target)) {
                    setError('合并关系存在循环，请重新调整服务目录。');
                    return;
                }
                visited.add(target);
                target = aliases[target];
            }
            const targetName = currentRows.get(target)?.name.trim();
            if (!targetName) {
                setError('合并目标已被删除，请重新选择。');
                return;
            }
            changes[source] = targetName;
        }

        setBusy(true);
        setError('');
        try {
            const updated = await updateServiceCatalog(
                application.key,
                categories,
                changes,
                application.revision,
            );
            onSaved(updated);
            onClose();
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '保存服务目录失败');
        }
        finally {
            setBusy(false);
        }
    }

    return <>
        <Modal
            open={open}
            title="服务目录"
            width={720}
            okText="保存目录"
            cancelText="取消"
            confirmLoading={busy}
            destroyOnHidden
            onOk={() => void save()}
            onCancel={() => {
                if (!busy) onClose();
            }}
        >
            <p className="sa-catalog-manager-intro">
                服务目录由当前应用统一维护。新建和编辑场景只能从这里选择分类；重命名、合并会在同一事务内同步场景草稿。
            </p>
            {error && <Alert type="error" showIcon message={error}/>}
            <div className="sa-catalog-manager-list">
                {rows.map((row, index) => <div className="sa-catalog-manager-row" key={row.uid}>
                    <span className="sa-catalog-manager-index">{String(index + 1).padStart(2, '0')}</span>
                    <Input
                        aria-label={`分类名称 ${row.originalName || index + 1}`}
                        value={row.name}
                        maxLength={100}
                        placeholder="例如：订单服务"
                        onChange={event => updateName(row.uid, event.target.value)}
                    />
                    <Tag>{row.sceneCount} 个场景</Tag>
                    <div className="sa-catalog-manager-actions">
                        <Button
                            type="text"
                            size="small"
                            icon={<ArrowUpOutlined/>}
                            aria-label={`上移 ${row.name || index + 1}`}
                            disabled={index === 0 || busy}
                            onClick={() => move(index, -1)}
                        />
                        <Button
                            type="text"
                            size="small"
                            icon={<ArrowDownOutlined/>}
                            aria-label={`下移 ${row.name || index + 1}`}
                            disabled={index === rows.length - 1 || busy}
                            onClick={() => move(index, 1)}
                        />
                        <Button
                            type="text"
                            size="small"
                            icon={<MergeCellsOutlined/>}
                            aria-label={`合并 ${row.name || index + 1}`}
                            disabled={row.sceneCount === 0 || rows.length < 2 || busy}
                            onClick={() => openMerge(row)}
                        />
                        {row.sceneCount === 0
                            ? <Popconfirm
                                title="删除这个空分类？"
                                okText="删除"
                                cancelText="取消"
                                disabled={busy}
                                onConfirm={() => removeCategory(row)}
                            >
                                <Button
                                    type="text"
                                    danger
                                    size="small"
                                    icon={<DeleteOutlined/>}
                                    aria-label={`删除 ${row.name || index + 1}`}
                                />
                            </Popconfirm>
                            : null}
                    </div>
                </div>)}
                {!rows.length && <div className="sa-catalog-manager-empty">
                    还没有服务分类。先新增分类，再创建场景。
                </div>}
            </div>
            <Button type="dashed" block icon={<PlusOutlined/>} disabled={busy} onClick={addCategory}>
                新增分类
            </Button>
            <p className="sa-muted-note" style={{ marginTop: 12 }}>
                分类下仍有场景时不能直接删除，请先合并到其他分类。合并会迁移场景草稿并保留应用 revision 校验。
            </p>
        </Modal>

        <Modal
            open={!!mergeSourceUid}
            title="合并服务分类"
            okText="确认合并"
            cancelText="取消"
            width={460}
            destroyOnHidden
            onOk={mergeCategory}
            onCancel={() => {
                setMergeSourceUid('');
                setMergeTargetUid('');
            }}
        >
            <p className="sa-catalog-manager-intro">
                将「{mergeSource?.name}」下的 {mergeSource?.sceneCount || 0} 个场景迁移到目标分类，源分类会被移除。
            </p>
            <Select
                aria-label="合并目标分类"
                style={{ width: '100%' }}
                value={mergeTargetUid || undefined}
                placeholder="选择目标分类"
                options={mergeTargets.map(row => ({
                    value: row.uid,
                    label: row.name || '未命名分类',
                }))}
                onChange={setMergeTargetUid}
            />
        </Modal>
    </>;
}
