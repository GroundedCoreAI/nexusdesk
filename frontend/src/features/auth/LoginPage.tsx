import {useEffect, useMemo, useState} from 'react';
import {useTranslation} from 'react-i18next';
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Form,
  Input,
  Tabs,
} from 'antd';
import {
  AppstoreOutlined,
  ArrowRightOutlined,
  CloudServerOutlined,
  GithubOutlined,
  KeyOutlined,
  LockOutlined,
  RobotOutlined,
  SafetyOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {t} from '../../i18n';
import {LanguageSelector} from '../../i18n/LanguageSelector';
import {setToken} from '../../shared/api/client';
import {BrandMark} from '../../shared/components/BrandMark';
import {ssoLogin, type LoginProvider} from '../open-platform/SsoLogin';
import './login.css';

const REMEMBERED_USER_KEY = 'nexusdesk-remembered-user';

export function loginError(code:string) {
  if(code==='invalid_local_credentials') return t('账号或密码不正确');
  if(code==='local_login_rate_limited') return t('尝试次数过多，请在 15 分钟后重试');
  if(code==='new_password_must_differ') return t('新密码不能与原密码相同');
  if(code==='password_requires_12_to_128_characters') return t('密码需要 12–128 个字符');
  if(code==='workbench_access_pending') return t('身份已登记，请联系管理员分配工作台角色');
  return t('登录服务暂不可用，请稍后重试');
}

// Keep the existing development-only prefill behavior. Production builds do not
// contain deployment credentials unless VITE_PREFILL_LOGIN is explicitly set.
const prefillLogin = import.meta.env.DEV || import.meta.env.VITE_PREFILL_LOGIN === 'true';
const devCredentials = prefillLogin
  ? {
      username:String(import.meta.env.VITE_DEV_LOGIN_USER||'admin'),
      password:String(import.meta.env.VITE_DEV_LOGIN_PASSWORD||'nexusdesk'),
    }
  : {username:'',password:''};

const features = [
  {key:'agent', icon:<RobotOutlined/>, title:'AI Agent', caption:'智能协作'},
  {key:'open', icon:<AppstoreOutlined/>, title:'Open Source', caption:'开源开放'},
  {key:'host', icon:<CloudServerOutlined/>, title:'Self-Hosted', caption:'自主可控'},
  {key:'extend', icon:<SafetyOutlined/>, title:'Extensible', caption:'灵活扩展'},
];

export function LoginPage({complete, expired=false}:{complete:()=>void;expired?:boolean}) {
  useTranslation();
  const [tab,setTab]=useState('local');
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const [providers,setProviders]=useState<LoginProvider[]>([]);
  const [loading,setLoading]=useState(true);
  const [retry,setRetry]=useState(0);
  const [status,setStatus]=useState<{initialized:boolean;development_access:boolean}|null>(null);
  const [serviceToken,setServiceToken]=useState('');
  const [remember,setRemember]=useState(false);
  const [form]=Form.useForm();

  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);
    setError('');
    Promise.all([
      fetch('/api/v1/sso/providers',{signal:controller.signal}),
      fetch('/api/v1/auth/local/status',{signal:controller.signal}),
    ])
      .then(async ([p,s])=>{
        if(!p.ok||!s.ok) throw Error();
        const [ps,st]=await Promise.all([p.json(),s.json()]);
        if(!controller.signal.aborted){
          setProviders(ps);
          setStatus(st);
        }
      })
      .catch(()=>{
        if(!controller.signal.aborted) setError(t('登录服务暂不可用，请稍后重试'));
      })
      .finally(()=>{
        if(!controller.signal.aborted) setLoading(false);
      });
    return()=>controller.abort();
  },[retry]);

  useEffect(()=>{
    const remembered=localStorage.getItem(REMEMBERED_USER_KEY);
    if(remembered){
      form.setFieldValue('username',remembered);
      setRemember(true);
    } else if(prefillLogin) {
      form.setFieldsValue(devCredentials);
    }
  },[form]);

  const githubProvider=useMemo(
    ()=>providers.find(p=>/github/i.test(`${p.id} ${p.name}`)),
    [providers],
  );
  const [heroBefore,heroAfter]=t('Build Your AI Workforce').split('AI');

  async function local(values:{username:string;password:string}) {
    setBusy('local');
    setError('');
    try {
      const response=await fetch('/api/v1/auth/local/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(values),
      });
      const data=await response.json();
      if(!response.ok){
        setError(loginError(data.detail));
        form.setFieldValue('password','');
        return;
      }
      if(remember) localStorage.setItem(REMEMBERED_USER_KEY,values.username);
      else localStorage.removeItem(REMEMBERED_USER_KEY);
      setToken(data.access_token);
      form.resetFields();
      complete();
    } catch {
      setError(t('登录服务暂不可用，请稍后重试'));
    } finally {
      setBusy('');
    }
  }

  async function enterprise(provider:LoginProvider) {
    setBusy(provider.id);
    setError('');
    try {
      const session=await ssoLogin(provider);
      setToken(session.access_token);
      complete();
    } catch(e) {
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  }

  async function applyServiceToken() {
    const credential=serviceToken.trim();
    if(!credential) return;
    setBusy('token');
    setError('');
    try {
      const response=await fetch('/api/v1/me',{
        headers:{Authorization:'Bearer '+credential},
      });
      if(!response.ok){
        setError(t('访问凭据无效，请重新配置'));
        return;
      }
      setToken(credential);
      setServiceToken('');
      complete();
    } catch {
      setError(t('登录服务暂不可用，请稍后重试'));
    } finally {
      setBusy('');
    }
  }

  return (
    <main className="login-page">
      <div className="login-backdrop" aria-hidden="true"/>
      <div className="login-layout">
        <section className="login-brand-panel" aria-label="NexusDesk">
          <div className="login-brand-top">
            <BrandMark size="lg" subtitle={t('Build · Deploy · Empower')}/>
          </div>

          <div className="login-story">
            <h1>{heroBefore}<span>AI</span>{heroAfter}</h1>
            <p>{t('开源 · 可自托管 · 可扩展的企业 AI 运营平台')}</p>
            <div className="login-story-rule"/>
            <div className="login-features">
              {features.map((feature,index)=>(
                <div className="login-feature" key={feature.key}>
                  <span className="login-feature-icon" aria-hidden="true">{feature.icon}</span>
                  <span className="login-feature-title">{t(feature.title)}</span>
                  <span className="login-feature-caption">{t(feature.caption)}</span>
                  {index!==features.length-1&&<i className="login-feature-divider" aria-hidden="true"/>}
                </div>
              ))}
            </div>
          </div>

          <a
            className="login-brand-footer"
            href="https://github.com/GroundedCoreAI/nexusdesk"
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${t('Open Source')} · Apache 2.0`}
          >
            <GithubOutlined aria-hidden/>
            <span>{t('Open Source')}</span>
            <i/>
            <span>Apache 2.0</span>
          </a>
        </section>

        <section className="login-form-panel" aria-label={t('登录')}>
          <div className="login-language"><LanguageSelector/></div>
          <div className="login-card">
            <header className="login-card-header">
              <BrandMark size="md" showDot={false}/>
              <h2>{t('欢迎回来，请登录')}</h2>
            </header>

            {expired&&<Alert className="login-notice" type="info" showIcon title={t('登录已过期，请重新登录')}/>}
            {error&&<Alert className="login-notice" type="error" showIcon title={error} action={
              <Button type="text" size="small" onClick={()=>setRetry(v=>v+1)}>{t('重试')}</Button>
            }/>}

            <Tabs
              className="login-tabs"
              activeKey={tab}
              onChange={key=>{setTab(key);setError('');}}
              items={[
                {key:'local',label:t('账号登录')},
                {key:'enterprise',label:t('企业 SSO')},
                {key:'token',label:t('访问令牌')},
              ]}
            />

            {tab==='local'&&(
              <>
                <Form
                  form={form}
                  layout="vertical"
                  requiredMark={false}
                  initialValues={devCredentials}
                  onFinish={local}
                  disabled={!!busy}
                >
                  <Form.Item name="username" rules={[{required:true,message:t('请输入用户名或邮箱')}]}>
                    <Input
                      size="large"
                      prefix={<UserOutlined/>}
                      autoComplete="username"
                      maxLength={64}
                      placeholder={t('请输入用户名或邮箱')}
                    />
                  </Form.Item>
                  <Form.Item name="password" rules={[{required:true,message:t('请输入密码')}]}>
                    <Input.Password
                      size="large"
                      prefix={<LockOutlined/>}
                      autoComplete="current-password"
                      maxLength={128}
                      placeholder={t('请输入密码')}
                    />
                  </Form.Item>
                  <div className="login-form-options">
                    <Checkbox checked={remember} onChange={e=>setRemember(e.target.checked)}>
                      {t('记住我')}
                    </Checkbox>
                    <span className="login-no-reset">{t('账号密码由管理员分配')}</span>
                  </div>
                  <Button
                    className="login-submit"
                    type="primary"
                    block
                    htmlType="submit"
                    loading={busy==='local'}
                  >
                    {t('登录')} <ArrowRightOutlined aria-hidden/>
                  </Button>
                </Form>

                {githubProvider&&(
                  <>
                    <Divider plain>{t('或')}</Divider>
                    <Button
                      className="login-github"
                      block
                      icon={<GithubOutlined/>}
                      loading={busy===githubProvider.id}
                      disabled={!!busy}
                      onClick={()=>enterprise(githubProvider)}
                    >
                      {t('使用 GitHub 登录')}
                    </Button>
                  </>
                )}

                {status&&!status.initialized&&(
                  <Alert className="login-notice" type="info" showIcon title={t('本地管理员尚未初始化，请联系部署管理员完成设置。')}/>
                )}
              </>
            )}

            {tab==='enterprise'&&(
              <div className="login-providers">
                <p>{t('选择企业身份，安全进入工作台')}</p>
                {providers.map(provider=>(
                  <Button
                    key={provider.id}
                    block
                    icon={/github/i.test(`${provider.id} ${provider.name}`)?<GithubOutlined/>:<SafetyOutlined/>}
                    loading={busy===provider.id}
                    disabled={!!busy}
                    onClick={()=>enterprise(provider)}
                  >
                    {provider.name}<ArrowRightOutlined aria-hidden/>
                  </Button>
                ))}
                {!providers.length&&!loading&&<Alert showIcon type="info" title={t('暂未配置企业登录，请使用账号登录')}/>}
                {loading&&<Button loading block>{t('加载中')}</Button>}
              </div>
            )}

            {tab==='token'&&(
              <div className="login-token-panel">
                <p>{t('输入已签发的 Bearer 服务令牌以访问工作台')}</p>
                <Input.Password
                  size="large"
                  prefix={<KeyOutlined/>}
                  autoComplete="off"
                  value={serviceToken}
                  onChange={e=>setServiceToken(e.target.value)}
                  placeholder={t('请输入访问令牌')}
                />
                <Button
                  className="login-submit"
                  type="primary"
                  block
                  loading={busy==='token'}
                  disabled={!serviceToken.trim()||!!busy}
                  onClick={applyServiceToken}
                >
                  {t('验证并进入')} <ArrowRightOutlined aria-hidden/>
                </Button>
              </div>
            )}

            {status?.development_access&&(
              <Button className="login-development" type="link" onClick={()=>{setToken('');complete();}}>
                {t('进入本地体验')}
              </Button>
            )}

            <footer className="login-card-footer">
              <span>NexusDesk</span>
              <i/>
              <span>GroundedCoreAI</span>
            </footer>
          </div>
          <footer className="login-page-footer">NexusDesk · {t('Build · Deploy · Empower')}</footer>
        </section>
      </div>
    </main>
  );
}
