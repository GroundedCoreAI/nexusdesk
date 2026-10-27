/** Stable UI extension types shared by the application shell and capabilities. */

export type ExtensionKind = 'tools' | 'policies' | 'events' | 'routes' | 'ui';

export interface UiNavigationItem {
  id: string;
  labelKey: string;
  path: `/${string}`;
  icon: string;
  group: string;
  requiredPermissions?: readonly string[];
  requiredCapability?: string;
  order?: number;
}

export interface UiRouteContribution {
  id: string;
  path: `/${string}`;
  feature: string;
  requiredPermissions?: readonly string[];
  requiredCapability?: string;
}

export interface UiExtensionManifest {
  extensionId: string;
  version: string;
  apiVersion?: string;
  requiresPlatform?: string | null;
  navigation: readonly UiNavigationItem[];
  routes: readonly UiRouteContribution[];
}
