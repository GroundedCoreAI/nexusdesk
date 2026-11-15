import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import { EmbedChat, HostedChat } from './features/open-platform/EmbedChat';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import zhTW from 'antd/locale/zh_TW';
import enUS from 'antd/locale/en_US';
import hiIN from 'antd/locale/hi_IN';
import { useTranslation } from 'react-i18next';
import { locale } from './i18n';
import { ToastHolder } from './shared/components/ui';
import './styles/global.css';
import './styles/console.css';
import './styles/design-system.css';
import {consoleTheme} from './styles/theme';

// Public chat surfaces live outside the console router: the widget runs in a
// host page's iframe, the hosted page is a link anyone can open.
function chatSurface() {
  if (location.pathname.startsWith('/embed/')) return <EmbedChat />;
  if (location.pathname.startsWith('/h/')) return <HostedChat />;
  return null;
}

function Root() { useTranslation(); const surface = chatSurface(); return <ConfigProvider locale={{'zh-CN':zhCN,'zh-TW':zhTW,en:enUS,hi:hiIN}[locale()]} theme={consoleTheme}><AntApp><ToastHolder/>{surface ?? <App />}</AntApp></ConfigProvider>; }
createRoot(document.getElementById('root')!).render(<StrictMode><Root /></StrictMode>);
