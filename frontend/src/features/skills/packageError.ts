import { useTranslation } from 'react-i18next';
import { skillErrorCode } from './api';

/**
 * Turns a package rejection into a sentence about the zip, not about HTTP.
 *
 * Every rejection is a stable code (`skill_package_missing_manifest`, ...), so
 * the mapping stays a lookup instead of a parser. An unrecognised code falls
 * back to the generic line rather than leaking a raw server detail: a new rule
 * should still be diagnosable without pretending to explain itself.
 *
 * Shared by the package card and the import entry point on the create page so
 * the same archive always reports the same thing.
 */
export function usePackageErrorMessage(): (error: unknown) => string {
  const { t } = useTranslation();
  return (error: unknown) => {
    const code = skillErrorCode(error);
    if (!code) return t('skill.package.error.generic');
    const key = `skill.package.error.${code}`;
    const label = t(key);
    return label === key ? t('skill.package.error.generic') : label;
  };
}

/** Client-side mirror of the server's archive ceiling, checked before upload. */
export const MAX_PACKAGE_BYTES = 50 * 1024 * 1024;
