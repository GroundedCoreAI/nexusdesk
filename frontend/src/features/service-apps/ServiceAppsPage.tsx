import { Alert, Button } from 'antd';
import { ApplicationCatalog } from './catalog/ApplicationCatalog';
import { StandardApplicationCatalog } from './catalog/StandardApplicationCatalog';
import { ApplicationDetail } from './detail/ApplicationDetail';
import { say } from './labels';
import './service-apps.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
}

export function ServiceAppsPage({ route, onNavigate }: Props) {
    if (route === '/service-apps') {
        return <ApplicationCatalog onNavigate={onNavigate}/>;
    }
    if (route === '/service-apps/standards') {
        return <StandardApplicationCatalog onNavigate={onNavigate}/>;
    }
    if (/^\/service-apps\/[a-z0-9-]+(?:\/(?:overview|agent|experience|skills|rules|conversations|release))?$/.test(route)) {
        return <ApplicationDetail
            route={route}
            onNavigate={onNavigate}
        />;
    }
    return <RemovedRoute onNavigate={onNavigate}/>;
}

function RemovedRoute({
    onNavigate,
}: Pick<Props, 'onNavigate'>) {
    return <div className="sa-not-found">
        <Alert
            type="error"
            showIcon
            message={say('页面不存在')}
            description={say('该服务应用页面不存在或已移除。')}
        />
        <Button onClick={() => onNavigate('/service-apps')}>
            {say('返回应用列表')}
        </Button>
    </div>;
}
