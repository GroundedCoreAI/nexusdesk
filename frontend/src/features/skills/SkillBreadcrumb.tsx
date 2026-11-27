import { Button } from 'antd';
import { HomeOutlined, RightOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

interface SkillBreadcrumbProps {
  current: string;
  onOpenCatalog: () => void;
}

export function SkillBreadcrumb({ current, onOpenCatalog }: SkillBreadcrumbProps) {
  const { t } = useTranslation();
  return (
    <nav className="skill-breadcrumb" aria-label={t('面包屑导航')}>
      <Button type="text" icon={<HomeOutlined />} aria-label={t('返回 Skill 能力库')} onClick={onOpenCatalog} />
      <RightOutlined aria-hidden="true" />
      <button type="button" onClick={onOpenCatalog}>{t('资源中心')}</button>
      <RightOutlined aria-hidden="true" />
      <button type="button" onClick={onOpenCatalog}>{t('Skill 能力库')}</button>
      <RightOutlined aria-hidden="true" />
      <span aria-current="page">{t(current)}</span>
    </nav>
  );
}
