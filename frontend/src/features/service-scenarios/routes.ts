export const DEFAULT_APP_KEY = 'consumer-service';
export const DEFAULT_SCENARIO_KEY = 'query-orders';

const appBasePattern = /^(\/service-apps\/[a-z0-9-]+)/;
const scenarioBasePattern = /^(\/service-apps\/[a-z0-9-]+\/scenarios\/[a-z][a-z0-9_-]{0,63})/;

export function appBasePath(route: string) {
    return route.match(appBasePattern)?.[1] || `/service-apps/${DEFAULT_APP_KEY}`;
}

export function scenarioBasePath(route: string) {
    return route.match(scenarioBasePattern)?.[1]
        || `${appBasePath(route)}/scenarios/${DEFAULT_SCENARIO_KEY}`;
}

export function scenarioKeyFromPath(route: string) {
    return route.match(/^\/service-apps\/[a-z0-9-]+\/scenarios\/([a-z][a-z0-9_-]{0,63})(?:\/|$)/)?.[1]
        || DEFAULT_SCENARIO_KEY;
}

export function experienceBasePath(route: string) {
    return `${appBasePath(route)}/experience`;
}
